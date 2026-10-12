"""
session_injector.py
====================
ARIA Connect Session Data Injector Lambda

Invoked from the Amazon Connect contact flow via an "Invoke AWS Lambda function"
block, placed IMMEDIATELY AFTER the "Connect assistant" block.

WHY this Lambda exists
----------------------
The Connect AI Prompt uses Handlebars-style template variables:
    {{$.Custom.sessionId}}, {{$.Custom.customerId}}, {{$.Custom.authStatus}},
    {{$.Custom.vulnerabilityContext}}, {{$.Custom.priorSummary}}, etc.

These variables are populated by calling the Q Connect UpdateSessionData API.
The session must already exist before UpdateSessionData can be called — which is
why this Lambda is placed AFTER the Connect assistant block (the block that
creates the session).

Without this Lambda:
    - All {{$.Custom.*}} variables resolve to empty strings
    - ARIA cannot greet the customer by name
    - ARIA does not know the authentication state
    - ARIA does not know about vulnerability flags
    - ARIA does not receive prior session context

WHAT this Lambda injects
------------------------
Core session variables (always injected):
    sessionId          — ContactId, used to correlate all tool calls in this session
    customerId         — Customer ID retrieved from contact attributes
    authStatus         — "authenticated" | "unauthenticated" (from IVR or mobile pre-auth)
    channel            — "voice" | "chat" | "ivr" (derived from Connect channel)
    dateTime           — Current UTC ISO timestamp for compliance logging
    instanceId         — Connect instance ID for escalation routing
    locale             — Defaults to "en-GB"

Context variables (injected when customerId is available):
    preferredName      — Customer's preferred first name for greeting
    productSummary     — Natural language sentence describing the customer's products
                         e.g. "You have a current account, a savings account, and a Visa debit card."
    vulnerabilityContext — JSON string of vulnerability flags (SILENT — ARIA never discloses this)
    priorSummary       — Brief summary of the customer's last interaction (from memory store)

Known contact reasons (injected only for a verified caller):
    hasKnownContactReason    — "true" | "false"
    topContactReason         — Short label of the most likely reason for the contact
    topContactReasonCategory — Routing topic of that reason (matches the routing table)
    contactReasonSummary     — One sentence listing up to three known reasons
    contactReasons           — JSON list of the same reasons with detail and date
    These are disclosed only when an upstream ID&V flow has set the `LoA`
    contact attribute, and only reasons whose minimum level that LoA meets.
    A caller authenticated by phone number alone receives none.
    productContext     — JSON string of masked account/card references for ARIA's tool calls

HOW this Lambda is invoked
--------------------------
Amazon Connect invokes Lambda functions with an event in the following format:
{
    "Details": {
        "ContactData": {
            "ContactId": "abc-123",
            "InstanceARN": "arn:aws:connect:eu-west-2:395402194296:instance/INST-ID",
            "Channel": "VOICE",
            "Attributes": {
                "customerId": "CUST-001",
                "authStatus": "unauthenticated",
                ...
            },
            "CustomerEndpoint": {"Address": "+447700900000", "Type": "TELEPHONE_NUMBER"},
            "SystemEndpoint": {"Address": "+441612345678", "Type": "TELEPHONE_NUMBER"}
        },
        "Parameters": {}
    },
    "Name": "ContactFlowEvent",
    "Version": "1.0"
}

DEPLOYMENT
----------
See docs/aria-connect-conversational-ai-setup-guide.md Part 5 for step-by-step
deployment instructions including IAM role, packaging, and Connect permissions.

ENVIRONMENT VARIABLES
---------------------
Required:
    ASSISTANT_ID       — Q Connect assistant ID (from Step 1.2 of the setup guide)

Optional:
    INSTANCE_ID        — Connect instance ID; derived from event if not set
    AWS_REGION         — Defaults to eu-west-2
    CRM_API_ENDPOINT   — HTTP endpoint of your CRM API. If unset, stub data is used.
    MEMORY_TABLE_NAME  — DynamoDB table name for prior session summaries. If unset, skipped.

IAM PERMISSIONS REQUIRED (on the Lambda execution role)
--------------------------------------------------------
    connect:DescribeContact          on arn:aws:connect:*:ACCOUNT:instance/*
    connect:GetContactAttributes     on arn:aws:connect:*:ACCOUNT:instance/*
    qconnect:UpdateSessionData       on arn:aws:wisdom:*:ACCOUNT:assistant/*
    wisdom:UpdateSessionData         on arn:aws:wisdom:*:ACCOUNT:assistant/*
    lambda:InvokeFunction            on arn:aws:lambda:*:ACCOUNT:function:aria-* (if chaining)
    dynamodb:GetItem                 on arn:aws:dynamodb:*:ACCOUNT:table/MEMORY_TABLE (optional)

OFFICIAL AWS REFERENCES
-----------------------
    Connect Lambda integration:
        https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html
    Q Connect UpdateSessionData API:
        https://docs.aws.amazon.com/connect/latest/APIReference/API_amazon-q-connect_UpdateSessionData.html
    Contact flow event format:
        https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html#function-contact-flow-event-data
    Session data in AI prompts:
        https://docs.aws.amazon.com/connect/latest/adminguide/customize-connect-ai-agents.html
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Configuration — override via environment variables in the Lambda console
# ---------------------------------------------------------------------------
ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "")  # REQUIRED: Q Connect assistant ID
AWS_REGION: str = os.environ.get("AWS_REGION", "eu-west-2")
CRM_API_ENDPOINT: str = os.environ.get("CRM_API_ENDPOINT", "")  # Empty = use stub data
MEMORY_TABLE_NAME: str = os.environ.get("MEMORY_TABLE_NAME", "")  # Empty = skip prior summary
TRANSCRIPT_TABLE_NAME: str = os.environ.get("TRANSCRIPT_TABLE_NAME", "aria-transcript-store")  # Cross-channel transcripts

# ---------------------------------------------------------------------------
# AWS clients — initialised once per Lambda container lifecycle
# ---------------------------------------------------------------------------
_connect_client = None
_qconnect_client = None
_dynamodb_client = None


def _get_connect() -> Any:
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _connect_client


def _get_qconnect() -> Any:
    global _qconnect_client
    if _qconnect_client is None:
        _qconnect_client = boto3.client("qconnect", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _qconnect_client


def _get_dynamodb() -> Any:
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = boto3.client("dynamodb", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _dynamodb_client


# ---------------------------------------------------------------------------
# Phone number → customer ID mapping (test/dev only)
# ---------------------------------------------------------------------------
# Maps inbound PSTN numbers to stub customer IDs so the Lambda can inject
# rich customer context when no customerId has been set in contact attributes
# (e.g. unauthenticated callers during development testing).
#
# In production this lookup is replaced by a CRM API call using the caller's
# verified phone number or IVR-collected account reference.
#
# Add your own test number here to get full customer context on test calls.
# ---------------------------------------------------------------------------
_PHONE_TO_CUSTOMER: dict[str, str] = {
    "+447765309252": "CUST-001",   # Developer / admin test number → James Hartley
    "+447700900001": "CUST-002",   # Test: Sarah Chen (financial difficulty)
    "+447700900002": "CUST-003",   # Test: Margaret Okonkwo (bereavement)
    "+447700900003": "CUST-004",   # Test: Daniel Walsh (mental health)
    "+447700900004": "CUST-005",   # Test: Ethel Parsons (elderly)
}


def _mask_phone(phone: str) -> str:
    """Return phone masked to last 4 digits: ***-**-1234"""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) >= 4:
        return f"***-**-{digits[-4:]}"
    return "***"


# ---------------------------------------------------------------------------
# Stub customer registry
# ---------------------------------------------------------------------------
# This replicates the data in aria/tools/customer/customer_details.py.
# In production, replace _lookup_customer() below with a real CRM API call.
# Both this Lambda and the ARIA agent tools should read from the same CRM
# backend to ensure data consistency across the interaction.
# ---------------------------------------------------------------------------
_STUB_CUSTOMERS: dict[str, dict] = {
    "CUST-001": {
        "preferred_name": "James",
        "full_name": "James Hartley",
        "status": "active",
        "accounts": [
            {"masked": "****4821", "type": "current", "nickname": "Main Account"},
            {"masked": "****9104", "type": "savings",  "nickname": "Holiday Savings"},
        ],
        "cards": [
            {"last_four": "4821", "type": "debit",  "scheme": "Visa",       "nickname": "Everyday Debit"},
            {"last_four": "2291", "type": "credit", "scheme": "Mastercard", "nickname": "Rewards Credit Card"},
        ],
        "mortgages": ["MR-****-GB"],
        "vulnerability": None,
    },
    "CUST-002": {
        "preferred_name": "Sarah",
        "full_name": "Sarah Chen",
        "status": "active",
        "accounts": [{"masked": "****3317", "type": "current", "nickname": "Main Account"}],
        "cards": [{"last_four": "3317", "type": "debit", "scheme": "Visa", "nickname": "Everyday Debit"}],
        "mortgages": [],
        "vulnerability": {
            "flag_type": "financial_difficulty",
            "requires_extra_time": True,
            "requires_simplified_language": True,
            "refer_to_specialist": True,
            "suppress_promotion": True,
            "suppress_collections": True,
            "debt_signpost": True,
        },
    },
    "CUST-003": {
        "preferred_name": "Margaret",
        "full_name": "Margaret Okonkwo",
        "status": "active",
        "accounts": [{"masked": "****6612", "type": "current", "nickname": "Main Account"}],
        "cards": [{"last_four": "6612", "type": "debit", "scheme": "Visa", "nickname": "Everyday Debit"}],
        "mortgages": ["MR-****-BM"],
        "vulnerability": {
            "flag_type": "bereavement",
            "requires_extra_time": True,
            "requires_simplified_language": True,
            "refer_to_specialist": False,
            "suppress_promotion": True,
            "suppress_collections": False,
            "debt_signpost": False,
        },
    },
    "CUST-004": {
        "preferred_name": "Daniel",
        "full_name": "Daniel Walsh",
        "status": "active",
        "accounts": [{"masked": "****7734", "type": "current", "nickname": "Main Account"}],
        "cards": [{"last_four": "7734", "type": "debit", "scheme": "Mastercard", "nickname": "Everyday Debit"}],
        "mortgages": [],
        "vulnerability": {
            "flag_type": "mental_health",
            "requires_extra_time": True,
            "requires_simplified_language": True,
            "refer_to_specialist": True,
            "suppress_promotion": True,
            "suppress_collections": True,
            "debt_signpost": False,
        },
    },
    "CUST-005": {
        "preferred_name": "Ethel",
        "full_name": "Ethel Parsons",
        "status": "active",
        "accounts": [
            {"masked": "****1155", "type": "current", "nickname": "Main Account"},
            {"masked": "****8820", "type": "savings",  "nickname": "Savings Account"},
        ],
        "cards": [{"last_four": "1155", "type": "debit", "scheme": "Visa", "nickname": "Everyday Debit"}],
        "mortgages": [],
        "vulnerability": {
            "flag_type": "elderly",
            "requires_extra_time": True,
            "requires_simplified_language": True,
            "refer_to_specialist": False,
            "suppress_promotion": True,
            "suppress_collections": False,
            "debt_signpost": False,
        },
    },
}


# ---------------------------------------------------------------------------
# BEGIN known contact reasons
# (this block is kept identical in session_injector.py and
#  session_injector_qconnect.py — a unit test compares the two copies)
# ---------------------------------------------------------------------------
# Things the bank already knows that may be why the customer is getting in
# touch: a stalled mortgage application, repeated failed payments, trouble with
# mobile banking, a card blocked for suspected fraud. Injected so ARIA can ask
# "are you calling about ...?" instead of making the customer explain.
#
# DISCLOSURE RULE: a known reason is personal data, and some of it (a fraud
# block) would tip off a fraudster. Reasons are therefore injected ONLY when an
# upstream ID&V flow has verified the caller and left a level of assurance in
# the `LoA` contact attribute, and only reasons whose min_loa that level meets.
# A caller who is "authenticated" by phone number alone gets none.
#
# Stub fields:
#   type            stable code for rules and reporting
#   label           short phrase ARIA can say after "are you calling about ..."
#   detail          context for ARIA; not to be read out verbatim
#   days_ago        how long ago it happened (kept relative so test data never goes stale)
#   priority        1 = most likely reason; ties broken by most recent
#   topic_category  matches the proficiency routing table, for escalation
#   min_loa         lowest level of assurance at which it may be mentioned
MAX_CONTACT_REASONS = 3
SESSION_VALUE_MAX_CHARS = 1024   # Q Connect per-value limit for session data

_STUB_CONTACT_REASONS: dict[str, list[dict]] = {
    "CUST-001": [
        {"type": "MORTGAGE_APPLICATION_PENDING", "label": "your mortgage application",
         "detail": "Application started online and paused at the income documents step; payslips have not been uploaded.",
         "days_ago": 9, "priority": 2, "topic_category": "mortgages", "min_loa": 2},
        {"type": "MOBILE_APP_LOGIN_FAILED", "label": "trouble signing in to the mobile app",
         "detail": "Four failed sign-in attempts on the mobile app today, following an app update.",
         "days_ago": 0, "priority": 1, "topic_category": "general_banking", "min_loa": 2},
    ],
    "CUST-002": [
        {"type": "PAYMENT_FAILED_REPEATED", "label": "a payment that did not go through",
         "detail": "Three attempts to pay an existing payee were declined in the last 24 hours.",
         "days_ago": 0, "priority": 1, "topic_category": "current_account", "min_loa": 2},
        {"type": "DIRECT_DEBIT_RETURNED", "label": "a direct debit that was returned unpaid",
         "detail": "One direct debit was returned unpaid two days ago.",
         "days_ago": 2, "priority": 2, "topic_category": "current_account", "min_loa": 2},
    ],
    "CUST-003": [
        {"type": "MOBILE_BANKING_LOCKED", "label": "being locked out of mobile banking",
         "detail": "Mobile banking access was locked yesterday after repeated incorrect passcode entries.",
         "days_ago": 1, "priority": 1, "topic_category": "general_banking", "min_loa": 2},
        {"type": "DOCUMENT_UPLOAD_FAILED", "label": "a document you tried to send us",
         "detail": "A document upload to the bereavement team failed three days ago and was not received.",
         "days_ago": 3, "priority": 2, "topic_category": "bereavement", "min_loa": 2},
    ],
    "CUST-004": [
        {"type": "CARD_BLOCKED_FRAUD", "label": "a block on your debit card",
         "detail": "Debit card ending 7734 was blocked yesterday after two unrecognised online transactions were declined.",
         "days_ago": 1, "priority": 1, "topic_category": "fraud_security", "min_loa": 3},
        {"type": "PAYMENT_FAILED_REPEATED", "label": "card payments that were declined",
         "detail": "Several card payments have been declined since yesterday.",
         "days_ago": 0, "priority": 2, "topic_category": "debit_card", "min_loa": 2},
    ],
    "CUST-005": [
        {"type": "CARD_PIN_LOCKED", "label": "your card PIN being locked",
         "detail": "The debit card PIN was locked yesterday after three incorrect attempts at a cash machine.",
         "days_ago": 1, "priority": 1, "topic_category": "debit_card", "min_loa": 2},
        {"type": "STATEMENT_REQUEST_PENDING", "label": "a paper statement you asked for",
         "detail": "A paper statement was requested six days ago and has not been sent yet.",
         "days_ago": 6, "priority": 2, "topic_category": "current_account", "min_loa": 2},
    ],
}


def _parse_loa(raw: str) -> int | None:
    """Level of assurance from the `LoA` contact attribute; None when absent or not a number."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _lookup_contact_reasons(customer_id: str) -> list[dict]:
    """
    Known reasons this customer may be getting in touch.

    Returns stub data. In production, replace with queries to the systems that
    hold these events (mortgage origination, payments, digital banking, fraud).
    """
    return list(_STUB_CONTACT_REASONS.get(customer_id, []))


