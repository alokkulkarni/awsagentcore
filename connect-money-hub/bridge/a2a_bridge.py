"""
a2a_bridge.py
=============
The front door Connect uses to bring the Money Hub agent into a call or chat
(SPEC section 5). A Lambda behind a Function URL.

Why a bridge: Connect authenticates an external agent with a fixed API key sent
as "Authorization: Bearer"; AgentCore Runtime accepts only IAM signatures or
short-lived OAuth tokens. The bridge checks Connect's key, speaks Connect's A2A
extensions (protocol.py), keeps the conversation, and calls the Strands agent on
AgentCore Runtime with IAM.

Per SendMessage event:
    INIT_SESSION      who the customer is (from Connect's record of the contact,
                      never from the conversation), channel, history -> session
    CHANNEL_STATE     acknowledged
    a customer turn   the agent runs; reply + trace + completed status (FINISH
                      when it hands back to ARIA)
    <EMPTY_USER_INPUT> a gentle re-prompt, without calling the agent
    INTERRUPTION, DTMF_INPUT_COMPLETE, ERROR   acknowledged
GetTask returns a stored task (poll mode).

ENVIRONMENT VARIABLES
    MONEY_HUB_TABLE        DynamoDB table (sessions share it with the Money Hub)
    AGENT_RUNTIME_ARN      the Money Hub agent on AgentCore Runtime
    API_KEY_SECRET_ID      Secrets Manager secret holding the key Connect presents
    CONNECT_INSTANCE_ID    to read the contact's attributes
    BRIDGE_MODE            sync (default): answer each turn in the response.
                           poll: answer "working" and let Connect call GetTask
    LOG_LEVEL              default INFO

LOGGING: event types, outcomes and timings only. Never the customer's words,
the agent's reply, the key, or any amount.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any

import protocol
from moneyhub.store import DynamoStore, MemoryStore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

SESSION_SECONDS = 2 * 60 * 60
MAX_BODY_BYTES = 512 * 1024
MAX_TURNS_KEPT = 40
SECRET_CACHE_SECONDS = 300

_TABLE = os.environ.get("MONEY_HUB_TABLE", "")
store = DynamoStore(_TABLE, time.time) if _TABLE else MemoryStore(time.time)
_secret_cache: dict[str, tuple[float, str]] = {}


# ── outside the Lambda (replaced in tests) ─────────────────────────────────────

def api_key() -> str:
    """The key Connect must present, read with this Lambda's role and kept five minutes. Never logged.
    A failed read is not kept, so the bridge recovers as soon as the permission works (for example a minute
    after deployment, when a new role's permissions have reached every AWS endpoint)."""
    secret_id = os.environ.get("API_KEY_SECRET_ID", "")
    if not secret_id:
        return ""
    kept = _secret_cache.get(secret_id)
    if kept and kept[0] > time.time():
        return kept[1]
    try:
        import boto3
        value = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id).get("SecretString", "").strip()
    except Exception:
        logger.exception("Could not read the API key secret. Check secretsmanager:GetSecretValue and kms:Decrypt.")
        return ""
    if value:
        _secret_cache[secret_id] = (time.time() + SECRET_CACHE_SECONDS, value)
    return value


def contact_attributes(contact_id: str) -> dict:
    instance_id = os.environ.get("CONNECT_INSTANCE_ID", "")
    if not (instance_id and contact_id):
        return {}
    try:
        import boto3
        return boto3.client("connect").get_contact_attributes(
            InstanceId=instance_id, InitialContactId=contact_id).get("Attributes", {})
    except Exception:
        logger.exception("Could not read the contact. Check connect:GetContactAttributes.")
        return {}


def invoke_agent(payload: dict, session_id: str) -> dict:
    """The Strands agent on AgentCore Runtime, called with this Lambda's IAM role."""
    import boto3
    from botocore.config import Config
    client = boto3.client("bedrock-agentcore", config=Config(read_timeout=50, retries={"max_attempts": 1}))
    response = client.invoke_agent_runtime(agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"], qualifier="DEFAULT",
                                           runtimeSessionId=session_id, payload=json.dumps(payload).encode())
    return json.loads(response["response"].read() or b"{}")


