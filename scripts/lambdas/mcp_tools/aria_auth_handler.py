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

_MOCK_DATA = os.environ.get("MOCK_DATA", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Stub data — replace with real Meridian Bank identity service calls
# ---------------------------------------------------------------------------
if _MOCK_DATA:
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
else:
    _MOCK_CUSTOMERS = {}


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


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
    logger.info("auth event: %s", json.dumps(_redact_event(event)))

    tool_name, params = _parse_tool_call(event, context)

    dispatch = {
        "verify_customer_identity":      _validate_customer,
        "initiate_customer_auth":        _initiate_auth,
        "validate_customer_auth":        _cross_validate,
        "cross_validate_session_identity": _verify_identity,
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
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    cid = str(params.get("customer_id", "")).strip()
    if cid in _MOCK_CUSTOMERS:
        return {"valid": True, "customer_found": True}
    return {"valid": False, "customer_found": False, "message": "Customer ID not found."}


def _cross_validate(params: dict) -> dict:
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

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
