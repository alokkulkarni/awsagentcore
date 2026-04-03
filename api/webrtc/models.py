"""
api/webrtc/models.py — Pydantic request / response models for the WebRTC API.

Using Pydantic v2 (model_config instead of class Config).

Data shapes mirror the Amazon Connect API exactly so that the caller can feed
the response directly into the Amazon Chime SDK without any reshaping.

Reference
---------
• StartWebRTCContact request/response:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html
• ConnectionData (Meeting + Attendee):
  https://docs.aws.amazon.com/connect/latest/APIReference/API_ConnectionData.html
• CreateParticipantConnection (WEBRTC_CONNECTION type):
  https://docs.aws.amazon.com/connect-participant/latest/APIReference/API_CreateParticipantConnection.html
• Chime SDK MeetingSessionConfiguration:
  https://aws.github.io/amazon-chime-sdk-js/classes/meetingsessionconfiguration.html
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


# ─── Request models ──────────────────────────────────────────────────────────

class ParticipantCapabilitiesRequest(BaseModel):
    """
    Video and screen-share capability flags for one participant role.

    Valid values for each field: "SEND" | "RECEIVE" | "SEND_RECEIVE" | "NONE".
    Omit a field to use the Connect instance default.

    Ref: https://docs.aws.amazon.com/connect/latest/APIReference/API_ParticipantCapabilities.html
    """
    video: Optional[str] = Field(None, alias="Video")
    screen_share: Optional[str] = Field(None, alias="ScreenShare")

    model_config = {"populate_by_name": True}


class AllowedCapabilitiesRequest(BaseModel):
    """
    Per-role capability overrides sent to StartWebRTCContact.

    Both fields are optional.  Omit entirely to use the Connect instance
    defaults configured in the Communication Widget.

    Ref: https://docs.aws.amazon.com/connect/latest/APIReference/API_AllowedCapabilities.html
    """
    agent: Optional[ParticipantCapabilitiesRequest] = Field(None, alias="Agent")
    customer: Optional[ParticipantCapabilitiesRequest] = Field(None, alias="Customer")

    model_config = {"populate_by_name": True}


class StartWebRTCContactRequest(BaseModel):
    """
    Body accepted by POST /webrtc/start-contact.

    Fields
    ------
    display_name        Customer-facing display name shown in the agent CCP.
                        Required; 1–256 characters.
    attributes          Key-value pairs forwarded to the Connect contact as
                        contact attributes.  Accessible in flows via
                        $.Attributes.<key>.  Max 32,768 UTF-8 bytes total.
    description         Free-text description visible in the CCP task pane.
    related_contact_id  Links this WebRTC contact to an existing contact (e.g.
                        after a voice→chat transfer).  Optional.
    allowed_capabilities  Override video/screen-share capabilities.  Optional.
    client_token        Idempotency token.  If omitted the boto3 SDK generates
                        one automatically.  Re-use the same token within 7 days
                        to receive the same ContactId instead of a duplicate.
    """

    display_name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Customer display name shown to the agent in the CCP.",
    )
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Contact attributes forwarded to the Connect flow.",
    )
    description: Optional[str] = Field(
        None,
        max_length=4096,
        description="Optional description visible in the CCP task pane.",
    )
    related_contact_id: Optional[str] = Field(
        None,
        max_length=256,
        description="Link this contact to an existing contact ID.",
    )
    allowed_capabilities: Optional[AllowedCapabilitiesRequest] = Field(
        None,
        description="Override default video / screen-share capabilities.",
    )
    client_token: Optional[str] = Field(
        None,
        max_length=500,
        description="Idempotency token.  Auto-generated if omitted.",
    )

    @model_validator(mode="after")
    def _validate_attribute_size(self) -> "StartWebRTCContactRequest":
        """
        Enforce the 32,768-byte limit on contact attributes.

        Reference:
        https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html
        """
        total = sum(
            len(k.encode()) + len(v.encode())
            for k, v in self.attributes.items()
        )
        if total > 32_768:
            raise ValueError(
                f"Contact attributes exceed 32,768 UTF-8 bytes ({total} bytes used)."
            )
        return self


class CreateParticipantConnectionRequest(BaseModel):
    """
    Body accepted by POST /webrtc/participant-connection.

    Used after StartWebRTCContact to obtain a ConnectionToken for sending
    DTMF digits via the Connect Participant Service SendMessage API.

    participant_token   The ParticipantToken returned by start-contact.
    connect_participant Mark the participant as "connected" (required for
                        non-streaming scenarios; defaults to True).

    Reference:
    https://docs.aws.amazon.com/connect-participant/latest/APIReference/API_CreateParticipantConnection.html
    """

    participant_token: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="ParticipantToken from the start-contact response.",
    )
    connect_participant: bool = Field(
        True,
        description="Mark participant as connected in the session.",
    )


# ─── Response models ─────────────────────────────────────────────────────────

class MediaPlacementResponse(BaseModel):
    """
    Chime SDK media endpoint URLs returned inside the Meeting object.

    The Chime SDK MeetingSessionConfiguration constructor accepts this object
    directly (camelCase field names match the SDK's MediaPlacement interface).

    Reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_MediaPlacement.html
    """
    AudioHostUrl: str
    AudioFallbackUrl: str
    SignalingUrl: str
    TurnControlUrl: str
    EventIngestionUrl: str


class MeetingFeaturesResponse(BaseModel):
    """Echo-reduction and other feature flags for the Chime meeting."""
    Audio: Optional[dict[str, Any]] = None


class MeetingResponse(BaseModel):
    """
    Amazon Chime SDK Meeting object.

    Pass this directly as the first argument to
    ``new MeetingSessionConfiguration(meeting, attendee)`` in the JS SDK or
    the equivalent iOS / Android constructor.

    Reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_Meeting.html
    """
    MeetingId: str
    MediaRegion: str
    MediaPlacement: MediaPlacementResponse
    MeetingFeatures: Optional[MeetingFeaturesResponse] = None


class AttendeeResponse(BaseModel):
    """
    Amazon Chime SDK Attendee object.

    Pass this directly as the second argument to
    ``new MeetingSessionConfiguration(meeting, attendee)`` in the JS SDK.

    Reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_Attendee.html
    """
    AttendeeId: str
    JoinToken: str


class ConnectionDataResponse(BaseModel):
    """
    Full connection data block from StartWebRTCContact.

    Contains both the Meeting and Attendee needed to instantiate a Chime SDK
    ``DefaultMeetingSession``.

    Reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_ConnectionData.html
    """
    Meeting: MeetingResponse
    Attendee: AttendeeResponse


class StartWebRTCContactResponse(BaseModel):
    """
    Response returned by POST /webrtc/start-contact.

    Fields
    ------
    contact_id          Unique ID for this contact.  Store this to end the
                        contact later via DELETE /webrtc/end-contact/{id}.
    participant_id      Stable identifier for the customer participant
                        throughout the contact lifecycle.
    participant_token   Bearer token identifying the customer within the
                        contact session.

                        SECURITY: Treat like a password.
                        • Never log this value.
                        • Transmit only over HTTPS/TLS.
                        • Use it to call CreateParticipantConnection if DTMF
                          is needed; then discard.
                        Ref: https://docs.aws.amazon.com/connect/latest/adminguide/
                             security-best-practices.html#bp-webrtc-security

    connection_data     Meeting + Attendee objects for the Chime SDK.
                        Pass to ``new MeetingSessionConfiguration(
                            response.connection_data.Meeting,
                            response.connection_data.Attendee
                        )``.
    """

    contact_id: str
    participant_id: str
    participant_token: str = Field(
        description=(
            "Bearer token for the customer participant. "
            "Treat as a secret — do not log or embed in URLs."
        )
    )
    connection_data: ConnectionDataResponse


class ParticipantConnectionResponse(BaseModel):
    """
    Response from POST /webrtc/participant-connection.

    connection_token    Credential used to call the Connect Participant
                        Service APIs (e.g. SendMessage for DTMF).
                        Valid for 24 hours from issue.
    connection_expiry   ISO-8601 expiry timestamp for the connection_token.
    webrtc_connection   Meeting + Attendee for rejoining the call (optional;
                        present when Type=WEBRTC_CONNECTION was requested).

    Reference:
    https://docs.aws.amazon.com/connect-participant/latest/APIReference/API_CreateParticipantConnection.html
    """

    connection_token: Optional[str] = None
    connection_expiry: Optional[str] = None
    webrtc_connection: Optional[dict[str, Any]] = Field(
        None,
        description="WebRTCConnection block if WEBRTC_CONNECTION type requested.",
    )


class EndContactResponse(BaseModel):
    """Response from DELETE /webrtc/end-contact/{contact_id}."""
    contact_id: str
    status: str = "ended"
    message: str = "Contact ended successfully."


class HealthResponse(BaseModel):
    """Response from GET /health."""
    status: str = "ok"
    service: str = "webrtc-contact-api"
    connect_instance_configured: bool
