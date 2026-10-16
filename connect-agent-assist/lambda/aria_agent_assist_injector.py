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
    customerId, channel, authStatus          set by the main flow's injector
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
suggestions the agent clicks after the customer has spoken. So the briefing is
shown in the agent's screen pop, in two steps:

    1. After writing the session data, this Lambda asks the opening question
       (SendMessage) and returns at once. The answer is written while the
       customer is in the queue. If the flow passes the Lambda parameter
       "briefingAgentArn", a small, fast AI agent answers. Otherwise the
       agent-assist agent does, which takes about twenty seconds.
    2. The screen-pop flow calls this Lambda with the parameter
       operation = "get_briefing". It reads the assistant's answer from the
       session and returns the lines the view shows: first, verification,
       reason1-2, product1-3, guidance1-2. "Refresh briefing" calls it again.

Nothing is stored on the contact. The screen pop runs under its own contact ID,
so it could not rely on attributes set on the original contact after it opened;
the session is shared by both.

ENVIRONMENT VARIABLES
---------------------
Required:
    ASSISTANT_ID       Q Connect assistant ID
Optional:
    BRIEFING_ENABLED     "false" switches the arrival briefing off
    DISPUTE_FUNCTION_NAME  The card dispute Lambda, if deployed. The screen pop
                         then shows a customer's open dispute and a link to it
    LIVESYNC_FUNCTION_NAME Live Sync's main Lambda, if it can save applications.
                         The screen pop then shows the mortgage form the
                         customer has filled in, for a contact that carries
                         its applicationId
    BRIEFING_AI_AGENT_ARN  The fast briefing AI agent's version ARN, used only
                         when the flow does not pass "briefingAgentArn"
    CLI_MATCH_LOA        The level ARIA's injector gives a caller recognised by
                         phone number alone. Copied from that Lambda by the
                         deploy script, so the agent is told what ARIA was told
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
    lambda:InvokeFunction        on the card dispute Lambda and on Live Sync's
                                 main Lambda, when they are deployed
    wisdom:UpdateSessionData     on the assistant and its sessions
    qconnect:UpdateSessionData   (same resources; the newer action name)
