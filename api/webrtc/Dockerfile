# api/webrtc/Dockerfile — WebRTC Contact API container image.
#
# Builds a minimal image suitable for:
#   • Local development  (docker run -p 8080:8080 ...)
#   • ECS Fargate / App Runner
#   • Lambda container image (change CMD to Lambda RIE entrypoint if needed)
#
# Authentication: AWS IAM SigV4 (DEV_MODE=true bypasses auth for local dev).
# The container does NOT embed AWS credentials — use IAM roles (ECS task role,
# Lambda execution role, or instance profile) or env vars for local dev.
#
# Build:
#   docker build -f api/webrtc/Dockerfile -t aria-webrtc-api .
#
# Run locally (DEV_MODE skips SigV4 — local only):
#   docker run --rm -p 8080:8080 \
#     -e DEV_MODE=true \
#     -e CONNECT_INSTANCE_ID=<uuid> \
#     -e CONNECT_CONTACT_FLOW_ID=<uuid> \
#     -e AWS_REGION=eu-west-2 \
#     -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
#     -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
#     -e AWS_SESSION_TOKEN=$AWS_SESSION_TOKEN \
#     aria-webrtc-api
#
# Run in production (IAM role supplies credentials automatically):
#   docker run --rm -p 8080:8080 \
#     -e CONNECT_INSTANCE_ID=<uuid> \
#     -e CONNECT_CONTACT_FLOW_ID=<uuid> \
#     -e AWS_REGION=eu-west-2 \
#     -e ALLOWED_ORIGINS=https://app.meridianbank.com \
#     aria-webrtc-api

FROM python:3.12-slim

# Least-privilege non-root user
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements-webrtc.txt ./
RUN pip install --no-cache-dir -r requirements-webrtc.txt

# Copy only the api package (not the full repo)
COPY api/ ./api/

# Switch to non-root
USER appuser

EXPOSE 8080

# uvicorn with 2 workers; increase for higher concurrency
CMD ["uvicorn", "api.webrtc.app:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "2", \
     "--log-level", "info", \
     "--no-access-log"]
