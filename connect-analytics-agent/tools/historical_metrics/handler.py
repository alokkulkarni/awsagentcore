import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_csv, parse_datetime, parse_parameters
from shared.scan_resources import get_instance_arn, get_queue_id_map, get_queue_ids, get_routing_profile_id_map

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

ALLOWED_METRICS = {
    # Core contact metrics
    "CONTACTS_HANDLED",
    "CONTACTS_ABANDONED",
    "CONTACTS_QUEUED",
    "CONTACTS_CREATED",
    "CONTACTS_TRANSFERRED_IN",
    "CONTACTS_TRANSFERRED_OUT",
    "CONTACTS_TRANSFERRED_IN_FROM_QUEUE",
    "CONTACTS_TRANSFERRED_OUT_FROM_QUEUE",
    "CONTACTS_TRANSFERRED_IN_BY_AGENT",
    "CONTACTS_TRANSFERRED_OUT_BY_AGENT",
    "CONTACTS_HOLD_ABANDONS",
    "CONTACTS_MISSED",
    "CONTACTS_AGENT_HUNG_UP_FIRST",
    "CONTACTS_HANDLED_BY_CONNECTED_TO_AGENT",
    "CONTACTS_ON_HOLD",
    # Average time metrics
    "AVG_HANDLE_TIME",
    "AVG_AFTER_CONTACT_WORK_TIME",
    "AVG_QUEUE_ANSWER_TIME",
    "AVG_HOLD_TIME",
    "AVG_HOLD_TIME_ALL_CONTACTS",
    "AVG_TALK_TIME",
    "AVG_INTERACTION_TIME",
    "AVG_INTERACTION_AND_HOLD_TIME",
    "AVG_ABANDON_TIME",
    "AVG_GREETING_TIME",
    "AVG_AGENT_CONNECTING_TIME",
    "AVG_CONTACT_DURATION",
    "AVG_ACTIVE_TIME",
    "AVG_IDLE_TIME",
    "AVG_NON_TALK_TIME",
    "AVG_INTERRUPTIONS_TIME",
    # Agent state/time sum metrics
    "SUM_ONLINE_TIME_AGENT",
    "SUM_IDLE_TIME_AGENT",
    "SUM_NON_PRODUCTIVE_TIME_AGENT",
    "SUM_CONTACT_TIME_AGENT",
    "SUM_AFTER_CONTACT_WORK_TIME",
    "SUM_HANDLE_TIME",
    "SUM_HOLD_TIME",
    "SUM_TALK_TIME",
    "SUM_TALK_TIME_AGENT",
    "SUM_TALK_TIME_CUSTOMER",
    "SUM_CONNECTING_TIME_AGENT",
    "SUM_ERROR_STATUS_TIME",
    "SUM_CONTACTS_HANDLED",
    "SUM_CONTACTS_ABANDONED",
    "SUM_CONTACTS_MISSED",
    "SUM_CONTACTS_QUEUED",
    "SUM_CONTACTS_TRANSFERRED_IN",
    "SUM_CONTACTS_TRANSFERRED_OUT",
    "SUM_CONTACTS_HOLD_ABANDONS",
    # Rate/percentage metrics
    "AGENT_OCCUPANCY",
    "AGENT_NON_RESPONSE",
    "AGENT_ANSWER_RATE",
    "ABANDONMENT_RATE",
    "SERVICE_LEVEL",
    "PERCENT_TALK_TIME",
    "PERCENT_TALK_TIME_AGENT",
    "PERCENT_TALK_TIME_CUSTOMER",
    "PERCENT_NON_TALK_TIME",
    # Queue/wait metrics
    "MAX_QUEUED_TIME",
    # Bot / conversational AI metrics (Connect GetMetricDataV2 with BOT grouping)
    "BOT_CONVERSATIONS_COMPLETED",
    "BOT_INTENT_ATTEMPTED",
    "BOT_INTENT_COMPLETED",
    "AVG_BOT_CONVERSATION_TIME",
    "AVG_BOT_CONVERSATION_TURNS",
    "PERCENT_BOT_CONVERSATIONS_OUTCOME",
    # Contact flow / IVR metrics
    "FLOWS_OUTCOME",
    "FLOWS_STARTED",
    "PERCENT_FLOWS_OUTCOME",
    "AVG_FLOW_TIME",
    "MAX_FLOW_TIME",
    "MIN_FLOW_TIME",
    # Step / routing step metrics
    "STEP_CONTACTS_QUEUED",
}

