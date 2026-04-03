"""
api/webrtc/connect_client.py — AWS Connect client wrapper for WebRTC contacts.

Responsibility
--------------
This module owns all boto3 calls related to WebRTC contacts:

  start_webrtc_contact()          → StartWebRTCContact
  create_participant_connection() → CreateParticipantConnection (DTMF token)
  end_contact()                   → StopContact

IAM permissions required for the execution role
------------------------------------------------
The IAM role assumed by the process (Lambda execution role, ECS task role, or
EC2 instance profile) must have the following permissions:

  connect:StartWebRTCContact
      Resource: arn:aws:connect:<region>:<account>:instance/<instance-id>/contact/*

  connect:StopContact
      Resource: arn:aws:connect:<region>:<account>:instance/<instance-id>/contact/*

  connect:GetContactAttributes     (optional — for fetching attributes)
      Resource: arn:aws:connect:<region>:<account>:instance/<instance-id>/contact/*

NOTE: CreateParticipantConnection is a Connect Participant Service call
authenticated via the X-Amz-Bearer ParticipantToken header — NOT IAM.
The execution role does NOT need connectparticipant:* permissions.

Full IAM policy: see scripts/iam/webrtc_api_iam_policy.json

Reference
---------
• StartWebRTCContact:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html
• StopContact:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_StopContact.html
• CreateParticipantConnection:
  https://docs.aws.amazon.com/connect-participant/latest/APIReference/API_CreateParticipantConnection.html
• In-app / web calling guide:
  https://docs.aws.amazon.com/connect/latest/adminguide/config-com-widget2.html
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from api.webrtc.config import settings
from api.webrtc.models import (
    AllowedCapabilitiesRequest,
    AttendeeResponse,
    ConnectionDataResponse,
    MediaPlacementResponse,
    MeetingFeaturesResponse,
    MeetingResponse,
    ParticipantConnectionResponse,
    StartWebRTCContactResponse,
)

log = logging.getLogger(__name__)


# ─── Boto3 client helpers ─────────────────────────────────────────────────────

def _connect_client() -> Any:
    """
    Return a boto3 Amazon Connect client.

    boto3 automatically picks up credentials from the standard chain:
      1. Environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
      2. ~/.aws/credentials (local dev)
      3. ECS task role / EC2 instance profile / Lambda execution role (AWS)

    Using a function (not a module-level singleton) means unit tests can
    patch boto3.client without side effects on the module import.
    """
    return boto3.client("connect", region_name=settings.AWS_REGION)


def _connect_participant_client() -> Any:
    """
    Return a boto3 Connect Participant Service client.

    This client endpoint is separate from the main Connect endpoint.
    Authentication for participant operations is done via the
    X-Amz-Bearer header (the ParticipantToken), NOT via IAM credentials.
    boto3 handles this automatically when you pass participant_token to
    create_participant_connection().
    """
    return boto3.client("connectparticipant", region_name=settings.AWS_REGION)


# ─── Helper — build AllowedCapabilities dict for boto3 ───────────────────────

def _build_allowed_capabilities(
    caps: Optional[AllowedCapabilitiesRequest],
) -> Optional[dict]:
    """
    Convert the Pydantic AllowedCapabilitiesRequest model to the raw dict
    shape expected by the boto3 start_webrtc_contact() call.

    Valid values for Video / ScreenShare:
      "SEND" | "RECEIVE" | "SEND_RECEIVE" | "NONE"

    Reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_AllowedCapabilities.html
    """
    if caps is None:
        return None

    result: dict = {}

    if caps.agent:
        agent_caps: dict = {}
        if caps.agent.video:
            agent_caps["Video"] = caps.agent.video
        if caps.agent.screen_share:
            agent_caps["ScreenShare"] = caps.agent.screen_share
        if agent_caps:
            result["Agent"] = agent_caps

    if caps.customer:
        customer_caps: dict = {}
        if caps.customer.video:
            customer_caps["Video"] = caps.customer.video
        if caps.customer.screen_share:
            customer_caps["ScreenShare"] = caps.customer.screen_share
        if customer_caps:
            result["Customer"] = customer_caps

    return result or None


# ─── Helper — parse ConnectionData from StartWebRTCContact response ──────────

def _parse_connection_data(raw: dict) -> ConnectionDataResponse:
    """
    Parse the ``ConnectionData`` block from the StartWebRTCContact API response
    into strongly-typed Pydantic models.

    The raw structure returned by boto3:

    {
      "Meeting": {
        "MeetingId": "...",
        "MediaRegion": "eu-west-2",
        "MediaPlacement": {
          "AudioHostUrl":      "https://...",
          "AudioFallbackUrl":  "https://...",
          "SignalingUrl":      "wss://...",
          "TurnControlUrl":    "https://...",
          "EventIngestionUrl": "https://..."
        },
        "MeetingFeatures": {
          "Audio": {"EchoReduction": "AVAILABLE"}
        }
      },
      "Attendee": {
        "AttendeeId": "...",
        "JoinToken":  "..."   ← Valid for participant lifetime; protect like a secret
      }
    }

    Reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_ConnectionData.html
    """
    meeting_raw = raw["Meeting"]
    placement_raw = meeting_raw["MediaPlacement"]

    placement = MediaPlacementResponse(
        AudioHostUrl=placement_raw["AudioHostUrl"],
        AudioFallbackUrl=placement_raw["AudioFallbackUrl"],
        SignalingUrl=placement_raw["SignalingUrl"],
        TurnControlUrl=placement_raw["TurnControlUrl"],
        EventIngestionUrl=placement_raw["EventIngestionUrl"],
    )

    features_raw = meeting_raw.get("MeetingFeatures")
    features = MeetingFeaturesResponse(**features_raw) if features_raw else None

    meeting = MeetingResponse(
        MeetingId=meeting_raw["MeetingId"],
        MediaRegion=meeting_raw["MediaRegion"],
        MediaPlacement=placement,
        MeetingFeatures=features,
    )

    attendee_raw = raw["Attendee"]
    attendee = AttendeeResponse(
        AttendeeId=attendee_raw["AttendeeId"],
        JoinToken=attendee_raw["JoinToken"],
    )

    return ConnectionDataResponse(Meeting=meeting, Attendee=attendee)


# ─── Public API ───────────────────────────────────────────────────────────────

async def start_webrtc_contact(
    display_name: str,
    attributes: Optional[dict[str, str]] = None,
    description: Optional[str] = None,
    related_contact_id: Optional[str] = None,
    allowed_capabilities: Optional[AllowedCapabilitiesRequest] = None,
    client_token: Optional[str] = None,
) -> StartWebRTCContactResponse:
    """
    Call StartWebRTCContact and return the connection data needed by the
    Amazon Chime SDK client.

    Parameters
    ----------
    display_name            Customer name shown in the agent CCP. Required.
    attributes              Contact attributes forwarded to the Connect flow.
                            Accessible via $.Attributes.<key> in the flow.
    description             Optional text shown in the CCP task pane.
    related_contact_id      Links this contact to an existing one (e.g. after
                            a voice→WebRTC transfer).
    allowed_capabilities    Override video/screen-share defaults.
    client_token            Idempotency token.  Re-submitting with the same
                            token within 7 days returns the original ContactId
                            rather than creating a duplicate contact.

    Returns
    -------
    StartWebRTCContactResponse
        Contains:
        • contact_id        — store to end the contact later
        • participant_id    — stable customer participant identifier
        • participant_token — bearer token for participant service APIs (DTMF)
                              ⚠ treat as a secret; never log
        • connection_data   — Meeting + Attendee for Chime SDK

    Raises
    ------
    ClientError  wrapping the original botocore error with an informative log.

    AWS API reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html
    """
    client = _connect_client()

    # Build kwargs — only include optional fields when provided to keep the
    # request payload minimal and avoid unexpected defaults.
    kwargs: dict[str, Any] = {
        "InstanceId": settings.CONNECT_INSTANCE_ID,
        "ContactFlowId": settings.CONNECT_CONTACT_FLOW_ID,
        "ParticipantDetails": {"DisplayName": display_name},
        # ClientToken ensures idempotency. boto3 auto-generates a UUID if None.
        "ClientToken": client_token or str(uuid.uuid4()),
    }

    if attributes:
        kwargs["Attributes"] = attributes

    if description:
        kwargs["Description"] = description

    if related_contact_id:
        kwargs["RelatedContactId"] = related_contact_id

    caps_dict = _build_allowed_capabilities(allowed_capabilities)
    if caps_dict:
        kwargs["AllowedCapabilities"] = caps_dict

    log.info(
        "StartWebRTCContact: instance=%s flow=%s display_name=%s attributes=%s",
        settings.CONNECT_INSTANCE_ID,
        settings.CONNECT_CONTACT_FLOW_ID,
        display_name,
        list(attributes.keys()) if attributes else [],  # log keys only, not values
    )

    try:
        response = client.start_webrtc_contact(**kwargs)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_msg = exc.response["Error"]["Message"]
        log.error("StartWebRTCContact failed [%s]: %s", error_code, error_msg)
        raise

    contact_id = response["ContactId"]
    participant_id = response["ParticipantId"]
    # NOTE: participant_token is logged at DEBUG level only (never INFO/ERROR)
    # to avoid leaking it to log aggregation systems.
    log.debug("StartWebRTCContact succeeded: contact_id=%s", contact_id)

    connection_data = _parse_connection_data(response["ConnectionData"])

    return StartWebRTCContactResponse(
        contact_id=contact_id,
        participant_id=participant_id,
        # Security: participant_token is a bearer credential — never log at INFO+
        participant_token=response["ParticipantToken"],
        connection_data=connection_data,
    )


async def create_participant_connection(
    participant_token: str,
    connect_participant: bool = True,
) -> ParticipantConnectionResponse:
    """
    Call CreateParticipantConnection to obtain a ConnectionToken for DTMF.

    This is an optional step needed only when you want to send DTMF tones
    via the SendMessage API.  The Chime SDK handles the audio/video path
    independently using the Meeting + Attendee from start_webrtc_contact().

    Authentication model:  The participant_token is passed as the
    ``X-Amz-Bearer`` header — NOT via IAM SigV4.  boto3 handles this
    automatically; the execution role needs no connectparticipant:* permission.

    The returned ConnectionToken:
      • Is valid for 24 hours.
      • Grants access only to participant-scoped operations (SendMessage etc.).
      • Must be transmitted only over HTTPS.

    connection_type is always ["CONNECTION_CREDENTIALS"] — we do not request
    WEBRTC_CONNECTION here because those credentials were already supplied by
    StartWebRTCContact.

    AWS API reference:
    https://docs.aws.amazon.com/connect-participant/latest/APIReference/API_CreateParticipantConnection.html
    """
    client = _connect_participant_client()

    log.info("CreateParticipantConnection: requesting CONNECTION_CREDENTIALS")

    try:
        response = client.create_participant_connection(
            Type=["CONNECTION_CREDENTIALS"],
            ConnectParticipant=connect_participant,
            ParticipantToken=participant_token,
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_msg = exc.response["Error"]["Message"]
        log.error("CreateParticipantConnection failed [%s]: %s", error_code, error_msg)
        raise

    creds = response.get("ConnectionCredentials", {})
    log.debug("CreateParticipantConnection succeeded")

    return ParticipantConnectionResponse(
        connection_token=creds.get("ConnectionToken"),
        connection_expiry=creds.get("Expiry"),
    )


async def end_contact(contact_id: str) -> None:
    """
    Call StopContact to terminate a WebRTC contact.

    This disconnects all participants and ends the contact in the agent CCP.
    The contact record moves to the ENDED state and becomes available in
    Contact Search / Contact Lens reports.

    AWS API reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_StopContact.html
    """
    client = _connect_client()

    log.info("StopContact: contact_id=%s", contact_id)

    try:
        client.stop_contact(
            ContactId=contact_id,
            InstanceId=settings.CONNECT_INSTANCE_ID,
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        error_msg = exc.response["Error"]["Message"]
        log.error("StopContact failed [%s]: %s", error_code, error_msg)
        raise

    log.info("StopContact succeeded: contact_id=%s", contact_id)