def _select_contact_reasons(customer_id: str, auth_status: str, loa: int | None) -> list[dict]:
    """The reasons that may be disclosed at this level, most likely first, capped."""
    if auth_status != "authenticated" or loa is None:
        return []
    allowed = [r for r in _lookup_contact_reasons(customer_id) if r.get("min_loa", 2) <= loa]
    allowed.sort(key=lambda r: (r.get("priority", 9), r.get("days_ago", 999)))
    return allowed[:MAX_CONTACT_REASONS]


def _build_contact_reason_vars(customer_id: str, auth_status: str, loa: int | None) -> dict[str, str]:
    """
    Session variables describing the known contact reasons.

        hasKnownContactReason     "true" | "false"
        topContactReason          label of the most likely reason
        topContactReasonCategory  routing topic of the most likely reason
        contactReasonSummary      one sentence listing the reasons, for the AI prompt
        contactReasons            JSON list of {type, label, detail, occurredAt, topicCategory}

    Everything except hasKnownContactReason is an empty string when there is
    nothing to disclose, and empty values are not injected.
    """
    reasons = _select_contact_reasons(customer_id, auth_status, loa)
    if not reasons:
        return {"hasKnownContactReason": "false", "topContactReason": "", "topContactReasonCategory": "",
                "contactReasonSummary": "", "contactReasons": ""}

    now = datetime.now(timezone.utc)

    def public(reason: dict) -> dict:
        occurred = (now - timedelta(days=reason.get("days_ago", 0))).date().isoformat()
        return {"type": reason["type"], "label": reason["label"], "detail": reason["detail"],
                "occurredAt": occurred, "topicCategory": reason.get("topic_category", "")}

    # Drop the least likely reason until both values fit Q Connect's limit.
    kept = list(reasons)
    while True:
        as_json = json.dumps([public(r) for r in kept], separators=(",", ":"))
        summary = "; ".join(f"({i}) {r['label']}: {r['detail']}" for i, r in enumerate(kept, start=1))
        if len(kept) == 1 or max(len(as_json), len(summary)) <= SESSION_VALUE_MAX_CHARS:
            break
        kept.pop()

    return {
        "hasKnownContactReason": "true",
        "topContactReason": kept[0]["label"],
        "topContactReasonCategory": kept[0].get("topic_category", ""),
        "contactReasonSummary": summary[:SESSION_VALUE_MAX_CHARS],
        "contactReasons": as_json if len(as_json) <= SESSION_VALUE_MAX_CHARS else "",
    }