def invoke_self(event: dict) -> None:
    """Poll mode: do the turn's work in a second, asynchronous invocation of this Lambda."""
    import boto3
    boto3.client("lambda").invoke(FunctionName=os.environ["AWS_LAMBDA_FUNCTION_NAME"], InvocationType="Event",
                                  Payload=json.dumps(event).encode())


# ── who the customer is ─────────────────────────────────────────────────────────

def verified_customer(attributes: dict) -> str:
    """The contact's customer, only if a flow recorded them as verified (same gate as the dispute service)."""
    if attributes.get("authStatus") != "authenticated":
        return ""
    level = str(attributes.get("LoA") or attributes.get("loa") or "").strip()
    if level and not (level.isdigit() and int(level) >= 2):
        return ""
    return str(attributes.get("customerId") or "")


def _level(attributes: dict) -> str:
    level = str(attributes.get("LoA") or attributes.get("loa") or "").strip()
    return level if level.isdigit() else ""


def _page_view(attributes: dict) -> str:
    """Which Money Hub view the customer was on, when they started this contact from the page."""
    if attributes.get("entry") != "money_hub":
        return ""
    view = str(attributes.get("moneyHubView") or "")
    return view if view in ("out", "in", "expected", "transactions", "goals") else ""


def _channel(init: dict, attributes: dict) -> str:
    raw = str((init.get("contactContext") or {}).get("channel") or attributes.get("channel") or "")
    return "CHAT" if "chat" in raw.lower() else "VOICE"


# ── sessions ────────────────────────────────────────────────────────────────────

def _session_key(context_id: str) -> str:
    return f"sess#{hashlib.sha256(context_id.encode()).hexdigest()}"


def _runtime_session(context_id: str) -> str:
    """AgentCore wants 33+ characters; the same conversation always maps to the same session."""
    return hashlib.sha256(f"money-hub:{context_id}".encode()).hexdigest()


def _load(context_id: str) -> dict | None:
    return store.get(_session_key(context_id))


def _save(context_id: str, session: dict) -> None:
    session["transcript"] = session.get("transcript", [])[-MAX_TURNS_KEPT:]
    store.put(_session_key(context_id), {**session, "expiresAt": store.clock() + SESSION_SECONDS})


# ── events ──────────────────────────────────────────────────────────────────────

def on_init(request_id, context_id: str, message: dict) -> dict:
    init = protocol.data_part(message, "initSession")
    contact_id = protocol.contact_id_of(str(init.get("contactArn") or ""))
    attributes = contact_attributes(contact_id)
    existing = _load(context_id) or {}
    history = protocol.history_of(init)
    session = {
        "contactId": contact_id, "customerId": verified_customer(attributes),
        "loa": _level(attributes) if verified_customer(attributes) else "",
        "pageView": _page_view(attributes),
        "firstName": str(attributes.get("preferredName") or "")[:40], "channel": _channel(init, attributes),
        "finishTypes": [t for t in init.get("supportedFinishTypes") or ["COMPLETE", "ESCALATE"]
                        if t in ("COMPLETE", "ESCALATE")],
        "tracing": bool(init.get("subscribeToTracingEvents", True)),
        # Chat re-sends the whole history each time: it is the record. Voice keeps ours across a reconnect.
        "transcript": history if history else existing.get("transcript", []),
        # Voice over HTTPS starts a session for every turn: keep how recently we spoke and how many silences in a row.
        "lastReplyAt": existing.get("lastReplyAt", 0), "silences": existing.get("silences", 0),
        # A turn still being answered, and the last answer: a silence turn's session must not lose them.
        **({"inflight": existing["inflight"]} if existing.get("inflight") else {}),
        **({"lastAnswer": existing["lastAnswer"]} if existing.get("lastAnswer") else {}),
        "tasks": existing.get("tasks", {}),
    }
    _save(context_id, session)
    logger.info("event=INIT_SESSION verified=%s channel=%s history=%d", bool(session["customerId"]),
                session["channel"], len(history))
    return protocol.init_session_response(request_id, context_id)


