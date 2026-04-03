"""
api/webrtc/auth.py — Authentication middleware for the WebRTC Contact API.

Why authentication matters here
--------------------------------
The StartWebRTCContact API returns a ``ParticipantToken`` — a bearer token
that grants a caller full participant-level access to a live Amazon Connect
contact session.  The AWS security guidance states:

  "Authenticate users before token issuance. Ensure that robust authentication
   and authorization checks are performed before vending a participant token to
   any client or external service."

  Source: https://docs.aws.amazon.com/connect/latest/adminguide/
          security-best-practices.html#bp-webrtc-security

This module implements two pluggable authentication strategies:

1. API-key   (AUTH_MODE=api_key)
   A static secret stored in AWS Secrets Manager.  Callers supply:
       X-API-Key: <secret>
   Best for server-to-server or mobile-app scenarios where you control
   the client and can store the key securely.

2. Cognito JWT  (AUTH_MODE=cognito)
   Validates a Bearer JWT issued by an Amazon Cognito User Pool.
   Callers supply:
       Authorization: Bearer <id_token_or_access_token>
   Best for web / mobile apps where end-users authenticate with Cognito.
   Public keys are fetched once from the Cognito JWKS endpoint and cached.

3. None  (AUTH_MODE=none)
   No authentication.  Suitable only for private VPC deployments where
   network-level controls already restrict access.  Never use in production
   without network-layer protection.

Reference
---------
• IAM permissions needed for the execution role:
  - secretsmanager:GetSecretValue  (if using api_key mode)
  No Cognito IAM permission needed — JWKS validation is done via public HTTPS.
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Optional

import boto3
from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from api.webrtc.config import settings

log = logging.getLogger(__name__)

# ─── API-key auth ─────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@lru_cache(maxsize=1)
def _get_api_key_from_secrets_manager() -> str:
    """
    Fetch the API key from Secrets Manager and cache it for the process
    lifetime (Lambda container reuse / uvicorn worker).

    The secret must be a JSON string:  {"api_key": "<value>"}

    We cache with lru_cache instead of a module-level variable so that the
    cold-start penalty is paid only once per worker, and tests can clear it
    with _get_api_key_from_secrets_manager.cache_clear().
    """
    client = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
    response = client.get_secret_value(SecretId=settings.API_KEY_SECRET_NAME)
    secret = json.loads(response["SecretString"])
    return secret["api_key"]


async def verify_api_key(x_api_key: Optional[str] = Security(_api_key_header)) -> None:
    """
    FastAPI dependency — raises 401 if the X-API-Key header is missing or wrong.

    Usage::

        @router.post("/start-contact")
        async def start_contact(
            _: None = Depends(verify_api_key), ...
        ): ...
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    try:
        expected = _get_api_key_from_secrets_manager()
    except Exception as exc:
        log.error("Failed to retrieve API key from Secrets Manager: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable.",
        ) from exc

    # Constant-time comparison to prevent timing attacks
    import hmac
    if not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


# ─── Cognito JWT auth ─────────────────────────────────────────────────────────

_bearer_scheme = HTTPBearer(auto_error=False)

# Simple in-process JWKS cache: {kid: public_key_object}
_jwks_cache: dict = {}
_jwks_cache_expiry: float = 0.0
_JWKS_TTL_SECONDS = 3600  # refresh public keys once per hour


def _get_cognito_jwks() -> dict:
    """
    Download and cache the Cognito User Pool public keys (JWKS).

    Cognito exposes its JWKS at a well-known URL:
      https://cognito-idp.<region>.amazonaws.com/<pool_id>/.well-known/jwks.json

    Keys rotate infrequently; we cache for 1 hour.

    Reference:
    https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html
    """
    global _jwks_cache, _jwks_cache_expiry
    now = time.monotonic()

    if _jwks_cache and now < _jwks_cache_expiry:
        return _jwks_cache

    import urllib.request
    jwks_url = (
        f"https://cognito-idp.{settings.AWS_REGION}.amazonaws.com"
        f"/{settings.COGNITO_USER_POOL_ID}/.well-known/jwks.json"
    )
    with urllib.request.urlopen(jwks_url, timeout=5) as resp:  # noqa: S310
        keys = json.loads(resp.read())["keys"]

    _jwks_cache = {k["kid"]: k for k in keys}
    _jwks_cache_expiry = now + _JWKS_TTL_SECONDS
    return _jwks_cache


