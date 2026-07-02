"""
Callback analytics for Amazon Connect Analytics Agent.

Given a date range, enumerates every CALLBACK-initiated contact (the outbound
leg Connect dials when a customer requests a callback instead of waiting in
queue), describes each one, and groups the attempts that belong to the same
callback request via InitialContactId. From those groups it derives:

  requested — unique callback requests (groups)
  handled   — groups where at least one attempt connected to an agent
              (AgentInfo.ConnectedToAgentTimestamp present)
  retried   — groups with more than one dial attempt (a subset of the above
              two — do not sum it with them)
  failed    — groups where every attempt disconnected without ever reaching
              an agent, broken down by the final attempt's DisconnectReason
  pending   — groups whose latest attempt is still in flight (neither handled
              nor failed yet)

Amazon Connect's search_contacts API caps the INITIATION_TIMESTAMP range at
1345 hours (~56 days), so scans are clamped to the last 55 days and the
result says so when that happens.

The retry-grouping model (multiple CALLBACK contacts sharing one
InitialContactId) is a best-effort interpretation of the CTR data model —
treat "Retried: 0" as "no retries detected" rather than a guarantee.

Mirrors disconnect_reasons.py's pattern: one scan runs at a time, shared
state dict, SSE events broadcast to every connected client, a polling
snapshot via get_state(). No Bedrock involved — pure Connect API data.
"""

import asyncio
import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3

from contact_scan_utils import enumerate_contacts, parse_dt

LOGGER = logging.getLogger(__name__)

# search_contacts rejects INITIATION_TIMESTAMP ranges over 1345 hours (~56
# days) — clamp to a round 55 days so the request always succeeds.
_MAX_WINDOW_DAYS = 55

_CALLBACK_CRITERIA = {"InitiationMethods": ["CALLBACK"]}

# Friendly labels for DisconnectReason values seen on failed callback attempts.
_REASON_LABELS = {
    "TELECOM_UNANSWERED": "Customer didn't answer",
    "TELECOM_BUSY": "Customer line busy",
    "TELECOM_NUMBER_INVALID": "Invalid callback number",
    "TELECOM_POTENTIAL_BLOCKING": "Call potentially blocked",
    "TELECOM_TIMEOUT": "Network timeout",
    "TELECOM_PROBLEM": "Telecom problem",
    "TELECOM_ORIGINATOR_CANCEL": "Caller cancelled",
    "CUSTOMER_NEVER_ARRIVED": "Customer never arrived",
    "CUSTOMER_DISCONNECT": "Customer hung up",
    "AGENT_DISCONNECT": "Agent-side disconnect",
    "CONTACT_FLOW_DISCONNECT": "Flow ended the callback",
    "OUTBOUND_ATTEMPT_FAILED": "Outbound attempt failed",
    "OUTBOUND_DESTINATION_ENDPOINT_ERROR": "Destination endpoint error",
    "OUTBOUND_RESOURCE_ERROR": "Outbound resource error",
    "OUTBOUND_PREVIEW_DISCARDED": "Preview discarded",
    "EXPIRED": "Callback expired",
    "THIRD_PARTY_DISCONNECT": "Third-party disconnect",
    "BARGED": "Supervisor barged",
    "OTHER": "Other",
    "UNKNOWN": "Unknown",
}


def reason_label(reason: str) -> str:
    return _REASON_LABELS.get((reason or "UNKNOWN").upper(), (reason or "UNKNOWN").replace("_", " ").title())


def _date_key(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]


