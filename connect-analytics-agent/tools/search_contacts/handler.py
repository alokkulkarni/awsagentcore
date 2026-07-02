import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_datetime, parse_parameters

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
_CONNECT_CLIENT = boto3.client("connect", config=_BOTO_CONFIG)

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

ALLOWED_STATUSES = {"CONNECTED", "CONNECTING", "INCOMING", "MISSED", "REJECTED", "ENDED"}
VALID_CHANNELS = {"VOICE", "CHAT", "TASK"}
VALID_INITIATION_METHODS = {
    "INBOUND", "OUTBOUND", "TRANSFER", "QUEUE_TRANSFER", "CALLBACK", "API",
    "DISCONNECT", "MONITOR", "EXTERNAL_OUTBOUND", "WEBRTC_API", "AGENT_REPLY", "FLOW",
}
VALID_TIME_RANGE_TYPES = {"INITIATION_TIMESTAMP", "CONNECTED_TO_AGENT_TIMESTAMP", "DISCONNECT_TIMESTAMP"}
VALID_SORT_ORDERS = {"ASCENDING", "DESCENDING"}

_CONTACT_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

_CACHE_TTL = 300
_cache: Dict[str, Any] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["v"]
    return None


def _cache_set(key: str, value) -> None:
    _cache[key] = {"v": value, "ts": time.time()}


def _queue_lookup(connect_client, instance_id: str) -> Dict[str, str]:
    cache_key = f"queues/{instance_id}"
    cached_lookup = _cache_get(cache_key)
    if cached_lookup is not None:
        return cached_lookup
    lookup: Dict[str, str] = {}
    paginator = connect_client.get_paginator("list_queues")
    for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD", "AGENT"]):
        for queue in page.get("QueueSummaryList", []):
            lookup[queue["Id"]] = queue.get("Name", queue["Id"])
    _cache_set(cache_key, lookup)
    return lookup



def _agent_name(connect_client, instance_id: str, user_id: str) -> str:
    if not user_id:
        return "Unassigned"
    cache_key = f"user/{instance_id}/{user_id}"
    cached_name = _cache_get(cache_key)
    if cached_name is not None:
        return cached_name
    try:
        user = connect_client.describe_user(InstanceId=instance_id, UserId=user_id).get("User", {})
        identity = user.get("IdentityInfo", {})
        display_name = " ".join(part for part in [identity.get("FirstName"), identity.get("LastName")] if part) or user.get("Username", user_id)
        _cache_set(cache_key, display_name)
        return display_name
    except Exception:  # pylint: disable=broad-except
        return user_id



def _derive_contact_status(contact: Dict[str, Any]) -> str:
    explicit_state = str(contact.get("State") or contact.get("ContactState") or "").upper()
    if explicit_state in ALLOWED_STATUSES:
        return explicit_state
    if contact.get("DisconnectTimestamp"):
        return "ENDED"
    agent_info = contact.get("AgentInfo") or {}
    if agent_info.get("ConnectedToAgentTimestamp") or contact.get("ConnectedToAgentTimestamp"):
        return "CONNECTED"
    if contact.get("Channel"):
        return "CONNECTING"
    return "INCOMING"



def _get_custom_attributes(connect_client, instance_id: str, detail: Dict[str, Any], fallback_contact: Dict[str, Any]) -> Dict[str, Any]:
    attributes = detail.get("Attributes") or {}
    if attributes:
        return attributes
    initial_contact_id = detail.get("InitialContactId") or fallback_contact.get("InitialContactId") or detail.get("Id") or fallback_contact.get("Id")
    if not initial_contact_id:
        return {}
    try:
        return connect_client.get_contact_attributes(
            InstanceId=instance_id,
            InitialContactId=initial_contact_id,
        ).get("Attributes", {})
    except Exception:  # pylint: disable=broad-except
        return {}



