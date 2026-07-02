"""
Callback analytics for Amazon Connect Analytics Agent.

Given a date range, enumerates every CALLBACK-initiated contact (the leg
Connect creates when a customer requests a callback instead of waiting in
queue), describes each one, and groups the attempts that belong to the same
callback request via InitialContactId. In a callback the AGENT leg comes
first (an agent accepts the queued callback, then Connect dials the
customer), so each request classifies into:

  requested        — unique callback requests (groups)
  succeeded        — an agent connected AND the customer conversation
                     completed normally (no telecom-failure reason)
  customer_failed  — an agent connected but every connected attempt ended
                     with a telecom-failure reason (customer never answered,
                     busy, invalid number, …) — "succeeded at agent, failed
                     at customer"
  abandoned        — no attempt ever reached an agent; the callback expired
                     or was cancelled while waiting in the callback queue
  retried          — groups with more than one dial attempt (a subset of the
                     above — do not sum it with them). How many retries occur
                     is governed by the retry configuration on the flow's
                     callback block; this module reports what actually
                     happened, plus an attempts histogram.
  pending          — groups whose latest attempt is still in flight

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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import boto3

from contact_scan_utils import clamp_search_window, enumerate_contacts

LOGGER = logging.getLogger(__name__)

_CALLBACK_CRITERIA = {"InitiationMethods": ["CALLBACK"]}

# DisconnectReasons that mean the customer leg failed (agent side was fine).
_TELECOM_FAIL_REASONS = {
    "TELECOM_UNANSWERED",
    "TELECOM_BUSY",
    "TELECOM_NUMBER_INVALID",
    "TELECOM_POTENTIAL_BLOCKING",
    "TELECOM_TIMEOUT",
    "TELECOM_PROBLEM",
    "OUTBOUND_ATTEMPT_FAILED",
    "OUTBOUND_DESTINATION_ENDPOINT_ERROR",
    "OUTBOUND_RESOURCE_ERROR",
}

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


def classify_group(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify one callback request (its list of attempt details) into
    succeeded / customer_failed / abandoned / pending, with the reason of the
    decisive attempt. Shared with contact_stats' live "today" snapshot."""
    connected = [a for a in attempts if (a.get("AgentInfo") or {}).get("ConnectedToAgentTimestamp")]
    all_disconnected = all(a.get("DisconnectTimestamp") for a in attempts)

    def _last(cands: List[Dict[str, Any]]) -> Dict[str, Any]:
        return max(cands, key=lambda a: a.get("InitiationTimestamp") or datetime.min.replace(tzinfo=timezone.utc))

    if connected:
        ok = [a for a in connected
              if (a.get("DisconnectReason") or "").upper() not in _TELECOM_FAIL_REASONS
              and a.get("DisconnectTimestamp")]
        active = [a for a in connected if not a.get("DisconnectTimestamp")]
        if ok:
            outcome = "succeeded"
            reason = (_last(ok).get("DisconnectReason") or "UNKNOWN").upper()
        elif active:
            outcome = "pending"   # agent on the line right now
            reason = None
        else:
            outcome = "customer_failed"
            reason = (_last(connected).get("DisconnectReason") or "UNKNOWN").upper()
    elif all_disconnected:
        outcome = "abandoned"     # expired/cancelled in the callback queue
        reason = (_last(attempts).get("DisconnectReason") or "UNKNOWN").upper()
    else:
        outcome = "pending"       # still waiting in the callback queue
        reason = None

    init_keys = [k for k in (_date_key(a.get("InitiationTimestamp")) for a in attempts) if k]
    return {
        "outcome": outcome,
        "reason": reason,
        "attempts": len(attempts),
        "date_key": min(init_keys) if init_keys else "unknown",
        "agent_connected": bool(connected),
    }


_OUTCOME_KEYS = ("succeeded", "customer_failed", "abandoned", "pending")