# Silence. Connect sends it as <EMPTY_USER_INPUT>, and on calls also as an empty turn when the customer hasn't
# started speaking a few seconds after a reply finished playing, and whenever the bot block restarts (the flow's
# retry loop). Connect needs text on every turn: a turn without it errors the bot block and, three times over,
# ends the call. Connect speaks every reply it gets (its Q in Connect record can show fewer), so:
#   - if a real turn is still being answered, the silence waits for it (keeping the order) and then says next
#     to nothing (WAIT_REPLY, default "."), rather than the answer a second time;
#   - otherwise, on a call the first silence gets a short "Take your time." (SILENCE_REPLY), and a second in a
#     row the gentle re-prompt; chat re-prompts at once.
REPROMPT_AFTER = 2
REPROMPT = "Are you still there? Take your time; I'm here when you're ready."
INFLIGHT_WAIT_SECONDS = 20
sleep = time.sleep                     # replaced in tests


def _silence_reply(session: dict) -> str:
    session["silences"] = int(session.get("silences", 0)) + 1
    if session.get("channel") == "VOICE" and session["silences"] < REPROMPT_AFTER:
        return os.environ.get("SILENCE_REPLY") or "Take your time."
    session["silences"] = 0
    return REPROMPT


def _answer_in_flight(context_id: str) -> tuple[str, dict | None] | None:
    """(reply, finish) of a real turn still being answered for this conversation, once it's ready; else None."""
    current = _load(context_id) or {}
    pending = current.get("inflight")
    if not pending or store.clock() - float(pending.get("at") or 0) > INFLIGHT_WAIT_SECONDS:
        return None
    deadline = time.monotonic() + INFLIGHT_WAIT_SECONDS
    while True:
        done = current.get("lastAnswer") or {}
        if done.get("id") == pending.get("id"):
            return str(done.get("reply") or ""), done.get("finish")
        if not current.get("inflight") or time.monotonic() > deadline:
            return None
        sleep(0.25)
        current = _load(context_id) or {}


def with_unanswered(history: list[dict], text: str) -> tuple[list[dict], str]:
    """
    (history, input) with any customer words that never got a reply folded into the input.

    On a call Connect ends a customer's turn at the first pause, so one sentence can arrive as two turns a
    second or two apart. Connect keeps only the reply to the newest, so the first is never answered, and
    its history then ends with both pieces. Joined, the agent answers the whole sentence once.
    """
    kept, pending = list(history), []
    while kept and kept[-1].get("role") == "user":
        pending.insert(0, str(kept.pop().get("text") or "").strip())
    if pending and pending[-1] == text.strip():          # Connect's history already holds the current turn
        pending.pop()
    return kept, " ".join([p for p in pending if p] + [text.strip()]).strip()