def _verify_cognito_token(token: str) -> dict:
    """
    Validate a Cognito JWT and return its decoded claims.

    Validation steps (per AWS docs):
      1. Decode the token header to get ``kid``.
      2. Find the matching public key in the JWKS.
      3. Verify the signature using the RS256 public key.
      4. Verify ``exp`` (not expired).
      5. Verify ``iss`` matches our User Pool URL.
      6. Verify ``aud`` (id token) or ``client_id`` (access token) matches
         our App Client ID.

    Raises jwt.JWTError on any validation failure.

    Reference:
    https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html
    """
    try:
        from jose import jwt, jwk, JWTError  # python-jose
        from jose.utils import base64url_decode
    except ImportError as exc:
        raise RuntimeError(
            "python-jose is required for Cognito auth. "
            "Add 'python-jose[cryptography]' to requirements."
        ) from exc

    # Step 1 — decode header without verifying to get kid
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")

    # Step 2 — find matching public key
    jwks = _get_cognito_jwks()
    if kid not in jwks:
        raise JWTError(f"Public key '{kid}' not found in JWKS.")

    # Step 3 & 4 — verify signature + expiry
    issuer = (
        f"https://cognito-idp.{settings.AWS_REGION}.amazonaws.com"
        f"/{settings.COGNITO_USER_POOL_ID}"
    )
    claims = jwt.decode(
        token,
        jwks[kid],
        algorithms=["RS256"],
        issuer=issuer,
        # audience check: id tokens use 'aud', access tokens use 'client_id'
        options={"verify_aud": False},  # we check manually below
    )

    # Steps 5 & 6 — iss and audience
    if claims.get("iss") != issuer:
        raise JWTError("Token issuer does not match User Pool.")

    aud = claims.get("aud") or claims.get("client_id")
    if settings.COGNITO_APP_CLIENT_ID and aud != settings.COGNITO_APP_CLIENT_ID:
        raise JWTError("Token audience does not match App Client ID.")

    return claims


async def verify_cognito_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> dict:
    """
    FastAPI dependency — validates a Cognito Bearer JWT.

    Returns the decoded claims dict so routes can access the user's ``sub``,
    email, custom attributes etc. if needed.

    Usage::

        @router.post("/start-contact")
        async def start_contact(
            claims: dict = Depends(verify_cognito_jwt), ...
        ): ...
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization: Bearer <token> header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        from jose import JWTError
    except ImportError:
        JWTError = Exception  # type: ignore[misc,assignment]

    try:
        claims = _verify_cognito_token(credentials.credentials)
        return claims
    except Exception as exc:
        log.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ─── No-op auth (AUTH_MODE=none) ──────────────────────────────────────────────

async def verify_none() -> None:
    """No-op dependency used when AUTH_MODE=none (private deployments)."""
    return None


# ─── Dynamic auth selector ────────────────────────────────────────────────────

def get_auth_dependency():
    """
    Return the appropriate FastAPI dependency callable based on AUTH_MODE.

    Called once at app startup so all routes share the same dependency.

    Returns one of:
      verify_api_key     — validates X-API-Key header via Secrets Manager
      verify_cognito_jwt — validates Bearer JWT via Cognito JWKS
      verify_none        — no-op (private deployments only)
    """
    mode = settings.AUTH_MODE
    if mode == "api_key":
        log.info("WebRTC API: using API-key authentication (Secrets Manager: %s)",
                 settings.API_KEY_SECRET_NAME)
        return verify_api_key
    if mode == "cognito":
        log.info("WebRTC API: using Cognito JWT authentication (pool: %s)",
                 settings.COGNITO_USER_POOL_ID)
        return verify_cognito_jwt
    log.warning(
        "WebRTC API: AUTH_MODE=none — no authentication. "
        "Ensure network-layer controls restrict access."
    )
    return verify_none
