"""
api/webrtc/config.py — Runtime configuration for the WebRTC Contact API.

All values are read from environment variables so the service is portable
across local dev, Docker, and Lambda (via API Gateway / Function URL).

Required environment variables
-------------------------------
CONNECT_INSTANCE_ID      Amazon Connect instance ID (not ARN) e.g.
                         "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
CONNECT_CONTACT_FLOW_ID  Contact-flow ID that handles inbound WebRTC contacts.
                         Must be an INBOUND flow with type CONTACT_FLOW.
AWS_REGION               AWS region where the Connect instance lives, e.g.
                         "eu-west-2".

Optional / authentication environment variables
------------------------------------------------
API_KEY_SECRET_NAME      AWS Secrets Manager secret name that holds a JSON
                         object {"api_key": "<value>"}.  When set, callers
                         must supply  X-API-Key: <value>  header.
                         If unset, API-key auth is disabled (fine for private
                         VPCs; never expose the API publicly without auth).

COGNITO_USER_POOL_ID     Cognito User Pool ID for JWT validation, e.g.
                         "eu-west-2_AbCdEfGhI".  When set, callers must
                         supply a valid Bearer token issued by that pool.
COGNITO_APP_CLIENT_ID    Cognito App Client ID (audience claim).

ALLOWED_ORIGINS          Comma-separated CORS origins, e.g.
                         "https://app.meridianbank.com,https://localhost:3000"
                         Defaults to "*" (restrict in production).

AUTH_MODE                One of "api_key" | "cognito" | "none".
                         Defaults to "api_key" if API_KEY_SECRET_NAME is set,
                         "cognito" if COGNITO_USER_POOL_ID is set, else "none".
                         Explicit value always wins.

Reference
---------
• StartWebRTCContact API:
  https://docs.aws.amazon.com/connect/latest/APIReference/API_StartWebRTCContact.html
• Amazon Connect in-app / web calling:
  https://docs.aws.amazon.com/connect/latest/adminguide/config-com-widget2.html
• WebRTC security best practices:
  https://docs.aws.amazon.com/connect/latest/adminguide/security-best-practices.html#bp-webrtc-security
"""

from __future__ import annotations

import os


class _Config:
    # ── Connect ───────────────────────────────────────────────────────────────
    CONNECT_INSTANCE_ID: str = os.environ.get("CONNECT_INSTANCE_ID", "")
    CONNECT_CONTACT_FLOW_ID: str = os.environ.get("CONNECT_CONTACT_FLOW_ID", "")
    AWS_REGION: str = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"))

    # ── Authentication ────────────────────────────────────────────────────────
    API_KEY_SECRET_NAME: str = os.environ.get("API_KEY_SECRET_NAME", "")
    COGNITO_USER_POOL_ID: str = os.environ.get("COGNITO_USER_POOL_ID", "")
    COGNITO_APP_CLIENT_ID: str = os.environ.get("COGNITO_APP_CLIENT_ID", "")

    # Derive auth mode from presence of secrets unless explicitly overridden
    _explicit_auth_mode: str = os.environ.get("AUTH_MODE", "")

    @property
    def AUTH_MODE(self) -> str:
        if self._explicit_auth_mode:
            return self._explicit_auth_mode.lower()
        if self.API_KEY_SECRET_NAME:
            return "api_key"
        if self.COGNITO_USER_POOL_ID:
            return "cognito"
        return "none"

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = [
        o.strip()
        for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
        if o.strip()
    ]

    # ── Misc ──────────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

    def validate(self) -> None:
        """Raise ValueError on startup if required env vars are absent."""
        missing = []
        if not self.CONNECT_INSTANCE_ID:
            missing.append("CONNECT_INSTANCE_ID")
        if not self.CONNECT_CONTACT_FLOW_ID:
            missing.append("CONNECT_CONTACT_FLOW_ID")
        if missing:
            raise ValueError(
                f"Required environment variables not set: {', '.join(missing)}"
            )


settings = _Config()
