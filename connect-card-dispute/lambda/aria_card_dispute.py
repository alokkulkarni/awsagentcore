"""
aria_card_dispute.py
====================
Card transaction disputes: one Lambda, three ways in (SPEC.md section 6).

    Web       the HTTP API. The customer page, the adviser page, their JSON calls.
    Tool      the MCP gateway. ARIA's five tools; get_card_dispute for agent assist.
    Internal  the agent-assist Lambda. Lines and a link for the adviser's screen pop.

Which way a request came in is decided by its shape, and the web check comes
first: the HTTP API always wraps a request in its own envelope, so nothing sent
over the internet can pass itself off as a tool call or an internal call.

ENVIRONMENT VARIABLES
---------------------
    DISPUTE_TABLE_NAME      DynamoDB table. Unset = in-memory, for local runs only
    PUBLIC_BASE_URL         The HTTP API's address, used to build page links
    MERCHANT_DISPUTE_TOPIC  Topic to route "problem with a payment I made" disputes
                            to. Unset = the card's own topic (debit_card / credit_card)
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
        return dispute_web.handle(event, service)

    # 2. Internal: the agent-assist Lambda asking for the screen pop.
    if event.get("operation") == "screen_pop":
        try:
            reply = service.screen_pop(str(event.get("customerId") or ""))
        except Exception:
            logger.exception("op=screen_pop failed")
            reply = {"hasDispute": "false"}
        logger.info("op=screen_pop outcome=%s dispute=%s", reply["hasDispute"], reply.get("disputeId", "-"))
        return reply

    # 3. Tool.
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
