"""
Lambda handler: ARIA Debit Card Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - get_debit_card_details — card status, limits, contactless settings
  - block_debit_card       — blocks a debit card (lost or stolen)
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    logger.info("debit_card event: %s", json.dumps(event))

    tool_name = event.get("toolName") or event.get("tool_name", "")
    params: dict = event.get("parameters") or event.get("params") or {}

    if tool_name == "get_debit_card_details":
        return _get_debit_card_details(params)
    elif tool_name == "block_debit_card":
        return _block_debit_card(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_debit_card_details(params: dict) -> dict:
    card_last_four = str(params.get("card_last_four", "****"))
    return {
        "card_last_four": card_last_four,
        "card_status": "active",
        "card_type": "Visa Debit",
        "daily_atm_limit": 500.00,
        "daily_pos_limit": 5000.00,
        "expiry_masked": "**/**",
        "replacement_available": True,
        "contactless_enabled": True,
        "online_payments_enabled": True,
    }


def _block_debit_card(params: dict) -> dict:
    card_last_four = str(params.get("card_last_four", "****"))
    reason = str(params.get("reason", "lost_stolen"))
    ref = f"BLOCK-{card_last_four}-{uuid.uuid4().hex[:6].upper()}"
    return {
        "blocked": True,
        "card_last_four": card_last_four,
        "reason": reason,
        "reference": ref,
        "message": (
            f"Your debit card ending {card_last_four} has been blocked. "
            "A replacement card will be sent to your registered address within 3-5 working days."
        ),
    }
