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

THE ARRIVAL BRIEFING
--------------------
The agent wants the briefing, the product details and the related guidance on
screen when the contact arrives, without typing. The assistant's own panel
cannot do that: it shows only answers to questions typed into it, and
suggestions the agent clicks after the customer has spoken.

So, after writing the session data, this Lambda starts a second run of itself in
the background. That run asks the assistant the opening question, waits for the
answer (about twenty seconds) and stores it in the contact attribute
"assistBriefing". The agent's screen pop shows that attribute.

ENVIRONMENT VARIABLES
---------------------
Required:
    ASSISTANT_ID       Q Connect assistant ID
Optional:
    BRIEFING_ENABLED     "false" switches the arrival briefing off
    INSTANCE_ID          Connect instance ID; derived from the event if not set
    ASSIST_AI_AGENT_ARN  Agent-assist AI agent version ARN, used only when the
                         flow does not pass the "assistAgentArn" parameter
    LOG_LEVEL          Default INFO

IAM PERMISSIONS REQUIRED
------------------------
    connect:DescribeContact      on the Connect instance and its contacts
    wisdom:UpdateSession         on the assistant and its sessions
    wisdom:SendMessage           on the assistant and its sessions
    wisdom:ListMessages          on the assistant and its sessions
    connect:UpdateContactAttributes  on the instance's contacts
    lambda:InvokeFunction        on this function (to start its background run)
    wisdom:UpdateSessionData     on the assistant and its sessions
    qconnect:UpdateSessionData   (same resources; the newer action name)
"""

import html
import json
import logging
import os
import re
import time
from typing import Any

import session_injector_qconnect as injector

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "")
SESSION_VALUE_MAX_CHARS = injector.SESSION_VALUE_MAX_CHARS
MAX_REASONS = injector.MAX_CONTACT_REASONS
ASSIST_AI_AGENT_ARN: str = os.environ.get("ASSIST_AI_AGENT_ARN", "")

# The arrival briefing: the assistant's answer to one opening question, stored
# on the contact for the agent's screen pop.
BRIEFING_ENABLED: bool = os.environ.get("BRIEFING_ENABLED", "true").lower() != "false"
BRIEFING_ATTRIBUTE = "assistBriefing"
BRIEFING_WAIT_SECONDS = 45
BRIEFING_POLL_SECONDS = 1.5
BRIEFING_MAX_CHARS = 4000
BRIEFING_PENDING_TEXT = "The assistant is preparing the briefing. Press **Refresh** in a few seconds."
BRIEFING_FAILED_TEXT = "The assistant could not prepare a briefing for this contact. Ask it in the Connect assistant panel."
ARRIVAL_BRIEFING_REQUEST = (
    "I am about to take this contact and nobody has spoken to the customer yet. Brief me before I speak. "
    "Look up the details of the product the customer is contacting us about, and look up our "
    "guidance for that topic. Then tell me: what to do first; what ARIA already did; how the "
    "customer was verified and what that allows; the key details of that product; the likely "
    "reasons for the contact; and the related guidance."
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


def _signed_post(path: str, body: dict) -> dict:
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
            url, data=request.body.encode(), headers=dict(request.headers), method="POST"), timeout=5) as response:
        return json.loads(response.read() or b"{}")


def _call_assistant(method: str, session_id: str, path: str, body: dict) -> dict:
    """Call the SDK method, falling back to a signed request when the SDK is too old for the body."""
    try:
        return getattr(injector._get_qconnect(), method)(assistantId=ASSISTANT_ID, sessionId=session_id, **body)
    except Exception as error:
        if type(error).__name__ != "ParamValidationError":
            raise
        logger.info("The runtime's SDK does not accept this %s request. Using a signed request.", method)
        return _signed_post(path, body)


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


def briefing_to_markdown(answer: str) -> str:
    """
    Turn the assistant's answer into the Markdown a screen-pop view can show.

    The assistant writes for its own panel: light HTML, stored with the angle
    brackets escaped, plus a wrapper naming the documents it drew on.
    """
    text = html.unescape(html.unescape(answer))
    text = re.sub(r"<sources>.*?</sources>", "", text, flags=re.S)
    for pattern, replacement in ((r"</?(b|strong)>", "**"), (r"</?(i|em)>", "*"), (r"<br\s*/?>", "\n"),
                                 (r"<li>", "\n- "), (r"</(ul|ol|p)>", "\n\n"), (r"<[^>]+>", "")):
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:BRIEFING_MAX_CHARS]


def _briefing_answer(session_id: str, request_id: str) -> str:
    """The assistant's answer to our request, or "" while it is still working."""
    messages = injector._get_qconnect().list_messages(
        assistantId=ASSISTANT_ID, sessionId=session_id).get("messages", [])
    asked_at = next((m["timestamp"] for m in messages if m.get("messageId") == request_id), None)
    if asked_at is None:
        return ""
    replies = [((m.get("value") or {}).get("text") or {}).get("value", "") for m in messages
               if m.get("participant") == "BOT" and m["timestamp"] > asked_at]
    replies = [reply for reply in replies if reply.strip()]
    # The assistant sends a one-line lead first, then the answer. The answer is
    # the one with formatting in it; a second reply also means it has arrived.
    formatted = [reply for reply in replies if "&lt;" in reply or "<" in reply]
    if formatted or len(replies) >= 2:
        return max(formatted or replies, key=len)
    return ""


