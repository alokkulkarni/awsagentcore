"""
aria_callback_scheduler.py
==========================
Amazon Connect Lambda — dynamic callback queue resolver and context carrier.

Triggered from the ARIA-Callback-Offer flow immediately before the
"Set working queue (dynamic)" block.  Reads the topicCategory contact
attribute, queries the aria-routing-config DynamoDB table, and returns the
matching callback queue ID and ARN so the flow can set the working queue
dynamically.

Also echoes conversation context attributes (conversationSummary,
customerIntent, escalationReason) through so that the downstream
Outbound Whisper flow and Agent Whisper flow can read them from
$.Attributes or $.External without needing a second Lambda call.

Connect reads the response under the External namespace:

    $.External.callbackQueueId     → UUID only — used by Set working queue (dynamic)
    $.External.callbackQueueArn    → full ARN  — informational / alternate Transfer to queue
    $.External.callbackQueueName   → human-readable name — used in confirmation prompt
    $.External.callbackReason      → queue_full | out_of_hours | customer_request
    $.External.topicCategory       → echoed for downstream blocks
    $.External.conversationSummary → echoed for agent / outbound whisper flows
    $.External.customerIntent      → echoed for agent / outbound whisper flows
    $.External.escalationReason    → echoed for agent / outbound whisper flows
    $.External.schedulingError     → "true" only if no DynamoDB row found

IMPORTANT: Connect reads Lambda responses in STRING_MAP mode.
Every value in the returned dict MUST be a plain string — no ints,
no bools, no nested dicts, no lists. A non-string value causes the
External namespace to silently drop that key.

DynamoDB schema extension (aria-routing-config table):
    Each row must also contain (in addition to existing routing fields):
        callbackQueueId  (S)  — UUID of the dedicated callback queue
        callbackQueueArn (S)  — Full ARN of the dedicated callback queue
        callbackQueueName(S)  — Human-readable name, e.g. "Mortgage Callback"

    If callbackQueueId is missing/empty the Lambda falls back to the
    main queue's queueId so callbacks still work while you add the
    dedicated queues.

Environment variables:
    ROUTING_TABLE   DynamoDB table name  (default: aria-routing-config)
"""

import boto3
import json
import os
from decimal import Decimal

from botocore.config import Config

# ---------------------------------------------------------------------------
# Module-level initialisation — shared across warm Lambda invocations
# ---------------------------------------------------------------------------
_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

dynamodb = boto3.resource("dynamodb", config=_BOTO_CONFIG)
TABLE_NAME = os.environ.get("ROUTING_TABLE", "aria-routing-config")
DEFAULT_TOPIC = "general_banking"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def handler(event, context):
    contact_data = event.get("Details", {}).get("ContactData", {})
    attrs = contact_data.get("Attributes", {})
    contact_id = contact_data.get("ContactId", "unknown")

    topic = attrs.get("topicCategory", DEFAULT_TOPIC).strip().lower()
    callback_reason = attrs.get("callbackReason", "customer_request").strip()

    print(
        f"[{contact_id}] Callback scheduler — topicCategory: '{topic}', "
        f"reason: '{callback_reason}'"
    )

    table = dynamodb.Table(TABLE_NAME)

    # ── 1. Exact topic match ──────────────────────────────────────────────
    item = _get_item(table, topic)

    # ── 2. Fallback to general_banking ───────────────────────────────────
    if item is None:
        print(
            f"[{contact_id}] No routing config for '{topic}', "
            f"falling back to '{DEFAULT_TOPIC}'"
        )
        item = _get_item(table, DEFAULT_TOPIC)

    # ── 3. Hard error — no fallback row either ────────────────────────────
    if item is None:
        print(
            f"[{contact_id}] ERROR: No '{DEFAULT_TOPIC}' fallback row in "
            f"'{TABLE_NAME}'. Returning schedulingError=true."
        )
        return {
            "schedulingError": "true",
            "topicCategory": _str(topic),
            "callbackReason": _str(callback_reason),
        }

    # ── 4. Resolve callback queue — fall back to main queue if not set ────
    # callbackQueueId / callbackQueueArn are added to the table by the
    # deploy_callback_lambda.sh script (initially as PLACEHOLDERs).
    # If they are missing or still placeholder, fall back to the main
    # queue so the flow still works while you provision dedicated queues.
    cb_queue_id = _str(item.get("callbackQueueId", ""))
    cb_queue_arn = _str(item.get("callbackQueueArn", ""))
    cb_queue_name = _str(item.get("callbackQueueName", ""))

    is_placeholder = (
        cb_queue_id.startswith("PLACEHOLDER")
        or cb_queue_id == ""
    )

    if is_placeholder:
        print(
            f"[{contact_id}] callbackQueueId for '{topic}' is placeholder/empty — "
            f"falling back to main queueId: {_str(item.get('queueId', ''))}"
        )
        cb_queue_id = _str(item.get("queueId", ""))
        cb_queue_name = _str(item.get("queueName", "General Queue")) + " (Callback)"
        # ARN not stored separately for main queue — leave empty; flow uses UUID
        cb_queue_arn = ""

    # ── 5. Build flat string response ─────────────────────────────────────
    response = {
        "callbackQueueId":     cb_queue_id,
        "callbackQueueArn":    cb_queue_arn,
        "callbackQueueName":   cb_queue_name,
        "callbackReason":      _str(callback_reason),
        "topicCategory":       _str(topic),
        # Echo through for whisper flows — these were set on the original
        # contact before Transfer to callback queue, and will also be
        # available on the callback contact via the creation flow.
        "conversationSummary": _str(attrs.get("conversationSummary", "")),
        "customerIntent":      _str(attrs.get("customerIntent", "")),
        "escalationReason":    _str(attrs.get("escalationReason", "")),
        "schedulingError":     "false",
    }

    print(
        f"[{contact_id}] Routing callback to queue '{response['callbackQueueName']}' "
        f"(id={response['callbackQueueId']}, reason={response['callbackReason']})"
    )
    return _enforce_string_map(response, contact_id)


# ---------------------------------------------------------------------------
# Helpers — identical pattern to aria_routing_lookup.py for consistency
# ---------------------------------------------------------------------------

def _get_item(table, topic: str):
    """Return the DynamoDB item for the given topicCategory, or None."""
    response = table.get_item(Key={"topicCategory": topic})
    return response.get("Item")


def _str(value) -> str:
    """
    Coerce any scalar to a plain Python str, safe for Connect STRING_MAP mode.

    Rules:
      None        → ""
      bool        → "true" / "false"
      Decimal     → integer notation where possible
      list / dict → compact JSON
      anything    → str(value)
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        integral = value.to_integral_value()
        return str(integral) if value == integral else str(value.normalize())
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _enforce_string_map(response: dict, contact_id: str = "") -> dict:
    """
    Final-pass guard: ensure every value in the response dict is a plain str.

    Connect silently drops keys whose values are not strings. This guard
    catches any stragglers introduced by schema changes in the DynamoDB table.
    """
    clean = {}
    for key, value in response.items():
        if isinstance(value, str):
            clean[key] = value
        else:
            coerced = _str(value)
            print(
                f"[{contact_id}] WARNING: response['{key}'] had type "
                f"{type(value).__name__!r} — coerced to str '{coerced}'. "
                f"Check DynamoDB schema for unexpected type."
            )
            clean[key] = coerced
    return clean
