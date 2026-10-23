"""
banking_api.py
==============
The internet banking app (Nationwide Building Society branded demo) and its API, in one Lambda behind an
HTTP API. It brings together three journeys that already work on their own, without changing them:

    Money Hub        the Money Hub page's own API code (connect-money-hub/api/money_api.py, packaged
                     alongside, unchanged): links, figures, goals, call transcripts, the face on calls
    Mortgage         the mortgage Live Sync backend through its IAM door, and its Live Sync keys
    Card disputes    the dispute service's form calls, and its Live Sync keys

Every API call carries the page link's secret in its body (the Money Hub rule): nothing works without a
live link, and the customer always comes from the link's record, never from the browser. Contacts started
from a page carry what that page's journey expects (bankapp/journeys.py), so the right assistant helps.

ENVIRONMENT VARIABLES (none are secrets)
    Those of money_api.py: MONEY_HUB_TABLE, PUBLIC_BASE_URL, CONNECT_INSTANCE_ID, CONTACT_FLOW_ID,
        QCONNECT_ASSISTANT_ID, TAVUS_FACE_ID, TAVUS_PAL_ID, TAVUS_SECRET_ID
    MORTGAGE_FUNCTION_NAME, MORTGAGE_TOUCHPOINT_SECRET, HELP_PHONE_NUMBER    the mortgage service
    DISPUTE_FUNCTION_NAME, DISPUTE_TOUCHPOINT_SECRET, DISPUTE_PAGES_URL     the dispute service
    DISPUTE_TABLE_NAME                                                      its table (the customer's disputes)
    FLOW_VIEW_PARAMETER     the SSM parameter turning the demo's "how it works" view on or off (bankapp/flowview.py)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import money_api
from bankapp import disputes, flowview, home, journeys, partners
from bankapp.products import PRODUCTS
from moneyhub.service import MoneyHubError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION = money_api.REGION
WEB_DIR = next(d for d in (Path(__file__).parent / "web", Path(__file__).parent.parent / "web") if d.is_dir())
DISPUTE_PAGES_URL = os.environ.get("DISPUTE_PAGES_URL", "").rstrip("/")
MAX_BODY_BYTES = 4096

# The app's own pages: one page (index.html) with its own router. The mortgage stages keep the mortgage page's
# paths, because the mortgage assistant navigates by them.
APP_PATHS = {"/", "/accounts", "/accounts/current", "/accounts/savings", "/cards", "/cards/dispute", "/money-hub", "/mortgages", "/help",
             "/apply/about-you", "/apply/property", "/apply/decision", "/apply/products", "/apply/documents",
             "/apply/review"}
ASSET = re.compile(r"^(?:[a-z0-9-]+/)*[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(js|css|svg)$")       # no "..": names only
TOUCHPOINT_FILE = re.compile(r"^[A-Za-z0-9._-]+\.js$")
TYPES = {"js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}
# Money Hub calls answered by the Money Hub's own code, exactly as on its page.
MONEY_HUB_ROUTES = {"/api/hub", "/api/transactions", "/api/recategorise", "/api/goal", "/api/goal/delete",
                    "/api/contact/transcript", "/api/contact/avatar", "/api/contact/avatar/end"}

# Calls, chats and the face: what the Money Hub page allows. Live Sync: Agentic CX designer's hosts, as the
# mortgage page allows. Daily: the face's room (its client loads its call engine from Daily's own domains).
# 'wasm-unsafe-eval' lets the Touchpoint SDK compile its WebAssembly, as the mortgage page allows (it does so even
# headless); it allows no JavaScript eval. Inline styles stay blocked: they're Touchpoint's own widget, which the
# headless binding never shows (the app's stylesheet marks what the assistant fills).
_DAILY = "https://*.daily.co https://*.dailywebrtc.com https://*.dailywebrtc.net"
_LIVE_SYNC = (f"https://nlu.acxd.connect.{REGION}.amazonaws.com wss://ws.nlu.acxd.connect.{REGION}.amazonaws.com "
              f"https://participant.connect.{REGION}.api.aws")
SECURITY_HEADERS = {
    **money_api.SECURITY_HEADERS,
    "content-security-policy": f"default-src 'none'; script-src 'self' 'wasm-unsafe-eval' {_DAILY}; style-src 'self'; "
                               f"connect-src 'self' {money_api._TALK_HOSTS} {money_api._AVATAR_HOSTS} {_LIVE_SYNC}; "
                               "worker-src 'self' blob:; media-src 'self' blob: mediastream:; "
                               "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
}


def _response(status: int, body: str, content_type: str, extra: dict | None = None) -> dict:
    return {"statusCode": status, "body": body,
            "headers": {"content-type": f"{content_type}; charset=utf-8", **SECURITY_HEADERS, **(extra or {})}}


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
    return value.strip()[:200] if isinstance(value, str) else ""


def start_contact(kind: str, session: dict, body: dict, token: str) -> dict:
    """A call or chat from whichever page the customer is on, carrying what that page's journey expects."""
    if not (money_api.CONNECT_INSTANCE_ID and money_api.CONTACT_FLOW_ID):
        raise MoneyHubError("talk_unavailable", "Calls and chats aren't set up for this app yet.", 503)
    page, view, stage = _s(body, "page"), _s(body, "view"), _s(body, "stage")
    payment = _payment(session["customerId"], body) if page == "card_dispute" else None
    try:
        request = journeys.start_request(kind, page, session["customerId"], session["loa"], money_api.CONNECT_INSTANCE_ID,
                                         money_api.CONTACT_FLOW_ID, str(uuid.uuid4()), view=view, stage=stage,
                                         application_id=_s(body, "applicationId"), payment=payment,
                                         first_name=home.first_name(session["customerId"]))
    except ValueError:
        raise MoneyHubError("bad_request", "That page can't start a conversation.")
    client = money_api.connect_client()
    try:
        response = client.start_web_rtc_contact(**request) if kind == "call" else client.start_chat_contact(**request)
    except Exception as error:                                     # botocore ClientError and connection errors
        logger.warning("start %s failed: %s", kind, type(error).__name__)                  # never the request
        raise MoneyHubError("talk_failed", "We couldn't connect you just now. Try again in a minute.", 502)
    reply = money_api.contact.browser_reply(kind, response)
    if reply.get("contactId"):
        money_api._remember_contact(token, reply["contactId"])
    return {**reply, "region": REGION, "verified": journeys.money_hub.verified_level(session["loa"]),
            "transcript": kind == "call" and bool(money_api.ASSISTANT_ID),
            "journey": page, "opener": journeys.opener(page, view, stage, payment)}