def _set_briefing_attribute(instance_id: str, contact_id: str, text: str) -> None:
    injector._get_connect().update_contact_attributes(
        InstanceId=instance_id, InitialContactId=contact_id, Attributes={BRIEFING_ATTRIBUTE: text})


def prepare_briefing(instance_id: str, contact_id: str, session_arn: str) -> str:
    """
    Ask the assistant for a briefing and store its answer on the contact, where
    the agent's screen pop shows it.

    Runs on its own, in the background, while the customer waits in the queue:
    the assistant needs about twenty seconds to look things up and write. The
    assistant's own panel cannot be used for this. It only displays answers to
    questions the agent typed into it.
    """
    session_id = session_arn.split("/")[-1]
    _set_briefing_attribute(instance_id, contact_id, BRIEFING_PENDING_TEXT)
    sent = _call_assistant("send_message", session_id, f"{session_id}/message", {
        "type": "TEXT", "message": {"value": {"text": {"value": ARRIVAL_BRIEFING_REQUEST}}},
        "orchestratorUseCase": AGENT_ASSISTANCE_USE_CASE,
        "clientToken": f"arrival-briefing-{contact_id}"})   # one briefing per contact
    deadline = time.monotonic() + BRIEFING_WAIT_SECONDS
    answer = ""
    while not answer and time.monotonic() < deadline:
        time.sleep(BRIEFING_POLL_SECONDS)
        answer = _briefing_answer(session_id, sent.get("requestMessageId", ""))
    text = briefing_to_markdown(answer) if answer else BRIEFING_FAILED_TEXT
    _set_briefing_attribute(instance_id, contact_id, text)
    logger.info(json.dumps({"contactId": contact_id, "status": "briefing_ready" if answer else "briefing_timed_out",
                            "characters": len(text)}))
    return text


def _start_briefing_worker(context: Any, instance_id: str, contact_id: str, session_arn: str) -> bool:
    """Start prepare_briefing in a second, background run of this Lambda. Never raises."""
    try:
        import boto3
        boto3.client("lambda", region_name=injector.AWS_REGION).invoke(
            FunctionName=context.invoked_function_arn, InvocationType="Event",
            Payload=json.dumps({"operation": "prepare_briefing", "instanceId": instance_id,
                                "contactId": contact_id, "sessionArn": session_arn}).encode())
        return True
    except Exception:
        logger.exception("Could not start the briefing for contact %s. Check the lambda:InvokeFunction "
                         "permission on this Lambda's role.", contact_id)
        return False


def handler(event: dict, context: Any) -> dict:
    """
    Entry point. Called by Amazon Connect via the "Invoke AWS Lambda function"
    block. Never raises: a failure here must not stop the customer reaching an
    agent, so the flow continues whatever this returns.
    """
    if event.get("operation") == "prepare_briefing":
        # The background run started by _start_briefing_worker, not Connect.
        try:
            prepare_briefing(event["instanceId"], event["contactId"], event["sessionArn"])
        except Exception:
            logger.exception("Briefing failed for contact %s", event.get("contactId"))
        return {"status": "done"}

    contact: dict = (event.get("Details") or {}).get("ContactData") or {}
    contact_id: str = contact.get("ContactId", "")
    instance_id: str = os.environ.get("INSTANCE_ID", "") or contact.get("InstanceARN", "").split("instance/")[-1]
    channel = "chat" if (contact.get("Channel") or "VOICE").upper() in ("CHAT", "TASK") else "voice"

    parameters: dict = (event.get("Details") or {}).get("Parameters") or {}
    agent_arn: str = parameters.get("assistAgentArn") or ASSIST_AI_AGENT_ARN
    agent_status, briefing_status = "not_configured", "not_started"

    def reply(status: str, keys: list[str] | None = None) -> dict:
        return {"status": status, "assistAgent": agent_status, "briefing": briefing_status,
                "injectedKeys": ",".join(keys or [])}

    if not ASSISTANT_ID:
        logger.error("ASSISTANT_ID is not set. Set it to the Q Connect assistant ID.")
        return reply("error_missing_assistant_id")
    if not contact_id:
        logger.error("ContactId is missing from the event.")
        return reply("error_missing_contact_id")

    if parameters.get("operation") == "brief":
        # An earlier version was called from the screen-pop flow like this.
        logger.info("Ignoring the retired 'brief' operation. Remove that Lambda block from the screen-pop flow.")
        return reply("ignored")

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
        # Only once the session has the right agent and the briefing data.
        if agent_status == "set" and injected and BRIEFING_ENABLED:
            started = _start_briefing_worker(context, instance_id, contact_id, session_arn)
            briefing_status = "started" if started else "failed"
    except Exception:
        logger.exception("Agent assist context injection failed for contact %s", contact_id)
        return reply("error_exception")

    keys = sorted(key for key, value in data.items() if value)
    logger.info(json.dumps({"contactId": contact_id, "status": "injected" if injected else "partial_failure",
                            "assistAgent": agent_status, "briefing": briefing_status, "customerId": data.get("customerId", ""), "keys": keys}))
    return reply("injected" if injected else "partial_failure", keys)