def _run_turn(context_id: str, session: dict, text: str) -> tuple[str, dict | None, dict]:
    """The agent's reply, its FINISH (or None), and the turn record for the trace."""
    if not session.get("customerId"):
        reply = ("I can't open your Money Hub on this conversation yet. I'll hand you back so we can confirm "
                 "it's you first.")
        now = time.time_ns()
        return reply, {"type": "COMPLETE", "reason": "Money Hub: the customer is not verified (Level 2) on this "
                                                     "contact. Verify them, then hand back if they still want it."}, \
            {"input": text, "reply": reply, "startNs": now, "endNs": now, "tools": [], "model": "none"}
    if not text.strip() or text.strip() == protocol.EMPTY_INPUT:
        now = time.time_ns()
        if _answer_in_flight(context_id):
            reply, finish = os.environ.get("WAIT_REPLY") or ".", None     # the real turn carries the answer
            return reply, finish, {"input": protocol.EMPTY_INPUT, "reply": reply, "startNs": now,
                                   "endNs": time.time_ns(), "tools": [], "model": "none", "silence": True,
                                   "outcome": "waited"}
        reply = _silence_reply(session)
        return reply, None, {"input": protocol.EMPTY_INPUT, "reply": reply, "startNs": now, "endNs": now, "tools": [],
                             "model": "none", "silence": True,
                             "outcome": "reprompt" if reply == REPROMPT else "pause"}
    session["silences"] = 0
    started = time.time_ns()
    history, text = with_unanswered(session.get("transcript", []), text)
    # Visible to a silence turn that arrives while this one is being answered (see _answer_in_flight).
    inflight = {"id": secrets.token_hex(6), "at": store.clock()}
    _save(context_id, {**session, "inflight": inflight})
    answer = invoke_agent({"customerId": session["customerId"], "channel": session["channel"],
                           "firstName": session.get("firstName", ""), "history": history,
                           "loa": session.get("loa", ""), "pageView": session.get("pageView", ""),
                           "input": text}, _runtime_session(context_id))
    reply = str(answer.get("reply") or "Sorry, I didn't catch that. Could you say it another way?")
    finish = answer.get("finish") if isinstance(answer.get("finish"), dict) else None
    turn = {"input": text, "reply": reply, "model": answer.get("model", ""), "usage": answer.get("usage") or {},
            "tools": answer.get("tools") or [], "startNs": answer.get("startNs") or started,
            "endNs": answer.get("endNs") or time.time_ns()}
    session["lastAnswer"] = {"id": inflight["id"], "reply": reply, "finish": finish, "at": store.clock()}
    session.pop("inflight", None)
    _save(context_id, session)
    return reply, finish, turn


def _answer(request_id, context_id: str, task_id: str, session: dict, text: str, headers: dict) -> dict:
    try:
        reply, finish, turn = _run_turn(context_id, session, text)
    except Exception:
        logger.exception("event=TEXT outcome=agent_failed")
        return protocol.failed_task(request_id, context_id, task_id, 424, "The Money Hub agent is unavailable.",
                                    "DEPENDENCY_FAILURE")
    if finish and finish.get("type") not in session.get("finishTypes", []):
        finish = None
    if finish:
        finish = {"type": finish["type"], "reason": str(finish.get("reason") or "Money Hub conversation finished.")[:500]}
    if not turn.get("silence"):                 # silence isn't part of the conversation the agent sees
        session["transcript"] = session.get("transcript", []) + [{"role": "user", "text": text},
                                                                 {"role": "assistant", "text": reply}]
    if reply.strip():
        session["lastReplyAt"] = store.clock()
    trace = None
    if session.get("tracing", True):
        trace_id, parent = protocol.trace_context(headers)
        trace = protocol.build_trace(trace_id, parent, turn)
    logger.info("event=TEXT outcome=%s tools=%d finish=%s ms=%d", turn.get("outcome") or "ok",
                len(turn.get("tools") or []), finish["type"] if finish else "-",
                (turn["endNs"] - turn["startNs"]) // 1_000_000)
    return protocol.turn_task(request_id, context_id, task_id, reply, trace, finish)


def on_text(request_id, context_id: str, message: dict, headers: dict) -> dict:
    session = _load(context_id)
    if session is None:
        return protocol.rpc_error(request_id, -32602, "No session: INIT_SESSION must come first.", "SESSION_NOT_FOUND")
    text = (protocol.text_of(message) or "").strip()[:2000]
    task_id = f"task-{secrets.token_hex(8)}"
    if os.environ.get("BRIDGE_MODE", "sync") == "poll":
        session.setdefault("tasks", {})[task_id] = protocol.working_task(None, context_id, task_id)["result"]["task"]
        _save(context_id, session)
        invoke_self({"bridgeWork": {"contextId": context_id, "taskId": task_id, "text": text,
                                    "headers": {k: headers.get(k, "") for k in ("traceparent", "tracestate")}}})
        return protocol.working_task(request_id, context_id, task_id)
    reply = _answer(request_id, context_id, task_id, session, text, headers)
    _save(context_id, session)
    return reply


def do_poll_work(work: dict) -> None:
    """The asynchronous half of poll mode: run the turn, store the finished task for GetTask."""
    context_id, task_id = work["contextId"], work["taskId"]
    session = _load(context_id) or {}
    done = _answer(None, context_id, task_id, session, work.get("text", ""), work.get("headers") or {})
    session.setdefault("tasks", {})[task_id] = done["result"]["task"]
    _save(context_id, session)


def on_get_task(request_id, params: dict) -> dict:
    context_id, task_id = str(params.get("contextId") or ""), str(params.get("id") or params.get("taskId") or "")
    task = ((_load(context_id) or {}).get("tasks") or {}).get(task_id) if context_id else None
    if not task:
        return protocol.rpc_error(request_id, -32001, "Task not found.", "TASK_NOT_FOUND")
    return {"jsonrpc": "2.0", "id": request_id, "result": {"task": task}}


def dispatch(request: dict, headers: dict) -> dict:
    request_id = request.get("id")
    method = request.get("method")
    if method == "GetTask":
        return on_get_task(request_id, request.get("params") or {})
    if method != "SendMessage":
        return protocol.rpc_error(request_id, -32601, f"Unknown method: {method}", "METHOD_NOT_FOUND")
    message = protocol.message_of(request)
    context_id = str(message.get("contextId") or "")
    if not context_id:
        return protocol.rpc_error(request_id, -32602, "contextId is required.", "INVALID_PARAMS")
    kind = protocol.event_type(message)
    if kind == "INIT_SESSION":
        return on_init(request_id, context_id, message)
    if kind == "TEXT":
        return on_text(request_id, context_id, message, headers)
    if kind in ("CHANNEL_STATE", "INTERRUPTION", "DTMF_INPUT_COMPLETE", "ERROR"):
        logger.info("event=%s outcome=acknowledged", kind)
        return protocol.acknowledge(request_id, context_id, kind)
    return protocol.rpc_error(request_id, -32602, "Unsupported event.", "UNSUPPORTED_EVENT")


# ── HTTP (Lambda Function URL) ──────────────────────────────────────────────────

AGENT_CARD = {
    "name": protocol.AGENT_NAME, "version": "1.0.0", "protocolVersion": "1.0",
    "description": "Money Hub: explains a customer's spending, income, regular payments, expected months ahead "
                   "and savings goals. Information and guidance only, never financial advice.",
    "capabilities": {"streaming": False, "extensions": [{"uri": protocol.EXT, "required": True}]},
    "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "money-hub", "name": "Money Hub", "description": "Spending insights and savings goals",
                "tags": ["banking", "spending", "budget"]}],
}


