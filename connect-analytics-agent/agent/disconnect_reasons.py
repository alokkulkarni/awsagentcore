"""
Disconnect-reason discovery for Amazon Connect Analytics Agent.

Given a date range, scans every contact and classifies the ones that did
NOT complete via a normal customer-ended, agent-connected call into a
Customer / Agent / Technical / Other reason bucket, using Amazon Connect's
own DisconnectReason and DisconnectDetails.PotentialDisconnectIssue fields
(see https://docs.aws.amazon.com/connect/latest/adminguide/ctr-data-model.html).

Two populations feed this breakdown:
  1. "abandoned"       — the contact never reached an agent (matches Connect's
                          own CONTACTS_ABANDONED metric exactly).
  2. "handled_problem" — the contact DID reach an agent, but disconnected via
                          an agent-side or technical reason (or a detected
                          telecom/technical issue), rather than a plain
                          customer hangup. A normal, successfully completed
                          call (agent-connected, customer hangs up, no
                          detected issue) is deliberately excluded — it is
                          indistinguishable from any other successful call.

Mirrors theme_scan.py's pattern: one scan runs at a time, shared state dict,
SSE events broadcast to every connected client, a polling snapshot via
get_state(). No Bedrock involved — this is pure Connect API data.
"""

import asyncio
import json
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3

from contact_scan_utils import enumerate_contacts

LOGGER = logging.getLogger(__name__)

_CUSTOMER = "customer"
_AGENT = "agent"
_TECHNICAL = "technical"
_OTHER = "other"

# Channel-aware DisconnectReason → bucket mapping, per AWS's CTR data model docs.
_VOICE_REASON_BUCKET = {
    "TELECOM_BUSY": _TECHNICAL,
    "TELECOM_NUMBER_INVALID": _TECHNICAL,
    "TELECOM_POTENTIAL_BLOCKING": _TECHNICAL,
    "TELECOM_UNANSWERED": _TECHNICAL,
    "TELECOM_TIMEOUT": _TECHNICAL,
    "TELECOM_PROBLEM": _TECHNICAL,
    "TELECOM_ORIGINATOR_CANCEL": _CUSTOMER,   # inbound: customer cancelled before connecting
    "CUSTOMER_NEVER_ARRIVED": _CUSTOMER,
    "THIRD_PARTY_DISCONNECT": _OTHER,
    "CUSTOMER_DISCONNECT": _CUSTOMER,
    "AGENT_DISCONNECT": _AGENT,
    "BARGED": _OTHER,                          # supervisor disconnected the agent
    "CONTACT_FLOW_DISCONNECT": _OTHER,
    "OTHER": _OTHER,
    "OUTBOUND_DESTINATION_ENDPOINT_ERROR": _TECHNICAL,
    "OUTBOUND_RESOURCE_ERROR": _TECHNICAL,
    "OUTBOUND_ATTEMPT_FAILED": _TECHNICAL,
    "OUTBOUND_PREVIEW_DISCARDED": _OTHER,
    "EXPIRED": _OTHER,
}

_CHAT_REASON_BUCKET = {
    "AGENT_DISCONNECT": _AGENT,
    "CUSTOMER_DISCONNECT": _CUSTOMER,
    "AGENT_NETWORK_DISCONNECT": _TECHNICAL,
    "CUSTOMER_CONNECTION_NOT_ESTABLISHED": _CUSTOMER,
    "EXPIRED": _OTHER,
    "CONTACT_FLOW_DISCONNECT": _OTHER,
    "API": _OTHER,
    "BARGED": _OTHER,
    "IDLE_DISCONNECT": _OTHER,
    "THIRD_PARTY_DISCONNECT": _OTHER,
    "SYSTEM_ERROR": _TECHNICAL,
}

_TASK_REASON_BUCKET = {
    "AGENT_COMPLETED": _AGENT,
    "AGENT_DISCONNECT": _AGENT,
    "EXPIRED": _OTHER,
    "CONTACT_FLOW_DISCONNECT": _OTHER,
    "API": _OTHER,
    "OTHER": _OTHER,
}

