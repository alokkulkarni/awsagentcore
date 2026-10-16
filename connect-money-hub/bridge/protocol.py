"""
protocol.py
===========
The Connect A2A contract for an external agent that talks to the customer
(SPEC section 5), as plain functions: read what Connect sends, build what we
send back, and build the per-turn OpenTelemetry trace Connect requires.

Sources: "A2A protocol contract for external AI agents" and "A2A sample events"
in the Amazon Connect Customer developer guide (A2A protocol v1.0, JSON-RPC).

Over HTTPS, Connect sends each event as its own SendMessage request. A customer
turn is answered with one JSON-RPC result holding a task: the reply as a text
artifact, the turn's trace as a TRACING_SPAN artifact, and a terminal status,
carrying FINISH when the Money Hub agent hands back. That composite form is the
documented "the response or a task" over HTTPS, built from the streamed samples;
it is the first thing to confirm on a live contact (SPEC section 9).
"""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone

EXT = "https://docs.aws.amazon.com/connect/a2a/ext/v1"
EVENT_TYPE = f"{EXT}/eventType"
EMPTY_INPUT = "<EMPTY_USER_INPUT>"
AGENT_NAME = "money-hub-agent"


# ── reading what Connect sends ──────────────────────────────────────────────────

def message_of(request: dict) -> dict:
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    message = params.get("message")
    return message if isinstance(message, dict) else {}


def event_type(message: dict) -> str:
    """The extension event type, or TEXT for a plain customer turn."""
    meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    kind = meta.get(EVENT_TYPE)
    if kind:
        return str(kind)
    return "TEXT" if text_of(message) is not None else "UNKNOWN"


def data_part(message: dict, key: str) -> dict:
    for part in message.get("parts") or []:
        if isinstance(part, dict) and isinstance(part.get("data"), dict) and isinstance(part["data"].get(key), dict):
            return part["data"][key]
    return {}


def text_of(message: dict) -> str | None:
    texts = [p["text"] for p in message.get("parts") or [] if isinstance(p, dict) and isinstance(p.get("text"), str)]
    return " ".join(texts) if texts else None


def contact_id_of(contact_arn: str) -> str:
    """'arn:aws:connect:…:instance/<id>/contact/<contactId>' -> '<contactId>'."""
    return contact_arn.rsplit("/contact/", 1)[1] if "/contact/" in (contact_arn or "") else ""


def history_of(init: dict) -> list[dict]:
    """Connect's history as [{role: user|assistant, text}], oldest first, text parts only."""
    turns = []
    for m in init.get("history") or []:
        if not isinstance(m, dict):
            continue
        text = text_of(m)
        if text:
            turns.append({"role": "user" if m.get("role") == "ROLE_USER" else "assistant", "text": text})
    return turns


def trace_context(headers: dict) -> tuple[str, str]:
    """
    (traceId, parent span ID) from Connect's W3C headers. The parent is the span
    named in tracestate 'connect=parentSpanId:<uuid>' (first 16 hex digits),
    or else traceparent's span. Fresh IDs when neither is present.
    """
    trace_id, parent = "", ""
    parts = (headers.get("traceparent") or "").split("-")
    if len(parts) == 4 and len(parts[1]) == 32 and len(parts[2]) == 16:
        trace_id, parent = parts[1], parts[2]
    for entry in (headers.get("tracestate") or "").split(","):
        name, _, value = entry.strip().partition("=")
        if name == "connect" and value.startswith("parentSpanId:"):
            hex_id = value.split(":", 1)[1].replace("-", "")
            if len(hex_id) >= 16:
                parent = hex_id[:16]
    return trace_id or secrets.token_hex(16), parent


# ── building what we send back ──────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _result(request_id, value: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _agent_message(context_id: str, data: dict, event: str) -> dict:
    return {"messageId": f"m-{secrets.token_hex(6)}", "contextId": context_id, "role": "ROLE_AGENT",
            "parts": [{"data": data, "mediaType": "application/json"}], "extensions": [EXT],
            "metadata": {EVENT_TYPE: event}}


def init_session_response(request_id, context_id: str) -> dict:
    """Accept the session (text only: no audio counter-proposal)."""
    return _result(request_id, {"message": _agent_message(
        context_id, {"initSessionResponse": {"statusCode": "200"}}, "INIT_SESSION_RESPONSE")})


def acknowledge(request_id, context_id: str, event: str) -> dict:
    """
    The reply to an event that needs no answer of its own (CHANNEL_STATE, an
    INTERRUPTION, an informational ERROR). The contract doesn't define one over
    HTTPS; a message echoing the event is the least surprising (SPEC section 9).
    """
    return _result(request_id, {"message": _agent_message(context_id, {"acknowledged": {"eventType": event}}, event)})


def turn_task(request_id, context_id: str, task_id: str, reply: str, trace: dict | None = None,
              finish: dict | None = None) -> dict:
    """One customer turn, answered: the reply, its trace, and a completed status (with FINISH to hand back)."""
    artifacts = [{"artifactId": f"resp-{task_id}", "parts": [{"text": reply, "mediaType": "text/plain"}],
                  "metadata": {EVENT_TYPE: "TEXT_RESPONSE_CHUNK", "lastChunk": True}}]
    if trace:
        artifacts.append({"artifactId": f"trace-{task_id}",
                          "parts": [{"data": {"tracingSpan": trace}, "mediaType": "application/json"}],
                          "metadata": {EVENT_TYPE: "TRACING_SPAN"}})
    status = {"state": "TASK_STATE_COMPLETED", "timestamp": _now_iso()}
    if finish:
        status["message"] = {"messageId": f"m-{secrets.token_hex(6)}", "role": "ROLE_AGENT",
                             "parts": [{"data": {"finish": {"type": finish["type"], "reason": finish["reason"]}},
                                        "mediaType": "application/json"}],
                             "metadata": {EVENT_TYPE: "FINISH"}}
    return _result(request_id, {"task": {"id": task_id, "contextId": context_id, "status": status,
                                         "artifacts": artifacts, "kind": "task"}})


