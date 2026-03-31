"""
Lambda handler: ARIA Account Tools (AgentCore MCP Gateway target)

Tools exposed via MCP:
  - get_account_details — balance, transactions, statement URL, standing orders
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    logger.info("account event: %s", json.dumps(event))

    tool_name = event.get("toolName") or event.get("tool_name", "")
    params: dict = event.get("parameters") or event.get("params") or {}

    if tool_name == "get_account_details":
        return _get_account_details(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_account_details(params: dict) -> dict:
    account_number = str(params.get("account_number", ""))
    query_subtype = str(params.get("query_subtype", "balance"))
    customer_id = str(params.get("customer_id", ""))
    last_four = account_number[-4:] if len(account_number) >= 4 else account_number

    result: dict = {
        "account_number_last_four": last_four,
        "sort_code_last_two": "67",
        "account_type": "current",
        "available_balance": 1245.30,
        "cleared_balance": 1300.00,
        "currency": "GBP",
        "query_subtype": query_subtype,
    }

    if query_subtype == "transactions":
        result["recent_transactions"] = [
            {"date": "2026-03-27", "description": "TESCO STORES", "amount": -42.50, "type": "debit"},
            {"date": "2026-03-26", "description": "SALARY MERIDIAN CORP", "amount": 3200.00, "type": "credit"},
            {"date": "2026-03-25", "description": "AMAZON.CO.UK", "amount": -89.99, "type": "debit"},
            {"date": "2026-03-24", "description": "DIRECT DEBIT - EDF ENERGY", "amount": -75.00, "type": "debit"},
            {"date": "2026-03-23", "description": "CONTACTLESS - COSTA COFFEE", "amount": -4.50, "type": "debit"},
        ]
    elif query_subtype == "standing_orders":
        result["standing_orders"] = [
            {
                "payee": "LANDLORD RENT",
                "amount": 950.00,
                "frequency": "monthly",
                "next_date": "2026-04-01",
            }
        ]
    elif query_subtype == "statement":
        result["statement_url"] = (
            f"https://secure.meridianbank.co.uk/statements/{customer_id}/{last_four}"
        )

    return result
