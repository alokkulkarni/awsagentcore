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


def lambda_handler(event: dict, context) -> dict:
    logger.info("customer event: %s", json.dumps(event))

    tool_name = event.get("toolName") or event.get("tool_name", "")
    params: dict = event.get("parameters") or event.get("params") or {}

    if tool_name == "get_customer_profile":
        cid = str(params.get("customer_id", "")).strip()
        profile = _MOCK_PROFILES.get(cid)
        if profile:
            return {"customer_id": cid, **profile}
        return {"error": "Customer not found"}

    return {"error": f"Unknown tool: {tool_name}"}
