import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from agent_core import ConnectAnalyticsAgent, LocalToolInvoker
import startup_scan
import eventbridge_listener
from session_store import create_session_store

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s – %(message)s")
LOGGER = logging.getLogger(__name__)

# Throttle for EventBridge-not-configured ERROR log (log once, then every 5 min)
_EB_WARN_INTERVAL = 300  # seconds
_eb_last_warn: float = 0.0

_RAW_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5274")
_ALLOWED_ORIGINS: List[str] = [o.strip() for o in _RAW_ORIGINS.split(",") if o.strip()]

app = FastAPI(
    title="Amazon Connect Analytics Agent",
    version="1.0.0",
    # Disable automatic OpenAPI docs in production to reduce attack surface
    docs_url="/docs" if os.getenv("ENABLE_DOCS", "false").lower() == "true" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if os.getenv("ENABLE_DOCS", "false").lower() == "true" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Add security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"  # Rely on CSP; legacy header deprecated
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # Content-Security-Policy: API-only service — no browser document loading needed
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    # Only add HSTS on non-localhost HTTPS connections
    host = request.headers.get("host", "")
    if "localhost" not in host and "127.0.0.1" not in host:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ── Rate limiting (sliding window, in-memory) ─────────────────────────────────
_RATE_STORE: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT_CALLS = int(os.getenv("RATE_LIMIT_CALLS", "30"))
_RATE_LIMIT_WINDOW = float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


def _check_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    calls = [t for t in _RATE_STORE[client_ip] if now - t < _RATE_LIMIT_WINDOW]
    if len(calls) >= _RATE_LIMIT_CALLS:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded — please wait before sending more queries.",
        )
    calls.append(now)
    _RATE_STORE[client_ip] = calls


# ── Input validation patterns ─────────────────────────────────────────────────
_CONTACT_ID_RE = re.compile(r'^[a-zA-Z0-9\-]{1,128}$')
_SESSION_ID_RE = re.compile(r'^[a-zA-Z0-9\-]{1,64}$')
_VALID_CONTACT_STATUSES = frozenset({
    "CONNECTED", "ENDED", "MISSED", "QUEUED", "ERROR",
    "REJECTED", "TRANSFERRED", "HELD", "CONNECTING",
})

# Shared in-process tool invoker (tools/ volume-mounted at /app/tools in Docker)
_local_invoker = LocalToolInvoker()

_STATUS_DISPLAY: Dict[str, str] = {
    "AVAILABLE": "Available",
    "ON_CALL": "On Call",
    "AFTER_CONTACT_WORK": "After Contact Work",
    "NON_PRODUCTIVE": "Non-Productive",
    "OFFLINE": "Offline",
    "ERROR": "Error",
    "BUSY": "Busy",
    "MISSED": "Missed",
    "REJECTED": "Rejected",
}


def _is_mock() -> bool:
    return os.getenv("MOCK_MODE", "true").lower() == "true"


def _invoke_tool(tool_name: str, extra_params: List[Dict[str, Any]]) -> Dict[str, Any]:
    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    parameters = [{"name": "instance_id", "type": "string", "value": instance_id}] + extra_params
    payload = {"actionGroup": "ConnectAnalyticsTools", "function": tool_name, "parameters": parameters}
    raw = _local_invoker.invoke(tool_name, payload)
    result = json.loads(raw)
    # All tools return {"statusCode": 200, "success": true, "data": {...}} — unwrap the payload
    if isinstance(result, dict) and "data" in result:
        inner = result["data"]
        if isinstance(inner, dict) and "error" not in inner:
            return inner
    return result


# ── Mock data ─────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="Natural language query, max 4000 characters")
    session_id: Optional[str] = Field(
        default=None,
        pattern=r'^[a-zA-Z0-9\-]{1,64}$',
        description="Optional session UUID; must be alphanumeric+hyphens",
    )

    @field_validator("message")
    @classmethod
    def _no_null_bytes(cls, v: str) -> str:
        if "\x00" in v:
            raise ValueError("Null bytes are not allowed in message")
        return v


_MOCK_CHAT: Dict[str, str] = {
    "how many agents are busy": "There are currently 8 agents busy across all queues. Queue 'Customer Support' has 5 agents on calls, and 'Technical Support' has 3 agents on calls.",
    "who is my busiest agent": "Your busiest agent today is Sarah Johnson with 24 contacts handled. She has an average handle time of 4:32 and is currently available.",
}

_MOCK_AGENT_STATES = [
    {"name": "Sarah Johnson", "status": "Available", "currentQueue": "Customer Support", "timeInStatus": "00:12:18", "contactId": ""},
    {"name": "Marcus Lee", "status": "On Call", "currentQueue": "Technical Support", "timeInStatus": "00:08:05", "contactId": "c-10231"},
    {"name": "Priya Patel", "status": "After Contact Work", "currentQueue": "Billing", "timeInStatus": "00:02:44", "contactId": "c-10228"},
    {"name": "Andre Lewis", "status": "Non-Productive", "currentQueue": "VIP Support", "timeInStatus": "00:15:06", "contactId": ""},
    {"name": "Mina Chen", "status": "Offline", "currentQueue": "—", "timeInStatus": "01:03:54", "contactId": ""},
    {"name": "Dylan Brooks", "status": "Error", "currentQueue": "Customer Support", "timeInStatus": "00:01:09", "contactId": "c-10236"},
]

_MOCK_CONTACTS = [
    {"contactId": "c-10236", "dateTime": "2025-05-08T09:18:00Z", "agent": "Marcus Lee", "queue": "Technical Support", "duration": 412, "status": "ENDED", "channel": "VOICE"},
    {"contactId": "c-10231", "dateTime": "2025-05-08T08:42:00Z", "agent": "Sarah Johnson", "queue": "Customer Support", "duration": 268, "status": "ENDED", "channel": "VOICE"},
    {"contactId": "c-10228", "dateTime": "2025-05-08T08:15:00Z", "agent": "Priya Patel", "queue": "Billing", "duration": 198, "status": "MISSED", "channel": "VOICE"},
    {"contactId": "c-10214", "dateTime": "2025-05-08T07:50:00Z", "agent": "Andre Lewis", "queue": "VIP Support", "duration": 622, "status": "CONNECTED", "channel": "CHAT"},
]

_MOCK_TRANSCRIPT_SEGMENTS = [
    {"speaker": "CUSTOMER", "text": "I need this escalated right away.", "time": "00:00:12", "sentiment": "NEGATIVE", "start_offset_millis": 12000},
    {"speaker": "AGENT", "text": "I can help with that escalation request.", "time": "00:00:21", "sentiment": "NEUTRAL", "start_offset_millis": 21000},
    {"speaker": "CUSTOMER", "text": "Thank you, I appreciate the quick support.", "time": "00:01:02", "sentiment": "POSITIVE", "start_offset_millis": 62000},
]


def _mock_chat_response(message: str) -> str:
    normalized = message.lower().strip().rstrip("?.!")
    for prompt, response in _MOCK_CHAT.items():
        if prompt in normalized:
            return response
    if "abandoned" in normalized:
        return "In the last hour, there were 6 abandoned calls. Three were in Billing and three were in Technical Support. The longest wait before abandonment was 9 minutes and 14 seconds."
    if "escalation" in normalized:
        return "I found 4 calls mentioning 'escalation' today. Two were in Customer Support and two were in Technical Support. The most recent occurred 12 minutes ago."
    if "average handle time" in normalized:
        return "Today's average handle time is 00:04:46 across all queues. Technical Support is highest at 00:06:08, while Billing is lowest at 00:03:57."
    return "Mock mode is enabled. Ask about busy agents, busiest agent, abandoned calls, escalation keywords, or average handle time to see richer sample responses."


