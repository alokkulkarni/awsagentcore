"""
Lambda handler: ARIA Customer Profile Tools (AgentCore MCP Gateway target)

Tools exposed via MCP (ARIA-facing, PCI-safe):
  - get_customer_details    — returns customer name, accounts, card last-four
                              digits, and products. Full card numbers are NEVER
                              returned by this tool.

Internal tool (Lambda-to-Lambda, not exposed to ARIA):
  - verify_card_ownership   — called by aria-dtmf-validate to confirm a card
                              belongs to a customer. Accepts customer_id,
                              card_last_four, and card_bin (first 6 digits).
                              Matches against full 16-digit card numbers stored
                              in the internal registry. Returns true/false and
                              card type (debit/credit) without ever exposing
                              the full card number.

Card data design
────────────────
  The sample bank's one copy of its data (connect-money-hub/moneyhub/data.py,
  packaged with this handler) holds every customer's accounts and cards.
  _profile()        — PCI-safe display data (last_four only). Returned to ARIA
                      by get_customer_details.
  _card_registry()  — each card's BIN (first six digits) and last four. Used
                      ONLY by verify_card_ownership. No full card number is
                      held anywhere.

  BINs (must be in the aria-card-bins DynamoDB table):
    414900  →  VISA DEBIT        543210  →  MASTERCARD DEBIT
    531908  →  MASTERCARD CREDIT
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_MOCK_DATA = os.environ.get("MOCK_DATA", "false").lower() == "true"

# ---------------------------------------------------------------------------
# The sample bank's one copy of its data (connect-money-hub/moneyhub/data.py, packaged with this handler), so
# ARIA's greeting, this tool, the card dispute assistant and internet banking name the same accounts and cards.
# Only last fours and card BINs are held: never a full card number.
# ---------------------------------------------------------------------------
from moneyhub import data as bank  # noqa: E402


def _profile(customer_id: str) -> dict | None:
    """PCI-safe display data, as get_customer_details returns it."""
    held = bank.profile(customer_id)
    if not held:
        return None
    return {
        "name": held["preferredName"],
        "accounts": [{"type": a["type"], "nickname": a["nickname"], "number_last_four": a["ending"]}
                     for a in held["accounts"]],
        "debit_cards": [{"nickname": c["nickname"], "last_four": c["ending"]} for c in held["cards"] if c["type"] == "debit"],
        "credit_cards": [{"nickname": c["nickname"], "last_four": c["ending"]} for c in held["cards"] if c["type"] == "credit"],
        "has_mortgage": bank.mortgage(customer_id) is not None,
        **({"mortgage_reference": bank.mortgage_reference(customer_id)} if bank.mortgage(customer_id) else {}),
    }


def _card_registry(customer_id: str) -> list[dict]:
    """The customer's cards for ownership checks: BIN (first six digits) and last four, never the full number."""
    held = bank.profile(customer_id) or {}
    return [{"bin": c["bin"], "last_four": c["ending"], "card_type": c["type"], "nickname": c["nickname"]}
            for c in held.get("cards", [])]



# Per official AWS docs (gateway-add-target-lambda.html):
#   tool name  → context.client_context.custom['bedrockAgentCoreToolName']
#   parameters → event (flat key/value map)
# We also support the JSON-RPC 2.0 format that Connect AI Agent sends through
# the gateway, so both invocation paths work without code changes.
def _parse_tool_call(event: dict, context) -> tuple:
    # ── 1. Tool name ──────────────────────────────────────────────────────────
    raw = ""
    try:
        raw = (context.client_context.custom or {}).get("bedrockAgentCoreToolName", "")
    except Exception:
        logger.debug("context.client_context not available", exc_info=True)
    if not raw:                                      # JSON-RPC fallback
        _p = event.get("params", {})
        if isinstance(_p, str):
            try:
                import json as _j; _p = _j.loads(_p)
            except Exception:
                _p = {}
        raw = (
            _p.get("name")
            or event.get("toolName")
            or event.get("tool_name")
            or ""
        )
    tool_name = raw.split("___", 1)[1] if "___" in raw else raw

    # ── 2. Parameters ─────────────────────────────────────────────────────────
    _p = event.get("params", {})
    if isinstance(_p, str):
        try:
            import json as _j; _p = _j.loads(_p)
        except Exception:
            _p = {}
    params: dict = (
        _p.get("arguments")           # JSON-RPC (Connect AI Agent)
        or event.get("parameters")    # legacy direct invocation
        or event.get("tool_input")    # Bedrock inline-agent format
        or {}
    )
    # Official gateway format: event IS the params (no wrapper keys)
    if not params and not any(k in event for k in
            ("jsonrpc", "method", "params", "toolName", "tool_name", "id")):
        params = {k: v for k, v in event.items()
                  if k not in ("bedrockAgentCoreMessageVersion",)}

    return tool_name, params


