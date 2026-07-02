"""
Shared helpers for exhaustive date-range contact enumeration.

Used by any feature that needs to scan every Amazon Connect contact in a
time window (theme_scan.py, disconnect_reasons.py) — factored out so both
scans share one paginated search_contacts implementation instead of
duplicating it.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional


def parse_dt(value: str) -> datetime:
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def enumerate_contacts(
    connect,
    instance_id: str,
    start_iso: str,
    end_iso: str,
    on_progress: Optional[Callable[[int], Awaitable[None]]] = None,
) -> List[Dict[str, Any]]:
    """
    Exhaustively page through search_contacts (direct boto3 — avoids the
    search_contacts tool's per-contact describe_contact/get_contact_attributes
    enrichment, which is unnecessary overhead for callers that only need
    contact_id/channel to drive their own per-contact fetch).

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