# ---------------------------------------------------------------------------
# END known contact reasons
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CRM lookup
# ---------------------------------------------------------------------------

def _resolve_wisdom_session_id(instance_id: str, contact_id: str) -> str:
    """
    Resolve the Q Connect session ID for the given contact.

    The Q Connect session is created by the CreateWisdomSession block in the
    contact flow.  The session UUID (required by UpdateSessionData) is stored
    in Contact.WisdomInfo.SessionArn and is DIFFERENT from the ContactId.

    ARN format: arn:aws:wisdom:REGION:ACCOUNT:session/ASSISTANT_ID/SESSION_UUID

    We call DescribeContact to retrieve the ARN and return the full ARN (the
    Q Connect API accepts either the UUID or the full ARN as sessionId).

    Falls back to contact_id if DescribeContact fails or returns no SessionArn.
    The fallback almost always fails downstream — it is kept to preserve the
    error log for diagnosability.

    IAM: requires connect:DescribeContact on the instance resource.
    """
    if not instance_id or not contact_id:
        return contact_id

    try:
        resp = _get_connect().describe_contact(
            InstanceId=instance_id,
            ContactId=contact_id,
        )
        session_arn: str = resp.get("Contact", {}).get("WisdomInfo", {}).get("SessionArn", "")
        if session_arn:
            logger.info(f"Resolved Q Connect session ARN: {session_arn}")
            return session_arn  # Q Connect accepts the full ARN as sessionId
        else:
            logger.warning(
                "WisdomInfo.SessionArn not found on contact. "
                "Ensure CreateWisdomSession ran before this Lambda."
            )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.warning(f"DescribeContact failed [{code}]: {e} — falling back to contact_id")

    return contact_id