def _build_result(groups: Dict[str, List[Dict[str, Any]]], window: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce {group_key: [attempt detail, ...]} into the totals / daily /
    failure-reason / attempts-histogram structure the UI charts."""
    totals = {"requested": 0, "succeeded": 0, "customer_failed": 0, "abandoned": 0,
              "pending": 0, "retried": 0, "attempts": 0}
    daily: Dict[str, Dict[str, int]] = {}
    failure_counters: Dict[str, Counter] = {"customer_failed": Counter(), "abandoned": Counter()}
    attempts_histogram: Counter = Counter()

    for attempts in groups.values():
        cls = classify_group(attempts)
        totals["requested"] += 1
        totals["attempts"] += cls["attempts"]
        attempts_histogram["3+" if cls["attempts"] >= 3 else str(cls["attempts"])] += 1
        if cls["attempts"] > 1:
            totals["retried"] += 1

        totals[cls["outcome"]] += 1
        day = daily.setdefault(cls["date_key"], {"requested": 0, "succeeded": 0, "customer_failed": 0, "abandoned": 0})
        day["requested"] += 1
        if cls["outcome"] in day:
            day[cls["outcome"]] += 1
        if cls["outcome"] in failure_counters and cls["reason"]:
            failure_counters[cls["outcome"]][cls["reason"]] += 1

    resolved = totals["succeeded"] + totals["customer_failed"] + totals["abandoned"]
    totals["success_rate"] = round(totals["succeeded"] / resolved * 100, 1) if resolved else None

    daily_list = [{"date": d, **daily[d]} for d in sorted(daily.keys())]
    failure_reasons = [
        {"reason": reason, "label": reason_label(reason), "count": count, "bucket": bucket}
        for bucket, counter in failure_counters.items()
        for reason, count in counter.most_common()
    ]
    failure_reasons.sort(key=lambda r: -r["count"])
    return {
        "totals": totals,
        "daily": daily_list,
        "failure_reasons": failure_reasons,
        "attempts_histogram": [{"attempts": k, "requests": attempts_histogram[k]}
                               for k in ("1", "2", "3+") if attempts_histogram[k]],
        "window": window,
    }


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
    window = clamp_search_window(start_iso, end_iso)
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
                f"{totals['succeeded']} succeeded, {totals['customer_failed']} failed at customer, "
                f"{totals['abandoned']} abandoned, {totals['retried']} retried.",
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
        "requested": 58, "succeeded": 33, "customer_failed": 8, "abandoned": 15,
        "pending": 2, "retried": 9, "attempts": 71, "success_rate": 58.9,
    },
    "daily": [
        {"date": "2026-06-25", "requested": 7,  "succeeded": 4, "customer_failed": 1, "abandoned": 2},
        {"date": "2026-06-26", "requested": 9,  "succeeded": 5, "customer_failed": 1, "abandoned": 3},
        {"date": "2026-06-27", "requested": 8,  "succeeded": 5, "customer_failed": 1, "abandoned": 2},
        {"date": "2026-06-28", "requested": 6,  "succeeded": 4, "customer_failed": 0, "abandoned": 2},
        {"date": "2026-06-29", "requested": 10, "succeeded": 6, "customer_failed": 2, "abandoned": 2},
        {"date": "2026-06-30", "requested": 9,  "succeeded": 5, "customer_failed": 2, "abandoned": 2},
        {"date": "2026-07-01", "requested": 9,  "succeeded": 4, "customer_failed": 1, "abandoned": 2},
    ],
    "failure_reasons": [
        {"reason": "EXPIRED",                "label": "Callback expired",        "count": 9, "bucket": "abandoned"},
        {"reason": "TELECOM_UNANSWERED",     "label": "Customer didn't answer",  "count": 5, "bucket": "customer_failed"},
        {"reason": "CONTACT_FLOW_DISCONNECT","label": "Flow ended the callback", "count": 4, "bucket": "abandoned"},
        {"reason": "TELECOM_BUSY",           "label": "Customer line busy",      "count": 2, "bucket": "customer_failed"},
        {"reason": "CUSTOMER_DISCONNECT",    "label": "Customer hung up",        "count": 2, "bucket": "abandoned"},
        {"reason": "TELECOM_NUMBER_INVALID", "label": "Invalid callback number", "count": 1, "bucket": "customer_failed"},
    ],
    "attempts_histogram": [
        {"attempts": "1",  "requests": 49},
        {"attempts": "2",  "requests": 5},
        {"attempts": "3+", "requests": 4},
    ],
    "window": {"clamped": False},
}


async def run_mock_scan(start_iso: str, end_iso: str) -> None:
    started = time.time()
    window = clamp_search_window(start_iso, end_iso)
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
                f"{totals['succeeded']} succeeded, {totals['customer_failed']} failed at customer, "
                f"{totals['abandoned']} abandoned, {totals['retried']} retried. (mock)",
    )


def start_mock_scan(start_iso: str, end_iso: str) -> bool:
    global _scan_task
    if _state["running"]:
        return False
    _scan_task = asyncio.create_task(run_mock_scan(start_iso, end_iso))
    return True
