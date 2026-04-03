"""
api/webrtc/app.py — FastAPI application: Amazon Connect WebRTC Contact API.

Purpose
-------
This API acts as the **server-side mediator** between a mobile or web
application and Amazon Connect for in-app / web WebRTC calling.

The client (browser or mobile app) MUST NOT call StartWebRTCContact directly
from the front end because:
  • That would require embedding AWS credentials in the client — a major
    security risk.
  • The ParticipantToken returned by StartWebRTCContact is a bearer credential;
    it must only be issued after the caller has been authenticated.

Call flow (per AWS official guidance)
--------------------------------------
1. Client authenticates with your identity system (Cognito / API key).
2. Client calls  POST /webrtc/start-contact  with display name + attributes.
3. This API validates auth → calls connect:StartWebRTCContact → returns:
     • ContactId          (store to end the call later)
     • ParticipantToken   (bearer token — treat as a secret)
     • ConnectionData     (Meeting + Attendee → feed directly into Chime SDK)
4. Client instantiates Chime SDK MeetingSessionConfiguration:
     const config = new MeetingSessionConfiguration(
         response.connection_data.Meeting,
         response.connection_data.Attendee
     );
5. Client starts audio:  meetingSession.audioVideo.start()
6. To send DTMF:  POST /webrtc/participant-connection  with ParticipantToken
   → returns a ConnectionToken → use with connectparticipant:SendMessage.
7. To end the call:  DELETE /webrtc/end-contact/{contact_id}

Deployment options
------------------
• AWS Lambda + API Gateway:  wrap with Mangum (see api/webrtc/lambda_handler.py)
• Docker container:  uvicorn api.webrtc.app:app --host 0.0.0.0 --port 8080
• Local dev:         uvicorn api.webrtc.app:app --port 8080 --reload

IAM / Security
--------------
Execution role needs:
  connect:StartWebRTCContact  on instance/*/contact/*
  connect:StopContact         on instance/*/contact/*
  secretsmanager:GetSecretValue on the API key secret  (if AUTH_MODE=api_key)
See scripts/iam/webrtc_api_iam_policy.json for the full policy.

References
----------
• StartWebRTCContact API:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html
• In-app, web, video calling guide:
  https://docs.aws.amazon.com/connect/latest/adminguide/config-com-widget2.html
• Chime SDK JS guide:
  https://github.com/aws/amazon-chime-sdk-js/blob/main/guides/03_API_Overview.md
• WebRTC security best practices:
  https://docs.aws.amazon.com/connect/latest/adminguide/security-best-practices.html#bp-webrtc-security
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Path, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from botocore.exceptions import ClientError

from api.webrtc import connect_client
from api.webrtc.auth import CallerIdentity, get_auth_dependency
from api.webrtc.config import settings
from api.webrtc.models import (
    CreateParticipantConnectionRequest,
    EndContactResponse,
    HealthResponse,
    ParticipantConnectionResponse,
    StartWebRTCContactRequest,
    StartWebRTCContactResponse,
)

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# ─── Lifespan (startup validation) ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(application: FastAPI):
    """
    FastAPI lifespan context manager — replaces the deprecated @app.on_event.

    On startup:
      • Validates that all required environment variables are set.
      • Logs the active auth mode so operators can confirm the deployment.

    On shutdown:
      • Nothing required — boto3 clients are stateless.
    """
    try:
        settings.validate()
    except ValueError as exc:
        log.critical("WebRTC API startup failed: %s", exc)
        raise

    log.info(
        "WebRTC Contact API starting up | region=%s instance=%s auth=aws_iam dev_mode=%s",
        settings.AWS_REGION,
        settings.CONNECT_INSTANCE_ID,
        settings.DEV_MODE,
    )
    yield
    log.info("WebRTC Contact API shutting down.")


# ─── FastAPI application ──────────────────────────────────────────────────────

app = FastAPI(
    title="Amazon Connect WebRTC Contact API",
    description=(
        "Server-side mediator for Amazon Connect in-app and web WebRTC calling. "
        "Authenticates callers before vending Chime SDK connection credentials. "
        "See https://docs.aws.amazon.com/connect/latest/adminguide/config-com-widget2.html"
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Disable automatic redirect of /path → /path/ — avoids confusing Lambda URL behaviour
    redirect_slashes=False,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Restrict to your app's origin(s) in production.
# Set ALLOWED_ORIGINS env var to e.g. "https://app.meridianbank.com"
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Global error handler for AWS ClientError ─────────────────────────────────

@app.exception_handler(ClientError)
async def aws_client_error_handler(request: Request, exc: ClientError) -> JSONResponse:
    """
    Translate boto3 ClientError into a structured HTTP response.

    Maps common Connect / Participant error codes to appropriate HTTP status
    codes so clients get meaningful errors rather than a generic 500.

    Reference:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html#API_StartWebRTCContact_Errors
    """
    error_code = exc.response["Error"]["Code"]
    error_msg = exc.response["Error"]["Message"]
    http_status = _aws_error_to_http_status(error_code)

    log.error("AWS ClientError [%s] → HTTP %s: %s", error_code, http_status, error_msg)

    return JSONResponse(
        status_code=http_status,
        content={
            "error": error_code,
            "message": error_msg,
        },
    )


def _aws_error_to_http_status(error_code: str) -> int:
    """
    Map Amazon Connect error codes to HTTP status codes.

    Source:
    https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html#API_StartWebRTCContact_Errors
    """
    mapping = {
        "InvalidParameterException": status.HTTP_400_BAD_REQUEST,
        "InvalidRequestException": status.HTTP_400_BAD_REQUEST,
        "ValidationException": status.HTTP_400_BAD_REQUEST,
        "AccessDeniedException": status.HTTP_403_FORBIDDEN,
        "ResourceNotFoundException": status.HTTP_404_NOT_FOUND,
        "LimitExceededException": status.HTTP_429_TOO_MANY_REQUESTS,
        "ThrottlingException": status.HTTP_429_TOO_MANY_REQUESTS,
        "InternalServiceException": status.HTTP_502_BAD_GATEWAY,
        "InternalServerException": status.HTTP_502_BAD_GATEWAY,
    }
    return mapping.get(error_code, status.HTTP_502_BAD_GATEWAY)


# ─── Auth dependency (resolved once at import time) ───────────────────────────
# Calling get_auth_dependency() here means the auth mode is fixed at startup.
# All protected routes inject _auth as a dependency.
_auth: Any = get_auth_dependency()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["Operations"],
)
async def health_check() -> HealthResponse:
    """
    Lightweight health check — no auth required.

    Returns whether the service is running and whether the Connect instance
    ID has been configured (does not make any AWS API call).
    Used by load-balancer / Lambda health checks.
    """
    return HealthResponse(
        connect_instance_configured=bool(settings.CONNECT_INSTANCE_ID),
    )


@app.post(
    "/webrtc/start-contact",
    response_model=StartWebRTCContactResponse,
    status_code=status.HTTP_200_OK,
    summary="Start a WebRTC contact",
    description=(
        "Creates a new in-app / web WebRTC contact in Amazon Connect and returns "
        "the Amazon Chime SDK connection credentials (Meeting + Attendee) needed "
        "to join the call. "
        "The caller must be authenticated (see AUTH_MODE). "
        "The ParticipantToken in the response is a bearer credential — treat it "
        "as a secret and never log or embed it in URLs."
    ),
    tags=["WebRTC"],
)
async def start_contact(
    body: StartWebRTCContactRequest,
    caller: CallerIdentity = Depends(_auth),
) -> StartWebRTCContactResponse:
    log.debug("start_contact: caller_arn=%s dev_mode=%s", caller.user_arn, caller.dev_mode)
    return await connect_client.start_webrtc_contact(
        display_name=body.display_name,
        attributes=body.attributes or None,
        description=body.description,
        related_contact_id=body.related_contact_id,
        allowed_capabilities=body.allowed_capabilities,
        client_token=body.client_token,
    )


@app.post(
    "/webrtc/participant-connection",
    response_model=ParticipantConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a participant ConnectionToken for DTMF",
    description=(
        "Exchanges the ParticipantToken (from start-contact) for a "
        "ConnectionToken that can be used to send DTMF tones via the "
        "Connect Participant Service SendMessage API. "
        "This endpoint is optional — only needed when DTMF support is required."
    ),
    tags=["WebRTC"],
)
async def participant_connection(
    body: CreateParticipantConnectionRequest,
    caller: CallerIdentity = Depends(_auth),
) -> ParticipantConnectionResponse:
    log.debug("participant_connection: caller_arn=%s", caller.user_arn)
    return await connect_client.create_participant_connection(
        participant_token=body.participant_token,
        connect_participant=body.connect_participant,
    )


@app.delete(
    "/webrtc/end-contact/{contact_id}",
    response_model=EndContactResponse,
    status_code=status.HTTP_200_OK,
    summary="End a WebRTC contact",
    description=(
        "Terminates the specified WebRTC contact, disconnecting all participants "
        "and completing the contact in the agent CCP. "
        "Call this when the customer hangs up or navigates away."
    ),
    tags=["WebRTC"],
)
async def end_contact(
    contact_id: str = Path(
        ...,
        min_length=1,
        max_length=256,
        description="ContactId returned by start-contact.",
    ),
    caller: CallerIdentity = Depends(_auth),
) -> EndContactResponse:
    log.debug("end_contact: contact_id=%s caller_arn=%s", contact_id, caller.user_arn)
    await connect_client.end_contact(contact_id=contact_id)
    return EndContactResponse(contact_id=contact_id)
