import json
import logging
import os
import re as _re
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_parameters

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
_CONNECT_CLIENT = boto3.client("connect", config=_BOTO_CONFIG)


_CONTACT_ID_RE = _re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', _re.IGNORECASE)

def _validate_contact_id(contact_id: str) -> None:
    """Raise ValueError if contact_id is not a valid UUID."""
    if not contact_id or not _CONTACT_ID_RE.match(str(contact_id)):
        raise ValueError(f"Invalid contact_id format: {contact_id!r}")


def _recording_summary(recording: Dict[str, Any]) -> Dict[str, Any]:
    start = recording.get("StartTimestamp")
    stop = recording.get("StopTimestamp")
    duration_seconds: Optional[float] = None
    if start and stop:
        duration_seconds = max((stop - start).total_seconds(), 0)
    location = recording.get("Location")
    return {
        "storage_type": recording.get("StorageType"),
        "location": location,
        "media_stream_type": recording.get("MediaStreamType"),
        "participant_type": recording.get("ParticipantType"),
        "status": recording.get("Status"),
        "start_timestamp": start,
        "stop_timestamp": stop,
        "duration_seconds": duration_seconds,
        "duration": format_duration(duration_seconds),
        "format": location.rsplit(".", 1)[-1].lower() if location and "." in location else None,
        "unprocessed_transcript_location": recording.get("UnprocessedTranscriptLocation"),
    }


def lambda_handler(event, _context):
    try:
        LOGGER.info(json.dumps({"event": "lambda_invoked", "function": event.get("function", "unknown")}))
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        contact_id = params.get("contact_id")
        if not contact_id:
            raise ValueError("contact_id is required.")
        try:
            _validate_contact_id(contact_id)
        except ValueError as exc:
            return {"error": str(exc), "status": "invalid_input"}

        contact = _CONNECT_CLIENT.describe_contact(InstanceId=instance_id, ContactId=contact_id).get("Contact", {})
        attribute_contact_id = contact.get("InitialContactId") or contact_id
        attributes = _CONNECT_CLIENT.get_contact_attributes(
            InstanceId=instance_id,
            InitialContactId=attribute_contact_id,
        ).get("Attributes", {})

        recordings = [_recording_summary(recording) for recording in contact.get("Recordings", [])]
        response = {
            "contact_id": contact.get("Id"),
            "initial_contact_id": contact.get("InitialContactId"),
            "previous_contact_id": contact.get("PreviousContactId"),
            "arn": contact.get("Arn"),
            "name": contact.get("Name"),
            "description": contact.get("Description"),
            "channel": contact.get("Channel"),
            "initiation_method": contact.get("InitiationMethod"),
            "initiation_timestamp": contact.get("InitiationTimestamp"),
            "disconnect_timestamp": contact.get("DisconnectTimestamp"),
            "queue_info": contact.get("QueueInfo"),
            "agent_info": contact.get("AgentInfo"),
            "customer_endpoint": contact.get("CustomerEndpoint"),
            "system_endpoint": contact.get("SystemEndpoint"),
            "attributes": attributes,
            "recordings": recordings,
            "recording_location": recordings[0]["location"] if recordings else None,
            "contact_details": contact.get("ContactDetails"),
            "disconnect_reason": contact.get("DisconnectReason"),
            "quality_metrics": contact.get("QualityMetrics"),
            "raw_contact": contact,
        }

        return build_response(event, response)
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to describe contact")
        return build_error_response(event, f"Unable to fetch Amazon Connect contact details: {exc}", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while describing contact")
        return build_error_response(event, str(exc), status_code=500)
