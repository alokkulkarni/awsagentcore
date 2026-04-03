"""
api/webrtc/lambda_handler.py — AWS Lambda entry point for the WebRTC Contact API.

This module wraps the FastAPI ``app`` with Mangum so it can be deployed as an
AWS Lambda function fronted by either:

  • Lambda Function URL  (recommended — simplest, no extra API Gateway cost)
  • API Gateway HTTP API v2

Mangum translates the Lambda event into an ASGI request that FastAPI handles,
and converts the response back into the format Lambda / API Gateway expects.

Deployment
----------
Lambda handler setting:  api.webrtc.lambda_handler.handler

Authentication
--------------
This API uses AWS IAM SigV4 exclusively.  Configure the Lambda Function URL
with authType=AWS_IAM before exposing it to clients:

  aws lambda create-function-url-config \\
    --function-name aria-webrtc-api \\
    --auth-type AWS_IAM \\
    --cors '{"AllowOrigins":["https://app.meridianbank.com"],
             "AllowMethods":["POST","DELETE","GET"],
             "AllowHeaders":["*"],
             "AllowCredentials":true}'

  # Grant the client role permission to invoke the Function URL:
  aws lambda add-permission \\
    --function-name aria-webrtc-api \\
    --statement-id AllowWebRTCClientRole \\
    --action lambda:InvokeFunctionUrl \\
    --principal arn:aws:iam::<account>:role/aria-webrtc-client-role \\
    --function-url-auth-type AWS_IAM

Clients authenticate by calling sts:AssumeRoleWithWebIdentity (or using a
Cognito Identity Pool) to obtain temporary credentials, then signing requests
with SigV4 (service "lambda").  See scripts/iam/webrtc_client_role_policy.json.

Required Lambda environment variables
--------------------------------------
  CONNECT_INSTANCE_ID      Amazon Connect instance ID
  CONNECT_CONTACT_FLOW_ID  Inbound WebRTC contact flow ID
  AWS_REGION               Set automatically by the Lambda runtime

Optional Lambda environment variables
--------------------------------------
  ALLOWED_ORIGINS          Comma-separated CORS origins (default: "*")
  ALLOWED_PRINCIPAL_ARNS   Comma-separated IAM ARN patterns to allowlist
  LOG_LEVEL                DEBUG | INFO | WARNING | ERROR (default: INFO)
  DEV_MODE                 "true" only for local testing — NEVER in production

Required Lambda execution role permissions
-------------------------------------------
Attach the policy in scripts/iam/webrtc_api_iam_policy.json.
Minimum required actions:
  connect:StartWebRTCContact  on instance/*/contact/*
  connect:StopContact         on instance/*/contact/*
  connect:GetContactAttributes on instance/*/contact/*  (optional)
  logs:CreateLogGroup / CreateLogStream / PutLogEvents   (CloudWatch)

Lambda sizing recommendations
------------------------------
Memory:   256 MB  (boto3 + FastAPI fit comfortably; no heavy deps)
Timeout:  10 s    (StartWebRTCContact typically < 1 s; headroom for cold starts)
Architecture: arm64 (Graviton2 — ~20% cheaper, same performance)

Ref: https://mangum.fastapiexpert.com/
Ref: https://docs.aws.amazon.com/lambda/latest/dg/lambda-urls.html
"""

from __future__ import annotations

from api.webrtc.app import app  # FastAPI ASGI application

try:
    from mangum import Mangum

    # lifespan="off" — FastAPI lifespan events run once per Lambda container
    # (cold start), not per request.  Mangum's default "auto" re-runs them on
    # every invocation; "off" is correct for Lambda container reuse semantics.
    handler = Mangum(app, lifespan="off")

except ImportError:
    def handler(event, context):  # type: ignore[misc]
        raise ImportError(
            "Mangum is required for Lambda deployment. "
            "Add 'mangum' to requirements-webrtc.txt and redeploy."
        )
