import logging
from typing import Any, Dict, List

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_datetime, parse_parameters

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

ALLOWED_STATUSES = {"CONNECTED", "CONNECTING", "INCOMING", "MISSED", "REJECTED", "ENDED"}


def _queue_lookup(connect_client, instance_id: str) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    paginator = connect_client.get_paginator("list_queues")
    for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD", "AGENT"]):
        for queue in page.get("QueueSummaryList", []):
            lookup[queue["Id"]] = queue.get("Name", queue["Id"])
    return lookup


def _agent_name(connect_client, instance_id: str, user_id: str) -> str:
    if not user_id:
        return "Unassigned"
    try:
        user = connect_client.describe_user(InstanceId=instance_id, UserId=user_id).get("User", {})
        identity = user.get("IdentityInfo", {})
        return " ".join(part for part in [identity.get("FirstName"), identity.get("LastName")] if part) or user.get("Username", user_id)
    except Exception:  # pylint: disable=broad-except
        return user_id


def _derive_contact_status(contact: Dict[str, Any]) -> str:
    if contact.get("DisconnectTimestamp"):
        return "ENDED"
    if (contact.get("AgentInfo") or {}).get("ConnectedToAgentTimestamp"):
        return "CONNECTED"
    if contact.get("Channel"):
        return "CONNECTING"
    return "INCOMING"


def _transform_contact(contact: Dict[str, Any], connect_client, instance_id: str, queue_names: Dict[str, str]) -> Dict[str, Any]:
    queue_id = ((contact.get("QueueInfo") or {}).get("Id"))
    agent_id = ((contact.get("AgentInfo") or {}).get("Id"))
    initiation = contact.get("InitiationTimestamp")
    disconnect = contact.get("DisconnectTimestamp")
    duration_seconds = None
    if initiation and disconnect:
        duration_seconds = max((disconnect - initiation).total_seconds(), 0)

    # Check recording availability via describe_contact (Recordings field only exists there)
    has_recording = False
    try:
        detail = connect_client.describe_contact(InstanceId=instance_id, ContactId=contact["Id"]).get("Contact", {})
        has_recording = bool(detail.get("Recordings"))
    except Exception:  # pylint: disable=broad-except
        pass

    return {
        "contact_id": contact.get("Id"),
        "initial_contact_id": contact.get("InitialContactId"),
        "previous_contact_id": contact.get("PreviousContactId"),
        "name": contact.get("Name"),
        "channel": contact.get("Channel"),
        "initiation_method": contact.get("InitiationMethod"),
        "timestamp": initiation,
        "disconnect_timestamp": disconnect,
        "queue_id": queue_id,
        "queue_name": queue_names.get(queue_id, queue_id),
        "agent_id": agent_id,
        "agent_name": _agent_name(connect_client, instance_id, agent_id),
        "duration_seconds": duration_seconds,
        "duration": format_duration(duration_seconds),
        "contact_status": _derive_contact_status(contact),
        "has_recording": has_recording,
    }


def lambda_handler(event, _context):
    try:
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        start_time = parse_datetime(params.get("start_time"))
        end_time = parse_datetime(params.get("end_time"))
        if not start_time or not end_time:
            raise ValueError("start_time and end_time are required in ISO 8601 format.")

        requested_status = (params.get("contact_status") or "").upper() or None
        if requested_status and requested_status not in ALLOWED_STATUSES:
            raise ValueError(f"contact_status must be one of: {', '.join(sorted(ALLOWED_STATUSES))}")

        min_duration = int(params["min_duration_seconds"]) if params.get("min_duration_seconds") else None
        max_duration = int(params["max_duration_seconds"]) if params.get("max_duration_seconds") else None
        max_results = min(int(params.get("max_results") or 25), 100)

        search_criteria: Dict[str, Any] = {}
        if params.get("queue_id"):
            search_criteria["QueueIds"] = [params["queue_id"]]
        if params.get("agent_id"):
            search_criteria["AgentIds"] = [params["agent_id"]]
        # SearchContacts requires at least one non-empty criterion — default to all channels
        if not search_criteria:
            search_criteria = {"Channels": ["VOICE", "CHAT", "TASK"]}

        connect_client = boto3.client("connect")
        search_kwargs: Dict[str, Any] = {
            "InstanceId": instance_id,
            "TimeRange": {"Type": "INITIATION_TIMESTAMP", "StartTime": start_time, "EndTime": end_time},
            "SearchCriteria": search_criteria,
            "MaxResults": max_results,
        }
        if params.get("next_token"):
            search_kwargs["NextToken"] = params["next_token"]
        response = connect_client.search_contacts(**search_kwargs)

        queue_names = _queue_lookup(connect_client, instance_id)
        contacts = [_transform_contact(item, connect_client, instance_id, queue_names) for item in response.get("Contacts", [])]

        filtered_contacts: List[Dict[str, Any]] = []
        for contact in contacts:
            if requested_status and contact["contact_status"] != requested_status:
                continue
            duration = contact.get("duration_seconds")
            if min_duration is not None and (duration is None or duration < min_duration):
                continue
            if max_duration is not None and duration is not None and duration > max_duration:
                continue
            filtered_contacts.append(contact)

        return build_response(
            event,
            {
                "instance_id": instance_id,
                "search_window": {"start_time": start_time, "end_time": end_time},
                "filters": {
                    "queue_id": params.get("queue_id"),
                    "agent_id": params.get("agent_id"),
                    "contact_status": requested_status,
                    "min_duration_seconds": min_duration,
                    "max_duration_seconds": max_duration,
                },
                "total_count": response.get("TotalCount", len(filtered_contacts)),
                "returned_count": len(filtered_contacts),
                "next_token": response.get("NextToken"),
                "contacts": filtered_contacts,
            },
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to search contacts")
        return build_error_response(event, "Unable to search Amazon Connect contacts", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while searching contacts")
        return build_error_response(event, "An unexpected error occurred while searching contacts", status_code=500)
