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
    logger.info("products event: %s", json.dumps(event))

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


@_register("analyse_spending")
def _analyse_spending(params: dict) -> dict:
    source_type      = str(params.get("source_type", "current_account"))
    ref_last_four    = str(params.get("source_ref_last_four", "****"))
    period           = str(params.get("period", "last_2_months"))
    category_filter  = str(params.get("category_filter", ""))
    return {
        "source_type": source_type,
        "source_ref_last_four": ref_last_four,
        "period": period,
        "total_spent": 1847.32,
        "category_filter": category_filter or "all",
        "top_categories": [
            {"category": "groceries",   "total": 423.50, "transactions": 12},
            {"category": "eating_out",  "total": 187.20, "transactions": 8},
            {"category": "utilities",   "total": 145.00, "transactions": 2},
        ],
        "transactions": [
            {"date": "2026-03-31", "merchant": "TESCO",   "category": "groceries",    "amount": -42.50},
            {"date": "2026-03-30", "merchant": "COSTA",   "category": "eating_out",   "amount": -4.20},
            {"date": "2026-03-29", "merchant": "NETFLIX", "category": "entertainment","amount": -17.99},
        ],
    }