METRIC_INTENTS = {
    "agent_state": [
        "AGENT_OCCUPANCY",
        "SUM_ONLINE_TIME_AGENT",
        "SUM_IDLE_TIME_AGENT",
        "SUM_NON_PRODUCTIVE_TIME_AGENT",
        "SUM_CONTACT_TIME_AGENT",
        "SUM_AFTER_CONTACT_WORK_TIME",
        "SUM_ERROR_STATUS_TIME",
        "CONTACTS_HANDLED",
        "CONTACTS_MISSED",
    ],
    "agent_performance": [
        "CONTACTS_HANDLED",
        "AVG_HANDLE_TIME",
        "AGENT_OCCUPANCY",
        "AVG_AFTER_CONTACT_WORK_TIME",
        "CONTACTS_MISSED",
        "AGENT_ANSWER_RATE",
        "AVG_TALK_TIME",
        "AVG_HOLD_TIME",
        "AGENT_NON_RESPONSE",
    ],
    "queue_health": [
        "CONTACTS_HANDLED",
        "CONTACTS_ABANDONED",
        "CONTACTS_QUEUED",
        "AVG_QUEUE_ANSWER_TIME",
        "AVG_HANDLE_TIME",
        "ABANDONMENT_RATE",
        "SERVICE_LEVEL",
        "MAX_QUEUED_TIME",
        "CONTACTS_HOLD_ABANDONS",
    ],
    "transfer": [
        "CONTACTS_TRANSFERRED_IN",
        "CONTACTS_TRANSFERRED_OUT",
        "CONTACTS_TRANSFERRED_IN_FROM_QUEUE",
        "CONTACTS_TRANSFERRED_OUT_FROM_QUEUE",
        "CONTACTS_TRANSFERRED_IN_BY_AGENT",
        "CONTACTS_TRANSFERRED_OUT_BY_AGENT",
    ],
    "hold": [
        "CONTACTS_ON_HOLD",
        "CONTACTS_HOLD_ABANDONS",
        "AVG_HOLD_TIME",
        "AVG_HOLD_TIME_ALL_CONTACTS",
        "SUM_HOLD_TIME",
    ],
    "talk_time": [
        "AVG_TALK_TIME",
        "SUM_TALK_TIME",
        "SUM_TALK_TIME_AGENT",
        "SUM_TALK_TIME_CUSTOMER",
        "PERCENT_TALK_TIME",
        "PERCENT_TALK_TIME_AGENT",
        "PERCENT_TALK_TIME_CUSTOMER",
        "PERCENT_NON_TALK_TIME",
        "AVG_NON_TALK_TIME",
    ],
    "abandonment": [
        "CONTACTS_ABANDONED",
        "CONTACTS_HOLD_ABANDONS",
        "ABANDONMENT_RATE",
        "AVG_ABANDON_TIME",
        "SUM_CONTACTS_ABANDONED",
    ],
    "bot_performance": [
        "BOT_CONVERSATIONS_COMPLETED",
        "BOT_INTENT_ATTEMPTED",
        "BOT_INTENT_COMPLETED",
        "AVG_BOT_CONVERSATION_TIME",
        "AVG_BOT_CONVERSATION_TURNS",
        "PERCENT_BOT_CONVERSATIONS_OUTCOME",
    ],
    "flow_performance": [
        "FLOWS_OUTCOME",
        "FLOWS_STARTED",
        "PERCENT_FLOWS_OUTCOME",
        "AVG_FLOW_TIME",
        "MAX_FLOW_TIME",
        "MIN_FLOW_TIME",
        "STEP_CONTACTS_QUEUED",
    ],
}

