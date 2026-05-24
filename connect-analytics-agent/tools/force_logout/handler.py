import json
import logging
import os
import time
from typing import Any, Dict, List

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, get_instance_id, parse_parameters

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
_cache: Dict[str, Any] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["v"]
    return None


def _cache_set(key: str, value) -> None:
    _cache[key] = {"v": value, "ts": time.time()}

# Statuses that indicate the agent has an active / unclosed contact
_BLOCKING_STATUSES = {"ON_CALL", "AFTER_CONTACT_WORK"}


def _get_agent_current_data(connect_client, instance_id: str, user_id: str) -> Dict[str, Any]:
    """Return the current user-data entry for a single agent, or {} if not found."""
    response = _CONNECT_CLIENT.get_current_user_data(
        InstanceId=instance_id,
        Filters={"Agents": [user_id]},
        MaxResults=1,
    )
    entries = response.get("UserDataList", [])
    return entries[0] if entries else {}


def _has_active_contacts(user_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the list of active contacts, empty if the agent is clear."""
    return user_data.get("Contacts", [])


def _get_offline_status_id(connect_client, instance_id: str) -> str:
    """Retrieve the Amazon Connect status ID that corresponds to 'Offline'."""
    cache_key = f"{instance_id}/offline_status"
    cached_value = _cache_get(cache_key)
    if cached_value is not None:
        return cached_value

    paginator = _CONNECT_CLIENT.get_paginator("list_agent_statuses")
    for page in paginator.paginate(InstanceId=instance_id):
        for status in page.get("AgentStatusSummaryList", []):
            if status.get("Name", "").lower() == "offline":
                offline_status_id = status["Id"]
                _cache_set(cache_key, offline_status_id)
                return offline_status_id
    raise ValueError("Could not find an 'Offline' agent status in this Connect instance.")


def lambda_handler(event, _context):
    try:
        LOGGER.info(json.dumps({"event": "lambda_invoked", "function": event.get("function", "unknown")}))
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        user_id = params.get("user_id") or params.get("agent_id")

        if not user_id:
            return build_error_response(event, "user_id (agent_id) is required.", status_code=400)

        # ── 1. Check for active contacts ─────────────────────────────────────
        user_data = _get_agent_current_data(_CONNECT_CLIENT, instance_id, user_id)
        active_contacts = _has_active_contacts(user_data)

        if active_contacts:
            contact_summaries = [
                {
                    "contact_id": c.get("ContactId"),
                    "channel": c.get("Channel"),
                    "state": c.get("AgentContactState"),
                    "queue": (c.get("Queue") or {}).get("Id"),
                }
                for c in active_contacts
            ]
            return build_response(
                event,
                {
                    "forced": False,
                    "blocked": True,
                    "reason": (
                        f"Agent has {len(active_contacts)} active contact(s). "
                        "End or transfer all contacts before forcing logout."
                    ),
                    "active_contacts": contact_summaries,
                },
                status_code=409,
            )

        # ── 2. Also guard on ACW — current status check ───────────────────────
        status_name = (user_data.get("Status") or {}).get("StatusName", "").lower()
        if "after" in status_name or "acw" in status_name:
            return build_response(
                event,
                {
                    "forced": False,
                    "blocked": True,
                    "reason": (
                        "Agent is in After Contact Work (ACW). "
                        "The contact has not been fully closed yet. "
                        "Wait for ACW to complete or ask the agent to close the contact."
                    ),
                    "active_contacts": [],
                },
                status_code=409,
            )

        # ── 3. Get Offline status ID ──────────────────────────────────────────
        offline_status_id = _get_offline_status_id(_CONNECT_CLIENT, instance_id)

        # ── 4. Force the agent to Offline ────────────────────────────────────
        _CONNECT_CLIENT.put_user_status(
            InstanceId=instance_id,
            UserId=user_id,
            AgentStatusId=offline_status_id,
        )

        LOGGER.info("Force-logged out agent %s in instance %s", user_id, instance_id)

        return build_response(
            event,
            {
                "forced": True,
                "blocked": False,
                "user_id": user_id,
                "new_status": "Offline",
                "message": f"Agent {user_id} has been forced to Offline successfully.",
            },
        )

    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("AWS error during force logout for user_id=%s", event)
        return build_error_response(event, f"AWS error during force logout: {exc}", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error during force logout")
        return build_error_response(event, str(exc), status_code=500)
