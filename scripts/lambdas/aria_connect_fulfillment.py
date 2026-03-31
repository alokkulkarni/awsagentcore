"""
aria_connect_fulfillment.py

Lambda fulfillment function for the ARIA-Connect-Bot Lex V2 bot.
Called on every conversation turn by Amazon Lex V2.

Flow:
  Amazon Connect (PSTN voice)
    → Lex V2 + Nova Sonic S2S (speech ↔ text)
      → This Lambda (every turn)
        → ARIA AgentCore HTTP /invocations
          → ARIA Strands agent response (plain text)
        → Lex response → Nova Sonic speaks it back

Environment variables required:
  AGENTCORE_ENDPOINT  — full HTTPS URL to the AgentCore runtime invocations endpoint

Session continuity:
  ContactId from Amazon Connect is used as the AgentCore session ID.
  This keeps the Strands agent state (auth, conversation history) consistent
  across all turns of a single phone call.

Deployment:
  See docs/amazon-connect-lex-nova-sonic-setup-guide.md for full setup instructions.
"""

import json
import logging
import os
import urllib.request
import urllib.error

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

logger = logging.getLogger()
logger.setLevel(logging.INFO)

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
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")
SERVICE = "bedrock-agentcore"

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
# Lambda handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    logger.info("Lex event: %s", json.dumps(event, default=str))

    session_state = event.get("sessionState", {})
    intent_name = session_state.get("intent", {}).get("name", "FallbackIntent")
    input_transcript = event.get("inputTranscript", "").strip()
    session_attrs = session_state.get("sessionAttributes", {}) or {}

    # ContactId from Amazon Connect is passed inside requestAttributes
    request_attrs = event.get("requestAttributes", {}) or {}
    contact_id = (
        request_attrs.get("ContactId")
        or session_attrs.get("contactId")
        or event.get("sessionId", "unknown-session")
    )

    # Persist contactId in session attributes so it survives across turns
    session_attrs["contactId"] = contact_id

    logger.info(
        "Turn: intent=%s contactId=%s transcript=%r",
        intent_name,
        contact_id,
        input_transcript,
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

    # Call ARIA AgentCore
    try:
        aria_response = _call_agentcore(input_transcript, contact_id)
    except Exception as exc:
        logger.error("AgentCore call failed: %s", exc, exc_info=True)
        return _build_elicit_response(
            "I'm sorry, I'm having a technical issue right now. "
            "Please bear with me, or press zero to speak with an advisor.",
            session_attrs,
        )

    logger.info("ARIA response (session=%s): %r", contact_id, aria_response[:200])

    # Detect escalation in ARIA's response
    escalate = any(phrase in aria_response.lower() for phrase in ESCALATION_PHRASES)
    if escalate:
        session_attrs["escalate"] = "true"
        return _build_close_response(aria_response, session_attrs, escalate=True)

    return _build_elicit_response(aria_response, session_attrs)


# ---------------------------------------------------------------------------
# AgentCore HTTP invocation (SigV4 signed)
# ---------------------------------------------------------------------------
def _call_agentcore(user_message: str, session_id: str) -> str:
    """POST to AgentCore /invocations, return ARIA's plain-text response."""
    body = json.dumps({"message": user_message}).encode("utf-8")

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
# Lex V2 response builders
# ---------------------------------------------------------------------------
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