"""

import html
import json
import logging
import os
import re
from typing import Any

import session_injector_qconnect as injector

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "")
SESSION_VALUE_MAX_CHARS = injector.SESSION_VALUE_MAX_CHARS
MAX_REASONS = injector.MAX_CONTACT_REASONS
ASSIST_AI_AGENT_ARN: str = os.environ.get("ASSIST_AI_AGENT_ARN", "")
# Must match CLI_MATCH_LOA on aria-session-injector-qconnect. The deploy script copies it.
CLI_MATCH_LOA: int | None = injector._parse_loa(os.environ.get("CLI_MATCH_LOA", ""))

# The arrival briefing: the assistant's answer to one opening question, which
# the agent's screen pop fetches through this Lambda.
BRIEFING_ENABLED: bool = os.environ.get("BRIEFING_ENABLED", "true").lower() != "false"
BRIEFING_AI_AGENT_ARN: str = os.environ.get("BRIEFING_AI_AGENT_ARN", "")
BRIEFING_FIELD_MAX_CHARS = 400
# How many bullet lines the screen pop's view has for each list.
BRIEFING_SLOTS = {"reason": 2, "product": 3, "guidance": 2}
BRIEFING_EMPTY_SLOT = "—"
# The card dispute Lambda (connect-card-dispute), asked whether the customer has
# an open dispute. Unset = that feature is not deployed; the screen pop says no.
DISPUTE_FUNCTION_NAME: str = os.environ.get("DISPUTE_FUNCTION_NAME", "")
DISPUTE_LINES = 6        # dispute1..6 in the screen pop: reference, payment, form, screen, cards, note
# Live Sync's main Lambda (connect-livesync-mortgage), asked for a saved mortgage
# application. Unset = not available; the screen pop shows a dash.
LIVESYNC_FUNCTION_NAME: str = os.environ.get("LIVESYNC_FUNCTION_NAME", "")
APPLICATION_LINES = 6
# The form is found by the application ID the contact carried, which on the web
# journey comes from the customer's browser. Nothing ties it to a verified customer.
APPLICATION_CAUTION = ("**Found by application ID, not by a verified customer:** confirm identity before "
                       "reading any of it back.")
_APPLICATION_ID = re.compile(r"MA-[A-Z0-9]{6,12}")
_APPLICATION_STAGES = {"about_you": "About you", "property_loan": "Property and loan",
                       "dip_result": "Decision in Principle", "product_selection": "Choosing a product",
                       "documents": "Documents", "review_submit": "Review and submit"}
_APPLICATION_FIELD_LABELS = {
    "fullName": "full name", "dateOfBirth": "date of birth", "employmentStatus": "employment",
    "annualIncome": "income", "commitmentsMonthly": "monthly commitments", "propertyValue": "property value",
    "deposit": "deposit", "termYears": "term", "buyerType": "buyer type",
    "dipDecision": "Decision in Principle", "productId": "product"}
_APPLICATION_DOCUMENTS = {"payslips": "payslips", "bank_statement": "bank statement", "photo_id": "photo ID"}
_EMPLOYMENT = {"employed": "employed", "self_employed": "self-employed", "other": "other employment"}
_BUYER = {"first_time": "first-time buyer", "home_mover": "home mover", "remortgage": "remortgage"}
BRIEFING_PENDING_TEXT = "*Still being prepared. Press Refresh briefing in a few seconds.*"
BRIEFING_FAILED_TEXT = "*Not available. Ask in the Connect assistant panel.*"
ARRIVAL_BRIEFING_REQUEST = (
    "I am about to take this contact and nobody has spoken to the customer yet. Brief me before I speak. "
    "Look up the details of the product the customer is contacting us about, and look up our guidance "
    "for that topic. Answer under exactly these three headings: What to do first (one sentence); "
    "Product details (three short bullets); Related guidance (two short bullets). Put the key figure "
    "or action in each in bold. I am the bank's adviser on this contact: under Related guidance tell me what "
    "the guidance means I should do or explain, and do not tell me the customer should call the bank, "
    "visit a branch or speak to an adviser."
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
    if method == "cli_match" and loa is not None and loa >= 2:
        # ARIA's injector was configured (CLI_MATCH_LOA) to treat a call from the
        # customer's registered number as this level, and ARIA served them at it.
        return (f"Verified by one check (ARIA recognised the customer's registered phone number and treated "
                f"them as Level {loa}; no app approval or security questions were completed). Enough for "
                "account information, not for payments or changes to contact details until you have "
                "completed your own further verification.")
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


def verification_headline(loa: int | None, method: str) -> str:
    """
    The verification position as one line an agent can take in at a glance on
    the screen pop. Says the same as describe_verification, in fewer words.
    """
    how = _METHOD_WORDS.get(method, method.replace("_", " ")) if method else ""
    if method == "cli_match" and loa is not None and loa >= 2:
        return (f"**Level {loa}, one check** (phone number recognised by ARIA). **OK:** account information. "
                "**Your own check first:** payments, changes of details.")
    if method == "cli_match" or loa is None or loa < 2:
        return "**Not verified.** **Verify identity first**, before discussing the account."
    if loa >= 3:
        return f"**Strongly verified** by {how or 'the ID&V flow'}. **No further check needed** for servicing."
    return (f"**Level 2, one check** ({how or 'the ID&V flow'}). **OK:** account information. "
            "**Your own check first:** payments, changes of details.")


def contact_reason_bullets(customer_id: str) -> list[str]:
    """The known reasons as bullet points for the screen pop, most likely first."""
    reasons = injector._lookup_contact_reasons(customer_id) if customer_id else []
    reasons.sort(key=lambda r: (r.get("priority", 9), r.get("days_ago", 999)))
    return [f"**{reason['label'][:1].upper()}{reason['label'][1:]}:** {reason['detail']}"
            + (" *(sensitive: confirm identity before raising)*" if reason.get("min_loa", 2) >= 3 else "")
            for reason in reasons[:MAX_REASONS]]


def resolve_verification(attrs: dict) -> tuple[int | None, str]:
    """The level and method to describe, from flow-set contact attributes only."""
    method = str(attrs.get("idvMethod") or "")
    loa = injector._parse_loa(str(attrs.get("LoA") or attrs.get("loa") or ""))
    if loa is None and not method and attrs.get("authStatus") == "authenticated" and CLI_MATCH_LOA is not None:
        # A direct call: no ID&V flow ran. ARIA's injector recognised the phone
        # number and told ARIA this level, so the agent is told the same.
        loa, method = CLI_MATCH_LOA, "cli_match"
    return loa, method


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
    loa, method = resolve_verification(attrs)
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
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def briefing_fields(markdown: str) -> dict[str, list[str]]:
    """
    Split the assistant's answer into the parts the screen pop shows. Keys:
    "first", "product", "guidance". Each value is a list of bullet points, one
    line each, with the assistant's **bold** kept so the view can show it.
    """
    def key_for(label: str) -> str:
        return next((key for key, words in (("first", ("first",)), ("guidance", ("guidance",)),
                                            ("product", ("product", "detail", "mortgage", "account", "card")))
                     if any(word in label.lower() for word in words)), "")

    parts: list[tuple[str, list[str]]] = []          # (key, bullets)
    for line in (line.strip() for line in markdown.split("\n")):
        if not line:
            continue
        bullet = line[2:] if line.startswith("- ") else line
        heading = re.match(r"^\*\*([^*]+?)\*\*(:?)\s*(.*)$", bullet)
        label = heading.group(1) if heading and (heading.group(2) or ":" in heading.group(1)) else ""
        key = key_for(label.split(":", 1)[0]) if label else ""
        # A bold lead-in only starts a new part when it names one we show and
        # is not the part we are already in. "- **Rate:** 4.25%" stays a bullet.
        if key and not (parts and parts[-1][0] == key):
            text = heading.group(3) or (label.split(":", 1)[1].strip() if ":" in label.rstrip(":") else "")
            parts.append((key, [text] if text else []))
        elif parts:
            parts[-1][1].append(bullet)
    fields: dict[str, list[str]] = {}
    for key, bullets in parts:
        bullets = [re.sub(r"\s+", " ", bullet.replace('"', "'")).strip(" ;")[:BRIEFING_FIELD_MAX_CHARS]
                   for bullet in bullets]
        bullets = [bullet for bullet in bullets if bullet]
        if bullets and key not in fields:
            fields[key] = bullets
    return fields


def _slots(name: str, bullets: list[str], count: int, when_empty: str) -> dict[str, str]:
    """
    Fit a list of bullets into the fixed lines the view has for them: name1,
    name2, ... A view cannot grow or shrink a list, so extra bullets share the
    last line and unused lines show a dash.
    """
    bullets = list(bullets) or [when_empty]
    if len(bullets) > count:
        bullets = bullets[:count - 1] + [" · ".join(bullets[count - 1:])]
    bullets += [BRIEFING_EMPTY_SLOT] * (count - len(bullets))
    return {f"{name}{number}": bullet for number, bullet in enumerate(bullets, start=1)}


def _briefing_answer(session_id: str) -> str:
    """The assistant's answer to the arrival request, or "" while it is still working."""
    messages = injector._get_qconnect().list_messages(
        assistantId=ASSISTANT_ID, sessionId=session_id).get("messages", [])

    def text(message: dict) -> str:
        return ((message.get("value") or {}).get("text") or {}).get("value", "")

    asked = [m["timestamp"] for m in messages if text(m) == ARRIVAL_BRIEFING_REQUEST]
    if not asked:
        return ""
    # While it works the assistant sends plain one-line progress notes. Only the
    # finished answer carries formatting, stored with its angle brackets escaped.
    answers = [text(m) for m in messages if m.get("participant") == "BOT" and m["timestamp"] > max(asked)
               and ("&lt;b&gt;" in text(m) or "<b>" in text(m))]
    return max(answers, key=len) if answers else ""


