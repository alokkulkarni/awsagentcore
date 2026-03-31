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


def lambda_handler(event: dict, context) -> dict:
    logger.info("mortgage event: %s", json.dumps(event))

    tool_name = event.get("toolName") or event.get("tool_name", "")
    params: dict = event.get("parameters") or event.get("params") or {}

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
