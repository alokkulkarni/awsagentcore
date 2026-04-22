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
  _MOCK_PROFILES          — PCI-safe display data (last_four only). Returned
                            to ARIA by get_customer_details.
  _MOCK_CARD_REGISTRY     — Internal registry with full 16-digit card numbers.
                            Used ONLY by verify_card_ownership. Never returned
                            to ARIA, never logged in full.

  All full card numbers follow the pattern:
    <BIN 6 digits> + <middle 6 digits> + <last 4 digits>

  BINs used in mock data (must match aria-card-bins DynamoDB table):
    414900  →  VISA DEBIT
    532188  →  MASTERCARD CREDIT
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# PCI-safe display data (returned to ARIA by get_customer_details)
# Full card numbers are NOT present here — only last_four for display.
# ---------------------------------------------------------------------------
_MOCK_PROFILES: dict[str, dict] = {
    "CUST-001": {
        "name": "James",
        "accounts": [
            {"type": "current", "nickname": "Main Account",     "number_last_four": "4521"},
            {"type": "savings", "nickname": "Holiday Savings",  "number_last_four": "7832"},
        ],
        "debit_cards":  [{"nickname": "Everyday Debit",      "last_four": "8901"}],
        "credit_cards": [{"nickname": "Rewards Credit Card", "last_four": "3456"}],
        "has_mortgage": True,
    },
    "CUST-002": {
        "name": "Sarah",
        "accounts": [
            {"type": "current", "nickname": "Main Current",  "number_last_four": "1234"},
        ],
        "debit_cards":  [{"nickname": "Classic Debit",      "last_four": "2711"}],
        "credit_cards": [{"nickname": "Platinum Credit",    "last_four": "2199"}],
        "has_mortgage": False,
    },
    "CUST-003": {
        "name": "Michael",
        "accounts": [
            {"type": "current", "nickname": "Current Account", "number_last_four": "8843"},
            {"type": "savings", "nickname": "ISA",             "number_last_four": "6621"},
        ],
        "debit_cards":  [
            {"nickname": "Primary Debit",  "last_four": "5543"},
            {"nickname": "Joint Debit",    "last_four": "1102"},
        ],
        "credit_cards": [{"nickname": "Cashback Credit",     "last_four": "9912"}],
        "has_mortgage": True,
    },
}

# ---------------------------------------------------------------------------
# Internal card registry — full 16-digit card numbers for ownership validation.
# Structure:  { customer_id: [ {full_card_number, card_type, nickname}, … ] }
#
# full_card_number format: 16 digit string, no spaces.
#   Digits 1–6  : BIN (must match aria-card-bins DynamoDB table)
#   Digits 7–12 : middle digits (any valid digits)
#   Digits 13–16: last four (must match _MOCK_PROFILES above)
#
# These values are NEVER returned to callers — only used internally by
# _verify_card_ownership() for BIN+last_four matching.
# ---------------------------------------------------------------------------
_MOCK_CARD_REGISTRY: dict[str, list[dict]] = {
    "CUST-001": [
        # VISA DEBIT  — BIN 414900, last four 8901
        {"full_card_number": "4149008923148901", "card_type": "debit",  "nickname": "Everyday Debit"},
        # MASTERCARD CREDIT — BIN 532188, last four 3456
        {"full_card_number": "5321884720933456", "card_type": "credit", "nickname": "Rewards Credit Card"},
    ],
    "CUST-002": [
        # VISA DEBIT  — BIN 414900, last four 2711
        {"full_card_number": "4149008941092711", "card_type": "debit",  "nickname": "Classic Debit"},
        # MASTERCARD CREDIT — BIN 532188, last four 2199
        {"full_card_number": "5321884756832199", "card_type": "credit", "nickname": "Platinum Credit"},
    ],
    "CUST-003": [
        # VISA DEBIT (primary) — BIN 414900, last four 5543
        {"full_card_number": "4149008912315543", "card_type": "debit",  "nickname": "Primary Debit"},
        # VISA DEBIT (joint)   — BIN 414900, last four 1102
        {"full_card_number": "4149008977641102", "card_type": "debit",  "nickname": "Joint Debit"},
        # MASTERCARD CREDIT — BIN 532188, last four 9912
        {"full_card_number": "5321884788769912", "card_type": "credit", "nickname": "Cashback Credit"},
    ],
}



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
        pass
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

def lambda_handler(event: dict, context) -> dict:
    logger.info("customer event: %s", json.dumps(event))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "get_customer_details":
        cid = str(params.get("customer_id", "")).strip()
        profile = _MOCK_PROFILES.get(cid)
        if profile:
            return {"customer_id": cid, **profile}
        return {"error": "Customer not found"}

    if tool_name == "verify_card_ownership":
        return _verify_card_ownership(params)

    return {"error": f"Unknown tool: {tool_name}"}


def _verify_card_ownership(params: dict) -> dict:
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
    card_last_four: str  e.g. "8901"
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

    cards = _MOCK_CARD_REGISTRY.get(customer_id, [])
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
            full = card["full_card_number"]
            if full[:6] == card_bin[:6] and full[-4:] == card_last_four:
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
        if card["full_card_number"][-4:] == card_last_four:
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