def request_arrival_briefing(session_arn: str, contact_id: str, briefing_agent: str = "") -> bool:
    """
    Ask the assistant, on the agent's behalf, for a briefing. Called as soon as
    the session has the right agent and data, while the customer is still in the
    queue, because the assistant needs time to look things up and write.
    Returns at once; get_briefing collects the answer. Never raises.

    `briefing_agent` names a small, fast AI agent to answer this one question
    (see prompts/agent-briefing-prompt-v1.yaml). Without it the session's own
    agent-assist agent answers, which takes about twenty seconds: its prompt is
    very long and it runs on a larger model.
    """
    session_id = session_arn.split("/")[-1]
    body = {"type": "TEXT", "message": {"value": {"text": {"value": ARRIVAL_BRIEFING_REQUEST}}},
            "orchestratorUseCase": AGENT_ASSISTANCE_USE_CASE,
            "clientToken": f"arrival-briefing-{contact_id}"}   # one briefing per contact
    if briefing_agent:
        body["aiAgentId"] = briefing_agent
    try:
        _call_assistant("send_message", session_id, f"{session_id}/message", body)
    except Exception:
        logger.exception("Could not request the arrival briefing for session %s. Check the "
                         "wisdom:SendMessage permission on this Lambda's role.", session_id)
        return False
    return True


