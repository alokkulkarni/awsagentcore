"""
aria_card_dispute.py
====================
Card transaction disputes: one Lambda, four ways in (SPEC.md section 6 and Part 4).

    Web       the HTTP API. The customer page, the adviser page, their JSON calls,
              and the CX designer disputes agent's tools (POST /acxd/ops).
    Flow      a Connect flow, when the disputes agent hands the call back. The
              summary and team for ARIA's human hand-over.
    Tool      the MCP gateway. get_card_dispute for agent assist (and ARIA's older tools).
    Internal  the agent-assist Lambda. Lines and a link for the adviser's screen pop.

Which way a request came in is decided by how it arrived, never by what it
asks for:
  - The web check comes first. The HTTP API always wraps a request in its own
    envelope, so nothing sent over the internet can pass itself off as a tool
    call or an internal call.
  - A request the MCP gateway sent is always a tool call, even if its arguments
    ask for the internal operation. The internal operation hands out an adviser
    link, and ARIA must never be able to get one.

ENVIRONMENT VARIABLES
---------------------
    DISPUTE_TABLE_NAME      DynamoDB table. Unset = in-memory, for local runs only
    PUBLIC_BASE_URL         The HTTP API's address, used to build page links
    MERCHANT_DISPUTE_TOPIC  Topic to route "problem with a payment I made" disputes
                            to. Unset = the card's own topic (debit_card / credit_card)
    CONNECT_INSTANCE_ID     Connect instance. Needed by the Live Sync route to find
                            out which customer a contact belongs to
    ACXD_KEY_SECRET_ID      Secrets Manager secret holding the CX designer door's key.
                            Unset = that door answers "not configured"
    TOUCHPOINT_SECRET_ID    Secrets Manager secret holding {"deploymentKey", "apiKey"}
                            for Live Sync. Unset = the page is a view only
    SMS_ORIGINATION_IDENTITY  AWS End User Messaging sender (phone number, sender ID or
                            pool, as its ID or ARN) for texting the form link. Unset =
                            the agent is told it cannot text, and carries on by voice
    SMS_ALLOWED_PREFIXES    Comma-separated number prefixes a text may go to. Default +447
    BANK_NAME               How the text names the sender. Default "Your bank"
    LOG_LEVEL               Default INFO

LOGGING
-------
Operation, outcome and dispute reference only. Never a narrative, merchant,
amount, code, page secret or adviser token.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import dispute_web
from dispute_service import DisputeError, DisputeService
from dispute_store import DynamoStore, MemoryStore

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_TABLE = os.environ.get("DISPUTE_TABLE_NAME", "")
_store = DynamoStore(_TABLE, time.time) if _TABLE else MemoryStore(time.time)
service = DisputeService(_store, time.time, page_url=os.environ.get("PUBLIC_BASE_URL", ""),
                         merchant_topic=os.environ.get("MERCHANT_DISPUTE_TOPIC", ""))

_TOOLS = ("list_card_transactions", "start_card_dispute", "update_card_dispute", "get_card_dispute",
          "attach_dispute_screen")

_secret_cache: dict[str, tuple[float, str]] = {}
SECRET_CACHE_SECONDS = 300


def _secret(secret_id: str) -> str:
    """
    A secret's value, read by this Lambda with its own role at run time and kept
    for five minutes, so a busy page does not call Secrets Manager every time.
    Never logged, and never returned except to the one check that needs it.
    """
    if not secret_id:
        return ""
    kept = _secret_cache.get(secret_id)
    if kept and kept[0] > time.time():
        return kept[1]
    try:
        import boto3
        value = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id).get("SecretString", "")
    except Exception:
        logger.exception("Could not read a secret. Check the secretsmanager:GetSecretValue permission.")
        value = ""
    _secret_cache[secret_id] = (time.time() + SECRET_CACHE_SECONDS, value)
    return value


def _touchpoint_keys() -> dict:
    try:
        keys = json.loads(_secret(os.environ.get("TOUCHPOINT_SECRET_ID", "")) or "{}")
    except ValueError:
        return {}
    return keys if isinstance(keys, dict) else {}


_contact_cache: dict[str, tuple[float, dict]] = {}
CONTACT_CACHE_SECONDS = 30


def _contact_attributes(contact_id: str) -> dict:
    """
    The attributes Connect holds for a contact. Flows set them; the agent and the
    customer cannot. Kept for 30 seconds, because the disputes agent makes several
    calls in a row and Connect limits how often this may be asked.
    """
    instance_id = os.environ.get("CONNECT_INSTANCE_ID", "")
    if not instance_id:
        return {}
    kept = _contact_cache.get(contact_id)
    if kept and kept[0] > time.time():
        return kept[1]
    try:
        import boto3
        attributes = boto3.client("connect").get_contact_attributes(
            InstanceId=instance_id, InitialContactId=contact_id).get("Attributes", {})
    except Exception:
        logger.exception("Could not read the contact. Check the connect:GetContactAttributes permission.")
        return {}
    _contact_cache[contact_id] = (time.time() + CONTACT_CACHE_SECONDS, attributes)
    return attributes


def _customer_of_contact(contact_id: str) -> str:
    return verified_customer(_contact_attributes(contact_id))


def _contact_phone(contact_id: str) -> str:
    """The number the customer is calling from. The bot flow records it as customerPhone."""
    return str(_contact_attributes(contact_id).get("customerPhone") or "")


def _send_sms(phone: str, text: str) -> str:
    """Texts the customer. "" when sent, otherwise a reason that is safe to log and to show the agent."""
    sender = os.environ.get("SMS_ORIGINATION_IDENTITY", "")
    if not sender:
        return "sms_not_configured"
    try:
        import boto3
        boto3.client("pinpoint-sms-voice-v2").send_text_message(
            DestinationPhoneNumber=phone, OriginationIdentity=sender, MessageBody=text, MessageType="TRANSACTIONAL")
    except Exception as error:
        # The class name only: the error text can hold the number.
        logger.warning("Could not send the form link text: %s", type(error).__name__)
        return "sms_failed"
    return ""


def verified_customer(attributes: dict) -> str:
    """
    The contact's customer, but only if a flow recorded them as verified. This
    is the assurance gate for the Live Sync route, enforced here and not left to
    the agent's prompt: an unverified caller's page is never attached, whatever
    the agent is persuaded to try.

    "Verified" is what the flows record: authStatus "authenticated", and, where
    an ID&V flow set a level, Level 2 or above. A caller recognised by phone
    number alone passes when ARIA's injector is configured to treat them as
    authenticated; that is a decision made for this instance (see SPEC Part 3).
    """
    if attributes.get("authStatus") != "authenticated":
        return ""
    level = str(attributes.get("LoA") or attributes.get("loa") or "").strip()
    if level and not (level.isdigit() and int(level) >= 2):
        return ""
    return str(attributes.get("customerId") or "")


doors = dispute_web.Doors(
    acxd_key=lambda: _secret(os.environ.get("ACXD_KEY_SECRET_ID", "")).strip(),
    touchpoint_keys=_touchpoint_keys,
    customer_of_contact=_customer_of_contact,
    region=os.environ.get("AWS_REGION", "eu-west-2"),
    instance_id=os.environ.get("CONNECT_INSTANCE_ID", ""),
    contact_phone=_contact_phone,
    send_sms=_send_sms,
    sms_prefixes=tuple(p.strip() for p in os.environ.get("SMS_ALLOWED_PREFIXES", "+447").split(",") if p.strip()),
    bank_name=os.environ.get("BANK_NAME", "Your bank"),
)

# Tool argument (as ARIA sends it) -> field on the record.
_UPDATE_ARGUMENTS = {
    "dispute_type": "disputeType", "reason": "reason", "card_in_possession": "cardInPossession",
    "card_blocked": "cardBlocked", "contacted_merchant": "contactedMerchant", "narrative": "narrative",
}


def _tool_call(event: dict, context: Any) -> tuple[str, dict]:
    """
    Tool name and arguments, in either form the gateway uses: the name in the
    invocation context with the event as the arguments, or a JSON-RPC body.
    Same reading as the other aria-banking-mcp-* tool Lambdas.
    """
    name = ""
    try:
        name = (context.client_context.custom or {}).get("bedrockAgentCoreToolName", "")
    except Exception:
        pass
    rpc = event.get("params", {})
    if isinstance(rpc, str):
        try:
            rpc = json.loads(rpc)
        except ValueError:
            rpc = {}
    name = name or rpc.get("name") or event.get("toolName") or event.get("tool_name") or ""
    arguments = rpc.get("arguments") or event.get("parameters") or event.get("tool_input")
    if not arguments and not any(key in event for key in ("jsonrpc", "method", "params", "toolName", "tool_name", "id")):
        arguments = {key: value for key, value in event.items() if key != "bedrockAgentCoreMessageVersion"}
    return (name.split("___", 1)[1] if "___" in name else name), (arguments if isinstance(arguments, dict) else {})


def _is_tool_call(event: dict, context: Any) -> bool:
    """True for anything the MCP gateway sent: it names the tool in the invocation context, or sends JSON-RPC."""
    try:
        if (context.client_context.custom or {}).get("bedrockAgentCoreToolName"):
            return True
    except Exception:
        pass
    return any(key in event for key in ("jsonrpc", "method", "params", "toolName", "tool_name"))


def _run_tool(name: str, args: dict) -> dict:
    def text(key: str) -> str:
        value = args.get(key, "")
        return value.strip() if isinstance(value, str) else str(value)

    customer = text("customer_id")
    if name == "list_card_transactions":
        return service.list_card_transactions(customer, text("card_type"))
    if name == "start_card_dispute":
        return service.start_card_dispute(customer, text("transaction_id"), text("dispute_type"))
    if name == "update_card_dispute":
        fields = {field: args[arg] for arg, field in _UPDATE_ARGUMENTS.items() if args.get(arg) not in (None, "")}
        return service.update_card_dispute(customer, text("dispute_id"), fields)
    if name == "get_card_dispute":
        return service.get_card_dispute(customer, text("dispute_id"))
    if name == "attach_dispute_screen":
        return service.attach_dispute_screen(customer, text("dispute_id"), text("code"))
    raise DisputeError("unknown_tool", f"Unknown tool: {name or '(none)'}")


def lambda_handler(event: dict, context: Any) -> dict:
    event = event if isinstance(event, dict) else {}

    # 1. Web. Checked first: see the note at the top of this file.
    if isinstance(event.get("requestContext"), dict) and "http" in event["requestContext"]:
        return dispute_web.handle(event, service, doors)

    # 2. Flow: a Connect flow's Lambda block, when the disputes agent hands the
    #    call back. Connect sends {"Name": "ContactFlowEvent", "Details": ...}.
    #    Tool arguments can arrive at the top level of an event, so a tool call
    #    that copies that shape is still a tool call. The reply holds no link or
    #    secret, only the hand-over summary for this contact's own customer.
    if event.get("Name") == "ContactFlowEvent" and isinstance(event.get("Details"), dict) \
            and not _is_tool_call(event, context):
        details = event["Details"]
        asked = details.get("Parameters") if isinstance(details.get("Parameters"), dict) else {}
        attributes = (details.get("ContactData") or {}).get("Attributes") or {}
        if asked.get("operation") != "handover":
            return {"hasDispute": "false", "error": "unknown_operation"}
        try:
            reply = service.handover(verified_customer(attributes), str(asked.get("assistantSummary") or ""),
                                     str(asked.get("assistantReason") or ""))
        except Exception:
            logger.exception("op=handover failed")
            reply = service.handover("", "")          # still a usable hand-over, routed to fraud_security
        logger.info("op=handover outcome=%s dispute=%s topic=%s", reply["hasDispute"], reply["disputeId"],
                    reply["topicCategory"])
        return reply

    # 3. Internal: the agent-assist Lambda asking for the screen pop. This path
    #    hands out an adviser link, which can confirm and submit, so a TOOL call
    #    must never reach it: ARIA could otherwise ask for a link by passing
    #    "operation" as a tool argument. Anything that arrives as a tool call is
    #    a tool call, whatever its arguments say.
    if event.get("operation") == "screen_pop" and not _is_tool_call(event, context):
        try:
            reply = service.screen_pop(str(event.get("customerId") or ""))
        except Exception:
            logger.exception("op=screen_pop failed")
            reply = {"hasDispute": "false"}
        logger.info("op=screen_pop outcome=%s dispute=%s", reply["hasDispute"], reply.get("disputeId", "-"))
        return reply

    # 4. Tool.
    name, args = _tool_call(event, context)
    try:
        reply = _run_tool(name, args)
        outcome = "ok"
    except DisputeError as error:
        reply, outcome = {"error": error.code, "message": error.message}, error.code
    except ValueError as error:
        reply, outcome = {"error": "invalid_field", "message": str(error)}, "invalid_field"
    except Exception:
        logger.exception("tool=%s failed", name)
        reply, outcome = {"error": "error", "message": "The dispute service is not available right now."}, "error"
    # Only a reference the service itself issued is logged, never caller-supplied text.
    logger.info("tool=%s outcome=%s dispute=%s", name if name in _TOOLS else "unknown", outcome,
                reply.get("dispute_id") or "-")
    return reply
