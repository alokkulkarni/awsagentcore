"""
Lambda handler: ARIA Knowledge Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - search_knowledge_base  — search KB articles for customer queries
  - get_feature_parity     — check which features are available on which channels
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DOMAIN = "knowledge"

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
    logger.info("knowledge event: %s", json.dumps(_redact_event(event)))

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


@_register("search_knowledge_base")
def _search_knowledge_base(params: dict) -> dict:
    query    = str(params.get("query", ""))
    category = str(params.get("category", ""))

    # TODO: Replace with Amazon Bedrock Knowledge Base API call
    results = [
        {
            "title":           "How to block a lost or stolen card",
            "content":         (
                "You can block your card immediately by calling 0161 900 9000 "
                "or through the Meridian Bank mobile app. "
                "A replacement card will arrive within 5-7 working days."
            ),
            "category":        "cards",
            "relevance_score": 0.92,
        },
        {
            "title":           "Account statement access",
            "content":         (
                "Statements are available to download in PDF format from online "
                "banking or the mobile app. Paper statements are sent monthly."
            ),
            "category":        "accounts",
            "relevance_score": 0.78,
        },
        {
            "title":           "How to set up a standing order",
            "content":         (
                "Standing orders can be set up through online banking, the mobile app, "
                "or by calling 0161 900 9000."
            ),
            "category":        "payments",
            "relevance_score": 0.71,
        },
    ]

    # Simple category filter if provided
    if category:
        results = [r for r in results if r.get("category") == category]

    return {"query": query, "results": results, "total_results": len(results)}


@_register("get_feature_parity")
def _get_feature_parity(params: dict) -> dict:
    feature_area = str(params.get("feature_area", ""))

    # TODO: Replace with feature registry API call
    return {
        "feature_area":       feature_area,
        "available_channels": ["voice", "chat", "mobile", "web"],
        "channel_notes": {
            "voice":  "Full self-service available via ARIA",
            "chat":   "Full self-service available via ARIA",
            "mobile": "Available in the Meridian Bank app",
            "web":    "Available at meridianbank.co.uk",
        },
    }
