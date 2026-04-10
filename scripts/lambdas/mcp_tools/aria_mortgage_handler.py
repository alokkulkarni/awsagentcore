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
    logger.info("mortgage event: %s", json.dumps(event))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "get_mortgage_details":
        return _get_mortgage_details(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_mortgage_details(params: dict) -> dict:
    return {
        "customer_id": params.get("customer_id"),
        "outstanding_balance": 210500.00,
        "monthly_payment": 1245.00,
        "interest_rate": 4.25,
        "rate_type": "fixed",
        "rate_expiry_date": "2027-06-30",
        "term_remaining_years": 18,
        "next_payment_date": "2026-04-01",
        "currency": "GBP",
        "property_address_masked": "** Oak Street, Altrincham",
    }
