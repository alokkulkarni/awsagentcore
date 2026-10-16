"""
session_injector_qconnect.py
=============================
ARIA Connect Session Data Injector Lambda — Q Connect / Wisdom variant

This is a copy of session_injector.py with Q Connect (Wisdom) session data
injection ALWAYS enabled.  Use this variant when your contact flow includes
a "Connect assistant" (Q Connect) block and you need ARIA's AI prompt template
variables ({{$.Custom.*}}) to be populated at session start.

Differences from session_injector.py
--------------------------------------
1. ASSISTANT_ID is REQUIRED — the handler returns an error immediately if it
   is not set, rather than gracefully skipping injection.
2. _resolve_wisdom_session_id() is ALWAYS called — it resolves the Wisdom
   session ARN from the contact via connect:DescribeContact, which is required
   by the Q Connect UpdateSessionData API.
3. _inject_session_data() is ALWAYS called — the handler treats an injection
   failure as a hard error (status = "partial_failure") and logs clearly.
4. This Lambda MUST be placed AFTER the "Connect assistant" block in the flow,
   because the Wisdom session does not exist until that block runs.

Contact flow placement
------------------------
    [Play prompt]
        ↓
    [Connect assistant]   ← creates the Q Connect / Wisdom session
        ↓
    [Invoke Lambda: aria-session-injector-qconnect]   ← this Lambda
        ↓ Success
    [Set contact attributes]  ← store $.External.* → $.Attributes.*
        ↓
    [Get customer input / Lex V2]

WHY this Lambda exists
-----------------------
The Connect AI Prompt uses Handlebars-style template variables:
    {{$.Custom.sessionId}}, {{$.Custom.customerId}}, {{$.Custom.authStatus}},
    {{$.Custom.vulnerabilityContext}}, {{$.Custom.priorSummary}}, etc.

These variables are populated by calling the Q Connect UpdateSessionData API.
The session must already exist before UpdateSessionData can be called — which is
why this Lambda is placed AFTER the Connect assistant block.

Without this Lambda:
    - All {{$.Custom.*}} variables resolve to empty strings
    - ARIA cannot greet the customer by name
    - ARIA does not know the authentication state
    - ARIA does not know about vulnerability flags
    - ARIA does not receive prior session context

WHAT this Lambda injects
-------------------------
Core session variables (always injected):
    sessionId          — Wisdom session ARN (resolved from the contact)
    customerId         — Customer ID retrieved from contact attributes
    authStatus         — "authenticated" | "unauthenticated"
    channel            — "voice" | "chat" | "ivr"
    dateTime           — Current UTC ISO timestamp for compliance logging
    instanceId         — Connect instance ID for escalation routing
    locale             — Defaults to "en-GB"

Context variables (injected when customerId is available):
    preferredName      — Customer's preferred first name for greeting
    productSummary     — Natural language sentence describing the customer's products
    vulnerabilityContext — JSON string of vulnerability flags (SILENT)
    priorSummary       — Brief summary of the customer's last interaction
    productContext     — JSON string of masked account/card references

Known contact reasons (injected only for a verified caller):
    hasKnownContactReason    — "true" | "false"
    topContactReason         — Short label of the most likely reason for the contact
    topContactReasonCategory — Routing topic of that reason (matches the routing table)
    contactReasonSummary     — One sentence listing up to three known reasons
    contactReasons           — JSON list of the same reasons with detail and date
    These are disclosed only when an upstream ID&V flow has set the `LoA`
    contact attribute, and only reasons whose minimum level that LoA meets.
    A caller recognised by phone number alone receives none, unless CLI_MATCH_LOA
    is set as an explicit opt-in for test and demo use.

ID&V pass-through (optional — set by an upstream ID&V flow)
-----------------------------------------------------------
If an upstream flow has already identified and verified the caller (for example
the ARIA IDV Test Harness in connect-idv-test-harness/), it leaves its result
in contact attributes. When the `idvStatus` attribute is present this Lambda:
    - does NOT fall back to the phone-number lookup, so a caller the ID&V flow
      left unverified is never upgraded to "authenticated" by CLI alone
    - injects loa, idvMethod, cliRelationship, riskScore, reasonCodes and
      idvStatus as {{$.Custom.*}} so the AI prompt can see the assurance level
A contact that never went through an ID&V flow behaves as before by default: a
phone match earns no level, no contact reasons and no payments. Setting
CLI_MATCH_LOA (for example "3") is an explicit opt-in that gives such a caller
that level with idvMethod "cli_match", so a direct call and a call through the
ID&V flow behave the same. Use it for test and demo only.

ENVIRONMENT VARIABLES
----------------------
Required:
    ASSISTANT_ID       — Q Connect assistant ID (from the Connect console →
                         Amazon Q in Connect → Assistants)

Optional:
    INSTANCE_ID        — Connect instance ID; derived from event InstanceARN if not set
    AWS_REGION         — Defaults to eu-west-2
    CRM_API_ENDPOINT   — HTTP endpoint of your CRM API. If unset, stub data is used.
    MEMORY_TABLE_NAME  — DynamoDB table name for prior session summaries. If unset, skipped.
    TRANSCRIPT_TABLE_NAME — DynamoDB table for cross-channel transcripts. Default: aria-transcript-store
    CLI_MATCH_LOA      — OPT-IN. Level of assurance for a caller recognised by phone
                         number alone on a contact with no upstream ID&V. Default ""
                         (no level). "3" makes a direct call behave like one that
                         passed ID&V. Test and demo use only: caller ID can be spoofed.

IAM PERMISSIONS REQUIRED (on the Lambda execution role)
---------------------------------------------------------
    connect:DescribeContact          on arn:aws:connect:*:ACCOUNT:instance/*
    connect:GetContactAttributes     on arn:aws:connect:*:ACCOUNT:instance/*
    qconnect:UpdateSessionData       on arn:aws:wisdom:*:ACCOUNT:assistant/*
    wisdom:UpdateSessionData         on arn:aws:wisdom:*:ACCOUNT:assistant/*
    dynamodb:GetItem                 on arn:aws:dynamodb:*:ACCOUNT:table/* (optional)

Amazon Connect must also be granted lambda:InvokeFunction on this Lambda:
    aws lambda add-permission \\
        --function-name aria-session-injector-qconnect \\
        --statement-id ConnectInvoke \\
        --action lambda:InvokeFunction \\
        --principal connect.amazonaws.com \\
        --source-account <ACCOUNT_ID>

OFFICIAL AWS REFERENCES
------------------------
    Connect Lambda integration:
        https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html
    Q Connect UpdateSessionData API:
        https://docs.aws.amazon.com/connect/latest/APIReference/API_amazon-q-connect_UpdateSessionData.html
    Q Connect session data in AI prompts:
        https://docs.aws.amazon.com/connect/latest/adminguide/customize-connect-ai-agents.html
    Contact flow event format:
        https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html#function-contact-flow-event-data
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
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
ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "")          # REQUIRED: Q Connect assistant ID
AWS_REGION: str = os.environ.get("AWS_REGION", "eu-west-2")
CRM_API_ENDPOINT: str = os.environ.get("CRM_API_ENDPOINT", "")  # Empty = use stub data
MEMORY_TABLE_NAME: str = os.environ.get("MEMORY_TABLE_NAME", "") # Empty = skip prior summary
TRANSCRIPT_TABLE_NAME: str = os.environ.get("TRANSCRIPT_TABLE_NAME", "aria-transcript-store")

# Level of assurance given to a caller who is recognised by phone number alone,
# on a contact that did NOT come through an ID&V flow.
#
# Default "": a phone match earns NO level, so no contact reasons are released
# and no payment can be started. A calling number can be borrowed, shared or
# spoofed, so it is a claim about a line, not proof about a person.
#
# Setting it (for example "3") is an explicit opt-in for test and demo use. It
# makes a direct call behave like one that passed ID&V. Do not set it where the
# calling number is not otherwise verified.
CLI_MATCH_LOA: str = os.environ.get("CLI_MATCH_LOA", "").strip()

# ---------------------------------------------------------------------------
# AWS clients — eagerly initialised at module load time so the SDK connection
# pool and credential resolution happen during the cold-start phase, not on
# the first in-handler call.  Warm invocations reuse the same client objects.
# ---------------------------------------------------------------------------
_connect_client = boto3.client("connect", region_name=AWS_REGION, config=_BOTO_CONFIG)
_qconnect_client = boto3.client("qconnect", region_name=AWS_REGION, config=_BOTO_CONFIG)
_dynamodb_client = boto3.client("dynamodb", region_name=AWS_REGION, config=_BOTO_CONFIG)

# Circuit breaker: flipped to True when the DynamoDB memory table is confirmed
# missing so subsequent invocations skip the wasteful API call immediately.
_memory_table_unavailable: bool = False


def _get_connect() -> Any:
    return _connect_client


def _get_qconnect() -> Any:
    return _qconnect_client


def _get_dynamodb() -> Any:
    return _dynamodb_client


# ---------------------------------------------------------------------------
# Phone number → customer ID mapping (test/dev only)
# ---------------------------------------------------------------------------
_PHONE_TO_CUSTOMER: dict[str, str] = {
    "+447765309252": "CUST-001",   # Developer / admin test number → James Hartley
    "07765309252":   "CUST-001",   # Same number — UK national format fallback
    "+447700900001": "CUST-002",   # Test: Sarah Chen (financial difficulty)
    "+447700900002": "CUST-003",   # Test: Margaret Okonkwo (bereavement)
    "+447700900003": "CUST-004",   # Test: Daniel Walsh (mental health)
    "+447700900004": "CUST-005",   # Test: Ethel Parsons (elderly)
}


def _normalise_phone(phone: str) -> str:
    """Normalise a UK phone number to E.164 (+44...) for consistent lookup.
    Connect always sends E.164, but this guards against any edge cases."""
    phone = phone.strip().replace(" ", "").replace("-", "")
    if phone.startswith("07") and len(phone) == 11:
        return "+44" + phone[1:]
    return phone


def _mask_phone(phone: str) -> str:
    """Return phone masked to last 4 digits: ***-**-1234"""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) >= 4:
        return f"***-**-{digits[-4:]}"
    return "***"


# ---------------------------------------------------------------------------
# Stub customer registry
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
# A caller recognised by phone number alone gets none, unless CLI_MATCH_LOA has
# been set as an explicit opt-in (see the handler).
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


# A contact started from the Money Hub page (connect-money-hub) carries entry=money_hub and the tab the
# customer had open. That is their reason for getting in touch, so it is offered to ARIA as the known contact
# reason: ARIA's prompt can then open with the Money Hub at once, on a call as well as in a chat.
MONEY_HUB_TABS = {"out": "Money out", "in": "Money in", "expected": "Expected", "transactions": "Transactions",
                  "goals": "Goals"}


def _money_hub_reason_vars(entry: str, view: str) -> dict[str, str]:
    if entry != "money_hub":
        return {}
    tab = MONEY_HUB_TABS.get(view, "Money out")
    return {
        "hasKnownContactReason": "true",
        "topContactReason": f"their Money Hub ({tab} tab)",
        "topContactReasonCategory": "money_hub",
        "contactReasonSummary": f"Money Hub: the customer started this from their Money Hub page, on the {tab} tab, "
                                "to understand their money.",
        "contactReasons": "",
    }



# ---------------------------------------------------------------------------
# Q Connect session resolution
# ---------------------------------------------------------------------------

def _resolve_wisdom_session_id(instance_id: str, contact_id: str) -> str:
    """
    Resolve the Q Connect (Wisdom) session ARN for the given contact.

    The Q Connect session is created by the "Connect assistant" block in the
    contact flow. The session UUID (required by UpdateSessionData) is stored in
    Contact.WisdomInfo.SessionArn and is DIFFERENT from the ContactId.

    ARN format: arn:aws:wisdom:REGION:ACCOUNT:session/ASSISTANT_ID/SESSION_UUID

    We call DescribeContact to retrieve the ARN. The Q Connect API accepts either
    the UUID alone or the full ARN as sessionId — we return the full ARN.

    Returns contact_id as fallback if DescribeContact fails so the caller can
    still log the error and continue.

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
            return session_arn
        else:
            logger.error(
                "WisdomInfo.SessionArn not found on contact. "
                "Ensure the 'Connect assistant' block ran BEFORE this Lambda in the contact flow. "
                "The Wisdom session is created by that block."
            )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "Unknown")
        logger.error(
            f"DescribeContact failed [{code}]: {e}. "
            "Cannot resolve Q Connect session ARN. "
            "Check connect:DescribeContact IAM permission on this Lambda's role."
        )

    return contact_id  # fallback — downstream injection will fail with ResourceNotFoundException


