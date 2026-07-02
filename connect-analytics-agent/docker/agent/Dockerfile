FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent/ .
COPY tools/ ./tools/
RUN mkdir -p /app/data && chown -R appuser:appuser /app
ENV PYTHONPATH=/app HOME=/home/appuser
USER appuser
CMD ["uvicorn", "local_server:app", "--host", "0.0.0.0", "--port", "8100", "--reload"]
