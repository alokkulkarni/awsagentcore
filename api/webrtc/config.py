"""
api/webrtc/config.py — Runtime configuration for the WebRTC Contact API.

All values are read from environment variables so the service is portable
across local dev, Docker, and Lambda (via API Gateway / Function URL).

Required environment variables
-------------------------------
CONNECT_INSTANCE_ID      Amazon Connect instance ID (not ARN), e.g.
                         "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
CONNECT_CONTACT_FLOW_ID  Contact-flow ID that handles inbound WebRTC contacts.
                         Must be an INBOUND flow with type CONTACT_FLOW.

Optional environment variables
-------------------------------
AWS_REGION               AWS region where the Connect instance lives.
                         Defaults to "eu-west-2".
                         Set automatically by the Lambda runtime.

ALLOWED_ORIGINS          Comma-separated CORS origins.
                         e.g. "https://app.meridianbank.com,https://localhost:3000"
                         Defaults to "*" — restrict to your domain in production.

ALLOWED_PRINCIPAL_ARNS   Comma-separated IAM principal ARN patterns that are
                         permitted to call this API.  Supports prefix wildcards
                         ending with "/*" to match any session under a role:
                           "arn:aws:sts::395402194296:assumed-role/aria-webrtc-client-role/*"
                         Leave empty to allow any IAM principal that passes the
                         SigV4 / Lambda Function URL AWS_IAM check.

DEV_MODE                 Set to "true" to skip SigV4 verification entirely.
                         Intended for local uvicorn and Docker development only.
                         ⚠ MUST be "false" (or unset) in all production
                         deployments.  Setting DEV_MODE=true disables the only
                         authentication layer.

LOG_LEVEL                Logging verbosity: DEBUG | INFO | WARNING | ERROR.
                         Defaults to "INFO".

Authentication
--------------
This API uses AWS IAM SigV4 authentication exclusively.  Callers must:

1. Obtain temporary AWS credentials via sts:AssumeRoleWithWebIdentity
   (or through a Cognito Identity Pool, which does this internally).
2. Sign every HTTP request with SigV4 (service "execute-api" for API Gateway,
   "lambda" for Lambda Function URLs).
3. The Lambda Function URL (authType=AWS_IAM) or API Gateway HTTP API
   (authorizationType=AWS_IAM) validates the signature before the request
   reaches this service.

Client IAM role:  scripts/iam/webrtc_client_role_policy.json
                  scripts/iam/webrtc_client_trust_policy.json

References
----------
• Lambda Function URL auth:
  https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html
• API Gateway IAM auth:
  https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-access-control-iam.html
• AssumeRoleWithWebIdentity:
  https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html
"""

from __future__ import annotations

import os


class _Config:
    # ── Connect (required) ────────────────────────────────────────────────────
    CONNECT_INSTANCE_ID: str = os.environ.get("CONNECT_INSTANCE_ID", "")
    CONNECT_CONTACT_FLOW_ID: str = os.environ.get("CONNECT_CONTACT_FLOW_ID", "")

    # ── AWS region ────────────────────────────────────────────────────────────
    AWS_REGION: str = os.environ.get(
        "AWS_REGION",
        os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"),
    )

    # ── IAM principal allowlist (optional) ────────────────────────────────────
    # Comma-separated ARN patterns. Supports trailing "/*" prefix matching.
    # Leave empty to allow any principal that passes the SigV4/IAM check.
    ALLOWED_PRINCIPAL_ARNS: list[str] = [
        a.strip()
        for a in os.environ.get("ALLOWED_PRINCIPAL_ARNS", "").split(",")
        if a.strip()
    ]

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = [
        o.strip()
        for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")
        if o.strip()
    ]

    # ── Dev mode (local / Docker only — disables SigV4 verification) ─────────
    DEV_MODE: bool = os.environ.get("DEV_MODE", "false").lower() == "true"

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
        if self.DEV_MODE:
            import warnings
            warnings.warn(
                "WebRTC API is running in DEV_MODE — SigV4 auth is DISABLED. "
                "Set DEV_MODE=false before deploying to production.",
                stacklevel=2,
            )


settings = _Config()