# ── Startup validation ────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup_check():
    if not _is_mock() and not os.getenv("CONNECT_INSTANCE_ID"):
        LOGGER.warning(
            "CONNECT_INSTANCE_ID is not set. All live Connect API calls will fail. "
            "Set it in your .env file or pass it as an environment variable."
        )
    elif not _is_mock():
        LOGGER.info("Amazon Connect Analytics Agent starting in real-data mode (instance=%s)",
                    os.getenv("CONNECT_INSTANCE_ID"))

    # Trigger startup resource scan (only if needed, only leader instance does it)
    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    if not _is_mock() and instance_id:
        became_leader = await startup_scan.start_scan_if_needed(instance_id, region)
        if became_leader:
            LOGGER.info("This instance is the scan leader — discovery started")
        else:
            state = startup_scan.get_state()
            if state["complete"]:
                LOGGER.info("Startup scan already complete — using cached resources")

    # Start EventBridge contact event listener if SQS queue is configured.
    # Priority: env var → deploy state file → can be set at runtime via PUT /api/eventbridge/configure
    bot_queue_url = os.getenv("BOT_EVENTS_QUEUE_URL", "").strip()
    if not bot_queue_url:
        # Try reading from the deploy state file mounted at /app/deploy-state.json
        state_paths = ["/app/deploy-state.json", "/app/.deploy-state.json"]
        for sp in state_paths:
            try:
                with open(sp) as f:
                    ds = json.load(f)
                    bot_queue_url = ds.get("bot_events_queue_url", "").strip()
                    if bot_queue_url:
                        LOGGER.info("EventBridge queue URL loaded from state file: %s", sp)
                        break
            except (FileNotFoundError, json.JSONDecodeError):
                pass

    if not _is_mock() and bot_queue_url:
        eventbridge_listener.start(queue_url=bot_queue_url, region=region)
        LOGGER.info("EventBridge SQS listener started for bot contact events")
    elif not _is_mock():
        LOGGER.error(
            "ERROR: EventBridge SQS listener NOT started — BOT_EVENTS_QUEUE_URL is not set. "
            "Live contact tracking will use degraded direct-poll fallback mode. "
            "Fix: run './deploy.sh setup-eventbridge' then './deploy.sh update' to enable full real-time tracking."
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

# ── Startup scan SSE + status ──────────────────────────────────────────────────

async def _sse_generator(q: asyncio.Queue) -> AsyncGenerator[str, None]:
    """Yield SSE messages from the queue; send heartbeats to keep connection alive."""
    startup_scan.register_queue(q)
    try:
        state = startup_scan.get_state()
        # If already complete, emit a dedicated event so the frontend can
        # pre-populate all phase states before showing the completion message
        if state["complete"] and not state["running"]:
            yield f"data: {json.dumps({'type': 'already_complete', 'ts': datetime.now(timezone.utc).isoformat(), 'progress': 1.0, 'total_found': state['total_found'], 'found': state['found'], 'duration_sec': None})}\n\n"
            return
        # If mock mode — tell frontend to skip the scan screen
        if _is_mock():
            yield f"data: {json.dumps({'type': 'scan_skipped', 'ts': datetime.now(timezone.utc).isoformat(), 'reason': 'mock_mode'})}\n\n"
            return

        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield msg
                # Stop streaming once scan completes
                if '"scan_complete"' in msg or '"scan_error"' in msg:
                    break
            except asyncio.TimeoutError:
                # Heartbeat to keep connection alive
                yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
    finally:
        startup_scan.unregister_queue(q)


@app.get("/startup-scan/stream")
async def startup_scan_stream():
    """SSE stream of real-time scan progress events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    return StreamingResponse(
        _sse_generator(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/startup-scan/status")
def startup_scan_status() -> Dict[str, Any]:
    """Snapshot of current scan state (for polling fallback)."""
    state = startup_scan.get_state()
    resources = startup_scan.get_resources()
    return {
        **state,
        "has_resources": resources is not None,
        "mock_mode": _is_mock(),
        "boot_id": startup_scan.BOOT_ID,  # unique per server restart
    }


@app.get("/startup-scan/resources")
def startup_scan_resources() -> Dict[str, Any]:
    """Return a sanitised summary of discovered resources (no ARNs, no account IDs)."""
    resources = startup_scan.get_resources()
    if not resources:
        raise HTTPException(status_code=404, detail="Resources not yet discovered")
    # Return counts and non-sensitive identifiers only — strip ARNs, account IDs
    safe: Dict[str, Any] = {"scan_at": resources.get("scan_completed_at")}
    connect = resources.get("connect", {})
    safe["connect"] = {
        "instance_alias": connect.get("instance", {}).get("alias", ""),
        "queue_count": len(connect.get("queues", [])),
        "agent_count": len(connect.get("agents", [])),
        "flow_count": len(connect.get("flows", [])),
        "routing_profile_count": len(connect.get("routing_profiles", [])),
        "phone_number_count": len(connect.get("phone_numbers", [])),
        "queues": [{"name": q.get("name", ""), "type": q.get("type", "")} for q in connect.get("queues", [])],
    }
    bots = resources.get("bots", {})
    safe["bots"] = {
        "lex_v2_count": len(bots.get("lex_v2", [])),
        "lex_v1_count": len(bots.get("lex_v1", [])),
        "q_assistants": [a.get("name", "") for a in bots.get("q_in_connect_assistants", [])],
    }
    storage = resources.get("storage", {})
    safe["storage"] = {
        "s3_bucket_count": len(storage.get("all_s3_buckets", [])),
        "connect_s3_bucket_count": len(storage.get("connect_s3_buckets", {})),
        "kinesis_stream_count": len(storage.get("kinesis_streams", [])),
    }
    ai = resources.get("ai_ml", {})
    safe["ai_ml"] = {
        "bedrock_model_count": len(ai.get("bedrock_models", [])),
        "knowledge_base_count": len(ai.get("knowledge_bases", [])),
    }
    return safe


@app.post("/startup-scan/rescan")
async def startup_scan_rescan() -> Dict[str, Any]:
    """Force a new discovery scan."""
    if startup_scan.get_state()["running"]:
        return {"status": "already_running"}
    import startup_scan as _ss
    _ss.RESOURCES_FILE.unlink(missing_ok=True)
    _ss._state["complete"] = False
    _ss._state["running"] = False
    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    await startup_scan.start_scan_if_needed(instance_id, region)
    return {"status": "started"}

@app.get("/health")
def health() -> Dict[str, Any]:
    mock = _is_mock()
    mode = "mock"
    if not mock:
        if os.getenv("AGENTCORE_GATEWAY_ENDPOINT"):
            mode = "agentcore-gateway"
        elif _local_invoker.available:
            mode = "local-tools"
        else:
            mode = "unconfigured"
    return {
        "status": "ok",
        "mode": mode,
        "mock_mode": mock,
        "local_tools_available": _local_invoker.available,
        "gateway_configured": bool(os.getenv("AGENTCORE_GATEWAY_ENDPOINT")),
        "connect_instance_configured": bool(os.getenv("CONNECT_INSTANCE_ID")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/config")
def config() -> Dict[str, Any]:
    """
    Returns the live configuration resolved from AWS — no values are hardcoded.
    S3 buckets are discovered from the Connect instance storage configuration.
    """
    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    profile = os.getenv("AWS_PROFILE", "default")

    result: Dict[str, Any] = {
        "mock_mode": _is_mock(),
        "aws_region": region,
        "aws_profile": profile,
        "connect_instance_id": instance_id or None,
        "storage_configs": {},
        "notes": [],
    }

    if _is_mock():
        result["notes"].append("Running in mock mode — no AWS API calls are made.")
        return result

    if not instance_id:
        result["notes"].append("CONNECT_INSTANCE_ID is not set. Cannot resolve storage configuration.")
        return result

    # Dynamically fetch every S3 storage config from the Connect instance
    resource_types = [
        "CALL_RECORDINGS",
        "CHAT_TRANSCRIPTS",
        "REAL_TIME_CONTACT_ANALYSIS_SEGMENTS",
        "SCHEDULED_REPORTS",
        "CONTACT_TRACE_RECORDS",
        "AGENT_EVENTS",
    ]
    try:
        import boto3
        connect_client = boto3.client("connect", region_name=region)
        for resource_type in resource_types:
            try:
                resp = connect_client.list_instance_storage_configs(
                    InstanceId=instance_id,
                    ResourceType=resource_type,
                )
                configs = []
                for cfg in resp.get("StorageConfigs", []):
                    entry: Dict[str, Any] = {"storage_type": cfg.get("StorageType")}
                    if cfg.get("StorageType") == "S3":
                        s3 = cfg.get("S3Config", {})
                        entry["bucket"] = s3.get("BucketName")
                        entry["prefix"] = s3.get("BucketPrefix")
                        entry["encryption"] = (s3.get("EncryptionConfig") or {}).get("EncryptionType")
                    elif cfg.get("StorageType") == "KINESIS_FIREHOSE":
                        entry["stream"] = (cfg.get("KinesisFirehoseConfig") or {}).get("FirehoseArn")
                    configs.append(entry)
                result["storage_configs"][resource_type] = configs
            except Exception as exc:  # pylint: disable=broad-except
                result["storage_configs"][resource_type] = {"error": str(exc)}
    except Exception as exc:  # pylint: disable=broad-except
        result["notes"].append(f"Failed to fetch storage configuration: {exc}")

    if not any(
        isinstance(v, list) and v
        for v in result["storage_configs"].values()
    ):
        result["notes"].append(
            "No S3 storage configurations found. Verify that the Connect instance has S3 configured "
            "for recordings and/or transcripts in the Amazon Connect console."
        )

    return result


@app.get("/metrics")
def metrics() -> Dict[str, Any]:
    if _is_mock():
        return {
            "mock": True,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "metrics": {"agents_online": 19, "agents_available": 7, "agents_on_call": 8, "agents_in_acw": 3, "contacts_in_queue": 5, "oldest_contact_age": "00:03:42"},
        }
    try:
        data = _invoke_tool("get_realtime_metrics", [])
        totals = data.get("overall_totals", {})
        return {
            "mock": False,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "agents_online": int(totals.get("AGENTS_ONLINE", 0)),
                "agents_available": int(totals.get("AGENTS_AVAILABLE", 0)),
                "agents_on_call": int(totals.get("AGENTS_ON_CALL", 0)),
                "agents_in_acw": int(totals.get("AGENTS_AFTER_CONTACT_WORK", 0)),
                "contacts_in_queue": int(totals.get("CONTACTS_IN_QUEUE", 0)),
                "oldest_contact_age": totals.get("OLDEST_CONTACT_AGE_formatted", "00:00:00"),
            },
        }
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch real-time metrics") from exc


_MOCK_HISTORICAL = {
    "period": "Last 30 days",
    "data": [
        {"date_key": "2026-04-08", "label": "8 Apr",  "CONTACTS_HANDLED": 4,  "AVG_HANDLE_TIME": 192, "CONTACTS_QUEUED": 6,  "AVG_AFTER_CONTACT_WORK_TIME": 45},
        {"date_key": "2026-04-09", "label": "9 Apr",  "CONTACTS_HANDLED": 7,  "AVG_HANDLE_TIME": 210, "CONTACTS_QUEUED": 9,  "AVG_AFTER_CONTACT_WORK_TIME": 62},
        {"date_key": "2026-04-10", "label": "10 Apr", "CONTACTS_HANDLED": 3,  "AVG_HANDLE_TIME": 178, "CONTACTS_QUEUED": 5,  "AVG_AFTER_CONTACT_WORK_TIME": 38},
        {"date_key": "2026-04-14", "label": "14 Apr", "CONTACTS_HANDLED": 9,  "AVG_HANDLE_TIME": 245, "CONTACTS_QUEUED": 12, "AVG_AFTER_CONTACT_WORK_TIME": 71},
        {"date_key": "2026-04-15", "label": "15 Apr", "CONTACTS_HANDLED": 12, "AVG_HANDLE_TIME": 198, "CONTACTS_QUEUED": 15, "AVG_AFTER_CONTACT_WORK_TIME": 55},
        {"date_key": "2026-04-16", "label": "16 Apr", "CONTACTS_HANDLED": 8,  "AVG_HANDLE_TIME": 231, "CONTACTS_QUEUED": 11, "AVG_AFTER_CONTACT_WORK_TIME": 67},
        {"date_key": "2026-04-17", "label": "17 Apr", "CONTACTS_HANDLED": 5,  "AVG_HANDLE_TIME": 163, "CONTACTS_QUEUED": 7,  "AVG_AFTER_CONTACT_WORK_TIME": 42},
        {"date_key": "2026-04-22", "label": "22 Apr", "CONTACTS_HANDLED": 11, "AVG_HANDLE_TIME": 220, "CONTACTS_QUEUED": 14, "AVG_AFTER_CONTACT_WORK_TIME": 58},
        {"date_key": "2026-04-23", "label": "23 Apr", "CONTACTS_HANDLED": 3,  "AVG_HANDLE_TIME": 108, "CONTACTS_QUEUED": 4,  "AVG_AFTER_CONTACT_WORK_TIME": 30},
        {"date_key": "2026-04-24", "label": "24 Apr", "CONTACTS_HANDLED": 7,  "AVG_HANDLE_TIME": 159, "CONTACTS_QUEUED": 9,  "AVG_AFTER_CONTACT_WORK_TIME": 48},
        {"date_key": "2026-04-27", "label": "27 Apr", "CONTACTS_HANDLED": 1,  "AVG_HANDLE_TIME": 287, "CONTACTS_QUEUED": 3,  "AVG_AFTER_CONTACT_WORK_TIME": 90},
        {"date_key": "2026-04-28", "label": "28 Apr", "CONTACTS_HANDLED": 0,  "AVG_HANDLE_TIME": 0,   "CONTACTS_QUEUED": 2,  "AVG_AFTER_CONTACT_WORK_TIME": 0},
        {"date_key": "2026-05-01", "label": "1 May",  "CONTACTS_HANDLED": 2,  "AVG_HANDLE_TIME": 87,  "CONTACTS_QUEUED": 4,  "AVG_AFTER_CONTACT_WORK_TIME": 25},
        {"date_key": "2026-05-08", "label": "8 May",  "CONTACTS_HANDLED": 7,  "AVG_HANDLE_TIME": 158, "CONTACTS_QUEUED": 8,  "AVG_AFTER_CONTACT_WORK_TIME": 44},
    ],
    "abandoned": [
        {"date_key": "2026-04-08", "label": "8 Apr",  "CONTACTS_ABANDONED": 1},
        {"date_key": "2026-04-09", "label": "9 Apr",  "CONTACTS_ABANDONED": 2},
        {"date_key": "2026-04-14", "label": "14 Apr", "CONTACTS_ABANDONED": 3},
        {"date_key": "2026-04-15", "label": "15 Apr", "CONTACTS_ABANDONED": 1},
        {"date_key": "2026-04-16", "label": "16 Apr", "CONTACTS_ABANDONED": 2},
        {"date_key": "2026-04-22", "label": "22 Apr", "CONTACTS_ABANDONED": 4},
        {"date_key": "2026-04-23", "label": "23 Apr", "CONTACTS_ABANDONED": 0},
        {"date_key": "2026-04-24", "label": "24 Apr", "CONTACTS_ABANDONED": 1},
        {"date_key": "2026-05-01", "label": "1 May",  "CONTACTS_ABANDONED": 0},
        {"date_key": "2026-05-08", "label": "8 May",  "CONTACTS_ABANDONED": 1},
    ],
}


@app.get("/historical-metrics")
def historical_metrics(days: int = Query(default=30, ge=1, le=90)) -> Dict[str, Any]:
    if _is_mock():
        return {"mock": True, "period": _MOCK_HISTORICAL["period"],
                "data": _MOCK_HISTORICAL["data"], "abandoned": _MOCK_HISTORICAL["abandoned"]}
    try:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days)).isoformat()
        end = now.isoformat()

        def _invoke_day(metrics_str: str) -> List[Dict[str, Any]]:
            return _invoke_tool("get_historical_metrics", [
                {"name": "start_time", "type": "string", "value": start},
                {"name": "end_time",   "type": "string", "value": end},
                {"name": "group_by",   "type": "string", "value": "QUEUE"},
                {"name": "interval",   "type": "string", "value": "DAY"},
                {"name": "metrics",    "type": "string", "value": metrics_str},
            ]).get("results", [])

        def _parse_dt(iso_str):
            try:
                return datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
            except Exception:
                return None

        def _fmt_label(iso_str):
            dt = _parse_dt(iso_str)
            if dt:
                return dt.strftime("%-d %b")
            return str(iso_str)[:10]

        def _date_key(iso_str):
            dt = _parse_dt(iso_str)
            return dt.strftime("%Y-%m-%d") if dt else str(iso_str)[:10]

        # Fetch all series (3 calls)
        handled_rows = _invoke_day("CONTACTS_HANDLED,AVG_HANDLE_TIME")
        abandoned_rows = _invoke_day("CONTACTS_ABANDONED")
        acw_rows = _invoke_day("CONTACTS_QUEUED,AVG_AFTER_CONTACT_WORK_TIME")

        # Build keyed maps indexed by date_key for merging
        handled_map: Dict[str, Dict] = {}
        for row in handled_rows:
            dk = _date_key(row.get("interval_start"))
            m = row.get("metrics", {})
            handled_map[dk] = {
                "date_key": dk,
                "label": _fmt_label(row.get("interval_start")),
                "CONTACTS_HANDLED": round(m.get("CONTACTS_HANDLED") or 0),
                "AVG_HANDLE_TIME": round(m.get("AVG_HANDLE_TIME") or 0),
            }

        acw_map: Dict[str, Dict] = {}
        for row in acw_rows:
            dk = _date_key(row.get("interval_start"))
            m = row.get("metrics", {})
            acw_map[dk] = {
                "date_key": dk,
                "label": _fmt_label(row.get("interval_start")),
                "CONTACTS_QUEUED": round(m.get("CONTACTS_QUEUED") or 0),
                "AVG_AFTER_CONTACT_WORK_TIME": round(m.get("AVG_AFTER_CONTACT_WORK_TIME") or 0),
            }

        # Merge into a single list sorted by date_key ascending
        all_keys = sorted(set(handled_map) | set(acw_map))
        chart_data = []
        for dk in all_keys:
            h = handled_map.get(dk, {})
            a = acw_map.get(dk, {})
            chart_data.append({
                "date_key": dk,
                "label": h.get("label") or a.get("label") or dk,
                "CONTACTS_HANDLED": h.get("CONTACTS_HANDLED", 0),
                "AVG_HANDLE_TIME": h.get("AVG_HANDLE_TIME", 0),
                "CONTACTS_QUEUED": a.get("CONTACTS_QUEUED", 0),
                "AVG_AFTER_CONTACT_WORK_TIME": a.get("AVG_AFTER_CONTACT_WORK_TIME", 0),
            })

        abandoned_chart = []
        for row in abandoned_rows:
            dk = _date_key(row.get("interval_start"))
            abandoned_chart.append({
                "date_key": dk,
                "label": _fmt_label(row.get("interval_start")),
                "CONTACTS_ABANDONED": round(row.get("metrics", {}).get("CONTACTS_ABANDONED") or 0),
            })
        abandoned_chart.sort(key=lambda r: r["date_key"])

        return {
            "mock": False,
            "period": f"Last {days} days",
            "data": chart_data,
            "abandoned": abandoned_chart,
        }
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch historical metrics") from exc


@app.get("/agent-states")
def agent_states() -> Dict[str, Any]:
    if _is_mock():
        return {"mock": True, "agents": _MOCK_AGENT_STATES, "agent_count": len(_MOCK_AGENT_STATES)}
    try:
        data = _invoke_tool("get_agent_states", [])
        agents = []
        for agent in data.get("agents", []):
            raw_status = agent.get("current_status", "")
            agents.append({
                "name": agent.get("display_name") or agent.get("username", "Unknown"),
                "status": _STATUS_DISPLAY.get(raw_status, raw_status.replace("_", " ").title()),
                "currentQueue": agent.get("current_queue_name") or agent.get("current_queue") or "—",
                "timeInStatus": agent.get("time_in_status", "00:00:00"),
                "contactId": agent.get("contact_id") or "",
            })
        return {"mock": False, "agents": agents, "agent_count": len(agents)}
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch agent states") from exc


_MOCK_ACTIVE_CALLS = [
    {"contactId": "c-10236", "agent": "Marcus Lee",  "queue": "Technical Support", "channel": "VOICE", "duration": 142, "status": "CONNECTED"},
    {"contactId": "c-10238", "agent": "Sarah Johnson", "queue": "Customer Support", "channel": "VOICE", "duration": 67, "status": "CONNECTED"},
    {"contactId": "c-10240", "agent": "Andre Lewis",  "queue": "VIP Support",       "channel": "CHAT",  "duration": 310, "status": "CONNECTED"},
    {"contactId": "c-10241", "agent": "Priya Patel",  "queue": "Billing",           "channel": "VOICE", "duration": 28, "status": "CONNECTED"},
    {"contactId": "c-10242", "agent": "Dylan Brooks", "queue": "Customer Support",  "channel": "VOICE", "duration": 195, "status": "CONNECTED"},
    {"contactId": "c-10243", "agent": "Mina Chen",    "queue": "Technical Support", "channel": "CHAT",  "duration": 87, "status": "CONNECTED"},
]


@app.get("/active-calls")
def active_calls() -> Dict[str, Any]:
    if _is_mock():
        return {"mock": True, "calls": _MOCK_ACTIVE_CALLS, "total": len(_MOCK_ACTIVE_CALLS)}
    try:
        import boto3  # pylint: disable=import-outside-toplevel
        data = _invoke_tool("get_agent_states", [])
        connect = boto3.client("connect")
        instance_id = os.getenv("CONNECT_INSTANCE_ID", "")

        calls = []
        for ag in data.get("agents", []):
            if ag.get("current_status", "") != "ON_CALL" or not ag.get("contact_id"):
                continue
            contact_id = ag["contact_id"]
            call = {
                "contactId": contact_id,
                "agent": ag.get("display_name") or ag.get("username", "Unknown"),
                "queue": ag.get("current_queue_name") or ag.get("current_queue") or "—",
                "channel": ag.get("channel", "VOICE"),
                "duration": ag.get("duration_seconds", 0),
                "status": "CONNECTED",
                "escalatedFromBot": False,
                "previousContactId": None,
                "enqueuedAt": None,
                "connectedToAgentAt": None,
            }
            # Enrich with describe_contact — detect bot escalation and queue info
            if instance_id:
                try:
                    detail = connect.describe_contact(InstanceId=instance_id, ContactId=contact_id).get("Contact", {})
                    # Bot escalation: AUTOMATED_INTERACTION recording present = bot was involved
                    has_bot_recording = any(
                        r.get("MediaStreamType") == "AUTOMATED_INTERACTION"
                        for r in detail.get("Recordings", [])
                    )
                    call["escalatedFromBot"] = has_bot_recording
                    call["previousContactId"] = detail.get("PreviousContactId")
                    qi = detail.get("QueueInfo", {})
                    if qi.get("Name"):
                        call["queue"] = qi["Name"]
                    if qi.get("EnqueueTimestamp"):
                        call["enqueuedAt"] = qi["EnqueueTimestamp"].isoformat() if hasattr(qi["EnqueueTimestamp"], "isoformat") else str(qi["EnqueueTimestamp"])
                    ai = detail.get("AgentInfo", {})
                    if ai.get("ConnectedToAgentTimestamp"):
                        call["connectedToAgentAt"] = ai["ConnectedToAgentTimestamp"].isoformat() if hasattr(ai["ConnectedToAgentTimestamp"], "isoformat") else str(ai["ConnectedToAgentTimestamp"])
                except Exception as exc:  # pylint: disable=broad-except
                    LOGGER.debug("describe_contact enrichment failed for %s: %s", contact_id, exc)
            calls.append(call)
        return {"mock": False, "calls": calls, "total": len(calls)}
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch active calls") from exc


@app.get("/recent-bot-contacts")
def recent_bot_contacts(hours: int = Query(2, ge=1, le=24)) -> Dict[str, Any]:
    """
    Return recently completed contacts that were handled by the conversational AI bot.
    Sorted newest-first. Contacts with AgentInfo show bot→agent escalation.
    Note: truly in-progress bot contacts cannot be tracked via Connect REST API —
    they only appear here once completed (Connect doesn't expose IVR-state contacts in real-time).
    """
    if _is_mock():
        return {"contacts": [], "total": 0, "hours_window": hours, "api_limitation": True}
    try:
        import boto3  # pylint: disable=import-outside-toplevel
        connect = boto3.client("connect")
        instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
        if not instance_id:
            return {"contacts": [], "total": 0, "hours_window": hours, "api_limitation": True}

        start = datetime.now(timezone.utc) - timedelta(hours=hours)
        resp = connect.search_contacts(
            InstanceId=instance_id,
            TimeRange={"Type": "INITIATION_TIMESTAMP", "StartTime": start.isoformat(), "EndTime": datetime.now(timezone.utc).isoformat()},
            MaxResults=50,
        )

        bot_contacts = []
        for c in resp.get("Contacts", []):
            try:
                detail = connect.describe_contact(InstanceId=instance_id, ContactId=c["Id"]).get("Contact", {})
            except Exception:  # pylint: disable=broad-except
                continue

            recordings = detail.get("Recordings", [])
            has_bot = any(r.get("MediaStreamType") == "AUTOMATED_INTERACTION" for r in recordings)
            if not has_bot:
                continue

            qi = detail.get("QueueInfo", {})
            ai = detail.get("AgentInfo", {})
            initiated = detail.get("InitiationTimestamp")
            disconnected = detail.get("DisconnectTimestamp")
            bot_contacts.append({
                "contactId": c["Id"],
                "channel": detail.get("Channel", "VOICE"),
                "initiationMethod": detail.get("InitiationMethod"),
                "initiatedAt": initiated.isoformat() if hasattr(initiated, "isoformat") else str(initiated or ""),
                "disconnectedAt": disconnected.isoformat() if hasattr(disconnected, "isoformat") else (str(disconnected) if disconnected else None),
                "inProgress": disconnected is None,
                "escalatedToAgent": bool(ai.get("Id")),
                "agentId": ai.get("Id"),
                "queueName": qi.get("Name") or "—",
                "enqueuedAt": qi["EnqueueTimestamp"].isoformat() if qi.get("EnqueueTimestamp") and hasattr(qi["EnqueueTimestamp"], "isoformat") else None,
                "connectedToAgentAt": ai["ConnectedToAgentTimestamp"].isoformat() if ai.get("ConnectedToAgentTimestamp") and hasattr(ai["ConnectedToAgentTimestamp"], "isoformat") else None,
            })

        bot_contacts.sort(key=lambda x: x.get("initiatedAt", ""), reverse=True)
        return {
            "contacts": bot_contacts,
            "total": len(bot_contacts),
            "hours_window": hours,
            "api_limitation_note": (
                "Contacts currently being handled by the bot (IVR state) are not visible via "
                "the Connect REST API until they complete. To see live bot interactions, enable "
                "Amazon Connect Streams (browser SDK) or Amazon EventBridge contact events."
            ),
        }
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("recent_bot_contacts failed: %s", exc)
        return {"contacts": [], "total": 0, "hours_window": hours, "error": str(exc)}


@app.get("/live-bot-contacts")
def live_bot_contacts() -> Dict[str, Any]:
    """Backward-compat: returns bot/IVR contacts only. Prefer /live-contacts."""
    listener_active = eventbridge_listener.is_running()
    contacts = eventbridge_listener.get_active_bot_contacts() if listener_active else []
    return {
        "contacts": contacts,
        "total": len(contacts),
        "listener_active": listener_active,
        "queue_url": bool(os.getenv("BOT_EVENTS_QUEUE_URL")),
        "setup_required": not listener_active,
    }


@app.get("/live-contacts")
def live_contacts() -> Dict[str, Any]:
    """
    All live contacts tracked via EventBridge → SQS (preferred) with automatic
    fallback to direct Connect API polling via get_current_user_data when
    EventBridge is not configured.  The `listener_active` flag tells the UI
    which mode is in use; `polling_mode` is True when using the fallback.
    """
    listener_active = eventbridge_listener.is_running()
    if listener_active:
        all_contacts = eventbridge_listener.get_all_live_contacts()
        summary      = eventbridge_listener.get_summary()
        cb_by_queue  = eventbridge_listener.get_callbacks_by_queue()
        return {
            "listener_active": True,
            "polling_mode": False,
            "setup_required": False,
            "summary": summary,
            "inbound":     [c for c in all_contacts if c.get("contactType") == "inbound"
                            and not c.get("isOutbound") and not c.get("isCallback")
                            and not c.get("isInternalBotSession")],
            "outbound":    [c for c in all_contacts if c.get("isOutbound")],
            "callbacks":   [c for c in all_contacts if c.get("isCallback")],
            "bot_contacts":[c for c in all_contacts if c.get("isBot") and not c.get("isInternalBotSession")],
            "transfers":   [c for c in all_contacts if c.get("contactType") == "transfer"],
            "all":         [c for c in all_contacts if not c.get("isInternalBotSession")],
            "callbacks_by_queue": cb_by_queue,
        }

    # ── Fallback: poll Connect API directly ────────────────────────────────────
    # Log an ERROR so it's visible in Docker logs, but throttle to once per 5 min
    global _eb_last_warn
    now_ts = time.monotonic()
    if now_ts - _eb_last_warn >= _EB_WARN_INTERVAL:
        LOGGER.error(
            "ERROR: EventBridge SQS listener is NOT running. "
            "Real-time contact tracking is degraded — falling back to direct Connect API polling (5 s delay). "
            "Run './deploy.sh setup-eventbridge' then './deploy.sh update' to enable full real-time tracking."
        )
        _eb_last_warn = now_ts

    contacts = _get_live_contacts_direct()
    summary = {
        "total_active": len(contacts),
        "voice":   sum(1 for c in contacts if c.get("channel") == "VOICE"),
        "chat":    sum(1 for c in contacts if c.get("channel") == "CHAT"),
        "agents_on_call": len({c["agentArn"] for c in contacts if c.get("agentArn")}),
    }
    inbound    = [c for c in contacts if not c.get("isOutbound")]
    outbound   = [c for c in contacts if c.get("isOutbound")]
    bot_ctcts  = [c for c in contacts if c.get("isBot")]
    return {
        "listener_active": False,
        "polling_mode": True,
        "setup_required": True,
        "summary": summary,
        "inbound":      inbound,
        "outbound":     outbound,
        "callbacks":    [],
        "bot_contacts": bot_ctcts,
        "transfers":    [],
        "all":          contacts,
        "callbacks_by_queue": {},
    }


def _get_live_contacts_direct() -> list:
    """
    Poll Connect get_current_user_data to build a live-contacts list when
    EventBridge is not configured.  Returns normalised contact dicts shaped
    like EventBridge contact objects so the frontend can display them unchanged.
    """
    try:
        instance_id = os.environ.get("CONNECT_INSTANCE_ID", "")
        if not instance_id:
            return []
        connect = _get_connect_client()

        # Fetch all routing profiles first (needed for the filter)
        rp_pages = connect.get_paginator("list_routing_profiles").paginate(InstanceId=instance_id)
        rp_ids = [rp["RoutingProfileId"] for page in rp_pages for rp in page.get("RoutingProfileSummaryList", [])]
        if not rp_ids:
            return []

        # get_current_user_data: one call per routing profile batch (max 100 per filter)
        contacts_map: Dict[str, dict] = {}
        for i in range(0, len(rp_ids), 100):
            batch = rp_ids[i:i + 100]
            try:
                paginator = connect.get_paginator("get_current_user_data")
                for page in paginator.paginate(
                    InstanceId=instance_id,
                    Filters={"RoutingProfiles": batch},
                ):
                    for user_data in page.get("UserDataList", []):
                        agent_ref = user_data.get("User", {})
                        agent_arn = agent_ref.get("Arn", "")
                        agent_id  = agent_ref.get("Id", "")
                        for c in user_data.get("Contacts", []):
                            cid = c.get("ContactId")
                            if not cid or cid in contacts_map:
                                continue
                            queue_ref = c.get("Queue", {})
                            agent_name = ""
                            try:
                                # Try to resolve agent name
                                u_resp = connect.describe_user(InstanceId=instance_id, UserId=agent_id)
                                id_info = u_resp.get("User", {}).get("IdentityInfo", {})
                                agent_name = f"{id_info.get('FirstName','')} {id_info.get('LastName','')}".strip()
                            except Exception:
                                pass
                            queue_name = queue_ref.get("Name", "") or queue_ref.get("Id", "")
                            channel = c.get("Channel", "VOICE")
                            state   = (c.get("AgentContactState") or "CONNECTED_TO_AGENT").upper()
                            contacts_map[cid] = {
                                "contactId":    cid,
                                "channel":      channel,
                                "contactState": state,
                                "contactType":  "inbound",
                                "isOutbound":   False,
                                "isBot":        False,
                                "isCallback":   False,
                                "agentArn":     agent_arn,
                                "agentName":    agent_name or agent_id,
                                "queueId":      queue_ref.get("Id", ""),
                                "queueName":    queue_name,
                                "initiatedAt":  c.get("ConnectedToAgentTimestamp") or c.get("StateStartTimestamp"),
                                "contactTerminal": False,
                            }
            except Exception as exc:
                LOGGER.warning("get_current_user_data batch failed: %s", exc)
        return list(contacts_map.values())
    except Exception as exc:
        LOGGER.warning("_get_live_contacts_direct failed: %s", exc)
        return []



@app.get("/live-callbacks")
def live_callbacks() -> Dict[str, Any]:
    """
    Contacts waiting for a callback or with a scheduled callback.
    CALLBACK_SCHEDULED = the customer requested a callback; it hasn't fired yet.
    QUEUED             = the callback has fired and is now waiting for an agent.
    Grouped by queue so supervisors can see pressure at a glance.
    """
    listener_active = eventbridge_listener.is_running()
    callbacks = eventbridge_listener.get_callback_contacts() if listener_active else []
    waiting   = [c for c in callbacks if not c.get("callbackScheduled")]
    scheduled = [c for c in callbacks if c.get("callbackScheduled")]
    by_queue  = eventbridge_listener.get_callbacks_by_queue()
    return {
        "listener_active": listener_active,
        "total_waiting":   len(waiting),
        "total_scheduled": len(scheduled),
        "waiting":         waiting,
        "scheduled":       scheduled,
        "by_queue":        by_queue,
    }


@app.get("/live-outbound")
def live_outbound() -> Dict[str, Any]:
    """
    Outbound calls currently in progress (initiationMethod OUTBOUND or EXTERNAL_OUTBOUND).
    Each record includes:
      - outboundAgentArn / outboundAgentName  — agent who placed the call
      - customerEndpoint  — the number being dialled (masked display + raw address)
      - systemEndpoint    — the Connect DID used for the outbound leg
      - contactState      — current state (INITIATED, CONNECTED_TO_AGENT, etc.)
    Grouped by agent for quick supervisor scanning.
    """
    listener_active = eventbridge_listener.is_running()
    outbound   = eventbridge_listener.get_outbound_contacts() if listener_active else []
    by_agent   = eventbridge_listener.get_outbound_by_agent() if listener_active else {}
    return {
        "listener_active": listener_active,
        "total":           len(outbound),
        "calls":           outbound,
        "by_agent":        by_agent,
    }


@app.get("/config/streams")
def streams_config() -> Dict[str, Any]:
    """
    Return Connect Streams SDK configuration for the frontend.
    The CCP URL is built from the instance alias (CONNECT_ALIAS env var).
    The approved origins are managed in Amazon Connect → Application integrations.
    """
    alias = os.getenv("CONNECT_ALIAS", "")
    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    region = os.getenv("AWS_REGION", "us-east-1")
    ccp_url = f"https://{alias}.my.connect.aws/ccp-v2/" if alias else ""
    return {
        "enabled": bool(alias and instance_id),
        "ccp_url": ccp_url,
        "instance_alias": alias,
        "instance_id": instance_id,
        "region": region,
        "eventbridge_listener_active": eventbridge_listener.is_running(),
        "bot_events_queue_configured": eventbridge_listener.is_running() or bool(os.getenv("BOT_EVENTS_QUEUE_URL")),
    }


class EventbridgeConfigRequest(BaseModel):
    queue_url: str = Field(..., description="SQS queue URL produced by ./deploy.sh setup-eventbridge")


@app.put("/api/eventbridge/configure")
@app.put("/eventbridge/configure")
async def configure_eventbridge(body: EventbridgeConfigRequest) -> Dict[str, Any]:
    """
    Configure the EventBridge SQS listener at runtime without restarting Docker.
    Call this after running ./deploy.sh setup-eventbridge:

      curl -X PUT http://localhost:8100/api/eventbridge/configure \\
           -H 'Content-Type: application/json' \\
           -d '{"queue_url": "<SQS_URL_FROM_SETUP>"}'
    """
    if _is_mock():
        return {"status": "skipped", "reason": "mock mode — EventBridge listener not used"}

    queue_url = body.queue_url.strip()
    if not queue_url.startswith("https://sqs."):
        raise HTTPException(status_code=400, detail="queue_url must be a valid SQS HTTPS URL")

    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    if eventbridge_listener.is_running():
        eventbridge_listener.stop()

    eventbridge_listener.start(queue_url=queue_url, region=region)
    LOGGER.info("EventBridge SQS listener (re)started via runtime API with queue: %s", queue_url)
    return {
        "status": "started",
        "queue_url": queue_url,
        "region": region,
        "listener_active": eventbridge_listener.is_running(),
    }


_MOCK_BOT_METRICS = {
    # Mock data mirrors the real "coversatonalaibot" (Q in Connect + LLM)
    "bot_inventory": {
        "total_bots": 1,
        "lex_v2_count": 1,
        "lex_v1_count": 0,
        "q_in_connect": 1,
        "bots": [
            {
                "bot_type": "LexV2",
                "bot_id": "5CE3XMSSPB",
                "bot_name": "coversatonalaibot",
                "bot_status": "Available",
                "description": "",
                "region": "eu-west-2",
                "has_q_in_connect": True,
                "aliases": [
                    {"alias_id": "PAKRDSHDKA", "alias_name": "production", "is_prod": True,
                     "alias_arn": "arn:aws:lex:eu-west-2:395402194296:bot-alias/5CE3XMSSPB/PAKRDSHDKA"},
                    {"alias_id": "TSTALIASID", "alias_name": "TestBotAlias", "is_prod": False,
                     "alias_arn": "arn:aws:lex:eu-west-2:395402194296:bot-alias/5CE3XMSSPB/TSTALIASID"},
                ],
                "locales": [{"locale_id": "en_GB", "locale_name": "English (GB)", "status": "Built"}],
                "intents": [
                    {"intent_id": "0GIBZ99JDZ", "intent_name": "AmazonQinConnect", "is_q_intent": True,  "is_fallback": False},
                    {"intent_id": "FALLBCKINT", "intent_name": "FallbackIntent",   "is_q_intent": False, "is_fallback": True},
                ],
            },
        ],
    },
    "lex_analytics": [
        {
            "bot_id":          "5CE3XMSSPB",
            "bot_name":        "coversatonalaibot",
            "has_q_in_connect": True,
            "alias_id":        "PAKRDSHDKA",
            "locale_id":       "en_GB",
            "note": "AmazonQinConnect bot: utterances handled by LLM. 'Missed' = Q in Connect delegation (expected). See escalations for human handoff events.",
            "session_metrics": {
                "total_sessions": 54,
                "successful": 7,
                "failed": 0,
                "escalated": 47,
                "escalation_rate_pct": 87.0,
                "avg_duration_sec": 35.2,
                "avg_duration_fmt": "35s",
                "avg_turns": 4.6,
            },
            "intent_metrics": [
                {
                    "intent_name": "AmazonQinConnect",
                    "is_q_intent": True,
                    "is_fallback": False,
                    "total": 54,
                    "successful": 7,
                    "failed": 0,
                    "dropped": 47,
                    "switched": 0,
                    "success_rate_pct": 13.0,
                },
            ],
            "utterance_metrics": {
                "total": 159,
                "detected": 0,
                "missed": 159,
                "detection_rate_pct": 0.0,
                "missed_rate_pct": 100.0,
            },
            "missed_utterances": [],
            "escalations": {
                "total_escalated": 47,
                "sessions": [
                    {"session_id": "session-001", "channel": "Connect Chat", "mode": "Text",
                     "start_time": "2026-05-08T09:14:00Z", "end_state": "Dropped", "turns": 5, "locale": "en_GB"},
                    {"session_id": "session-002", "channel": "Connect Voice", "mode": "Speech",
                     "start_time": "2026-05-08T10:32:00Z", "end_state": "Dropped", "turns": 3, "locale": "en_GB"},
                ],
            },
        },
    ],
    "flow_metrics": [
        {
            "flow_name": "INBOUND",
            "flow_type": "INBOUND",
            "metrics": {
                "FLOWS_STARTED": 312,
                "FLOWS_OUTCOME": 298,
                "PERCENT_FLOWS_OUTCOME": 95.5,
                "AVG_FLOW_TIME": {"raw_seconds": 23, "formatted": "23s"},
                "MAX_FLOW_TIME": {"raw_seconds": 187, "formatted": "3m 7s"},
            },
        },
        {
            "flow_name": "TRANSFER",
            "flow_type": "TRANSFER",
            "metrics": {
                "FLOWS_STARTED": 89,
                "FLOWS_OUTCOME": 86,
                "PERCENT_FLOWS_OUTCOME": 96.6,
                "AVG_FLOW_TIME": {"raw_seconds": 8, "formatted": "8s"},
                "MAX_FLOW_TIME": {"raw_seconds": 45, "formatted": "45s"},
            },
        },
    ],
    "lex_cloudwatch_metrics": [
        {"bot_name": "coversatonalaibot", "metric_name": "RuntimeRequestCount",       "total": 159, "data_points": []},
        {"bot_name": "coversatonalaibot", "metric_name": "MissedUtteranceCount",       "total": 159, "data_points": []},
        {"bot_name": "coversatonalaibot", "metric_name": "DetectedUtteranceCount",     "total": 0,   "data_points": []},
        {"bot_name": "coversatonalaibot", "metric_name": "RuntimeThrottledEvents",     "total": 2,   "data_points": []},
        {"bot_name": "coversatonalaibot", "metric_name": "RuntimeSuccessfulRequestLatency", "total": 342.5, "data_points": []},
    ],
}


@app.get("/bot-metrics")
def bot_metrics_endpoint(days: int = Query(default=7, ge=1, le=90),
                          max_samples: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
    if _is_mock():
        return {"mock": True, **_MOCK_BOT_METRICS}
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).isoformat()
    end = now.isoformat()
    try:
        data = _invoke_tool("get_bot_metrics", [
            {"name": "query_type",  "type": "string", "value": "all"},
            {"name": "start_time",  "type": "string", "value": start},
            {"name": "end_time",    "type": "string", "value": end},
            {"name": "interval",    "type": "string", "value": "TOTAL"},
            {"name": "days",        "type": "string", "value": str(days)},
            {"name": "max_samples", "type": "string", "value": str(max_samples)},
        ])
        return {"mock": False, **data}
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.error("bot-metrics endpoint error: %s", exc, exc_info=True)
        return {"mock": False, "error": str(exc),
                "bot_inventory": {"total_bots": 0, "bots": []},
                "lex_analytics": [], "flow_metrics": [], "lex_cloudwatch_metrics": []}


@app.get("/contacts")
def contacts(
    request: Request,
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    contact_status: Optional[str] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None, ge=0, le=86400),
    max_duration_seconds: Optional[int] = Query(default=None, ge=0, le=86400),
    max_results: int = Query(default=25, ge=1, le=100),
) -> Dict[str, Any]:
    # Validate contact_status against known enum
    if contact_status and contact_status.upper() not in _VALID_CONTACT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid contact_status. Allowed: {sorted(_VALID_CONTACT_STATUSES)}")
    if contact_status:
        contact_status = contact_status.upper()
    if _is_mock():
        return {"mock": True, "contacts": _MOCK_CONTACTS, "total_count": len(_MOCK_CONTACTS)}
    now = datetime.now(timezone.utc)
    extra_params: List[Dict[str, Any]] = [
        {"name": "start_time", "type": "string", "value": start or (now - timedelta(hours=8)).isoformat()},
        {"name": "end_time", "type": "string", "value": end or now.isoformat()},
        {"name": "max_results", "type": "string", "value": str(max_results)},
    ]
    if contact_status:
        extra_params.append({"name": "contact_status", "type": "string", "value": contact_status})
    if min_duration_seconds is not None:
        extra_params.append({"name": "min_duration_seconds", "type": "string", "value": str(min_duration_seconds)})
    if max_duration_seconds is not None:
        extra_params.append({"name": "max_duration_seconds", "type": "string", "value": str(max_duration_seconds)})
    try:
        data = _invoke_tool("search_contacts", extra_params)
        contacts_list = []
        for c in data.get("contacts", []):
            ts = c.get("timestamp")
            contacts_list.append({
                "contactId": c.get("contact_id"),
                "dateTime": ts.isoformat() if hasattr(ts, "isoformat") else ts,
                "agent": c.get("agent_name", "Unassigned"),
                "queue": c.get("queue_name") or c.get("queue_id") or "—",
                "duration": int(c.get("duration_seconds") or 0),
                "status": c.get("contact_status", "UNKNOWN"),
                "channel": c.get("channel"),
                "hasRecording": c.get("has_recording", False),
            })
        return {"mock": False, "contacts": contacts_list, "total_count": data.get("total_count", len(contacts_list))}
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to search contacts") from exc


def _assert_valid_contact_id(contact_id: str) -> None:
    """Raise 400 if contact_id doesn't match the expected Amazon Connect pattern."""
    if not _CONTACT_ID_RE.match(contact_id):
        raise HTTPException(status_code=400, detail="Invalid contact_id format")


@app.get("/transcript/{contact_id}")
def get_transcript(contact_id: str) -> Dict[str, Any]:
    _assert_valid_contact_id(contact_id)
    if _is_mock():
        return {"mock": True, "contact_id": contact_id, "segments": _MOCK_TRANSCRIPT_SEGMENTS}
    try:
        data = _invoke_tool("get_transcript", [{"name": "contact_id", "type": "string", "value": contact_id}])
        return {
            "mock": False,
            "contact_id": contact_id,
            "segments": data.get("segments", []),
            "status": data.get("status"),
            "channel": data.get("channel"),
            "source": data.get("source"),
            "message": data.get("message"),
            "still_active": data.get("still_active"),
            "cl_realtime_enabled": data.get("cl_realtime_enabled"),
            "cl_segments_count": data.get("cl_segments_count", 0),
            "qc_segments_count": data.get("qc_segments_count", 0),
            "sentiment_summary": data.get("sentiment_summary"),
        }
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch transcript") from exc


@app.get("/sentiment/{contact_id}")
def get_contact_sentiment(contact_id: str) -> Dict[str, Any]:
    """Lightweight endpoint that returns only the sentiment summary for a live contact."""
    _assert_valid_contact_id(contact_id)
    if _is_mock():
        return {"contact_id": contact_id, "sentiment": {"overall": "POSITIVE", "score": 0.6,
            "customer": {"overall": "POSITIVE", "score": 0.6, "total_turns": 3, "counts": {"POSITIVE": 2, "NEUTRAL": 1, "NEGATIVE": 0, "MIXED": 0}},
            "agent":    {"overall": "NEUTRAL",  "score": 0.0, "total_turns": 2, "counts": {"POSITIVE": 1, "NEUTRAL": 1, "NEGATIVE": 0, "MIXED": 0}}}}
    try:
        data = _invoke_tool("get_transcript", [{"name": "contact_id", "type": "string", "value": contact_id}])
        return {
            "contact_id":  contact_id,
            "still_active": data.get("still_active", False),
            "sentiment":   data.get("sentiment_summary"),
            "source":      data.get("source"),
        }
    except Exception:  # pylint: disable=broad-except
        return {"contact_id": contact_id, "sentiment": None}


@app.get("/transcript/{contact_id}/summarize")
def summarize_transcript(contact_id: str) -> Dict[str, Any]:
    _assert_valid_contact_id(contact_id)
    if _is_mock():
        return {
            "mock": True,
            "contact_id": contact_id,
            "segment_count": 3,
            "summary": (
                "**Escalation Request — Billing Dispute**\n\n"
                "**Key Issues**\n"
                "- Customer reported an unresolved billing charge and requested immediate escalation.\n\n"
                "**Resolution**\n"
                "Agent acknowledged the escalation and initiated the supervisor callback process. "
                "Customer expressed satisfaction before ending the call.\n\n"
                "**Sentiment Arc**\n"
                "Negative → Neutral → Positive\n\n"
                "**Action Items**\n"
                "- Supervisor follow-up callback scheduled within 2 hours."
            ),
        }

    # 1. Fetch the transcript
    try:
        data = _invoke_tool("get_transcript", [{"name": "contact_id", "type": "string", "value": contact_id}])
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch transcript for summarization") from exc

    segments = data.get("segments", [])
    if not segments:
        return {
            "contact_id": contact_id,
            "segment_count": 0,
            "summary": data.get("message") or "No transcript is available for this contact — nothing to summarize.",
        }

    # 2. Build a readable transcript block
    lines: List[str] = []
    for seg in segments:
        speaker = seg.get("speaker", "UNKNOWN")
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        time_label = seg.get("time") or ""
        sentiment = (seg.get("sentiment") or "").upper()
        line = f"[{speaker}]"
        if time_label:
            line += f" ({time_label})"
        line += f": {text}"
        if sentiment and sentiment != "NEUTRAL":
            line += f"  [{sentiment}]"
        lines.append(line)
    transcript_text = "\n".join(lines)

    # 3. Send to Bedrock for summarization
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    prompt = (
        "You are an Amazon Connect supervisor assistant reviewing a contact transcript.\n\n"
        f"TRANSCRIPT (contact {contact_id}):\n{transcript_text}\n\n"
        "Provide a concise summary using this exact Markdown structure:\n\n"
        "**Summary** — one sentence describing the main topic and outcome.\n\n"
        "**Key Issues**\n"
        "- bullet list of issues raised by the customer\n\n"
        "**Resolution**\n"
        "What was resolved, or what was left open.\n\n"
        "**Sentiment Arc**\n"
        "Customer sentiment progression (e.g. Frustrated → Relieved).\n\n"
        "**Action Items**\n"
        "- Any follow-up required. If none, write 'None'.\n\n"
        "Keep the total response under 250 words."
    )

    import boto3  # pylint: disable=import-outside-toplevel
    bedrock = boto3.client("bedrock-runtime", region_name=region)
    configured_model = os.getenv("BEDROCK_MODEL_ID", "")
    candidates = [m for m in [
        configured_model,
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "anthropic.claude-3-5-haiku-20241022-v1:0",
        "amazon.nova-lite-v1:0",
    ] if m]

    for model_id in candidates:
        try:
            resp = bedrock.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
            )
            summary = resp["output"]["message"]["content"][0]["text"]
            LOGGER.info("Transcript summarized with model '%s' for contact %s.", model_id, contact_id)
            return {"contact_id": contact_id, "segment_count": len(segments), "summary": summary}
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Bedrock model '%s' failed during summarization: %s", model_id, exc)

    # Fallback — plain listing if all Bedrock calls fail
    fallback = f"Transcript contains {len(segments)} turns:\n\n" + "\n".join(
        f"**{s.get('speaker','?')}**: {(s.get('text') or '').strip()}" for s in segments[:15]
    )
    return {"contact_id": contact_id, "segment_count": len(segments), "summary": fallback}


@app.get("/recording/{contact_id}")
def get_recording(contact_id: str) -> Dict[str, Any]:
    _assert_valid_contact_id(contact_id)
    if _is_mock():
        return {"mock": True, "contact_id": contact_id, "url": None, "message": "Recording not available in mock mode."}
    try:
        data = _invoke_tool("get_recording_url", [{"name": "contact_id", "type": "string", "value": contact_id}])
        return {
            "mock": False,
            "contact_id": contact_id,
            "url": data.get("url"),
            "message": data.get("message"),
            "recording": data.get("recording"),
        }
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch recording URL") from exc


# ── Supervisor: Monitor / Barge-In ─────────────────────────────────────────────

class MonitorContactRequest(BaseModel):
    supervisor_user_id: str = Field(..., min_length=1, max_length=128,
                                    description="Amazon Connect userId of the supervisor (UUID from agent ARN)")
    allow_barge: bool = Field(True, description="Grant barge-in capability alongside silent monitoring")

    @field_validator('supervisor_user_id')
    @classmethod
    def _valid_user_id(cls, v: str) -> str:
        import re
        if not re.match(r'^[a-f0-9\-]{8,}$', v.lower()):
            raise ValueError('supervisor_user_id must be a UUID-style Connect userId')
        return v


@app.post("/contacts/{contact_id}/monitor")
def start_monitor(contact_id: str, body: MonitorContactRequest) -> Dict[str, Any]:
    """Initiate supervisor monitoring (with optional barge-in) on a live contact.

    Amazon Connect will ring the supervisor's CCP with a MONITOR contact.
    The supervisor accepts it in their CCP to start hearing the call.
    With allow_barge=True, Connect also enables the in-CCP barge-in toggle.
    """
    _assert_valid_contact_id(contact_id)
    if _is_mock():
        return {
            "mock": True,
            "contact_id": contact_id,
            "monitor_contact_id": str(uuid.uuid4()),
            "status": "monitoring_initiated",
            "message": "Mock mode: monitoring simulated.",
        }
    connect_client = _get_connect_client()
    instance_id = _get_instance_id()
    try:
        capabilities = ['SILENT_MONITOR', 'BARGE'] if body.allow_barge else ['SILENT_MONITOR']
        resp = connect_client.monitor_contact(
            InstanceId=instance_id,
            ContactId=contact_id,
            UserId=body.supervisor_user_id,
            AllowedMonitorCapabilities=capabilities,
            ClientToken=str(uuid.uuid4()),
        )
        return {
            "mock": False,
            "contact_id": contact_id,
            "monitor_contact_id": resp.get('ContactId'),
            "status": "monitoring_initiated",
            "capabilities": capabilities,
        }
    except connect_client.exceptions.ContactNotFoundException:
        raise HTTPException(status_code=404, detail="Contact not found or already ended")
    except connect_client.exceptions.UserNotFoundException:
        raise HTTPException(status_code=404, detail="Supervisor userId not found in this Connect instance")
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.error("MonitorContact failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"MonitorContact API error: {exc}") from exc


@app.delete("/contacts/{contact_id}/monitor")
def stop_monitor(contact_id: str) -> Dict[str, Any]:
    """Disconnect a supervisor's active monitoring/barge-in contact."""
    _assert_valid_contact_id(contact_id)
    if _is_mock():
        return {"mock": True, "contact_id": contact_id, "status": "stopped"}
    # Connect does not expose a direct 'stop monitoring' API — the supervisor
    # ends the contact via their CCP. This endpoint is a no-op placeholder
    # kept for API consistency; the actual disconnection happens client-side
    # via Streams agent.getContacts() → monitoringContact.destroy()
    return {"contact_id": contact_id, "status": "use_streams_to_stop",
            "message": "Disconnect the monitoring contact via your CCP or Connect Streams."}


def _get_connect_client():
    """Return a boto3 Connect client (cached on module level if possible)."""
    import boto3
    region = os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
    return boto3.client("connect", region_name=region)


def _get_instance_id() -> str:
    instance_id = os.environ.get("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        raise HTTPException(status_code=503, detail="CONNECT_INSTANCE_ID not configured")
    return instance_id


@app.post("/query")
def query(request: QueryRequest, req: Request) -> Dict[str, Any]:
    session_id = request.session_id or str(uuid.uuid4())
    # Log message length only — never log message content (potential PII)
    LOGGER.info("Query received: len=%d (session=%s)", len(request.message), session_id)
    if _is_mock():
        return {"response": _mock_chat_response(request.message), "session_id": session_id}

    # Rate limit by client IP
    client_ip = req.client.host if req.client else "unknown"
    _check_rate_limit(client_ip)

    try:
        agent = ConnectAnalyticsAgent()
        response = agent.query(request.message, session_id=session_id)
        return {"response": response, "session_id": session_id}
    except Exception as exc:  # pylint: disable=broad-except
        exc_str = str(exc)
        exc_type = type(exc).__name__

        _operational = (
            "ClientError", "NoCredentialsError", "EndpointResolutionError",
            "ValidationException", "AccessDeniedException", "ConnectTimeout",
            "ConnectionError", "RuntimeError",
        )
        if exc_type in _operational or any(
            tag in exc_str for tag in (
                "credentials", "region", "endpoint", "model identifier",
                "tool", "Tools directory", "instance", "CONNECT_INSTANCE_ID",
            )
        ):
            LOGGER.warning("Query could not be completed (%s: %s) — returning friendly response.", exc_type, exc_str)
        else:
            LOGGER.error("Unexpected error handling query (%s: %s).", exc_type, exc_str, exc_info=True)

        friendly = (
            "I'm sorry, I ran into an issue processing your query. "
            "You can ask about **queue health**, **agent states**, "
            "**historical metrics** (e.g. 'average handle time last 7 days'), "
            "or **search for contacts and transcripts**. "
            "If the problem persists please check the server logs."
        )
        # Never return raw exception strings to the client — log only
        return {"response": friendly, "session_id": session_id}


# ── Chat session persistence ───────────────────────────────────────────────────
# Sessions are stored server-side (SQLite locally, DynamoDB in cloud) so they
# survive browser clears, container restarts (via the agent_data volume), and
# can be shared across devices.

class _UpsertSessionRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(default="New session", max_length=200)
    createdAt: str = Field(default="")
    updatedAt: str = Field(default="")
    messages: List[Dict[str, Any]] = Field(default_factory=list)


@app.get("/sessions")
def list_sessions() -> List[Dict[str, Any]]:
    try:
        return create_session_store().list_sessions()
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to list sessions")
        raise HTTPException(status_code=500, detail="Failed to list sessions")


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> Dict[str, Any]:
    _assert_valid_contact_id(session_id)  # reuse UUID/alphanum validator
    try:
        session = create_session_store().get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except HTTPException:
        raise
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to get session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to get session")


@app.put("/sessions/{session_id}", status_code=200)
def upsert_session(session_id: str, body: _UpsertSessionRequest) -> Dict[str, Any]:
    _assert_valid_contact_id(session_id)
    if body.id != session_id:
        raise HTTPException(status_code=400, detail="Session id mismatch")
    try:
        create_session_store().upsert_session(body.model_dump())
        return {"ok": True}
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to upsert session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to save session")


@app.delete("/sessions/{session_id}", status_code=200)
def delete_session(session_id: str) -> Dict[str, Any]:
    _assert_valid_contact_id(session_id)
    try:
        create_session_store().delete_session(session_id)
        return {"ok": True}
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to delete session %s", session_id)
        raise HTTPException(status_code=500, detail="Failed to delete session")


@app.get("/realtime-queue-metrics")
def realtime_queue_metrics() -> Dict[str, Any]:
    """
    Current metric snapshot for all standard queues:
    contacts_in_queue, agents_available, agents_on_call, oldest_contact_age.
    Polled every 5 s by the frontend live-queue chart.
    """
    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        return {"timestamp": datetime.utcnow().isoformat(), "queues": []}

    import boto3
    connect = boto3.client("connect", region_name=os.getenv("AWS_REGION", "eu-west-2"))
    ts = datetime.utcnow().isoformat()

    # 1 — fetch all standard queues (names + IDs)
    queues: List[Dict] = []
    try:
        paginator = connect.get_paginator("list_queues")
        for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD"]):
            queues.extend(page.get("QueueSummaryList", []))
    except Exception as exc:
        LOGGER.warning("realtime_queue_metrics: list_queues failed: %s", exc)
        return {"timestamp": ts, "queues": [], "error": str(exc)}

    if not queues:
        return {"timestamp": ts, "queues": []}

    queue_id_to_name = {q["Id"]: q["Name"] for q in queues}
    queue_ids = list(queue_id_to_name.keys())[:100]  # API max 100

    # 2 — GetCurrentMetricData for all queues in one call
    metrics_by_queue: Dict[str, Dict] = {}
    try:
        resp = connect.get_current_metric_data(
            InstanceId=instance_id,
            Filters={"Queues": queue_ids, "Channels": ["VOICE", "CHAT"]},
            Groupings=["QUEUE"],
            CurrentMetrics=[
                {"Name": "CONTACTS_IN_QUEUE",  "Unit": "COUNT"},
                {"Name": "AGENTS_AVAILABLE",    "Unit": "COUNT"},
                {"Name": "AGENTS_ON_CONTACT",   "Unit": "COUNT"},
                {"Name": "AGENTS_ONLINE",       "Unit": "COUNT"},
                {"Name": "OLDEST_CONTACT_AGE",  "Unit": "SECONDS"},
                {"Name": "CONTACTS_SCHEDULED",  "Unit": "COUNT"},
            ],
        )
        for result in resp.get("MetricResults", []):
            queue_info = result.get("Dimensions", {}).get("Queue", {})
            qid = queue_info.get("Id", "")
            values: Dict[str, float] = {}
            for item in result.get("Collections", []):
                values[item["Metric"]["Name"]] = item.get("Value") or 0
            metrics_by_queue[qid] = {
                "id":                  qid,
                "name":                queue_id_to_name.get(qid, qid),
                "contacts_in_queue":   int(values.get("CONTACTS_IN_QUEUE", 0)),
                "agents_available":    int(values.get("AGENTS_AVAILABLE", 0)),
                "agents_on_call":      int(values.get("AGENTS_ON_CONTACT", 0)),
                "agents_online":       int(values.get("AGENTS_ONLINE", 0)),
                "oldest_contact_age":  int(values.get("OLDEST_CONTACT_AGE", 0)),
                "contacts_scheduled":  int(values.get("CONTACTS_SCHEDULED", 0)),
            }
    except Exception as exc:
        LOGGER.error("realtime_queue_metrics: get_current_metric_data failed: %s", exc)
        return {"timestamp": ts, "queues": [], "error": str(exc)}

    # Include queues with zero activity so they always appear in the chart
    for qid, qname in queue_id_to_name.items():
        if qid not in metrics_by_queue:
            metrics_by_queue[qid] = {
                "id": qid, "name": qname,
                "contacts_in_queue": 0, "agents_available": 0,
                "agents_on_call": 0, "agents_online": 0,
                "oldest_contact_age": 0, "contacts_scheduled": 0,
            }

    return {"timestamp": ts, "queues": list(metrics_by_queue.values())}


@app.delete("/sessions", status_code=200)
def delete_all_sessions() -> Dict[str, Any]:
    try:
        create_session_store().delete_all()
        return {"ok": True}
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to delete all sessions")
        raise HTTPException(status_code=500, detail="Failed to delete all sessions")