TIME_METRICS = {
    "AVG_HANDLE_TIME",
    "AVG_AFTER_CONTACT_WORK_TIME",
    "AVG_QUEUE_ANSWER_TIME",
    "AVG_HOLD_TIME",
    "AVG_HOLD_TIME_ALL_CONTACTS",
    "AVG_TALK_TIME",
    "AVG_INTERACTION_TIME",
    "AVG_INTERACTION_AND_HOLD_TIME",
    "AVG_ABANDON_TIME",
    "AVG_GREETING_TIME",
    "AVG_AGENT_CONNECTING_TIME",
    "AVG_CONTACT_DURATION",
    "AVG_ACTIVE_TIME",
    "AVG_IDLE_TIME",
    "AVG_NON_TALK_TIME",
    "AVG_INTERRUPTIONS_TIME",
    "SUM_ONLINE_TIME_AGENT",
    "SUM_IDLE_TIME_AGENT",
    "SUM_NON_PRODUCTIVE_TIME_AGENT",
    "SUM_CONTACT_TIME_AGENT",
    "SUM_AFTER_CONTACT_WORK_TIME",
    "SUM_HANDLE_TIME",
    "SUM_HOLD_TIME",
    "SUM_TALK_TIME",
    "SUM_TALK_TIME_AGENT",
    "SUM_TALK_TIME_CUSTOMER",
    "SUM_CONNECTING_TIME_AGENT",
    "SUM_ERROR_STATUS_TIME",
    "MAX_QUEUED_TIME",
    # Bot / flow time metrics
    "AVG_BOT_CONVERSATION_TIME",
    "AVG_FLOW_TIME",
    "MAX_FLOW_TIME",
    "MIN_FLOW_TIME",
}

PERCENTAGE_METRICS = {
    "AGENT_OCCUPANCY",
    "AGENT_NON_RESPONSE",
    "AGENT_ANSWER_RATE",
    "ABANDONMENT_RATE",
    "SERVICE_LEVEL",
    "PERCENT_TALK_TIME",
    "PERCENT_TALK_TIME_AGENT",
    "PERCENT_TALK_TIME_CUSTOMER",
    "PERCENT_NON_TALK_TIME",
    "PERCENT_BOT_CONVERSATIONS_OUTCOME",
    "PERCENT_FLOWS_OUTCOME",
}

