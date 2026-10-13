"""
aria_agent_assist_injector.py
=============================
ARIA Agent Assist Context Injector Lambda.

Gives the agent-assist AI agent (the assistant a human agent sees in the agent
workspace) a head start on a contact: who the customer is, how well they were
verified, what ARIA already did, why the contact was handed over, and what the
bank already knows about why they may be getting in touch.

Without it, the assist agent starts cold. It can read the live transcript but
knows nothing about the conversation the customer just had with ARIA.

WHY a separate Lambda
---------------------
aria-session-injector-qconnect serves ARIA, the customer-facing bot. This one
serves the human agent's assistant. They write to different assistant sessions,
for different readers, with different disclosure rules:

    ARIA's injector        the reader talks to the CUSTOMER. Known contact
                           reasons are withheld unless the customer is verified.
    This injector          the reader advises a member of STAFF. Everything is
                           passed, together with the verification level, so the
                           assistant can tell the agent to check identity first.

The customer data itself is not copied here. It is imported from
session_injector_qconnect.py, so both Lambdas describe the same test customers.

Contact flow placement
----------------------
    [Set recording and analytics behavior]
        ↓
    [Connect assistant]            ← creates the agent-assist session
        ↓
    [Set contact data]             ← stores that session on the contact
        ↓
    [Invoke Lambda: aria-agent-assist-injector]   ← this Lambda
        ↓ Success or Error
    [Set event flow] → [Transfer to queue]

It MUST run after "Connect assistant" and "Set contact data": it finds the
session to write to by asking Connect for the contact's current assistant
session.

WHAT this Lambda reads (contact attributes)
-------------------------------------------
    customerId, channel                      set by the main flow's injector
    LoA, idvMethod                           set by an ID&V flow, if one ran
    ariaSummary, ariaCustomerIntent,
    ariaTopicCategory, ariaEscalationReason  set by "ARIA human handover"
    conversationSummary, customerIntent,
    topicCategory, escalationReason          fallbacks, set by the main flow

WHAT this Lambda injects ({{$.Custom.*}} in the agent-assist prompt)
--------------------------------------------------------------------
    customerId            Customer ID, for the assistant's look-up tools
    preferredName         Customer's preferred first name
    productSummary        One sentence describing the customer's products
    vulnerabilityContext  JSON of vulnerability flags, or empty
    verification          Plain-English statement of how the customer was verified
    paymentApproved       "true" when ARIA completed a payment approval in the app
    ariaSummary           ARIA's summary of the conversation so far
    ariaCustomerIntent    What the customer was trying to do
    ariaTopicCategory     Topic used for routing
    ariaEscalationReason  Why ARIA handed over
    knownContactReasons   What the bank already knows may be behind the contact
    channel               "voice" | "chat"

ENVIRONMENT VARIABLES
---------------------
Required:
    ASSISTANT_ID       Q Connect assistant ID
Optional:
    INSTANCE_ID        Connect instance ID; derived from the event if not set
    LOG_LEVEL          Default INFO

IAM PERMISSIONS REQUIRED
------------------------
    connect:DescribeContact      on the Connect instance and its contacts
    wisdom:UpdateSessionData     on the assistant and its sessions
    qconnect:UpdateSessionData   (same resources; the newer action name)
"""

import json
import logging
import os
from typing import Any

import session_injector_qconnect as injector

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "")
SESSION_VALUE_MAX_CHARS = injector.SESSION_VALUE_MAX_CHARS
MAX_REASONS = injector.MAX_CONTACT_REASONS

# ARIA starts its escalation summary with this when a payment was approved in
# the app (see the "Level 4" step-up in ARIA's orchestration prompt).
PAYMENT_APPROVED_MARKER = "level 4 payment step-up passed"

_METHOD_WORDS = {
    "push": "an approval in the banking app",
    "app_handoff": "an in-app call from a signed-in session",
    "sca": "an approval in the banking app",
    "dial_code": "an app dial code",
    "chat_session": "a signed-in chat session",
    "otp_sms": "a one-time code by text",
    "otp_email": "a one-time code by email",
    "kba": "security questions",
    "kba+otp_sms": "a one-time code by text and security questions",
    "test_quick_select": "the test harness quick-select (no real check)",
}


def describe_verification(loa: int | None, method: str) -> str:
    """
    How the customer was verified, in words a human agent can act on.

    The assistant shows this to staff, never to the customer. It always ends in
    an instruction so the agent knows whether to check identity themselves.
    """
    how = _METHOD_WORDS.get(method, method.replace("_", " ")) if method else ""
    if method == "cli_match":
        return ("Recognised by phone number only. Nobody has checked who is holding the phone. "
                "Verify identity before discussing the account.")
    if loa is None:
        return "No identity check has been recorded for this contact. Verify identity before discussing the account."
    if loa >= 3:
        return f"Strongly verified by {how or 'the ID&V flow'}. No further identity check is needed for servicing."
    if loa == 2:
        return (f"Verified by one check ({how or 'the ID&V flow'}). Enough for account information, "
                "not for payments or changes to contact details.")
    return "Not verified. Verify identity before discussing the account."