# ---------------------------------------------------------------------------
# CRM lookup
# ---------------------------------------------------------------------------

def _lookup_customer(customer_id: str) -> dict | None:
    """
    Look up a customer record by ID.

    Returns stub data from _STUB_CUSTOMERS. In production, replace this with a
    real CRM API call using CRM_API_ENDPOINT.
    """
    if CRM_API_ENDPOINT:
        logger.warning("CRM_API_ENDPOINT is set but real CRM call not yet implemented. Falling back to stub.")

    return _STUB_CUSTOMERS.get(customer_id)


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _build_product_summary(customer: dict) -> str:
    """
    Build a natural-language sentence describing the customer's products.
    Injected as {{$.Custom.productSummary}}.

    Example: "James has a current account ending 4821, a savings account,
              a Visa debit card ending 4821, and a Mastercard credit card."
    """
    parts: list[str] = []

    for acct in customer.get("accounts", []):
        if acct["type"] == "current":
            parts.append(f"a current account ending {acct['masked'][-4:]}")
        elif acct["type"] == "savings":
            parts.append(f"a savings account ({acct['nickname']})")
        else:
            parts.append(f"a {acct['type']} account")

    for card in customer.get("cards", []):
        scheme = card.get("scheme", "")
        ctype  = card.get("type", "")
        last4  = card.get("last_four", "****")
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
    Injected as {{$.Custom.productContext}}.
    """
    return json.dumps({
        "accounts":  customer.get("accounts", []),
        "cards":     customer.get("cards", []),
        "mortgages": customer.get("mortgages", []),
    }, default=str)


def _build_vulnerability_context(customer: dict) -> str:
    """
    Build a JSON string of vulnerability flags.
    Injected as {{$.Custom.vulnerabilityContext}}.
    ARIA's system prompt instructs it to read this SILENTLY — never disclose.
    """
    vuln = customer.get("vulnerability")
    if not vuln:
        return ""
    return json.dumps(vuln, default=str)


def _lookup_prior_summary(customer_id: str, session_id: str) -> str:
    """
    Retrieve the summary of the customer's most recent prior session from DynamoDB.
    Injected as {{$.Custom.priorSummary}}.

    DynamoDB schema:
        PK: CUSTOMER#<customer_id>
        SK: LAST_SESSION_SUMMARY
        summary: "Customer asked about their balance and requested a statement."

    A module-level circuit breaker (_memory_table_unavailable) is set on the
    first ResourceNotFoundException so subsequent invocations skip the call
    entirely rather than wasting ~160 ms on a known-missing table.
    """
    global _memory_table_unavailable

    if not MEMORY_TABLE_NAME or _memory_table_unavailable:
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
        code = e.response.get("Error", {}).get("Code", "Unknown")
        if code == "ResourceNotFoundException":
            _memory_table_unavailable = True
            logger.error(
                f"DynamoDB table {MEMORY_TABLE_NAME!r} does not exist. "
                "Disabling prior summary lookups for the lifetime of this container. "
                "Either create the table or unset MEMORY_TABLE_NAME to silence this error."
            )
        else:
            logger.warning(f"DynamoDB lookup for prior summary failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Cross-channel transcript retrieval
# ---------------------------------------------------------------------------

def _get_cross_channel_transcript(flow_attributes: dict) -> dict:
    """
    Detect cross-channel transfers and retrieve the prior channel's transcript.

    Returns extra session variables to inject (priorTranscript, priorSummary,
    priorChannel, priorContactId) if a transfer source attribute is set.
    """
    if not TRANSCRIPT_TABLE_NAME:
        return {}

    chat_transfer_source  = flow_attributes.get("chatTransferSource", "")
    voice_transfer_source = flow_attributes.get("voiceTransferSource", "")

    prior_contact_id = ""
    prior_channel    = ""

    if chat_transfer_source == "voice":
        prior_contact_id = flow_attributes.get("voiceContactId", "")
        prior_channel    = "voice"
    elif voice_transfer_source == "chat":
        prior_contact_id = flow_attributes.get("chatContactId", "")
        prior_channel    = "chat"

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
                f"Cross-channel transcript not found for contactId={prior_contact_id!r}. "
                "The transfer Lambda may not have stored it yet, or it expired."
            )
            return {}

        return {
            "priorTranscript": item.get("transcript", {}).get("S", ""),
            "priorSummary":    item.get("summary",    {}).get("S", ""),
            "priorChannel":    prior_channel,
            "priorContactId":  prior_contact_id,
        }

    except Exception as exc:
        logger.error(f"Failed to retrieve cross-channel transcript: {exc}")
        return {}


# ---------------------------------------------------------------------------
# Q Connect session data injection
# ---------------------------------------------------------------------------

def _inject_session_data(
    assistant_id: str,
    session_id: str,
    data: dict[str, str],
) -> bool:
    """
    Call the Q Connect UpdateSessionData API to inject key-value pairs into the
    session so that {{$.Custom.*}} prompt template variables are populated.

    All values must be strings — Q Connect session data only supports strings.

    Official API reference:
        https://docs.aws.amazon.com/connect/latest/APIReference/API_amazon-q-connect_UpdateSessionData.html

    The Q Connect session must already exist (created by the "Connect assistant"
    block) before this function is called.

    Args:
        assistant_id: Q Connect assistant ID (from ASSISTANT_ID env var)
        session_id:   Wisdom session ARN resolved by _resolve_wisdom_session_id()
        data:         Dict of key → value (all strings) to inject as {{$.Custom.*}}

    Returns:
        True on success, False on any error
    """
    # Build the RuntimeSessionData payload
    # Ref: https://docs.aws.amazon.com/connect/latest/APIReference/API_amazon-q-connect_RuntimeSessionData.html
    session_data_payload = [
        {"key": k, "value": {"stringValue": str(v)}}
        for k, v in data.items()
        if v is not None and v != ""
    ]

    if not session_data_payload:
        logger.warning("No session data to inject (all values were empty).")
        return True

    logger.info(
        f"Injecting {len(session_data_payload)} keys into Q Connect session: "
        f"assistant={assistant_id} session={session_id} "
        f"keys={[d['key'] for d in session_data_payload]}"
    )

    try:
        _get_qconnect().update_session_data(
            assistantId=assistant_id,
            sessionId=session_id,
            data=session_data_payload,
        )
        logger.info("Q Connect session data injected successfully.")
        return True

    except ClientError as e:
        code    = e.response.get("Error", {}).get("Code", "Unknown")
        message = e.response.get("Error", {}).get("Message", str(e))

        if code == "ResourceNotFoundException":
            logger.error(
                f"Q Connect session not found: sessionId={session_id!r}. "
                "This usually means this Lambda ran BEFORE the 'Connect assistant' block. "
                "Re-order the contact flow: Connect assistant → this Lambda."
            )
        elif code == "AccessDeniedException":
            logger.error(
                "Access denied calling UpdateSessionData. "
                "Add qconnect:UpdateSessionData AND wisdom:UpdateSessionData to the Lambda "
                f"IAM role for resource arn:aws:wisdom:*:*:assistant/{assistant_id}."
            )
        elif code == "ValidationException":
            logger.error(
                f"Validation error from UpdateSessionData [{message}]. "
                "One or more values may exceed Q Connect's per-key length limit (1024 chars). "
                "Truncate productContext or priorSummary if necessary."
            )
        else:
            logger.error(f"UpdateSessionData failed [{code}]: {message}")

        return False


# ---------------------------------------------------------------------------
# Main Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict, context: Any) -> dict:
    """
    Entry point. Called by Amazon Connect via the "Invoke AWS Lambda function" block.

    This variant ALWAYS attempts Q Connect session injection. ASSISTANT_ID is
    required — the handler returns an error immediately if it is not set.

    The handler never raises an exception. All errors are caught and logged.
    On injection failure the contact flow continues but {{$.Custom.*}} variables
    will be empty in the AI prompt.

    Returns:
        Dict with keys: sessionId (Wisdom ARN), status, customerId, authStatus,
        channel, and all context fields (preferredName, productSummary, etc.)
        These are available as $.External.* in the next contact flow block.
    """
    logger.info(f"Session injector (Q Connect) invoked: {json.dumps(event, default=str)}")

    # ── Guard: ASSISTANT_ID must be set ──────────────────────────────────────
    if not ASSISTANT_ID:
        logger.error(
            "ASSISTANT_ID environment variable is not set. "
            "This Lambda variant requires Q Connect — set ASSISTANT_ID to the "
            "Q Connect assistant ID from the Connect console."
        )
        return {"status": "error", "reason": "missing_assistant_id"}

    # ── 1. Extract contact data ───────────────────────────────────────────────
    contact_data: dict  = event.get("Details", {}).get("ContactData", {})
    contact_id: str     = contact_data.get("ContactId", "")
    instance_arn: str   = contact_data.get("InstanceARN", "")
    instance_id: str    = os.environ.get("INSTANCE_ID", "") or instance_arn.split("instance/")[-1]
    raw_channel: str    = contact_data.get("Channel", "VOICE")

    channel_map  = {"VOICE": "voice", "CHAT": "chat", "TASK": "chat"}
    aria_channel = channel_map.get(raw_channel.upper(), "voice")

    flow_attributes: dict = contact_data.get("Attributes", {}) or {}

    # Amazon Connect's hosted widget prefixes contactAttributes with "HostedWidget-".
    # Read plain key first, fall back to the prefixed version.
    def _attr(key: str, default: str = "") -> str:
        return flow_attributes.get(key) or flow_attributes.get(f"HostedWidget-{key}", default)

    customer_id: str = _attr("customerId")
    auth_status: str = _attr("authStatus", "unauthenticated")
    locale: str      = _attr("locale", "en-GB")

    if not contact_id:
        logger.error("ContactId is missing from event. Cannot process session.")
        return {"status": "error", "reason": "missing_contact_id"}

    # ── Upstream ID&V result (optional) ───────────────────────────────────────
    # Set by an ID&V flow that ran before this one. Its presence means the
    # caller's identity has already been decided upstream, so CLI must not
    # override that decision below.
    idv_status: str = _attr("idvStatus")
    idv_vars: dict[str, str] = {
        "loa":             _attr("LoA"),
        "idvStatus":       idv_status,
        "idvMethod":       _attr("idvMethod"),
        "cliRelationship": _attr("cliRelationship"),
        "riskScore":       _attr("riskScore"),
        "reasonCodes":     _attr("reasonCodes"),
    } if idv_status else {}
    idv_loa: int | None = _parse_loa(_attr("LoA")) if idv_status else None

    # ── Phone-based customer lookup (dev/test fallback) ───────────────────────
    caller_phone: str = (contact_data.get("CustomerEndpoint") or {}).get("Address", "")
    if idv_status and not customer_id:
        logger.info("Upstream ID&V left this contact %r — skipping phone lookup", idv_status)
    elif not customer_id and caller_phone:
        normalised_phone = _normalise_phone(caller_phone)
        resolved = _PHONE_TO_CUSTOMER.get(normalised_phone) or _PHONE_TO_CUSTOMER.get(caller_phone, "")
        if resolved:
            customer_id = resolved
            auth_status = "authenticated"
            # No ID&V flow ran. Only if explicitly opted in, treat the phone
            # match as the configured level, and say plainly how it was reached.
            if CLI_MATCH_LOA:
                idv_loa = _parse_loa(CLI_MATCH_LOA)
                idv_vars = {"loa": CLI_MATCH_LOA, "idvStatus": "cli_match",
                            "idvMethod": "cli_match", "cliRelationship": "MATCH"}
            logger.info("Resolved customerId=%r from phone=%s (normalised=%s)", customer_id, _mask_phone(caller_phone), _mask_phone(normalised_phone))
        else:
            logger.info("Caller phone %s has no mapped customerId — unauthenticated session", _mask_phone(caller_phone))

    # ── 2 + 4(prior summary) + 4b: Fan-out independent I/O calls ─────────────
    # _resolve_wisdom_session_id  → DescribeContact API
    # _lookup_prior_summary       → DynamoDB GetItem  (doesn't need the ARN)
    # _get_cross_channel_transcript → DynamoDB GetItem
    # All three are independent; run them concurrently to cut sequential wait.
    with ThreadPoolExecutor(max_workers=3) as _pool:
        _future_session_arn   = _pool.submit(_resolve_wisdom_session_id, instance_id, contact_id)
        _future_prior_summary = (
            _pool.submit(_lookup_prior_summary, customer_id, "")
            if customer_id and MEMORY_TABLE_NAME and not _memory_table_unavailable
            else None
        )
        _future_cross_channel = _pool.submit(_get_cross_channel_transcript, flow_attributes)

        session_id: str    = _future_session_arn.result()
        prior_summary: str = _future_prior_summary.result() if _future_prior_summary else ""
        cross_channel_vars: dict = _future_cross_channel.result()

    logger.info(
        f"Contact: id={contact_id} wisdomSession={session_id!r} "
        f"channel={aria_channel} customerId={customer_id!r} authStatus={auth_status!r}"
    )

    # ── 3. Build base session variables ──────────────────────────────────────
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
    # Empty values are dropped by _inject_session_data, so this is a no-op for
    # contacts that never went through an ID&V flow.
    session_vars.update(idv_vars)

    # ── 4. Enrich with customer context ──────────────────────────────────────
    if customer_id:
        customer = _lookup_customer(customer_id)

        if customer:
            preferred_name        = customer.get("preferred_name", "")
            product_summary       = _build_product_summary(customer)
            product_context       = _build_product_context(customer)
            vulnerability_context = _build_vulnerability_context(customer)
            # prior_summary already fetched concurrently in the fan-out above

            session_vars.update({
                "preferredName":        preferred_name,
                "productSummary":       product_summary,
                "productContext":       product_context,
                "vulnerabilityContext": vulnerability_context,
                "priorSummary":         prior_summary,
            })
            reason_vars = _build_contact_reason_vars(customer_id, auth_status, idv_loa)
            reason_vars.update(_money_hub_reason_vars(_attr("entry"), _attr("moneyHubView")))
            session_vars.update(reason_vars)

            logger.info(
                f"Customer context built: name={preferred_name!r} "
                f"vulnerability={'yes' if vulnerability_context else 'none'} "
                f"priorSummary={'yes' if prior_summary else 'none'} "
                f"knownContactReason={reason_vars['hasKnownContactReason']} (LoA={idv_loa})"
            )
        else:
            logger.warning(f"Customer ID {customer_id!r} not found in CRM. Injecting base variables only.")
            session_vars.update({
                "preferredName": "", "productSummary": "",
                "productContext": "", "vulnerabilityContext": "", "priorSummary": "",
            })
    else:
        logger.info("No customerId — injecting base session variables only (phone=%s)", _mask_phone(caller_phone))

    # ── 4b. Cross-channel transfer context ────────────────────────────────────
    # cross_channel_vars already fetched concurrently in the fan-out above
    if cross_channel_vars:
        session_vars.update(cross_channel_vars)
        logger.info(
            f"Cross-channel context injected: priorChannel={cross_channel_vars.get('priorChannel')!r} "
            f"priorContactId={cross_channel_vars.get('priorContactId')!r}"
        )

    # ── 5. Inject into Q Connect session (REQUIRED in this variant) ───────────
    # All session_vars are written to {{$.Custom.*}} in the AI prompt template.
    q_connect_success = _inject_session_data(
        assistant_id=ASSISTANT_ID,
        session_id=session_id,
        data=session_vars,
    )

    injected_keys = list(session_vars.keys())

    # Return all context fields so the contact flow (Block 5) can also store
    # them as contact attributes → Lex session attributes → AgentCore payload.
    # ALL values MUST be strings — Connect ResponseType=STRING_MAP rejects any non-string.
    result = {
        "sessionId":            session_id,
        "customerId":           customer_id,
        "status":               "injected" if q_connect_success else "partial_failure",
        "injectedKeys":         ",".join(injected_keys),
        "channel":              aria_channel,
        "authStatus":           auth_status,
        # Context variables
        "preferredName":        session_vars.get("preferredName", ""),
        "productSummary":       session_vars.get("productSummary", ""),
        "productContext":       session_vars.get("productContext", ""),
        "vulnerabilityContext": session_vars.get("vulnerabilityContext", ""),
        "priorSummary":         session_vars.get("priorSummary", ""),
        # Cross-channel transfer context
        "priorChannel":         session_vars.get("priorChannel", ""),
        "priorContactId":       session_vars.get("priorContactId", ""),
        "priorTranscript":      session_vars.get("priorTranscript", ""),
        # Core metadata
        "locale":               session_vars.get("locale", locale),
        "dateTime":             session_vars.get("dateTime", ""),
        "instanceId":           session_vars.get("instanceId", instance_id),
        # Known contact reasons (empty unless an upstream ID&V flow verified the caller)
        "hasKnownContactReason":    session_vars.get("hasKnownContactReason", "false"),
        "topContactReason":         session_vars.get("topContactReason", ""),
        "topContactReasonCategory": session_vars.get("topContactReasonCategory", ""),
        "contactReasonSummary":     session_vars.get("contactReasonSummary", ""),
        "contactReasons":           session_vars.get("contactReasons", ""),
        # Upstream ID&V result (empty strings when no ID&V flow ran)
        "loa":                  idv_vars.get("loa", ""),
        "idvStatus":            idv_vars.get("idvStatus", ""),
    }

    if not q_connect_success:
        logger.error(
            "Q Connect session injection failed. AI prompt variables ({{$.Custom.*}}) will be "
            "empty for this session. ARIA will still work via the Lex/AgentCore path. "
            "Check CloudWatch logs for the specific error above."
        )

    logger.info(f"Session injector (Q Connect) complete: status={result['status']!r} "
                f"keys={injected_keys}")
    return result
