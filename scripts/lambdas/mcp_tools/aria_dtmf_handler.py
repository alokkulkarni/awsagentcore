"""
aria_dtmf_handler.py — DTMF Secure Collection MCP Tool

Meridian Bank / ARIA AgentCore MCP Gateway

Exposes one tool to the ARIA AI agent:

  initiate_dtmf_card_capture
    Called by ARIA when it needs to securely collect a card number, PIN,
    or account number from the customer via encrypted DTMF tones. The digits
    are never heard by any party — they are encrypted by Amazon Connect before
    leaving the telephony layer. ARIA cannot and must not ask the customer to
    speak card numbers aloud.

HOW THE BRIDGE ACTION WORKS
────────────────────────────
  1. ARIA calls this tool with purpose (e.g. "card_last_four").
  2. This Lambda writes  dtmf_collection_requested = "true"  plus the
     collection parameters into the Amazon Connect contact attributes.
  3. The Lex fulfillment Lambda (aria_connect_fulfillment.py) checks contact
     attributes after every AgentCore call. When it sees
     dtmf_collection_requested == "true" it:
       a. Clears the flag.
       b. Returns the CollectCardDetails Lex intent to Amazon Connect.
  4. The Amazon Connect contact flow detects CollectCardDetails and transfers
     to the ARIA-DTMF-SecureCollection sub-flow.
  5. After the sub-flow completes, the results (dtmf_masked, dtmf_result,
     dtmf_card_type, …) are written to contact attributes which become Lex
     session attributes on the next turn.
  6. ARIA reads those session attributes and resumes the conversation.

This design keeps routing logic in the contact flow where it belongs, while
giving ARIA a clean, intent-based tool interface.

MCP Gateway target configuration
──────────────────────────────────
  Lambda function: aria-banking-mcp-dtmf-prod
  Tool:            initiate_dtmf_card_capture

Environment variables (set by deploy_mcp_gateway.sh)
──────────────────────────────────────────────────────
  CONNECT_INSTANCE_ID   Amazon Connect instance ID (UUID)
  CONNECT_KEY_ID        RSA public-key ID from Connect Security Keys
  AWS_REGION            defaults to eu-west-2
"""

from __future__ import annotations

import json
import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Environment / clients (module-level — reused across warm Lambda invocations)
# ---------------------------------------------------------------------------
CONNECT_INSTANCE_ID = os.environ.get("CONNECT_INSTANCE_ID", "")
CONNECT_KEY_ID      = os.environ.get("CONNECT_KEY_ID", "")
AWS_REGION          = os.environ.get("AWS_REGION", "eu-west-2")

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

_connect_client = None


