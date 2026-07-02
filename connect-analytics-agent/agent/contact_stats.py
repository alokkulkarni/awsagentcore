"""
Synchronous contact-record statistics for Amazon Connect Analytics Agent.

Unlike the SSE scan modules (theme_scan, disconnect_reasons,
callback_analytics), these helpers answer quickly enough to serve a normal
GET request: they page search_contacts summaries — which already carry
QueueInfo.EnqueueTimestamp, AgentInfo.ConnectedToAgentTimestamp and
DisconnectTimestamp — so no per-contact describe_contact is needed for the
abandonment computation. (This instance's GetMetricDataV2 API has no
CONTACTS_ABANDONED_IN_X threshold metric and no INITIATION_METHOD filter —
verified live — hence the contact-record approach.)

Two computations:

1. abandonment_buckets — calls abandoned in queue, bucketed by how long the
   customer waited before giving up: ≤10s, ≤20s, ≤30s, ≤40s, ≤1m, ≤2m, >2m.
   Wait = DisconnectTimestamp − QueueInfo.EnqueueTimestamp. A contact counts
   as abandoned when it was enqueued, never reached an agent, and has
   disconnected.

2. callback_snapshot — a point-in-time view of callbacks in a window
   (normally "today so far"), classified with callback_analytics'
   classify_group: requested / waiting in queue now / agent connected now /
   succeeded / customer_failed / abandoned / retried. Callback contacts are
   described individually (DisconnectReason and InitialContactId are not in
   the search summary), so the describe count is capped.

Both use search_contacts, so windows are clamped to 55 days (see
contact_scan_utils.clamp_search_window).
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import boto3

from contact_scan_utils import clamp_search_window, enumerate_contact_summaries

import callback_analytics

LOGGER = logging.getLogger(__name__)

# Upper bounds (seconds) for the wait-time buckets; the final bucket catches
# everything above the last bound.
ABANDON_BUCKETS = [
    {"key": "lt10",    "label": "≤ 10s",  "max": 10},
    {"key": "lt20",    "label": "≤ 20s",  "max": 20},
    {"key": "lt30",    "label": "≤ 30s",  "max": 30},
    {"key": "lt40",    "label": "≤ 40s",  "max": 40},
    {"key": "lt60",    "label": "≤ 1m",   "max": 60},
    {"key": "lt120",   "label": "≤ 2m",   "max": 120},
    {"key": "over120", "label": "> 2m",   "max": None},
]
BUCKET_KEYS = [b["key"] for b in ABANDON_BUCKETS]

_MAX_SEARCH_PAGES = 40   # 100 contacts/page — bounds the sync endpoint on busy instances
_MAX_DESCRIBES = 200     # callback snapshot cap


def bucket_key_for_wait(seconds: float) -> str:
    for b in ABANDON_BUCKETS:
        if b["max"] is not None and seconds <= b["max"]:
            return b["key"]
    return ABANDON_BUCKETS[-1]["key"]


def _date_key(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if hasattr(ts, "strftime"):
        return ts.strftime("%Y-%m-%d")
    return str(ts)[:10]


async def abandonment_buckets(instance_id: str, region: str, start_iso: str, end_iso: str) -> Dict[str, Any]:
    """Totals + daily series of abandoned-in-queue contacts by wait-time bucket."""
    connect = boto3.client("connect", region_name=region)
    window = clamp_search_window(start_iso, end_iso)
    summaries = await enumerate_contact_summaries(
        connect, instance_id, window["start"], window["end"], max_pages=_MAX_SEARCH_PAGES,
    )

    totals = {k: 0 for k in BUCKET_KEYS}
    daily: Dict[str, Dict[str, int]] = {}
    for c in summaries:
        queue_info = c.get("QueueInfo") or {}
        agent_info = c.get("AgentInfo") or {}
        enqueued = queue_info.get("EnqueueTimestamp")
        disconnected = c.get("DisconnectTimestamp")
        if not enqueued or not disconnected or agent_info.get("ConnectedToAgentTimestamp"):
            continue
        wait_sec = max(0.0, (disconnected - enqueued).total_seconds())
        key = bucket_key_for_wait(wait_sec)
        totals[key] += 1
        day = daily.setdefault(_date_key(enqueued), {k: 0 for k in BUCKET_KEYS})
        day[key] += 1

    truncated = len(summaries) >= _MAX_SEARCH_PAGES * 100
    return {
        "buckets": [{**b, "count": totals[b["key"]]} for b in ABANDON_BUCKETS],
        "daily": [{"date": d, **daily[d]} for d in sorted(daily.keys())],
        "total_abandoned": sum(totals.values()),
        "contacts_scanned": len(summaries),
        "truncated": truncated,
        "window": window,
    }


async def callback_snapshot(instance_id: str, region: str, start_iso: str, end_iso: str) -> Dict[str, Any]:
    """Point-in-time callback outcomes for a window (normally today so far)."""
    connect = boto3.client("connect", region_name=region)
    window = clamp_search_window(start_iso, end_iso)
    summaries = await enumerate_contact_summaries(
        connect, instance_id, window["start"], window["end"],
        search_criteria={"InitiationMethods": ["CALLBACK"]},
        max_pages=_MAX_SEARCH_PAGES,
    )

    truncated = len(summaries) > _MAX_DESCRIBES
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in summaries[:_MAX_DESCRIBES]:
        try:
            resp = await asyncio.to_thread(
                connect.describe_contact, InstanceId=instance_id, ContactId=c["Id"],
            )
            detail = resp.get("Contact", {})
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("describe_contact failed for %s: %s", c.get("Id"), exc)
            detail = c  # summary is still classifiable minus DisconnectReason
        group_key = detail.get("InitialContactId") or detail.get("Id") or c["Id"]
        groups.setdefault(group_key, []).append(detail)

    counts = {"requested": 0, "waiting": 0, "connected": 0,
              "succeeded": 0, "customer_failed": 0, "abandoned": 0, "retried": 0, "attempts": 0}
    for attempts in groups.values():
        cls = callback_analytics.classify_group(attempts)
        counts["requested"] += 1
        counts["attempts"] += cls["attempts"]
        if cls["attempts"] > 1:
            counts["retried"] += 1
        if cls["outcome"] == "pending":
            counts["connected" if cls["agent_connected"] else "waiting"] += 1
        else:
            counts[cls["outcome"]] += 1

    return {**counts, "truncated": truncated, "window": window}
