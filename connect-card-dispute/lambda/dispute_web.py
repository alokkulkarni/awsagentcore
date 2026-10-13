"""
dispute_web.py
==============
The web way into the Lambda: the customer page, the adviser page, the JSON
calls those two pages make, and the door the CX designer agent's tool uses.
Reached through the HTTP API only.

Every page call is a POST carrying the caller's own secret in the body: the
customer page's session id, or the adviser link's token. Neither is ever put in
an address, so neither reaches an access log.

The CX designer door (POST /acxd/ops) is for the Live Sync route. A CX designer
tool is an HTTPS call with a key, not an MCP tool, so it comes in here. It
accepts one operation, attachToScreen, and only with the right key. Being a web
request, it can never reach a tool or the internal screen-pop operation.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dispute_service import DisputeError, DisputeService

logger = logging.getLogger()

# In the Lambda package the pages sit in web/ beside this file; in the repo, one folder up.
WEB_DIR = next(d for d in (Path(__file__).parent / "web", Path(__file__).parent.parent / "web") if d.is_dir())
MAX_BODY_BYTES = 4096

PAGES = {"/": "customer.html", "/adviser": "adviser.html"}
ASSETS = {"styles.css": "text/css", "common.js": "text/javascript", "customer.js": "text/javascript",
          "adviser.js": "text/javascript", "formfill.js": "text/javascript", "livesync.js": "text/javascript"}

# Only this site's own files may load or run, and nothing may frame the pages.
@dataclass
class Doors:
    """What the web way in needs from outside the Lambda. Each is a function so tests can supply their own."""
    acxd_key: Callable[[], str]                     # the CX designer door's key, or "" if not set up
    touchpoint_keys: Callable[[], dict]             # {"deploymentKey", "apiKey"} for Live Sync, or {}
    customer_of_contact: Callable[[str], str]       # the customerId Connect holds for a contact, or ""
    region: str = "eu-west-2"


VENDOR_FILE = re.compile(r"^/vendor/([A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+\.js$")
CONTACT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ACXD_REPLY = {"attached": False, "locked": False, "reason": ""}       # every field, always


SECURITY_HEADERS = {
    "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


def customer_page_headers(region: str) -> dict:
    """
    The customer page runs Amazon's Touchpoint library for Live Sync, which needs
    WebAssembly, its own inline styles, and connections to the CX designer's
    endpoints. Same policy as the mortgage Live Sync page. Nothing else is allowed.
    """
    connect = (f"https://nlu.acxd.connect.{region}.amazonaws.com wss://ws.nlu.acxd.connect.{region}.amazonaws.com "
               f"https://participant.connect.{region}.amazonaws.com wss://*.transport.connect.{region}.amazonaws.com")
    return {**SECURITY_HEADERS,
            "content-security-policy": "default-src 'none'; script-src 'self' 'wasm-unsafe-eval'; "
                                       "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                                       "font-src 'self' data:; media-src 'self' blob:; worker-src 'self' blob:; "
                                       f"connect-src 'self' {connect}; frame-ancestors 'none'; base-uri 'none'; "
                                       "form-action 'none'",
            "permissions-policy": "microphone=(), camera=(), geolocation=(), payment=()"}


def _response(status: int, body: str, content_type: str, headers: dict | None = None) -> dict:
    return {"statusCode": status, "body": body,
            "headers": {"content-type": f"{content_type}; charset=utf-8", **(headers or SECURITY_HEADERS)}}


def _json(status: int, payload: dict) -> dict:
    return _response(status, json.dumps(payload), "application/json")


def _file(name: str, content_type: str, headers: dict | None = None) -> dict:
    return _response(200, (WEB_DIR / name).read_text(encoding="utf-8"), content_type, headers)


def _vendor(path: str) -> dict:
    """A file of the Touchpoint library, put in web/vendor by the deploy script. Versioned path, so it can be cached."""
    vendor = (WEB_DIR / "vendor").resolve()
    target = (WEB_DIR / path.lstrip("/")).resolve()
    if not VENDOR_FILE.match(path) or vendor not in target.parents or not target.is_file():
        return _response(404, "Not found", "text/plain")
    return _response(200, target.read_text(encoding="utf-8"), "text/javascript",
                     {**SECURITY_HEADERS, "cache-control": "public, max-age=86400, immutable"})


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


def _acxd(event: dict, service: DisputeService, doors: Doors) -> dict:
    """The CX designer door. One operation, and only with the key."""
    key = doors.acxd_key()
    given = (event.get("headers") or {}).get("x-api-key", "")
    if not key:
        return _json(503, {"error": "not_configured"})
    if not hmac.compare_digest(given.encode(), key.encode()):
        return _json(401, {"error": "unauthorised"})
    body = _body(event)
    if body.get("operation") != "attachToScreen":
        return _json(403, {"error": "operation_not_available"})
    contact_id = _text(body, "contactId").strip().lower()
    if not CONTACT_ID.match(contact_id):
        return _json(200, {**ACXD_REPLY, "reason": "contact_not_recognised"})
    # Who the customer is comes from Connect's own record of this contact (rule R7),
    # never from anything the agent or the customer supplies.
    reply = service.attach_contact_screen(contact_id, doors.customer_of_contact(contact_id), _text(body, "code"))
    return _json(200, {**ACXD_REPLY, **reply})


def handle(event: dict, service: DisputeService, doors: Doors) -> dict:
    http = event["requestContext"]["http"]
    method, path = http.get("method", ""), (event.get("rawPath") or "/").rstrip("/") or "/"

    if method == "GET":
        if path == "/":
            return _file(PAGES[path], "text/html", customer_page_headers(doors.region))
        if path in PAGES:
            return _file(PAGES[path], "text/html")
        name = path.removeprefix("/assets/")
        if path.startswith("/assets/") and name in ASSETS:
            return _file(name, ASSETS[name])
        if path.startswith("/vendor/"):
            return _vendor(path)
        if path == "/api/config":
            keys = doors.touchpoint_keys() or {}
            ready = bool(keys.get("deploymentKey") and keys.get("apiKey"))
            return _json(200, {"configured": ready, "region": doors.region,
                               **({"deploymentKey": keys["deploymentKey"], "apiKey": keys["apiKey"]} if ready else {})})
        return _response(404, "Not found", "text/plain")

    routes = {
        "/api/screen": lambda b: service.create_screen(),
        "/api/screen/status": lambda b: service.screen_status(_text(b, "sessionId")),
        "/api/screen/confirm": lambda b: service.customer_confirm(_text(b, "sessionId")),
        "/api/screen/save": lambda b: service.page_save(_text(b, "sessionId"), _fields(b)),
        "/acxd/ops": None,                              # handled by _acxd: it needs the request's headers
        "/api/adviser/open": lambda b: service.adviser_open(_text(b, "token")),
        "/api/adviser/update": lambda b: service.adviser_update(_text(b, "token"), _fields(b)),
        "/api/adviser/confirm": lambda b: service.adviser_record_confirmation(_text(b, "token"), b.get("accepted") is True),
        "/api/adviser/submit": lambda b: service.adviser_submit(_text(b, "token")),
    }
    if method != "POST" or path not in routes:
        return _response(404, "Not found", "text/plain")
    route = routes[path]
    try:
        if route is None:
            reply = _acxd(event, service, doors)
            answer = json.loads(reply["body"])
            outcome = answer.get("error") or answer.get("reason") or "ok"
        else:
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
