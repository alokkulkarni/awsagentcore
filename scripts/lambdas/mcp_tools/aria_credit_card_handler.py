"""
Lambda handler: ARIA Credit Card Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - get_credit_card_details — balance, limit, minimum payment, transactions
  - block_credit_card       — blocks a credit card (lost or stolen)
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# The sample bank's one copy of its data (connect-money-hub/moneyhub/data.py, packaged with this handler), so
# ARIA sees the same cards and payments as the Money Hub, the card dispute assistant and internet banking.
from moneyhub import data as bank  # noqa: E402



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
    logger.info("credit_card event: %s", json.dumps(_redact_event(event)))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "get_credit_card_details":
        return _get_credit_card_details(params)
    elif tool_name == "block_credit_card":
        return _block_credit_card(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_credit_card_details(params: dict) -> dict:
    customer_id = str(params.get("customer_id", "")).strip()
    card_last_four = str(params.get("card_last_four", "")).strip()
    query_subtype = str(params.get("query_subtype", "status"))
    if not customer_id:
        return {"error": "customer_id is required"}
    # Only the customer's own card: naming another customer's digits finds nothing.
    held = bank.held_by(customer_id, card_last_four)
    card = bank.credit_card(customer_id) if held and held.get("type") == "credit" else None
    if not card:
        return {"error": "Credit card not found", "card_last_four": card_last_four}
    result: dict = {
        "card_last_four": card["ending"],
        "card_type": card["nickname"],
        "card_scheme": card["scheme"],
        "card_status": "active",
        "credit_limit": card["limit"],
        "available_credit": card["available"],
        "outstanding_balance": card["balance"],
        "minimum_payment": card["minimumPayment"],
        "next_payment_date": card["nextPaymentDate"],
        "expiry_masked": "**/**",
        "query_subtype": query_subtype,
        "as_of": bank.as_of().isoformat(),
    }
    if query_subtype == "transactions":
        result["recent_transactions"] = [
            {"date": t["date"], "description": t["merchant"], "amount": -t["amount"], "transaction_id": t["transactionId"]}
            for t in bank.card_payments(customer_id, "credit")
        ]
    return result


def _block_credit_card(params: dict) -> dict:
    card_last_four = str(params.get("card_last_four", "****"))
    reason = str(params.get("reason", "lost_stolen"))
    ref = f"CC-BLOCK-{card_last_four}-{uuid.uuid4().hex[:6].upper()}"
    return {
        "blocked": True,
        "card_last_four": card_last_four,
        "reason": reason,
        "reference": ref,
        "message": (
            f"Your credit card ending {card_last_four} has been blocked. "
            "A replacement card will be sent to your registered address within 3-5 working days."
        ),
    }
