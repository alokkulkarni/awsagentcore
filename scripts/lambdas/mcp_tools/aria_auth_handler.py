"""
Lambda handler: ARIA Authentication Tools (AgentCore MCP Gateway target)

Invoked by AgentCore MCP Gateway on behalf of Amazon Connect Agentic Self-Service.
The toolName field in the event payload determines which operation is performed.

Tools exposed via MCP:
  - initiate_auth      — begins a customer authentication session
  - validate_customer  — verifies a customer ID exists in the system
  - cross_validate     — validates DOB + last 4 mobile digits against records
  - verify_identity    — confirms identity match before data access

Environment variables:
  BANKING_API_URL  — optional; Meridian Bank identity service base URL
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Stub data — replace with real Meridian Bank identity service calls
# ---------------------------------------------------------------------------
_MOCK_CUSTOMERS: dict[str, dict] = {
    "CUST-001": {
        "name": "James",
        "dob": "09/09/1982",
        "mobile_last_four": "9252",
        "status": "active",
    },
    "CUST-002": {
        "name": "Sarah",
        "dob": "14/03/1990",
        "mobile_last_four": "4471",
        "status": "active",
    },
}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context) -> dict:
    logger.info("auth event: %s", json.dumps(event))

    tool_name = event.get("toolName") or event.get("tool_name", "")
    params: dict = event.get("parameters") or event.get("params") or {}

    dispatch = {
        "initiate_auth": _initiate_auth,
        "validate_customer": _validate_customer,
        "cross_validate": _cross_validate,
        "verify_identity": _verify_identity,
    }

    handler = dispatch.get(tool_name)
    if handler is None:
        return {"error": f"Unknown tool: {tool_name}"}

    return handler(params)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _initiate_auth(params: dict) -> dict:
    return {
        "session_started": True,
        "message": "Authentication session initiated.",
        "required_fields": ["customer_id"],
    }


def _validate_customer(params: dict) -> dict:
    cid = str(params.get("customer_id", "")).strip()
    if cid in _MOCK_CUSTOMERS:
        return {"valid": True, "customer_found": True}
    return {"valid": False, "customer_found": False, "message": "Customer ID not found."}


def _cross_validate(params: dict) -> dict:
    """Verifies customer ID, date of birth, and last 4 digits of mobile number."""
    cid = str(params.get("customer_id", "")).strip()
    dob = str(params.get("date_of_birth", "")).strip()
    mobile4 = str(params.get("mobile_last_four", "")).strip()

    if cid not in _MOCK_CUSTOMERS:
        return {"verified": False, "reason": "Customer not found."}

    cust = _MOCK_CUSTOMERS[cid]
    dob_ok = cust["dob"] == dob
    mobile_ok = cust["mobile_last_four"] == mobile4

    if dob_ok and mobile_ok:
        return {
            "verified": True,
            "customer_id": cid,
            "name": cust["name"],
            "auth_level": "full",
        }

    return {
        "verified": False,
        "reason": "Verification details do not match our records.",
    }


def _verify_identity(params: dict) -> dict:
    """Confirms the authenticated identity before any account data is accessed."""
    header_cid = str(params.get("header_customer_id", "")).strip()
    requested_cid = str(params.get("requested_customer_id", "")).strip()
    match = bool(header_cid and header_cid == requested_cid)
    return {
        "identity_match": match,
        "risk_score": 10 if match else 90,
        "auth_level": "full" if match else "none",
    }