def _get_connect():
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=AWS_REGION, config=_BOTO_CONFIG)
    return _connect_client


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _tool_initiate_dtmf_card_capture(params: dict) -> dict:
    """
    Signal that ARIA needs secure DTMF card capture.

    Parameters
    ──────────
    contact_id  : str   — Amazon Connect ContactId (= AgentCore session ID)
    purpose     : str   — What is being collected:
                            "card_last_four"     last 4 digits of card
                            "full_card_number"   full 16-digit PAN
                            "expiry_date"        MMYY
                            "cvv"                3-digit CVV
                            "pin"                4-digit PIN
                            "account_number"     8-digit account number
                            "sort_code"          6-digit sort code (no dashes)
    digit_count : int   — Expected digit count (used by sub-flow for validation)
                          Omit or set 0 to use the default for the purpose.
    customer_id : str   — Optional; forwarded so sub-flow can run ownership check.

    Returns
    ───────
    A dict with:
      status          "initiated" on success, "error" if Connect call failed
      message         Customer-facing script ARIA should read aloud
      bridge_action   Always "DTMF_COLLECT" — intercepted by fulfillment Lambda
      purpose         Echo of the requested purpose
    """
    contact_id  = params.get("contact_id",  "")
    purpose     = params.get("purpose",     "card_last_four")
    digit_count = int(params.get("digit_count", 0))
    customer_id = params.get("customer_id", "")

    # Derive expected digit count from purpose when not supplied
    _purpose_digit_map = {
        "card_last_four":   4,
        "full_card_number": 16,
        "expiry_date":      4,
        "cvv":              3,
        "pin":              4,
        "account_number":   8,
        "sort_code":        6,
    }
    if digit_count == 0:
        digit_count = _purpose_digit_map.get(purpose, 4)

    # Customer-facing script (ARIA reads this aloud before the sub-flow starts)
    _purpose_script = {
        "card_last_four":   (
            "I'll briefly transfer you to our secure input system. "
            "When prompted, please use your telephone keypad to enter "
            "the last four digits of your card. I'll pick up the conversation "
            "as soon as that's done."
        ),
        "full_card_number": (
            "To keep your card number completely secure, I'll transfer you to "
            "our encrypted keypad for a moment. Please enter all sixteen digits "
            "of your card using the telephone keypad when prompted."
        ),
        "expiry_date":      (
            "Please enter your card's expiry date using the keypad — "
            "four digits, month then year, for example 0128 for January 2028."
        ),
        "cvv":              (
            "Please enter the three-digit security code from the back of "
            "your card using the telephone keypad."
        ),
        "pin":              (
            "I'll transfer you to our secure PIN entry system now. "
            "Please enter your four-digit PIN using the telephone keypad."
        ),
        "account_number":   (
            "Please enter your eight-digit account number using the telephone keypad."
        ),
        "sort_code":        (
            "Please enter your six-digit sort code using the telephone keypad — "
            "numbers only, no dashes."
        ),
    }
    script = _purpose_script.get(
        purpose,
        "I'll transfer you to our secure keypad entry system briefly. "
        "Please enter the digits when prompted."
    )

    # Write contact attributes so the sub-flow is fully configured when it runs
    contact_attrs: dict[str, str] = {
        "dtmf_collection_requested": "true",
        "collectionPurpose":         purpose,
        "dtmf_expected_digits":      str(digit_count),
        "dtmf_status":               "awaiting_trigger",
    }
    if CONNECT_KEY_ID:
        contact_attrs["connectKeyId"] = CONNECT_KEY_ID
    if customer_id:
        contact_attrs["dtmf_customer_id"] = customer_id

    if contact_id and CONNECT_INSTANCE_ID:
        try:
            _get_connect().update_contact_attributes(
                InitialContactId=contact_id,
                InstanceId=CONNECT_INSTANCE_ID,
                Attributes=contact_attrs,
            )
            logger.info(
                "DTMF capture initiated: contact=%s purpose=%s digits=%d",
                contact_id, purpose, digit_count,
            )
        except ClientError as exc:
            logger.error("Failed to set DTMF contact attributes: %s", exc)
            return {
                "status":        "error",
                "error_message": f"Could not configure secure capture: {exc}",
                "bridge_action": "DTMF_COLLECT",
                "purpose":       purpose,
            }
    else:
        logger.warning(
            "DTMF initiate called without contact_id or CONNECT_INSTANCE_ID — "
            "contact attributes not written; bridge action still returned so "
            "the fulfillment Lambda can route via session attribute fallback."
        )

    return {
        "status":        "initiated",
        "message":       script,
        "bridge_action": "DTMF_COLLECT",
        "purpose":       purpose,
        "digit_count":   digit_count,
    }


# ---------------------------------------------------------------------------
# MCP Gateway dispatcher
# ---------------------------------------------------------------------------

#: Maps the tool name (as declared in the MCP gateway schema) to its handler.
TOOL_DISPATCH = {
    "initiate_dtmf_card_capture": _tool_initiate_dtmf_card_capture,
}


def _parse_tool_call(event: dict) -> tuple[str, dict]:
    """
    Extract tool name and parameters from an MCP gateway invocation event.

    The MCP gateway wraps the tool call in one of two shapes depending on
    whether the domain Lambda is invoked directly or via the gateway router:

      Shape A (gateway router):
        { "tool": "domainname___toolname", "parameters": { … } }

      Shape B (direct invocation / test):
        { "tool": "toolname", "parameters": { … } }

    Returns (tool_name_without_domain_prefix, parameters_dict).
    """
    raw_tool = event.get("tool", "") or event.get("name", "")
    # Strip domain prefix (e.g. "dtmf___initiate_dtmf_card_capture" → "initiate_dtmf_card_capture")
    tool_name = raw_tool.split("___", 1)[-1] if "___" in raw_tool else raw_tool

    params = event.get("parameters", {}) or event.get("input", {}) or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except json.JSONDecodeError:
            params = {}

    return tool_name, params


def lambda_handler(event, context):
    logger.info("DTMF handler invoked: %s", json.dumps(event, default=str))

    tool_name, params = _parse_tool_call(event)
    logger.info("Tool: %s  Params: %s", tool_name, params)

    handler_fn = TOOL_DISPATCH.get(tool_name)
    if handler_fn is None:
        logger.error("Unknown tool: %r — registered tools: %s", tool_name, list(TOOL_DISPATCH))
        return {
            "error":   f"Unknown tool '{tool_name}'",
            "tools":   list(TOOL_DISPATCH),
        }

    result = handler_fn(params)
    logger.info("Tool result: %s", json.dumps(result, default=str))
    return result