def _lookup_customer(customer_id: str) -> dict | None:
    """
    Look up a customer record by ID.

    This stub returns data from _STUB_CUSTOMERS.
    In production, replace the body of this function with a call to your CRM API,
    e.g.:

        import urllib.request
        url = f"{CRM_API_ENDPOINT}/customers/{customer_id}"
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + _get_crm_token()})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())

    The CRM API should be the SAME source that the ARIA Strands tools call via the
    MCP Gateway, ensuring data consistency across the session. If ARIA later calls
    get_customer_details via the tool, it should return the same data.
    """
    if CRM_API_ENDPOINT:
        # TODO: Replace with real CRM API call
        logger.warning("CRM_API_ENDPOINT is set but real CRM call not yet implemented. Falling back to stub.")

    return _STUB_CUSTOMERS.get(customer_id)


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _build_product_summary(customer: dict) -> str:
    """
    Build a natural-language sentence describing the customer's products.

    This is injected as {{$.Custom.productSummary}} and used by ARIA to acknowledge
    products conversationally at session start without calling a tool.

    Example output:
        "James has a current account ending 4821, a savings account,
         a Visa debit card ending 4821, and a Mastercard credit card."
    """
    parts: list[str] = []

    accounts = customer.get("accounts", [])
    for acct in accounts:
        if acct["type"] == "current":
            parts.append(f"a current account ending {acct['masked'][-4:]}")
        elif acct["type"] == "savings":
            parts.append(f"a savings account ({acct['nickname']})")
        else:
            parts.append(f"a {acct['type']} account")

    cards = customer.get("cards", [])
    for card in cards:
        scheme = card.get("scheme", "")
        ctype = card.get("type", "")
        last4 = card.get("last_four", "****")
        parts.append(f"a {scheme} {ctype} card ending {last4}")

    mortgages = customer.get("mortgages", [])
    if mortgages:
        parts.append(f"{len(mortgages)} mortgage{'s' if len(mortgages) > 1 else ''}")

    if not parts:
        return ""

    name = customer.get("preferred_name", "")
    if len(parts) == 1:
        return f"{name} has {parts[0]}."
    elif len(parts) == 2:
        return f"{name} has {parts[0]} and {parts[1]}."
    else:
        return f"{name} has {', '.join(parts[:-1])}, and {parts[-1]}."


