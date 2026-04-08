"""
aria_routing_lookup.py
======================
Amazon Connect Lambda integration — proficiency-based queue routing.

Called by the Contact Flow immediately after ARIA escalates via the
"Escalate" Return to Control tool. Reads topicCategory from the contact
attributes, queries the aria-routing-config DynamoDB table, and returns
the matching queue ID so the flow can dynamically set the working queue.

Connect reads the response under the External namespace:
    $.External.queueId          → used by Set Working Queue (dynamic)
    $.External.queueName        → informational / screen pop
    $.External.proficiencyLevel → informational
    $.External.proficiencySkill → informational
    $.External.topicCategory    → echoed back for downstream attribute blocks
    $.External.conversationSummary → echoed through for agent screen pop
    $.External.customerIntent   → echoed through for agent screen pop
    $.External.escalationReason → echoed through for agent screen pop

IMPORTANT: Connect reads Lambda responses in STRING_MAP mode.
Every value in the returned dict MUST be a plain string — no ints,
no bools, no nested dicts, no lists. Returning a non-string value
causes the External namespace to silently drop that key in the flow.

Environment variables:
    ROUTING_TABLE   DynamoDB table name (default: aria-routing-config)
"""

import boto3
import json
import os
from decimal import Decimal

# ---------------------------------------------------------------------------
# Initialise outside handler for connection reuse across warm invocations
# ---------------------------------------------------------------------------
dynamodb = boto3.resource("dynamodb")
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
    print(f"[{contact_id}] Routing lookup — topicCategory: '{topic}'")

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
            f"[{contact_id}] ERROR: No '{DEFAULT_TOPIC}' fallback row found. "
            f"Contact flow will route to Error branch."
        )
        # Returning a single error flag so the flow can detect and use its own fallback.
        # Still a flat string dict — no exceptions raised so Connect gets the response.
        return {"routingError": "true"}

    # ── 4. Build flat string response ─────────────────────────────────────
    # Every value is explicitly cast to str() to satisfy Connect's STRING_MAP
    # requirement. DynamoDB Decimal types (for proficiencyLevel stored as Number)
    # would cause a JSON serialisation error without the cast.
    response = {
        "queueId":            _str(item.get("queueId", "")),
        "queueName":          _str(item.get("queueName", "General Queue")),
        "proficiencyLevel":   _str(item.get("proficiencyLevel", "1")),
        "proficiencySkill":   _str(item.get("proficiencySkill", "General")),
        "topicCategory":      _str(topic),
        # Echo contact attributes through so downstream Set Contact Attributes
        # blocks can read them from $.External rather than needing a second
        # lookup of the Lex session attributes.
        "conversationSummary": _str(attrs.get("conversationSummary", "")),
        "customerIntent":      _str(attrs.get("customerIntent", "")),
        "escalationReason":    _str(attrs.get("escalationReason", "")),
        "routingError":        "false",
    }

    print(
        f"[{contact_id}] Routing to queue '{response['queueName']}' "
        f"(id={response['queueId']}, proficiency={response['proficiencySkill']} "
        f"L{response['proficiencyLevel']})"
    )
    return _enforce_string_map(response, contact_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_item(table, topic: str):
    """Return the DynamoDB item for the given topicCategory, or None."""
    response = table.get_item(Key={"topicCategory": topic})
    return response.get("Item")


def _str(value) -> str:
    """
    Coerce any scalar to a plain Python str, safe for Connect STRING_MAP mode.

    Rules:
      None        → ""                (not the literal "None")
      bool        → "true" / "false"  (lowercase, not Python's "True"/"False")
      Decimal     → integer notation  Decimal('3.0') → "3", Decimal('3.5') → "3.5"
      int / float → str(value)
      list / dict → compact JSON      (shouldn't appear; preserves data for debug)
      anything    → str(value)
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        # Drop unnecessary trailing decimal: Decimal('3.0') → "3", Decimal('3.5') → "3.5"
        integral = value.to_integral_value()
        return str(integral) if value == integral else str(value.normalize())
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _enforce_string_map(response: dict, contact_id: str = "") -> dict:
    """
    Final-pass validation: ensure every value in the response dict is a plain str.

    Connect reads Lambda responses in STRING_MAP mode and silently drops any key
    whose value is not a string. This guard coerces stragglers and logs a warning
    to CloudWatch so schema drift is immediately visible rather than silently
    breaking queue routing.
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
