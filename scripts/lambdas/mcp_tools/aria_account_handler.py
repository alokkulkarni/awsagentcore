"""
Lambda handler: ARIA Account Tools (AgentCore MCP Gateway target)

Tools exposed via MCP (matches deployed gateway schema):
  - get_account_balance      — current and available balance for a customer's account
  - get_recent_transactions  — recent transactions for a customer's account
  - get_account_details      — sort code, account number, and account type
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_MOCK_DATA = os.environ.get("MOCK_DATA", "false").lower() == "true"

# The sample bank's one copy of its data (connect-money-hub/moneyhub/data.py, packaged with this handler), so
# ARIA sees the same accounts and payments as the Money Hub, the card dispute assistant and internet banking.
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
    logger.info("account event: %s", json.dumps(_redact_event(event)))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "get_account_balance":
        return _get_account_balance(params)
    if tool_name == "get_recent_transactions":
        return _get_recent_transactions(params)
    if tool_name == "get_account_details":
        return _get_account_details(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _account(params: dict) -> tuple[str, str, dict | None]:
    customer_id = str(params.get("customer_id", "")).strip()
    account_type = str(params.get("account_type", "current")).strip().lower() or "current"
    acct = bank.account(customer_id, account_type) or bank.account(customer_id, "current")
    return customer_id, account_type, acct


def _get_account_balance(params: dict) -> dict:
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    customer_id, _, acct = _account(params)
    if not acct:
        return {"error": "Account not found", "customer_id": customer_id}

    return {
        "customer_id": customer_id,
        "account_type": acct["type"],
        "account_name": acct["name"],
        "available_balance": acct["balance"],
        "cleared_balance": acct["balance"],
        "currency": "GBP",
        "account_number_last_four": acct["ending"],
        "as_of": bank.as_of().isoformat(),
    }


def _get_recent_transactions(params: dict) -> dict:
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    customer_id, _, acct = _account(params)
    if not acct:
        return {"error": "Account not found", "customer_id": customer_id}
    try:
        limit = max(1, min(int(params.get("limit", 5) or 5), 50))
    except (TypeError, ValueError):
        limit = 5

    rows = bank.savings_transactions(customer_id) if acct["type"] == "savings" \
        else bank.current_account_transactions(customer_id)
    txns = [{"date": t["date"], "description": t["merchant"], "amount": t["amount"],
             "type": "credit" if t["amount"] > 0 else "debit",
             **({"balance": t["balanceAfter"]} if "balanceAfter" in t else {})} for t in rows[:limit]]
    return {
        "customer_id": customer_id,
        "account_type": acct["type"],
        "account_number_last_four": acct["ending"],
        "transactions": txns,
        "total_returned": len(txns),
    }


def _get_account_details(params: dict) -> dict:
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    customer_id, _, acct = _account(params)
    if not acct:
        return {"error": "Account not found", "customer_id": customer_id}

    return {
        "customer_id": customer_id,
        "account_number_last_four": acct["ending"],
        "sort_code": bank.SORT_CODE,
        "account_type": acct["type"],
        "account_name": acct["name"],
        "nickname": acct["nickname"],
        "currency": "GBP",
    }
