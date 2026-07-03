import asyncio
import json
import logging
import os
import random
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from agent_core import ConnectAnalyticsAgent, LocalToolInvoker
import startup_scan
import eventbridge_listener
import theme_scan
import disconnect_reasons
import callback_analytics
import contact_scan_utils
import contact_stats
import hours_of_operation
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
    "CONNECTED", "CONNECTING", "INCOMING", "MISSED", "REJECTED", "ENDED",
    "QUEUED", "ERROR", "TRANSFERRED", "HELD",
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


# Runtime override for mock mode, settable via PUT /config/mock-mode without a
# container restart. None = defer to the MOCK_MODE env var (the original
# behaviour); True/False = explicit override for the life of this process.
_mock_override: Optional[bool] = None


def _is_mock() -> bool:
    if _mock_override is not None:
        return _mock_override
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
    "how many agents are busy": "There are currently around 80 agents busy across all 8 queues. 'Billing' has the most agents on contacts (14), followed by 'Technical Support' (10) — around 30 agents are Available and 13 contacts are waiting in queue.",
    "who is my busiest agent": "Your busiest agent today is Sarah Johnson with 24 contacts handled. She has an average handle time of 4:32 and is currently available.",
}

# ── Mock realtime fleet ────────────────────────────────────────────────────────
# Production-scale simulation for MOCK_MODE: ~130 contact slots (~100-115 live
# at any instant) served by a 140-agent roster, so the realtime UI can be
# exercised with the volumes a real contact centre produces. Each slot runs an
# endless idle-gap → contact cycle derived purely from the wall clock, which
# keeps successive polls coherent: durations tick up naturally, contacts end
# and are replaced organically, and every realtime endpoint reads the same
# snapshot. Slot i is always served by agent i, so no agent is double-booked.

_MOCK_RT_QUEUES = [
    {"id": "mock-queue-1", "name": "Technical Support"},
    {"id": "mock-queue-2", "name": "Billing"},
    {"id": "mock-queue-3", "name": "General Enquiry"},
    {"id": "mock-queue-4", "name": "Sales"},
    {"id": "mock-queue-5", "name": "Customer Support"},
    {"id": "mock-queue-6", "name": "VIP Support"},
    {"id": "mock-queue-7", "name": "Fraud & Security"},
    {"id": "mock-queue-8", "name": "Mortgages"},
]

_MOCK_FIRST_NAMES = [
    "Sarah", "Marcus", "Priya", "Andre", "Mina", "Dylan", "Amelia", "Noah", "Fatima", "Leo",
    "Grace", "Kwame", "Isla", "Mateo", "Hannah", "Ravi", "Chloe", "Tomasz", "Yasmin", "Ethan",
    "Nadia", "Oliver", "Zara", "Callum", "Ingrid", "Jamal", "Rosa", "Felix", "Aisha", "Hugo",
    "Elena", "Declan", "Sofia", "Arjun", "Freya", "Kofi", "Lucia", "Brendan", "Maya", "Stefan",
]
_MOCK_LAST_NAMES = [
    "Johnson", "Lee", "Patel", "Lewis", "Chen", "Brooks", "Okafor", "Sharma", "Mitchell", "Novak",
    "Garcia", "Ahmed", "Kowalski", "Ndiaye", "Murphy", "Silva", "Tanaka", "O'Brien", "Haddad", "Larsen",
    "Mensah", "Rossi", "Dubois", "Petrov", "Campbell", "Nguyen", "Osei", "Fitzgerald", "Iqbal", "Moreau",
    "Svensson", "Adeyemi", "Kaur", "Byrne", "Costa",
]


def _build_mock_fleet(count: int = 140) -> List[Dict[str, str]]:
    rng = random.Random(20260703)
    agents: List[Dict[str, str]] = []
    seen = set()
    while len(agents) < count:
        name = f"{rng.choice(_MOCK_FIRST_NAMES)} {rng.choice(_MOCK_LAST_NAMES)}"
        if name in seen:
            continue
        seen.add(name)
        agents.append({
            "agentId": f"mock-agent-{len(agents) + 1:03d}",
            "name": name,
            "arn": f"arn:aws:connect:eu-west-2:000000000000:instance/mock/agent/mock-agent-{len(agents) + 1:03d}",
        })
    return agents


_MOCK_FLEET = _build_mock_fleet()
_MOCK_CONTACT_SLOTS = 130
_MOCK_FLEET_STATE_CACHE: Dict[str, Any] = {}