_EMAIL_REASON_BUCKET = {
    "TRANSFERRED": _OTHER,
    "AGENT_DISCONNECT": _AGENT,
    "EXPIRED": _OTHER,
    "DISCARDED": _OTHER,
    "CONTACT_FLOW_DISCONNECT": _OTHER,
    "API": _OTHER,
    "OTHER": _OTHER,
}

_CHANNEL_MAPS = {
    "VOICE": _VOICE_REASON_BUCKET,
    "CHAT": _CHAT_REASON_BUCKET,
    "TASK": _TASK_REASON_BUCKET,
    "EMAIL": _EMAIL_REASON_BUCKET,
}


def _bucket_for(channel: str, disconnect_reason: Optional[str], potential_issue: Optional[str]) -> str:
    """A detected telecom/technical issue always wins, regardless of the primary
    DisconnectReason — e.g. a call reported as CUSTOMER_DISCONNECT that also had
    detected packet loss is bucketed Technical, not Customer."""
    if potential_issue:
        return _TECHNICAL
    reason_map = _CHANNEL_MAPS.get((channel or "VOICE").upper(), _VOICE_REASON_BUCKET)
    return reason_map.get((disconnect_reason or "").upper(), _OTHER)


def _classify_contact(detail: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Returns {"bucket", "population", "date_key", "raw_reason"} or None if this
    contact should be excluded (still active, or a normal successfully completed
    agent-connected call with a plain customer hangup and no detected issue)."""
    disconnect_ts = detail.get("DisconnectTimestamp")
    if not disconnect_ts:
        return None

    channel = detail.get("Channel", "VOICE")
    agent_info = detail.get("AgentInfo") or {}
    reached_agent = bool(agent_info.get("ConnectedToAgentTimestamp"))
    disconnect_reason = detail.get("DisconnectReason")
    disconnect_details = detail.get("DisconnectDetails") or {}
    potential_issue = disconnect_details.get("PotentialDisconnectIssue")

    bucket = _bucket_for(channel, disconnect_reason, potential_issue)

    if not reached_agent:
        population = "abandoned"
    elif bucket != _CUSTOMER or potential_issue:
        population = "handled_problem"
    else:
        return None  # normal, successfully completed call — not part of this breakdown

    date_key = disconnect_ts.strftime("%Y-%m-%d") if hasattr(disconnect_ts, "strftime") else str(disconnect_ts)[:10]
    raw_reason = potential_issue or disconnect_reason or "UNKNOWN"
    return {"bucket": bucket, "population": population, "date_key": date_key, "raw_reason": raw_reason}


def _build_result(
    bucket_totals: Dict[str, int],
    population_totals: Dict[str, int],
    daily: Dict[str, Dict[str, int]],
    reason_counters: Dict[str, Counter],
) -> Dict[str, Any]:
    daily_list = [{"date": d, **daily[d]} for d in sorted(daily.keys())]
    top_reasons = {bucket: counter.most_common(3) for bucket, counter in reason_counters.items()}
    return {
        "totals": {**bucket_totals, **population_totals},
        "daily": daily_list,
        "top_reasons": top_reasons,
    }


# ── Shared scan state ─────────────────────────────────────────────────────────

_state: Dict[str, Any] = {
    "running": False,
    "complete": False,
    "start": None,
    "end": None,
    "message": "No scan started yet.",
    "contacts_found": 0,
    "contacts_scanned": 0,
    "unsuccessful_found": 0,
    "error": None,
    "started_at": None,
    "completed_at": None,
    "result": None,   # {"totals": {...}, "daily": [...], "top_reasons": {...}} once available
}

_sse_queues: List[asyncio.Queue] = []
_scan_task: Optional[asyncio.Task] = None


def get_state() -> Dict[str, Any]:
    return dict(_state)


def register_queue(q: asyncio.Queue) -> None:
    _sse_queues.append(q)


def unregister_queue(q: asyncio.Queue) -> None:
    try:
        _sse_queues.remove(q)
    except ValueError:
        pass


def is_running() -> bool:
    return _state["running"]


async def _emit(event_type: str, **kwargs: Any) -> None:
    for k, v in kwargs.items():
        if k in _state:
            _state[k] = v
    payload = json.dumps({
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }, default=str)
    msg = f"data: {payload}\n\n"
    dead = []
    for q in list(_sse_queues):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        unregister_queue(q)


# ── Main pipeline ────────────────────────────────────────────────────────────

async def run_scan(start_iso: str, end_iso: str, instance_id: str, region: str) -> None:
    started = time.time()
    _state.update({
        "running": True, "complete": False, "error": None,
        "start": start_iso, "end": end_iso,
        "contacts_found": 0, "contacts_scanned": 0, "unsuccessful_found": 0,
        "result": None,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
        "message": "Enumerating contacts in range…",
    })
    await _emit("scan_start", start=start_iso, end=end_iso, message="Enumerating contacts in range…")

    bucket_totals = {"customer": 0, "agent": 0, "technical": 0, "other": 0}
    population_totals = {"abandoned": 0, "handled_problem": 0}
    daily: Dict[str, Dict[str, int]] = {}
    reason_counters: Dict[str, Counter] = {
        "customer": Counter(), "agent": Counter(), "technical": Counter(), "other": Counter(),
    }

    try:
        connect = boto3.client("connect", region_name=region)

        async def _on_enumerate_progress(count: int) -> None:
            await _emit("enumerating", contacts_found=count, message=f"Found {count} contacts so far…")

        contacts = await enumerate_contacts(connect, instance_id, start_iso, end_iso, _on_enumerate_progress)
        _state["contacts_found"] = len(contacts)
        await _emit("contacts_found", contacts_found=len(contacts),
                    message=f"{len(contacts)} contacts in range — checking disconnect reasons…")

        for i, c in enumerate(contacts):
            _state["contacts_scanned"] = i + 1
            try:
                # describe_contact is a blocking network call — off the event
                # loop so it can't stall other concurrent requests (background
                # polling from other screens, the SSE stream itself, etc.)
                # while a batch of contacts is being checked.
                resp = await asyncio.to_thread(
                    connect.describe_contact, InstanceId=instance_id, ContactId=c["contact_id"],
                )
                detail = resp.get("Contact", {})
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.warning("describe_contact failed for %s: %s", c["contact_id"], exc)
                detail = {}

            classified = _classify_contact(detail)
            if classified:
                bucket = classified["bucket"]
                bucket_totals[bucket] += 1
                population_totals[classified["population"]] += 1
                day = daily.setdefault(classified["date_key"], {"customer": 0, "agent": 0, "technical": 0, "other": 0})
                day[bucket] += 1
                reason_counters[bucket][classified["raw_reason"]] += 1
                _state["unsuccessful_found"] += 1

            if (i + 1) % 20 == 0 or i == len(contacts) - 1:
                await _emit(
                    "progress",
                    contacts_scanned=_state["contacts_scanned"],
                    unsuccessful_found=_state["unsuccessful_found"],
                    message=f"Checked {_state['contacts_scanned']}/{len(contacts)} contacts, "
                            f"{_state['unsuccessful_found']} unsuccessful so far…",
                )
            await asyncio.sleep(0)

    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Disconnect-reason scan failed: %s", exc)
        _state["running"] = False
        _state["error"] = str(exc)
        await _emit("scan_error", message=str(exc))
        return

    result = _build_result(bucket_totals, population_totals, daily, reason_counters)
    duration = round(time.time() - started, 1)
    _state["running"] = False
    _state["complete"] = True
    _state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _state["result"] = result
    await _emit(
        "scan_complete",
        result=result,
        duration_sec=duration,
        contacts_found=_state["contacts_found"],
        contacts_scanned=_state["contacts_scanned"],
        unsuccessful_found=_state["unsuccessful_found"],
        message=f"Scan complete — {_state['unsuccessful_found']} unsuccessful contacts found "
                f"across {_state['contacts_found']} scanned.",
    )


def start_scan(start_iso: str, end_iso: str, instance_id: str, region: str) -> bool:
    """Kick off a scan if none is currently running. Returns True if started."""
    global _scan_task
    if _state["running"]:
        return False
    _scan_task = asyncio.create_task(run_scan(start_iso, end_iso, instance_id, region))
    return True


# ── MOCK_MODE simulation ─────────────────────────────────────────────────────

_MOCK_RESULT = {
    "totals": {"customer": 42, "agent": 9, "technical": 15, "other": 6, "abandoned": 51, "handled_problem": 21},
    "daily": [
        {"date": "2026-06-25", "customer": 6, "agent": 1, "technical": 2, "other": 1},
        {"date": "2026-06-26", "customer": 5, "agent": 2, "technical": 3, "other": 0},
        {"date": "2026-06-27", "customer": 7, "agent": 1, "technical": 1, "other": 1},
        {"date": "2026-06-28", "customer": 4, "agent": 0, "technical": 2, "other": 1},
        {"date": "2026-06-29", "customer": 8, "agent": 2, "technical": 3, "other": 1},
        {"date": "2026-06-30", "customer": 6, "agent": 2, "technical": 2, "other": 1},
        {"date": "2026-07-01", "customer": 6, "agent": 1, "technical": 2, "other": 1},
    ],
    "top_reasons": {
        "customer": [["CUSTOMER_DISCONNECT", 40], ["CUSTOMER_NEVER_ARRIVED", 2]],
        "agent": [["AGENT_DISCONNECT", 8], ["AGENT_NETWORK_DISCONNECT", 1]],
        "technical": [["TELECOM_TIMEOUT", 7], ["TELECOM_UNANSWERED", 5], ["TELECOM_PROBLEM", 3]],
        "other": [["CONTACT_FLOW_DISCONNECT", 4], ["BARGED", 2]],
    },
}


async def run_mock_scan(start_iso: str, end_iso: str) -> None:
    started = time.time()
    total_contacts = 340
    _state.update({
        "running": True, "complete": False, "error": None,
        "start": start_iso, "end": end_iso,
        "contacts_found": 0, "contacts_scanned": 0, "unsuccessful_found": 0,
        "result": None,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
        "message": "Enumerating contacts in range… (mock)",
    })
    await _emit("scan_start", start=start_iso, end=end_iso, message="Enumerating contacts in range… (mock)")
    await asyncio.sleep(0.3)

    _state["contacts_found"] = total_contacts
    await _emit("contacts_found", contacts_found=total_contacts,
                message=f"{total_contacts} contacts in range — checking disconnect reasons… (mock)")
    await asyncio.sleep(0.2)

    total_unsuccessful = sum(v for k, v in _MOCK_RESULT["totals"].items() if k in ("customer", "agent", "technical", "other"))
    steps = 8
    for step in range(1, steps + 1):
        scanned = round(total_contacts * step / steps)
        found = round(total_unsuccessful * step / steps)
        _state["contacts_scanned"] = scanned
        _state["unsuccessful_found"] = found
        await _emit(
            "progress",
            contacts_scanned=scanned,
            unsuccessful_found=found,
            message=f"Checked {scanned}/{total_contacts} contacts, {found} unsuccessful so far… (mock)",
        )
        await asyncio.sleep(0.2)

    duration = round(time.time() - started, 1)
    _state["running"] = False
    _state["complete"] = True
    _state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _state["result"] = _MOCK_RESULT
    await _emit(
        "scan_complete",
        result=_MOCK_RESULT,
        duration_sec=duration,
        contacts_found=total_contacts,
        contacts_scanned=total_contacts,
        unsuccessful_found=total_unsuccessful,
        message=f"Scan complete — {total_unsuccessful} unsuccessful contacts found across {total_contacts} scanned. (mock)",
    )


def start_mock_scan(start_iso: str, end_iso: str) -> bool:
    global _scan_task
    if _state["running"]:
        return False
    _scan_task = asyncio.create_task(run_mock_scan(start_iso, end_iso))
    return True
