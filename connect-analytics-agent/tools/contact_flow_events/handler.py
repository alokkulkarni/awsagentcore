import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, parse_parameters

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
_CACHE_TTL = 300
_cache: Dict[str, Any] = {}
_LOGS_CLIENT = boto3.client("logs", config=_BOTO_CONFIG)


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["v"]
    return None



def _cache_set(key: str, value) -> None:
    _cache[key] = {"v": value, "ts": time.time()}

_LAMBDA_LOG_PREFIX  = "/aws/lambda/"
_CONNECT_LOG_PREFIX = "/aws/connect/"

# ── Log group discovery ───────────────────────────────────────────────────────

def _discover_log_groups(logs_client, extra_names: List[str]) -> List[str]:
    """Return all Connect flow + Lambda log groups plus any extras supplied."""
    cached_groups = _cache_get("log_groups")
    if cached_groups is None:
        groups = set()
        for prefix in [_CONNECT_LOG_PREFIX, _LAMBDA_LOG_PREFIX]:
            try:
                paginator = logs_client.get_paginator("describe_log_groups")
                for page in paginator.paginate(logGroupNamePrefix=prefix):
                    for lg in page.get("logGroups", []):
                        groups.add(lg["logGroupName"])
            except (ClientError, BotoCoreError) as exc:
                LOGGER.warning("Could not list log groups with prefix %s: %s", prefix, exc)
        cached_groups = list(groups)
        _cache_set("log_groups", cached_groups)
    return list(set(cached_groups) | set(extra_names))


def _flow_log_groups(logs_client, flow_name: str, extra_names: List[str]) -> List[str]:
    """Return log groups for a specific flow name (no fallback to all-Connect groups).

    Uses token-based matching because the log group name (chosen by the user when
    enabling flow logging) may differ from the flow display name —
    e.g. flow="conversation bot flow" → log group="conversationalbot".
    """
    all_groups = _discover_log_groups(logs_client, extra_names)
    fl_norm   = flow_name.lower().replace(" ", "").replace("-", "").replace("_", "")
    fl_tokens = [t for t in flow_name.lower().replace("-", " ").replace("_", " ").split() if len(t) > 3]

    matched = []
    for g in all_groups:
        gn = g.lower().replace("/aws/connect/", "").replace("-", "").replace("_", "").replace(" ", "")
        # Normalised substring match in either direction
        if fl_norm in gn or gn in fl_norm:
            matched.append(g)
            continue
        # Token overlap: any significant word from the flow name appears in the log group suffix
        if any(tok in gn for tok in fl_tokens):
            matched.append(g)
    return matched


# ── Per-contact event query (filterLogEvents) ─────────────────────────────────

def _search_log_group(
    logs_client, log_group: str, contact_id: str, start_ms: int, end_ms: int
) -> List[Dict]:
    events = []
    try:
        kwargs = {
            "logGroupName": log_group,
            "filterPattern": f'{{$.ContactId = "{contact_id}"}}',
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 200,
        }
        paginator = logs_client.get_paginator("filter_log_events")
        for page in paginator.paginate(**kwargs):
            for ev in page.get("events", []):
                try:
                    data = json.loads(ev["message"])
                    events.append({"ts": ev["timestamp"], "data": data, "log_group": log_group})
                except (json.JSONDecodeError, KeyError):
                    LOGGER.debug('Suppressed exception', exc_info=True)
    except (ClientError, BotoCoreError) as exc:
        LOGGER.debug("Could not search %s: %s", log_group, exc)
    return events


def _parse_event(raw: Dict, start_ts: int) -> Optional[Dict]:
    d = raw["data"]
    if not d.get("ContactId"):
        return None
    block_type = (
        d.get("ContactFlowModuleType")
        or d.get("BlockType")
        or d.get("Type")
        or "Unknown"
    )
    return {
        "event_id":     d.get("Identifier", str(raw["ts"])),
        "timestamp_ms": raw["ts"],
        "elapsed_ms":   raw["ts"] - start_ts,
        "block_id":     d.get("Identifier", ""),
        "block_type":   block_type,
        "block_name":   d.get("BlockName") or d.get("Name") or block_type,
        "flow_name":    d.get("ContactFlowName", ""),
        "flow_type":    d.get("ContactFlowType", ""),
        "outcome":      d.get("Results", ""),
        "parameters":   d.get("Parameters", {}),
        "results":      d.get("Results", ""),
        "duration_ms":  0,
        "source":       "flow_log",
        "log_group":    raw.get("log_group", ""),
    }


# ── Aggregate funnel via CloudWatch Logs Insights ────────────────────────────

_INSIGHTS_POLL_INTERVAL = 1.5   # seconds between status polls
_INSIGHTS_MAX_WAIT      = 55    # seconds total — stay within Lambda timeout

