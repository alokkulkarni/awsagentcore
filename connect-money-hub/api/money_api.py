"""
money_api.py
============
The Money Hub page and its data, and two read-only tools for the MCP gateway.
One Lambda, three ways in, told apart by how a request arrives, never by what
it asks for (the dispute service's pattern):

    Web       the HTTP API: the page, its assets, and its JSON calls. Every call
              carries the page link's secret in the body, never in an address.
    Tool      the MCP gateway: get_money_hub_summary and get_money_hub_forecast,
              read-only, for ARIA's agent assist.
    Internal  a direct invoke {"operation": "mint_link", "customerId", "loa"?}
              from the deploy script, for a demo link. A tool call can never
              reach it.

The page can also start a call or a chat with ARIA (moneyhub/contact.py):
/api/contact/call and /api/contact/chat start the contact in Amazon Connect and
return only what the browser needs to join it.

ENVIRONMENT VARIABLES
    MONEY_HUB_TABLE      DynamoDB table. Unset = in memory, for local runs only
    PUBLIC_BASE_URL      The page's address, for links
    CONNECT_INSTANCE_ID  Connect instance for calls and chats from the page.
    CONTACT_FLOW_ID      The flow they start in (conversation bot flow).
                         Either unset = the page offers no call or chat.
    LOG_LEVEL            default INFO
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from moneyhub import contact
from moneyhub.service import MoneyHub, MoneyHubError
from moneyhub.store import DynamoStore, MemoryStore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_TABLE = os.environ.get("MONEY_HUB_TABLE", "")
hub = MoneyHub(DynamoStore(_TABLE, time.time) if _TABLE else MemoryStore(time.time), time.time,
               page_url=os.environ.get("PUBLIC_BASE_URL", ""))

WEB_DIR = next(d for d in (Path(__file__).parent / "web", Path(__file__).parent.parent / "web") if d.is_dir())
MAX_BODY_BYTES = 4096
# chime.js is the Amazon Chime SDK, built by scripts/build_chime.sh (not in git).
ASSETS = {"styles.css": ("styles.css", "text/css"), "app.js": ("app.js", "text/javascript"),
          "talk.js": ("talk.js", "text/javascript"), "chime.js": ("vendor/chime.js", "text/javascript")}
REGION = os.environ.get("AWS_REGION", "eu-west-2")
CONNECT_INSTANCE_ID = os.environ.get("CONNECT_INSTANCE_ID", "")
CONTACT_FLOW_ID = os.environ.get("CONTACT_FLOW_ID", "")
# Calls need the Chime SDK's media and signalling hosts; chats need the Connect Participant Service and its websocket.
_TALK_HOSTS = (f"https://participant.connect.{REGION}.amazonaws.com wss://*.transport.connect.{REGION}.amazonaws.com "
               "https://*.chime.aws wss://*.chime.aws https://*.ingest.chime.aws")
SECURITY_HEADERS = {
    "content-security-policy": f"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self' {_TALK_HOSTS}; "
                               "worker-src 'self' blob:; media-src 'self' blob: mediastream:; "
                               "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "cache-control": "no-store",
    "permissions-policy": "microphone=(self), camera=(), geolocation=()",
}
_connect = None


def connect_client():
    """Amazon Connect, created on first use (replaced in tests)."""
    global _connect
    if _connect is None:
        import boto3
        _connect = boto3.client("connect", region_name=REGION)
    return _connect


def start_contact(kind: str, session: dict, view: str) -> dict:
    """Start a call or chat with ARIA for the page link's customer; only what the browser needs comes back."""
    if not (CONNECT_INSTANCE_ID and CONTACT_FLOW_ID):
        raise MoneyHubError("talk_unavailable", "Calls and chats aren't set up for this page yet.", 503)
    request = contact.start_request(kind, session["customerId"], session["loa"], view, CONNECT_INSTANCE_ID,
                                    CONTACT_FLOW_ID, str(uuid.uuid4()))
    client = connect_client()
    try:
        response = client.start_web_rtc_contact(**request) if kind == "call" else client.start_chat_contact(**request)
    except Exception as error:                                     # botocore ClientError and connection errors
        logger.warning("start %s failed: %s", kind, type(error).__name__)
        raise MoneyHubError("talk_failed", "We couldn't connect you just now. Try again in a minute.", 502)
    return {**contact.browser_reply(kind, response), "region": REGION,
            "verified": contact.verified_level(session["loa"])}
TOOLS = ("get_money_hub_summary", "get_money_hub_forecast")


def _response(status: int, body: str, content_type: str) -> dict:
    return {"statusCode": status, "body": body, "headers": {"content-type": f"{content_type}; charset=utf-8",
                                                            **SECURITY_HEADERS}}


def _json(status: int, payload: Any) -> dict:
    return _response(status, json.dumps(payload), "application/json")


def _body(event: dict) -> dict:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        raise MoneyHubError("too_large", "Request too large.", 413)
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        raise MoneyHubError("bad_request", "The request was not understood.")
    if not isinstance(parsed, dict):
        raise MoneyHubError("bad_request", "The request was not understood.")
    return parsed