def get_briefing(session_arn: str, attrs: dict, channel: str) -> dict[str, str]:
    """
    What the agent's screen pop shows, as the fixed set of lines its view has.
    Called by the screen-pop flow when the agent accepts, and again each time
    they press "Refresh briefing".

    Verification and likely reasons come from this Lambda, so they are always
    there and always the bank's own wording. The rest is the assistant's
    answer, read from the session, or a "still preparing" line.
    """
    customer_id = str(attrs.get("customerId") or "")
    found = briefing_fields(briefing_to_markdown(_briefing_answer(session_arn.split("/")[-1])))
    lines = {
        "first": " ".join(found.get("first", [])) or BRIEFING_PENDING_TEXT,
        "verification": verification_headline(*resolve_verification(attrs)),
        **_slots("reason", contact_reason_bullets(customer_id), BRIEFING_SLOTS["reason"], "None recorded."),
        **_slots("product", found.get("product", []), BRIEFING_SLOTS["product"], BRIEFING_PENDING_TEXT),
        **_slots("guidance", found.get("guidance", []), BRIEFING_SLOTS["guidance"], BRIEFING_PENDING_TEXT),
        "ready": "true" if found else "false",
        **card_dispute_lines(customer_id),
        **mortgage_application_lines(str(attrs.get("applicationId") or "")),
    }
    return lines


def card_dispute_lines(customer_id: str) -> dict[str, str]:
    """
    Whether this customer has an open card dispute, and if so the lines and the
    adviser link for the screen pop. Asks the card dispute Lambda
    (connect-card-dispute). Always returns the same keys, as text, and never
    raises: a screen pop must open whatever happens here.
    """
    lines = {"hasDispute": "false", "disputeId": BRIEFING_EMPTY_SLOT, "disputeUrl": BRIEFING_EMPTY_SLOT,
             **{f"dispute{number}": BRIEFING_EMPTY_SLOT for number in range(1, DISPUTE_LINES + 1)}}
    if not (DISPUTE_FUNCTION_NAME and customer_id):
        return lines
    try:
        answer = _invoke_dispute_lambda({"operation": "screen_pop", "customerId": customer_id})
    except Exception:
        logger.exception("Could not ask %s about a card dispute. Check the lambda:InvokeFunction "
                         "permission on this Lambda's role.", DISPUTE_FUNCTION_NAME)
        return lines
    if isinstance(answer, dict) and answer.get("hasDispute") == "true":
        lines.update({key: str(answer[key]) for key in lines if answer.get(key)})
    return lines


def _invoke_lambda(function_name: str, payload: dict) -> Any:
    import boto3
    response = boto3.client("lambda", region_name=injector.AWS_REGION).invoke(
        FunctionName=function_name, InvocationType="RequestResponse", Payload=json.dumps(payload).encode())
    return json.loads(response["Payload"].read() or b"{}")


def _invoke_dispute_lambda(payload: dict) -> Any:
    return _invoke_lambda(DISPUTE_FUNCTION_NAME, payload)


def _money(value: str) -> str:
    digits = value.replace(",", "").replace("£", "").strip()
    return f"£{int(float(digits)):,}" if re.fullmatch(r"\d+(\.\d+)?", digits) else value


def describe_application(application: dict) -> list[str]:
    """
    A saved mortgage application as the lines the screen pop shows: status, each
    stage's answers, the documents, and what is still to fill in. One line each.
    """
    answers, uploaded = application.get("answers") or {}, application.get("documents") or []

    def said(name: str, words: dict | None = None, money: bool = False) -> str:
        value = str(answers.get(name) or "").strip()
        if not value:
            return ""
        return (words or {}).get(value, value) if not money else _money(value)

    def line(heading: str, parts: list[tuple[str, str]]) -> str:
        filled = [f"{label} **{value}**" if label else f"**{value}**" for label, value in parts if value]
        return f"**{heading}:** " + (", ".join(filled) if filled else "nothing filled in yet")

    state = (f"**Submitted**, reference {application.get('reference')}" if application.get("submitted")
             else "**Not submitted**")
    stage = _APPLICATION_STAGES.get(application.get("stage", ""), application.get("stage", ""))
    missing = [label for name, label in _APPLICATION_FIELD_LABELS.items() if not str(answers.get(name) or "").strip()]
    missing += [words for doc, words in _APPLICATION_DOCUMENTS.items() if doc not in uploaded]
    return [
        f"**{application.get('applicationId', '')}** · {state} · reached **{stage}** · "
        f"last changed {str(application.get('updatedAt', ''))[:10]} · " + APPLICATION_CAUTION,
        # The date of birth is not shown: an adviser checks identity by asking for it,
        # so it must not be on a screen that the caller's own application ID selected.
        line("About you", [("", said("fullName")), ("date of birth", said("dateOfBirth") and "given"),
                           ("", said("employmentStatus", _EMPLOYMENT)), ("income", said("annualIncome", money=True)),
                           ("monthly commitments", said("commitmentsMonthly", money=True))]),
        line("Property and loan", [("property", said("propertyValue", money=True)), ("deposit", said("deposit", money=True)),
                                   ("term", said("termYears") and f"{said('termYears')} years"),
                                   ("", said("buyerType", _BUYER))]),
        line("Decision and product", [("Decision in Principle", said("dipDecision")),
                                      ("maximum loan", said("maxLoan", money=True)), ("product", said("productId"))]),
        "**Documents:** " + (", ".join(f"**{_APPLICATION_DOCUMENTS[d]}**" for d in uploaded if d in _APPLICATION_DOCUMENTS)
                             or "none uploaded yet"),
        ("**Still to fill in:** " + ", ".join(missing) + ".") if missing else "**Every answer is filled in.**",
    ]