def _transform_contact(contact: Dict[str, Any], connect_client, instance_id: str, queue_names: Dict[str, str]) -> Dict[str, Any]:
    queue_info = contact.get("QueueInfo") or {}
    agent_info = contact.get("AgentInfo") or {}
    queue_id = queue_info.get("Id") or queue_info.get("QueueId") or contact.get("QueueId")
    agent_id = agent_info.get("Id") or contact.get("AgentId") or ""
    initiation = contact.get("InitiationTimestamp")
    disconnect = contact.get("DisconnectTimestamp")
    duration_seconds: Optional[float] = None
    if initiation and disconnect:
        duration_seconds = max((disconnect - initiation).total_seconds(), 0)

    customer_ep = contact.get("CustomerEndpoint") or {}
    customer_endpoint_value = customer_ep.get("Address") or customer_ep.get("address") or ""

    has_recording = False
    custom_attributes: Dict[str, Any] = {}
    try:
        detail_resp = connect_client.describe_contact(InstanceId=instance_id, ContactId=contact["Id"])
        detail = detail_resp.get("Contact", {})
        has_recording = bool(detail.get("Recordings"))
        custom_attributes = _get_custom_attributes(connect_client, instance_id, detail, contact)
        if not customer_endpoint_value:
            ep = detail.get("CustomerEndpoint") or {}
            customer_endpoint_value = ep.get("Address") or ep.get("address") or ""
    except Exception:  # pylint: disable=broad-except
        LOGGER.debug("Suppressed exception parsing customer endpoint", exc_info=True)

    if not has_recording:
        has_recording = bool(contact.get("Recordings"))

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
        "customer_endpoint": customer_endpoint_value,
        "custom_attributes": custom_attributes,
    }



def _apply_post_filters(
    contacts: List[Dict[str, Any]],
    requested_status: Optional[str],
    min_duration: Optional[int],
    max_duration: Optional[int],
) -> List[Dict[str, Any]]:
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
    return filtered_contacts



