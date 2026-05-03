"""
aria_meeting_id_capture.py
==========================
Amazon Connect Lambda — captures a 6-digit meeting ID from flow input.

Use this with a Contact Flow "Store customer input" block followed by
"Invoke AWS Lambda function".

Expected behavior:
  1. Read meeting ID from Connect event payload.
  2. Accept only a 6-digit value.
  3. Print the meeting ID in CloudWatch logs.
  4. Return STRING_MAP response so Contact Flow can branch on success.

Flow reads response under External namespace:
  $.External.success
  $.External.status
  $.External.meetingId
  $.External.meetingIdSource
  $.External.message
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

MEETING_ID_REGEX = re.compile(r"\b(\d{6})\b")
KEY_CANDIDATES = (
    "meetingId",
    "meetingID",
    "meeting_id",
    "MeetingId",
    "MeetingID",
    "meetingCode",
    "meeting_code",
    "storedCustomerInput",
    "StoredCustomerInput",
    "customerInput",
    "customer_input",
)


def handler(event: dict[str, Any], context: Any) -> dict[str, str]:
    del context  # unused
    details = _as_dict(event.get("Details"))
    contact_data = _as_dict(details.get("ContactData"))
    attributes = _as_dict(contact_data.get("Attributes"))
    parameters = _as_dict(details.get("Parameters"))
    contact_id = _to_str(contact_data.get("ContactId")) or "unknown"

    meeting_id = ""
    source = ""

    for candidate_source, mapping in (
        ("Details.Parameters", parameters),
        ("Details.ContactData.Attributes", attributes),
        ("Root", _as_dict(event)),
    ):
        meeting_id, key = _extract_meeting_id_from_mapping(mapping)
        if meeting_id:
            source = f"{candidate_source}.{key}"
            break

    if not meeting_id:
        # Last resort: recursive payload scan for any 6-digit value.
        meeting_id = _find_meeting_id_recursive(event)
        if meeting_id:
            source = "recursive_payload_scan"

    if meeting_id:
        print(f"[{contact_id}] Meeting ID received ({source}): {meeting_id}")
        return {
            "success": "true",
            "status": "success",
            "meetingId": meeting_id,
            "meetingIdSource": source,
            "message": "Meeting ID processed successfully.",
        }

    print(f"[{contact_id}] No valid 6-digit meeting ID found in event payload.")
    return {
        "success": "false",
        "status": "error",
        "meetingId": "",
        "meetingIdSource": "",
        "message": "No valid 6-digit meeting ID found.",
    }


def _extract_meeting_id_from_mapping(mapping: dict[str, Any]) -> tuple[str, str]:
    for key in KEY_CANDIDATES:
        if key not in mapping:
            continue
        value = mapping.get(key)
        meeting_id = _extract_six_digits(value)
        if meeting_id:
            return meeting_id, key
    return "", ""


def _find_meeting_id_recursive(value: Any) -> str:
    for scalar in _iter_scalars(value):
        meeting_id = _extract_six_digits(scalar)
        if meeting_id:
            return meeting_id
    return ""


def _iter_scalars(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_scalars(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_scalars(item)
        return
    yield value


def _extract_six_digits(value: Any) -> str:
    raw = _to_str(value)
    if not raw:
        return ""
    match = MEETING_ID_REGEX.search(raw)
    return match.group(1) if match else ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)