def mortgage_application_lines(application_id: str) -> dict[str, str]:
    """
    The customer's saved mortgage application, for the screen pop. Reads it from
    Live Sync's main Lambda (operation getApplication, which has no internet
    route). Always returns the same keys, as text, and never raises.
    """
    lines = {"hasApplication": "false",
             **{f"app{number}": BRIEFING_EMPTY_SLOT for number in range(1, APPLICATION_LINES + 1)}}
    if not (LIVESYNC_FUNCTION_NAME and _APPLICATION_ID.fullmatch(application_id or "")):
        return lines
    try:
        reply = _invoke_lambda(LIVESYNC_FUNCTION_NAME, {"operation": "getApplication",
                                                        "payload": {"applicationId": application_id}})
        application = json.loads(reply["body"]) if isinstance(reply.get("body"), str) else reply
    except Exception:
        logger.exception("Could not read the mortgage application from %s. Check the lambda:InvokeFunction "
                         "permission on this Lambda's role.", LIVESYNC_FUNCTION_NAME)
        return lines
    if not application.get("found"):
        lines["app1"] = "The form has not been saved yet. It is saved as the customer fills it in on the web page."
        return lines
    lines["hasApplication"] = "true"
    lines.update({f"app{number}": text for number, text in enumerate(describe_application(application), start=1)})
    return lines


def _briefing_unavailable() -> dict[str, str]:
    """The same set of lines, for when the session could not be read at all."""
    return {"first": BRIEFING_FAILED_TEXT, "verification": BRIEFING_FAILED_TEXT, "ready": "false",
            **card_dispute_lines(""), **mortgage_application_lines(""),
            **{key: value for name, count in BRIEFING_SLOTS.items()
               for key, value in _slots(name, [], count, BRIEFING_FAILED_TEXT).items()}}


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
    agent_status, briefing_status = "not_configured", "not_requested"

    def reply(status: str, keys: list[str] | None = None) -> dict:
        return {"status": status, "assistAgent": agent_status, "briefing": briefing_status,
                "injectedKeys": ",".join(keys or [])}

    if not ASSISTANT_ID:
        logger.error("ASSISTANT_ID is not set. Set it to the Q Connect assistant ID.")
        return reply("error_missing_assistant_id")
    if not contact_id:
        logger.error("ContactId is missing from the event.")
        return reply("error_missing_contact_id")

    if parameters.get("operation") == "get_briefing":
        # Called from the agent's screen-pop flow. Always returns the five
        # lines, so the screen pop has something to show whatever happens.
        try:
            session_arn = injector._resolve_wisdom_session_id(instance_id, contact_id)
            lines = get_briefing(session_arn, contact.get("Attributes") or {}, channel)
        except Exception:
            logger.exception("Could not read the briefing for contact %s", contact_id)
            lines = _briefing_unavailable()
        logger.info(json.dumps({"contactId": contact_id, "status": "briefing_read", "ready": lines["ready"]}))
        return lines

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
            briefing_agent = parameters.get("briefingAgentArn") or BRIEFING_AI_AGENT_ARN
            asked = request_arrival_briefing(session_arn, contact_id, briefing_agent)
            briefing_status = ("requested_fast" if briefing_agent else "requested") if asked else "failed"
    except Exception:
        logger.exception("Agent assist context injection failed for contact %s", contact_id)
        return reply("error_exception")

    keys = sorted(key for key, value in data.items() if value)
    logger.info(json.dumps({"contactId": contact_id, "status": "injected" if injected else "partial_failure",
                            "assistAgent": agent_status, "briefing": briefing_status, "customerId": data.get("customerId", ""), "keys": keys}))
    return reply("injected" if injected else "partial_failure", keys)