def _payment(customer_id: str, body: dict) -> dict | None:
    """The card payment the customer chose to dispute, from the customer's own payments (or None)."""
    wanted = _s(body, "paymentId")
    return next((p for p in home.cards(customer_id)["payments"] if p["id"] == wanted), None) if wanted else None


def _own_contact(token: str, contact_id: str) -> None:
    """Only a conversation this link started (the Money Hub's own record of them)."""
    item = money_api.hub.store.get(money_api._talk_key(token)) or {}
    if not contact_id or contact_id not in item.get("contacts", []):
        raise MoneyHubError("not_found", "That conversation isn't available.", 404)


def _began_at(contact_id: str) -> float:
    """When the conversation began, from Connect's own record of the contact (never the browser's clock)."""
    found = money_api.connect_client().describe_contact(InstanceId=money_api.CONNECT_INSTANCE_ID,
                                                        ContactId=contact_id)["Contact"]
    began = found.get("InitiationTimestamp")
    return began.timestamp() if hasattr(began, "timestamp") else 0.0


def contact_journey(customer: str, contact_id: str, token: str) -> dict:
    """For the demo's "how it works" view: where this link's own conversation has got to (bankapp/flowview.py)."""
    if not flowview.enabled():
        raise MoneyHubError("flow_view_off", "This view is turned off.", 404)
    _own_contact(token, contact_id)
    client = money_api.connect_client()
    described = client.describe_contact(InstanceId=money_api.CONNECT_INSTANCE_ID, ContactId=contact_id)["Contact"]
    attributes = client.get_contact_attributes(InstanceId=money_api.CONNECT_INSTANCE_ID,
                                               InitialContactId=contact_id).get("Attributes", {})
    began = described.get("InitiationTimestamp")
    began = began.timestamp() if hasattr(began, "timestamp") else 0.0
    money_hub_mark = money_api.hub.store.get(flowview.SPECIALIST_KEY.format(contact_id=contact_id))
    dispute = None
    try:
        # The newest dispute this conversation touched (open or submitted), never one from before it. The service
        # stamps whole seconds: allow for the second the conversation began in.
        touched = [d for d in disputes.list_disputes(customer) if disputes._as_time(d["updatedAt"]) >= began - 1]
        if touched:
            dispute = {**touched[0], "formSent": disputes._as_time(touched[0]["formSentAt"]) >= began - 1}
    except (disputes.NotAvailable, disputes.DisputeError):
        pass
    return flowview.state(described, attributes, dispute, money_hub_mark)


def contact_assistant(body: dict, token: str) -> dict:
    """Which of the flow's own assistants has this link's own conversation now ("mortgage", "card_dispute" or "" for
    ARIA): the mortgage form re-sends its fields when the mortgage assistant takes over. Not the demo view's: always on."""
    contact_id = _s(body, "contactId")
    _own_contact(token, contact_id)
    attributes = money_api.connect_client().get_contact_attributes(
        InstanceId=money_api.CONNECT_INSTANCE_ID, InitialContactId=contact_id).get("Attributes", {})
    return {"assistant": flowview.specialist(attributes)[0]}


