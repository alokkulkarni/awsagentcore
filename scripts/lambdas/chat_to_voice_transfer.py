"""
chat_to_voice_transfer.py
==========================
Amazon Connect Chat → Voice (Callback) Channel Transfer Lambda

PURPOSE
-------
Called from the ARIA Unified Inbound chat flow when a chat-to-voice callback
is requested. Performs three actions:
  1. Retrieves the live chat transcript from Contact Lens (V2 API)
  2. Stores the transcript in DynamoDB for cross-session retrieval
  3. Initiates an outbound voice callback via StartOutboundVoiceContact

HOW IT IS TRIGGERED
-------------------
The ARIA Unified Inbound flow contains a "Check contact attributes" block that
checks for `requestVoiceTransfer = true`. When ARIA (or a human agent) sets
this attribute, the flow branches to this Lambda.

ARIA sets the attribute via the `request_channel_transfer` tool in aria/tools/.

ENVIRONMENT VARIABLES
---------------------
Required:
  INSTANCE_ID              — Amazon Connect instance ID
  CONTACT_FLOW_ID          — Contact flow ID for the outbound voice call
                             (usually the same Unified Inbound flow)
  QUEUE_ID                 — Queue ARN/ID for the outbound call
  SOURCE_PHONE_NUMBER      — Connect phone number for the outbound call (E.164)
  DYNAMODB_TABLE           — DynamoDB table for transcript storage (aria-transcript-store)

IAM PERMISSIONS REQUIRED
------------------------
  connect:StartOutboundVoiceContact
  connect:ListRealtimeContactAnalysisSegmentsV2
  dynamodb:PutItem (on aria-transcript-store table)
  logs:CreateLogGroup / CreateLogStream / PutLogEvents

Official docs referenced:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_StartOutboundVoiceContact.html
  https://docs.aws.amazon.com/connect/latest/APIReference/
    API_ListRealtimeContactAnalysisSegmentsV2.html
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INSTANCE_ID = os.environ.get("INSTANCE_ID", "")
CONTACT_FLOW_ID = os.environ.get("CONTACT_FLOW_ID", "")
QUEUE_ID = os.environ.get("QUEUE_ID", "")
SOURCE_PHONE_NUMBER = os.environ.get("SOURCE_PHONE_NUMBER", "")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "aria-transcript-store")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
_connect_client = None
_dynamodb_resource = None


def _connect() -> Any:
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=AWS_REGION)
    return _connect_client


def _dynamodb() -> Any:
    global _dynamodb_resource
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb_resource


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def lambda_handler(event: dict, context: Any) -> dict:
    """
    Entry point. Called synchronously from Amazon Connect chat flow.

    Returns a dict accessible in the flow via $.External.* attributes.
    On success, the flow should display a "We are calling you now" message
    then disconnect the chat (or let it remain open for reference).
    """
    logger.info(f"chat_to_voice_transfer invoked: {json.dumps(event, default=str)}")

    params = event.get("Details", {}).get("Parameters", {})
    contact_data = event.get("Details", {}).get("ContactData", {})

    chat_contact_id = params.get("contactId") or contact_data.get("ContactId", "")
    customer_id = params.get("customerId", "")
    auth_status = params.get("authStatus", "unauthenticated")
    locale = params.get("locale", "en-GB")
    customer_phone = params.get("customerPhone", "")
    agent_id = params.get("agentId", "")
    transfer_mode = params.get("transferMode", "aria")  # 'aria' or 'human'

    logger.info(
        f"Callback request: chatContactId={chat_contact_id!r} "
        f"customerId={customer_id!r} phone={customer_phone!r}"
    )

    if not chat_contact_id:
        return {"status": "error", "message": "Missing chat contact ID"}

    if not customer_phone:
        logger.error("No customer phone number provided — cannot initiate callback")
        return {"status": "error", "message": "Customer phone number is required for callback"}

    # ----------------------------------------------------------------
    # 1. Retrieve the live chat transcript from Contact Lens V2 API
    # ----------------------------------------------------------------
    segments = _retrieve_chat_transcript(chat_contact_id)
    transcript_text = _format_transcript(segments)
    transcript_summary = _build_summary(segments)
    logger.info(f"Chat transcript: {len(segments)} segments retrieved")

    # ----------------------------------------------------------------
    # 2. Store transcript in DynamoDB
    # ----------------------------------------------------------------
    _store_transcript(
        contact_id=chat_contact_id,
        customer_id=customer_id,
        channel="chat",
        transcript=transcript_text,
        summary=transcript_summary,
    )

    # ----------------------------------------------------------------
    # 3. Initiate outbound voice call via StartOutboundVoiceContact
    # ----------------------------------------------------------------
    voice_attributes = {
        "chatContactId":         chat_contact_id,
        "customerId":            customer_id,
        "authStatus":            auth_status,
        "locale":                locale,
        "channel":               "voice",
        "voiceTransferSource":   "chat",
        # Truncate to 1000 chars — contact attributes have a 32KB total limit
        "chatTranscriptSummary": transcript_summary[:1000],
        # For human agent routing — empty string means ARIA handles
        "transferToAgent":       agent_id if transfer_mode == "human" else "",
    }

    try:
        voice_response = _connect().start_outbound_voice_contact(
            DestinationPhoneNumber=customer_phone,
            InstanceId=INSTANCE_ID,
            ContactFlowId=CONTACT_FLOW_ID,
            QueueId=QUEUE_ID,
            SourcePhoneNumber=SOURCE_PHONE_NUMBER,
            Attributes=voice_attributes,
            # Link the outbound call to the original chat contact
            RelatedContactId=chat_contact_id,
            Description="Continuing conversation transferred from chat",
        )
    except Exception as exc:
        logger.error(f"StartOutboundVoiceContact failed: {exc}")
        return {"status": "error", "message": str(exc)}

    voice_contact_id = voice_response["ContactId"]
    logger.info(f"Outbound voice contact created: {voice_contact_id}")

    return {
        "status":          "success",
        "voiceContactId":  voice_contact_id,
        "callbackNumber":  customer_phone,
    }


# ---------------------------------------------------------------------------
# Contact Lens V2 chat transcript retrieval
# ---------------------------------------------------------------------------

def _retrieve_chat_transcript(contact_id: str) -> list:
    """
    Retrieves chat transcript segments from Contact Lens V2 API.

    Note: Chat uses the V2 API (ListRealtimeContactAnalysisSegmentsV2), which
    is accessed via the main Connect client (not the contact-lens client).
    The TRANSCRIPT segment type filters out non-conversation events.

    Official docs:
      https://docs.aws.amazon.com/connect/latest/APIReference/
      API_ListRealtimeContactAnalysisSegmentsV2.html
    """
    segments = []
    next_token = None

    try:
        while True:
            kwargs: dict = {
                "InstanceId":   INSTANCE_ID,
                "ContactId":    contact_id,
                "MaxResults":   100,
                "OutputType":   "Raw",
                "SegmentTypes": ["TRANSCRIPT"],
            }
            if next_token:
                kwargs["NextToken"] = next_token

            response = _connect().list_realtime_contact_analysis_segments_v2(**kwargs)
            segments.extend(response.get("Segments", []))
            next_token = response.get("NextToken")
            if not next_token:
                break

    except Exception as exc:
        logger.error(f"Error retrieving chat transcript: {exc}")

    return segments


def _format_transcript(segments: list) -> str:
    """Formats chat transcript segments into human-readable text."""
    if not segments:
        return "(Chat transcript not available)"

    lines = []
    for seg in segments:
        # V2 API segments wrap content in Transcript.Transcript (nested)
        inner = seg.get("Transcript", {})
        content = inner.get("Content", "")
        role = inner.get("ParticipantRole", "")
        if content:
            speaker = "ARIA" if role == "AGENT" else "Customer"
            lines.append(f"{speaker}: {content}")

    return "\n".join(lines) if lines else "(No chat transcript segments)"


def _build_summary(segments: list) -> str:
    """
    Creates a brief summary for the voice callback flow context injection.
    Shows the last 6 turns for readability.
    """
    lines = _format_transcript(segments).split("\n")
    if not lines or lines == ["(No chat transcript segments)"]:
        return "Customer transferred from chat conversation."

    recent = lines[-6:]
    return (
        "💬 Transferred from chat:\n"
        + "\n".join(recent)
    )


# ---------------------------------------------------------------------------
# DynamoDB transcript persistence
# ---------------------------------------------------------------------------

def _store_transcript(contact_id: str, customer_id: str, channel: str,
                       transcript: str, summary: str) -> None:
    """
    Stores the full transcript in DynamoDB (aria-transcript-store).

    The session injector reads this when a new voice contact arrives with
    voiceTransferSource = 'chat', retrieving context for ARIA's Q Connect session.

    TTL is set to 7 days.
    """
    if not DYNAMODB_TABLE:
        logger.warning("DYNAMODB_TABLE not set — transcript not persisted")
        return

    try:
        table = _dynamodb().Table(DYNAMODB_TABLE)
        table.put_item(Item={
            "contactId":   contact_id,
            "customerId":  customer_id,
            "channel":     channel,
            "transcript":  transcript,
            "summary":     summary,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "ttl":         int(time.time()) + (7 * 24 * 60 * 60),
        })
        logger.info(f"Chat transcript stored: contactId={contact_id!r}")
    except Exception as exc:
        logger.error(f"DynamoDB store failed: {exc}")