def _fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _mock_fleet_state(now: Optional[datetime] = None) -> Dict[str, Any]:
    """One coherent snapshot of every live mock contact, cached per second so
    the several endpoints polled together all agree."""
    now = now or datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    cached = _MOCK_FLEET_STATE_CACHE.get("state")
    if cached and cached[0] == epoch:
        return cached[1]

    contacts: List[Dict[str, Any]] = []
    agent_contact: Dict[int, Dict[str, Any]] = {}

    for slot in range(_MOCK_CONTACT_SLOTS):
        srng = random.Random(slot * 9973 + 17)
        cycle = srng.randint(240, 1800)              # lifetime of each contact in this slot
        gap = srng.randint(30, max(40, cycle // 3))  # idle time between contacts
        period = cycle + gap
        offset = srng.randint(0, 1_000_000)
        phase = (epoch + offset) % period
        if phase < gap:
            continue  # slot idle right now → live count breathes around ~110
        age = phase - gap
        generation = (epoch + offset) // period
        crng = random.Random((slot << 20) ^ generation)

        roll = crng.random()
        if roll < 0.58:
            kind = "inbound"
        elif roll < 0.72:
            kind = "bot"
        elif roll < 0.81:
            kind = "callback"
        elif roll < 0.92:
            kind = "outbound"
        else:
            kind = "transfer"

        if kind == "inbound":
            channel = "VOICE" if crng.random() < 0.70 else ("CHAT" if crng.random() < 0.83 else "TASK")
        elif kind == "bot":
            channel = "VOICE" if crng.random() < 0.60 else "CHAT"
        elif kind == "transfer":
            channel = "VOICE" if crng.random() < 0.85 else "CHAT"
        else:
            channel = "VOICE"

        queue = crng.choice(_MOCK_RT_QUEUES)
        wait = crng.randint(8, 200)                  # seconds until an agent answers
        agent = _MOCK_FLEET[slot]
        contact_id = (
            f"{slot:08x}-{generation & 0xffff:04x}-4{slot % 16:03x}"
            f"-9{generation % 16:03x}-{(slot * 1_000_003 + generation) % 16**12:012x}"
        )
        number = f"+4477{(slot * 7919 + generation * 104729) % 10**7:07d}"
        voice_customer = {"type": "TELEPHONE_NUMBER", "address": number, "display": f"*******{number[-4:]}"}
        voice_system = {"type": "TELEPHONE_NUMBER", "address": "+441512345000", "display": "*******5000"}

        contact: Dict[str, Any] = {
            "contactId": contact_id,
            "channel": channel,
            "contactType": "inbound" if kind == "bot" else kind,
            "isOutbound": kind == "outbound",
            "isCallback": kind == "callback",
            "isBot": kind == "bot",
            "isInternalBotSession": False,
            "initiationMethod": {"inbound": "INBOUND", "bot": "INBOUND", "callback": "CALLBACK",
                                 "outbound": "OUTBOUND", "transfer": "TRANSFER"}[kind],
            "customerEndpoint": voice_customer if channel == "VOICE" else {},
            "systemEndpoint": voice_system if channel == "VOICE" and kind != "callback" else {},
            "initiatedAt": datetime.fromtimestamp(epoch - age, tz=timezone.utc).isoformat(),
            "contactTerminal": False,
            "contactEndedAt": None,
            "transferDirection": None,
            "transferTargetType": None,
            "transferTargetLabel": None,
            "queueArn": "",
            "agentArn": "",
            "agentName": "",
        }

        if kind == "bot":
            contact.update({"contactState": "CONNECTED_TO_SYSTEM", "escalatedToAgent": False,
                            "queueId": "", "queueName": "—"})
        elif kind == "outbound":
            contact.update({"contactState": "CONNECTED_TO_AGENT", "escalatedToAgent": True,
                            "queueId": "", "queueName": "—",
                            "agentArn": agent["arn"], "agentName": agent["name"],
                            "outboundAgentArn": agent["arn"], "outboundAgentName": agent["name"]})
            agent_contact[slot] = contact
        else:
            connected = age >= wait
            contact.update({
                "contactState": "CONNECTED_TO_AGENT" if connected else "QUEUED",
                "escalatedToAgent": connected,
                "queueId": queue["id"], "queueName": queue["name"],
                "queueArn": f"arn:aws:connect:eu-west-2:000000000000:instance/mock/queue/{queue['id']}",
            })
            if connected:
                contact["agentArn"] = agent["arn"]
                contact["agentName"] = agent["name"]
                agent_contact[slot] = contact
            if kind == "callback":
                contact["callbackScheduled"] = bool(not connected and crng.random() < 0.25)
            if kind == "transfer":
                direction = "internal" if crng.random() < 0.70 else "external"
                if direction == "external":
                    contact.update({"transferDirection": "external", "transferTargetType": "phone",
                                    "transferTargetLabel": "*******4999"})
                elif crng.random() < 0.6:
                    contact.update({"transferDirection": "internal", "transferTargetType": "queue",
                                    "transferTargetLabel": queue["name"]})
                else:
                    contact.update({"transferDirection": "internal", "transferTargetType": "agent",
                                    "transferTargetLabel": agent["name"]})

        contact["_slot"] = slot
        contact["_kind"] = kind
        contact["_age"] = age
        contact["_wait"] = wait
        contacts.append(contact)

    state = {"now": now, "contacts": contacts, "agent_contact": agent_contact}
    _MOCK_FLEET_STATE_CACHE["state"] = (epoch, state)
    return state


def _public_contact(contact: Dict[str, Any]) -> Dict[str, Any]:
    """Strip the simulator-internal keys before returning a contact to the UI."""
    return {k: v for k, v in contact.items() if not k.startswith("_")}


def _mock_agent_states_now() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    state = _mock_fleet_state(now)
    agent_contact = state["agent_contact"]
    # Idle-agent statuses reshuffle every 5 minutes so the wallboard drifts
    epoch5 = int(now.timestamp()) // 300
    agents: List[Dict[str, Any]] = []
    for i, member in enumerate(_MOCK_FLEET):
        contact = agent_contact.get(i)
        if contact is not None:
            agents.append({
                "agentId": member["agentId"], "name": member["name"],
                "status": "On Call",
                "currentQueue": contact["queueName"] if contact["queueName"] != "—" else "Outbound",
                "timeInStatus": _fmt_hms(contact["_age"] - contact["_wait"] if not contact["isOutbound"] else contact["_age"]),
                "contactId": contact["contactId"],
                "hasActiveContact": True,
            })
            continue
        rng = random.Random((i << 8) ^ epoch5)
        roll = rng.random()
        if roll < 0.40:
            status = "Available"
        elif roll < 0.52:
            status = "After Contact Work"
        elif roll < 0.63:
            status = "Non-Productive"
        elif roll < 0.97:
            status = "Offline"
        else:
            status = "Error"
        agents.append({
            "agentId": member["agentId"], "name": member["name"],
            "status": status,
            "currentQueue": rng.choice(_MOCK_RT_QUEUES)["name"] if status not in ("Offline",) else "—",
            "timeInStatus": _fmt_hms(rng.randint(20, 5400)),
            "contactId": "",
            "hasActiveContact": False,
        })
    for entry in agents:
        if _MOCK_FORCE_LOGOUT_APPLIED.get(entry["agentId"]) and not entry["hasActiveContact"]:
            entry["status"] = "Offline"
            entry["currentQueue"] = "—"
            entry["contactId"] = ""
    return agents


# Track mock force-logout state so the UI reflects changes within a session
_MOCK_FORCE_LOGOUT_APPLIED: Dict[str, bool] = {}

_MOCK_QUEUES = [
    {"id": "mock-queue-1", "name": "General Support"},
    {"id": "mock-queue-2", "name": "ARIA Banking Agents"},
    {"id": "mock-queue-3", "name": "Escalation Queue"},
]

_MOCK_AGENTS = [
    {"id": "mock-agent-1", "name": "Sarah Mitchell"},
    {"id": "mock-agent-2", "name": "James Okafor"},
    {"id": "mock-agent-3", "name": "Priya Sharma"},
]

_MOCK_NOW = datetime.now(timezone.utc)
_MOCK_CONTACTS = [
    {
        "contactId": "c-10236",
        "dateTime": (_MOCK_NOW - timedelta(minutes=42)).isoformat().replace("+00:00", "Z"),
        "agent": "James Okafor",
        "agentId": "mock-agent-2",
        "queue": "General Support",
        "queueId": "mock-queue-1",
        "duration": 412,
        "status": "ENDED",
        "channel": "VOICE",
        "initiationMethod": "INBOUND",
        "phoneNumber": "+447700900123",
        "customAttributes": {"customerName": "Alex Thompson", "customerId": "CUST-001", "authStatus": "authenticated"},
        "hasRecording": True,
    },
    {
        "contactId": "c-10231",
        "dateTime": (_MOCK_NOW - timedelta(hours=2, minutes=5)).isoformat().replace("+00:00", "Z"),
        "agent": "Sarah Mitchell",
        "agentId": "mock-agent-1",
        "queue": "ARIA Banking Agents",
        "queueId": "mock-queue-2",
        "duration": 268,
        "status": "ENDED",
        "channel": "CHAT",
        "initiationMethod": "TRANSFER",
        "phoneNumber": "+447700900456",
        "customAttributes": {"customerName": "Maya Singh", "customerId": "CUST-002", "authStatus": "pending"},
        "hasRecording": False,
    },
    {
        "contactId": "c-10228",
        "dateTime": (_MOCK_NOW - timedelta(hours=3, minutes=12)).isoformat().replace("+00:00", "Z"),
        "agent": "Priya Sharma",
        "agentId": "mock-agent-3",
        "queue": "Escalation Queue",
        "queueId": "mock-queue-3",
        "duration": 198,
        "status": "MISSED",
        "channel": "VOICE",
        "initiationMethod": "CALLBACK",
        "phoneNumber": "+447700900789",
        "customAttributes": {"customerName": "Jordan Bell", "customerId": "CUST-003", "authStatus": "failed"},
        "hasRecording": False,
    },
    {
        "contactId": "c-10214",
        "dateTime": (_MOCK_NOW - timedelta(hours=4, minutes=20)).isoformat().replace("+00:00", "Z"),
        "agent": "Sarah Mitchell",
        "agentId": "mock-agent-1",
        "queue": "General Support",
        "queueId": "mock-queue-1",
        "duration": 622,
        "status": "CONNECTED",
        "channel": "CHAT",
        "initiationMethod": "OUTBOUND",
        "phoneNumber": "+447700900321",
        "customAttributes": {"customerName": "Noah Carter", "customerId": "CUST-004", "authStatus": "authenticated"},
        "hasRecording": False,
    },
    {
        "contactId": "c-10198",
        "dateTime": (_MOCK_NOW - timedelta(hours=6, minutes=40)).isoformat().replace("+00:00", "Z"),
        "agent": "James Okafor",
        "agentId": "mock-agent-2",
        "queue": "Escalation Queue",
        "queueId": "mock-queue-3",
        "duration": 95,
        "status": "REJECTED",
        "channel": "TASK",
        "initiationMethod": "API",
        "phoneNumber": "+447700900654",
        "customAttributes": {"customerName": "Ella Wong", "customerId": "CUST-005", "authStatus": "queued"},
        "hasRecording": False,
    },
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
                LOGGER.debug('Suppressed exception', exc_info=True)

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


class MockModeRequest(BaseModel):
    mock: bool = Field(..., description="True to force dummy data on every screen, false to use real AWS data")


@app.put("/config/mock-mode")
def set_mock_mode(req: MockModeRequest) -> Dict[str, Any]:
    """
    Runtime toggle for mock mode — no container restart needed. Only meaningful
    against this local FastAPI server (the cloud Lambda doesn't serve this route
    at all), so it's inherently local-only.
    """
    global _mock_override
    _mock_override = req.mock
    LOGGER.info("Mock mode runtime override set to %s", req.mock)
    return {"mock_mode": _is_mock()}


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
        agents = _mock_agent_states_now()
        by_status = defaultdict(int)
        for a in agents:
            by_status[a["status"]] += 1
        queued = [c for c in _mock_fleet_state()["contacts"] if c["contactState"] == "QUEUED"]
        return {
            "mock": True,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "metrics": {
                "agents_online": len(agents) - by_status["Offline"],
                "agents_available": by_status["Available"],
                "agents_on_call": by_status["On Call"],
                "agents_in_acw": by_status["After Contact Work"],
                "contacts_in_queue": len(queued),
                "oldest_contact_age": _fmt_hms(max((c["_age"] for c in queued), default=0)),
            },
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


# ── Reporting window resolution (shared by historical endpoints) ─────────────

# GetMetricDataV2 retains data for "the previous 3 months" and rejects older
# StartTimes with the same generic InvalidParameterException it uses for
# too-long windows. 88 days is safe for every month-length combination, so
# custom start dates older than that are rejected with a clear message
# instead of surfacing as a silently empty chart.
_METRIC_RETENTION_DAYS = 88


def _resolve_history_window(
    days: int, start_date: Optional[str], end_date: Optional[str],
) -> Tuple[datetime, datetime, str]:
    """Resolve a preset (`days` back from now) or custom (`start_date`/`end_date`,
    inclusive YYYY-MM-DD) selection into (start_dt, end_dt, period_label)."""
    now = datetime.now(timezone.utc)
    if start_date or end_date:
        if not (start_date and end_date):
            raise HTTPException(status_code=400, detail="start_date and end_date must be provided together")
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_incl = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="start_date and end_date must be YYYY-MM-DD") from exc
        # Inclusive end date → end of that day, clamped to now for open/future ranges.
        end_dt = min(end_incl + timedelta(days=1), now)
        if start_dt >= end_dt:
            raise HTTPException(status_code=400, detail="start_date must be on or before end_date and not in the future")
        if (end_dt - start_dt) > timedelta(days=90):
            raise HTTPException(status_code=400, detail="Date range cannot exceed 90 days")
        if start_dt < now - timedelta(days=_METRIC_RETENTION_DAYS):
            raise HTTPException(
                status_code=400,
                detail=f"start_date can be at most {_METRIC_RETENTION_DAYS} days ago — "
                       "Amazon Connect retains historical metrics for about 3 months",
            )
        label = f"{start_dt.strftime('%-d %b %Y')} – {end_incl.strftime('%-d %b %Y')}"
        return start_dt, end_dt, label
    return now - timedelta(days=days), now, f"Last {days} days"


# GetMetricDataV2 rejects DAY-interval requests spanning more than ~35 days
# ("The time range specified exceeds the specified limit"), so longer windows
# are split into chunks and the per-day buckets merged.
_METRIC_WINDOW_CHUNK_DAYS = 35


def _window_chunks(start_dt: datetime, end_dt: datetime) -> List[Tuple[datetime, datetime]]:
    chunks: List[Tuple[datetime, datetime]] = []
    cur = start_dt
    while cur < end_dt:
        nxt = min(cur + timedelta(days=_METRIC_WINDOW_CHUNK_DAYS), end_dt)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


# ── Mock historical data generation ──────────────────────────────────────────
# Generated for whatever window is requested (this is what makes the period
# selector visibly work in mock mode). Values are seeded per calendar day, so
# the same date always reports the same numbers and overlapping windows agree.

def _iter_window_days(start_dt: datetime, end_dt: datetime):
    day = start_dt.date()
    last = (end_dt - timedelta(seconds=1)).date()
    while day <= last:
        yield day
        day += timedelta(days=1)


def _mock_day_stats(day) -> Dict[str, int]:
    """Deterministic per-day mock volumes — one source of truth so the
    historical, abandonment and breakdown mocks all agree on a given date."""
    rng = random.Random(day.toordinal())
    weekend = day.weekday() >= 5
    handled = max(0, round(rng.randint(3, 12) * (0.35 if weekend else 1.0)) + rng.randint(-1, 1))
    avg_ht = rng.randint(95, 290) if handled else 0
    avg_talk = round(avg_ht * rng.uniform(0.55, 0.72)) if handled else 0
    avg_acw = round(avg_ht * rng.uniform(0.20, 0.32)) if handled else 0
    aband = max(0, round(handled * rng.uniform(0.05, 0.20)) + (1 if rng.random() < 0.2 else 0))
    queued_extra = rng.randint(0, 2)
    return {"handled": handled, "avg_ht": avg_ht, "avg_talk": avg_talk,
            "avg_acw": avg_acw, "aband": aband, "queued_extra": queued_extra}


def _gen_mock_historical(start_dt: datetime, end_dt: datetime, period_label: str) -> Dict[str, Any]:
    data, abandoned = [], []
    for day in _iter_window_days(start_dt, end_dt):
        s = _mock_day_stats(day)
        handled, avg_ht, avg_talk, avg_acw = s["handled"], s["avg_ht"], s["avg_talk"], s["avg_acw"]
        dk, lbl = day.strftime("%Y-%m-%d"), day.strftime("%-d %b")
        data.append({
            "date_key": dk,
            "label": lbl,
            "CONTACTS_HANDLED": handled,
            "AVG_HANDLE_TIME": avg_ht,
            "TOTAL_HANDLE_TIME_MIN": round(avg_ht * handled / 60, 2) if handled else 0,
            "AVG_TALK_TIME": avg_talk,
            "TOTAL_TALK_TIME_MIN": round(avg_talk * handled / 60, 2) if handled else 0,
            "CONTACTS_QUEUED": handled + s["aband"] + s["queued_extra"],
            "AVG_AFTER_CONTACT_WORK_TIME": avg_acw,
            "TOTAL_ACW_TIME_MIN": round(avg_acw * handled / 60, 2) if handled else 0,
        })
        abandoned.append({"date_key": dk, "label": lbl, "CONTACTS_ABANDONED": s["aband"]})
    return {"period": period_label, "data": data, "abandoned": abandoned}


# Short waits dominate real abandonment curves — weights per wait bucket.
_ABANDON_BUCKET_WEIGHTS = [0.28, 0.20, 0.15, 0.10, 0.12, 0.09, 0.06]


def _gen_mock_abandonment(start_dt: datetime, end_dt: datetime) -> Dict[str, Any]:
    """Window-aware mock for /abandonment-buckets — per-day abandon counts
    match _gen_mock_historical exactly (same _mock_day_stats seed)."""
    totals = {k: 0 for k in contact_stats.BUCKET_KEYS}
    daily = []
    scanned = 0
    for day in _iter_window_days(start_dt, end_dt):
        s = _mock_day_stats(day)
        scanned += s["handled"] + s["aband"]
        rng = random.Random(day.toordinal() * 7 + 1)
        row = {k: 0 for k in contact_stats.BUCKET_KEYS}
        for _ in range(s["aband"]):
            r = rng.random()
            acc = 0.0
            chosen = contact_stats.BUCKET_KEYS[-1]
            for key, w in zip(contact_stats.BUCKET_KEYS, _ABANDON_BUCKET_WEIGHTS):
                acc += w
                if r <= acc:
                    chosen = key
                    break
            row[chosen] += 1
            totals[chosen] += 1
        daily.append({"date": day.strftime("%Y-%m-%d"), **row})
    return {
        "buckets": [{**b, "count": totals[b["key"]]} for b in contact_stats.ABANDON_BUCKETS],
        "daily": daily,
        "total_abandoned": sum(totals.values()),
        "contacts_scanned": scanned,
        "truncated": False,
    }


# ── Mock per-queue and per-agent breakdown data ──────────────────────────────

_MOCK_QUEUES = [
    {"name": "Technical Support", "splits": [0.35, 0.25, 0.22, 0.18],
     "avg_ht": [240, 195, 180, 155], "avg_acw": [75, 60, 52, 45], "aband_rate": [0.14, 0.11, 0.09, 0.08]},
    {"name": "Billing",           "splits": [0.25, 0.35, 0.22, 0.18],
     "avg_ht": [195, 215, 185, 160], "avg_acw": [60, 70, 55, 48], "aband_rate": [0.10, 0.13, 0.08, 0.07]},
    {"name": "General Enquiry",   "splits": [0.22, 0.22, 0.35, 0.18],
     "avg_ht": [160, 175, 165, 145], "avg_acw": [45, 50, 48, 40], "aband_rate": [0.07, 0.08, 0.12, 0.06]},
    {"name": "Sales",             "splits": [0.18, 0.18, 0.21, 0.46],
     "avg_ht": [280, 295, 270, 310], "avg_acw": [90, 95, 85, 100], "aband_rate": [0.06, 0.07, 0.06, 0.05]},
]

_MOCK_AGENTS = [
    {"name": "Sarah Johnson", "splits": [0.26, 0.20, 0.18, 0.17, 0.19],
     "avg_ht": [195, 170, 190, 175, 185], "avg_acw": [60, 52, 58, 54, 57], "aband_rate": [0.0]*5},
    {"name": "Mike Chen",     "splits": [0.20, 0.26, 0.18, 0.17, 0.19],
     "avg_ht": [210, 225, 200, 215, 205], "avg_acw": [68, 72, 65, 70, 66], "aband_rate": [0.0]*5},
    {"name": "Lisa Park",     "splits": [0.18, 0.18, 0.26, 0.17, 0.21],
     "avg_ht": [180, 185, 175, 178, 180], "avg_acw": [55, 57, 53, 56, 54], "aband_rate": [0.0]*5},
    {"name": "James Wilson",  "splits": [0.17, 0.17, 0.17, 0.26, 0.23],
     "avg_ht": [240, 250, 235, 260, 245], "avg_acw": [78, 82, 76, 85, 80], "aband_rate": [0.0]*5},
    {"name": "Emma Davis",    "splits": [0.19, 0.19, 0.21, 0.23, 0.18],
     "avg_ht": [165, 170, 160, 168, 162], "avg_acw": [50, 53, 48, 52, 49], "aband_rate": [0.0]*5},
]


def _gen_mock_breakdown(entities: List[Dict], start_dt: datetime, end_dt: datetime) -> Dict:
    """Build daily per-entity breakdown across the requested window. Seeded per
    calendar day (like _gen_mock_historical) so windows agree where they overlap."""
    daily: List[Dict] = []
    totals: List[Dict] = []

    for day in _iter_window_days(start_dt, end_dt):
        rng = random.Random(day.toordinal() * 31 + len(entities))
        weekend = day.weekday() >= 5
        row: Dict = {"date_key": day.strftime("%Y-%m-%d"), "label": day.strftime("%-d %b")}
        for idx, ent in enumerate(entities):
            split = ent["splits"][idx % len(ent["splits"])]
            base = rng.randint(8, 18) * (0.35 if weekend else 1.0)
            n = max(0, round(base * split * (0.7 + rng.random() * 0.6)))
            ht = ent["avg_ht"][idx % len(ent["avg_ht"])] + rng.randint(-20, 20)
            acw = ent["avg_acw"][idx % len(ent["avg_acw"])] + rng.randint(-8, 8)
            rate = ent["aband_rate"][idx % len(ent["aband_rate"])]
            ab = round(n * rate) + (1 if rate > 0 and n > 0 and rng.random() < 0.25 else 0)
            row[ent["name"]] = {
                "CONTACTS_HANDLED": n,
                "CONTACTS_ABANDONED": ab,
                "AVG_HANDLE_TIME": ht,
                "AVG_AFTER_CONTACT_WORK_TIME": acw,
            }
        daily.append(row)

    for idx, ent in enumerate(entities):
        rng2 = random.Random(idx * 97 + len(daily))
        total_handled = sum(d[ent["name"]]["CONTACTS_HANDLED"] for d in daily)
        total_aband   = sum(d[ent["name"]]["CONTACTS_ABANDONED"] for d in daily)
        totals.append({
            "entity": ent["name"],
            "CONTACTS_HANDLED": total_handled,
            "CONTACTS_ABANDONED": total_aband,
            "AVG_HANDLE_TIME": ent["avg_ht"][idx % len(ent["avg_ht"])] + rng2.randint(-10, 10),
            "AVG_AFTER_CONTACT_WORK_TIME": ent["avg_acw"][idx % len(ent["avg_acw"])] + rng2.randint(-5, 5),
        })

    return {"daily": daily, "totals": totals, "entities": [e["name"] for e in entities]}


@app.get("/historical-metrics")
def historical_metrics(
    days: int = Query(default=30, ge=1, le=90),
    start_date: Optional[str] = Query(default=None, description="Custom range start, YYYY-MM-DD (inclusive)"),
    end_date: Optional[str] = Query(default=None, description="Custom range end, YYYY-MM-DD (inclusive)"),
) -> Dict[str, Any]:
    start_dt, end_dt, period_label = _resolve_history_window(days, start_date, end_date)
    if _is_mock():
        return {"mock": True, **_gen_mock_historical(start_dt, end_dt, period_label)}
    try:
        def _invoke_day(metrics_str: str) -> List[Dict[str, Any]]:
            # One call per ≤35-day chunk — GetMetricDataV2 rejects longer
            # DAY-interval windows. Daily buckets don't overlap across chunks,
            # so concatenation is safe.
            results: List[Dict[str, Any]] = []
            for c_start, c_end in _window_chunks(start_dt, end_dt):
                results.extend(_invoke_tool("get_historical_metrics", [
                    {"name": "start_time", "type": "string", "value": c_start.isoformat()},
                    {"name": "end_time",   "type": "string", "value": c_end.isoformat()},
                    {"name": "group_by",   "type": "string", "value": "QUEUE"},
                    {"name": "interval",   "type": "string", "value": "DAY"},
                    {"name": "metrics",    "type": "string", "value": metrics_str},
                ]).get("results", []))
            return results

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
        handled_rows = _invoke_day("CONTACTS_HANDLED,AVG_HANDLE_TIME,AVG_TALK_TIME")
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
                "AVG_TALK_TIME": round(m.get("AVG_TALK_TIME") or 0),
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
            handled_count   = h.get("CONTACTS_HANDLED", 0)
            avg_handle      = h.get("AVG_HANDLE_TIME", 0)
            avg_talk        = h.get("AVG_TALK_TIME", 0)
            avg_acw         = a.get("AVG_AFTER_CONTACT_WORK_TIME", 0)
            # Total = avg (seconds) × number of contacts handled that day, expressed in minutes (2dp)
            total_handle_min = round((avg_handle * handled_count) / 60, 2) if handled_count else 0
            total_talk_min   = round((avg_talk   * handled_count) / 60, 2) if handled_count else 0
            total_acw_min    = round((avg_acw    * handled_count) / 60, 2) if handled_count else 0
            chart_data.append({
                "date_key": dk,
                "label": h.get("label") or a.get("label") or dk,
                "CONTACTS_HANDLED": handled_count,
                "AVG_HANDLE_TIME": avg_handle,
                "TOTAL_HANDLE_TIME_MIN": total_handle_min,
                "AVG_TALK_TIME": avg_talk,
                "TOTAL_TALK_TIME_MIN": total_talk_min,
                "CONTACTS_QUEUED": a.get("CONTACTS_QUEUED", 0),
                "AVG_AFTER_CONTACT_WORK_TIME": avg_acw,
                "TOTAL_ACW_TIME_MIN": total_acw_min,
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
            "period": period_label,
            "data": chart_data,
            "abandoned": abandoned_chart,
        }
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch historical metrics") from exc


@app.get("/historical-breakdown")
def historical_breakdown(
    days: int = Query(default=30, ge=1, le=90),
    group_by: str = Query(default="QUEUE"),
    start_date: Optional[str] = Query(default=None, description="Custom range start, YYYY-MM-DD (inclusive)"),
    end_date: Optional[str] = Query(default=None, description="Custom range end, YYYY-MM-DD (inclusive)"),
) -> Dict[str, Any]:
    """Return per-queue or per-agent daily breakdown for the 4 key metrics."""
    group_by = group_by.upper()
    if group_by not in ("QUEUE", "AGENT"):
        raise HTTPException(status_code=400, detail="group_by must be QUEUE or AGENT")

    start_dt, end_dt, period_label = _resolve_history_window(days, start_date, end_date)

    if _is_mock():
        entities = _MOCK_QUEUES if group_by == "QUEUE" else _MOCK_AGENTS
        bd = _gen_mock_breakdown(entities, start_dt, end_dt)
        return {"mock": True, "group_by": group_by, "period": period_label, **bd}

    try:
        # One call per ≤35-day chunk (GetMetricDataV2 window limit), then merge
        # per-entity: timelines concatenate (daily buckets never overlap across
        # chunks); totals sum, with averages weighted by contacts handled.
        merged: Dict[str, Dict[str, Any]] = {}
        for c_start, c_end in _window_chunks(start_dt, end_dt):
            result = _invoke_tool("get_historical_metrics", [
                {"name": "start_time", "type": "string", "value": c_start.isoformat()},
                {"name": "end_time",   "type": "string", "value": c_end.isoformat()},
                {"name": "group_by",   "type": "string", "value": group_by},
                {"name": "interval",   "type": "string", "value": "DAY"},
                {"name": "metrics",    "type": "string",
                 "value": "CONTACTS_HANDLED,CONTACTS_ABANDONED,AVG_HANDLE_TIME,AVG_AFTER_CONTACT_WORK_TIME"},
            ])
            for row in result.get("dimension_results", []):
                ent_name = row.get("display_name") or row.get("dimension_value", "Unknown")
                m = merged.setdefault(ent_name, {
                    "display_name": ent_name, "timeline": [],
                    "_handled": 0, "_abandoned": 0, "_ht_weighted": 0.0, "_acw_weighted": 0.0,
                })
                m["timeline"].extend(row.get("timeline", []))
                t = row.get("totals", {})
                handled = int(t.get("CONTACTS_HANDLED") or 0)
                m["_handled"] += handled
                m["_abandoned"] += int(t.get("CONTACTS_ABANDONED") or 0)
                m["_ht_weighted"] += float(t.get("AVG_HANDLE_TIME") or 0) * handled
                m["_acw_weighted"] += float(t.get("AVG_AFTER_CONTACT_WORK_TIME") or 0) * handled

        dimension_results = [
            {
                "display_name": m["display_name"],
                "timeline": m["timeline"],
                "totals": {
                    "CONTACTS_HANDLED": m["_handled"],
                    "CONTACTS_ABANDONED": m["_abandoned"],
                    "AVG_HANDLE_TIME": (m["_ht_weighted"] / m["_handled"]) if m["_handled"] else 0,
                    "AVG_AFTER_CONTACT_WORK_TIME": (m["_acw_weighted"] / m["_handled"]) if m["_handled"] else 0,
                },
            }
            for m in merged.values()
        ]

        def _parse_dt(iso_str):
            try:
                return datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
            except Exception:
                return None

        def _fmt_label(iso_str):
            dt = _parse_dt(iso_str)
            return dt.strftime("%-d %b") if dt else str(iso_str)[:10]

        def _date_key(iso_str):
            dt = _parse_dt(iso_str)
            return dt.strftime("%Y-%m-%d") if dt else str(iso_str)[:10]

        if not dimension_results:
            raise HTTPException(status_code=204, detail="No breakdown data returned from Connect")

        entities_list = [row.get("display_name") or row.get("dimension_value", "Unknown")
                         for row in dimension_results]

        # Build list of all date keys in order
        all_date_keys: Dict[str, str] = {}
        for row in dimension_results:
            for bucket in row.get("timeline", []):
                dk = _date_key(bucket.get("interval_start"))
                if dk not in all_date_keys:
                    all_date_keys[dk] = _fmt_label(bucket.get("interval_start"))
        sorted_dates = sorted(all_date_keys.keys())

        # Pivot to [{label, entity1: {metrics}, entity2: {metrics}}, ...]
        date_entity_map: Dict[str, Dict] = {dk: {"date_key": dk, "label": all_date_keys[dk]} for dk in sorted_dates}

        for row in dimension_results:
            ent_name = row.get("display_name") or row.get("dimension_value", "Unknown")
            for bucket in row.get("timeline", []):
                dk = _date_key(bucket.get("interval_start"))
                m = bucket.get("metrics", {})
                if dk in date_entity_map:
                    date_entity_map[dk][ent_name] = {
                        "CONTACTS_HANDLED": int(m.get("CONTACTS_HANDLED") or 0),
                        "CONTACTS_ABANDONED": int(m.get("CONTACTS_ABANDONED") or 0),
                        "AVG_HANDLE_TIME": round(float(m.get("AVG_HANDLE_TIME") or 0)),
                        "AVG_AFTER_CONTACT_WORK_TIME": round(float(m.get("AVG_AFTER_CONTACT_WORK_TIME") or 0)),
                    }

        daily = [date_entity_map[dk] for dk in sorted_dates]

        totals = []
        for row in dimension_results:
            ent_name = row.get("display_name") or row.get("dimension_value", "Unknown")
            t = row.get("totals", {})
            totals.append({
                "entity": ent_name,
                "CONTACTS_HANDLED": int(t.get("CONTACTS_HANDLED") or 0),
                "CONTACTS_ABANDONED": int(t.get("CONTACTS_ABANDONED") or 0),
                "AVG_HANDLE_TIME": round(float(t.get("AVG_HANDLE_TIME") or 0)),
                "AVG_AFTER_CONTACT_WORK_TIME": round(float(t.get("AVG_AFTER_CONTACT_WORK_TIME") or 0)),
            })

        return {
            "mock": False,
            "group_by": group_by,
            "period": period_label,
            "entities": entities_list,
            "daily": daily,
            "totals": totals,
        }
    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch historical breakdown") from exc


# ── Transcript theme discovery ──────────────────────────────────────────────────

class ThemeScanRequest(BaseModel):
    start: str = Field(..., description="ISO 8601 start of the date range")
    end: str = Field(..., description="ISO 8601 end of the date range")


@app.post("/transcript-themes/scan")
async def transcript_themes_scan(req: ThemeScanRequest) -> Dict[str, Any]:
    """Kick off a transcript theme scan for the given date range. Only one scan
    runs at a time — if one is already running, returns its current state instead
    of starting a second one."""
    if theme_scan.is_running():
        return {"started": False, **theme_scan.get_state()}

    if _is_mock():
        theme_scan.start_mock_scan(req.start, req.end)
        return {"started": True, **theme_scan.get_state()}

    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        raise HTTPException(status_code=400, detail="CONNECT_INSTANCE_ID is not configured")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    started = theme_scan.start_scan(req.start, req.end, instance_id, region, _invoke_tool)
    return {"started": started, **theme_scan.get_state()}


async def _theme_scan_sse_generator(q: asyncio.Queue) -> AsyncGenerator[str, None]:
    theme_scan.register_queue(q)
    try:
        state = theme_scan.get_state()
        if state["complete"] and not state["running"]:
            yield f"data: {json.dumps({'type': 'already_complete', 'ts': datetime.now(timezone.utc).isoformat(), 'themes': state['themes']})}\n\n"
            return
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield msg
                if '"scan_complete"' in msg or '"scan_error"' in msg:
                    break
            except asyncio.TimeoutError:
                yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
    finally:
        theme_scan.unregister_queue(q)


@app.get("/transcript-themes/stream")
async def transcript_themes_stream():
    """SSE stream of theme-scan progress events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    return StreamingResponse(
        _theme_scan_sse_generator(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/transcript-themes/status")
def transcript_themes_status() -> Dict[str, Any]:
    """Snapshot of the current theme scan (for polling fallback / page reload)."""
    return {**theme_scan.get_state(), "mock_mode": _is_mock()}


# ── Disconnect-reason discovery ─────────────────────────────────────────────────

class DisconnectReasonScanRequest(BaseModel):
    start: str = Field(..., description="ISO 8601 start of the date range")
    end: str = Field(..., description="ISO 8601 end of the date range")


@app.post("/disconnect-reasons/scan")
async def disconnect_reasons_scan(req: DisconnectReasonScanRequest) -> Dict[str, Any]:
    """Kick off a disconnect-reason scan for the given date range. Only one scan
    runs at a time — if one is already running, returns its current state instead
    of starting a second one."""
    if disconnect_reasons.is_running():
        return {"started": False, **disconnect_reasons.get_state()}

    if _is_mock():
        disconnect_reasons.start_mock_scan(req.start, req.end)
        return {"started": True, **disconnect_reasons.get_state()}

    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        raise HTTPException(status_code=400, detail="CONNECT_INSTANCE_ID is not configured")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    started = disconnect_reasons.start_scan(req.start, req.end, instance_id, region)
    return {"started": started, **disconnect_reasons.get_state()}


async def _disconnect_reasons_sse_generator(q: asyncio.Queue) -> AsyncGenerator[str, None]:
    disconnect_reasons.register_queue(q)
    try:
        state = disconnect_reasons.get_state()
        if state["complete"] and not state["running"]:
            yield f"data: {json.dumps({'type': 'already_complete', 'ts': datetime.now(timezone.utc).isoformat(), 'result': state['result']})}\n\n"
            return
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield msg
                if '"scan_complete"' in msg or '"scan_error"' in msg:
                    break
            except asyncio.TimeoutError:
                yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
    finally:
        disconnect_reasons.unregister_queue(q)


@app.get("/disconnect-reasons/stream")
async def disconnect_reasons_stream():
    """SSE stream of disconnect-reason scan progress events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    return StreamingResponse(
        _disconnect_reasons_sse_generator(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/disconnect-reasons/status")
def disconnect_reasons_status() -> Dict[str, Any]:
    """Snapshot of the current disconnect-reason scan (for polling fallback / page reload)."""
    return {**disconnect_reasons.get_state(), "mock_mode": _is_mock()}


# ── Callback analytics ──────────────────────────────────────────────────────────

class CallbackScanRequest(BaseModel):
    start: str = Field(..., description="ISO 8601 start of the date range")
    end: str = Field(..., description="ISO 8601 end of the date range")


@app.post("/callback-analytics/scan")
async def callback_analytics_scan(req: CallbackScanRequest) -> Dict[str, Any]:
    """Kick off a callback-analytics scan for the given date range. Only one scan
    runs at a time — if one is already running, returns its current state instead
    of starting a second one."""
    if callback_analytics.is_running():
        return {"started": False, **callback_analytics.get_state()}

    if _is_mock():
        callback_analytics.start_mock_scan(req.start, req.end)
        return {"started": True, **callback_analytics.get_state()}

    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        raise HTTPException(status_code=400, detail="CONNECT_INSTANCE_ID is not configured")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    started = callback_analytics.start_scan(req.start, req.end, instance_id, region)
    return {"started": started, **callback_analytics.get_state()}


async def _callback_analytics_sse_generator(q: asyncio.Queue) -> AsyncGenerator[str, None]:
    callback_analytics.register_queue(q)
    try:
        state = callback_analytics.get_state()
        if state["complete"] and not state["running"]:
            yield f"data: {json.dumps({'type': 'already_complete', 'ts': datetime.now(timezone.utc).isoformat(), 'result': state['result']})}\n\n"
            return
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                yield msg
                if '"scan_complete"' in msg or '"scan_error"' in msg:
                    break
            except asyncio.TimeoutError:
                yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
    finally:
        callback_analytics.unregister_queue(q)


@app.get("/callback-analytics/stream")
async def callback_analytics_stream():
    """SSE stream of callback-analytics scan progress events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    return StreamingResponse(
        _callback_analytics_sse_generator(q),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/callback-analytics/status")
def callback_analytics_status() -> Dict[str, Any]:
    """Snapshot of the current callback-analytics scan (for polling fallback / page reload)."""
    return {**callback_analytics.get_state(), "mock_mode": _is_mock()}


# ── Abandonment wait-time buckets & callback snapshot (contact-record stats) ────

@app.get("/abandonment-buckets")
async def abandonment_buckets_endpoint(
    days: int = Query(default=30, ge=1, le=90),
    start_date: Optional[str] = Query(default=None, description="Custom range start, YYYY-MM-DD (inclusive)"),
    end_date: Optional[str] = Query(default=None, description="Custom range end, YYYY-MM-DD (inclusive)"),
) -> Dict[str, Any]:
    """Calls abandoned in queue, bucketed by wait time (≤10s…>2m), from
    contact records. The realtime page calls this with start_date=end_date=
    today for a "today so far" view. Window clamps to 55 days
    (search_contacts limit) — the response says when it did."""
    start_dt, end_dt, period_label = _resolve_history_window(days, start_date, end_date)

    if _is_mock():
        window = contact_scan_utils.clamp_search_window(start_dt.isoformat(), end_dt.isoformat())
        gen = _gen_mock_abandonment(
            contact_scan_utils.parse_dt(window["start"]), contact_scan_utils.parse_dt(window["end"]),
        )
        return {"mock": True, "period": period_label, **gen, "window": window}

    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        raise HTTPException(status_code=400, detail="CONNECT_INSTANCE_ID is not configured")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    try:
        result = await contact_stats.abandonment_buckets(
            instance_id, region, start_dt.isoformat(), end_dt.isoformat(),
        )
        return {"mock": False, "period": period_label, **result}
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Abandonment-bucket stats failed")
        raise HTTPException(status_code=502, detail="Failed to compute abandonment buckets") from exc


def _mock_callback_today_now() -> Dict[str, Any]:
    """Today's callback snapshot at fleet scale: waiting/connected read live
    from the simulation; finished outcomes grow steadily through the day."""
    now = datetime.now(timezone.utc)
    state = _mock_fleet_state(now)
    live = [c for c in state["contacts"] if c["_kind"] == "callback"]
    waiting = sum(1 for c in live if c["contactState"] == "QUEUED")
    connected = len(live) - waiting
    # Finished outcomes accumulate across a 12h working day starting 07:00
    day_fraction = min(1.0, max(0.0, (now.hour - 7 + now.minute / 60) / 12))
    rng = random.Random(now.toordinal() * 13 + 5)
    finished = int(rng.randint(95, 120) * day_fraction)
    succeeded = int(finished * 0.72)
    customer_failed = int(finished * 0.09)
    abandoned = finished - succeeded - customer_failed
    retried = int(finished * 0.18)
    return {
        "requested": finished + waiting + connected,
        "waiting": waiting, "connected": connected,
        "succeeded": succeeded, "customer_failed": customer_failed, "abandoned": abandoned,
        "retried": retried, "attempts": finished + retried + waiting + connected,
        "truncated": False,
    }


@app.get("/callback-metrics/today")
async def callback_metrics_today() -> Dict[str, Any]:
    """Live snapshot of today's callbacks: waiting in queue now, connected to
    an agent now, plus today's finished outcomes (succeeded / failed at the
    customer leg / abandoned) and retry counts."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if _is_mock():
        return {"mock": True, "as_of": now.isoformat(), **_mock_callback_today_now()}

    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        raise HTTPException(status_code=400, detail="CONNECT_INSTANCE_ID is not configured")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    try:
        result = await contact_stats.callback_snapshot(
            instance_id, region, start.isoformat(), now.isoformat(),
        )
        return {"mock": False, "as_of": now.isoformat(), **result}
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Callback snapshot failed")
        raise HTTPException(status_code=502, detail="Failed to compute callback snapshot") from exc


@app.get("/agent-states")
def agent_states() -> Dict[str, Any]:
    if _is_mock():
        agents = _mock_agent_states_now()
        return {"mock": True, "agents": agents, "agent_count": len(agents)}
    try:
        data = _invoke_tool("get_agent_states", [])
        agents = []
        for agent in data.get("agents", []):
            raw_status = agent.get("current_status", "")
            has_active = bool(agent.get("contacts")) or raw_status in {"ON_CALL", "AFTER_CONTACT_WORK"}
            agents.append({
                "agentId": agent.get("agent_id", ""),
                "name": agent.get("display_name") or agent.get("username", "Unknown"),
                "status": _STATUS_DISPLAY.get(raw_status, raw_status.replace("_", " ").title()),
                "currentQueue": agent.get("current_queue_name") or agent.get("current_queue") or "—",
                "timeInStatus": agent.get("time_in_status", "00:00:00"),
                "contactId": agent.get("contact_id") or "",
                "hasActiveContact": has_active,
            })
        return {"mock": False, "agents": agents, "agent_count": len(agents)}
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=502, detail="Failed to fetch agent states") from exc


class ForceLogoutRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


@app.post("/agents/{agent_id}/force-logout")
def force_logout_agent(agent_id: str, body: ForceLogoutRequest = ForceLogoutRequest()) -> Dict[str, Any]:
    """Force an agent to Offline via PutUserStatus, with active-contact guard."""
    if not agent_id or len(agent_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid agent_id")

    if _is_mock():
        # In mock mode, block if agent has an active contact
        target = next((a for a in _mock_agent_states_now() if a["agentId"] == agent_id), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Agent {agent_id!r} not found")
        if target.get("hasActiveContact"):
            return {
                "forced": False,
                "blocked": True,
                "reason": (
                    f"Agent has an active contact ({target['contactId']}). "
                    "End or transfer the contact before forcing logout."
                ),
                "active_contacts": [{"contact_id": target["contactId"], "channel": "VOICE", "state": "CONNECTED"}],
            }
        _MOCK_FORCE_LOGOUT_APPLIED[agent_id] = True
        return {
            "forced": True,
            "blocked": False,
            "user_id": agent_id,
            "new_status": "Offline",
            "message": f"Agent '{target['name']}' has been forced to Offline.",
        }

    try:
        import boto3  # pylint: disable=import-outside-toplevel
        from botocore.exceptions import BotoCoreError, ClientError  # pylint: disable=import-outside-toplevel
        instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
        if not instance_id:
            raise HTTPException(status_code=500, detail="CONNECT_INSTANCE_ID not configured")

        connect = boto3.client("connect")

        # ── Check for active contacts ────────────────────────────────────────
        ud_response = connect.get_current_user_data(
            InstanceId=instance_id,
            Filters={"Agents": [agent_id]},
            MaxResults=1,
        )
        user_data = (ud_response.get("UserDataList") or [{}])[0]
        active_contacts = user_data.get("Contacts", [])
        status_name = (user_data.get("Status") or {}).get("StatusName", "").lower()

        if active_contacts:
            return {
                "forced": False,
                "blocked": True,
                "reason": (
                    f"Agent has {len(active_contacts)} active contact(s). "
                    "End or transfer all contacts before forcing logout."
                ),
                "active_contacts": [
                    {
                        "contact_id": c.get("ContactId"),
                        "channel": c.get("Channel"),
                        "state": c.get("AgentContactState"),
                    }
                    for c in active_contacts
                ],
            }

        if "after" in status_name or "acw" in status_name:
            return {
                "forced": False,
                "blocked": True,
                "reason": (
                    "Agent is in After Contact Work (ACW). "
                    "The contact has not been fully closed. "
                    "Wait for ACW to complete or ask the agent to close the contact."
                ),
                "active_contacts": [],
            }

        # ── Resolve Offline status ID ────────────────────────────────────────
        offline_id: Optional[str] = None
        paginator = connect.get_paginator("list_agent_statuses")
        for page in paginator.paginate(InstanceId=instance_id):
            for s in page.get("AgentStatusSummaryList", []):
                if s.get("Name", "").lower() == "offline":
                    offline_id = s["Id"]
                    break
            if offline_id:
                break

        if not offline_id:
            raise HTTPException(status_code=500, detail="Could not find Offline status in this Connect instance")

        # ── Force the agent Offline ──────────────────────────────────────────
        connect.put_user_status(
            InstanceId=instance_id,
            UserId=agent_id,
            AgentStatusId=offline_id,
        )
        LOGGER.info("Force-logged out agent %s (reason: %s)", agent_id, body.reason or "supervisor action")
        return {
            "forced": True,
            "blocked": False,
            "user_id": agent_id,
            "new_status": "Offline",
            "message": f"Agent {agent_id} has been forced to Offline successfully.",
        }

    except HTTPException:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error during force logout for agent %s", agent_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc



def _mock_active_calls_now() -> List[Dict[str, Any]]:
    state = _mock_fleet_state()
    calls = []
    for slot, contact in sorted(state["agent_contact"].items()):
        agent = _MOCK_FLEET[slot]
        duration = contact["_age"] if contact["isOutbound"] else contact["_age"] - contact["_wait"]
        calls.append({
            "contactId": contact["contactId"],
            "agent": agent["name"],
            "queue": contact["queueName"] if contact["queueName"] != "—" else "Outbound",
            "channel": contact["channel"],
            "duration": max(0, duration),
            "status": "CONNECTED",
            "escalatedFromBot": False,
            "previousContactId": None,
            "enqueuedAt": None,
            "connectedToAgentAt": None,
        })
    return calls


@app.get("/active-calls")
def active_calls() -> Dict[str, Any]:
    if _is_mock():
        calls = _mock_active_calls_now()
        return {"mock": True, "calls": calls, "total": len(calls)}
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


def _mock_live_contacts() -> Dict[str, Any]:
    """
    MOCK_MODE dataset for /live-contacts, generated from the shared fleet
    simulation (~100+ concurrent contacts). Covers every contact type the
    UI can render — inbound, bot/IVR, outbound, callbacks (waiting and
    scheduled), and internal/external transfers to queue/agent/phone — at
    the volumes a production contact centre produces, with contacts ageing
    and churning naturally between polls.
    """
    state = _mock_fleet_state()
    contacts = state["contacts"]

    inbound = [_public_contact(c) for c in contacts if c["_kind"] == "inbound"]
    bot_contacts = [_public_contact(c) for c in contacts if c["_kind"] == "bot"]
    outbound = [_public_contact(c) for c in contacts if c["_kind"] == "outbound"]
    callbacks = [_public_contact(c) for c in contacts if c["_kind"] == "callback"]
    transfers = [_public_contact(c) for c in contacts if c["_kind"] == "transfer"]

    all_contacts = inbound + bot_contacts + outbound + callbacks + transfers
    callbacks_waiting = [c for c in callbacks if not c.get("callbackScheduled")]
    callbacks_scheduled = [c for c in callbacks if c.get("callbackScheduled")]

    callbacks_by_queue: Dict[str, Dict[str, int]] = {}
    for c in callbacks:
        entry = callbacks_by_queue.setdefault(c["queueName"], {"waiting": 0, "scheduled": 0})
        entry["scheduled" if c.get("callbackScheduled") else "waiting"] += 1

    summary = {
        "total": len(all_contacts),
        "inbound": len(inbound),
        "outbound": len(outbound),
        "callbacks_waiting": len(callbacks_waiting),
        "callbacks_scheduled": len(callbacks_scheduled),
        "bot_handling": len(bot_contacts),
        "agent_connected": sum(1 for c in all_contacts if c.get("escalatedToAgent")),
        "transfers": len(transfers),
        "transfers_internal": sum(1 for c in transfers if c.get("transferDirection") == "internal"),
        "transfers_external": sum(1 for c in transfers if c.get("transferDirection") == "external"),
        "voice": sum(1 for c in all_contacts if c.get("channel") == "VOICE"),
        "chat": sum(1 for c in all_contacts if c.get("channel") == "CHAT"),
        "task": sum(1 for c in all_contacts if c.get("channel") == "TASK"),
    }
    return {
        "listener_active": True, "polling_mode": False, "setup_required": False, "mock": True,
        "summary": summary,
        "inbound": inbound,
        "outbound": outbound,
        "callbacks": callbacks,
        "bot_contacts": bot_contacts,
        "transfers": transfers,
        "all": all_contacts,
        "callbacks_by_queue": callbacks_by_queue,
    }


@app.get("/live-contacts")
def live_contacts() -> Dict[str, Any]:
    """
    All live contacts tracked via EventBridge → SQS (preferred) with automatic
    fallback to direct Connect API polling via get_current_user_data when
    EventBridge is not configured.  The `listener_active` flag tells the UI
    which mode is in use; `polling_mode` is True when using the fallback.
    """
    if _is_mock():
        return _mock_live_contacts()

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
                                LOGGER.debug('Suppressed exception', exc_info=True)
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

# ── Mock contact flow event data ────────────────────────────────────────────
_MOCK_CONTACT_ID_FOR_FLOW = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

_MOCK_FLOW_EVENTS = {
    "contact_id": _MOCK_CONTACT_ID_FOR_FLOW,
    "mock": True,
    "flows_traversed": ["MainInboundFlow", "BillingSubflow"],
    "event_count": 9,
    "total_duration_ms": 284_000,
    "events": [
        {
            "event_id": "b1-welcome",
            "timestamp_ms": 0,
            "elapsed_ms": 0,
            "block_id": "b1",
            "block_type": "PlayPrompt",
            "block_name": "Welcome Message",
            "flow_name": "MainInboundFlow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Success",
            "duration_ms": 4_200,
            "parameters": {"TextToSpeechMessage": "Welcome to ACME support. Your call may be recorded."},
            "results": "Success",
            "source": "flow_log",
        },
        {
            "event_id": "b2-intent",
            "timestamp_ms": 4_200,
            "elapsed_ms": 4_200,
            "block_id": "b2",
            "block_type": "GetCustomerInput",
            "block_name": "Capture Customer Intent",
            "flow_name": "MainInboundFlow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Billing",
            "duration_ms": 9_500,
            "parameters": {
                "TextToSpeechMessage": "For billing press 1. For technical support press 2. To speak with an agent press 0.",
                "InputTimeLimitSeconds": "8",
            },
            "results": "Billing",
            "source": "flow_log",
        },
        {
            "event_id": "b3-hours",
            "timestamp_ms": 13_700,
            "elapsed_ms": 13_700,
            "block_id": "b3",
            "block_type": "CheckHoursOfOperation",
            "block_name": "Check Business Hours",
            "flow_name": "MainInboundFlow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "In hours",
            "duration_ms": 80,
            "parameters": {"HoursOfOperationId": "arn:aws:connect:eu-west-2:123456789:hours/09-17-weekdays"},
            "results": "In hours",
            "source": "flow_log",
        },
        {
            "event_id": "b4-attr-check",
            "timestamp_ms": 13_780,
            "elapsed_ms": 13_780,
            "block_id": "b4",
            "block_type": "CheckContactAttributes",
            "block_name": "Check Account Status",
            "flow_name": "MainInboundFlow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Active",
            "duration_ms": 60,
            "parameters": {"Attribute": "AccountStatus", "ComparisonValue": "Active"},
            "results": "Active",
            "source": "flow_log",
        },
        {
            "event_id": "b5-lambda",
            "timestamp_ms": 13_840,
            "elapsed_ms": 13_840,
            "block_id": "b5",
            "block_type": "InvokeExternalResource",
            "block_name": "Get Account Balance",
            "flow_name": "MainInboundFlow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Success",
            "duration_ms": 380,
            "parameters": {
                "FunctionArn": "arn:aws:lambda:eu-west-2:123456789:function:connect-get-account-balance",
                "TimeLimit": "8",
            },
            "results": "Success",
            "source": "flow_log",
        },
        {
            "event_id": "b6-balance",
            "timestamp_ms": 14_220,
            "elapsed_ms": 14_220,
            "block_id": "b6",
            "block_type": "PlayPrompt",
            "block_name": "Read Account Balance",
            "flow_name": "MainInboundFlow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Success",
            "duration_ms": 3_800,
            "parameters": {"TextToSpeechMessage": "$.Attributes.AccountBalance"},
            "results": "Success",
            "source": "flow_log",
        },
        {
            "event_id": "b7-anything-else",
            "timestamp_ms": 18_020,
            "elapsed_ms": 18_020,
            "block_id": "b7",
            "block_type": "GetCustomerInput",
            "block_name": "Anything Else?",
            "flow_name": "BillingSubflow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Dispute",
            "duration_ms": 11_500,
            "parameters": {
                "TextToSpeechMessage": "Would you like to raise a billing dispute? Press 1 for yes, 2 to end the call.",
                "InputTimeLimitSeconds": "8",
            },
            "results": "Dispute",
            "source": "flow_log",
        },
        {
            "event_id": "b8-transfer",
            "timestamp_ms": 29_520,
            "elapsed_ms": 29_520,
            "block_id": "b8",
            "block_type": "TransferToQueue",
            "block_name": "Transfer to Billing Queue",
            "flow_name": "BillingSubflow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Success",
            "duration_ms": 254_480,
            "parameters": {"QueueId": "arn:aws:connect:eu-west-2:123456789:queue/billing-queue"},
            "results": "Success",
            "source": "flow_log",
        },
        {
            "event_id": "b9-disconnect",
            "timestamp_ms": 284_000,
            "elapsed_ms": 284_000,
            "block_id": "b9",
            "block_type": "DisconnectParticipant",
            "block_name": "End Call",
            "flow_name": "BillingSubflow",
            "flow_type": "CONTACT_FLOW",
            "outcome": "Disconnected",
            "duration_ms": 0,
            "parameters": {},
            "results": "Disconnected",
            "source": "flow_log",
        },
    ],
}

_MOCK_FLOW_FUNNEL = {
    "flow_name": "MainInboundFlow",
    "mock": True,
    "total_contacts": 150,
    "period_days": 30,
    "blocks": [
        {"sequence": 1,  "block_name": "Welcome Message",         "block_type": "PlayPrompt",             "count": 150, "pct": 100.0, "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 2,  "block_name": "Capture Customer Intent", "block_type": "GetCustomerInput",       "count": 148, "pct": 98.7,  "drop_count": 2,  "drop_pct": 1.3},
        {"sequence": 3,  "block_name": "Check Business Hours",    "block_type": "CheckHoursOfOperation",  "count": 148, "pct": 98.7,  "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 4,  "block_name": "Check Account Status",    "block_type": "CheckContactAttributes", "count": 120, "pct": 80.0,  "drop_count": 28, "drop_pct": 18.9},
        {"sequence": 5,  "block_name": "Get Account Balance",     "block_type": "InvokeExternalResource", "count": 85,  "pct": 56.7,  "drop_count": 35, "drop_pct": 29.2},
        {"sequence": 6,  "block_name": "Read Account Balance",    "block_type": "PlayPrompt",             "count": 83,  "pct": 55.3,  "drop_count": 2,  "drop_pct": 2.4},
        {"sequence": 7,  "block_name": "Anything Else?",          "block_type": "GetCustomerInput",       "count": 78,  "pct": 52.0,  "drop_count": 5,  "drop_pct": 6.0},
        {"sequence": 8,  "block_name": "Transfer to Billing Queue","block_type": "TransferToQueue",       "count": 35,  "pct": 23.3,  "drop_count": 43, "drop_pct": 55.1},
        {"sequence": 9,  "block_name": "End Call",                "block_type": "DisconnectParticipant",  "count": 112, "pct": 74.7,  "drop_count": 0,  "drop_pct": 0.0},
    ],
}

# Realistic conversational-bot flow template — reflects the full journey:
#   Entry → Start Recording → Invoke LLM/Lex → Check Intent
#     ├─ Self-service path  (bot handles): Fetch Data → Read Result → Confirm → Disconnect
#     └─ Escalation path    (bot gives up): Check Hours → Check Staffing → Set Queue
#                                           → Transfer to Queue → (Agent) → Disconnect
_MOCK_FLOW_FUNNEL_BOT = {
    "flow_name": "conversationalbot",
    "mock": True,
    "total_contacts": 200,
    "period_days": 30,
    "blocks": [
        {"sequence": 1,  "block_name": "Start Recording",            "block_type": "SetRecordingBehavior",   "count": 200, "pct": 100.0, "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 2,  "block_name": "Set Contact Attributes",     "block_type": "SetAttributes",          "count": 200, "pct": 100.0, "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 3,  "block_name": "Invoke Conversational Bot",  "block_type": "InvokeExternalResource", "count": 200, "pct": 100.0, "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 4,  "block_name": "Check Bot Intent Result",    "block_type": "CheckAttribute",         "count": 198, "pct": 99.0,  "drop_count": 2,  "drop_pct": 1.0},
        {"sequence": 5,  "block_name": "Invoke Lambda — Fetch Data", "block_type": "InvokeLambdaFunction",   "count": 148, "pct": 74.0,  "drop_count": 50, "drop_pct": 25.3},
        {"sequence": 6,  "block_name": "Set Response Attributes",    "block_type": "SetAttributes",          "count": 145, "pct": 72.5,  "drop_count": 3,  "drop_pct": 2.0},
        {"sequence": 7,  "block_name": "Read Bot Response",          "block_type": "MessageParticipant",     "count": 145, "pct": 72.5,  "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 8,  "block_name": "Anything Else? (Follow-up)", "block_type": "GetUserInput",           "count": 140, "pct": 70.0,  "drop_count": 5,  "drop_pct": 3.4},
        # ── Escalation path (subset of contacts request agent) ─────────────────────
        {"sequence": 9,  "block_name": "Check Business Hours",       "block_type": "CheckHoursOfOperation",  "count": 82,  "pct": 41.0,  "drop_count": 58, "drop_pct": 41.4},
        {"sequence": 10, "block_name": "After-hours Message",        "block_type": "MessageParticipant",     "count": 12,  "pct": 6.0,   "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 11, "block_name": "Check Agent Availability",   "block_type": "CheckStaffingLevel",     "count": 70,  "pct": 35.0,  "drop_count": 12, "drop_pct": 14.6},
        {"sequence": 12, "block_name": "Set Agent Queue",            "block_type": "SetQueue",               "count": 68,  "pct": 34.0,  "drop_count": 2,  "drop_pct": 2.9},
        {"sequence": 13, "block_name": "Play Queue Hold Music",      "block_type": "MessageParticipant",     "count": 68,  "pct": 34.0,  "drop_count": 0,  "drop_pct": 0.0},
        {"sequence": 14, "block_name": "Transfer to Agent Queue",    "block_type": "TransferToQueue",        "count": 65,  "pct": 32.5,  "drop_count": 3,  "drop_pct": 4.4},
        # ── Terminal ───────────────────────────────────────────────────────────────
        {"sequence": 15, "block_name": "End Call",                   "block_type": "DisconnectParticipant",  "count": 193, "pct": 96.5,  "drop_count": 0,  "drop_pct": 0.0},
    ],
}

# Map flow name keywords → base template
def _get_funnel_template(flow_name: str) -> dict:
    # Word-boundary match — a raw substring check would false-positive on
    # e.g. "ai" inside "MainInboundFlow" and wrongly pick the bot template.
    fl_tokens = re.findall(r"[a-z]+", flow_name.lower())
    if any(k in fl_tokens for k in ("bot", "conversational", "lex", "ai", "chat")):
        return _MOCK_FLOW_FUNNEL_BOT
    return _MOCK_FLOW_FUNNEL


def _allocate_ints(total: int, weights: list, total_w: float) -> list:
    """Distribute `total` items across slots proportionally, ensuring sum == total."""
    if total <= 0:
        return [0] * len(weights)
    fractional = [total * w / total_w for w in weights]
    floored = [int(f) for f in fractional]
    remainder = total - sum(floored)
    # Give the remaining units to the slots with the largest fractional parts
    order = sorted(range(len(weights)), key=lambda i: fractional[i] - floored[i], reverse=True)
    for j in range(int(remainder)):
        floored[order[j]] += 1
    return floored


def _synthetic_daily_trend(intent_metrics: list, days: int) -> list:
    """Distribute period-aggregate intent counts across days using weekday weighting."""
    import math as _math
    total_s = sum(i.get("successful", 0) for i in intent_metrics)
    total_d = sum(i.get("dropped",    0) for i in intent_metrics)
    total_f = sum(i.get("failed",     0) for i in intent_metrics)
    if days == 0 or (total_s + total_d + total_f) == 0:
        return []
    now = datetime.now(timezone.utc)
    weights, dates = [], []
    for offset in range(days, 0, -1):
        day = now - timedelta(days=offset)
        dow = day.weekday()  # 0=Mon … 6=Sun
        w = 1.0 if dow < 5 else 0.3
        w *= 0.75 + 0.5 * abs(_math.sin(offset * 1.3))
        weights.append(max(w, 0.05))
        dates.append(day)
    total_w = sum(weights) or 1.0
    s_vals = _allocate_ints(total_s, weights, total_w)
    d_vals = _allocate_ints(total_d, weights, total_w)
    f_vals = _allocate_ints(total_f, weights, total_w)
    return [
        {
            "date":       day.strftime("%Y-%m-%d"),
            "label":      f"{day.day} {day.strftime('%b')}",
            "Successful": s_vals[i],
            "Dropped":    d_vals[i],
            "Failed":     f_vals[i],
            "Total":      s_vals[i] + d_vals[i] + f_vals[i],
        }
        for i, day in enumerate(dates)
    ]


@app.get("/bot-intent-trend")
def bot_intent_trend_endpoint(days: int = Query(default=7, ge=1, le=90)) -> Dict[str, Any]:
    """Return per-day intent outcome trend for the primary bot."""
    if _is_mock():
        intent_metrics = (_MOCK_BOT_METRICS.get("lex_analytics") or [{}])[0].get("intent_metrics", [])
        return {"mock": True, "days": days, "synthesized": True,
                "trend": _synthetic_daily_trend(intent_metrics, days)}
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
            {"name": "max_samples", "type": "string", "value": "20"},
        ])
        if data.get("intent_daily_trend"):
            return {"mock": False, "days": days, "synthesized": False,
                    "trend": data["intent_daily_trend"]}
        # Synthesise from period aggregates
        intent_metrics = (data.get("lex_analytics") or [{}])[0].get("intent_metrics", [])
        return {"mock": False, "days": days, "synthesized": True,
                "trend": _synthetic_daily_trend(intent_metrics, days)}
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.error("bot-intent-trend error: %s", exc, exc_info=True)
        return {"mock": False, "days": days, "trend": [], "error": str(exc)}


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


@app.get("/contact-flow-events")
def contact_flow_events(
    request: Request,
    contact_id: str = Query(..., description="Amazon Connect Contact ID"),
) -> Dict[str, Any]:
    """Return the ordered sequence of contact flow block events for a specific contact."""
    _assert_valid_contact_id(contact_id)
    if _is_mock():
        events = _MOCK_FLOW_EVENTS.copy()
        events["contact_id"] = contact_id
        events["mock"] = True
        return events
    try:
        data = _invoke_tool(
            "contact_flow_events",
            [
                {"name": "query_type",  "type": "string", "value": "contact_events"},
                {"name": "contact_id",  "type": "string", "value": contact_id},
            ],
        )
        return {"mock": False, **data}
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Real flow events unavailable, returning mock: %s", exc)
        # Fallback to mock only when AWS is unreachable (local dev without credentials)
        events = _MOCK_FLOW_EVENTS.copy()
        events["contact_id"] = contact_id
        events["mock"] = True
        events["fallback_reason"] = str(exc)
        return events


@app.get("/contact-funnel")
def contact_funnel(
    request: Request,
    flow_name: str = Query(default="", description="Contact flow name to aggregate"),
    days: int = Query(default=30, ge=1, le=90, description="Number of days to aggregate"),
) -> Dict[str, Any]:
    """Return aggregate funnel / block-traversal counts for a flow over the given period.

    Queries CloudWatch Logs Insights for real data. Falls back to scaled mock data
    only when AWS credentials are not available (local Docker without env vars).
    """
    if not flow_name.strip():
        return {"mock": False, "total_contacts": 0, "blocks": [],
                "warning": "No flow_name specified"}
    if _is_mock():
        return _scale_funnel_mock(days, flow_name)
    try:
        data = _invoke_tool(
            "contact_flow_events",
            [
                {"name": "query_type", "type": "string", "value": "flow_funnel"},
                {"name": "flow_name",  "type": "string", "value": flow_name},
                {"name": "days",       "type": "string", "value": str(days)},
            ],
        )
        return {"mock": False, **data}
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Real funnel unavailable, returning scaled mock: %s", exc)
        return _scale_funnel_mock(days, flow_name, reason=str(exc))


@app.get("/contact-flows")
def list_contact_flows() -> Dict[str, Any]:
    """Return all contact flows from the Connect instance with their log group status.

    This is used by the frontend to populate the flow selector with real flow names.
    Falls back to reading log groups only when the Connect API is unavailable.
    """
    if _is_mock():
        # Names deliberately match _MOCK_FLOW_FUNNEL / _MOCK_FLOW_FUNNEL_BOT so
        # selecting either one in the funnel picker returns a rich template.
        flows = [
            {"id": "mock-flow-1", "arn": None, "name": "MainInboundFlow",
             "type": "CONTACT_FLOW", "state": "ACTIVE", "logging_enabled": True},
            {"id": "mock-flow-2", "arn": None, "name": "conversationalbot",
             "type": "CONTACT_FLOW", "state": "ACTIVE", "logging_enabled": True},
        ]
        return {"mock": True, "flows": flows, "total": len(flows), "logging_enabled_count": len(flows)}
    try:
        import boto3  # pylint: disable=import-outside-toplevel
        instance_id = os.environ.get("CONNECT_INSTANCE_ID", "")
        connect = boto3.client("connect", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
        logs    = boto3.client("logs",    region_name=os.environ.get("AWS_REGION", "eu-west-2"))

        # 1. List all contact flows from Connect (CONTACT_FLOW type only — not modules/queues)
        flows = []
        paginator = connect.get_paginator("list_contact_flows")
        for page in paginator.paginate(InstanceId=instance_id,
                                       ContactFlowTypes=["CONTACT_FLOW"]):
            for f in page.get("ContactFlowSummaryList", []):
                flows.append({
                    "id":    f["Id"],
                    "arn":   f["Arn"],
                    "name":  f["Name"],
                    "type":  f.get("ContactFlowType", "CONTACT_FLOW"),
                    "state": f.get("ContactFlowState", "ACTIVE"),
                })

        # 2. Discover CloudWatch log groups under /aws/connect/
        log_groups = set()
        try:
            cw_paginator = logs.get_paginator("describe_log_groups")
            for page in cw_paginator.paginate(logGroupNamePrefix="/aws/connect/"):
                for lg in page.get("logGroups", []):
                    log_groups.add(lg["logGroupName"].lower())
        except Exception:  # pylint: disable=broad-except
            LOGGER.debug('Suppressed exception', exc_info=True)

        # 3. Annotate each flow with whether logging is enabled.
        # Matching strategy: normalise both sides; also try token overlap because
        # the log group name (set by user) may abbreviate or join words from the
        # flow display name (e.g. flow="conversation bot flow" → lg="conversationalbot").
        for f in flows:
            fn_raw  = f["name"].lower()
            fn_norm = fn_raw.replace(" ", "").replace("-", "").replace("_", "")
            # Significant tokens (length > 3) from the flow name
            fn_tokens = [t for t in fn_raw.replace("-", " ").replace("_", " ").split() if len(t) > 3]

            def _matches_log_group(lg: str) -> bool:
                lg_norm = lg.replace("/aws/connect/", "").replace("-", "").replace("_", "")
                # Exact normalised match in either direction
                if fn_norm in lg_norm or lg_norm in fn_norm:
                    return True
                # Token overlap: any significant word from the flow name is a
                # substring of the log group suffix (handles "conversation bot flow" → "conversationalbot")
                return any(tok in lg_norm for tok in fn_tokens)

            f["logging_enabled"] = any(_matches_log_group(lg) for lg in log_groups)

        # Sort: logging-enabled first, then alphabetically
        flows.sort(key=lambda x: (not x["logging_enabled"], x["name"].lower()))

        return {
            "flows": flows,
            "total": len(flows),
            "logging_enabled_count": sum(1 for f in flows if f["logging_enabled"]),
        }

    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("Could not list contact flows from Connect: %s", exc)
        # Fall back to reading log groups only
        try:
            import boto3  # pylint: disable=import-outside-toplevel
            logs = boto3.client("logs", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
            log_group_flows = []
            paginator = logs.get_paginator("describe_log_groups")
            for page in paginator.paginate(logGroupNamePrefix="/aws/connect/"):
                for lg in page.get("logGroups", []):
                    name = lg["logGroupName"].replace("/aws/connect/", "")
                    log_group_flows.append({
                        "id": None, "arn": None,
                        "name": name, "type": "CONTACT_FLOW", "state": "ACTIVE",
                        "logging_enabled": True,
                    })
            return {"flows": log_group_flows, "total": len(log_group_flows),
                    "logging_enabled_count": len(log_group_flows),
                    "source": "log_groups_only"}
        except Exception as exc2:  # pylint: disable=broad-except
            return {"flows": [], "total": 0, "logging_enabled_count": 0,
                    "error": str(exc2)}



def _scale_funnel_mock(days: int, flow_name: str, reason: str = "") -> Dict[str, Any]:
    """Scale mock funnel counts proportionally to the requested period (fallback only)."""
    import random as _random
    _random.seed(days + hash(flow_name) % 997)
    base_template = _get_funnel_template(flow_name)
    base_days     = 30
    base_total    = base_template["total_contacts"]
    scale = (days / base_days) * (0.85 + _random.random() * 0.30)
    new_total = max(1, round(base_total * scale))

    new_blocks = []
    for b in base_template["blocks"]:
        new_count = max(0, min(new_total, round(b["count"] * scale * (0.9 + _random.random() * 0.20))))
        new_blocks.append({**b, "count": new_count, "pct": round(new_count / new_total * 100, 1) if new_total else 0})

    for i in range(len(new_blocks) - 1):
        diff = new_blocks[i]["count"] - new_blocks[i + 1]["count"]
        new_blocks[i]["drop_count"] = max(0, diff)
        new_blocks[i]["drop_pct"] = round(diff / new_blocks[i]["count"] * 100, 1) if new_blocks[i]["count"] else 0.0
    new_blocks[-1]["drop_count"] = 0
    new_blocks[-1]["drop_pct"]   = 0.0

    result = {
        "flow_name": flow_name, "mock": True,
        "total_contacts": new_total, "period_days": days,
        "blocks": new_blocks,
    }
    if reason:
        result["fallback_reason"] = reason
    return result


def _parse_csv_query(value: Optional[str], uppercase: bool = False) -> List[str]:
    if not value:
        return []
    items = [item.strip() for item in value.split(",") if item.strip()]
    return [item.upper() for item in items] if uppercase else items



def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)



def _parse_searchable_attributes_query(value: Optional[str]) -> List[Dict[str, Any]]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []

    criteria: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        raw_values = item.get("values")
        if isinstance(raw_values, list):
            values = [str(v).strip() for v in raw_values if str(v).strip()]
        else:
            candidate = str(item.get("value", raw_values or "")).strip()
            values = [candidate] if candidate else []
        if key and values:
            criteria.append({"key": key, "values": values})
    return criteria



def _matches_mock_attributes(contact: Dict[str, Any], criteria: List[Dict[str, Any]]) -> bool:
    if not criteria:
        return True

    searchable = {str(key).lower(): str(value or "") for key, value in (contact.get("customAttributes") or {}).items()}
    searchable["customerendpoint"] = str(contact.get("phoneNumber") or "")

    for criterion in criteria:
        haystack = searchable.get(criterion["key"].lower(), "")
        if not haystack:
            return False
        if not any(value.lower() in haystack.lower() for value in criterion["values"]):
            return False
    return True



@app.get("/queues")
def list_queues() -> Dict[str, Any]:
    """Return all standard queues for populating the queue dropdown."""
    if _is_mock():
        return {"queues": _MOCK_QUEUES}
    try:
        connect = _get_connect_client()
        instance_id = _get_instance_id()
        queues = []
        paginator = connect.get_paginator("list_queues")
        for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD"]):
            for queue in page.get("QueueSummaryList", []):
                queues.append({"id": queue["Id"], "name": queue.get("Name", queue["Id"])})
        queues.sort(key=lambda queue: queue["name"].lower())
        return {"queues": queues}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to list queues") from exc



@app.get("/agents-list")
def list_agents_for_search() -> Dict[str, Any]:
    """Return all agents for the agent dropdown in Contact Search."""
    if _is_mock():
        return {"agents": _MOCK_AGENTS}
    try:
        connect = _get_connect_client()
        instance_id = _get_instance_id()
        agents = []
        paginator = connect.get_paginator("list_users")
        for page in paginator.paginate(InstanceId=instance_id):
            for user_summary in page.get("UserSummaryList", []):
                try:
                    user = connect.describe_user(InstanceId=instance_id, UserId=user_summary["Id"]).get("User", {})
                    identity = user.get("IdentityInfo", {})
                    name = " ".join(part for part in [identity.get("FirstName"), identity.get("LastName")] if part) or user.get("Username", user_summary["Id"])
                    agents.append({"id": user_summary["Id"], "name": name})
                except Exception:
                    agents.append({"id": user_summary["Id"], "name": user_summary.get("Username", user_summary["Id"])})
        agents.sort(key=lambda agent: agent["name"].lower())
        return {"agents": agents}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to list agents") from exc



@app.get("/contacts")
def contacts(
    request: Request,
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    contact_status: Optional[str] = Query(default=None),
    contact_id: Optional[str] = Query(default=None),
    channels: Optional[str] = Query(default=None),
    initiation_methods: Optional[str] = Query(default=None),
    time_range_type: Optional[str] = Query(default=None),
    queue_ids: Optional[str] = Query(default=None),
    agent_ids: Optional[str] = Query(default=None),
    phone_number: Optional[str] = Query(default=None),
    searchable_attributes: Optional[str] = Query(default=None),
    sort_field: Optional[str] = Query(default=None),
    sort_order: Optional[str] = Query(default=None),
    min_duration_seconds: Optional[int] = Query(default=None, ge=0, le=86400),
    max_duration_seconds: Optional[int] = Query(default=None, ge=0, le=86400),
    max_results: int = Query(default=25, ge=1, le=100),
) -> Dict[str, Any]:
    if contact_status and contact_status.upper() not in _VALID_CONTACT_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid contact_status. Allowed: {sorted(_VALID_CONTACT_STATUSES)}")
    if contact_status:
        contact_status = contact_status.upper()
    if contact_id:
        _assert_valid_contact_id(contact_id)

    if _is_mock():
        contacts_list = list(_MOCK_CONTACTS)
        start_dt = _parse_iso_datetime(start)
        end_dt = _parse_iso_datetime(end)
        channel_filters = set(_parse_csv_query(channels, uppercase=True))
        initiation_filters = set(_parse_csv_query(initiation_methods, uppercase=True))
        queue_filters = set(_parse_csv_query(queue_ids))
        agent_filters = set(_parse_csv_query(agent_ids))
        attribute_filters = _parse_searchable_attributes_query(searchable_attributes)

        if start_dt:
            contacts_list = [contact for contact in contacts_list if _parse_iso_datetime(contact.get("dateTime")) and _parse_iso_datetime(contact.get("dateTime")) >= start_dt]
        if end_dt:
            contacts_list = [contact for contact in contacts_list if _parse_iso_datetime(contact.get("dateTime")) and _parse_iso_datetime(contact.get("dateTime")) <= end_dt]
        if contact_status:
            contacts_list = [contact for contact in contacts_list if (contact.get("status") or "").upper() == contact_status]
        if contact_id:
            contacts_list = [contact for contact in contacts_list if contact.get("contactId") == contact_id]
        if channel_filters:
            contacts_list = [contact for contact in contacts_list if (contact.get("channel") or "").upper() in channel_filters]
        if initiation_filters:
            contacts_list = [contact for contact in contacts_list if (contact.get("initiationMethod") or "").upper() in initiation_filters]
        if queue_filters:
            contacts_list = [contact for contact in contacts_list if contact.get("queueId") in queue_filters]
        if agent_filters:
            contacts_list = [contact for contact in contacts_list if contact.get("agentId") in agent_filters]
        if phone_number:
            phone_filter = phone_number.strip().lower()
            contacts_list = [contact for contact in contacts_list if phone_filter in str(contact.get("phoneNumber") or "").lower()]
        if min_duration_seconds is not None:
            contacts_list = [contact for contact in contacts_list if int(contact.get("duration") or 0) >= min_duration_seconds]
        if max_duration_seconds is not None:
            contacts_list = [contact for contact in contacts_list if int(contact.get("duration") or 0) <= max_duration_seconds]
        if attribute_filters:
            contacts_list = [contact for contact in contacts_list if _matches_mock_attributes(contact, attribute_filters)]

        reverse = (sort_order or "DESCENDING").upper() != "ASCENDING"
        contacts_list.sort(key=lambda contact: contact.get("dateTime") or "", reverse=reverse)
        total_count = len(contacts_list)
        return {"mock": True, "contacts": contacts_list[:max_results], "total_count": total_count}

    now = datetime.now(timezone.utc)
    extra_params: List[Dict[str, Any]] = [
        {"name": "start_time", "type": "string", "value": start or (now - timedelta(hours=8)).isoformat()},
        {"name": "end_time", "type": "string", "value": end or now.isoformat()},
        {"name": "max_results", "type": "string", "value": str(max_results)},
    ]

    forwarded_params = {
        "contact_status": contact_status,
        "contact_id": contact_id,
        "channels": channels,
        "initiation_methods": initiation_methods,
        "time_range_type": time_range_type,
        "queue_ids": queue_ids,
        "agent_ids": agent_ids,
        "phone_number": phone_number,
        "searchable_attributes": searchable_attributes,
        "sort_field": sort_field,
        "sort_order": sort_order,
    }
    for name, value in forwarded_params.items():
        if value not in (None, ""):
            extra_params.append({"name": name, "type": "string", "value": str(value)})
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
                "agentId": c.get("agent_id", ""),
                "queue": c.get("queue_name") or c.get("queue_id") or "—",
                "queueId": c.get("queue_id", ""),
                "duration": int(c.get("duration_seconds") or 0),
                "status": c.get("contact_status", "UNKNOWN"),
                "channel": c.get("channel"),
                "initiationMethod": c.get("initiation_method", ""),
                "phoneNumber": c.get("customer_endpoint", ""),
                "customAttributes": c.get("custom_attributes", {}),
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


# The realtime queue list is the fleet simulation's queue list — keeping the
# old name so the occupancy mocks below stay untouched.
_MOCK_LIVE_QUEUES = _MOCK_RT_QUEUES


def _mock_realtime_queue_metrics() -> Dict[str, Any]:
    """Per-queue snapshot aggregated from the shared fleet simulation, so the
    5s-polling live-queue chart moves in step with the contact/agent tables."""
    now = datetime.now(timezone.utc)
    state = _mock_fleet_state(now)
    agents = _mock_agent_states_now()
    ts = now.replace(tzinfo=None).isoformat()

    by_queue: Dict[str, Dict[str, Any]] = {
        q["name"]: {"id": q["id"], "name": q["name"], "contacts_in_queue": 0,
                    "agents_available": 0, "agents_on_call": 0, "agents_online": 0,
                    "oldest_contact_age": 0, "contacts_scheduled": 0}
        for q in _MOCK_RT_QUEUES
    }
    for c in state["contacts"]:
        row = by_queue.get(c["queueName"])
        if row is None:
            continue
        if c["contactState"] == "QUEUED":
            if c.get("callbackScheduled"):
                row["contacts_scheduled"] += 1
            else:
                row["contacts_in_queue"] += 1
                row["oldest_contact_age"] = max(row["oldest_contact_age"], c["_age"])
    for a in agents:
        row = by_queue.get(a["currentQueue"])
        if row is None:
            continue
        row["agents_online"] += 1
        if a["status"] == "On Call":
            row["agents_on_call"] += 1
        elif a["status"] == "Available":
            row["agents_available"] += 1
    return {"mock": True, "timestamp": ts, "queues": list(by_queue.values())}


@app.get("/realtime-queue-metrics")
def realtime_queue_metrics() -> Dict[str, Any]:
    """
    Current metric snapshot for all standard queues:
    contacts_in_queue, agents_available, agents_on_call, oldest_contact_age.
    Polled every 5 s by the frontend live-queue chart.
    """
    if _is_mock():
        return _mock_realtime_queue_metrics()

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


# ── Agent occupancy (time-averaged utilisation, NOT a live snapshot) ───────────
# Deliberately separate from realtime_queue_metrics above: that endpoint is an
# instantaneous snapshot polled every 5s for the live chart, which is far too
# noisy to use as "utilisation" (a single agent finishing a call flips the
# number by tens of percent). These two endpoints instead return a real,
# time-averaged AGENT_OCCUPANCY from Connect's historical metrics — a rolling
# window the caller chooses (5-120 min) and a day-to-date average bounded by
# each queue's actual configured Hours of Operation.

def _invoke_occupancy(start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    # AGENT_OCCUPANCY only accepts ROUTING_PROFILE / AGENT filters and groupings
    # (GetMetricDataV2 returns "Invalid filter" for QUEUE) — fetch per routing
    # profile and map back onto queues via _routing_profile_queue_map below.
    return _invoke_tool("get_historical_metrics", [
        {"name": "start_time", "type": "string", "value": start_iso},
        {"name": "end_time",   "type": "string", "value": end_iso},
        {"name": "group_by",   "type": "string", "value": "ROUTING_PROFILE"},
        {"name": "interval",   "type": "string", "value": "TOTAL"},
        {"name": "metrics",    "type": "string", "value": "AGENT_OCCUPANCY"},
    ]).get("results", [])


_RP_QUEUE_MAP_CACHE: Dict[str, Tuple[float, Dict[str, Dict[str, Any]]]] = {}


def _routing_profile_queue_map(connect, instance_id: str) -> Dict[str, Dict[str, Any]]:
    """{queue_id: {"name": queue_name, "profiles": {rp_id, ...}}} — cached 5 min."""
    cached = _RP_QUEUE_MAP_CACHE.get(instance_id)
    if cached and time.time() - cached[0] < 300:
        return cached[1]
    mapping: Dict[str, Dict[str, Any]] = {}
    for page in connect.get_paginator("list_routing_profiles").paginate(InstanceId=instance_id):
        for rp in page.get("RoutingProfileSummaryList", []):
            rp_id = rp.get("Id")
            if not rp_id:
                continue
            for qpage in connect.get_paginator("list_routing_profile_queues").paginate(
                InstanceId=instance_id, RoutingProfileId=rp_id
            ):
                for q in qpage.get("RoutingProfileQueueConfigSummaryList", []):
                    qid = q.get("QueueId")
                    if not qid:
                        continue
                    entry = mapping.setdefault(qid, {"name": q.get("QueueName") or qid, "profiles": set()})
                    entry["profiles"].add(rp_id)
    _RP_QUEUE_MAP_CACHE[instance_id] = (time.time(), mapping)
    return mapping


def _mean_profile_occupancy(profile_ids, occ_by_profile: Dict[str, Optional[float]]) -> Optional[float]:
    values = [occ_by_profile[rp] for rp in profile_ids if occ_by_profile.get(rp) is not None]
    return sum(values) / len(values) if values else None


def _mock_agent_occupancy(window_minutes: int) -> Dict[str, Any]:
    import random
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=window_minutes)
    queues = [
        {"queue_id": q["id"], "queue_name": q["name"], "occupancy_pct": round(random.uniform(35, 85), 1)}
        for q in _MOCK_LIVE_QUEUES
    ]
    return {"mock": True, "window_minutes": window_minutes, "start": start.isoformat(), "end": now.isoformat(), "queues": queues}


@app.get("/agent-occupancy")
def agent_occupancy(window_minutes: int = Query(default=30, ge=5, le=120)) -> Dict[str, Any]:
    """
    Real, time-averaged AGENT_OCCUPANCY per queue over the trailing
    `window_minutes` (5-120). Intended to be polled once per `window_minutes`
    by the frontend — not every few seconds — since the whole point is a
    stable average rather than a jittery instantaneous read.
    """
    if _is_mock():
        return _mock_agent_occupancy(window_minutes)

    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        return {"mock": False, "window_minutes": window_minutes, "queues": []}

    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=window_minutes)
        occ_by_profile = {
            row.get("dimension_value"): row.get("metrics", {}).get("AGENT_OCCUPANCY")
            for row in _invoke_occupancy(start.isoformat(), now.isoformat())
        }
        import boto3
        connect = boto3.client("connect", region_name=os.getenv("AWS_REGION", "eu-west-2"))
        # Per-queue value = mean occupancy of the routing profiles serving that
        # queue (the agent pool), since AWS has no per-queue occupancy at all.
        queues = []
        rp_queue_map = _routing_profile_queue_map(connect, instance_id)
        for qid, info in sorted(rp_queue_map.items(), key=lambda kv: kv[1]["name"]):
            occ = _mean_profile_occupancy(info["profiles"], occ_by_profile)
            queues.append({
                "queue_id": qid,
                "queue_name": info["name"],
                "occupancy_pct": round(occ, 1) if occ is not None else None,
            })
        return {
            "mock": False, "window_minutes": window_minutes,
            "start": start.isoformat(), "end": now.isoformat(),
            "queues": queues,
        }
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("agent_occupancy failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch agent occupancy") from exc


def _mock_agent_occupancy_day_to_date() -> Dict[str, Any]:
    import random
    now = datetime.now(timezone.utc)
    open_today = now.replace(hour=9, minute=0, second=0, microsecond=0)
    close_today = now.replace(hour=18, minute=0, second=0, microsecond=0)
    if now < open_today:
        status = "not_yet_open"
    elif now < close_today:
        status = "open"
    else:
        status = "closed_for_day"
    queues = []
    for q in _MOCK_LIVE_QUEUES:
        queues.append({
            "queue_id": q["id"], "queue_name": q["name"], "status": status,
            "open": open_today.isoformat(), "close": close_today.isoformat(),
            "occupancy_pct": round(random.uniform(40, 75), 1) if status != "not_yet_open" else None,
        })
    return {"mock": True, "as_of": now.isoformat(), "queues": queues}


@app.get("/agent-occupancy/day-to-date")
def agent_occupancy_day_to_date() -> Dict[str, Any]:
    """
    Per-queue average AGENT_OCCUPANCY from that queue's real Hours-of-Operation
    open time through now (or through close, once the day has ended) — each
    queue can have different hours, so this is resolved per queue and queues
    sharing an identical window are batched into one historical-metrics call.
    """
    if _is_mock():
        return _mock_agent_occupancy_day_to_date()

    instance_id = os.getenv("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        return {"mock": False, "queues": []}

    import boto3
    connect = boto3.client("connect", region_name=os.getenv("AWS_REGION", "eu-west-2"))
    now = datetime.now(timezone.utc)

    try:
        queues_list: List[Dict[str, Any]] = []
        paginator = connect.get_paginator("list_queues")
        for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD"]):
            queues_list.extend(page.get("QueueSummaryList", []))
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("agent_occupancy_day_to_date: list_queues failed: %s", exc)
        return {"mock": False, "queues": [], "error": str(exc)}

    queue_windows: Dict[str, Dict[str, Any]] = {}
    for q in queues_list:
        qid, qname = q["Id"], q["Name"]
        window = hours_of_operation.get_today_window(connect, instance_id, qid)
        if not window:
            queue_windows[qid] = {"name": qname, "status": "closed_today"}
            continue
        open_utc, close_utc = window
        if now < open_utc:
            queue_windows[qid] = {"name": qname, "status": "not_yet_open", "open": open_utc.isoformat(), "close": close_utc.isoformat()}
            continue
        end = min(now, close_utc)
        status = "open" if now < close_utc else "closed_for_day"
        queue_windows[qid] = {
            "name": qname, "status": status,
            "open": open_utc.isoformat(), "close": close_utc.isoformat(),
            "_range": (open_utc.isoformat(), end.isoformat()),
        }

    # Batch queues sharing an identical (start, end) window into one call each
    groups: Dict[Tuple[str, str], List[str]] = {}
    for qid, info in queue_windows.items():
        rng = info.get("_range")
        if rng:
            groups.setdefault(rng, []).append(qid)

    rp_queue_map = _routing_profile_queue_map(connect, instance_id)
    occupancy_by_queue: Dict[str, Optional[float]] = {}
    for (start_iso, end_iso), qids in groups.items():
        try:
            rows = _invoke_occupancy(start_iso, end_iso)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("agent_occupancy_day_to_date: occupancy call failed for %s-%s: %s", start_iso, end_iso, exc)
            continue
        occ_by_profile = {
            row.get("dimension_value"): row.get("metrics", {}).get("AGENT_OCCUPANCY")
            for row in rows
        }
        for qid in qids:
            profiles = rp_queue_map.get(qid, {}).get("profiles", ())
            occ = _mean_profile_occupancy(profiles, occ_by_profile)
            if occ is not None:
                occupancy_by_queue[qid] = occ

    queues_out = []
    for qid, info in queue_windows.items():
        occ = occupancy_by_queue.get(qid)
        queues_out.append({
            "queue_id": qid,
            "queue_name": info["name"],
            "status": info["status"],
            "open": info.get("open"),
            "close": info.get("close"),
            "occupancy_pct": round(occ, 1) if occ is not None else None,
        })

    return {"mock": False, "as_of": now.isoformat(), "queues": queues_out}


@app.delete("/sessions", status_code=200)
def delete_all_sessions() -> Dict[str, Any]:
    try:
        create_session_store().delete_all()
        return {"ok": True}
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Failed to delete all sessions")
        raise HTTPException(status_code=500, detail="Failed to delete all sessions")
