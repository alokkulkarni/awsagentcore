"""
api/webrtc/auth.py — AWS IAM / SigV4 authentication for the WebRTC Contact API.

Authentication model
--------------------
The only supported authentication mode is **AWS IAM SigV4** via
``AssumeRoleWithWebIdentity``.  No API keys or Cognito JWTs are used.

Why SigV4 + AssumeRoleWithWebIdentity?
---------------------------------------
• No long-term secrets ever leave AWS.
• The ParticipantToken returned by StartWebRTCContact is a bearer credential;
  AWS guidance mandates authentication before token issuance.
• SigV4 signature verification is performed by the **infrastructure layer**
  (Lambda Function URL authType=AWS_IAM or API Gateway authorizationType=AWS_IAM),
  not by application code.  The application reads the verified caller identity
  that the infrastructure injects into each request.

End-to-end call flow
--------------------
1. Client authenticates with an OIDC/OAuth2 identity provider (Cognito User
   Pool, Google, Auth0, …) and receives an **ID token**.

2. Client exchanges the ID token for temporary AWS credentials by calling
   ``sts:AssumeRoleWithWebIdentity``:

     # AWS CLI
     aws sts assume-role-with-web-identity \
       --role-arn arn:aws:iam::<account>:role/aria-webrtc-client-role \
       --role-session-name <user-id> \
       --web-identity-token <id-token>

     # Python (boto3)
     sts = boto3.client("sts")
     resp = sts.assume_role_with_web_identity(
         RoleArn="arn:aws:iam::<account>:role/aria-webrtc-client-role",
         RoleSessionName="<user-id>",
         WebIdentityToken="<id-token>",
     )
     creds = resp["Credentials"]
     # creds = { AccessKeyId, SecretAccessKey, SessionToken, Expiration }

   Alternatively, a **Cognito Identity Pool** calls AssumeRoleWithWebIdentity
   internally — the client uses ``fetchAuthSession()`` (Amplify) or the
   Cognito Identity SDK to get the same temporary credentials.

   Ref: https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html

3. Client signs every HTTP request with SigV4 using the temporary credentials:

     # Python (requests-aws4auth)
     from requests_aws4auth import AWS4Auth
     auth = AWS4Auth(
         creds["AccessKeyId"], creds["SecretAccessKey"],
         region, "execute-api",
         session_token=creds["SessionToken"],
     )
     requests.post(url, auth=auth, json=body)

     # JavaScript (@aws-sdk/signature-v4)
     import { SignatureV4 } from "@smithy/signature-v4";
     import { Sha256 } from "@aws-crypto/sha256-browser";
     const signer = new SignatureV4({ credentials, region, service: "execute-api", sha256: Sha256 });
     const signed = await signer.sign(httpRequest);

4. **Lambda Function URL** (authType=AWS_IAM) or **API Gateway HTTP API**
   (authorizationType=AWS_IAM) validates the SigV4 signature.
   On success, the verified caller identity is injected into the Lambda event:

     # Lambda Function URL event
     event["requestContext"]["authorizer"]["iam"] == {
         "accessKey": "ASIA...",
         "accountId": "395402194296",
         "callerId": "AROA...:session-name",
         "cognitoIdentity": null,          # present when via Cognito Identity Pool
         "principalOrgId": null,
         "userArn": "arn:aws:sts::395402194296:assumed-role/aria-webrtc-client-role/session-name",
         "userId": "AROA...:session-name",
     }

   Ref: https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html
   Ref: https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-access-control-iam.html

5. **This module** reads the injected identity from the ASGI scope (Mangum
   places the raw Lambda event at ``request.scope["aws.event"]``) and
   optionally enforces an ``ALLOWED_PRINCIPAL_ARNS`` allowlist.

   In local / Docker dev (``DEV_MODE=true``), the infrastructure layer is
   absent.  The dependency returns a synthetic ``CallerIdentity`` with
   ``dev_mode=True`` so routes can distinguish the deployment context.

Infrastructure setup
--------------------
# Lambda Function URL — AWS_IAM auth:
aws lambda create-function-url-config \
  --function-name aria-webrtc-api \
  --auth-type AWS_IAM \
  --cors '{"AllowOrigins":["https://app.meridianbank.com"],"AllowMethods":["POST","DELETE","GET"],"AllowHeaders":["*"]}'

# Grant the client IAM role permission to call the Function URL:
aws lambda add-permission \
  --function-name aria-webrtc-api \
  --statement-id AllowWebRTCClientRole \
  --action lambda:InvokeFunctionUrl \
  --principal arn:aws:iam::<account>:role/aria-webrtc-client-role \
  --function-url-auth-type AWS_IAM

# API Gateway HTTP API alternative:
aws apigatewayv2 update-route \
  --api-id <api-id> --route-id <route-id> \
  --authorization-type AWS_IAM

Client IAM role:  see scripts/iam/webrtc_client_role_policy.json
                      scripts/iam/webrtc_client_trust_policy.json
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request, status

from api.webrtc.config import settings

log = logging.getLogger(__name__)


# ─── Caller identity dataclass ────────────────────────────────────────────────

@dataclass(frozen=True)
class CallerIdentity:
    """
    Verified AWS IAM identity of the request caller.

    Populated from the Lambda event context injected by:
      • Lambda Function URL (authType=AWS_IAM)
      • API Gateway HTTP API (authorizationType=AWS_IAM)

    Fields mirror the ``requestContext.authorizer.iam`` block of the Lambda
    event.  See:
    https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html

    Attributes
    ----------
    user_arn        Full assumed-role ARN, e.g.
                    ``arn:aws:sts::123456789012:assumed-role/aria-webrtc-client-role/alice``
    user_id         Caller ID in the form ``AROAID:session-name``.
    account_id      12-digit AWS account number of the caller.
    access_key      Temporary access key ID (ASIA…).
    dev_mode        True when running locally / in Docker without the
                    Lambda infrastructure layer (DEV_MODE=true env var).
                    Routes may use this to skip per-caller logging.
    """
    user_arn: str
    user_id: str
    account_id: str
    access_key: str
    dev_mode: bool = False


# ─── Identity extraction helpers ─────────────────────────────────────────────

def _extract_iam_context_from_scope(scope: dict) -> Optional[dict]:
    """
    Pull the ``requestContext.authorizer.iam`` block from the raw Lambda event
    that Mangum injects into the ASGI scope under the key ``"aws.event"``.

    Returns None when the key is absent (local uvicorn, Docker without a proxy,
    or API Gateway integrations that use a different context shape).

    Mangum docs: https://mangum.fastapiexpert.com/
    Lambda URL event shape:
      https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html
    """
    event: Optional[dict] = scope.get("aws.event")
    if not event:
        return None
    return (
        event.get("requestContext", {})
             .get("authorizer", {})
             .get("iam")
    )


def _extract_iam_context_from_apigw(scope: dict) -> Optional[dict]:
    """
    API Gateway HTTP API v2 payload format injects the caller identity at
    ``requestContext.authorizer.iam`` identically to the Function URL shape,
    but some integrations use ``requestContext.identity`` (REST API / v1).

    This helper tries the v1 REST API shape as a fallback.
    """
    event: Optional[dict] = scope.get("aws.event")
    if not event:
        return None
    identity = event.get("requestContext", {}).get("identity")
    if not identity:
        return None
    # REST API shape uses userArn / userAgent instead of the iam sub-object.
    user_arn = identity.get("userArn", "")
    if not user_arn:
        return None
    return {
        "userArn": user_arn,
        "userId": identity.get("caller", ""),
        "accountId": identity.get("accountId", ""),
        "accessKey": identity.get("accessKey", ""),
    }


# ─── FastAPI dependency ───────────────────────────────────────────────────────

async def verify_aws_iam(request: Request) -> CallerIdentity:
    """
    FastAPI dependency — extract and validate the AWS IAM caller identity.

    Behaviour per deployment context
    ---------------------------------
    Lambda Function URL / API Gateway (production)
        The infrastructure has already validated the SigV4 signature.
        This function reads the verified identity from the Mangum-injected
        Lambda event scope.  An optional ALLOWED_PRINCIPAL_ARNS allowlist is
        enforced if configured.

    Local uvicorn / Docker (DEV_MODE=true)
        No Lambda infrastructure layer is present.  Returns a synthetic
        ``CallerIdentity`` with ``dev_mode=True`` so callers are clearly
        identifiable as unauthenticated dev sessions.
        ⚠ Never set DEV_MODE=true in production.

    Parameters
    ----------
    request     FastAPI Request — used to access ``request.scope``.

    Returns
    -------
    CallerIdentity
        The verified caller.  Routes receive this as their dependency result
        and may log ``caller.user_arn`` for audit purposes.

    Raises
    ------
    HTTP 401    If the Lambda event context is absent (infrastructure
                misconfiguration) and DEV_MODE is not enabled.
    HTTP 403    If ALLOWED_PRINCIPAL_ARNS is configured and the caller's
                ARN does not match any allowed pattern.
    """
    # ── DEV_MODE bypass (local / Docker only) ────────────────────────────────
    if settings.DEV_MODE:
        log.warning(
            "WebRTC API: DEV_MODE=true — skipping SigV4 verification. "
            "This MUST NOT be used in production."
        )
        return CallerIdentity(
            user_arn="arn:aws:iam::000000000000:user/dev-local",
            user_id="dev-local",
            account_id="000000000000",
            access_key="AKIAIOSFODNN7EXAMPLE",
            dev_mode=True,
        )

    # ── Extract IAM context from Mangum-injected Lambda event ────────────────
    iam_ctx = (
        _extract_iam_context_from_scope(request.scope)
        or _extract_iam_context_from_apigw(request.scope)
    )

    if not iam_ctx:
        # The request arrived without a Lambda event context, meaning:
        #   a) The Function URL / API Gateway is not configured for AWS_IAM auth.
        #   b) The service is running without a proxy (set DEV_MODE=true for local).
        log.error(
            "WebRTC API: IAM context missing from request scope. "
            "Ensure Lambda Function URL authType=AWS_IAM (or set DEV_MODE=true locally)."
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Request must be signed with AWS SigV4 credentials obtained via "
                "sts:AssumeRoleWithWebIdentity. "
                "See scripts/iam/webrtc_client_role_policy.json."
            ),
        )

    user_arn = iam_ctx.get("userArn", "")
    user_id = iam_ctx.get("userId", "") or iam_ctx.get("callerId", "")
    account_id = iam_ctx.get("accountId", "")
    access_key = iam_ctx.get("accessKey", "")

    identity = CallerIdentity(
        user_arn=user_arn,
        user_id=user_id,
        account_id=account_id,
        access_key=access_key,
    )

    # ── Optional principal ARN allowlist ─────────────────────────────────────
    if settings.ALLOWED_PRINCIPAL_ARNS:
        if not _is_principal_allowed(user_arn, settings.ALLOWED_PRINCIPAL_ARNS):
            log.warning(
                "WebRTC API: caller %s not in ALLOWED_PRINCIPAL_ARNS", user_arn
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caller principal is not authorised to access this API.",
            )

    log.debug("WebRTC API: authenticated caller arn=%s account=%s", user_arn, account_id)
    return identity


def _is_principal_allowed(caller_arn: str, allowed: list[str]) -> bool:
    """
    Check whether ``caller_arn`` matches any pattern in ``allowed``.

    Supports exact matches and prefix wildcards ending with ``/*``, e.g.:
      "arn:aws:sts::395402194296:assumed-role/aria-webrtc-client-role/*"

    The trailing ``/*`` is replaced with a prefix check so that any session
    name under the role is accepted.
    """
    for pattern in allowed:
        if pattern.endswith("/*"):
            if caller_arn.startswith(pattern[:-2]):
                return True
        elif caller_arn == pattern:
            return True
    return False


# ─── Selector (kept for backward-compat import in app.py) ────────────────────

def get_auth_dependency():
    """Return the SigV4 IAM auth dependency (the only supported mode)."""
    log.info(
        "WebRTC API: auth=aws_iam | dev_mode=%s | allowed_principals=%d",
        settings.DEV_MODE,
        len(settings.ALLOWED_PRINCIPAL_ARNS),
    )
    return verify_aws_iam
