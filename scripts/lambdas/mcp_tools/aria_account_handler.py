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

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_MOCK_ACCOUNTS: dict[str, dict] = {
    "CUST-001": {
        "current": {
            "account_number": "12344521",
            "sort_code": "20-45-67",
            "account_type": "current",
            "account_name": "Meridian Select",
            "available_balance": 1245.30,
            "cleared_balance": 1300.00,
            "currency": "GBP",
        },
        "savings": {
            "account_number": "98767832",
            "sort_code": "20-45-67",
            "account_type": "savings",
            "account_name": "Meridian Instant Access",
            "available_balance": 4200.00,
            "cleared_balance": 4200.00,
            "currency": "GBP",
        },
    },
    "CUST-002": {
        "current": {
            "account_number": "56781234",
            "sort_code": "20-45-67",
            "account_type": "current",
            "account_name": "Meridian Classic",
            "available_balance": 892.15,
            "cleared_balance": 950.00,
            "currency": "GBP",
        },
    },
}

_MOCK_TRANSACTIONS: dict[str, list] = {
    "CUST-001": [
        {"date": "2026-03-27", "description": "TESCO STORES", "amount": -42.50, "type": "debit", "balance": 1245.30},
        {"date": "2026-03-26", "description": "SALARY MERIDIAN CORP", "amount": 3200.00, "type": "credit", "balance": 1287.80},
        {"date": "2026-03-25", "description": "AMAZON.CO.UK", "amount": -89.99, "type": "debit", "balance": -1912.20},
        {"date": "2026-03-24", "description": "DIRECT DEBIT - EDF ENERGY", "amount": -75.00, "type": "debit", "balance": -1822.21},
        {"date": "2026-03-23", "description": "CONTACTLESS - COSTA COFFEE", "amount": -4.50, "type": "debit", "balance": -1747.21},
        {"date": "2026-03-22", "description": "TRANSFER FROM SAVINGS", "amount": 500.00, "type": "credit", "balance": -1742.71},
        {"date": "2026-03-21", "description": "NETFLIX.COM", "amount": -10.99, "type": "debit", "balance": -2242.71},
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
    logger.info("account event: %s", json.dumps(event))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "get_account_balance":
        return _get_account_balance(params)
    if tool_name == "get_recent_transactions":
        return _get_recent_transactions(params)
    if tool_name == "get_account_details":
        return _get_account_details(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_account_balance(params: dict) -> dict:
    customer_id = str(params.get("customer_id", "")).strip()
    account_type = str(params.get("account_type", "current")).strip().lower()

    accounts = _MOCK_ACCOUNTS.get(customer_id, {})
    acct = accounts.get(account_type) or next(iter(accounts.values()), None)
    if not acct:
        return {"error": "Account not found", "customer_id": customer_id}

    return {
        "customer_id": customer_id,
        "account_type": acct["account_type"],
        "account_name": acct["account_name"],
        "available_balance": acct["available_balance"],
        "cleared_balance": acct["cleared_balance"],
        "currency": acct["currency"],
        "account_number_last_four": acct["account_number"][-4:],
    }


def _get_recent_transactions(params: dict) -> dict:
    customer_id = str(params.get("customer_id", "")).strip()
    account_type = str(params.get("account_type", "current")).strip().lower()
    limit = int(params.get("limit", 5))

    txns = _MOCK_TRANSACTIONS.get(customer_id, [])
    if account_type == "savings":
        txns = [t for t in txns if t.get("type") == "credit"]

    return {
        "customer_id": customer_id,
        "account_type": account_type,
        "transactions": txns[:limit],
        "total_returned": min(limit, len(txns)),
    }


def _get_account_details(params: dict) -> dict:
    customer_id = str(params.get("customer_id", "")).strip()
    account_type = str(params.get("account_type", "current")).strip().lower()

    accounts = _MOCK_ACCOUNTS.get(customer_id, {})
    acct = accounts.get(account_type) or next(iter(accounts.values()), None)
    if not acct:
        return {"error": "Account not found", "customer_id": customer_id}

    return {
        "customer_id": customer_id,
        "account_number_last_four": acct["account_number"][-4:],
        "sort_code": acct["sort_code"],
        "account_type": acct["account_type"],
        "account_name": acct["account_name"],
        "currency": acct["currency"],
    }

