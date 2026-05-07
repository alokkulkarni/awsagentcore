import logging
from typing import Any, Dict, List

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_csv, parse_parameters

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

CURRENT_METRICS = [
    {"Name": "AGENTS_ONLINE", "Unit": "COUNT"},
    {"Name": "AGENTS_AVAILABLE", "Unit": "COUNT"},
    {"Name": "AGENTS_ON_CALL", "Unit": "COUNT"},
    {"Name": "AGENTS_NON_PRODUCTIVE", "Unit": "COUNT"},
    {"Name": "AGENTS_AFTER_CONTACT_WORK", "Unit": "COUNT"},
    {"Name": "CONTACTS_IN_QUEUE", "Unit": "COUNT"},
    {"Name": "CONTACTS_SCHEDULED", "Unit": "COUNT"},
    {"Name": "OLDEST_CONTACT_AGE", "Unit": "SECONDS"},
]


def _list_queue_names(connect_client, instance_id: str) -> Dict[str, str]:
    queue_map: Dict[str, str] = {}
    paginator = connect_client.get_paginator("list_queues")
    for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD", "AGENT"]):
        for queue in page.get("QueueSummaryList", []):
            queue_map[queue["Id"]] = queue.get("Name", queue["Id"])
    return queue_map


def _metric_map(collections: List[Dict[str, Any]]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    for collection in collections:
        metric_name = collection.get("Metric", {}).get("Name")
        if not metric_name:
            continue
        value = collection.get("Value", 0)
        metrics[metric_name] = value
        if metric_name == "OLDEST_CONTACT_AGE":
            metrics[f"{metric_name}_formatted"] = format_duration(value)
    return metrics


def lambda_handler(event, _context):
    try:
        params = parse_parameters(event.get("parameters"))
        instance_id = get_instance_id(params)
        connect_client = boto3.client("connect")

        queue_ids = parse_csv(params.get("queue_ids"))
        routing_profile_ids = parse_csv(params.get("routing_profile_ids"))
        queue_lookup = _list_queue_names(connect_client, instance_id)

        if not queue_ids and not routing_profile_ids:
            queue_ids = list(queue_lookup.keys())
            if not queue_ids:
                return build_response(
                    event,
                    {
                        "message": "No Amazon Connect queues were found in this instance, so real-time metrics could not be collected.",
                        "overall_totals": {},
                        "queues": [],
                    },
                    status_code=200,
                )

        filters: Dict[str, Any] = {}
        if queue_ids:
            filters["Queues"] = queue_ids[:100]
        if routing_profile_ids:
            filters["RoutingProfiles"] = routing_profile_ids[:100]

        response = connect_client.get_current_metric_data(
            InstanceId=instance_id,
            Filters=filters,
            Groupings=["QUEUE"],
            CurrentMetrics=CURRENT_METRICS,
            MaxResults=100,
        )

        metric_results = response.get("MetricResults", [])
        if not metric_results:
            return build_response(
                event,
                {
                    "message": "Amazon Connect returned no current metric data for the requested filters.",
                    "overall_totals": {},
                    "queues": [],
                },
                status_code=200,
            )

        overall_totals: Dict[str, float] = {}
        queues: List[Dict[str, Any]] = []
        for result in metric_results:
            dimensions = result.get("Dimensions", {})
            queue_ref = dimensions.get("Queue", {})
            queue_id = queue_ref.get("Id")
            metrics = _metric_map(result.get("Collections", []))
            for key, value in metrics.items():
                if key.endswith("_formatted"):
                    continue
                overall_totals[key] = overall_totals.get(key, 0) + float(value)
            queues.append(
                {
                    "queue_id": queue_id,
                    "queue_name": queue_lookup.get(queue_id, queue_id or "Unknown Queue"),
                    "routing_profile_id": dimensions.get("RoutingProfile", {}).get("Id"),
                    "metrics": metrics,
                }
            )

        if "OLDEST_CONTACT_AGE" in overall_totals:
            overall_totals["OLDEST_CONTACT_AGE_formatted"] = format_duration(overall_totals["OLDEST_CONTACT_AGE"])

        return build_response(
            event,
            {
                "instance_id": instance_id,
                "filters": {
                    "queue_ids": queue_ids,
                    "routing_profile_ids": routing_profile_ids,
                },
                "overall_totals": overall_totals,
                "queues": sorted(queues, key=lambda item: item.get("queue_name") or ""),
                "snapshot_time": response.get("DataSnapshotTime"),
                "approximate_total_count": response.get("ApproximateTotalCount", len(queues)),
            },
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to retrieve current metrics")
        return build_error_response(event, f"Unable to fetch Amazon Connect real-time metrics: {exc}", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while retrieving current metrics")
        return build_error_response(event, str(exc), status_code=500)
