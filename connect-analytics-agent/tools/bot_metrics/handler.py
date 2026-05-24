"""bot_metrics Lambda tool — uses real Lex V2 analytics APIs + Connect flow metrics.

Architecture detected for this instance:
  - Lex V2 bot with AmazonQinConnect intent → Amazon Q in Connect (Nova Sonic / LLM)
  - AmazonQinConnect bots: all utterances handled by LLM; "Dropped" sessions = escalations

Data sources:
  1. Bot inventory      — connect.list_bots(V2/V1) + lexv2-models.describe_bot
  2. Session metrics    — lexv2-models.list_session_metrics (Count/Success/Failure/Dropped/Duration/Turns)
  3. Intent metrics     — lexv2-models.list_intent_metrics grouped by IntentName
  4. Utterance metrics  — lexv2-models.list_utterance_metrics (Detected/Missed/Count)
  5. Missed utterances  — lexv2-models.list_utterance_analytics_data (filtered Missed, last N)
  6. Escalations        — lexv2-models.list_session_analytics_data (ConversationEndState=Dropped)
  7. Flow metrics       — connect.get_metric_data_v2 grouped by FLOW_TYPE
  8. CloudWatch Lex     — AWS/Lex namespace (RuntimeRequestCount, latency, throttles)
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from shared.connect_utils import (
    build_error_response,
    build_response,
    format_duration,
    get_instance_id,
    parse_datetime,
    parse_parameters,
)
from shared.scan_resources import get_account_id as scan_get_account_id, get_instance_arn, get_instance_region, get_queue_ids

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
_CACHE_TTL = 300
_cache: Dict[str, Any] = {}
_CONNECT_CLIENT = boto3.client("connect", config=_BOTO_CONFIG)
_CW_CLIENT = boto3.client("cloudwatch", config=_BOTO_CONFIG)
_lex_clients: Dict[str, Any] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["v"]
    return None



def _cache_set(key: str, value) -> None:
    _cache[key] = {"v": value, "ts": time.time()}

# ── constants ─────────────────────────────────────────────────────────────────

# Valid metric names for Lex V2 analytics APIs
SESSION_METRIC_NAMES = ["Count", "Success", "Failure", "Dropped", "Duration", "TurnsPerConversation"]
# Concurrency is excluded — it only supports Max/Sum, not Avg, and less useful here
INTENT_METRIC_NAMES  = ["Count", "Success", "Failure", "Dropped", "Switched"]
UTTERANCE_METRIC_NAMES = ["Count", "Detected", "Missed"]

# Connect flow metrics (valid for GetMetricDataV2 + FLOW_TYPE grouping)
FLOW_METRICS = [
    {"Name": "FLOWS_OUTCOME"},
    {"Name": "FLOWS_STARTED"},
    {"Name": "PERCENT_FLOWS_OUTCOME"},
    {"Name": "AVG_FLOW_TIME"},
    {"Name": "MAX_FLOW_TIME"},
]

# CloudWatch Lex namespace
CW_LEX_METRICS_V2 = [
    "RuntimeRequestCount",
    "RuntimeSuccessfulRequestLatency",
    "RuntimeThrottledEvents",
    "MissedUtteranceCount",
    "DetectedUtteranceCount",
]
CW_LEX_METRICS_V1 = [
    "RuntimeRequestCount",
    "RuntimeSuccessfulRequestLatency",
    "MissedUtteranceCount",
    "DetectedUtteranceCount",
]

AMAZON_Q_INTENT = "AmazonQinConnect"


# ── helpers ───────────────────────────────────────────────────────────────────

def _resource_arn(instance_id: str, region: str, account_id: str) -> str:
    return get_instance_arn(instance_id)


def _get_account_id() -> str:
    cached_account_id = _cache_get("account_id")
    if cached_account_id is not None:
        return cached_account_id
    account_id = scan_get_account_id()
    resolved_account_id = account_id if account_id else "000000000000"
    _cache_set("account_id", resolved_account_id)
    return resolved_account_id


def _parse_lex_v2_alias_arn(alias_arn: str) -> Dict[str, str]:
    """Parse arn:aws:lex:{region}:{account}:bot-alias/{botId}/{aliasId}."""
    result = {"bot_id": "", "alias_id": "", "region": ""}
    if not alias_arn:
        return result
    try:
        parts = alias_arn.split(":")
        result["region"] = parts[3] if len(parts) > 3 else ""
        resource = parts[5] if len(parts) > 5 else ""
        rp = resource.split("/")
        result["bot_id"]   = rp[1] if len(rp) > 1 else ""
        result["alias_id"] = rp[2] if len(rp) > 2 else ""
    except Exception:  # pylint: disable=broad-except
        LOGGER.debug("Suppressed exception in alias path resolution", exc_info=True)
    return result


def _lex_client(region: str):
    lex_region = region or _REGION
    if lex_region not in _lex_clients:
        _lex_clients[lex_region] = boto3.client(
            "lexv2-models",
            region_name=lex_region,
            config=_BOTO_CONFIG,
        )
    return _lex_clients[lex_region]


def _describe_bot(bot_id: str, region: str) -> Dict[str, str]:
    """Return {bot_id, bot_name, bot_status, description, has_q_in_connect}."""
    info: Dict[str, str] = {"bot_id": bot_id, "bot_name": bot_id,
                            "bot_status": "Unknown", "description": ""}
    try:
        resp = _lex_client(region).describe_bot(botId=bot_id)
        info["bot_name"]    = resp.get("botName", bot_id)
        info["bot_status"]  = resp.get("botStatus", "Unknown")
        info["description"] = resp.get("description", "")
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.debug("describe_bot(%s) failed: %s", bot_id, exc)
    return info


def _describe_bot_alias(bot_id: str, alias_id: str, region: str) -> str:
    """Return alias name."""
    try:
        resp = _lex_client(region).describe_bot_alias(botId=bot_id, botAliasId=alias_id)
        return resp.get("botAliasName", alias_id)
    except Exception:  # pylint: disable=broad-except
        LOGGER.debug("Suppressed exception in alias path resolution", exc_info=True)
        return alias_id


def _bot_intents(bot_id: str, bot_version: str, locale_id: str, region: str) -> List[Dict]:
    """List intents for a bot/version/locale. Detect AmazonQinConnect."""
    intents = []
    try:
        lex = _lex_client(region)
        # list_intents is NOT paginatable via get_paginator — use maxResults + nextToken loop
        kwargs = {"botId": bot_id, "botVersion": bot_version, "localeId": locale_id, "maxResults": 100}
        while True:
            resp = lex.list_intents(**kwargs)
            for i in resp.get("intentSummaries", []):
                intents.append({
                    "intent_id":   i.get("intentId", ""),
                    "intent_name": i.get("intentName", ""),
                    "is_q_intent": i.get("intentName", "") == AMAZON_Q_INTENT,
                    "is_fallback": i.get("intentName", "") == "FallbackIntent",
                })
            next_token = resp.get("nextToken")
            if not next_token:
                break
            kwargs["nextToken"] = next_token
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_intents(%s) failed: %s", bot_id, exc)
    return intents


# ── bot inventory ─────────────────────────────────────────────────────────────

def _list_lex_v2_bots(connect_client, instance_id: str) -> List[Dict[str, Any]]:
    """List Lex V2 bots, resolving names via describe_bot.
    Deduplicate by bot_id (same bot can appear with multiple aliases).
    """
    seen_bot_ids: Dict[str, Dict] = {}
    aliases_by_bot: Dict[str, List] = {}

    try:
        paginator = connect_client.get_paginator("list_bots")
        for page in paginator.paginate(InstanceId=instance_id, LexVersion="V2"):
            for entry in page.get("LexBots", []):
                lex_bot = entry.get("LexV2Bot", entry.get("LexBot", {}))
                alias_arn = lex_bot.get("AliasArn", "")
                parsed    = _parse_lex_v2_alias_arn(alias_arn)
                bot_id    = parsed["bot_id"]
                alias_id  = parsed["alias_id"]
                lex_region = parsed["region"]

                if not bot_id:
                    continue

                if bot_id not in seen_bot_ids:
                    bot_info = _describe_bot(bot_id, lex_region)
                    seen_bot_ids[bot_id] = {
                        "bot_type":    "LexV2",
                        "bot_id":      bot_id,
                        "bot_name":    bot_info["bot_name"],
                        "bot_status":  bot_info["bot_status"],
                        "description": bot_info["description"],
                        "region":      lex_region,
                        "aliases":     [],
                        "locales":     [],
                        "intents":     [],
                        "has_q_in_connect": False,
                    }
                    aliases_by_bot[bot_id] = []

                alias_name = _describe_bot_alias(bot_id, alias_id, lex_region)
                is_prod = alias_id not in ("TSTALIASID",) and "test" not in alias_name.lower()
                aliases_by_bot[bot_id].append({
                    "alias_id":   alias_id,
                    "alias_name": alias_name,
                    "alias_arn":  alias_arn,
                    "is_prod":    is_prod,
                })
                seen_bot_ids[bot_id]["aliases"] = aliases_by_bot[bot_id]

    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_bots(V2) failed: %s", exc)
        return []

    # Enrich with locales + intents for each unique bot
    bots = list(seen_bot_ids.values())
    for bot in bots:
        bid = bot["bot_id"]
        reg = bot["region"]
        try:
            lex = _lex_client(reg)
            locale_pages = lex.get_paginator("list_bot_locales").paginate(
                botId=bid, botVersion="DRAFT"
            )
            locales = []
            for lp in locale_pages:
                for loc in lp.get("botLocaleSummaries", []):
                    locales.append({
                        "locale_id":   loc.get("localeId", ""),
                        "locale_name": loc.get("localeName", ""),
                        "status":      loc.get("botLocaleStatus", ""),
                    })
            bot["locales"] = locales
            # Get intents for first locale
            if locales:
                intents = _bot_intents(bid, "DRAFT", locales[0]["locale_id"], reg)
                bot["intents"] = intents
                bot["has_q_in_connect"] = any(i["is_q_intent"] for i in intents)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.debug("enrich_bot(%s) failed: %s", bid, exc)

    return bots


def _list_lex_v1_bots(connect_client, instance_id: str) -> List[Dict[str, Any]]:
    """List Lex V1 bots."""
    bots: List[Dict[str, Any]] = []
    try:
        paginator = connect_client.get_paginator("list_lex_bots")
        for page in paginator.paginate(InstanceId=instance_id):
            for entry in page.get("LexBots", []):
                lex_bot = entry.get("LexBot", entry)
                bots.append({
                    "bot_type":        "LexV1",
                    "bot_name":        lex_bot.get("Name", ""),
                    "bot_alias":       lex_bot.get("BotAlias", lex_bot.get("Alias", "$LATEST")),
                    "lex_region":      lex_bot.get("LexRegion", ""),
                    "has_q_in_connect": False,
                })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_lex_bots(V1) failed: %s", exc)
    return bots


# ── Lex V2 analytics ─────────────────────────────────────────────────────────

def _session_metrics(bot_id: str, alias_id: str, locale_id: str,
                     start_dt: datetime, end_dt: datetime, region: str) -> Dict[str, Any]:
    """list_session_metrics — overall conversation health for one bot alias."""
    raw: Dict[str, float] = {}
    try:
        lex = _lex_client(region)
        resp = lex.list_session_metrics(
            botId=bot_id,
            startDateTime=start_dt,
            endDateTime=end_dt,
            metrics=[{"name": n, "statistic": "Avg" if n in ("Duration", "TurnsPerConversation", "Concurrency") else "Sum"}
                     for n in SESSION_METRIC_NAMES],
        )
        for row in resp.get("results", []):
            for m in row.get("metricsResults", []):
                raw[m["name"]] = m.get("value", 0.0)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_session_metrics(%s) failed: %s", bot_id, exc)

    escalations = int(raw.get("Dropped", 0))
    total_sessions = int(raw.get("Count", 0))
    return {
        "total_sessions":     total_sessions,
        "successful":         int(raw.get("Success", 0)),
        "failed":             int(raw.get("Failure", 0)),
        "escalated":          escalations,
        "escalation_rate_pct": round(escalations / total_sessions * 100, 1) if total_sessions else 0,
        "avg_duration_sec":   round(raw.get("Duration", 0) / 1000, 1),   # Lex returns ms
        "avg_duration_fmt":   format_duration(int(raw.get("Duration", 0) / 1000)),
        "avg_turns":          round(raw.get("TurnsPerConversation", 0), 1),
    }


def _intent_metrics(bot_id: str, start_dt: datetime, end_dt: datetime,
                    region: str) -> List[Dict[str, Any]]:
    """list_intent_metrics grouped by IntentName."""
    results = []
    try:
        lex = _lex_client(region)
        resp = lex.list_intent_metrics(
            botId=bot_id,
            startDateTime=start_dt,
            endDateTime=end_dt,
            metrics=[{"name": n, "statistic": "Sum"} for n in INTENT_METRIC_NAMES],
            groupBy=[{"name": "IntentName"}],
        )
        for row in resp.get("results", []):
            intent_name = ""
            for g in row.get("groupByKeys", []):
                if g.get("name") == "IntentName":
                    intent_name = g.get("value", "")
            m: Dict[str, float] = {mr["name"]: mr.get("value", 0.0)
                                    for mr in row.get("metricsResults", [])}
            total = int(m.get("Count", 0))
            success = int(m.get("Success", 0))
            results.append({
                "intent_name":   intent_name,
                "is_q_intent":   intent_name == AMAZON_Q_INTENT,
                "is_fallback":   intent_name == "FallbackIntent",
                "total":         total,
                "successful":    success,
                "failed":        int(m.get("Failure", 0)),
                "dropped":       int(m.get("Dropped", 0)),
                "switched":      int(m.get("Switched", 0)),
                "success_rate_pct": round(success / total * 100, 1) if total else 0,
            })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_intent_metrics(%s) failed: %s", bot_id, exc)
    return results


def _utterance_metrics(bot_id: str, start_dt: datetime, end_dt: datetime,
                       region: str) -> Dict[str, Any]:
    """list_utterance_metrics — detected vs missed."""
    raw: Dict[str, float] = {}
    try:
        lex = _lex_client(region)
        resp = lex.list_utterance_metrics(
            botId=bot_id,
            startDateTime=start_dt,
            endDateTime=end_dt,
            metrics=[{"name": n, "statistic": "Sum"} for n in UTTERANCE_METRIC_NAMES],
        )
        for row in resp.get("results", []):
            for m in row.get("metricsResults", []):
                raw[m["name"]] = m.get("value", 0.0)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_utterance_metrics(%s) failed: %s", bot_id, exc)

    total    = int(raw.get("Count", 0))
    detected = int(raw.get("Detected", 0))
    missed   = int(raw.get("Missed", 0))
    return {
        "total":        total,
        "detected":     detected,
        "missed":       missed,
        "detection_rate_pct": round(detected / total * 100, 1) if total else 0,
        "missed_rate_pct":    round(missed   / total * 100, 1) if total else 0,
    }


def _missed_utterance_samples(bot_id: str, alias_id: str, start_dt: datetime,
                               end_dt: datetime, region: str, max_items: int = 20) -> List[Dict]:
    """list_utterance_analytics_data filtered to Missed — sample of recent missed utterances."""
    samples = []
    try:
        lex = _lex_client(region)
        # UtteranceState values: Hit, Missed
        resp = lex.list_utterance_analytics_data(
            botId=bot_id,
            startDateTime=start_dt,
            endDateTime=end_dt,
            filters=[{"name": "UtteranceState", "operator": "EQ", "values": ["Missed"]}],
            maxResults=min(max_items, 100),
        )
        for u in resp.get("utterances", [])[:max_items]:
            responses = [r.get("content", "") for r in u.get("botResponses", []) if r.get("content")]
            samples.append({
                "utterance":    u.get("utterance", ""),
                "understood":   u.get("utteranceUnderstood", False),
                "channel":      u.get("channel", ""),
                "mode":         u.get("mode", ""),
                "intent":       u.get("associatedIntentName", ""),
                "timestamp":    u.get("utteranceTimestamp", ""),
                "bot_response": responses[0] if responses else "",
                "session_id":   u.get("sessionId", ""),
            })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_utterance_analytics_data(%s) failed: %s", bot_id, exc)
    return samples


def _escalation_sessions(bot_id: str, alias_id: str, start_dt: datetime,
                          end_dt: datetime, region: str, max_items: int = 50) -> Dict[str, Any]:
    """list_session_analytics_data filtered to Dropped (= escalated to human).

    For AmazonQinConnect bots, Dropped = Q in Connect handed off to human agent.
    """
    sessions = []
    try:
        lex = _lex_client(region)
        resp = lex.list_session_analytics_data(
            botId=bot_id,
            startDateTime=start_dt,
            endDateTime=end_dt,
            filters=[{"name": "ConversationEndState",
                       "operator": "EQ", "values": ["Dropped"]}],
            maxResults=min(max_items, 100),
        )
        for s in resp.get("sessions", [])[:max_items]:
            sessions.append({
                "session_id":   s.get("sessionId", ""),
                "channel":      s.get("channel", ""),
                "mode":         s.get("mode", ""),
                "start_time":   str(s.get("sessionStartDateTime", "")),
                "last_updated": str(s.get("sessionLastUpdatedDateTime", "")),
                "end_state":    s.get("sessionEndState", "Dropped"),
                "turns":        s.get("numberOfTurns", 0),
                "locale":       s.get("localeId", ""),
            })
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("list_session_analytics_data(%s) failed: %s", bot_id, exc)

    total_escalated = len(sessions)
    return {"total_escalated": total_escalated, "sessions": sessions}


# ── Connect flow metrics ──────────────────────────────────────────────────────

def _flow_metrics_v2(connect_client, instance_id: str, start_dt: datetime,
                     end_dt: datetime, interval: str, region: str,
                     account_id: str) -> List[Dict[str, Any]]:
    """GetMetricDataV2 for contact-handling metrics grouped by QUEUE.

    FLOWS_* metrics are unstable across instance types; use standard contact
    metrics (CONTACTS_HANDLED, CONTACTS_ABANDONED, AVG_HANDLE_TIME) grouped by
    QUEUE with a CHANNEL filter — the most reliably supported combination.
    """
    valid_metrics = [
        {"Name": "CONTACTS_HANDLED"},
        {"Name": "CONTACTS_ABANDONED"},
        {"Name": "AVG_HANDLE_TIME"},
        {"Name": "AVG_QUEUE_ANSWER_TIME"},
        {"Name": "CONTACTS_QUEUED"},
    ]

    # Use scan data for queue IDs — falls back to live API automatically
    queue_ids = get_queue_ids(instance_id, connect_client)

    if not queue_ids:
        LOGGER.warning("No queues found — skipping flow metrics")
        return []

    kwargs: Dict[str, Any] = {
        "ResourceArn": _resource_arn(instance_id, region, account_id),
        "StartTime":   start_dt,
        "EndTime":     end_dt,
        "Metrics":     valid_metrics,
        # QUEUE filter avoids the "must include non-CHANNEL filter" restriction
        "Filters":     [{"FilterKey": "QUEUE", "FilterValues": queue_ids[:100]}],
        "Groupings":   ["QUEUE"],
        "MaxResults":  100,
    }
    if interval != "TOTAL":
        kwargs["Interval"] = {"IntervalPeriod": interval}

    results: List[Dict[str, Any]] = []
    try:
        call_kwargs = dict(kwargs)
        while True:
            resp = connect_client.get_metric_data_v2(**call_kwargs)
            for row in resp.get("MetricResults", []):
                dims = {d["Name"]: d["Value"] for d in row.get("Dimensions", [])}
                entry: Dict[str, Any] = {
                    "flow_type": "QUEUE",
                    "flow_name": dims.get("QUEUE", dims.get("QUEUE_ID", "Unknown")),
                    "metrics":   {},
                }
                for col in row.get("Collections", []):
                    name = col.get("Metric", {}).get("Name", "")
                    val  = col.get("Value") or 0
                    entry["metrics"][name] = (
                        {"raw_seconds": val, "formatted": format_duration(int(val))}
                        if name.startswith("AVG_") and val
                        else val
                    )
                results.append(entry)
            next_token = resp.get("NextToken")
            if not next_token:
                break
            call_kwargs["NextToken"] = next_token
        LOGGER.info("GetMetricDataV2(QUEUE) returned %d rows", len(results))
    except ClientError as exc:
        LOGGER.warning("GetMetricDataV2(QUEUE) %s: %s", exc.response["Error"]["Code"], exc)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.warning("GetMetricDataV2(QUEUE) error: %s", exc)
    return results


# ── CloudWatch Lex metrics ────────────────────────────────────────────────────

def _lex_cloudwatch_metrics(bots: List[Dict[str, Any]], start_dt: datetime,
                             end_dt: datetime, region: str) -> List[Dict[str, Any]]:
    """Query CloudWatch AWS/Lex.

    V2: dimensions BotId + BotAliasId (no LocaleId needed for aggregate view)
    V1: dimensions BotName + BotAlias
    """
    if not bots:
        return []

    queries: List[Dict] = []
    meta: List[Dict[str, str]] = []

    for b in bots:
        if b["bot_type"] == "LexV2":
            prod_alias = next((a for a in b.get("aliases", []) if a.get("is_prod")),
                              b.get("aliases", [{}])[0] if b.get("aliases") else {})
            alias_id = prod_alias.get("alias_id", "")
            if not b.get("bot_id") or not alias_id:
                continue
            base_dims = [
                {"Name": "BotId",      "Value": b["bot_id"]},
                {"Name": "BotAliasId", "Value": alias_id},
            ]
            cw_metrics = CW_LEX_METRICS_V2
            label = b.get("bot_name", b["bot_id"])
        else:
            if not b.get("bot_name"):
                continue
            base_dims = [
                {"Name": "BotName",  "Value": b["bot_name"]},
                {"Name": "BotAlias", "Value": b.get("bot_alias", "$LATEST")},
            ]
            cw_metrics = CW_LEX_METRICS_V1
            label = b.get("bot_name", "")

        for metric_name in cw_metrics:
            stat = "Average" if "Latency" in metric_name else "Sum"
            qid  = f"m{len(queries)}"
            queries.append({
                "Id": qid,
                "MetricStat": {
                    "Metric": {
                        "Namespace":  "AWS/Lex",
                        "MetricName": metric_name,
                        "Dimensions": base_dims,
                    },
                    "Period": 86400,
                    "Stat":   stat,
                },
                "ReturnData": True,
            })
            meta.append({"bot_name": label, "metric_name": metric_name})

    if not queries:
        return []

    cw_results: List[Any] = []
    for i in range(0, len(queries), 500):
        try:
            resp = _CW_CLIENT.get_metric_data(
                MetricDataQueries=queries[i:i + 500],
                StartTime=start_dt,
                EndTime=end_dt,
            )
            cw_results.extend(resp.get("MetricDataResults", []))
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("CW get_metric_data error: %s", exc)

    results: List[Dict[str, Any]] = []
    for j, entry in enumerate(cw_results):
        m = meta[j] if j < len(meta) else {}
        values     = entry.get("Values", [])
        timestamps = entry.get("Timestamps", [])
        total = round(sum(values), 3) if values else 0
        if total == 0 and not values:
            continue  # skip zero-data metrics
        results.append({
            "bot_name":    m.get("bot_name", ""),
            "metric_name": m.get("metric_name", ""),
            "total":       total,
            "data_points": [
                {"timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts), "value": v}
                for ts, v in zip(timestamps, values)
            ],
        })
    return results


# ── main handler ──────────────────────────────────────────────────────────────

def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:  # noqa: C901
    LOGGER.info(json.dumps({"event": "lambda_invoked", "function": event.get("function", "unknown")}))
    params = parse_parameters(event.get("parameters", []))

    instance_id = get_instance_id(params)
    if not instance_id:
        return build_error_response(event, "instance_id is required")

    query_type  = (params.get("query_type") or "all").strip().lower()
    interval    = (params.get("interval")    or "TOTAL").strip().upper()
    days        = int(params.get("days", 7))
    max_samples = int(params.get("max_samples", 20))

    now      = datetime.now(timezone.utc)
    start_dt = parse_datetime(params.get("start_time")) or (now - timedelta(days=days))
    end_dt   = parse_datetime(params.get("end_time"))   or now

    region     = get_instance_region()
    account_id = _get_account_id()

    connect_client = _CONNECT_CLIENT

    result: Dict[str, Any] = {
        "query_type": query_type,
        "start_time": start_dt.isoformat(),
        "end_time":   end_dt.isoformat(),
        "interval":   interval,
    }

    # 1. Bot inventory (always fetched — needed by downstream steps)
    v2_bots: List[Dict] = []
    v1_bots: List[Dict] = []
    all_bots: List[Dict] = []

    if query_type in ("inventory", "all", "lex_analytics", "escalations", "lex_cw"):
        v2_bots  = _list_lex_v2_bots(connect_client, instance_id)
        v1_bots  = _list_lex_v1_bots(connect_client, instance_id)
        all_bots = v2_bots + v1_bots
        result["bot_inventory"] = {
            "total_bots":     len(all_bots),
            "lex_v2_count":   len(v2_bots),
            "lex_v1_count":   len(v1_bots),
            "q_in_connect":   sum(1 for b in all_bots if b.get("has_q_in_connect")),
            "bots":           all_bots,
        }
        LOGGER.info("Inventory: %d V2 (%d Q-in-Connect), %d V1",
                    len(v2_bots),
                    result["bot_inventory"]["q_in_connect"],
                    len(v1_bots))

    # 2. Lex V2 analytics (session + intent + utterance metrics + missed utterances + escalations)
    if query_type in ("lex_analytics", "all"):
        lex_analytics: List[Dict] = []
        for bot in v2_bots:
            bid    = bot["bot_id"]
            region = bot["region"]
            locales = bot.get("locales", [])
            locale_id = locales[0]["locale_id"] if locales else "en_US"
            prod_alias = next((a for a in bot.get("aliases", []) if a.get("is_prod")),
                              bot.get("aliases", [{}])[0] if bot.get("aliases") else {})
            alias_id = prod_alias.get("alias_id", "")

            bot_analytics: Dict[str, Any] = {
                "bot_id":          bid,
                "bot_name":        bot["bot_name"],
                "has_q_in_connect": bot.get("has_q_in_connect", False),
                "alias_id":        alias_id,
                "locale_id":       locale_id,
            }

            bot_analytics["session_metrics"] = _session_metrics(
                bid, alias_id, locale_id, start_dt, end_dt, region)

            intent_metrics_data = _intent_metrics(bid, start_dt, end_dt, region)
            bot_analytics["intent_metrics"] = intent_metrics_data

            # Detect Q in Connect from intent_metrics (more reliable than list_intents)
            has_q = any(i.get("is_q_intent") for i in intent_metrics_data)
            if not has_q:
                has_q = any(i.get("intent_name") == AMAZON_Q_INTENT for i in intent_metrics_data)
            bot_analytics["has_q_in_connect"] = has_q
            # Also update the inventory entry so the frontend sees it
            bot["has_q_in_connect"] = has_q

            bot_analytics["utterance_metrics"] = _utterance_metrics(
                bid, start_dt, end_dt, region)

            # Only pull missed utterance samples for classic Lex bots (not Q in Connect)
            if not has_q:
                bot_analytics["missed_utterances"] = _missed_utterance_samples(
                    bid, alias_id, start_dt, end_dt, region, max_samples)
            else:
                # For Q in Connect bots, "Missed" = handled by LLM (expected)
                bot_analytics["missed_utterances"] = []
                bot_analytics["note"] = (
                    "AmazonQinConnect bot: utterances handled by LLM, "
                    "'Missed' count reflects Q in Connect delegation (expected). "
                    "See escalations for human handoff events."
                )

            # Escalations for all bot types
            bot_analytics["escalations"] = _escalation_sessions(
                bid, alias_id, start_dt, end_dt, region, max_samples)

            lex_analytics.append(bot_analytics)

        # Recalculate q_in_connect count after intent-based detection
        if "bot_inventory" in result:
            result["bot_inventory"]["q_in_connect"] = sum(1 for b in all_bots if b.get("has_q_in_connect"))

        result["lex_analytics"] = lex_analytics

    # 3. Flow metrics
    if query_type in ("flow_metrics", "all"):
        result["flow_metrics"] = _flow_metrics_v2(
            connect_client, instance_id, start_dt, end_dt,
            interval, region, account_id,
        )

    # 4. CloudWatch Lex metrics
    if query_type in ("lex_cw", "all"):
        bots_for_cw = all_bots or (
            _list_lex_v2_bots(connect_client, instance_id) +
            _list_lex_v1_bots(connect_client, instance_id)
        )
        result["lex_cloudwatch_metrics"] = _lex_cloudwatch_metrics(
            bots_for_cw, start_dt, end_dt, region)

    return build_response(event, result)
