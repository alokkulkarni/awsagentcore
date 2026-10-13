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

WHY this Lambda also chooses the AI agent
-----------------------------------------
A contact has ONE assistant session for its whole life. The bot flow creates it
and sets ARIA as its agent. A later "Connect assistant" block returns that same
session and does NOT change its agent, so without help the human agent's panel
is driven by ARIA's customer-facing agent and stays silent.

So this Lambda switches the session to the agent-assist AI agent itself
(UpdateSession), before writing the briefing. The agent to use is passed by the
flow as the Lambda parameter "assistAgentArn", so the version is pinned in one
place: the flow.

WHAT this Lambda reads (contact attributes)
-------------------------------------------
    customerId, channel                      set by the main flow's injector
    LoA, idvMethod                           set by an ID&V flow, if one ran
    ariaSummary, ariaCustomerIntent,
    ariaTopicCategory, ariaEscalationReason  set by "ARIA human handover"
    conversationSummary, customerIntent,
    topicCategory, escalationReason          fallbacks, set by the main flow

Only attributes set by a flow or a Lambda are read. Attributes a chat customer's
browser can set arrive prefixed "HostedWidget-" and are ignored, because every
value here states who the customer is or how far they were verified.

paymentApproved is taken from the opening words of ARIA's summary, which ARIA
writes. It is a signal for the agent, not proof: the prompt tells the assistant
to have the agent read the payee and amount back to the customer first.

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

THE ARRIVAL BRIEFING (a second way this Lambda is called)
--------------------------------------------------------
The agent's screen-pop flow calls this Lambda with the parameter
operation = "brief" when the agent accepts the contact. It then asks the
assistant for a briefing on the agent's behalf (SendMessage), so the agent does
not have to type anything and does not have to wait for the customer to speak.

ENVIRONMENT VARIABLES
---------------------
Required:
    ASSISTANT_ID       Q Connect assistant ID
Optional:
    BRIEFING_DELAY_SECONDS  Seconds to wait before asking for the arrival
                         briefing, so the agent's panel is open. Default 2
    INSTANCE_ID          Connect instance ID; derived from the event if not set
    ASSIST_AI_AGENT_ARN  Agent-assist AI agent version ARN, used only when the
                         flow does not pass the "assistAgentArn" parameter
    LOG_LEVEL          Default INFO

IAM PERMISSIONS REQUIRED
------------------------
    connect:DescribeContact      on the Connect instance and its contacts
    wisdom:UpdateSession         on the assistant and its sessions
    wisdom:SendMessage           on the assistant and its sessions
    wisdom:UpdateSessionData     on the assistant and its sessions
    qconnect:UpdateSessionData   (same resources; the newer action name)
