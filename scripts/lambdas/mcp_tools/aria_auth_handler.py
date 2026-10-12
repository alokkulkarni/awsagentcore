"""
Lambda handler: ARIA Authentication Tools (AgentCore MCP Gateway target)

Invoked by AgentCore MCP Gateway on behalf of Amazon Connect Agentic Self-Service.
The toolName field in the event payload determines which operation is performed.

Tools exposed via MCP:
  - initiate_auth          — begins a customer authentication session
  - validate_customer      — verifies a customer ID exists in the system
  - cross_validate         — validates DOB + last 4 mobile digits against records
  - verify_identity        — confirms identity match before data access
  - send_push_challenge    — sends a number-matching approval to the customer's app
  - verify_push_challenge  — checks the outcome of that approval (payment step-up)

Environment variables:
  BANKING_API_URL  — optional; Meridian Bank identity service base URL
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

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
            "app_enrolled": True,
            "status": "active",
        },
        "CUST-002": {
            "name": "Sarah",
            "dob": "14/03/1990",
            "mobile_last_four": "4471",
            "app_enrolled": True,
            "status": "active",
        },
        "CUST-003": {
            "name": "Margaret",
            "dob": "09/11/1958",
            "mobile_last_four": "0002",
            "app_enrolled": True,
            "status": "active",
        },
        "CUST-004": {
            "name": "Daniel",
            "dob": "30/05/1994",
            "mobile_last_four": "0003",
            "app_enrolled": True,
            "status": "active",
        },
        "CUST-005": {
            "name": "Ethel",
            "dob": "03/02/1941",
            "mobile_last_four": "0004",
            "app_enrolled": False,
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
        "send_push_challenge":           _send_push_challenge,
        "verify_push_challenge":         _verify_push_challenge,
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


def _digits(value) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def _normalise_dob(value) -> str:
    """
    Reduce a date of birth to DDMMYYYY so spoken, typed and ISO forms compare
    equal: "09/09/1982", "9-9-1982", "09091982" and "1982-09-09" all match.
    Returns "" when the value is not a recognisable date.
    """
    text = str(value or "").strip()
    parts = [p for p in text.replace("-", "/").replace(".", "/").replace(" ", "/").split("/") if p]
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        if len(parts[0]) == 4:                                  # YYYY/MM/DD
            parts = [parts[2], parts[1], parts[0]]
        day, month, year = parts
        if len(year) == 4:
            return f"{int(day):02d}{int(month):02d}{year}"
    digits = _digits(text)
    return digits if len(digits) == 8 else ""


def _cross_validate(params: dict) -> dict:
    """
    validate_customer_auth: verifies customer ID, date of birth and the last 4
    digits of the mobile number. Both answers must match.

    ARIA uses this in two places: to authenticate an unauthenticated caller,
    and as the payment step-up that lifts a level 3 caller to level 4. The
    answer never says which of the two details was wrong.

    The date of birth is accepted as `dob` (the name in the tool schema) or
    `date_of_birth`, in any common format.
    """
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    cid = str(params.get("customer_id", "")).strip()
    dob = _normalise_dob(params.get("dob") or params.get("date_of_birth"))
    mobile4 = _digits(params.get("mobile_last_four"))[-4:]

    if cid not in _MOCK_CUSTOMERS:
        return {"verified": False, "reason": "Customer not found."}

    cust = _MOCK_CUSTOMERS[cid]
    dob_ok = bool(dob) and _normalise_dob(cust["dob"]) == dob
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


# ---------------------------------------------------------------------------
# App push with number matching — the payment step-up (level 3 to level 4)
# ---------------------------------------------------------------------------
# SIMULATION. No notification is really sent. In production the customer picks
# the number in the bank app and approves with a biometric; the app sends a
# signed assertion straight to the push service, and the AI agent only ever
# learns the outcome. Here there is no app, so the customer TELLS the agent
# which number they picked and the agent passes it to verify_push_challenge.
# That means the agent has seen the right answer, which a real deployment must
# never allow. The decision is still made here, not by the agent.
#
# The challenge is stateless: challenge_id is a signed token carrying the
# customer, the payment it was raised for and an expiry. Statelessness means a
# challenge is time-limited but not single-use; production needs a store.
PUSH_CHALLENGE_TTL_SECONDS = 180
_PUSH_SECRET = os.environ.get("PUSH_CHALLENGE_SECRET", "aria-mock-push-secret-not-for-production")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _sign_challenge(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = hmac.new(_PUSH_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def _read_challenge(token) -> dict | None:
    """Payload of a genuinely signed challenge, or None. Never raises."""
    try:
        body, sig = str(token or "").split(".", 1)
        expected = hmac.new(_PUSH_SECRET.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _match_number(customer_id: str, nonce: str) -> str:
    """The two-digit number (10 to 99) the customer must pick in the app."""
    digest = hmac.new(_PUSH_SECRET.encode(), f"{customer_id}|{nonce}".encode(), hashlib.sha256).hexdigest()
    return str(10 + int(digest, 16) % 90)


def _send_push_challenge(params: dict) -> dict:
    """
    send_push_challenge: raise an approval request in the customer's app for one
    payment. Returns the number the agent must read out and a challenge_id to
    pass to verify_push_challenge.
    """
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    cid = str(params.get("customer_id", "")).strip()
    cust = _MOCK_CUSTOMERS.get(cid)
    if cust is None:
        return {"sent": False, "reason": "Customer not found."}
    if not cust.get("app_enrolled", False):
        return {"sent": False, "reason": "no_registered_app"}

    payee = str(params.get("payee", "")).strip()
    amount = str(params.get("amount", "")).strip()
    nonce = uuid.uuid4().hex[:12]
    challenge_id = _sign_challenge({"c": cid, "n": nonce, "p": payee, "a": amount,
                                    "e": int(time.time()) + PUSH_CHALLENGE_TTL_SECONDS})
    return {
        "sent": True,
        "challenge_id": challenge_id,
        "match_number": _match_number(cid, nonce),
        "expires_in_seconds": PUSH_CHALLENGE_TTL_SECONDS,
        "payee": payee,
        "amount": amount,
    }


def _verify_push_challenge(params: dict) -> dict:
    """
    verify_push_challenge: the outcome of an app approval.

    status APPROVED    the customer picked the right number        verified: true
           DECLINED    wrong number, or the customer declined
           NO_RESPONSE no number was given (nothing arrived, or not opened)
           EXPIRED     the challenge timed out
           INVALID     the challenge is not genuine or is for another customer
    Only APPROVED carries verified: true. The payee and amount returned are the
    ones the challenge was raised for.
    """
    if not _MOCK_DATA:
        return {"error": "No data source configured. Set MOCK_DATA=true for demo mode or configure a real data source."}

    cid = str(params.get("customer_id", "")).strip()
    payload = _read_challenge(params.get("challenge_id"))
    if payload is None or payload.get("c") != cid or cid not in _MOCK_CUSTOMERS:
        return {"verified": False, "status": "INVALID"}
    if payload.get("e", 0) < time.time():
        return {"verified": False, "status": "EXPIRED"}

    selected = _digits(params.get("selected_number"))
    if not selected:
        return {"verified": False, "status": "NO_RESPONSE"}
    if hmac.compare_digest(selected, _match_number(cid, payload.get("n", ""))):
        return {"verified": True, "status": "APPROVED", "customer_id": cid,
                "payee": payload.get("p", ""), "amount": payload.get("a", "")}
    return {"verified": False, "status": "DECLINED"}


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