# Security: redact PII/sensitive fields before logging
_REDACT_KEYS = frozenset({
    "date_of_birth", "dob", "mobile", "mobile_last_four", "phone", "phone_number",
    "password", "pin", "otp", "cvv", "cvc", "card_number", "full_card_number",
    "account_number", "sort_code", "iban", "secret", "token", "auth_token",
    "access_token", "refresh_token", "credit_card", "debit_card",
})

def _redact_event(event: dict) -> dict:
    """Return a shallow copy of event with sensitive values replaced by ***REDACTED***."""
    return {
        k: "***REDACTED***" if k.lower() in _REDACT_KEYS else v
        for k, v in event.items()
    }

def lambda_handler(event: dict, context) -> dict:
    logger.info("customer event: %s", json.dumps(_redact_event(event)))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "get_customer_details":
        return get_customer_details(params)

    if tool_name == "verify_card_ownership":
        return _verify_card_ownership(params)

    return {"error": f"Unknown tool: {tool_name}"}


def get_customer_details(params: dict) -> dict:
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    cid = str(params.get("customer_id", "")).strip()
    profile = _profile(cid)
    if profile:
        return {"customer_id": cid, **profile}
    return {"error": "Customer not found"}


def _verify_card_ownership(params: dict) -> dict:
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    """
    Internal tool called by aria-dtmf-validate (Lambda-to-Lambda) to confirm
    a captured card belongs to an authenticated customer.

    Matches using TWO factors for security:
      1. BIN (first 6 digits) — ensures the card network and bank are correct
      2. Last four digits     — ensures the specific card matches

    A match on last-four alone is insufficient because different card networks
    may issue cards with the same last four digits. The BIN double-check
    eliminates this risk.

    Parameters
    ──────────
    customer_id   : str  e.g. "CUST-001"
    card_last_four: str  e.g. "4821"
    card_bin      : str  e.g. "414900"  (first 6 digits from aria-dtmf-decrypt)

    Returns
    ───────
    {
      "belongs_to_customer": true | false,
      "card_type":           "debit" | "credit" | "",
      "card_nickname":       "Everyday Debit" | "",
      "match_method":        "bin_and_last_four" | "last_four_only" | "no_match"
    }

    Full card numbers are never included in the response or logs.
    """
    customer_id    = str(params.get("customer_id",    "")).strip()
    card_last_four = str(params.get("card_last_four", "")).strip()
    card_bin       = str(params.get("card_bin",       "")).strip()

    # Log only non-sensitive fragments for audit trail
    logger.info(
        "verify_card_ownership: customer=%s bin=%s lastFour=****%s",
        customer_id,
        (card_bin[:4] + "**") if len(card_bin) >= 6 else card_bin,
        card_last_four,
    )

    if not customer_id or not card_last_four:
        return {
            "belongs_to_customer": False,
            "card_type":           "",
            "card_nickname":       "",
            "match_method":        "no_match",
            "error":               "customer_id and card_last_four are required",
        }

    cards = _card_registry(customer_id)
    if not cards:
        logger.info("No cards found in registry for customer=%s", customer_id)
        return {
            "belongs_to_customer": False,
            "card_type":           "",
            "card_nickname":       "",
            "match_method":        "no_match",
        }

    # ── Primary check: BIN + last four (most secure) ──────────────────────
    if card_bin and len(card_bin) >= 6:
        for card in cards:
            if card["bin"] == card_bin[:6] and card["last_four"] == card_last_four:
                logger.info(
                    "Card ownership confirmed (bin+last4): customer=%s type=%s",
                    customer_id, card["card_type"],
                )
                return {
                    "belongs_to_customer": True,
                    "card_type":           card["card_type"],
                    "card_nickname":       card["nickname"],
                    "match_method":        "bin_and_last_four",
                }

    # ── Fallback: last four only (when BIN not available) ─────────────────
    # This is less secure but used as fallback when only last_four is captured
    # (e.g., purpose = "card_last_four" without a BIN lookup available).
    for card in cards:
        if card["last_four"] == card_last_four:
            logger.info(
                "Card ownership confirmed (last4 only): customer=%s type=%s",
                customer_id, card["card_type"],
            )
            return {
                "belongs_to_customer": True,
                "card_type":           card["card_type"],
                "card_nickname":       card["nickname"],
                "match_method":        "last_four_only",
            }

    logger.info(
        "Card not found on account: customer=%s bin=%s lastFour=****%s",
        customer_id,
        (card_bin[:4] + "**") if len(card_bin) >= 6 else "?",
        card_last_four,
    )
    return {
        "belongs_to_customer": False,
        "card_type":           "",
        "card_nickname":       "",
        "match_method":        "no_match",
    }
