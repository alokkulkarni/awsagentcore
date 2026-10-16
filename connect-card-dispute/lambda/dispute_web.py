"""
dispute_web.py
==============
The web way into the Lambda: the customer page, the adviser page, the JSON
calls those two pages make, and the door the CX designer agent's tool uses.
Reached through the HTTP API only.

Every page call is a POST carrying the caller's own secret in the body: the
customer page's session id, or the adviser link's token. Neither is ever put in
an address, so neither reaches an access log.

The CX designer door (POST /acxd/ops) is the disputes agent's whole tool set
(SPEC Part 4). A CX designer tool is an HTTPS call with a key, not an MCP tool,
so it comes in here. Only with the right key; only the operations in
ACXD_OPERATIONS; and never with a customer ID or phone number from the request:
both come from Connect's own record of the contact (rule R7). Being a web
request, it can never reach a tool or the internal screen-pop operation. It has
no operation that confirms or submits a dispute.
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

from dispute_service import (ASSISTANT_DISPUTE, FORM_LINK_SECONDS, REPLACEMENT_WORKING_DAYS as REPLACEMENT_DAYS,
                             DisputeError, DisputeService)

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
    customer_of_contact: Callable[[str], str]       # the verified customerId Connect holds for a contact, or ""
    region: str = "eu-west-2"
    instance_id: str = ""                           # the Connect instance; not a secret
    contact_phone: Callable[[str], str] = lambda contact_id: ""     # the number the customer is calling from
    contact_channel: Callable[[str], str] = lambda contact_id: "VOICE"     # VOICE or CHAT, as the flow recorded it
    send_sms: Callable[[str, str], str] = lambda phone, text: "sms_not_configured"   # "" when sent, else why not
    sms_prefixes: tuple = ("+447",)                 # numbers a text may go to (UK mobiles)
    bank_name: str = "Your bank"


VENDOR_FILE = re.compile(r"^/vendor/([A-Za-z0-9._-]+/)?[A-Za-z0-9._-]+\.js$")
CONTACT_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ACXD_REPLY = {"attached": False, "locked": False, "reason": ""}       # every field, always

# The CX designer door's operations, each with its full reply. Every key is in
# every reply, because the CX designer rejects one that lacks a field.
_STATUS = {"ok": False, "reason": "", "message": ""}
ACXD_OPERATIONS = {
    "attachToScreen": ACXD_REPLY,               # the older code route; the disputes agent texts a link instead
    "listCardsAndPayments": {**_STATUS, "today": "", "cards": [], "payments": [], "page": 1, "totalPages": 1,
                             "totalPayments": 0, "hasMore": False},
    "startDispute": ASSISTANT_DISPUTE,
    "updateDispute": ASSISTANT_DISPUTE,
    "getDispute": ASSISTANT_DISPUTE,
    "blockCard": {**_STATUS, "cardType": "", "cardLastFour": "", "reference": "", "replacementOrdered": False,
                  "replacementReference": "", "arrivesInWorkingDays": "", "confirmation": ""},
    "orderReplacementCard": {**_STATUS, "cardType": "", "cardLastFour": "", "reference": "", "arrivesInWorkingDays": "",
                             "confirmation": ""},
    "sendFormLink": {**_STATUS, "sent": False, "sentTo": "", "link": ""},     # link: on chat only
}
# Request field -> dispute field, for updateDispute. Nothing else can be set. "reason"
# in a reply means why a call was refused, so the dispute's reason is "reasonCode".
_UPDATABLE = {"disputeType": "disputeType", "reasonCode": "reason", "cardInPossession": "cardInPossession",
              "cardBlocked": "cardBlocked", "contactedMerchant": "contactedMerchant", "narrative": "narrative"}


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
    # The list is the mortgage page's, unchanged. It was arrived at on live calls; one missing
    # address and Live Sync fails with nothing but a message in the browser's console.
    connect = (f"https://nlu.acxd.connect.{region}.amazonaws.com wss://ws.nlu.acxd.connect.{region}.amazonaws.com "
               f"https://participant.connect.{region}.amazonaws.com https://participant.connect.{region}.api.aws "
               f"wss://*.transport.connect.{region}.amazonaws.com https://*.chime.aws wss://*.chime.aws")
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


def _contact_id_shape(value) -> str:
    """
    Why a contactId was refused, for the log only, never the value itself:
    empty (a CX designer test, or the input is not mapped), placeholder (the
    input is Explicit text with a {contactId} chip inside, which sends the
    chip's name instead of the ID), or malformed.
    """
    if not isinstance(value, str) or not value.strip():
        return "empty"
    if "{" in value or "NLX" in value or "contactId" in value:
        return "placeholder"
    return "malformed"


def _send_form_link(service: DisputeService, doors: Doors, customer_id: str, contact_id: str, dispute_id: str) -> dict:
    """
    On chat, the link comes back for the assistant to post in the chat: the
    customer is already in that verified conversation. On a call, it is texted to
    the number they are calling from, and the assistant never sees it.
    """
    if doors.contact_channel(contact_id) == "CHAT":
        service._owned(customer_id, dispute_id)
        link = service.mint_form_link(customer_id, contact_id, dispute_id)
        service.mark_link_sent(dispute_id, "chat")
        return {"sent": True, "sentTo": "this chat", "link": link}
    phone = "".join(ch for ch in doors.contact_phone(contact_id) if ch == "+" or ch.isdigit())
    if not phone.startswith(doors.sms_prefixes):
        raise DisputeError("no_mobile_number", "The customer is not calling from a mobile we can text. "
                           "Carry on filling the form by voice.")
    service._owned(customer_id, dispute_id)
    link = service.mint_form_link(customer_id, contact_id, dispute_id)
    hours = FORM_LINK_SECONDS // 3600
    failed = doors.send_sms(phone, f"{doors.bank_name}: here is your card dispute form, joined to the call you are on: "
                                   f"{link} It works for {hours} hours. We will never ask for your PIN or passwords.")
    if failed:
        raise DisputeError(failed, "The text could not be sent. Carry on filling the form by voice.")
    service.mark_link_sent(dispute_id, "text")
    return {"sent": True, "sentTo": f"the mobile ending {phone[-3:]}", "link": ""}


def _acxd_operation(operation: str, body: dict, service: DisputeService, doors: Doors,
                    customer_id: str, contact_id: str) -> dict:
    dispute_id = _text(body, "disputeId").strip().upper()
    if operation == "listCardsAndPayments":
        return service.assistant_cards_and_payments(
            customer_id, body.get("page") or 1, _text(body, "fromDate").strip(), _text(body, "toDate").strip(),
            _text(body, "cardType").strip().lower())
    if operation == "startDispute":
        return service.assistant_start(customer_id, _text(body, "transactionId").strip(), _text(body, "disputeType").strip())
    if operation == "updateDispute":
        fields = {field: body[name] for name, field in _UPDATABLE.items() if name in body}
        return service.assistant_update(customer_id, dispute_id, fields)
    if operation == "getDispute":
        return service.assistant_get(customer_id, dispute_id)
    if operation == "blockCard":
        # One call blocks the card and, if asked, orders its replacement, so the assistant has
        # no second tool to forget. "confirmation" is the sentence to say, with every reference.
        card_type = _text(body, "cardType").strip().lower()
        blocked = service.card_action(customer_id, card_type, "blocked")
        card = f"{blocked['cardType']} card ending {blocked['cardLastFour']}"
        reply = {"cardType": blocked["cardType"], "cardLastFour": blocked["cardLastFour"], "reference": blocked["reference"],
                 "confirmation": f"Your {card} is now blocked, so it can't be used again. "
                                 f"Your reference is {blocked['reference']}."}
        if _text(body, "orderReplacement").strip().lower() in ("yes", "true", "y"):
            replaced = service.card_action(customer_id, card_type, "replacement_ordered")
            reply.update({"replacementOrdered": True, "replacementReference": replaced["reference"],
                          "arrivesInWorkingDays": REPLACEMENT_DAYS,
                          "confirmation": reply["confirmation"] + f" A replacement {blocked['cardType']} card is on its "
                                          f"way and should arrive in {REPLACEMENT_DAYS} working days. Its reference is "
                                          f"{replaced['reference']}."})
        return reply
    if operation == "orderReplacementCard":
        done = service.card_action(customer_id, _text(body, "cardType").strip().lower(), "replacement_ordered")
        return {"cardType": done["cardType"], "cardLastFour": done["cardLastFour"], "reference": done["reference"],
                "arrivesInWorkingDays": REPLACEMENT_DAYS,
                "confirmation": f"A replacement {done['cardType']} card is on its way and should arrive in "
                                f"{REPLACEMENT_DAYS} working days. Its reference is {done['reference']}."}
    return _send_form_link(service, doors, customer_id, contact_id, dispute_id)          # sendFormLink


def _acxd(event: dict, service: DisputeService, doors: Doors) -> dict:
    """The CX designer door: only with the key, only the listed operations, the customer always from Connect."""
    key = doors.acxd_key()
    given = (event.get("headers") or {}).get("x-api-key", "")
    if not key:
        return _json(503, {"error": "not_configured"})
    if not hmac.compare_digest(given.encode(), key.encode()):
        return _json(401, {"error": "unauthorised"})
    body = _body(event)
    operation = body.get("operation")
    if operation not in ACXD_OPERATIONS:
        return _json(403, {"error": "operation_not_available"})
    empty = ACXD_OPERATIONS[operation]
    contact_id = _text(body, "contactId").strip().lower()
    if not CONTACT_ID.match(contact_id):
        return _json(200, {**empty, "reason": "contact_not_recognised"})
    # Who the customer is comes from Connect's own record of this contact (rule R7),
    # never from anything the agent or the customer supplies.
    customer_id = doors.customer_of_contact(contact_id)
    if operation == "attachToScreen":
        return _json(200, {**empty, **service.attach_contact_screen(contact_id, customer_id, _text(body, "code"))})
    if not customer_id:
        return _json(200, {**empty, "reason": "customer_not_identified",
                           "message": "The caller is not verified. Do nothing on their cards or disputes; "
                                      "pass them to a colleague."})
    # Refusals are answers, not failures: HTTP 200 with ok=false, so the agent can read why and carry on.
    try:
        reply = {**empty, **_acxd_operation(operation, body, service, doors, customer_id, contact_id), "ok": True}
    except DisputeError as error:
        reply = {**empty, "reason": error.code, "message": error.message}
    except ValueError as error:          # a field value the model refused; the message names the allowed values
        reply = {**empty, "reason": "invalid_field", "message": str(error)}
    return _json(200, reply)


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
            return _json(200, {"configured": ready, "region": doors.region, "instanceId": doors.instance_id,
                               **({"deploymentKey": keys["deploymentKey"], "apiKey": keys["apiKey"]} if ready else {})})
        return _response(404, "Not found", "text/plain")

    routes = {
        "/api/screen": lambda b: service.create_screen(),
        "/api/screen/open": lambda b: service.open_form_link(_text(b, "linkToken")),
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
            body = _body(event) if reply["statusCode"] not in (401, 503) else {}   # parsed once already
            asked = body.get("operation")
            outcome = f"{asked if asked in ACXD_OPERATIONS else '-'}:{outcome}"
            if outcome.endswith("contact_not_recognised"):
                outcome += f":{_contact_id_shape(body.get('contactId'))}"
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
