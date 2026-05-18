import logging
from typing import Any, Dict, List

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, get_instance_id, parse_parameters

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

# Statuses that indicate the agent has an active / unclosed contact
_BLOCKING_STATUSES = {"ON_CALL", "AFTER_CONTACT_WORK"}


def _get_agent_current_data(connect_client, instance_id: str, user_id: str) -> Dict[str, Any]:
    """Return the current user-data entry for a single agent, or {} if not found."""
    response = connect_client.get_current_user_data(
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
    paginator = connect_client.get_paginator("list_agent_statuses")
    for page in paginator.paginate(InstanceId=instance_id):
        for status in page.get("AgentStatusSummaryList", []):
            if status.get("Name", "").lower() == "offline":
                return status["Id"]
    raise ValueError("Could not find an 'Offline' agent status in this Connect instance.")


def lambda_handler(event, _context):
    try:
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        user_id = params.get("user_id") or params.get("agent_id")

        if not user_id:
            return build_error_response(event, "user_id (agent_id) is required.", status_code=400)

        connect_client = boto3.client("connect")

        # ── 1. Check for active contacts ─────────────────────────────────────
        user_data = _get_agent_current_data(connect_client, instance_id, user_id)
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
        offline_status_id = _get_offline_status_id(connect_client, instance_id)

        # ── 4. Force the agent to Offline ────────────────────────────────────
        connect_client.put_user_status(
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