def describe_contact_reasons(customer_id: str) -> str:
    """Every known reason for the customer, most likely first, for a member of staff."""
    reasons = injector._lookup_contact_reasons(customer_id)
    reasons.sort(key=lambda r: (r.get("priority", 9), r.get("days_ago", 999)))
    parts = []
    for index, reason in enumerate(reasons[:MAX_REASONS], start=1):
        sensitive = " [sensitive: confirm identity before raising]" if reason.get("min_loa", 2) >= 3 else ""
        parts.append(f"({index}) {reason['label']}: {reason['detail']}{sensitive}")
    return "; ".join(parts)


def build_context(attrs: dict, channel: str) -> dict[str, str]:
    """The key/value pairs to inject, built only from contact attributes and the customer record."""
    def attr(*names: str) -> str:
        for name in names:
            value = attrs.get(name) or attrs.get(f"HostedWidget-{name}")
            if value:
                return str(value)
        return ""

    customer_id = attr("customerId")
    method = attr("idvMethod")
    loa = injector._parse_loa(attr("LoA", "loa"))
    summary = attr("ariaSummary", "conversationSummary")

    context = {
        "customerId": customer_id,
        "channel": channel,
        "verification": describe_verification(loa, method),
        "paymentApproved": "true" if summary.lower().startswith(PAYMENT_APPROVED_MARKER) else "false",
        "ariaSummary": summary,
        "ariaCustomerIntent": attr("ariaCustomerIntent", "customerIntent"),
        "ariaTopicCategory": attr("ariaTopicCategory", "topicCategory"),
        "ariaEscalationReason": attr("ariaEscalationReason", "escalationReason"),
    }

    customer = injector._lookup_customer(customer_id) if customer_id else None
    if customer:
        context.update({
            "preferredName": customer.get("preferred_name", ""),
            "productSummary": injector._build_product_summary(customer),
            "vulnerabilityContext": injector._build_vulnerability_context(customer),
            "knownContactReasons": describe_contact_reasons(customer_id),
        })
    elif customer_id:
        logger.warning("Customer %r not found. Injecting the handover details only.", customer_id)

    return {key: value[:SESSION_VALUE_MAX_CHARS] for key, value in context.items()}


def handler(event: dict, context: Any) -> dict:
    """
    Entry point. Called by Amazon Connect via the "Invoke AWS Lambda function"
    block. Never raises: a failure here must not stop the customer reaching an
    agent, so the flow continues whatever this returns.
    """
    contact: dict = (event.get("Details") or {}).get("ContactData") or {}
    contact_id: str = contact.get("ContactId", "")
    instance_id: str = os.environ.get("INSTANCE_ID", "") or contact.get("InstanceARN", "").split("instance/")[-1]
    channel = "chat" if (contact.get("Channel") or "VOICE").upper() in ("CHAT", "TASK") else "voice"

    def reply(status: str, keys: list[str] | None = None) -> dict:
        return {"status": status, "injectedKeys": ",".join(keys or [])}

    if not ASSISTANT_ID:
        logger.error("ASSISTANT_ID is not set. Set it to the Q Connect assistant ID.")
        return reply("error_missing_assistant_id")
    if not contact_id:
        logger.error("ContactId is missing from the event.")
        return reply("error_missing_contact_id")

    try:
        data = build_context(contact.get("Attributes") or {}, channel)
        session_arn = injector._resolve_wisdom_session_id(instance_id, contact_id)
        if session_arn == contact_id:
            # _resolve_wisdom_session_id returns the contact ID when the contact
            # has no assistant session, which means this ran before the
            # "Connect assistant" and "Set contact data" blocks.
            logger.error("No assistant session on contact %s. Place this Lambda after "
                         "'Connect assistant' and 'Set contact data'.", contact_id)
            return reply("error_no_assistant_session")
        injected = injector._inject_session_data(ASSISTANT_ID, session_arn, data)
    except Exception:
        logger.exception("Agent assist context injection failed for contact %s", contact_id)
        return reply("error_exception")

    keys = sorted(key for key, value in data.items() if value)
    logger.info(json.dumps({"contactId": contact_id, "status": "injected" if injected else "partial_failure",
                            "customerId": data.get("customerId", ""), "keys": keys}))
    return reply("injected" if injected else "partial_failure", keys)
