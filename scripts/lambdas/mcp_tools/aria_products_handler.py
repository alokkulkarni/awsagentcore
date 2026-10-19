"""
Lambda handler: ARIA Products & Analytics Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - get_product_catalogue  — current accounts, savings, credit cards catalogue
  - analyse_spending       — spending breakdown by category and period
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# The sample bank's one copy of its data (connect-money-hub/moneyhub/data.py, packaged with this handler), so
# spending here is the Money Hub's spending.
from moneyhub import data as bank  # noqa: E402

DOMAIN = "products"

_DISPATCH = {}


def _register(name):
    def decorator(fn):
        _DISPATCH[name] = fn
        return fn
    return decorator



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
    logger.info("products event: %s", json.dumps(_redact_event(event)))

    tool_name, params = _parse_tool_call(event, context)

    # Parse stringified inputs if needed
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            params = {}

    handler_fn = _DISPATCH.get(tool_name)
    if not handler_fn:
        logger.warning("Unknown tool: %s (domain=%s)", tool_name, DOMAIN)
        return {
            "result": {
                "error": f"Tool '{tool_name}' not found in domain '{DOMAIN}'",
                "available_tools": list(_DISPATCH.keys()),
            }
        }

    try:
        return {"result": handler_fn(params)}
    except Exception as exc:
        logger.exception("Tool %s raised an exception", tool_name)
        return {"result": {"error": str(exc), "tool": tool_name}}


@_register("get_product_catalogue")
def _get_product_catalogue(params: dict) -> dict:
    category = str(params.get("product_category", "current_accounts"))
    catalogue = {
        "current_accounts": [
            {
                "name": "Meridian Select",
                "tagline": "Everyday banking, rewarding you more",
                "features": ["0% arranged overdraft up to £500", "1% cashback on bills", "24/7 mobile app"],
            },
            {
                "name": "Meridian Classic",
                "tagline": "Simple, reliable banking",
                "features": ["No monthly fee", "Debit card included", "Online and mobile banking"],
            },
        ],
        "savings": [
            {
                "name": "Meridian Instant Access",
                "tagline": "Save today, access whenever",
                "features": ["4.20% AER variable", "No notice period", "Linked to your current account"],
            }
        ],
        "credit_cards": [
            {
                "name": "Meridian Rewards Visa",
                "tagline": "Every purchase earns you more",
                "features": ["1.5% cashback", "No foreign transaction fee", "0% for 12 months on purchases"],
            }
        ],
    }
    return {"category": category, "products": catalogue.get(category, [])}


_PERIOD_DAYS = {"last_week": 7, "last_month": 31, "last_2_months": 62, "last_3_months": 92, "last_6_months": 183}


@_register("analyse_spending")
def _analyse_spending(params: dict) -> dict:
    source_type      = str(params.get("source_type", "current_account"))
    ref_last_four    = str(params.get("source_ref_last_four", "")).strip()
    period           = str(params.get("period", "last_2_months"))
    category_filter  = str(params.get("category_filter", "")).strip().lower()
    customer_id      = str(params.get("customer_id", "")).strip()
    if not customer_id:
        return {"error": "customer_id is required"}
    # Only the customer's own account or card: naming another customer's digits finds nothing.
    item = bank.held_by(customer_id, ref_last_four) if ref_last_four else bank.account(customer_id, "current")
    if not item:
        return {"error": "No account or card of this customer's has that ending", "source_ref_last_four": ref_last_four}
    if item.get("type") == "credit":
        rows = [{"date": t["date"], "merchant": t["merchant"], "category": "card_payment", "amount": -t["amount"]}
                for t in bank.card_payments(customer_id, "credit")]
    elif item.get("type") == "debit":
        rows = [{"date": t["date"], "merchant": t["merchant"], "category": "card_payment", "amount": -t["amount"]}
                for t in bank.card_payments(customer_id, "debit")]
    else:
        rows = bank.current_account_transactions(customer_id)
    since = (bank.as_of() - __import__("datetime").timedelta(days=_PERIOD_DAYS.get(period, 62))).isoformat()
    spent = [t for t in rows if t["amount"] < 0 and t["date"] > since
             and t.get("category") not in ("savings", "transfers_out")
             and (not category_filter or t.get("category") == category_filter)]
    totals: dict[str, list] = {}
    for t in spent:
        totals.setdefault(t["category"], []).append(-t["amount"])
    top = sorted(({"category": c, "total": round(sum(v), 2), "transactions": len(v)} for c, v in totals.items()),
                 key=lambda x: x["total"], reverse=True)
    return {
        "source_type": source_type,
        "source_ref_last_four": ref_last_four,
        "period": period,
        "from": since,
        "to": bank.as_of().isoformat(),
        "total_spent": round(sum(-t["amount"] for t in spent), 2),
        "category_filter": category_filter or "all",
        "top_categories": top[:5],
        "transactions": [{"date": t["date"], "merchant": t["merchant"], "category": t["category"], "amount": t["amount"]}
                         for t in spent[:10]],
    }
