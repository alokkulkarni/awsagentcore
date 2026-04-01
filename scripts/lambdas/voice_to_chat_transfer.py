"""
voice_to_chat_transfer.py
==========================
Amazon Connect Voice → Chat Channel Transfer Lambda

PURPOSE
-------
Called from the ARIA Unified Inbound voice flow when a voice-to-chat transfer
is requested. Performs three actions:
  1. Retrieves the real-time voice transcript from Contact Lens
  2. Creates a new chat contact linked to the voice contact (StartChatContact)
  3. Sends an SMS with a deep link to the new chat session

HOW IT IS TRIGGERED
-------------------
The ARIA Unified Inbound flow contains a "Check contact attributes" block that
checks for the attribute `requestChatTransfer = true`. When ARIA (or a human
agent) sets this attribute, the flow branches to this Lambda via an
"Invoke AWS Lambda function" block.

ARIA sets the attribute via the `request_channel_transfer` tool in aria/tools/.

ENVIRONMENT VARIABLES
---------------------
Required:
  INSTANCE_ID              — Amazon Connect instance ID
  CONTACT_FLOW_ID          — Contact flow ID of ARIA Unified Inbound flow
  CHAT_WIDGET_URL          — Base URL of the chat widget page
                             e.g. https://app.meridianbank.co.uk/chat
  SMS_ORIGINATION_NUMBER   — SMS-enabled phone number in E.164 format
                             e.g. +441234567890
  DYNAMODB_TABLE           — DynamoDB table for transcript storage (aria-transcript-store)

Optional:
  MOBILE_APP_SCHEME        — Deep link scheme for mobile app
                             e.g. meridianbank://chat

IAM PERMISSIONS REQUIRED
------------------------
  connect:StartChatContact
  connect-contact-lens:ListRealtimeContactAnalysisSegments
  sms-voice:SendTextMessage
  dynamodb:PutItem (on aria-transcript-store table)
  logs:CreateLogGroup / CreateLogStream / PutLogEvents

Official docs referenced:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_StartChatContact.html
  https://docs.aws.amazon.com/contact-lens/latest/APIReference/API_ListRealtimeContactAnalysisSegments.html
  https://docs.aws.amazon.com/connect/latest/adminguide/setup-sms-messaging.html
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
CHAT_WIDGET_URL = os.environ.get("CHAT_WIDGET_URL", "")
MOBILE_APP_SCHEME = os.environ.get("MOBILE_APP_SCHEME", "")
SMS_ORIGINATION_NUMBER = os.environ.get("SMS_ORIGINATION_NUMBER", "")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "aria-transcript-store")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")

# ---------------------------------------------------------------------------
# AWS clients — initialised once per Lambda container
# ---------------------------------------------------------------------------
_connect_client = None
_contact_lens_client = None
_sms_client = None
_dynamodb_resource = None


def _connect() -> Any:
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=AWS_REGION)
    return _connect_client


def _contact_lens() -> Any:
    global _contact_lens_client
    if _contact_lens_client is None:
        _contact_lens_client = boto3.client("connect-contact-lens", region_name=AWS_REGION)
    return _contact_lens_client


def _sms() -> Any:
    global _sms_client
    if _sms_client is None:
        _sms_client = boto3.client("pinpoint-sms-voice-v2", region_name=AWS_REGION)
    return _sms_client


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
    Entry point. Called synchronously from Amazon Connect voice flow.

    Connect invokes Lambda with:
        event["Details"]["ContactData"]  — contact metadata
        event["Details"]["Parameters"]   — flow-configured key/value pairs

    Returns a dict that is accessible in the flow via $.External.* attributes.
    """
    logger.info(f"voice_to_chat_transfer invoked: {json.dumps(event, default=str)}")

    params = event.get("Details", {}).get("Parameters", {})
    contact_data = event.get("Details", {}).get("ContactData", {})

    voice_contact_id = params.get("contactId") or contact_data.get("ContactId", "")
    customer_id = params.get("customerId", "")
    auth_status = params.get("authStatus", "unauthenticated")
    locale = params.get("locale", "en-GB")
    customer_phone = params.get("customerPhone", "")
    agent_id = params.get("agentId", "")
    transfer_mode = params.get("transferMode", "aria")  # 'aria' or 'human'

    logger.info(
        f"Transfer request: voiceContactId={voice_contact_id!r} "
        f"customerId={customer_id!r} transferMode={transfer_mode!r}"
    )

    if not voice_contact_id:
        return {"status": "error", "message": "Missing voice contact ID"}

    # ----------------------------------------------------------------
    # 1. Retrieve the real-time voice transcript from Contact Lens
    # ----------------------------------------------------------------
    segments = _retrieve_voice_transcript(voice_contact_id)
    transcript_text = _format_transcript(segments)
    transcript_summary = _build_summary(segments)
    logger.info(f"Voice transcript: {len(segments)} segments retrieved")

    # ----------------------------------------------------------------
    # 2. Store transcript in DynamoDB before Contact Lens data expires
    # ----------------------------------------------------------------
    _store_transcript(
        contact_id=voice_contact_id,
        customer_id=customer_id,
        channel="voice",
        transcript=transcript_text,
        summary=transcript_summary,
    )

    # ----------------------------------------------------------------
    # 3. Create the new chat contact via StartChatContact
    # ----------------------------------------------------------------
    initial_message = (
        f"[Continuing from your voice call — "
        f"{datetime.now(timezone.utc).strftime('%H:%M UTC')}]\n\n"
        f"{transcript_summary}"
    )

    chat_attributes = {
        "voiceContactId":    voice_contact_id,
        "customerId":        customer_id,
        "authStatus":        auth_status,
        "locale":            locale,
        "channel":           "chat",
        "chatTransferSource": "voice",
        # If transferMode is 'human', route to the specific agent; empty = ARIA handles
        "transferToAgent":   agent_id if transfer_mode == "human" else "",
    }

    try:
        chat_response = _connect().start_chat_contact(
            InstanceId=INSTANCE_ID,
            ContactFlowId=CONTACT_FLOW_ID,
            Attributes=chat_attributes,
            ParticipantDetails={
                "DisplayName": f"Customer ({customer_id})" if customer_id else "Customer",
            },
            InitialMessage={
                "ContentType": "text/plain",
                "Content": initial_message,
            },
            # Link the new chat to the voice contact (copies attributes; links in CCP)
            RelatedContactId=voice_contact_id,
            # Keep chat open 48h — customer may not tap the link immediately
            ChatDurationInMinutes=2880,
            SupportedMessagingContentTypes=["text/plain", "text/markdown"],
        )
    except Exception as exc:
        logger.error(f"StartChatContact failed: {exc}")
        return {"status": "error", "message": str(exc)}

    chat_contact_id = chat_response["ContactId"]
    participant_token = chat_response["ParticipantToken"]
    logger.info(f"Chat created: contactId={chat_contact_id}")

    # ----------------------------------------------------------------
    # 4. Build deep links (web + optional mobile app)
    # ----------------------------------------------------------------
    web_link = f"{CHAT_WIDGET_URL}?token={participant_token}&ref={voice_contact_id}"
    mobile_link = (
        f"{MOBILE_APP_SCHEME}?token={participant_token}&ref={voice_contact_id}"
        if MOBILE_APP_SCHEME else ""
    )

    # ----------------------------------------------------------------
    # 5. Send SMS to customer
    # ----------------------------------------------------------------
    sms_sent = "false"
    if customer_phone and SMS_ORIGINATION_NUMBER:
        link_to_send = mobile_link or web_link
        sms_body = (
            "Meridian Bank: Your conversation has been transferred to chat. "
            f"Tap to continue (valid 48h): {link_to_send}"
        )
        try:
            _send_sms(customer_phone, sms_body)
            sms_sent = "true"
            logger.info(f"SMS sent to {customer_phone}")
        except Exception as exc:
            # Non-fatal — chat already exists; log and continue
            logger.warning(f"SMS send failed: {exc}")
    else:
        logger.warning("No customer phone or SMS origination number — SMS skipped")

    return {
        "status":          "success",
        "chatContactId":   chat_contact_id,
        "chatLink":        web_link,
        "mobileChatLink":  mobile_link,
        "smsSent":         sms_sent,
    }


