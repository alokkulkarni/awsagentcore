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
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Configuration — override via environment variables in the Lambda console
# ---------------------------------------------------------------------------
ASSISTANT_ID: str = os.environ.get("ASSISTANT_ID", "")  # REQUIRED: Q Connect assistant ID
AWS_REGION: str = os.environ.get("AWS_REGION", "eu-west-2")
CRM_API_ENDPOINT: str = os.environ.get("CRM_API_ENDPOINT", "")  # Empty = use stub data
MEMORY_TABLE_NAME: str = os.environ.get("MEMORY_TABLE_NAME", "")  # Empty = skip prior summary

# ---------------------------------------------------------------------------
# AWS clients — initialised once per Lambda container lifecycle
# ---------------------------------------------------------------------------
_connect_client = None
_qconnect_client = None
_dynamodb_client = None


def _get_connect() -> Any:
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=AWS_REGION)
    return _connect_client


def _get_qconnect() -> Any:
    global _qconnect_client
    if _qconnect_client is None:
        _qconnect_client = boto3.client("qconnect", region_name=AWS_REGION)
    return _qconnect_client


def _get_dynamodb() -> Any:
    global _dynamodb_client
    if _dynamodb_client is None:
        _dynamodb_client = boto3.client("dynamodb", region_name=AWS_REGION)
    return _dynamodb_client


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
# CRM lookup
# ---------------------------------------------------------------------------

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

def lambda_handler(event: dict, context: Any) -> dict:
    """
    Entry point. Called by Amazon Connect via the "Invoke AWS Lambda function" block.

    The handler NEVER raises an exception. All errors are caught and logged.
    If injection fails, we return a partial success so the contact flow continues —
    ARIA will still work, but without pre-injected context.

    Official Lambda integration reference:
        https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html

    Returns:
        Dict with keys: sessionId, status, customerId, injectedKeys
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

    # Session ID is the ContactId — this is the session created by the Connect assistant block
    session_id: str = contact_id

    if not session_id:
        logger.error("ContactId is missing from event. Cannot inject session data.")
        return {"status": "error", "reason": "missing_contact_id"}

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

            logger.info(
                f"Customer context built: name={preferred_name!r} "
                f"vulnerability={'yes' if vulnerability_context else 'none'} "
                f"priorSummary={'yes' if prior_summary else 'none'}"
            )
        else:
            logger.warning(f"Customer ID {customer_id!r} not found in CRM. Injecting base variables only.")
            session_vars["preferredName"] = ""
            session_vars["productSummary"] = ""
            session_vars["productContext"] = ""
            session_vars["vulnerabilityContext"] = ""
            session_vars["priorSummary"] = ""
    else:
        logger.info("No customerId in contact attributes — injecting base session variables only.")

    # ----------------------------------------------------------------
    # 4. Inject into Q Connect session
    # ----------------------------------------------------------------
    success = _inject_session_data(
        assistant_id=ASSISTANT_ID,
        session_id=session_id,
        data=session_vars,
    )

    injected_keys = list(session_vars.keys())
    result = {
        "sessionId":     session_id,
        "customerId":    customer_id,
        "status":        "injected" if success else "partial_failure",
        "injectedKeys":  injected_keys,
        "channel":       aria_channel,
        "authStatus":    auth_status,
    }

    if not success:
        logger.error(
            "Session data injection failed. ARIA will operate without pre-injected context. "
            "The contact flow will continue normally. Check CloudWatch logs for the error."
        )

    logger.info(f"Session injector complete: {json.dumps(result, default=str)}")
    return result