def lambda_handler(event, _context):
    try:
        LOGGER.info(json.dumps({"event": "lambda_invoked", "function": event.get("function", "unknown")}))
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

        channels = [c.strip().upper() for c in str(params.get("channels", "VOICE,CHAT,TASK")).split(",") if c.strip()]
        channels = [c for c in channels if c in VALID_CHANNELS] or ["VOICE", "CHAT", "TASK"]

        queue_ids = [q.strip() for q in str(params.get("queue_ids", "")).split(",") if q.strip()]
        if not queue_ids and params.get("queue_id"):
            queue_ids = [str(params["queue_id"])]

        agent_ids = [a.strip() for a in str(params.get("agent_ids", "")).split(",") if a.strip()]
        if not agent_ids and params.get("agent_id"):
            agent_ids = [str(params["agent_id"])]

        initiation_methods: List[str] = []
        if params.get("initiation_methods"):
            methods = [m.strip().upper() for m in str(params["initiation_methods"]).split(",") if m.strip()]
            initiation_methods = [m for m in methods if m in VALID_INITIATION_METHODS]

        time_range_type = str(params.get("time_range_type", "INITIATION_TIMESTAMP")).upper()
        if time_range_type not in VALID_TIME_RANGE_TYPES:
            time_range_type = "INITIATION_TIMESTAMP"

        sort_field = str(params.get("sort_field", "INITIATION_TIMESTAMP")).upper()
        if sort_field not in VALID_TIME_RANGE_TYPES:
            sort_field = "INITIATION_TIMESTAMP"

        sort_order = str(params.get("sort_order", "DESCENDING")).upper()
        if sort_order not in VALID_SORT_ORDERS:
            sort_order = "DESCENDING"

        try:
            queue_names = _queue_lookup(_CONNECT_CLIENT, instance_id)
        except Exception:  # pylint: disable=broad-except
            LOGGER.info("Unable to build queue lookup; continuing with queue IDs only")
            queue_names = {}

        if params.get("contact_id"):
            contact_id = str(params["contact_id"]).strip()
            if not _CONTACT_ID_RE.match(contact_id):
                return build_error_response(event, f"Invalid contact_id format: {contact_id!r}", status_code=400)
            detail = _CONNECT_CLIENT.describe_contact(InstanceId=instance_id, ContactId=contact_id).get("Contact", {})
            contact = _transform_contact(detail, _CONNECT_CLIENT, instance_id, queue_names)
            filtered_contacts = _apply_post_filters([contact], requested_status, min_duration, max_duration)
            return build_response(
                event,
                {
                    "instance_id": instance_id,
                    "search_window": {"start_time": start_time, "end_time": end_time},
                    "filters": {
                        "queue_ids": queue_ids,
                        "agent_ids": agent_ids,
                        "channels": channels,
                        "initiation_methods": initiation_methods,
                        "time_range_type": time_range_type,
                        "sort_field": sort_field,
                        "sort_order": sort_order,
                        "contact_status": requested_status,
                        "min_duration_seconds": min_duration,
                        "max_duration_seconds": max_duration,
                        "phone_number": params.get("phone_number"),
                        "contact_id": params.get("contact_id"),
                    },
                    "total_count": 1,
                    "returned_count": len(filtered_contacts),
                    "next_token": None,
                    "contacts": filtered_contacts,
                },
            )

        search_criteria: Dict[str, Any] = {"Channels": channels}
        if queue_ids:
            search_criteria["QueueIds"] = queue_ids
        if agent_ids:
            search_criteria["AgentIds"] = agent_ids
        if initiation_methods:
            search_criteria["InitiationMethods"] = initiation_methods

        searchable_criteria: List[Dict[str, Any]] = []
        if params.get("phone_number"):
            searchable_criteria.append({"Key": "CustomerEndpoint", "Values": [str(params["phone_number"]).strip()]})
        if params.get("searchable_attributes"):
            try:
                attrs = json.loads(str(params["searchable_attributes"]))
                for attr in attrs:
                    key = str(attr.get("key", "")).strip()
                    values_source = attr.get("values") if isinstance(attr.get("values"), list) else [attr.get("value", "")]
                    values = [str(v).strip() for v in values_source if str(v).strip()]
                    if key and values:
                        searchable_criteria.append({"Key": key, "Values": values})
            except Exception:  # pylint: disable=broad-except
                LOGGER.debug('Suppressed exception', exc_info=True)
        if searchable_criteria:
            search_criteria["SearchableContactAttributes"] = {
                "Criteria": searchable_criteria,
                "MatchType": "MATCH_ALL",
            }

        search_kwargs: Dict[str, Any] = {
            "InstanceId": instance_id,
            "TimeRange": {"Type": time_range_type, "StartTime": start_time, "EndTime": end_time},
            "SearchCriteria": search_criteria,
            "MaxResults": max_results,
            "Sort": {"FieldName": sort_field, "Order": sort_order},
        }
        if params.get("next_token"):
            search_kwargs["NextToken"] = params["next_token"]

        response = _CONNECT_CLIENT.search_contacts(**search_kwargs)
        contacts = [_transform_contact(item, _CONNECT_CLIENT, instance_id, queue_names) for item in response.get("Contacts", [])]
        filtered_contacts = _apply_post_filters(contacts, requested_status, min_duration, max_duration)

        return build_response(
            event,
            {
                "instance_id": instance_id,
                "search_window": {"start_time": start_time, "end_time": end_time},
                "filters": {
                    "queue_ids": queue_ids,
                    "agent_ids": agent_ids,
                    "channels": channels,
                    "initiation_methods": initiation_methods,
                    "time_range_type": time_range_type,
                    "sort_field": sort_field,
                    "sort_order": sort_order,
                    "contact_status": requested_status,
                    "min_duration_seconds": min_duration,
                    "max_duration_seconds": max_duration,
                    "phone_number": params.get("phone_number"),
                    "contact_id": params.get("contact_id"),
                },
                "total_count": response.get("TotalCount", len(filtered_contacts)),
                "returned_count": len(filtered_contacts),
                "next_token": response.get("NextToken"),
                "contacts": filtered_contacts,
            },
        )
    except (ClientError, BotoCoreError):
        LOGGER.exception("Failed to search contacts")
        return build_error_response(event, "Unable to search Amazon Connect contacts", status_code=502)
    except Exception:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while searching contacts")
        return build_error_response(event, "An unexpected error occurred while searching contacts", status_code=500)