def returned_note(body: dict, token: str) -> dict:
    """Has this link's own chat just come back to ARIA from an assistant? {note, key}: the widget sends the note to ARIA
    once per key (journeys.return_note), the moment her bot block starts."""
    contact_id = _s(body, "contactId")
    _own_contact(token, contact_id)
    attributes = money_api.connect_client().get_contact_attributes(
        InstanceId=money_api.CONNECT_INSTANCE_ID, InitialContactId=contact_id).get("Attributes", {})
    note = journeys.return_note(attributes)
    return {"note": note, "key": hashlib.sha256(note.encode()).hexdigest()[:16] if note else ""}


def page_moved(session: dict, body: dict, token: str) -> dict:
    """The customer moved to another page during this link's own conversation: the contact attributes the flows route
    on (the mortgage form's application, the Money Hub tab), and ARIA's known contact reason for her next turn."""
    contact_id = _s(body, "contactId")
    _own_contact(token, contact_id)
    page = _s(body, "page")
    payment = _payment(session["customerId"], body) if page == "card_dispute" else None
    try:
        changed = journeys.page_attributes(page, _s(body, "view"), _s(body, "stage"), _s(body, "applicationId"))
    except ValueError:
        raise MoneyHubError("bad_request", "That page can't be told to the assistant.")
    client = money_api.connect_client()
    client.update_contact_attributes(InstanceId=money_api.CONNECT_INSTANCE_ID, InitialContactId=contact_id,
                                     Attributes=changed)
    described = client.describe_contact(InstanceId=money_api.CONNECT_INSTANCE_ID, ContactId=contact_id)["Contact"]
    session_arn = (described.get("WisdomInfo") or {}).get("SessionArn", "")
    told = False
    if session_arn and money_api.ASSISTANT_ID:          # no session yet: ARIA hasn't joined, nothing to tell her
        reason = journeys.moved_reason(page, _s(body, "view"), _s(body, "stage"), payment)
        money_api.qconnect_client().update_session_data(
            assistantId=money_api.ASSISTANT_ID, sessionId=session_arn.rsplit("/", 1)[-1],
            data=[{"key": k, "value": {"stringValue": v}} for k, v in reason.items() if v])
        told = True
    return {"page": page, "ariaTold": told}


def dispute_route(path: str, customer: str, body: dict, token: str, verified: bool = False) -> dict:
    """The customer's disputes; submitting one; during a conversation, the dispute being filled in and its form."""
    try:
        if path == "/api/disputes":
            return {"disputes": disputes.list_disputes(customer)}
        if path == "/api/disputes/submit":
            # Submitting acts on the customer's behalf: only from a verified link, like starting a dispute.
            if not verified:
                raise MoneyHubError("not_verified", "Sign in with your verified link to submit a dispute.", 403)
            return {"dispute": disputes.submit(customer, _s(body, "disputeId"))}
        contact_id = _s(body, "contactId")
        _own_contact(token, contact_id)
        if path == "/api/disputes/live":
            return disputes.live(customer, _began_at(contact_id))
        return disputes.open_live(customer, contact_id, _s(body, "disputeId"))           # /api/disputes/open
    except disputes.NotAvailable:
        raise MoneyHubError("disputes_unavailable", "Disputes aren't set up for this app yet.", 503)
    except disputes.DisputeError as error:
        raise MoneyHubError(error.code, error.message, error.status)


def _app_page() -> dict:
    return _response(200, (WEB_DIR / "index.html").read_text(encoding="utf-8"), "text/html")


def _asset(name: str) -> dict:
    path = (WEB_DIR / name).resolve()
    if not (ASSET.match(name) and path.is_relative_to(WEB_DIR.resolve()) and path.is_file()):
        return _response(404, "Not found", "text/plain")
    return _response(200, path.read_text(encoding="utf-8"), TYPES[name.rsplit(".", 1)[1]])


def _touchpoint(name: str) -> dict:
    path = WEB_DIR / "vendor" / "touchpoint" / name
    if not (TOUCHPOINT_FILE.match(name) and path.is_file()):
        return _response(404, "Not found", "text/plain")
    return _response(200, path.read_text(encoding="utf-8"), "text/javascript")


