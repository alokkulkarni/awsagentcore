"""
dispute_web.py
==============
The web way into the Lambda: the customer page, the adviser page and the JSON
calls those two pages make. Reached through the HTTP API only.

Every JSON call is a POST carrying the caller's own secret in the body: the
customer page's session id, or the adviser link's token. Neither is ever put in
an address, so neither reaches an access log.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from dispute_service import DisputeError, DisputeService

logger = logging.getLogger()

# In the Lambda package the pages sit in web/ beside this file; in the repo, one folder up.
WEB_DIR = next(d for d in (Path(__file__).parent / "web", Path(__file__).parent.parent / "web") if d.is_dir())
MAX_BODY_BYTES = 4096

PAGES = {"/": "customer.html", "/adviser": "adviser.html"}
ASSETS = {"styles.css": "text/css", "common.js": "text/javascript",
          "customer.js": "text/javascript", "adviser.js": "text/javascript"}

# Only this site's own files may load or run, and nothing may frame the pages.
SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def _response(status: int, body: str, content_type: str) -> dict:
    return {"statusCode": status, "headers": {"content-type": f"{content_type}; charset=utf-8", **SECURITY_HEADERS},
            "body": body}


def _json(status: int, payload: dict) -> dict:
    return _response(status, json.dumps(payload), "application/json")


def _file(name: str, content_type: str) -> dict:
    return _response(200, (WEB_DIR / name).read_text(encoding="utf-8"), content_type)


def _body(event: dict) -> dict:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        raise DisputeError("too_large", "Request too large.", 413)
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        raise DisputeError("bad_request", "The request was not understood.", 400)
    if not isinstance(parsed, dict):
        raise DisputeError("bad_request", "The request was not understood.", 400)
    return parsed


def _text(body: dict, name: str) -> str:
    value = body.get(name)
    return value if isinstance(value, str) else ""


def _fields(body: dict) -> dict:
    fields = body.get("fields")
    if not isinstance(fields, dict):
        raise DisputeError("bad_request", "The request was not understood.", 400)
    return fields


def handle(event: dict, service: DisputeService) -> dict:
    http = event["requestContext"]["http"]
    method, path = http.get("method", ""), (event.get("rawPath") or "/").rstrip("/") or "/"

    if method == "GET":
        if path in PAGES:
            return _file(PAGES[path], "text/html")
        name = path.removeprefix("/assets/")
        if path.startswith("/assets/") and name in ASSETS:
            return _file(name, ASSETS[name])
        return _response(404, "Not found", "text/plain")

    routes = {
        "/api/screen": lambda b: service.create_screen(),
        "/api/screen/status": lambda b: service.screen_status(_text(b, "sessionId")),
        "/api/screen/confirm": lambda b: service.customer_confirm(_text(b, "sessionId")),
        "/api/adviser/open": lambda b: service.adviser_open(_text(b, "token")),
        "/api/adviser/update": lambda b: service.adviser_update(_text(b, "token"), _fields(b)),
        "/api/adviser/confirm": lambda b: service.adviser_record_confirmation(_text(b, "token"), b.get("accepted") is True),
        "/api/adviser/submit": lambda b: service.adviser_submit(_text(b, "token")),
    }
    route = routes.get(path) if method == "POST" else None
    if not route:
        return _response(404, "Not found", "text/plain")
    try:
        reply = _json(200, route(_body(event)))
        outcome = "ok"
    except DisputeError as error:
        reply, outcome = _json(error.status, {"error": error.code, "message": error.message}), error.code
    except ValueError as error:          # a field value the model refused
        reply, outcome = _json(400, {"error": "invalid_field", "message": str(error)}), "invalid_field"
    except Exception:
        logger.exception("route=%s failed", path)
        reply, outcome = _json(500, {"error": "error", "message": "Something went wrong. Try again."}), "error"
    logger.info("route=%s status=%s outcome=%s", path, reply["statusCode"], outcome)     # never the body
    return reply
