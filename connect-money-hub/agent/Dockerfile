# The Money Hub agent for AgentCore Runtime: ARM64 (Graviton), HTTP protocol on port 8080.
# Built by scripts/deploy_agent.sh from a build folder holding agent/*.py, moneyhub/ and requirements.txt.
FROM --platform=linux/arm64 python:3.12.4-slim AS builder
WORKDIR /app
RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM --platform=linux/arm64 python:3.12.4-slim
RUN useradd -r -u 1001 appuser
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY moneyhub ./moneyhub
COPY main.py money_tools.py prompt.py history.py ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER appuser
EXPOSE 8080
# OpenTelemetry auto-instrumentation sends traces to AgentCore Observability.
CMD ["opentelemetry-instrument", "python", "main.py"]