def _build_product_context(customer: dict) -> str:
    """
    Build a compact JSON string of the customer's masked product references.

    Injected as {{$.Custom.productContext}} — ARIA can use this to resolve
    "my account" or "my card" ambiguity without calling a tool first.
    All values use masked references only — no raw account numbers.
    """
    return json.dumps({
        "accounts": customer.get("accounts", []),
        "cards": customer.get("cards", []),
        "mortgages": customer.get("mortgages", []),
    }, default=str)


def _build_vulnerability_context(customer: dict) -> str:
    """
    Build a JSON string of the customer's vulnerability flags.

    Injected as {{$.Custom.vulnerabilityContext}}.
    ARIA's system prompt instructs it to read this SILENTLY — never disclose
    vulnerability status to the customer.

    The flags tell ARIA:
        requires_extra_time:          Allow longer pauses; do not rush the customer.
        requires_simplified_language: Use plain English; avoid jargon.
        refer_to_specialist:          Warm-transfer at session start without asking.
        suppress_promotion:           Never upsell, cross-sell, or mention rate switches.
        suppress_collections:         Never mention arrears or request payments.
        debt_signpost:                Proactively mention StepChange, MoneyHelper once.
    """
    vuln = customer.get("vulnerability")
    if not vuln:
        return ""
    return json.dumps(vuln, default=str)