_CONTACT_COUNT_QUERY = """\
fields ContactId
| filter ispresent(ContactId)
| stats count_distinct(ContactId) as unique_contacts
"""

# Per-block hit counts.
# Real Connect flow logs have no "BlockName" field — the unique block identifier
# is the "Identifier" UUID and the type is in "ContactFlowModuleType".
_BLOCK_CONTACTS_QUERY = """\
fields @timestamp, ContactId, ContactFlowModuleType, Identifier
| filter ispresent(ContactId) and ispresent(Identifier) and ispresent(ContactFlowModuleType)
| stats
    count_distinct(ContactId) as unique_contacts,
    min(@timestamp) as first_seen,
    max(@timestamp) as last_seen
  by Identifier, ContactFlowModuleType
| sort first_seen asc
| limit 100
"""

# Per-contact outcome: latest() returns the ContactFlowModuleType from the
# most-recent (@timestamp) log event for each ContactId — i.e. the last block
# each contact hit.  This is a single stats aggregate, no dedup before stats.
_OUTCOME_QUERY = """\
fields ContactId, ContactFlowModuleType
| filter ispresent(ContactId) and ispresent(ContactFlowModuleType)
| stats latest(ContactFlowModuleType) as last_block by ContactId
| limit 10000
"""

# ── Outcome classification mappings ──────────────────────────────────────────

# What it means when a given block type is the LAST one a contact hits
_BLOCK_TO_OUTCOME = {
    # Completed — flow ended intentionally after full interaction
    "Disconnect":                "completed",
    "DisconnectParticipant":     "completed",
    "EndFlowModuleExecution":    "completed",
    # Escalated — transferred to a human agent / queue
    "TransferToQueue":           "escalated",
    "Transfer":                  "escalated",
    "SetContactFlow":            "escalated",
    "TransferToFlow":            "escalated",
    "AddToPlayLoop":             "escalated",
    "SetQueue":                  "escalated",   # queue was set → transfer imminent
    "SetWisdomAssistant":        "escalated",   # Wisdom is agent-side → agent reached
    # Abandoned — contact hung up during or between interaction steps.
    # Intermediate/data blocks as the last entry = contact disconnected mid-processing.
    "GetUserInput":              "abandoned",
    "GetCustomerInput":          "abandoned",
    "MessageParticipant":        "abandoned",
    "PlayPrompt":                "abandoned",
    "StoreUserInput":            "abandoned",
    "ShowView":                  "abandoned",
    "SetContactData":            "abandoned",   # data block between turns → hung up mid-flow
    "SetAttributes":             "abandoned",   # same
    "UpdateContactAttributes":   "abandoned",
    "CheckAttribute":            "abandoned",   # decision block → hung up before branch completed
    "CheckContactAttributes":    "abandoned",
    "Branch":                    "abandoned",
    "CheckHoursOfOperation":     "abandoned",
    "CheckStaffingLevel":        "abandoned",
    "Resume":                    "abandoned",   # resumed from hold then hung up
    "SetLoggingBehavior":        "abandoned",   # very start of flow → instant hang-up
    "SetVoice":                  "abandoned",
    "UpdateContactRecordingAndAnalyticsBehavior": "abandoned",
    "StartContactRecording":     "abandoned",
    "SetRecordingBehavior":      "abandoned",
    # Error — Lambda/API failure was the last thing recorded
    "InvokeExternalResource":    "error",
    "InvokeLambdaFunction":      "error",
}

# What to display on a funnel bar when contacts EXIT at this block type
# (i.e. they hit this block but didn't reach the next one in sequence)
_EXIT_INTENT = {
    "Disconnect":                "completed",
    "DisconnectParticipant":     "completed",
    "EndFlowModuleExecution":    "completed",
    "TransferToQueue":           "escalated",
    "Transfer":                  "escalated",
    "SetContactFlow":            "escalated",
    "TransferToFlow":            "escalated",
    "SetQueue":                  "escalated",
    "SetWisdomAssistant":        "escalated",
    "AddToPlayLoop":             "escalated",
    "GetUserInput":              "abandoned",
    "GetCustomerInput":          "abandoned",
    "MessageParticipant":        "abandoned",
    "PlayPrompt":                "abandoned",
    "StoreUserInput":            "abandoned",
    "ShowView":                  "abandoned",
    "SetContactData":            "abandoned",
    "SetAttributes":             "abandoned",
    "CheckAttribute":            "abandoned",
    "Branch":                    "abandoned",
    "Resume":                    "abandoned",
    "InvokeExternalResource":    "error",
    "InvokeLambdaFunction":      "error",
}


