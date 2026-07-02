"""
Shared helpers for exhaustive date-range contact enumeration.

Used by any feature that needs to scan every Amazon Connect contact in a
time window (theme_scan.py, disconnect_reasons.py) — factored out so both
scans share one paginated search_contacts implementation instead of
duplicating it.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional


def parse_dt(value: str) -> datetime:
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# search_contacts rejects INITIATION_TIMESTAMP ranges over 1345 hours (~56
# days) — callers scanning contact records clamp their window to this.
SEARCH_CONTACTS_MAX_DAYS = 55


def clamp_search_window(start_iso: str, end_iso: str, max_days: int = SEARCH_CONTACTS_MAX_DAYS) -> Dict[str, Any]:
    """Clamp a scan window's start so the range never exceeds search_contacts' cap."""
    start_dt = parse_dt(start_iso)
    end_dt = parse_dt(end_iso)
    max_start = end_dt - timedelta(days=max_days)
    if start_dt < max_start:
        return {"start": max_start.isoformat(), "end": end_dt.isoformat(),
                "requested_start": start_dt.isoformat(), "clamped": True}
    return {"start": start_dt.isoformat(), "end": end_dt.isoformat(),
            "requested_start": start_dt.isoformat(), "clamped": False}


async def enumerate_contact_summaries(
    connect,
    instance_id: str,
    start_iso: str,
    end_iso: str,
    on_progress: Optional[Callable[[int], Awaitable[None]]] = None,
    search_criteria: Optional[Dict[str, Any]] = None,
    max_pages: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Page through search_contacts returning the RAW contact summaries — these
    include InitiationTimestamp, DisconnectTimestamp, QueueInfo.EnqueueTimestamp
    and AgentInfo.ConnectedToAgentTimestamp, which is enough for wait-time and
    outcome computations without a per-contact describe_contact.

    max_pages bounds the scan on very busy instances (100 contacts per page);
    callers should surface a truncation note when the cap is hit.
    """
    summaries: List[Dict[str, Any]] = []
    next_token = None
    pages = 0
    start_dt = parse_dt(start_iso)
    end_dt = parse_dt(end_iso)
    while True:
        kwargs: Dict[str, Any] = {
            "InstanceId": instance_id,
            "TimeRange": {"Type": "INITIATION_TIMESTAMP", "StartTime": start_dt, "EndTime": end_dt},
            "MaxResults": 100,
        }
        if search_criteria:
            kwargs["SearchCriteria"] = search_criteria
        if next_token:
            kwargs["NextToken"] = next_token
        # Blocking network call — run off the event loop so concurrent
        # requests (other screens' polling, SSE streams) aren't stalled.
        resp = await asyncio.to_thread(connect.search_contacts, **kwargs)
        summaries.extend(resp.get("Contacts", []))
        next_token = resp.get("NextToken")
        pages += 1
        if on_progress:
            await on_progress(len(summaries))
        if not next_token or (max_pages and pages >= max_pages):
            break
        await asyncio.sleep(0)
    return summaries


async def enumerate_contacts(
    connect,
    instance_id: str,
    start_iso: str,
    end_iso: str,
    on_progress: Optional[Callable[[int], Awaitable[None]]] = None,
    search_criteria: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Exhaustively page through search_contacts (direct boto3 — avoids the
    search_contacts tool's per-contact describe_contact/get_contact_attributes
    enrichment, which is unnecessary overhead for callers that only need
    contact_id/channel to drive their own per-contact fetch).

    search_criteria, when given, is passed straight through as the API's
    SearchCriteria (e.g. {"InitiationMethods": ["CALLBACK"]} to enumerate
    only callback contacts).

    Calls on_progress(running_count) after each page so callers can emit
    their own SSE progress events without this module knowing about SSE.
    """
    contacts: List[Dict[str, Any]] = []
    next_token = None
    start_dt = parse_dt(start_iso)
    end_dt = parse_dt(end_iso)
    while True:
        kwargs: Dict[str, Any] = {
            "InstanceId": instance_id,
            "TimeRange": {"Type": "INITIATION_TIMESTAMP", "StartTime": start_dt, "EndTime": end_dt},
            "MaxResults": 100,
        }
        if search_criteria:
            kwargs["SearchCriteria"] = search_criteria
        if next_token:
            kwargs["NextToken"] = next_token
        # search_contacts is a blocking network call — run it off the event loop
        # so it doesn't stall every other concurrent request the app is serving
        # (background polling from other screens, the SSE stream itself, etc.)
        # while a page is in flight.
        resp = await asyncio.to_thread(connect.search_contacts, **kwargs)
        for c in resp.get("Contacts", []):
            cid = c.get("Id")
            if cid:
                contacts.append({"contact_id": cid, "channel": c.get("Channel", "VOICE")})
        next_token = resp.get("NextToken")
        if on_progress:
            await on_progress(len(contacts))
        if not next_token:
            break
        await asyncio.sleep(0)
    return contacts