# ---------------------------------------------------------------------------
# Contact Lens transcript retrieval
# ---------------------------------------------------------------------------

def _retrieve_voice_transcript(contact_id: str) -> list:
    """
    Retrieves all real-time transcript segments from Contact Lens.
    Uses pagination to get every segment.

    Important: data is only available for 24 hours after the call.
    Contact Lens real-time analytics must be enabled (Block 6V of unified flow).

    Official docs:
      https://docs.aws.amazon.com/contact-lens/latest/APIReference/
      API_ListRealtimeContactAnalysisSegments.html
    """
    segments = []
    next_token = None

    try:
        while True:
            kwargs: dict = {
                "InstanceId": INSTANCE_ID,
                "ContactId":  contact_id,
                "MaxResults": 100,
            }
            if next_token:
                kwargs["NextToken"] = next_token

            response = _contact_lens().list_realtime_contact_analysis_segments(**kwargs)
            segments.extend(response.get("Segments", []))
            next_token = response.get("NextToken")
            if not next_token:
                break

    except _contact_lens().exceptions.ResourceNotFoundException:
        logger.warning(
            f"Contact Lens data not found for {contact_id!r}. "
            "Ensure Contact Lens real-time analytics is enabled in the voice flow."
        )
    except Exception as exc:
        logger.error(f"Error retrieving voice transcript: {exc}")

    return segments