def working_task(request_id, context_id: str, task_id: str) -> dict:
    """The poll-mode answer: Connect then asks for the result with GetTask."""
    return _result(request_id, {"task": {"id": task_id, "contextId": context_id, "kind": "task",
                                         "status": {"state": "TASK_STATE_WORKING", "timestamp": _now_iso()}}})


def failed_task(request_id, context_id: str, task_id: str, code: int, reason: str, category: str) -> dict:
    """A turn that started but could not finish. This ends the collaboration; Connect takes the flow's Error branch."""
    return _result(request_id, {"task": {"id": task_id, "contextId": context_id, "kind": "task", "status": {
        "state": "TASK_STATE_FAILED", "timestamp": _now_iso(),
        "message": {"messageId": f"m-{secrets.token_hex(6)}", "role": "ROLE_AGENT",
                    "parts": [{"data": {"error": {"errorCode": code, "errorReason": reason, "errorCategory": category}},
                               "mediaType": "application/json"}],
                    "metadata": {EVENT_TYPE: "ERROR"}}}}})


def rpc_error(request_id, code: int, message: str, reason: str) -> dict:
    """A request we can't dispatch: a JSON-RPC error carrying google.rpc.ErrorInfo, as A2A v1.0 asks."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message, "data": [
        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason, "domain": "a2a-protocol.org"}]}}


# ── the per-turn trace ──────────────────────────────────────────────────────────

def _attr(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _message_event(role: str, participant: str, content: str, at_ns: int, extra: list | None = None) -> dict:
    return {"name": "aws.connect.span.message", "timeUnixNano": str(at_ns), "attributes": [
        _attr("aws.connect.span.message.role", role), _attr("aws.connect.span.message.type", "TEXT_MESSAGE"),
        _attr("aws.connect.span.message.participant", participant),
        _attr("aws.connect.span.message.content", content[:4000]), *(extra or [])]}


def build_trace(trace_id: str, parent_span_id: str, turn: dict) -> dict:
    """
    One OTLP/JSON TracesData document for the turn: a root 'invoke_agent' span
    (kind SERVER) with the customer's input and the agent's output, a 'chat' span
    for the model, and an 'execute_tool' span per tool call with its input and result.
    `turn` is what the agent returned: input, reply, model, usage, startNs, endNs, tools.
    """
    start, end = int(turn.get("startNs") or time.time_ns()), int(turn.get("endNs") or time.time_ns())
    root_id = secrets.token_hex(8)
    usage = turn.get("usage") or {}
    root = {
        "traceId": trace_id, "spanId": root_id, "name": f"invoke_agent {AGENT_NAME}", "kind": 2,
        "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
        "attributes": [_attr("gen_ai.agent.name", AGENT_NAME), _attr("gen_ai.operation.name", "invoke_agent"),
                       _attr("gen_ai.usage.input_tokens", int(usage.get("input", 0))),
                       _attr("gen_ai.usage.output_tokens", int(usage.get("output", 0))),
                       _attr("aws.connect.usage.total_tokens", int(usage.get("input", 0)) + int(usage.get("output", 0)))],
        "events": [_message_event("input", "user", turn.get("input", ""), start),
                   _message_event("output", "assistant", turn.get("reply", ""), end)],
        "status": {"code": 2, "message": turn["error"]} if turn.get("error") else {"code": 1},
    }
    if parent_span_id:
        root["parentSpanId"] = parent_span_id
    spans = [root, {
        "traceId": trace_id, "spanId": secrets.token_hex(8), "parentSpanId": root_id,
        "name": f"chat {turn.get('model', 'model')}", "kind": 3,
        "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
        "attributes": [_attr("gen_ai.operation.name", "chat"), _attr("gen_ai.request.model", turn.get("model", ""))],
        "status": {"code": 1}}]
    for tool in turn.get("tools") or []:
        t_start = int(tool.get("startNs") or start)
        t_end = int(tool.get("endNs") or t_start)
        tool_id = secrets.token_hex(6)
        extra = [_attr("aws.connect.span.message.tool_id", tool_id),
                 _attr("aws.connect.span.message.tool_type", "FUNCTION")]
        spans.append({
            "traceId": trace_id, "spanId": secrets.token_hex(8), "parentSpanId": root_id,
            "name": f"execute_tool {tool.get('name', 'tool')}", "kind": 3,
            "startTimeUnixNano": str(t_start), "endTimeUnixNano": str(t_end),
            "attributes": [_attr("gen_ai.operation.name", "execute_tool"), _attr("gen_ai.tool.name", tool.get("name", ""))],
            "events": [_message_event("instruction", "assistant", str(tool.get("input", "")), t_start, extra),
                       _message_event("output", "tool", str(tool.get("output", "")), t_end, extra)],
            "status": {"code": 1} if tool.get("ok", True) else {"code": 2, "message": "tool failed"}})
    return {"otlp": {"resourceSpans": [{
        "resource": {"attributes": [_attr("service.name", AGENT_NAME)]},
        "scopeSpans": [{"scope": {"name": "aria.money-hub", "version": "1.0.0"}, "spans": spans}]}]}}
