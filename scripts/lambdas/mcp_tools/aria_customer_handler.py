"""
Lambda handler: ARIA Customer Profile Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - get_customer_profile — returns customer name, accounts, cards, and products
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_MOCK_PROFILES: dict[str, dict] = {
    "CUST-001": {
        "name": "James",
        "accounts": [
            {"type": "current", "nickname": "Main Account", "number_last_four": "4521"},
            {"type": "savings", "nickname": "Holiday Savings", "number_last_four": "7832"},
        ],
        "debit_cards": [{"nickname": "Everyday Debit", "last_four": "8901"}],
        "credit_cards": [{"nickname": "Rewards Credit Card", "last_four": "3456"}],
        "has_mortgage": True,
    },
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

    return {"error": f"Unknown tool: {tool_name}"}