def _format_transcript(segments: list) -> str:
    """Formats Contact Lens transcript segments into human-readable text."""
    if not segments:
        return "(Voice transcript not available)"

    lines = []
    for seg in segments:
        t = seg.get("Transcript", {})
        content = t.get("Content", "")
        role = t.get("ParticipantRole", "")
        if content:
            speaker = "ARIA" if role == "AGENT" else "Customer"
            lines.append(f"{speaker}: {content}")

    return "\n".join(lines) if lines else "(No transcript segments)"


def _build_summary(segments: list) -> str:
    """
    Creates a readable summary for the chat initial message.
    Shows the last 6 turns to keep the header concise.
    In production, this could call Amazon Bedrock for an AI-generated summary.
    """
    if not segments:
        return "Your voice conversation has been transferred to chat."

    lines = []
    for seg in segments:
        t = seg.get("Transcript", {})
        content = t.get("Content", "")
        if content:
            role = t.get("ParticipantRole", "")
            speaker = "ARIA" if role == "AGENT" else "You"
            lines.append(f"{speaker}: {content}")

    if not lines:
        return "Your voice conversation has been transferred to chat."

    recent = lines[-6:]
    return (
        "📞 **Transferred from voice call** — here is what was discussed:\n\n"
        + "\n".join(recent)
        + "\n\n---\nContinue the conversation below:"
    )


# ---------------------------------------------------------------------------
# DynamoDB transcript persistence
# ---------------------------------------------------------------------------

def _store_transcript(contact_id: str, customer_id: str, channel: str,
                       transcript: str, summary: str) -> None:
    """
    Stores the full transcript and summary in DynamoDB.

    This is essential because Contact Lens real-time voice data expires after 24 hours.
    The session injector reads from this table when a new chat contact arrives and
    the chatTransferSource attribute is 'voice'.

    TTL is set to 7 days (604800 seconds from now).
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
        logger.info(f"Transcript stored in DynamoDB: contactId={contact_id!r}")
    except Exception as exc:
        logger.error(f"DynamoDB store failed: {exc}")


# ---------------------------------------------------------------------------
# SMS delivery via AWS End User Messaging SMS
# ---------------------------------------------------------------------------

def _send_sms(destination: str, body: str) -> None:
    """
    Sends a transactional SMS via AWS End User Messaging SMS (Pinpoint SMS V2).

    The origination number must be:
      1. Procured via the AWS End User Messaging SMS console
      2. Associated with your Connect instance (Channels → SMS)

    Official docs:
      https://docs.aws.amazon.com/connect/latest/adminguide/setup-sms-messaging.html
      https://docs.aws.amazon.com/pinpoint-sms-voice/latest/APIReference/
             API_SendTextMessage.html
    """
    _sms().send_text_message(
        DestinationPhoneNumber=destination,
        OriginationIdentity=SMS_ORIGINATION_NUMBER,
        MessageBody=body,
        MessageType="TRANSACTIONAL",
    )
