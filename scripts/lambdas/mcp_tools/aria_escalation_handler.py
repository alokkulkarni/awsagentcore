"""
Lambda handler: ARIA Escalation Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - escalate_to_human_agent    — transfers the call to a human agent with full handoff package
  - generate_transcript_summary — produces a structured summary of the session for handoff/audit
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

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
    logger.info("escalation event: %s", json.dumps(event))

    tool_name, params = _parse_tool_call(event, context)

    if tool_name == "escalate_to_human_agent":
        return _escalate_to_human_agent(params)
    if tool_name == "generate_transcript_summary":
        return _generate_transcript_summary(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _escalate_to_human_agent(params: dict) -> dict:
    session_id      = str(params.get("session_id", ""))
    customer_id     = str(params.get("customer_id", ""))
    reason          = str(params.get("escalation_reason", "customer_request"))
    priority        = str(params.get("priority", "standard"))
    query_context   = params.get("query_context", {})
    vuln_flag       = params.get("vulnerability_flag", False)
    flag_type       = str(params.get("flag_type", ""))
    topic_category  = str(params.get("topicCategory", ""))
    conv_summary    = str(params.get("conversationSummary", ""))

    handoff_ref = f"HO-{datetime.now().strftime('%Y%m%d')}-{(customer_id or session_id)[:6].upper()}"

    return {
        "handoff_status": "accepted",
        "handoff_ref": handoff_ref,
        "agent_id": f"AGT-{uuid.uuid4().hex[:5].upper()}",
        "estimated_wait_seconds": 30,
        "escalation_reason": reason,
        "priority": priority,
        "queue": "ARIA-Escalations",
        "vulnerability_flag": vuln_flag,
        "flag_type": flag_type,
        "topic_category": topic_category,
        "conversation_summary": conv_summary,
        "query_context": query_context,
    }


def _generate_transcript_summary(params: dict) -> dict:
    session_id      = str(params.get("session_id", ""))
    summary_format  = str(params.get("summary_format", "structured"))
    include_vault   = bool(params.get("include_vault_refs", False))

    return {
        "session_id": session_id,
        "summary": "Customer called to enquire about their account. Authentication completed successfully.",
        "intent": "account_inquiry",
        "auth_status": "authenticated",
        "products_discussed": ["current_account"],
        "actions_taken": [],
        "summary_format": summary_format,
        "vault_refs_included": include_vault,
    }
