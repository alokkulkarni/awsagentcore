import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_parameters
from shared.scan_resources import get_queue_id_map

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)


def _display_name(connect_client, instance_id: str, user_id: str) -> Dict[str, str]:
    user = connect_client.describe_user(InstanceId=instance_id, UserId=user_id).get("User", {})
    identity = user.get("IdentityInfo", {})
    display_name = " ".join(part for part in [identity.get("FirstName"), identity.get("LastName")] if part) or user.get("Username", user_id)
    return {"username": user.get("Username", user_id), "display_name": display_name}


def _derive_status(user_data: Dict[str, Any]) -> str:
    status_name = (user_data.get("Status", {}) or {}).get("StatusName", "Unknown")
    contacts = user_data.get("Contacts", [])
    lowered = status_name.lower()
    if contacts:
        return "ON_CALL"
    if "after" in lowered or "acw" in lowered:
        return "AFTER_CONTACT_WORK"
    if "available" in lowered:
        return "AVAILABLE"
    if "offline" in lowered:
        return "OFFLINE"
    if "error" in lowered:
        return "ERROR"
    if any(token in lowered for token in ["break", "lunch", "meeting", "non", "away"]):
        return "NON_PRODUCTIVE"
    if any(token in lowered for token in ["busy", "missed", "reject"]):
        return "BUSY"
    return status_name.upper().replace(" ", "_")


def _matches_filter(derived_status: str, requested_status: Optional[str]) -> bool:
    if not requested_status:
        return True
    requested_status = requested_status.upper()
    if requested_status == derived_status:
        return True
    if requested_status == "BUSY" and derived_status in {"ON_CALL", "AFTER_CONTACT_WORK", "NON_PRODUCTIVE", "BUSY"}:
        return True
    return False


def lambda_handler(event, _context):
    try:
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        queue_id = params.get("queue_id")
        status_filter = params.get("agent_status_filter")

        connect_client = boto3.client("connect")
        filters: Dict[str, Any] = {}
        if queue_id:
            filters["Queues"] = [queue_id]

        queue_name_map = get_queue_id_map(instance_id, connect_client)

        # GetCurrentUserData requires at least one filter (Queue, RoutingProfile, Agent, or UserHierarchyGroup)
        if queue_id:
            filters = {"Queues": [queue_id]}
        elif queue_name_map:
            # Use all discovered standard queues as the filter
            filters = {"Queues": list(queue_name_map.keys())}
        else:
            filters = {}

        if not filters:
            return build_response(event, {"instance_id": instance_id, "agent_count": 0, "agents": [],
                                          "message": "No queues found — cannot query user data without a filter."})

        # get_current_user_data does not support paginators — use NextToken manually
        results: List[Dict[str, Any]] = []
        kwargs: Dict[str, Any] = {"InstanceId": instance_id, "Filters": filters, "MaxResults": 100}
        while True:
            response = connect_client.get_current_user_data(**kwargs)
            for user_data in response.get("UserDataList", []):
                derived_status = _derive_status(user_data)
                if not _matches_filter(derived_status, status_filter):
                    continue

                user_ref = user_data.get("User", {})
                user_id = user_ref.get("Id")
                contact = (user_data.get("Contacts") or [None])[0]
                name_fields = _display_name(connect_client, instance_id, user_id)
                status_start = (user_data.get("Status", {}) or {}).get("StatusStartTimestamp")
                time_in_status_seconds = None
                if isinstance(status_start, datetime):
                    time_in_status_seconds = max((datetime.now(timezone.utc) - status_start).total_seconds(), 0)

                current_queue = None
                contact_id = None
                if contact:
                    current_queue = ((contact.get("Queue") or {}).get("Id"))
                    contact_id = contact.get("ContactId")
                elif queue_id:
                    current_queue = queue_id

                results.append(
                    {
                        "agent_id": user_id,
                        "username": name_fields["username"],
                        "display_name": name_fields["display_name"],
                        "current_status": derived_status,
                        "raw_status_name": (user_data.get("Status", {}) or {}).get("StatusName"),
                        "current_queue": current_queue,
                        "current_queue_name": queue_name_map.get(current_queue, current_queue) if current_queue else None,
                        "contact_id": contact_id,
                        "time_in_status_seconds": time_in_status_seconds,
                        "time_in_status": format_duration(time_in_status_seconds),
                        "contacts": user_data.get("Contacts", []),
                        "available_slots_by_channel": user_data.get("AvailableSlotsByChannel", {}),
                        "active_slots_by_channel": user_data.get("ActiveSlotsByChannel", {}),
                    }
                )
            next_token = response.get("NextToken")
            if not next_token:
                break
            kwargs["NextToken"] = next_token

        return build_response(
            event,
            {
                "instance_id": instance_id,
                "queue_filter": queue_id,
                "agent_status_filter": status_filter,
                "agent_count": len(results),
                "agents": sorted(results, key=lambda item: (item.get("display_name") or "").lower()),
            },
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to retrieve agent states")
        return build_error_response(event, f"Unable to fetch Amazon Connect agent state data: {exc}", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while retrieving agent states")
        return build_error_response(event, str(exc), status_code=500)
