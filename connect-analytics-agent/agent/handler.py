import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Dict

from agent_core import ConnectAnalyticsAgent

# Restrict CORS to the configured frontend origin; when unset, omit the header
# entirely (an explicit "null" value is spoofable by sandboxed iframes).
_ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "")
CORS_HEADERS = {
    **({"Access-Control-Allow-Origin": _ALLOWED_ORIGIN} if _ALLOWED_ORIGIN else {}),
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "OPTIONS,GET,POST",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _response(status_code: int, body: Dict | str, content_type: str = "application/json") -> Dict:
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": content_type},
        "body": json.dumps(body, default=str) if content_type == "application/json" else body,
    }


def _stream_response(text: str, session_id: str) -> Dict:
    events = [f"event: session\ndata: {session_id}\n\n"]
    for chunk in text.split():
        events.append(f"event: message\ndata: {chunk}\n\n")
    events.append("event: done\ndata: [DONE]\n\n")
    return _response(200, "".join(events), content_type="text/event-stream")


def _normalized_path(event: Dict) -> str:
    return (event.get("path") or event.get("rawPath") or "").rstrip("/")


def _health_response(agent: ConnectAnalyticsAgent) -> Dict:
    return {
        "status": "ok",
        "mock_mode": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gateway_configured": bool(agent.gateway_endpoint),
    }


def _metrics_response(agent: ConnectAnalyticsAgent) -> Dict:
    request = {
        "tool_name": "get_realtime_metrics",
        "payload": {
            "actionGroup": "ConnectAnalyticsTools",
            "function": "get_realtime_metrics",
            "parameters": ([{"name": "instance_id", "type": "string", "value": agent.instance_id}] if agent.instance_id else []),
        },
    }
    raw = json.loads(agent._invoke_direct_tool(request))
    data = raw.get("data", {})
    totals = data.get("overall_totals", {})
    return {
        "mock": False,
        "last_updated": data.get("snapshot_time") or datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "agents_online": totals.get("AGENTS_ONLINE", 0),
            "agents_available": totals.get("AGENTS_AVAILABLE", 0),
            "agents_on_call": totals.get("AGENTS_ON_CALL", 0),
            "agents_in_acw": totals.get("AGENTS_AFTER_CONTACT_WORK", 0),
            "contacts_in_queue": totals.get("CONTACTS_IN_QUEUE", 0),
            "oldest_contact_age": totals.get("OLDEST_CONTACT_AGE_formatted", "00:00:00"),
        },
    }


def lambda_handler(event, _context):
    try:
        method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
        path = _normalized_path(event)
        agent = ConnectAnalyticsAgent()

        if method == "OPTIONS":
            return _response(200, {"ok": True})
        if method == "GET" and path.endswith("/health"):
            return _response(200, _health_response(agent))
        if method == "GET" and path.endswith("/metrics"):
            return _response(200, _metrics_response(agent))

        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64

            body = base64.b64decode(body).decode("utf-8")
        payload = json.loads(body)
        message = payload.get("message")
        session_id = str(payload.get("session_id") or "")
        if not _SESSION_ID_RE.match(session_id):
            session_id = str(uuid.uuid4())
        if not message or not isinstance(message, str):
            return _response(400, {"error": "message is required", "session_id": session_id})
        if len(message) > 4000:
            return _response(400, {"error": "message exceeds maximum length of 4000 characters", "session_id": session_id})

        response_text = agent.query(message, session_id=session_id)
        stream_flag = str((event.get("queryStringParameters") or {}).get("stream", "false")).lower() == "true"
        if stream_flag:
            return _stream_response(response_text, session_id)

        return _response(200, {"response": response_text, "session_id": session_id})
    except Exception as exc:  # pylint: disable=broad-except
        return _response(500, {"error": "Agent invocation failed"})