def _http(status: int, body: Any) -> dict:
    return {"statusCode": status, "body": json.dumps(body),
            "headers": {"content-type": "application/json", "a2a-extensions": protocol.EXT,
                        "cache-control": "no-store", "x-content-type-options": "nosniff"}}


def lambda_handler(event: dict, context: Any) -> dict:
    event = event if isinstance(event, dict) else {}
    if "bridgeWork" in event and "requestContext" not in event:            # poll mode's second half
        do_poll_work(event["bridgeWork"])
        return {"ok": True}
    http = (event.get("requestContext") or {}).get("http") or {}
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if http.get("method") == "GET" and event.get("rawPath") in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
        return _http(200, AGENT_CARD)
    if http.get("method") != "POST":
        return _http(404, {"error": "not_found"})
    key = api_key()
    given = headers.get("authorization", "")
    given = given[7:] if given.lower().startswith("bearer ") else ""
    if not key:
        return _http(503, {"error": "not_configured"})
    if not given or not hmac.compare_digest(given.encode(), key.encode()):
        logger.info("event=AUTH outcome=refused")
        return _http(401, {"error": "unauthorised"})
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        return _http(413, {"error": "too_large"})
    try:
        request = json.loads(raw)
    except ValueError:
        return _http(200, protocol.rpc_error(None, -32700, "Parse error.", "PARSE_ERROR"))
    if not isinstance(request, dict):
        return _http(200, protocol.rpc_error(None, -32600, "Invalid request.", "INVALID_REQUEST"))
    try:
        return _http(200, dispatch(request, headers))
    except Exception:
        logger.exception("event=DISPATCH outcome=error")
        return _http(200, protocol.rpc_error(request.get("id"), -32603, "Internal error.", "INTERNAL"))