def _run_insights_query(logs_client, query: str, log_groups: List[str],
                        start_epoch: int, end_epoch: int) -> List[Dict]:
    """Run a CloudWatch Logs Insights query and wait for results."""
    try:
        resp = logs_client.start_query(
            logGroupNames=log_groups[:20],          # Insights supports up to 20 groups
            startTime=start_epoch,
            endTime=end_epoch,
            queryString=query,
        )
        query_id = resp["queryId"]
    except (ClientError, BotoCoreError) as exc:
        LOGGER.warning("Could not start Insights query: %s", exc)
        return []

    deadline = time.time() + _INSIGHTS_MAX_WAIT
    while time.time() < deadline:
        time.sleep(_INSIGHTS_POLL_INTERVAL)
        try:
            result = logs_client.get_query_results(queryId=query_id)
        except (ClientError, BotoCoreError) as exc:
            LOGGER.warning("Error polling Insights query: %s", exc)
            break
        status = result.get("status", "")
        if status in ("Complete", "Failed", "Cancelled", "Timeout"):
            if status != "Complete":
                LOGGER.warning("Insights query ended with status %s", status)
                return []
            return result.get("results", [])

    # Timed out — try to cancel
    try:
        logs_client.stop_query(queryId=query_id)
    except Exception:  # pylint: disable=broad-except
        LOGGER.debug("Suppressed stop_query exception", exc_info=True)
    return []


def _insights_row_to_dict(row: List[Dict]) -> Dict[str, str]:
    return {f["field"]: f["value"] for f in row}


def _build_funnel(insights_rows: List[List[Dict]], total_contacts: int) -> List[Dict]:
    """Convert Insights per-block rows into ordered funnel blocks.

    Real Connect flow logs use 'Identifier' (a UUID per block invocation) +
    'ContactFlowModuleType' (the block type).  There is no 'BlockName' field.
    """
    raw = []
    for row in insights_rows:
        r = _insights_row_to_dict(row)
        identifier = r.get("Identifier", "").strip()
        block_type = (
            r.get("ContactFlowModuleType")
            or r.get("BlockType")
            or r.get("Type")
            or "Unknown"
        )
        if not identifier:
            continue
        try:
            count = int(r.get("unique_contacts", r.get("block_hits", 0)))
        except (ValueError, TypeError):
            count = 0
        raw.append({
            "_identifier": identifier,
            "block_type":  block_type,
            "count":       count,
            "first_seen":  r.get("first_seen", ""),
        })

    # Sort by count descending — most-traversed blocks first, forming a proper
    # top-to-bottom funnel shape.  first_seen-based ordering was causing
    # oscillation (edge-case 2-contact blocks sorted before 393-contact main
    # path blocks) which inflated drop counts far beyond total_contacts.
    raw.sort(key=lambda b: -b["count"])

    # Build human-readable names; disambiguate duplicate types with a counter
    type_total: Dict[str, int] = {}
    for b in raw:
        type_total[b["block_type"]] = type_total.get(b["block_type"], 0) + 1

    type_seen: Dict[str, int] = {}
    result = []
    for i, b in enumerate(raw):
        bt = b["block_type"]
        if type_total[bt] > 1:
            type_seen[bt] = type_seen.get(bt, 0) + 1
            block_name = f"{bt} ({type_seen[bt]})"
        else:
            block_name = bt

        pct = round(b["count"] / total_contacts * 100, 1) if total_contacts else 0.0
        next_count = raw[i + 1]["count"] if i + 1 < len(raw) else b["count"]
        drop = max(0, b["count"] - next_count)
        drop_pct = round(drop / b["count"] * 100, 1) if b["count"] else 0.0
        result.append({
            "sequence":    i + 1,
            "block_name":  block_name,
            "block_type":  bt,
            "identifier":  b["_identifier"],
            "count":       b["count"],
            "pct":         pct,
            "drop_count":  drop,
            "drop_pct":    drop_pct,
            # exit_intent: what likely happened to contacts that left after this block
            "exit_intent": _EXIT_INTENT.get(bt, "abandoned") if drop > 0 else None,
        })
    return result


def _build_outcomes_summary(outcome_rows: List[List[Dict]]) -> Dict[str, int]:
    """Classify each contact by the last flow block they hit into an outcome bucket.

    Uses the result of _OUTCOME_QUERY which runs latest(ContactFlowModuleType)
    per ContactId — giving one row per contact with their last block type.
    Outcomes therefore sum to exactly the number of unique contacts in the flow.
    """
    summary: Dict[str, int] = {
        "completed": 0,
        "escalated": 0,
        "abandoned": 0,
        "error":     0,
        "unknown":   0,
    }
    for row in outcome_rows:
        r = _insights_row_to_dict(row)
        last_block = r.get("last_block", "")
        outcome = _BLOCK_TO_OUTCOME.get(last_block, "unknown")
        summary[outcome] = summary.get(outcome, 0) + 1
    return summary