"""

import json
import logging
import os
import time
from typing import Any

import session_injector_qconnect as injector

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "")
SESSION_VALUE_MAX_CHARS = injector.SESSION_VALUE_MAX_CHARS
MAX_REASONS = injector.MAX_CONTACT_REASONS
ASSIST_AI_AGENT_ARN: str = os.environ.get("ASSIST_AI_AGENT_ARN", "")

BRIEFING_DELAY_SECONDS: float = float(os.environ.get("BRIEFING_DELAY_SECONDS", "2"))

# Sent to the assistant as the agent's first question when they accept a contact.
ARRIVAL_BRIEFING_REQUEST = (
    "I have just accepted this contact and nobody has spoken yet. Brief me before I speak. "
    "Look up the details of the product the customer is contacting us about, and look up our "
    "guidance for that topic. Then tell me: what to do first; what ARIA already did; how the "
    "customer was verified and what that allows; the key details of that product; the likely "
    "reasons for the contact; and the related guidance I can open."
)

# The use case Connect records for the agent a human agent's panel talks to.
AGENT_ASSISTANCE_USE_CASE = "Connect.AgentAssistance"

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
        # Exact names only. Every value read here says who the customer is or
        # how far they were verified, so it must have been set by a flow or a
        # Lambda. Attributes a chat customer's browser can set arrive with a
        # "HostedWidget-" prefix and are deliberately NOT read.
        for name in names:
            value = attrs.get(name)
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


def _signed_post(path: str, body: dict) -> None:
    """
    A signed HTTPS call to the assistant service, for a Lambda runtime whose
    bundled SDK is older than the parameter being sent.
    """
    import urllib.request

    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    region = injector.AWS_REGION
    url = f"https://wisdom.{region}.amazonaws.com/assistants/{ASSISTANT_ID}/sessions/{path}"
    request = AWSRequest(method="POST", url=url, data=json.dumps(body),
                         headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "wisdom", region).add_auth(request)
    with urllib.request.urlopen(urllib.request.Request(
            url, data=request.body.encode(), headers=dict(request.headers), method="POST"), timeout=5):
        pass


def _call_assistant(method: str, session_id: str, path: str, body: dict) -> None:
    """Call the SDK method, falling back to a signed request when the SDK is too old for the body."""
    try:
        getattr(injector._get_qconnect(), method)(assistantId=ASSISTANT_ID, sessionId=session_id, **body)
    except Exception as error:
        if type(error).__name__ != "ParamValidationError":
            raise
        logger.info("The runtime's SDK does not accept this %s request. Using a signed request.", method)
        _signed_post(path, body)


def assign_assist_agent(session_arn: str, agent_arn: str) -> bool:
    """
    Make the agent-assist AI agent the one that drives this session.

    Returns True when the session was switched. Never raises: a contact whose
    agent could not be switched must still reach a person.
    """
    session_id = session_arn.split("/")[-1]
    body = {"orchestratorConfigurationList": [
        {"aiAgentId": agent_arn, "orchestratorUseCase": AGENT_ASSISTANCE_USE_CASE}]}
    try:
        _call_assistant("update_session", session_id, session_id, body)
    except Exception:
        logger.exception("Could not switch session %s to AI agent %s. Check the wisdom:UpdateSession "
                         "permission on this Lambda's role.", session_id, agent_arn)
        return False
    logger.info("Session %s now uses AI agent %s", session_id, agent_arn)
    return True


def request_arrival_briefing(session_arn: str, contact_id: str) -> bool:
    """
    Ask the assistant for a briefing on the agent's behalf, the moment the agent
    accepts the contact.

    Left alone, the assistant only speaks once the customer has said something
    to the agent, or the agent has typed a question. This sends that first
    question for them, so the briefing, the product details and the related
    guidance are on screen before anyone speaks. Never raises.
    """
    session_id = session_arn.split("/")[-1]
    body = {"type": "TEXT", "message": {"value": {"text": {"value": ARRIVAL_BRIEFING_REQUEST}}},
            "orchestratorUseCase": AGENT_ASSISTANCE_USE_CASE,
            # The same token for the same contact, so a repeated screen pop
            # cannot ask twice.
            "clientToken": f"arrival-briefing-{contact_id}"}
    try:
        if BRIEFING_DELAY_SECONDS:
            time.sleep(BRIEFING_DELAY_SECONDS)   # give the agent's panel time to open
        _call_assistant("send_message", session_id, f"{session_id}/message", body)
    except Exception:
        logger.exception("Could not request the arrival briefing for session %s. Check the "
                         "wisdom:SendMessage permission on this Lambda's role.", session_id)
        return False
    logger.info("Arrival briefing requested for contact %s", contact_id)
    return True


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

    parameters: dict = (event.get("Details") or {}).get("Parameters") or {}
    agent_arn: str = parameters.get("assistAgentArn") or ASSIST_AI_AGENT_ARN
    agent_status = "not_configured"

    def reply(status: str, keys: list[str] | None = None) -> dict:
        return {"status": status, "assistAgent": agent_status, "injectedKeys": ",".join(keys or [])}

    if not ASSISTANT_ID:
        logger.error("ASSISTANT_ID is not set. Set it to the Q Connect assistant ID.")
        return reply("error_missing_assistant_id")
    if not contact_id:
        logger.error("ContactId is missing from the event.")
        return reply("error_missing_contact_id")

    if parameters.get("operation") == "brief":
        # Called from the agent's screen-pop flow, when the agent accepts.
        try:
            session_arn = injector._resolve_wisdom_session_id(instance_id, contact_id)
            if session_arn == contact_id:
                logger.error("No assistant session on contact %s. No briefing requested.", contact_id)
                return reply("error_no_assistant_session")
            asked = request_arrival_briefing(session_arn, contact_id)
        except Exception:
            logger.exception("Arrival briefing failed for contact %s", contact_id)
            return reply("error_exception")
        return reply("briefing_requested" if asked else "briefing_failed")

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
        if agent_arn:
            agent_status = "set" if assign_assist_agent(session_arn, agent_arn) else "failed"
        else:
            logger.warning("No agent-assist AI agent was passed (Lambda parameter assistAgentArn). "
                           "The agent's panel will keep using the session's existing AI agent.")
        injected = injector._inject_session_data(ASSISTANT_ID, session_arn, data)
    except Exception:
        logger.exception("Agent assist context injection failed for contact %s", contact_id)
        return reply("error_exception")

    keys = sorted(key for key, value in data.items() if value)
    logger.info(json.dumps({"contactId": contact_id, "status": "injected" if injected else "partial_failure",
                            "assistAgent": agent_status, "customerId": data.get("customerId", ""), "keys": keys}))
    return reply("injected" if injected else "partial_failure", keys)
