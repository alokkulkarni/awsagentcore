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
    Internal  a direct invoke {"operation": "mint_link", "customerId"} from the
              deploy script, for a demo link. A tool call can never reach it.

ENVIRONMENT VARIABLES
    MONEY_HUB_TABLE    DynamoDB table. Unset = in memory, for local runs only
    PUBLIC_BASE_URL    The page's address, for links
    LOG_LEVEL          default INFO
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from moneyhub.service import MoneyHub, MoneyHubError
from moneyhub.store import DynamoStore, MemoryStore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_TABLE = os.environ.get("MONEY_HUB_TABLE", "")
hub = MoneyHub(DynamoStore(_TABLE, time.time) if _TABLE else MemoryStore(time.time), time.time,
               page_url=os.environ.get("PUBLIC_BASE_URL", ""))

WEB_DIR = next(d for d in (Path(__file__).parent / "web", Path(__file__).parent.parent / "web") if d.is_dir())
MAX_BODY_BYTES = 4096
ASSETS = {"styles.css": "text/css", "app.js": "text/javascript"}
SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "cache-control": "no-store",
}
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
        if path.startswith("/assets/") and name in ASSETS:
            return _response(200, (WEB_DIR / name).read_text(encoding="utf-8"), ASSETS[name])
        return _response(404, "Not found", "text/plain")
    if method != "POST" or not path.startswith("/api/"):
        return _response(404, "Not found", "text/plain")
    try:
        body = _body(event)
        customer = hub.customer_of_link(_s(body, "token"))      # the page's own secret; nothing else names a customer
        if path == "/api/hub":
            reply = hub.page_view(customer)
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
        else:
            return _response(404, "Not found", "text/plain")
        status, outcome = 200, "ok"
    except MoneyHubError as error:
        reply, status, outcome = {"error": error.code, "message": error.message}, error.status, error.code
    except Exception:
        logger.exception("route=%s failed", path)
        reply, status, outcome = {"error": "error", "message": "Something went wrong. Try again."}, 500, "error"
    logger.info("route=%s status=%s outcome=%s", path, status, outcome)      # never the body
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
            return {"link": hub.mint_link(str(event.get("customerId") or ""))}
        except MoneyHubError as error:
            return {"error": error.code}
    return _tool(event, context)