def _build_result(groups: Dict[str, List[Dict[str, Any]]], window: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce {group_key: [attempt detail, ...]} into the totals / daily /
    failure-reason structure the UI charts."""
    totals = {"requested": 0, "handled": 0, "retried": 0, "failed": 0, "pending": 0, "attempts": 0}
    daily: Dict[str, Dict[str, int]] = {}
    failure_counter: Counter = Counter()

    for attempts in groups.values():
        totals["requested"] += 1
        totals["attempts"] += len(attempts)
        if len(attempts) > 1:
            totals["retried"] += 1

        handled = any((a.get("AgentInfo") or {}).get("ConnectedToAgentTimestamp") for a in attempts)
        all_disconnected = all(a.get("DisconnectTimestamp") for a in attempts)

        # The group's day is when the callback was first attempted.
        init_keys = [k for k in (_date_key(a.get("InitiationTimestamp")) for a in attempts) if k]
        day_key = min(init_keys) if init_keys else "unknown"
        day = daily.setdefault(day_key, {"requested": 0, "handled": 0, "failed": 0})
        day["requested"] += 1

        if handled:
            totals["handled"] += 1
            day["handled"] += 1
        elif all_disconnected:
            totals["failed"] += 1
            day["failed"] += 1
            # Attribute the failure to the final attempt's disconnect reason.
            last = max(
                attempts,
                key=lambda a: a.get("InitiationTimestamp") or datetime.min.replace(tzinfo=timezone.utc),
            )
            failure_counter[(last.get("DisconnectReason") or "UNKNOWN").upper()] += 1
        else:
            totals["pending"] += 1

    resolved = totals["handled"] + totals["failed"]
    totals["handle_rate"] = round(totals["handled"] / resolved * 100, 1) if resolved else None

    daily_list = [{"date": d, **daily[d]} for d in sorted(daily.keys())]
    failure_reasons = [
        {"reason": reason, "label": reason_label(reason), "count": count}
        for reason, count in failure_counter.most_common()
    ]
    return {"totals": totals, "daily": daily_list, "failure_reasons": failure_reasons, "window": window}


def _clamp_window(start_iso: str, end_iso: str) -> Dict[str, Any]:
    """Clamp the scan start so the range never exceeds search_contacts' cap."""
    start_dt = parse_dt(start_iso)
    end_dt = parse_dt(end_iso)
    max_start = end_dt - timedelta(days=_MAX_WINDOW_DAYS)
    if start_dt < max_start:
        return {"start": max_start.isoformat(), "end": end_dt.isoformat(),
                "requested_start": start_dt.isoformat(), "clamped": True}
    return {"start": start_dt.isoformat(), "end": end_dt.isoformat(),
            "requested_start": start_dt.isoformat(), "clamped": False}


# ── Shared scan state ─────────────────────────────────────────────────────────

_state: Dict[str, Any] = {
    "running": False,
    "complete": False,
    "start": None,
    "end": None,
    "clamped": False,
    "message": "No scan started yet.",
    "contacts_found": 0,
    "contacts_scanned": 0,
    "callbacks_found": 0,
    "error": None,
    "started_at": None,
    "completed_at": None,
    "result": None,   # {"totals", "daily", "failure_reasons", "window"} once available
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
        LOGGER.debug('Suppressed exception', exc_info=True)


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
    window = _clamp_window(start_iso, end_iso)
    _state.update({
        "running": True, "complete": False, "error": None,
        "start": window["start"], "end": window["end"], "clamped": window["clamped"],
        "contacts_found": 0, "contacts_scanned": 0, "callbacks_found": 0,
        "result": None,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
        "message": "Enumerating callback contacts in range…",
    })
    await _emit("scan_start", start=window["start"], end=window["end"], clamped=window["clamped"],
                message="Enumerating callback contacts in range…")

    groups: Dict[str, List[Dict[str, Any]]] = {}

    try:
        connect = boto3.client("connect", region_name=region)

        async def _on_enumerate_progress(count: int) -> None:
            await _emit("enumerating", contacts_found=count, message=f"Found {count} callback contacts so far…")

        contacts = await enumerate_contacts(
            connect, instance_id, window["start"], window["end"],
            _on_enumerate_progress, search_criteria=_CALLBACK_CRITERIA,
        )
        _state["contacts_found"] = len(contacts)
        await _emit("contacts_found", contacts_found=len(contacts),
                    message=f"{len(contacts)} callback contacts in range — analysing outcomes…")

        for i, c in enumerate(contacts):
            _state["contacts_scanned"] = i + 1
            try:
                # describe_contact is a blocking network call — off the event
                # loop so it can't stall other concurrent requests while a
                # batch of contacts is being checked.
                resp = await asyncio.to_thread(
                    connect.describe_contact, InstanceId=instance_id, ContactId=c["contact_id"],
                )
                detail = resp.get("Contact", {})
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.warning("describe_contact failed for %s: %s", c["contact_id"], exc)
                detail = {}

            group_key = detail.get("InitialContactId") or detail.get("Id") or c["contact_id"]
            groups.setdefault(group_key, []).append(detail)
            _state["callbacks_found"] = len(groups)

            if (i + 1) % 20 == 0 or i == len(contacts) - 1:
                await _emit(
                    "progress",
                    contacts_scanned=_state["contacts_scanned"],
                    callbacks_found=_state["callbacks_found"],
                    message=f"Checked {_state['contacts_scanned']}/{len(contacts)} callback contacts, "
                            f"{_state['callbacks_found']} callback requests so far…",
                )
            await asyncio.sleep(0)

    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Callback-analytics scan failed: %s", exc)
        _state["running"] = False
        _state["error"] = str(exc)
        await _emit("scan_error", message=str(exc))
        return

    result = _build_result(groups, window)
    duration = round(time.time() - started, 1)
    _state["running"] = False
    _state["complete"] = True
    _state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _state["result"] = result
    totals = result["totals"]
    await _emit(
        "scan_complete",
        result=result,
        duration_sec=duration,
        contacts_found=_state["contacts_found"],
        contacts_scanned=_state["contacts_scanned"],
        callbacks_found=_state["callbacks_found"],
        message=f"Scan complete — {totals['requested']} callback requests: "
                f"{totals['handled']} handled, {totals['failed']} failed, {totals['retried']} retried.",
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
    "totals": {
        "requested": 58, "handled": 41, "retried": 9, "failed": 17,
        "pending": 0, "attempts": 71, "handle_rate": 70.7,
    },
    "daily": [
        {"date": "2026-06-25", "requested": 7,  "handled": 5, "failed": 2},
        {"date": "2026-06-26", "requested": 9,  "handled": 6, "failed": 3},
        {"date": "2026-06-27", "requested": 8,  "handled": 6, "failed": 2},
        {"date": "2026-06-28", "requested": 6,  "handled": 4, "failed": 2},
        {"date": "2026-06-29", "requested": 10, "handled": 7, "failed": 3},
        {"date": "2026-06-30", "requested": 9,  "handled": 7, "failed": 2},
        {"date": "2026-07-01", "requested": 9,  "handled": 6, "failed": 3},
    ],
    "failure_reasons": [
        {"reason": "TELECOM_UNANSWERED",    "label": "Customer didn't answer",   "count": 8},
        {"reason": "TELECOM_BUSY",          "label": "Customer line busy",       "count": 3},
        {"reason": "CUSTOMER_DISCONNECT",   "label": "Customer hung up",         "count": 3},
        {"reason": "EXPIRED",               "label": "Callback expired",         "count": 2},
        {"reason": "TELECOM_NUMBER_INVALID","label": "Invalid callback number",  "count": 1},
    ],
    "window": {"clamped": False},
}


async def run_mock_scan(start_iso: str, end_iso: str) -> None:
    started = time.time()
    window = _clamp_window(start_iso, end_iso)
    total_contacts = 71
    _state.update({
        "running": True, "complete": False, "error": None,
        "start": window["start"], "end": window["end"], "clamped": window["clamped"],
        "contacts_found": 0, "contacts_scanned": 0, "callbacks_found": 0,
        "result": None,
        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
        "message": "Enumerating callback contacts in range… (mock)",
    })
    await _emit("scan_start", start=window["start"], end=window["end"], clamped=window["clamped"],
                message="Enumerating callback contacts in range… (mock)")
    await asyncio.sleep(0.3)

    _state["contacts_found"] = total_contacts
    await _emit("contacts_found", contacts_found=total_contacts,
                message=f"{total_contacts} callback contacts in range — analysing outcomes… (mock)")
    await asyncio.sleep(0.2)

    total_requests = _MOCK_RESULT["totals"]["requested"]
    steps = 8
    for step in range(1, steps + 1):
        scanned = round(total_contacts * step / steps)
        found = round(total_requests * step / steps)
        _state["contacts_scanned"] = scanned
        _state["callbacks_found"] = found
        await _emit(
            "progress",
            contacts_scanned=scanned,
            callbacks_found=found,
            message=f"Checked {scanned}/{total_contacts} callback contacts, {found} callback requests so far… (mock)",
        )
        await asyncio.sleep(0.2)

    mock_result = {**_MOCK_RESULT, "window": window}
    duration = round(time.time() - started, 1)
    _state["running"] = False
    _state["complete"] = True
    _state["completed_at"] = datetime.now(timezone.utc).isoformat()
    _state["result"] = mock_result
    totals = mock_result["totals"]
    await _emit(
        "scan_complete",
        result=mock_result,
        duration_sec=duration,
        contacts_found=total_contacts,
        contacts_scanned=total_contacts,
        callbacks_found=total_requests,
        message=f"Scan complete — {totals['requested']} callback requests: "
                f"{totals['handled']} handled, {totals['failed']} failed, {totals['retried']} retried. (mock)",
    )


def start_mock_scan(start_iso: str, end_iso: str) -> bool:
    global _scan_task
    if _state["running"]:
        return False
    _scan_task = asyncio.create_task(run_mock_scan(start_iso, end_iso))
    return True