def _lookup_prior_summary(customer_id: str, session_id: str) -> str:
    """
    Retrieve the summary of the customer's most recent prior session.

    If MEMORY_TABLE_NAME is set, looks up a DynamoDB item with the following schema:
        PK: CUSTOMER#<customer_id>
        SK: LAST_SESSION_SUMMARY
        summary: "Customer asked about their balance and requested a statement. ..."

    This populates {{$.Custom.priorSummary}} in ARIA's prompt, allowing ARIA to
    acknowledge prior context at session start.

    Official reference for Q Connect session memory:
        https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-session.html

    Returns empty string if no prior summary exists or if the table is not configured.
    """
    if not MEMORY_TABLE_NAME:
        return ""

    try:
        resp = _get_dynamodb().get_item(
            TableName=MEMORY_TABLE_NAME,
            Key={
                "PK": {"S": f"CUSTOMER#{customer_id}"},
                "SK": {"S": "LAST_SESSION_SUMMARY"},
            },
        )
        item = resp.get("Item", {})
        return item.get("summary", {}).get("S", "")
    except ClientError as e:
        logger.warning(f"DynamoDB lookup for prior summary failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Session data injection
# ---------------------------------------------------------------------------

def _inject_session_data(
    assistant_id: str,
    session_id: str,
    data: dict[str, str],
) -> bool:
    """
    Call the Q Connect UpdateSessionData API to inject key-value pairs into the session.

    All values must be strings — Q Connect session data only supports string values
    for use in the {{$.Custom.*}} prompt template variables.

    Official API reference:
        https://docs.aws.amazon.com/connect/latest/APIReference/API_amazon-q-connect_UpdateSessionData.html

    The session must already exist before calling this function. The "Connect assistant"
    block in the contact flow creates the session. That is why this Lambda must be
    placed AFTER the Connect assistant block in the flow.

    Args:
        assistant_id: Q Connect assistant ID
        session_id:   The session to update — in Connect integrations this is the ContactId
        data:         Dict of key -> value (all strings) to inject

    Returns:
        True on success, False on error
    """
    if not assistant_id:
        logger.error("ASSISTANT_ID environment variable is not set. Cannot inject session data.")
        return False

    # Build the runtime session data format required by the Q Connect API
    # Ref: RuntimeSessionData shape in the Q Connect API docs
    session_data_payload = [
        {"key": k, "value": {"stringValue": str(v)}}
        for k, v in data.items()
        if v is not None and v != ""
    ]

    if not session_data_payload:
        logger.warning("No session data to inject.")
        return True

    try:
        _get_qconnect().update_session_data(
            assistantId=assistant_id,
            sessionId=session_id,
            data=session_data_payload,
        )
        logger.info(
            f"Session data injected: assistant={assistant_id} session={session_id} "
            f"keys={[d['key'] for d in session_data_payload]}"
        )
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        message = e.response.get("Error", {}).get("Message", str(e))

        if code == "ResourceNotFoundException":
            logger.error(
                f"Session not found: {session_id}. "
                "Ensure this Lambda is placed AFTER the Connect assistant block in the flow. "
                "The session is created by the Connect assistant block."
            )
        elif code == "AccessDeniedException":
            logger.error(
                f"Access denied calling UpdateSessionData. "
                "Ensure the Lambda IAM role has qconnect:UpdateSessionData and "
                "wisdom:UpdateSessionData on the assistant ARN."
            )
        else:
            logger.error(f"UpdateSessionData failed [{code}]: {message}")
        return False


# ---------------------------------------------------------------------------
# Main Lambda handler
# ---------------------------------------------------------------------------

def _get_cross_channel_transcript(flow_attributes: dict) -> dict:
    """
    Detects cross-channel transfers and retrieves the prior channel's transcript
    from DynamoDB (aria-transcript-store).

    Called by lambda_handler when a contact has either:
      - chatTransferSource = 'voice'  → new CHAT continued from VOICE call
      - voiceTransferSource = 'chat'  → new VOICE call continued from CHAT session

    The DynamoDB table is populated by voice_to_chat_transfer.py and
    chat_to_voice_transfer.py when the transfer Lambda runs.

    Returns a dict of additional session variables to inject (may be empty if
    not a cross-channel transfer, or if the table lookup fails).
    """
    if not TRANSCRIPT_TABLE_NAME:
        return {}

    chat_transfer_source = flow_attributes.get("chatTransferSource", "")
    voice_transfer_source = flow_attributes.get("voiceTransferSource", "")

    prior_contact_id = ""
    prior_channel = ""

    if chat_transfer_source == "voice":
        prior_contact_id = flow_attributes.get("voiceContactId", "")
        prior_channel = "voice"
    elif voice_transfer_source == "chat":
        prior_contact_id = flow_attributes.get("chatContactId", "")
        prior_channel = "chat"

    if not prior_contact_id:
        return {}

    try:
        response = _get_dynamodb().get_item(
            TableName=TRANSCRIPT_TABLE_NAME,
            Key={"contactId": {"S": prior_contact_id}},
            ProjectionExpression="transcript, summary",
        )
        item = response.get("Item", {})
        if not item:
            logger.warning(
                f"Cross-channel transcript not found in DynamoDB for contactId={prior_contact_id!r}. "
                "The transfer Lambda may not have stored it yet, or it expired."
            )
            return {}

        return {
            "priorTranscript": item.get("transcript", {}).get("S", ""),
            "priorSummary":    item.get("summary", {}).get("S", ""),
            "priorChannel":    prior_channel,
            "priorContactId":  prior_contact_id,
        }

    except Exception as exc:
        logger.error(f"Failed to retrieve cross-channel transcript: {exc}")
        return {}


def lambda_handler(event: dict, context: Any) -> dict:
    """
    Entry point. Called by Amazon Connect via the "Invoke AWS Lambda function" block.

    The handler NEVER raises an exception. All errors are caught and logged.
    If a step fails, we return a partial success so the contact flow continues —
    ARIA will still work, but without pre-injected context.

    Q Connect / Wisdom integration is OPTIONAL. When ASSISTANT_ID is not set this
    Lambda still performs its primary job: look up the caller, build customer context,
    and return all fields so the contact flow can store them as contact attributes
    (Block 5) and forward them to Lex session attributes (Block 6), from where the
    fulfillment Lambda reads them and includes them in the AgentCore payload.

    Official Lambda integration reference:
        https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html

    Returns:
        Dict with keys: sessionId, status, customerId, authStatus, channel, and
        optional context fields (preferredName, productSummary, etc.)
    """
    logger.info(f"Session injector invoked: {json.dumps(event, default=str)}")

    # ----------------------------------------------------------------
    # 1. Extract contact data from the Connect event
    # ----------------------------------------------------------------
    contact_data: dict = event.get("Details", {}).get("ContactData", {})
    contact_id: str = contact_data.get("ContactId", "")
    instance_arn: str = contact_data.get("InstanceARN", "")
    instance_id: str = os.environ.get("INSTANCE_ID", "") or instance_arn.split("instance/")[-1]
    raw_channel: str = contact_data.get("Channel", "VOICE")

    # Map Connect channel names to ARIA channel names
    channel_map = {"VOICE": "voice", "CHAT": "chat", "TASK": "chat"}
    aria_channel: str = channel_map.get(raw_channel.upper(), "voice")

    # Read contact attributes set earlier in the flow
    # e.g. by a CRM lookup Lambda or IVR digit collection
    flow_attributes: dict = contact_data.get("Attributes", {}) or {}
    customer_id: str = flow_attributes.get("customerId", "")
    auth_status: str = flow_attributes.get("authStatus", "unauthenticated")
    locale: str = flow_attributes.get("locale", "en-GB")
    # Level of assurance left by an upstream ID&V flow; None when no such flow ran.
    idv_loa: int | None = _parse_loa(flow_attributes.get("LoA", ""))

    # If no customerId in attributes, try to identify the caller by phone number.
    # This covers unauthenticated test calls where IVR has not yet set customerId.
    caller_phone: str = contact_data.get("CustomerEndpoint", {}).get("Address", "")
    if not customer_id and caller_phone:
        resolved = _PHONE_TO_CUSTOMER.get(caller_phone, "")
        if resolved:
            customer_id = resolved
            auth_status = "authenticated"   # phone-based lookup counts as light auth
            logger.info("Resolved customerId=%r from phone=%s", customer_id, _mask_phone(caller_phone))
        else:
            logger.info("Caller phone %s has no mapped customerId — unauthenticated session", _mask_phone(caller_phone))

    # Use ContactId as the primary session correlator.
    # When Q Connect is configured (ASSISTANT_ID is set), also resolve the Wisdom
    # session ARN via DescribeContact — the Q Connect API requires it. Otherwise
    # contact_id is sufficient for the AgentCore / Lex code path.
    if not contact_id:
        logger.error("ContactId is missing from event. Cannot process session.")
        return {"status": "error", "reason": "missing_contact_id"}

    session_id: str = contact_id
    if ASSISTANT_ID:
        session_id = _resolve_wisdom_session_id(instance_id, contact_id)

    logger.info(
        f"Contact: id={contact_id} channel={aria_channel} "
        f"customerId={customer_id!r} authStatus={auth_status!r}"
    )

    # ----------------------------------------------------------------
    # 2. Build base session variables (always injected)
    # ----------------------------------------------------------------
    now_utc = datetime.now(timezone.utc).isoformat()
    session_vars: dict[str, str] = {
        "sessionId":  session_id,
        "customerId": customer_id,
        "authStatus": auth_status,
        "channel":    aria_channel,
        "dateTime":   now_utc,
        "instanceId": instance_id,
        "locale":     locale,
    }

    # ----------------------------------------------------------------
    # 3. Enrich with customer context (when customerId is available)
    # ----------------------------------------------------------------
    if customer_id:
        customer = _lookup_customer(customer_id)

        if customer:
            preferred_name = customer.get("preferred_name", "")
            product_summary = _build_product_summary(customer)
            product_context = _build_product_context(customer)
            vulnerability_context = _build_vulnerability_context(customer)
            prior_summary = _lookup_prior_summary(customer_id, session_id)

            session_vars.update({
                "preferredName":       preferred_name,
                "productSummary":      product_summary,
                "productContext":      product_context,
                "vulnerabilityContext": vulnerability_context,
                "priorSummary":        prior_summary,
            })
            reason_vars = _build_contact_reason_vars(customer_id, auth_status, idv_loa)
            session_vars.update(reason_vars)

            logger.info(
                f"Customer context built: name={preferred_name!r} "
                f"vulnerability={'yes' if vulnerability_context else 'none'} "
                f"priorSummary={'yes' if prior_summary else 'none'} "
                f"knownContactReason={reason_vars['hasKnownContactReason']} (LoA={idv_loa})"
            )
        else:
            logger.warning(f"Customer ID {customer_id!r} not found in CRM. Injecting base variables only.")
            session_vars["preferredName"] = ""
            session_vars["productSummary"] = ""
            session_vars["productContext"] = ""
            session_vars["vulnerabilityContext"] = ""
            session_vars["priorSummary"] = ""
    else:
        logger.info("No customerId resolved — injecting base session variables only (phone=%s)", _mask_phone(caller_phone))

    # ----------------------------------------------------------------
    # 3b. Cross-channel transfer context (voice→chat or chat→voice)
    # If this contact is a continuation of a prior channel, inject the
    # prior transcript so ARIA has full conversation continuity.
    # ----------------------------------------------------------------
    cross_channel_vars = _get_cross_channel_transcript(flow_attributes)
    if cross_channel_vars:
        session_vars.update(cross_channel_vars)
        logger.info(
            f"Cross-channel context injected: priorChannel={cross_channel_vars.get('priorChannel')!r} "
            f"priorContactId={cross_channel_vars.get('priorContactId')!r}"
        )

    # ----------------------------------------------------------------
    # 4. Inject into Q Connect session (only when ASSISTANT_ID is configured)
    # ----------------------------------------------------------------
    q_connect_success = True
    if ASSISTANT_ID:
        q_connect_success = _inject_session_data(
            assistant_id=ASSISTANT_ID,
            session_id=session_id,
            data=session_vars,
        )
        if not q_connect_success:
            logger.error(
                "Q Connect session injection failed. ARIA will operate without Q Connect "
                "prompt context. The contact flow will continue normally."
            )
    else:
        logger.info(
            "ASSISTANT_ID not set — skipping Q Connect session injection. "
            "Context will be forwarded via contact attributes (Block 5) and Lex session "
            "attributes (Block 6) only."
        )

    injected_keys = list(session_vars.keys())
    # Expose all context fields in the return value so they can be captured as
    # Connect contact attributes in Block 5 and forwarded to Lex session attributes
    # in Block 6, from where the fulfillment Lambda reads them and includes them
    # in the AgentCore payload.
    result = {
        "sessionId":             session_id,
        "customerId":            customer_id,
        "status":                "ok" if not ASSISTANT_ID else ("injected" if q_connect_success else "partial_failure"),
        "injectedKeys":          injected_keys,
        "channel":               aria_channel,
        "authStatus":            auth_status,
        # Context variables — populated when customerId is resolved
        "preferredName":         session_vars.get("preferredName", ""),
        "productSummary":        session_vars.get("productSummary", ""),
        "productContext":        session_vars.get("productContext", ""),
        "vulnerabilityContext":  session_vars.get("vulnerabilityContext", ""),
        "priorSummary":          session_vars.get("priorSummary", ""),
        # Known contact reasons (empty unless an upstream ID&V flow verified the caller)
        "hasKnownContactReason":    session_vars.get("hasKnownContactReason", "false"),
        "topContactReason":         session_vars.get("topContactReason", ""),
        "topContactReasonCategory": session_vars.get("topContactReasonCategory", ""),
        "contactReasonSummary":     session_vars.get("contactReasonSummary", ""),
        "contactReasons":           session_vars.get("contactReasons", ""),
        # Core metadata
        "locale":                session_vars.get("locale", locale),
        "dateTime":              session_vars.get("dateTime", ""),
        "instanceId":            session_vars.get("instanceId", instance_id),
    }

    logger.info(f"Session injector complete: {json.dumps(result, default=str)}")
    return result
