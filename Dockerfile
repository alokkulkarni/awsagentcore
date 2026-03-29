# ARIA Banking Agent — Amazon Bedrock AgentCore Runtime Container
#
# Build:  docker buildx build --platform linux/arm64 -t aria-agentcore .
# Run:    docker run --platform linux/arm64 -p 8080:8080 \
#           -e AWS_ACCESS_KEY_ID=... -e AWS_SECRET_ACCESS_KEY=... \
#           -e AWS_REGION=eu-west-2 aria-agentcore
#
# AgentCore requires linux/arm64. When using `agentcore deploy --local-build`
# the CLI handles the platform flag automatically.

FROM python:3.12-slim

# Metadata
LABEL org.opencontainers.image.title="ARIA — Meridian Bank AgentCore Agent"
LABEL org.opencontainers.image.description="ARIA banking agent (chat + voice) for Amazon Bedrock AgentCore Runtime"

# Non-root user for least-privilege execution
RUN groupadd --gid 1001 aria && useradd --uid 1001 --gid aria --shell /bin/bash --create-home aria

WORKDIR /app

# Install Python dependencies first (layer cached unless requirements change)
COPY requirements-docker.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements-docker.txt

# Copy application code
COPY aria/ ./aria/
COPY pyproject.toml .

# Switch to non-root
RUN chown -R aria:aria /app
USER aria

# AgentCore Runtime expects the app on port 8080
EXPOSE 8080

# Healthcheck — AgentCore polls /ping
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping')"

# Single worker: session cache is in-process memory; microVM isolation ensures
# each session hits the same process anyway.
CMD ["uvicorn", "aria.agentcore_app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
