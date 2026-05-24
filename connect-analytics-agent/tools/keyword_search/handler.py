import json
import logging
import os
import re as _re
import time
from typing import Any, Dict, List

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_datetime, parse_parameters

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
_CACHE_TTL = 300

_CONTACT_ID_RE = _re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', _re.IGNORECASE)

def _validate_contact_id(contact_id: str) -> None:
    """Raise ValueError if contact_id is not a valid UUID."""
    if not contact_id or not _CONTACT_ID_RE.match(str(contact_id)):
        raise ValueError(f"Invalid contact_id format: {contact_id!r}")

_cache: Dict[str, Any] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["v"]
    return None


def _cache_set(key: str, value) -> None:
    _cache[key] = {"v": value, "ts": time.time()}


def _queue_lookup(connect_client, instance_id: str) -> Dict[str, str]:
    cache_key = f"{instance_id}/queues"
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
    cache_key = f"{instance_id}/{user_id}"
    cached_name = _cache_get(cache_key)
    if cached_name is not None:
        return cached_name

    try:
        user = connect_client.describe_user(InstanceId=instance_id, UserId=user_id).get("User", {})
        identity = user.get("IdentityInfo", {})
        agent_name = " ".join(part for part in [identity.get("FirstName"), identity.get("LastName")] if part) or user.get("Username", user_id)
        _cache_set(cache_key, agent_name)
        return agent_name
    except Exception:  # pylint: disable=broad-except
        return user_id


def lambda_handler(event, _context):
    try:
        LOGGER.info(json.dumps({"event": "lambda_invoked", "function": event.get("function", "unknown")}))
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        contact_id = params.get("contact_id")
        if contact_id:
            try:
                _validate_contact_id(contact_id)
            except ValueError as exc:
                return {"error": str(exc), "status": "invalid_input"}
        keyword = params.get("keyword")
        if not keyword:
            raise ValueError("keyword is required.")

        start_time = parse_datetime(params.get("start_time"))
        end_time = parse_datetime(params.get("end_time"))
        if not start_time or not end_time:
            raise ValueError("start_time and end_time are required in ISO 8601 format.")

        max_results = min(int(params.get("max_results") or 25), 100)

        # SearchContacts ContactAnalysis only accepts AGENT or CUSTOMER — not ALL.
        # Use two criteria with MATCH_ANY so contacts where EITHER side mentions the keyword are returned.
        transcript_criteria: Dict[str, Any] = {
            "ContactAnalysis": {
                "Transcript": {
                    "Criteria": [
                        {"ParticipantRole": "AGENT", "SearchText": [keyword], "MatchType": "MATCH_ALL"},
                        {"ParticipantRole": "CUSTOMER", "SearchText": [keyword], "MatchType": "MATCH_ALL"},
                    ],
                    "MatchType": "MATCH_ANY",
                }
            }
        }
        if params.get("queue_id"):
            transcript_criteria["QueueIds"] = [params["queue_id"]]

        # Try transcript keyword search first (requires Contact Lens).
        # Fall back to a plain time-range search if Contact Lens is disabled/unavailable.
        contact_lens_available = True
        try:
            response = _CONNECT_CLIENT.search_contacts(
                InstanceId=instance_id,
                TimeRange={"Type": "INITIATION_TIMESTAMP", "StartTime": start_time, "EndTime": end_time},
                SearchCriteria=transcript_criteria,
                MaxResults=max_results,
                Sort={"FieldName": "INITIATION_TIMESTAMP", "Order": "DESCENDING"},
            )
        except (BotoCoreError, ClientError) as exc:
            err_msg = str(exc)
            if "BadRequestException" in err_msg or "InvalidRequest" in err_msg or "ContactAnalysis" in err_msg:
                LOGGER.warning("Contact Lens transcript search failed (%s); falling back to time-range search.", exc)
                contact_lens_available = False
                fallback_kwargs: Dict[str, Any] = {
                    "InstanceId": instance_id,
                    "TimeRange": {"Type": "INITIATION_TIMESTAMP", "StartTime": start_time, "EndTime": end_time},
                    "MaxResults": max_results,
                    "Sort": {"FieldName": "INITIATION_TIMESTAMP", "Order": "DESCENDING"},
                }
                if params.get("queue_id"):
                    fallback_kwargs["SearchCriteria"] = {"QueueIds": [params["queue_id"]]}
                response = _CONNECT_CLIENT.search_contacts(**fallback_kwargs)
            else:
                raise

        queue_names = _queue_lookup(_CONNECT_CLIENT, instance_id)
        matches: List[Dict[str, Any]] = []
        for contact in response.get("Contacts", []):
            queue_id = ((contact.get("QueueInfo") or {}).get("Id"))
            agent_id = ((contact.get("AgentInfo") or {}).get("Id"))
            start = contact.get("InitiationTimestamp")
            end = contact.get("DisconnectTimestamp")
            duration_seconds = max((end - start).total_seconds(), 0) if start and end else None
            matches.append(
                {
                    "contact_id": contact.get("Id"),
                    "timestamp": start,
                    "queue": queue_names.get(queue_id, queue_id),
                    "queue_id": queue_id,
                    "agent": _agent_name(_CONNECT_CLIENT, instance_id, agent_id) if agent_id else None,
                    "agent_id": agent_id,
                    "duration_seconds": duration_seconds,
                    "duration": format_duration(duration_seconds),
                    "channel": contact.get("Channel"),
                    "name": contact.get("Name"),
                    "keyword": keyword,
                }
            )

        return build_response(
            event,
            {
                "instance_id": instance_id,
                "keyword": keyword,
                "contact_lens_search": contact_lens_available,
                "contact_lens_note": None if contact_lens_available else (
                    "Contact Lens transcript search is unavailable for this instance. "
                    "Results show all contacts in the time window instead of keyword matches. "
                    "Enable Contact Lens in your Amazon Connect instance to search by keyword."
                ),
                "search_window": {"start_time": start_time, "end_time": end_time},
                "returned_count": len(matches),
                "matches": matches,
            },
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to search contact transcripts")
        return build_error_response(event, f"Unable to search Amazon Connect transcripts by keyword: {exc}", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while searching contact transcripts")
        return build_error_response(event, str(exc), status_code=500)