def _s(body: dict, name: str) -> str:
    value = body.get(name)
    return value.strip() if isinstance(value, str) else ""


def _num(body: dict, name: str) -> float:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MoneyHubError("bad_request", f"{name} must be a number.")
    try:
        return float(value)
    except ValueError:
        raise MoneyHubError("bad_request", f"{name} must be a number.")


def web(event: dict) -> dict:
    method = event["requestContext"]["http"].get("method", "")
    path = (event.get("rawPath") or "/").rstrip("/") or "/"
    if method == "GET":
        if path == "/":
            return _response(200, (WEB_DIR / "index.html").read_text(encoding="utf-8"), "text/html")
        name = path.removeprefix("/assets/")
        if path.startswith("/assets/") and name in ASSETS and (WEB_DIR / ASSETS[name][0]).is_file():
            file, content_type = ASSETS[name]
            return _response(200, (WEB_DIR / file).read_text(encoding="utf-8"), content_type)
        return _response(404, "Not found", "text/plain")
    if method != "POST" or not path.startswith("/api/"):
        return _response(404, "Not found", "text/plain")
    try:
        body = _body(event)
        session = hub.link_session(_s(body, "token"))     # the page's own secret; nothing else names a customer
        customer = session["customerId"]
        if path == "/api/hub":
            reply = {**hub.page_view(customer), "talk": bool(CONNECT_INSTANCE_ID and CONTACT_FLOW_ID)}
        elif path == "/api/transactions":
            reply = hub.list_transactions(customer, _s(body, "from"), _s(body, "to"), _s(body, "category"),
                                          _s(body, "direction"), _s(body, "merchant"), int(_num(body, "page") or 1)
                                          if "page" in body else 1, 25)
        elif path == "/api/recategorise":
            reply = hub.recategorise(customer, _s(body, "transactionId"), _s(body, "category"), "page")
        elif path == "/api/goal":
            reply = hub.save_goal(customer, _s(body, "name"), _num(body, "target"), _s(body, "byDate"),
                                  _num(body, "saved") if "saved" in body else 0.0)
        elif path == "/api/goal/delete":
            reply = hub.delete_goal(customer, _s(body, "name"))
        elif path in ("/api/contact/call", "/api/contact/chat"):
            reply = start_contact(path.rsplit("/", 1)[-1], session, _s(body, "view"))
        else:
            return _response(404, "Not found", "text/plain")
        status, outcome = 200, "ok"
    except MoneyHubError as error:
        reply, status, outcome = {"error": error.code, "message": error.message}, error.status, error.code
    except Exception:
        logger.exception("route=%s failed", path)
        reply, status, outcome = {"error": "error", "message": "Something went wrong. Try again."}, 500, "error"
    logger.info("route=%s status=%s outcome=%s", path, status, outcome)      # never the body or a token
    return _json(status, reply)


def _is_tool_call(event: dict, context: Any) -> bool:
    try:
        if (context.client_context.custom or {}).get("bedrockAgentCoreToolName"):
            return True
    except Exception:
        pass
    return any(key in event for key in ("jsonrpc", "method", "params", "toolName", "tool_name"))


def _tool(event: dict, context: Any) -> dict:
    name = ""
    try:
        name = (context.client_context.custom or {}).get("bedrockAgentCoreToolName", "")
    except Exception:
        pass
    rpc = event.get("params") if isinstance(event.get("params"), dict) else {}
    name = (name or rpc.get("name") or event.get("toolName") or "").split("___")[-1]
    args = rpc.get("arguments") if isinstance(rpc.get("arguments"), dict) else event
    customer = str(args.get("customer_id") or "")
    try:
        if name == "get_money_hub_summary":
            o = hub.overview(customer)
            d = hub.discretionary(customer)
            reply = {"balance": o["balance"], "averageMonth": o["averageMonth"],
                     "topSpending": [{k: c[k] for k in ("words", "total", "discretionary")} for c in o["topSpending"]],
                     "essentialPerMonth": d["essentialPerMonth"], "discretionaryPerMonth": d["discretionaryPerMonth"],
                     "goals": hub.goals(customer)}
        elif name == "get_money_hub_forecast":
            f = hub.forecast(customer, 3)
            reply = {"startBalance": f["startBalance"], "basis": f["basis"],
                     "months": [{k: m[k] for k in ("month", "expectedIn", "expectedOut", "endBalance")} for m in f["months"]]}
        else:
            reply = {"error": "unknown_tool", "message": f"Unknown tool: {name or '(none)'}"}
    except MoneyHubError as error:
        reply = {"error": error.code, "message": error.message}
    logger.info("tool=%s outcome=%s", name if name in TOOLS else "unknown", reply.get("error", "ok"))
    return reply


def lambda_handler(event: dict, context: Any) -> dict:
    event = event if isinstance(event, dict) else {}
    if isinstance(event.get("requestContext"), dict) and "http" in event["requestContext"]:
        return web(event)
    if event.get("operation") == "mint_link" and not _is_tool_call(event, context):
        try:
            return {"link": hub.mint_link(str(event.get("customerId") or ""), str(event.get("loa") or ""))}
        except MoneyHubError as error:
            return {"error": error.code}
    return _tool(event, context)
