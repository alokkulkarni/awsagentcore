"""
Lambda handler: ARIA Credit Card Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - get_credit_card_details — balance, limit, minimum payment, transactions
  - block_credit_card       — blocks a credit card (lost or stolen)
"""

from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    logger.info("credit_card event: %s", json.dumps(event))

    tool_name = event.get("toolName") or event.get("tool_name", "")
    params: dict = event.get("parameters") or event.get("params") or {}

    if tool_name == "get_credit_card_details":
        return _get_credit_card_details(params)
    elif tool_name == "block_credit_card":
        return _block_credit_card(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_credit_card_details(params: dict) -> dict:
    card_last_four = str(params.get("card_last_four", "****"))
    query_subtype = str(params.get("query_subtype", "status"))
    result: dict = {
        "card_last_four": card_last_four,
        "card_type": "Rewards Credit Card",
        "card_status": "active",
        "credit_limit": 5000.00,
        "available_credit": 3250.00,
        "outstanding_balance": 1750.00,
        "minimum_payment": 35.00,
        "next_payment_date": "2026-04-15",
        "expiry_masked": "**/**",
        "query_subtype": query_subtype,
    }
    if query_subtype == "transactions":
        result["recent_transactions"] = [
            {"date": "2026-03-27", "description": "MARKS & SPENCER", "amount": -65.40},
            {"date": "2026-03-25", "description": "NETFLIX", "amount": -17.99},
            {"date": "2026-03-22", "description": "PAYMENT RECEIVED - THANK YOU", "amount": 200.00},
        ]
    return result


def _block_credit_card(params: dict) -> dict:
    card_last_four = str(params.get("card_last_four", "****"))
    reason = str(params.get("reason", "lost_stolen"))
    ref = f"CC-BLOCK-{card_last_four}-{uuid.uuid4().hex[:6].upper()}"
    return {
        "blocked": True,
        "card_last_four": card_last_four,
        "reason": reason,
        "reference": ref,
        "message": (
            f"Your credit card ending {card_last_four} has been blocked. "
            "A replacement card will be sent to your registered address within 3-5 working days."
        ),
    }