METRIC_LABELS = {
    "CONTACTS_HANDLED": "Contacts Handled",
    "CONTACTS_ABANDONED": "Contacts Abandoned",
    "CONTACTS_QUEUED": "Contacts Queued",
    "CONTACTS_CREATED": "Contacts Created",
    "CONTACTS_TRANSFERRED_IN": "Contacts Transferred In",
    "CONTACTS_TRANSFERRED_OUT": "Contacts Transferred Out",
    "CONTACTS_TRANSFERRED_IN_FROM_QUEUE": "Transfers In From Queue",
    "CONTACTS_TRANSFERRED_OUT_FROM_QUEUE": "Transfers Out From Queue",
    "CONTACTS_TRANSFERRED_IN_BY_AGENT": "Transfers In By Agent",
    "CONTACTS_TRANSFERRED_OUT_BY_AGENT": "Transfers Out By Agent",
    "CONTACTS_HOLD_ABANDONS": "Hold Abandons",
    "CONTACTS_MISSED": "Contacts Missed",
    "CONTACTS_AGENT_HUNG_UP_FIRST": "Agent Hung Up First",
    "CONTACTS_HANDLED_BY_CONNECTED_TO_AGENT": "Handled By Connected Agent",
    "CONTACTS_ON_HOLD": "Contacts On Hold",
    "AVG_HANDLE_TIME": "Average Handle Time",
    "AVG_AFTER_CONTACT_WORK_TIME": "Average After Contact Work Time",
    "AVG_QUEUE_ANSWER_TIME": "Average Queue Answer Time",
    "AVG_HOLD_TIME": "Average Hold Time",
    "AVG_HOLD_TIME_ALL_CONTACTS": "Average Hold Time (All Contacts)",
    "AVG_TALK_TIME": "Average Talk Time",
    "AVG_INTERACTION_TIME": "Average Interaction Time",
    "AVG_INTERACTION_AND_HOLD_TIME": "Average Interaction + Hold Time",
    "AVG_ABANDON_TIME": "Average Abandon Time",
    "AVG_GREETING_TIME": "Average Greeting Time",
    "AVG_AGENT_CONNECTING_TIME": "Average Agent Connecting Time",
    "AVG_CONTACT_DURATION": "Average Contact Duration",
    "AVG_ACTIVE_TIME": "Average Active Time",
    "AVG_IDLE_TIME": "Average Idle Time",
    "AVG_NON_TALK_TIME": "Average Non-Talk Time",
    "AVG_INTERRUPTIONS_TIME": "Average Interruptions Time",
    "SUM_ONLINE_TIME_AGENT": "Total Online Time",
    "SUM_IDLE_TIME_AGENT": "Total Idle Time",
    "SUM_NON_PRODUCTIVE_TIME_AGENT": "Total Non-Productive Time",
    "SUM_CONTACT_TIME_AGENT": "Total Contact Time",
    "SUM_AFTER_CONTACT_WORK_TIME": "Total After Contact Work Time",
    "SUM_HANDLE_TIME": "Total Handle Time",
    "SUM_HOLD_TIME": "Total Hold Time",
    "SUM_TALK_TIME": "Total Talk Time",
    "SUM_TALK_TIME_AGENT": "Total Agent Talk Time",
    "SUM_TALK_TIME_CUSTOMER": "Total Customer Talk Time",
    "SUM_CONNECTING_TIME_AGENT": "Total Agent Connecting Time",
    "SUM_ERROR_STATUS_TIME": "Total Error Status Time",
    "SUM_CONTACTS_HANDLED": "Total Contacts Handled",
    "SUM_CONTACTS_ABANDONED": "Total Contacts Abandoned",
    "SUM_CONTACTS_MISSED": "Total Contacts Missed",
    "SUM_CONTACTS_QUEUED": "Total Contacts Queued",
    "SUM_CONTACTS_TRANSFERRED_IN": "Total Contacts Transferred In",
    "SUM_CONTACTS_TRANSFERRED_OUT": "Total Contacts Transferred Out",
    "SUM_CONTACTS_HOLD_ABANDONS": "Total Hold Abandons",
    "AGENT_OCCUPANCY": "Agent Occupancy %",
    "AGENT_NON_RESPONSE": "Agent Non-Response %",
    "AGENT_ANSWER_RATE": "Agent Answer Rate %",
    "ABANDONMENT_RATE": "Abandonment Rate %",
    "SERVICE_LEVEL": "Service Level %",
    "PERCENT_TALK_TIME": "Talk Time %",
    "PERCENT_TALK_TIME_AGENT": "Agent Talk Time %",
    "PERCENT_TALK_TIME_CUSTOMER": "Customer Talk Time %",
    "PERCENT_NON_TALK_TIME": "Non-Talk Time %",
    "MAX_QUEUED_TIME": "Max Queued Time",
    # Bot / conversational AI labels
    "BOT_CONVERSATIONS_COMPLETED": "Bot Conversations Completed",
    "BOT_INTENT_ATTEMPTED": "Bot Intents Attempted",
    "BOT_INTENT_COMPLETED": "Bot Intents Completed",
    "AVG_BOT_CONVERSATION_TIME": "Avg Bot Conversation Time",
    "AVG_BOT_CONVERSATION_TURNS": "Avg Bot Conversation Turns",
    "PERCENT_BOT_CONVERSATIONS_OUTCOME": "Bot Conversations Outcome %",
    # Flow / IVR labels
    "FLOWS_OUTCOME": "Flow Outcomes",
    "FLOWS_STARTED": "Flows Started",
    "PERCENT_FLOWS_OUTCOME": "Flow Outcome %",
    "AVG_FLOW_TIME": "Avg Flow Time",
    "MAX_FLOW_TIME": "Max Flow Time",
    "MIN_FLOW_TIME": "Min Flow Time",
    "STEP_CONTACTS_QUEUED": "Step Contacts Queued",
}