# ── Lambda entry point ────────────────────────────────────────────────────────

def lambda_handler(event, _context):
    try:
        LOGGER.info(json.dumps({"event": "lambda_invoked", "function": event.get("function", "unknown")}))
        params      = parse_parameters(event.get("parameters", []))
        query_type  = params.get("query_type", "contact_events")

        extra_groups = [g.strip() for g in params.get("log_groups", "").split(",") if g.strip()]

        # ── Mode 1: per-contact event timeline ──────────────────────────────
        if query_type == "contact_events":
            contact_id = params.get("contact_id")
            if not contact_id:
                raise ValueError("contact_id is required for query_type=contact_events")

            end_ms   = int(time.time() * 1000)
            start_ms = end_ms - 7 * 24 * 3600 * 1000

            all_groups  = _discover_log_groups(_LOGS_CLIENT, extra_groups)
            raw_events: List[Dict] = []
            for lg in all_groups:
                raw_events.extend(_search_log_group(_LOGS_CLIENT, lg, contact_id, start_ms, end_ms))

            raw_events.sort(key=lambda x: x["ts"])
            start_ts = raw_events[0]["ts"] if raw_events else end_ms

            events: List[Dict] = []
            for r in raw_events:
                parsed = _parse_event(r, start_ts)
                if parsed:
                    events.append(parsed)

            for i, evt in enumerate(events):
                if i + 1 < len(events):
                    evt["duration_ms"] = events[i + 1]["timestamp_ms"] - evt["timestamp_ms"]

            flows_traversed = list(dict.fromkeys(
                e["flow_name"] for e in events if e.get("flow_name")
            ))

            return build_response(event, {
                "contact_id":       contact_id,
                "events":           events,
                "flows_traversed":  flows_traversed,
                "event_count":      len(events),
                "start_time_ms":    start_ts if events else None,
                "end_time_ms":      raw_events[-1]["ts"] if raw_events else None,
                "total_duration_ms": (
                    raw_events[-1]["ts"] - start_ts if len(raw_events) > 1 else 0
                ),
            })

        # ── Mode 2: aggregate funnel across all contacts ─────────────────────
        if query_type == "flow_funnel":
            flow_name = params.get("flow_name", "")
            if not flow_name:
                raise ValueError("flow_name is required for query_type=flow_funnel")
            days = max(1, min(90, int(params.get("days", 30))))

            end_epoch   = int(time.time())
            start_epoch = end_epoch - days * 86400

            log_groups = _flow_log_groups(_LOGS_CLIENT, flow_name, extra_groups)
            if not log_groups:
                return build_response(event, {
                    "flow_name": flow_name, "period_days": days,
                    "total_contacts": 0, "blocks": [],
                    "outcomes_summary": {"completed": 0, "escalated": 0, "abandoned": 0, "error": 0, "unknown": 0},
                    "warning": "No matching log groups found",
                })

            # Run all 3 queries in parallel
            import concurrent.futures  # pylint: disable=import-outside-toplevel
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                fut_count   = pool.submit(_run_insights_query, _LOGS_CLIENT, _CONTACT_COUNT_QUERY,  log_groups, start_epoch, end_epoch)
                fut_blocks  = pool.submit(_run_insights_query, _LOGS_CLIENT, _BLOCK_CONTACTS_QUERY, log_groups, start_epoch, end_epoch)
                fut_outcome = pool.submit(_run_insights_query, _LOGS_CLIENT, _OUTCOME_QUERY,        log_groups, start_epoch, end_epoch)
                count_rows   = fut_count.result()
                block_rows   = fut_blocks.result()
                outcome_rows = fut_outcome.result()

            total_contacts = 0
            if count_rows:
                r = _insights_row_to_dict(count_rows[0])
                try:
                    total_contacts = int(r.get("unique_contacts", 0))
                except (ValueError, TypeError):
                    total_contacts = 0

            funnel_blocks    = _build_funnel(block_rows, total_contacts or 1)
            # outcomes_summary uses the per-contact latest-block query so counts
            # sum to the number of unique contacts, not inflated drop totals
            outcomes_summary = _build_outcomes_summary(outcome_rows)

            return build_response(event, {
                "flow_name":           flow_name,
                "period_days":         days,
                "total_contacts":      total_contacts,
                "blocks":              funnel_blocks,
                "outcomes_summary":    outcomes_summary,
                "log_groups_searched": len(log_groups),
            })

        raise ValueError(f"Unknown query_type '{query_type}'. Use 'contact_events' or 'flow_funnel'.")

    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("AWS error in contact_flow_events")
        return build_error_response(event, str(exc), status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error")
        return build_error_response(event, str(exc), status_code=500)