def web(event: dict) -> dict:
    method = event["requestContext"]["http"].get("method", "")
    path = (event.get("rawPath") or "/").rstrip("/") or "/"
    if method == "GET":
        if path in APP_PATHS:
            return _app_page()
        if path.startswith("/assets/"):
            return _asset(path.removeprefix("/assets/"))
        if path.startswith("/vendor/touchpoint/"):
            return _touchpoint(path.removeprefix("/vendor/touchpoint/"))
        return _response(404, "Not found", "text/plain")
    if method != "POST" or not path.startswith("/api/"):
        return _response(404, "Not found", "text/plain")
    if path in MONEY_HUB_ROUTES:                     # the Money Hub's own answers, with this app's headers
        answered = money_api.web(event)
        return {**answered, "headers": {**answered["headers"], **SECURITY_HEADERS}}
    try:
        body = _body(event)
        token = _s(body, "token")
        session = money_api.hub.link_session(token)    # the page's own secret; nothing else names a customer
        customer = session["customerId"]
        if path == "/api/app/home":
            reply = {**home.home(money_api.hub, customer), "talk": bool(money_api.CONNECT_INSTANCE_ID and money_api.CONTACT_FLOW_ID),
                     "avatar": money_api.avatar_on(), "verified": journeys.money_hub.verified_level(session["loa"]),
                     "disputePagesUrl": DISPUTE_PAGES_URL, "flowView": flowview.enabled()}
        elif path == "/api/app/accounts":
            wanted = _s(body, "account") if _s(body, "account") in home.ACCOUNT_PAGES else "current"
            history = home.account_history(money_api.hub, customer, wanted, 12)
            reply = {**home.accounts(money_api.hub, customer), "selected": history["selected"],
                     "recent": history["transactions"]}
        elif path == "/api/app/cards":
            reply = home.cards(customer)
        elif path in ("/api/contact/call", "/api/contact/chat"):
            reply = start_contact(path.rsplit("/", 1)[-1], session, body, token)
        elif path == "/api/contact/returned":
            reply = returned_note(body, token)
        elif path == "/api/contact/page":
            reply = page_moved(session, body, token)
        elif path == "/api/contact/assistant":
            reply = contact_assistant(body, token)
        elif path == "/api/contact/journey":
            reply = contact_journey(customer, _s(body, "contactId"), token)
        elif path == "/api/mortgage/config":
            reply = partners.mortgage_config(REGION, money_api.CONNECT_INSTANCE_ID, PRODUCTS)
        elif path == "/api/mortgage/help-code":
            reply = partners.mortgage("createHelpCode", {"applicationId": _s(body, "applicationId"), "stage": _s(body, "stage")})
        elif path == "/api/mortgage/help-code/status":
            reply = partners.mortgage("helpCodeStatus", {"helpSessionId": _s(body, "helpSessionId")})
        elif path == "/api/mortgage/submit":
            # The declaration as the mortgage service checks it (its own page door makes the same from `declared`):
            # accepted only when the page saw the customer's own click.
            clicked = body.get("declared") is True
            reply = partners.mortgage("submitApplication", {
                "applicationId": _s(body, "applicationId"), "productId": _s(body, "productId"),
                "dipDecision": _s(body, "dipDecision") or None,
                "declaration": {"accepted": True, "source": "customer_click"} if clicked else {"accepted": False, "source": "page"},
                "documents": [d for d in body.get("documents") or [] if d in ("payslips", "bank_statement", "photo_id")]})
        elif path == "/api/dispute/config":
            reply = {**partners.dispute_config(REGION, money_api.CONNECT_INSTANCE_ID), "pagesUrl": DISPUTE_PAGES_URL}
        elif path in ("/api/disputes", "/api/disputes/live", "/api/disputes/open", "/api/disputes/submit"):
            reply = dispute_route(path, customer, body, token, bool(journeys.money_hub.verified_level(session["loa"])))
        elif path.startswith("/api/dispute/screen/"):
            screen = {k: body[k] for k in ("sessionId", "linkToken", "fields") if k in body}
            reply = partners.dispute_screen(path.rsplit("/", 1)[-1], screen)
        else:
            return _response(404, "Not found", "text/plain")
        status, outcome = 200, "ok"
    except (MoneyHubError, partners.PartnerError) as error:
        reply, status, outcome = {"error": error.code, "message": error.message}, error.status, error.code
    except Exception:
        logger.exception("route=%s failed", path)
        reply, status, outcome = {"error": "error", "message": "Something went wrong. Try again."}, 500, "error"
    logger.info("route=%s status=%s outcome=%s", path, status, outcome)      # never the body or a token
    return _json(status, reply)


def lambda_handler(event: dict, context: Any) -> dict:
    event = event if isinstance(event, dict) else {}
    if isinstance(event.get("requestContext"), dict) and "http" in event["requestContext"]:
        return web(event)
    # A direct invoke from the deploy script, for a demo link (the Money Hub's own internal route: the link opens
    # this app, because PUBLIC_BASE_URL is this app's address). Nothing on the web can reach it.
    if event.get("operation") == "mint_link":
        return money_api.lambda_handler(event, context)
    return {"error": "not_supported"}