VALID_GROUPS = {"AGENT", "QUEUE", "ROUTING_PROFILE", "BOT", "FLOW_TYPE"}  # FLOW_NAME/INTENT are not valid Connect groupings
VALID_INTERVALS = {"TOTAL", "DAY", "HOUR", "FIFTEEN_MIN", "THIRTY_MIN"}
VALID_CHANNELS = {"VOICE", "CHAT", "TASK"}


def _resource_arn(instance_id: str) -> str:
    return get_instance_arn(instance_id)


def _load_routing_profile_names(connect_client, instance_id: str) -> Dict[str, str]:
    # Prefer scan data; fall back to live API inside get_routing_profile_id_map
    return get_routing_profile_id_map(instance_id, connect_client)


def _user_display_name(connect_client, instance_id: str, user_id: str) -> str:
    try:
        user = connect_client.describe_user(InstanceId=instance_id, UserId=user_id).get("User", {})
        identity = user.get("IdentityInfo", {})
        full_name = " ".join(part for part in [identity.get("FirstName"), identity.get("LastName")] if part)
        return full_name or user.get("Username", user_id)
    except Exception:  # pylint: disable=broad-except
        return user_id


def _dimension_display_name(connect_client, instance_id: str, group_by: str, dimension_value: str, queue_names, routing_profile_names) -> str:
    if group_by == "QUEUE":
        return queue_names.get(dimension_value, dimension_value)
    if group_by == "ROUTING_PROFILE":
        return routing_profile_names.get(dimension_value, dimension_value)
    if group_by == "AGENT":
        return _user_display_name(connect_client, instance_id, dimension_value)
    return dimension_value


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    items: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            items.append(value)
    return items


def _normalize_routing_profile_value(value: str) -> str:
    normalized = str(value).strip()
    if normalized.startswith("arn:") and "/" in normalized:
        return normalized.rsplit("/", 1)[-1]
    return normalized


def _build_metric_spec(name: str) -> Dict[str, Any]:
    if name == "SERVICE_LEVEL":
        return {"Name": name, "Threshold": [{"Comparison": "LT", "ThresholdValue": 20}]}
    return {"Name": name}


def _format_metric_value(metric_name: str, metric_value: Optional[float]) -> Optional[Any]:
    if metric_value is None:
        return None
    if metric_name in TIME_METRICS:
        return format_duration(metric_value)
    if metric_name in PERCENTAGE_METRICS:
        return f"{float(metric_value):.2f}%"
    return metric_value


