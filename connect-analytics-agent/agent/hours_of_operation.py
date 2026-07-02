"""
Amazon Connect Hours of Operation resolution.

Maps a queue to its actual configured business hours for "today" (evaluated
in the Hours of Operation's own configured timezone), so day-to-date
features can use each queue's real open/close window instead of guessing a
fixed midnight-to-midnight or fixed business-hours assumption. Different
queues can have different Hours of Operation, so this is resolved per queue.

Results are cached for the life of the process — Hours of Operation config
changes rarely, and re-fetching on every request would multiply API calls
across every queue on every poll.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)

_DAY_NAMES = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

_queue_hoo_cache: Dict[str, Optional[str]] = {}   # queue_id -> hours_of_operation_id (or None if lookup failed)
_hoo_config_cache: Dict[str, Optional[Dict[str, Any]]] = {}  # hoo_id -> {"timezone": str, "config": [...]}


def _get_queue_hoo_id(connect, instance_id: str, queue_id: str) -> Optional[str]:
    if queue_id in _queue_hoo_cache:
        return _queue_hoo_cache[queue_id]
    try:
        resp = connect.describe_queue(InstanceId=instance_id, QueueId=queue_id)
        hoo_id = resp.get("Queue", {}).get("HoursOfOperationId")
        _queue_hoo_cache[queue_id] = hoo_id
        return hoo_id
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("describe_queue failed for %s: %s", queue_id, exc)
        _queue_hoo_cache[queue_id] = None
        return None


def _get_hoo_config(connect, instance_id: str, hoo_id: str) -> Optional[Dict[str, Any]]:
    if hoo_id in _hoo_config_cache:
        return _hoo_config_cache[hoo_id]
    try:
        resp = connect.describe_hours_of_operation(InstanceId=instance_id, HoursOfOperationId=hoo_id)
        hoo = resp.get("HoursOfOperation", {})
        cfg = {"timezone": hoo.get("TimeZone") or "UTC", "config": hoo.get("Config") or []}
        _hoo_config_cache[hoo_id] = cfg
        return cfg
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("describe_hours_of_operation failed for %s: %s", hoo_id, exc)
        _hoo_config_cache[hoo_id] = None
        return None


def get_today_window(connect, instance_id: str, queue_id: str) -> Optional[Tuple[datetime, datetime]]:
    """
    Returns (open_utc, close_utc) for this queue's Hours of Operation "today",
    evaluated in the Hours of Operation's own configured timezone.

    Returns None when: the queue has no Hours of Operation configured, the
    lookup fails, or the queue is simply closed today (no Config entry for
    today's day-of-week — e.g. weekends for a Mon-Fri-only queue).
    """
    hoo_id = _get_queue_hoo_id(connect, instance_id, queue_id)
    if not hoo_id:
        return None
    cfg = _get_hoo_config(connect, instance_id, hoo_id)
    if not cfg:
        return None
    try:
        tz = ZoneInfo(cfg["timezone"])
    except Exception:  # pylint: disable=broad-except
        tz = timezone.utc

    now_local = datetime.now(tz)
    today_name = _DAY_NAMES[now_local.weekday()]
    entry = next((c for c in cfg["config"] if str(c.get("Day", "")).upper() == today_name), None)
    if not entry:
        return None  # closed today

    start = entry.get("StartTime", {})
    end = entry.get("EndTime", {})
    open_local = now_local.replace(
        hour=int(start.get("Hours", 0)), minute=int(start.get("Minutes", 0)), second=0, microsecond=0,
    )
    close_local = now_local.replace(
        hour=int(end.get("Hours", 23)), minute=int(end.get("Minutes", 59)), second=0, microsecond=0,
    )
    if close_local <= open_local:
        close_local += timedelta(days=1)  # overnight hours, e.g. 22:00-06:00

    return open_local.astimezone(timezone.utc), close_local.astimezone(timezone.utc)
