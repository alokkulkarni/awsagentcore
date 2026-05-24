"""
aria_connect_fulfillment.py

Lambda fulfillment function for the ARIA-Connect-Bot Lex V2 bot.
Called on every conversation turn by Amazon Lex V2.

Flow:
  Amazon Connect (PSTN voice / chat)
    → Lex V2 + Nova Sonic S2S (speech ↔ text)
      → This Lambda (every turn)
        → ARIA AgentCore HTTP /invocations
          → ARIA Strands agent response (plain text)
        → Lex response → Nova Sonic speaks it back

DTMF Secure Capture Bridge
──────────────────────────
When ARIA needs to collect sensitive digits (card number, PIN, etc.) it calls
the MCP tool  initiate_dtmf_card_capture  which writes the contact attribute
  dtmf_collection_requested = "true"
and returns  bridge_action = "DTMF_COLLECT"  to AgentCore.

After each AgentCore call, this Lambda checks the contact attribute. When it
finds  dtmf_collection_requested == "true"  it:
  1. Clears the flag (sets it to "false") so it does not fire again.
  2. Returns the  CollectCardDetails  Lex intent instead of the normal
     ElicitIntent. Amazon Connect reads this intent, branches the contact
     flow, and transfers the call to the ARIA-DTMF-SecureCollection sub-flow.
  3. When the sub-flow finishes the results are in contact attributes
     (dtmf_masked, dtmf_result, dtmf_card_type, …) which are mapped back to
     Lex session attributes by the contact flow before reinvoking this Lambda.
  4. ARIA reads the session attributes and resumes the conversation.

Environment variables required:
  AGENTCORE_ENDPOINT    full HTTPS URL to the AgentCore runtime invocations endpoint
  CONNECT_INSTANCE_ID   Amazon Connect instance ID (UUID)

Deployment:
  See docs/amazon-connect-lex-nova-sonic-setup-guide.md for full setup instructions.
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.exceptions import ClientError

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AGENTCORE_ENDPOINT = os.environ.get(
    "AGENTCORE_ENDPOINT",
    (
        "https://bedrock-agentcore.eu-west-2.amazonaws.com"
        "/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aeu-west-2%3A395402194296"
        "%3Aruntime%2Faria_banking_agent-ubLoKG8xsY/invocations"
    ),
)
AWS_REGION          = os.environ.get("AWS_REGION",          "eu-west-2")
CONNECT_INSTANCE_ID = os.environ.get("CONNECT_INSTANCE_ID", "")
SERVICE             = "bedrock-agentcore"

# Maximum number of automatic retries on transient AgentCore failures
AGENTCORE_MAX_RETRIES = int(os.environ.get("AGENTCORE_MAX_RETRIES", "2"))

# ── Security: validate AGENTCORE_ENDPOINT scheme to prevent SSRF ──────────
_parsed_endpoint = urllib.parse.urlparse(AGENTCORE_ENDPOINT)
if _parsed_endpoint.scheme != "https" or not _parsed_endpoint.netloc:
    raise ValueError(
        f"AGENTCORE_ENDPOINT must be a full HTTPS URL, got: {AGENTCORE_ENDPOINT!r}"
    )

_connect_client = None


def _get_connect():
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _connect_client


def _push_aria_status(contact_id: str, status: str, step: str = "", error_msg: str = "",
                      retry_count: int = 0) -> None:
    """
    Push ARIA AI processing status to both channels simultaneously:
      • Human agent  — Contact Attributes panel in their CCP refreshes in near-real time.
      • AI agent     — Contact attributes become Lex session attributes on the next turn,
                       so ARIA can read and communicate the status to the customer.

    This call is non-critical: failures are logged as warnings and never propagate.
    """
    if not contact_id or not CONNECT_INSTANCE_ID or contact_id in ("", "unknown", "unknown-session"):
        return
    attrs = {
        "aria_status":      status,
        "aria_retry_count": str(retry_count),
    }
    if step:       attrs["aria_step"]      = step
    if error_msg:  attrs["aria_error_msg"] = error_msg
    try:
        _get_connect().update_contact_attributes(
            InitialContactId=contact_id,
            InstanceId=CONNECT_INSTANCE_ID,
            Attributes=attrs,
        )
    except Exception as exc:
        logger.warning("push_aria_status failed (non-critical) contact=%s: %s", contact_id, exc)

# Phrases that signal ARIA wants to escalate to a human agent
ESCALATION_PHRASES = [
    "speak to an agent",
    "speak to someone",
    "transfer me",
    "transfer you",
    "human agent",
    "real person",
    "talk to a person",
    "connect you with",
    "one of our advisors",
    "one of our agents",
]

# ---------------------------------------------------------------------------
# DTMF bridge: detect and clear the secure-capture request flag
# ---------------------------------------------------------------------------

def _check_and_clear_dtmf_flag(contact_id: str) -> bool:
    """
    Check whether the MCP tool initiate_dtmf_card_capture has requested
    a DTMF collection flow for this contact.

    If  dtmf_collection_requested == "true"  is found in the contact
    attributes, this function clears the flag (sets it to "false") and
    returns True so the caller can return the CollectCardDetails intent.

    Returns False when:
      • The flag is absent or not "true".
      • CONNECT_INSTANCE_ID is not set (non-Connect invocations / unit tests).
      • The Connect API call fails for any reason (fail-open: don't block).
    """
    if not contact_id or not CONNECT_INSTANCE_ID:
        return False
    if contact_id in ("", "unknown", "unknown-session"):
        return False
    try:
        resp = _get_connect().get_contact_attributes(
            InitialContactId=contact_id,
            InstanceId=CONNECT_INSTANCE_ID,
        )
        attrs = resp.get("Attributes", {})
        if attrs.get("dtmf_collection_requested", "").lower() == "true":
            # Clear the flag so it doesn't fire on the next turn
            _get_connect().update_contact_attributes(
                InitialContactId=contact_id,
                InstanceId=CONNECT_INSTANCE_ID,
                Attributes={"dtmf_collection_requested": "false"},
            )
            logger.info("DTMF bridge triggered for contact=%s", contact_id)
            return True
    except Exception as exc:
        logger.warning(
            "DTMF flag check failed (non-critical, continuing normally) "
            "contact=%s: %s", contact_id, exc
        )
    return False


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------
def handler(event, context):
    logger.info("Lex event: %s", json.dumps(event, default=str))

    session_state    = event.get("sessionState", {})
    intent_name      = session_state.get("intent", {}).get("name", "FallbackIntent")
    input_transcript = event.get("inputTranscript", "").strip()
    session_attrs    = session_state.get("sessionAttributes", {}) or {}

    # ContactId from Amazon Connect — used as the AgentCore session ID so all
    # turns within a single call share the same Strands agent state.
    request_attrs = event.get("requestAttributes", {}) or {}
    contact_id = (
        request_attrs.get("ContactId")
        or session_attrs.get("contactId")
        or event.get("sessionId", "unknown-session")
    )

    # ------------------------------------------------------------------
    # Pre-auth context injected by aria-session-injector via Connect
    # contact attributes → Lex session attributes (Block 5 + Block 6).
    # All fields are optional — defaults keep unauthenticated calls safe.
    # ------------------------------------------------------------------
    customer_id           = session_attrs.get("customerId", "")
    auth_status           = session_attrs.get("authStatus", "unauthenticated")
    preferred_name        = session_attrs.get("preferredName", "")
    product_summary       = session_attrs.get("productSummary", "")
    product_context       = session_attrs.get("productContext", "")
    vulnerability_context = session_attrs.get("vulnerabilityContext", "")
    prior_summary         = session_attrs.get("priorSummary", "")
    channel               = session_attrs.get("channel", "voice")
    locale                = session_attrs.get("locale", "en-GB")
    date_time             = session_attrs.get("dateTime", "")

    # Persist contactId in session attributes so it survives across turns
    session_attrs["contactId"] = contact_id

    logger.info(
        "Turn: intent=%s contactId=%s customerId=%r authStatus=%s transcript=%r",
        intent_name, contact_id, customer_id, auth_status, input_transcript,
    )

    # Handle explicit TransferToAgent intent
    if intent_name == "TransferToAgent":
        session_attrs["escalate"] = "true"
        return _build_close_response(
            "Of course. Let me connect you with one of our advisors now. "
            "Please hold for a moment.",
            session_attrs,
            escalate=True,
        )

    # Guard against empty transcript
    if not input_transcript:
        return _build_elicit_response(
            "I'm sorry, I didn't quite catch that. Could you say that again?",
            session_attrs,
        )

    # Push "thinking" status so human agent and AI next-turn can see ARIA is active
    _push_aria_status(contact_id, "thinking",
                      "AI agent processing customer request...", retry_count=0)

    # Call ARIA AgentCore with full pre-auth context (with automatic retry)
    try:
        aria_response = _call_agentcore_with_retry(
            input_transcript,
            contact_id,
            customer_id=customer_id,
            auth_status=auth_status,
            preferred_name=preferred_name,
            product_summary=product_summary,
            product_context=product_context,
            vulnerability_context=vulnerability_context,
            prior_summary=prior_summary,
            channel=channel,
            locale=locale,
            date_time=date_time,
        )
    except Exception as exc:
        logger.error("AgentCore call failed after retries: %s", exc, exc_info=True)
        _push_aria_status(contact_id, "error",
                          "AI service unavailable — agent assistance recommended",
                          error_msg="AgentCore unreachable after retries")
        # Surface the failure in session attrs so ARIA or the Connect flow can read it
        session_attrs["aria_status"]      = "error"
        session_attrs["aria_error_msg"]   = "AgentCore unavailable"
        return _build_elicit_response(
            "I'm sorry, I'm having a technical issue right now. "
            "Please bear with me, or press zero to speak with an advisor.",
            session_attrs,
        )

    logger.info("ARIA response (session=%s): %r", contact_id, aria_response[:200])

    # Clear processing status — ARIA has a response
    _push_aria_status(contact_id, "complete", "Response ready")
    session_attrs["aria_status"] = "complete"

    # -----------------------------------------------------------------------
    # DTMF bridge check: did ARIA's MCP tool request secure digit collection?
    # This must run AFTER we have ARIA's response (so the MCP tool has had
    # time to set the contact attribute) but BEFORE we decide how to route.
    # -----------------------------------------------------------------------
    if _check_and_clear_dtmf_flag(contact_id):
        # Return CollectCardDetails intent — Amazon Connect branches the flow
        # to ARIA-DTMF-SecureCollection sub-flow.
        # ARIA's response becomes the message spoken just before the transfer.
        return _build_collect_card_response(aria_response, session_attrs)

    # Detect escalation in ARIA's response
    escalate = any(phrase in aria_response.lower() for phrase in ESCALATION_PHRASES)
    if escalate:
        session_attrs["escalate"] = "true"
        return _build_close_response(aria_response, session_attrs, escalate=True)

    return _build_elicit_response(aria_response, session_attrs)


# ---------------------------------------------------------------------------
# AgentCore HTTP invocation (SigV4 signed)
# ---------------------------------------------------------------------------
def _call_agentcore(
    user_message: str,
    session_id: str,
    customer_id: str = "",
    auth_status: str = "unauthenticated",
    preferred_name: str = "",
    product_summary: str = "",
    product_context: str = "",
    vulnerability_context: str = "",
    prior_summary: str = "",
    channel: str = "voice",
    locale: str = "en-GB",
    date_time: str = "",
) -> str:
    """POST to AgentCore /invocations with full pre-auth context, return ARIA's plain-text response.

    All context fields beyond ``user_message`` and ``session_id`` are optional —
    missing / empty values are omitted from the payload so the agentcore_app
    chat_handler receives clean input and falls back gracefully for non-voice
    callers (e.g. the React chat app which sends only ``message``).
    """
    payload: dict = {
        "message":       user_message,
        "authenticated": auth_status == "authenticated",
        "channel":       channel,
    }
    # Only include non-empty optional context fields to keep the payload compact
    if customer_id:
        payload["customer_id"] = customer_id
    if preferred_name:
        payload["preferred_name"] = preferred_name
    if product_summary:
        payload["product_summary"] = product_summary
    if product_context:
        payload["product_context"] = product_context
    if vulnerability_context:
        payload["vulnerability_context"] = vulnerability_context
    if prior_summary:
        payload["prior_summary"] = prior_summary
    if locale and locale != "en-GB":
        payload["locale"] = locale
    if date_time:
        payload["date_time"] = date_time

    body = json.dumps(payload).encode("utf-8")

    session = boto3.Session()
    creds = session.get_credentials().get_frozen_credentials()

    headers = {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }

    aws_request = AWSRequest(
        method="POST",
        url=AGENTCORE_ENDPOINT,
        data=body,
        headers=headers,
    )
    SigV4Auth(creds, SERVICE, AWS_REGION).add_auth(aws_request)

    req = urllib.request.Request(
        AGENTCORE_ENDPOINT,
        data=body,
        headers=dict(aws_request.headers),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")
        logger.error("AgentCore HTTP %s: %s", e.code, body_err)
        raise RuntimeError(f"AgentCore HTTP {e.code}: {body_err}") from e

    return raw.strip() or "I'm processing your request. Could you give me a moment?"


# ---------------------------------------------------------------------------
# Retry wrapper — AgentCore with live status updates
# ---------------------------------------------------------------------------

def _call_agentcore_with_retry(
    user_message: str,
    contact_id:   str,
    **kwargs,
) -> str:
    """
    Call AgentCore with automatic retry on transient failures.

    On each attempt, pushes real-time status to both channels:
      - Human agent  sees "aria_status" updating in their Contact Attributes panel.
      - AI agent     reads "aria_status" + "aria_retry_count" from session attributes
                     on the next Lex turn, so it can acknowledge delays to the customer.

    Retry schedule (configurable via AGENTCORE_MAX_RETRIES env var, default 2):
      Attempt 1 — immediate
      Attempt 2 — 1 second wait
      Attempt 3 — 2 second wait
    After all retries exhausted, raises the last exception.
    """
    last_exc: Optional[Exception] = None

    for attempt in range(1, AGENTCORE_MAX_RETRIES + 2):   # e.g. 1, 2, 3
        if attempt == 1:
            _push_aria_status(contact_id, "thinking",
                              "AI agent processing your request...", retry_count=0)
        else:
            wait = 2 ** (attempt - 2)   # 1s, 2s, 4s …
            logger.warning("AgentCore attempt %d failed — retrying in %ds", attempt - 1, wait)
            _push_aria_status(
                contact_id, "retrying",
                f"Reconnecting to AI service (attempt {attempt} of {AGENTCORE_MAX_RETRIES + 1})...",
                retry_count=attempt - 1,
            )
            time.sleep(wait)

        try:
            response = _call_agentcore(user_message, contact_id, **kwargs)
            if attempt > 1:
                logger.info("AgentCore succeeded on attempt %d", attempt)
                _push_aria_status(contact_id, "complete",
                                  f"Connected (recovered after {attempt - 1} retry)",
                                  retry_count=attempt - 1)
            return response
        except Exception as exc:
            last_exc = exc
            _push_aria_status(
                contact_id, "retrying" if attempt <= AGENTCORE_MAX_RETRIES else "error",
                f"Connection issue on attempt {attempt} — {'retrying' if attempt <= AGENTCORE_MAX_RETRIES else 'unable to connect'}",
                error_msg=type(exc).__name__,
                retry_count=attempt - 1,
            )
            logger.error("AgentCore attempt %d error: %s", attempt, exc)

    raise last_exc


# ---------------------------------------------------------------------------
# Lex V2 response builders
# ---------------------------------------------------------------------------
def _build_collect_card_response(message: str, session_attrs: dict) -> dict:
    """
    Return the CollectCardDetails Lex intent so Amazon Connect's contact flow
    branches to the ARIA-DTMF-SecureCollection module flow.

    The  message  (ARIA's spoken script from the MCP tool) is played to the
    customer BEFORE the transfer happens — they hear a natural prompt rather
    than silence or a generic beep.

    The contact flow MUST have a branch on intent name == "CollectCardDetails"
    after the 'Get customer input' Lex block. That branch should:
      • Set contact attributes from session attributes (collectionPurpose etc.)
      • Use 'Transfer to flow' to invoke ARIA-DTMF-SecureCollection
      • After return, map dtmf_* contact attributes back to session attributes
      • Loop back to the 'Get customer input' block so ARIA resumes
    """
    session_attrs["dtmf_pending"] = "true"
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {"name": "CollectCardDetails", "state": "Fulfilled"},
            "sessionAttributes": session_attrs,
        },
        "messages": [{"contentType": "PlainText", "content": message}],
    }


def _build_elicit_response(message: str, session_attrs: dict) -> dict:
    """Keep the conversation going — Lex will capture the next customer utterance."""
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitIntent"},
            "sessionAttributes": session_attrs,
        },
        "messages": [{"contentType": "PlainText", "content": message}],
    }


def _build_close_response(
    message: str, session_attrs: dict, escalate: bool = False
) -> dict:
    """End this intent turn. The Connect flow checks sessionAttributes.escalate."""
    if escalate:
        session_attrs["escalate"] = "true"
    return {
        "sessionState": {
            "dialogAction": {"type": "Close"},
            "intent": {"name": "FallbackIntent", "state": "Fulfilled"},
            "sessionAttributes": session_attrs,
        },
        "messages": [{"contentType": "PlainText", "content": message}],
    }