def _build_metric_maps(requested_metrics: List[str], collections: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    metrics: Dict[str, Any] = {metric: None for metric in requested_metrics}
    for collection in collections:
        metric_name = collection.get("Metric", {}).get("Name")
        if metric_name in metrics:
            metrics[metric_name] = collection.get("Value")

    formatted_metrics = {
        metric: _format_metric_value(metric, value)
        for metric, value in metrics.items()
        if value is not None
    }
    time_breakdown = {
        metric: {
            "label": METRIC_LABELS.get(metric, metric),
            "seconds": value,
            "formatted": format_duration(value),
        }
        for metric, value in metrics.items()
        if metric in TIME_METRICS and value is not None
    }
    return metrics, formatted_metrics, time_breakdown


def _empty_metric_totals(requested_metrics: List[str]) -> Dict[str, float]:
    return {metric: 0.0 for metric in requested_metrics}


def _accumulate_metrics(target: Dict[str, float], source: Dict[str, Any]) -> None:
    for metric, value in source.items():
        if value is not None:
            target[metric] = float(target.get(metric, 0.0)) + float(value)


def _resolve_requested_metrics(params: Dict[str, Any]) -> Tuple[str, List[str], List[str]]:
    warnings: List[str] = []
    requested_intent = str(params.get("intent", "queue_health") or "queue_health").strip().lower()
    intent = requested_intent if requested_intent in METRIC_INTENTS else "queue_health"
    if requested_intent != intent:
        LOGGER.warning("Unsupported intent '%s'; defaulting to queue_health.", requested_intent)
        warnings.append(f"Unsupported intent '{requested_intent}' ignored; using queue_health.")

    requested_metric_names = [metric.upper() for metric in parse_csv(params.get("metrics"))]
    valid_metrics = [metric for metric in _dedupe(requested_metric_names) if metric in ALLOWED_METRICS]
    invalid_metrics = [metric for metric in _dedupe(requested_metric_names) if metric not in ALLOWED_METRICS]
    if invalid_metrics:
        LOGGER.warning("Skipping unsupported historical metrics: %s", ", ".join(invalid_metrics))
        warnings.append(f"Skipped unsupported metrics: {', '.join(invalid_metrics)}")

    if not valid_metrics:
        if requested_metric_names:
            LOGGER.warning("No supported requested metrics remained; falling back to intent '%s'.", intent)
            warnings.append(f"No valid requested metrics remained; using intent '{intent}' defaults.")
        valid_metrics = [metric for metric in METRIC_INTENTS[intent] if metric in ALLOWED_METRICS]

    valid_metrics = _dedupe(valid_metrics)
    if not valid_metrics:
        raise ValueError("No valid historical metrics available for this request.")
    return intent, valid_metrics, warnings


def lambda_handler(event, _context):
    try:
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        start_time = parse_datetime(params.get("start_time"))
        end_time = parse_datetime(params.get("end_time"))
        if not start_time or not end_time:
            raise ValueError("start_time and end_time are required in ISO 8601 format.")
        if start_time >= end_time:
            raise ValueError("start_time must be earlier than end_time.")

        group_by = str(params.get("group_by", "AGENT")).upper()
        if group_by not in VALID_GROUPS:
            raise ValueError("group_by must be one of AGENT, QUEUE, or ROUTING_PROFILE.")

        raw_interval = str(params.get("interval", "TOTAL")).upper()
        interval_period = raw_interval if raw_interval in VALID_INTERVALS else "TOTAL"
        intent, requested_metrics, warnings = _resolve_requested_metrics(params)

        channel_filters = [channel.upper() for channel in parse_csv(params.get("channel_filter"))]
        invalid_channels = [channel for channel in channel_filters if channel not in VALID_CHANNELS]
        if invalid_channels:
            raise ValueError("channel_filter must contain only VOICE, CHAT, or TASK.")
        channel_filters = _dedupe(channel_filters)

        routing_profile_filters = _dedupe(
            [_normalize_routing_profile_value(value) for value in parse_csv(params.get("routing_profile_filter"))]
        )
        if len(routing_profile_filters) > 100:
            LOGGER.warning("Routing profile filter has >100 values; limiting to the first 100.")
            warnings.append("Routing profile filter truncated to the first 100 values.")
            routing_profile_filters = routing_profile_filters[:100]

        connect_client = boto3.client("connect")

        # Use scan data for queue list — falls back to live API automatically
        all_queues = get_queue_ids(instance_id, connect_client)
        queue_names = get_queue_id_map(instance_id, connect_client)

        queue_ids = all_queues[:100]
        if len(all_queues) > 100:
            LOGGER.warning("Instance has >100 queues; metrics are limited to the first 100.")
            warnings.append("Queue filter truncated to the first 100 queues.")

        filters: List[Dict[str, Any]] = []
        if queue_ids:
            filters.append({"FilterKey": "QUEUE", "FilterValues": queue_ids})
        if channel_filters:
            filters.append({"FilterKey": "CHANNEL", "FilterValues": channel_filters})
        if routing_profile_filters:
            filters.append({"FilterKey": "ROUTING_PROFILE", "FilterValues": routing_profile_filters})

        if not any(metric_filter["FilterKey"] in {"QUEUE", "ROUTING_PROFILE", "AGENT"} for metric_filter in filters):
            raise ValueError(
                "No queues found in the Connect instance. GetMetricDataV2 requires at least one queue or routing_profile_filter."
            )

        metric_results: List[Dict[str, Any]] = []
        next_token: Optional[str] = None
        while True:
            request_kwargs: Dict[str, Any] = {
                "ResourceArn": _resource_arn(instance_id),
                "StartTime": start_time,
                "EndTime": end_time,
                "Interval": {"TimeZone": "UTC", "IntervalPeriod": interval_period},
                "Filters": filters,
                "Groupings": [group_by],
                "Metrics": [_build_metric_spec(metric) for metric in requested_metrics],
                "MaxResults": 100,
            }
            if next_token:
                request_kwargs["NextToken"] = next_token

            response = connect_client.get_metric_data_v2(**request_kwargs)
            metric_results.extend(response.get("MetricResults", []))
            next_token = response.get("NextToken")
            if not next_token:
                break

        routing_profile_names = _load_routing_profile_names(connect_client, instance_id) if group_by == "ROUTING_PROFILE" else {}
        display_name_cache: Dict[str, str] = {}

        def resolve_display_name(dimension_value: Optional[str]) -> Optional[str]:
            if not dimension_value:
                return dimension_value
            if dimension_value not in display_name_cache:
                display_name_cache[dimension_value] = _dimension_display_name(
                    connect_client,
                    instance_id,
                    group_by,
                    dimension_value,
                    queue_names,
                    routing_profile_names,
                )
            return display_name_cache[dimension_value]

        sort_metric = "CONTACTS_HANDLED" if "CONTACTS_HANDLED" in requested_metrics else requested_metrics[0]
        rows: List[Dict[str, Any]] = []
        dimension_results: List[Dict[str, Any]] = []

        if interval_period != "TOTAL":
            bucket_totals: Dict[str, Dict[str, Any]] = {}
            agent_timelines: Dict[str, Dict[str, Any]] = {}

            for result in metric_results:
                metric_interval = result.get("MetricInterval", {})
                bucket_key = str(metric_interval.get("StartTime", ""))
                metric_values, _, _ = _build_metric_maps(requested_metrics, result.get("Collections", []))

                if bucket_key not in bucket_totals:
                    bucket_totals[bucket_key] = {
                        "interval_start": metric_interval.get("StartTime"),
                        "interval_end": metric_interval.get("EndTime"),
                        "metrics": _empty_metric_totals(requested_metrics),
                    }
                _accumulate_metrics(bucket_totals[bucket_key]["metrics"], metric_values)

                if group_by == "AGENT":
                    dimension_value = result.get("Dimensions", {}).get(group_by)
                    if dimension_value not in agent_timelines:
                        agent_timelines[dimension_value] = {
                            "group_by": group_by,
                            "dimension_value": dimension_value,
                            "display_name": resolve_display_name(dimension_value),
                            "timeline_map": {},
                            "totals": _empty_metric_totals(requested_metrics),
                        }
                    if bucket_key not in agent_timelines[dimension_value]["timeline_map"]:
                        agent_timelines[dimension_value]["timeline_map"][bucket_key] = {
                            "interval_start": metric_interval.get("StartTime"),
                            "interval_end": metric_interval.get("EndTime"),
                            "metrics": _empty_metric_totals(requested_metrics),
                        }
                    _accumulate_metrics(agent_timelines[dimension_value]["timeline_map"][bucket_key]["metrics"], metric_values)
                    _accumulate_metrics(agent_timelines[dimension_value]["totals"], metric_values)

            for bucket in bucket_totals.values():
                formatted_metrics = {
                    metric: _format_metric_value(metric, value)
                    for metric, value in bucket["metrics"].items()
                    if value is not None
                }
                time_breakdown = {
                    metric: {
                        "label": METRIC_LABELS.get(metric, metric),
                        "seconds": value,
                        "formatted": format_duration(value),
                    }
                    for metric, value in bucket["metrics"].items()
                    if metric in TIME_METRICS and value is not None
                }
                bucket["formatted_metrics"] = formatted_metrics
                bucket["time_breakdown"] = time_breakdown
                rows.append(bucket)
            rows.sort(key=lambda row: str(row.get("interval_start") or ""))

            if group_by == "AGENT":
                for agent_row in agent_timelines.values():
                    timeline_rows: List[Dict[str, Any]] = []
                    for bucket in agent_row.pop("timeline_map").values():
                        bucket["formatted_metrics"] = {
                            metric: _format_metric_value(metric, value)
                            for metric, value in bucket["metrics"].items()
                            if value is not None
                        }
                        bucket["time_breakdown"] = {
                            metric: {
                                "label": METRIC_LABELS.get(metric, metric),
                                "seconds": value,
                                "formatted": format_duration(value),
                            }
                            for metric, value in bucket["metrics"].items()
                            if metric in TIME_METRICS and value is not None
                        }
                        timeline_rows.append(bucket)
                    timeline_rows.sort(key=lambda row: str(row.get("interval_start") or ""))
                    totals = agent_row["totals"]
                    agent_row["timeline"] = timeline_rows
                    agent_row["formatted_totals"] = {
                        metric: _format_metric_value(metric, value)
                        for metric, value in totals.items()
                        if value is not None
                    }
                    agent_row["time_breakdown"] = {
                        metric: {
                            "label": METRIC_LABELS.get(metric, metric),
                            "seconds": value,
                            "formatted": format_duration(value),
                        }
                        for metric, value in totals.items()
                        if metric in TIME_METRICS and value is not None
                    }
                    agent_row["occupancy"] = totals.get("AGENT_OCCUPANCY")
                    agent_row["occupancy_formatted"] = _format_metric_value("AGENT_OCCUPANCY", totals.get("AGENT_OCCUPANCY"))
                    dimension_results.append(agent_row)
                dimension_results.sort(key=lambda row: row.get("totals", {}).get(sort_metric) or 0, reverse=True)
        else:
            for result in metric_results:
                dimension_value = result.get("Dimensions", {}).get(group_by)
                metrics, formatted_metrics, time_breakdown = _build_metric_maps(requested_metrics, result.get("Collections", []))
                row = {
                    "group_by": group_by,
                    "dimension_value": dimension_value,
                    "display_name": resolve_display_name(dimension_value),
                    "metric_interval": result.get("MetricInterval"),
                    "metrics": metrics,
                    "formatted_metrics": formatted_metrics,
                }
                if group_by == "AGENT":
                    row["time_breakdown"] = time_breakdown
                    row["occupancy"] = metrics.get("AGENT_OCCUPANCY")
                    row["occupancy_formatted"] = _format_metric_value("AGENT_OCCUPANCY", metrics.get("AGENT_OCCUPANCY"))
                rows.append(row)
            rows.sort(key=lambda row: row.get("metrics", {}).get(sort_metric) or 0, reverse=True)

        payload = {
            "instance_id": instance_id,
            "intent": intent,
            "group_by": group_by,
            "interval": interval_period,
            "metrics": requested_metrics,
            "metric_labels": {metric: METRIC_LABELS.get(metric, metric) for metric in requested_metrics},
            "time_metrics": [metric for metric in requested_metrics if metric in TIME_METRICS],
            "percentage_metrics": [metric for metric in requested_metrics if metric in PERCENTAGE_METRICS],
            "start_time": start_time,
            "end_time": end_time,
            "is_time_series": interval_period != "TOTAL",
            "applied_filters": {
                "queue_count": len(queue_ids),
                "channel_filter": channel_filters,
                "routing_profile_filter": routing_profile_filters,
            },
            "warnings": warnings,
            "results": rows,
        }
        if interval_period != "TOTAL" and group_by == "AGENT":
            payload["dimension_results"] = dimension_results
            payload["agent_timelines"] = dimension_results
        if interval_period == "TOTAL" and group_by == "AGENT":
            payload["agent_results"] = rows

        return build_response(event, payload)
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to fetch historical metrics")
        return build_error_response(event, f"Unable to fetch Amazon Connect historical metrics: {exc}", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while retrieving historical metrics")
        return build_error_response(event, str(exc), status_code=500)
