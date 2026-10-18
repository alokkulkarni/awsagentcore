"""
Lambda handler: ARIA Mortgage Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - get_mortgage_details — balance, payment, rate, remaining term
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# The sample bank's one copy of its data (connect-money-hub/moneyhub/data.py, packaged with this handler), so
# ARIA sees the same mortgages and payments as the Money Hub, the card dispute assistant and internet banking.
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
    logger.info("mortgage event: %s", json.dumps(_redact_event(event)))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "get_mortgage_details":
        return _get_mortgage_details(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_mortgage_details(params: dict) -> dict:
    reference = str(params.get("mortgage_reference", "")).strip()
    customer_id = str(params.get("customer_id", "")).strip()
    if not customer_id:
        return {"error": "customer_id is required"}
    # Only the customer's own mortgage. A reference (masked, MR-****-8842) must be theirs if one is given.
    held = bank.mortgage(customer_id)
    if not held or (any(ch.isdigit() for ch in reference) and bank.mortgage_owner(reference) != customer_id):
        return {"error": "Mortgage not found", "mortgage_reference": reference}
    return {
        "customer_id": customer_id,
        "mortgage_reference": bank.mortgage_reference(customer_id),
        "outstanding_balance": held["outstandingBalance"],
        "monthly_payment": held["monthlyPayment"],
        "interest_rate": held["interestRate"],
        "rate_type": held["rateType"],
        "rate_expiry_date": held["rateExpiryDate"],
        "term_remaining_years": held["termRemainingYears"],
        "next_payment_date": held["nextPaymentDate"],
        "currency": "GBP",
        "property_address_masked": held["propertyMasked"],
    }
