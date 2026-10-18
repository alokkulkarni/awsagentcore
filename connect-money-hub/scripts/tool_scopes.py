#!/usr/bin/env python3
"""
tool_scopes.py
==============
ARIA's card, mortgage and spending tools answer only for the customer ARIA is talking to: each takes the
customer's ID (customer_id, from the session context) and finds only that customer's own card, account or mortgage.
Without it, naming another customer's card digits would show their payments.

ARIA keeps her own copy of each MCP tool's input schema, so the field is added here as well as on the gateway
(scripts/deploy_mcp_gateway.sh update-targets). Used by collaborator.py; it only transforms JSON.
"""

from __future__ import annotations

import json

CUSTOMER_ID = {
    "type": "string",
    "description": "The customer's ID from the session context (customerId). Only that customer's own cards, "
                   "accounts and mortgage are found.",
}
# ARIA's tool name -> the field it already required
SCOPED = {
    "aria_banking_debit_card___get_debit_card_details": "card_last_four",
    "aria_banking_credit_card___get_credit_card_details": "card_last_four",
    "aria_banking_mortgage___get_mortgage_details": "mortgage_reference",
    "aria_banking_products___analyse_spending": "",
}


def apply(configuration: dict) -> dict:
    """ARIA's configuration with customer_id required on the scoped tools (applying twice changes nothing)."""
    config = json.loads(json.dumps(configuration))
    for tool in (config.get("orchestrationAIAgentConfiguration") or {}).get("toolConfigurations") or []:
        if tool.get("toolName") not in SCOPED or "inputSchema" not in tool:
            continue
        schema = tool["inputSchema"]
        schema.setdefault("properties", {})["customer_id"] = dict(CUSTOMER_ID)
        required = [r for r in schema.get("required", []) if r != "customer_id"]
        schema["required"] = ["customer_id", *required]
    return config
