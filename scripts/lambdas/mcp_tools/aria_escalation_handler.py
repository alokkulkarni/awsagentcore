"""
Lambda handler: ARIA Escalation Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - escalate_to_human — signals Connect to transfer the call to a human agent

When Connect's Agentic Self-Service AI invokes this tool, the Contact Flow
should detect the escalation flag and route to the CustomerServiceQueue.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    logger.info("escalation event: %s", json.dumps(event))

    tool_name = event.get("toolName") or event.get("tool_name", "")
    params: dict = event.get("parameters") or event.get("params") or {}

    if tool_name == "escalate_to_human":
        return _escalate_to_human(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _escalate_to_human(params: dict) -> dict:
    reason = str(params.get("reason", "Customer requested agent"))
    return {
        "escalation_requested": True,
        "reason": reason,
        "transfer_queue": "CustomerServiceQueue",
        "message": "Transferring you to one of our team now. Please hold.",
    }
