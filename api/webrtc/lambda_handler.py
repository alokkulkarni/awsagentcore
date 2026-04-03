"""
api/webrtc/lambda_handler.py — AWS Lambda entry point for the WebRTC Contact API.

This module wraps the FastAPI ``app`` with Mangum so it can be deployed as an
AWS Lambda function fronted by either:

  • API Gateway (HTTP API or REST API)
  • Lambda Function URL

Mangum translates the API Gateway / Function URL event format into an ASGI
request that FastAPI can handle, and converts the FastAPI response back into
the event-response format that Lambda / API Gateway expects.

Deployment
----------
Lambda handler setting:  api.webrtc.lambda_handler.handler

Required Lambda environment variables
--------------------------------------
  CONNECT_INSTANCE_ID      Amazon Connect instance ID
  CONNECT_CONTACT_FLOW_ID  Inbound WebRTC contact flow ID
  AWS_REGION               AWS region (set automatically by Lambda runtime)
  AUTH_MODE                "api_key" | "cognito" | "none"
  API_KEY_SECRET_NAME      (if AUTH_MODE=api_key) Secrets Manager secret name
  COGNITO_USER_POOL_ID     (if AUTH_MODE=cognito) Cognito User Pool ID
  COGNITO_APP_CLIENT_ID    (if AUTH_MODE=cognito) App Client ID
  ALLOWED_ORIGINS          Comma-separated CORS origins

Required Lambda execution role permissions
-------------------------------------------
Attach the policy in scripts/iam/webrtc_api_iam_policy.json.
Minimum required actions:
  connect:StartWebRTCContact        on instance/*/contact/*
  connect:StopContact               on instance/*/contact/*
  secretsmanager:GetSecretValue     on the API key secret  (api_key mode only)

Lambda sizing recommendations
------------------------------
Memory:   256 MB  (boto3 + FastAPI + python-jose fit comfortably)
Timeout:  10 s    (StartWebRTCContact typically < 1 s; allow for cold starts)
Concurrency: reserve based on expected concurrent WebRTC sessions

Reference
---------
• Mangum ASGI adapter for Lambda:  https://mangum.fastapiexpert.com/
• Lambda Function URLs:
  https://docs.aws.amazon.com/lambda/latest/dg/lambda-urls.html
• API Gateway HTTP API Lambda proxy:
  https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html
"""

from __future__ import annotations

from api.webrtc.app import app  # FastAPI ASGI application

try:
    from mangum import Mangum

    # lifespan="off" prevents Mangum from running FastAPI lifespan events on
    # every Lambda invocation (those run once per container, not per request).
    # Set lifespan="auto" if you need startup/shutdown hooks per invocation.
    handler = Mangum(app, lifespan="off")

except ImportError:
    # Mangum is an optional dependency — not needed for Docker/local deployments.
    # If this module is imported in a non-Lambda environment, expose a clear error.
    def handler(event, context):  # type: ignore[misc]
        raise ImportError(
            "Mangum is required for Lambda deployment. "
            "Add 'mangum' to requirements.txt and redeploy."
        )
