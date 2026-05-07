import logging
import os
from typing import Any, Dict, List

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from shared.connect_utils import build_error_response, build_response, format_duration, get_instance_id, parse_csv, parse_datetime, parse_parameters

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

ALLOWED_METRICS = {
    "AVG_HANDLE_TIME",
    "AVG_AFTER_CONTACT_WORK_TIME",
    "CONTACTS_HANDLED",
    "CONTACTS_ABANDONED",
    "AVG_QUEUE_ANSWER_TIME",
    "SERVICE_LEVEL",
}


def _resource_arn(instance_id: str) -> str:
    session = boto3.session.Session()
    region = session.region_name or os.getenv("AWS_REGION", "us-east-1")
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    return f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}"


def _load_queue_names(connect_client, instance_id: str) -> Dict[str, str]:
    names: Dict[str, str] = {}
    paginator = connect_client.get_paginator("list_queues")
    for page in paginator.paginate(InstanceId=instance_id, QueueTypes=["STANDARD", "AGENT"]):
        for queue in page.get("QueueSummaryList", []):
            names[queue["Id"]] = queue.get("Name", queue["Id"])
    return names


def _load_routing_profile_names(connect_client, instance_id: str) -> Dict[str, str]:
    names: Dict[str, str] = {}
    paginator = connect_client.get_paginator("list_routing_profiles")
    for page in paginator.paginate(InstanceId=instance_id):
        for profile in page.get("RoutingProfileSummaryList", []):
            names[profile["Id"]] = profile.get("Name", profile["Id"])
    return names


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
        if group_by not in {"AGENT", "QUEUE", "ROUTING_PROFILE"}:
            raise ValueError("group_by must be one of AGENT, QUEUE, or ROUTING_PROFILE.")

        requested_metrics = [metric.upper() for metric in parse_csv(params.get("metrics"))] or ["CONTACTS_HANDLED", "AVG_HANDLE_TIME"]
        invalid_metrics = [metric for metric in requested_metrics if metric not in ALLOWED_METRICS]
        if invalid_metrics:
            raise ValueError(f"Unsupported metrics requested: {', '.join(invalid_metrics)}")

        connect_client = boto3.client("connect")
        response = connect_client.get_metric_data_v2(
            ResourceArn=_resource_arn(instance_id),
            StartTime=start_time,
            EndTime=end_time,
            Interval={"TimeZone": "UTC", "IntervalPeriod": "TOTAL"},
            Groupings=[group_by],
            Metrics=[{"Name": metric} for metric in requested_metrics],
            MaxResults=100,
        )

        queue_names = _load_queue_names(connect_client, instance_id) if group_by == "QUEUE" else {}
        routing_profile_names = _load_routing_profile_names(connect_client, instance_id) if group_by == "ROUTING_PROFILE" else {}

        rows: List[Dict[str, Any]] = []
        for result in response.get("MetricResults", []):
            dimensions = result.get("Dimensions", {})
            dimension_value = dimensions.get(group_by)
            metrics: Dict[str, Any] = {}
            for collection in result.get("Collections", []):
                metric_name = collection.get("Metric", {}).get("Name")
                metric_value = collection.get("Value")
                metrics[metric_name] = metric_value
                if metric_name and "TIME" in metric_name and metric_value is not None:
                    metrics[f"{metric_name}_formatted"] = format_duration(metric_value)
            rows.append(
                {
                    "group_by": group_by,
                    "dimension_value": dimension_value,
                    "display_name": _dimension_display_name(
                        connect_client,
                        instance_id,
                        group_by,
                        dimension_value,
                        queue_names,
                        routing_profile_names,
                    ),
                    "metric_interval": result.get("MetricInterval"),
                    "metrics": metrics,
                }
            )

        sort_metric = "CONTACTS_HANDLED" if "CONTACTS_HANDLED" in requested_metrics else requested_metrics[0]
        rows.sort(key=lambda item: item.get("metrics", {}).get(sort_metric) or 0, reverse=True)

        return build_response(
            event,
            {
                "instance_id": instance_id,
                "group_by": group_by,
                "metrics": requested_metrics,
                "start_time": start_time,
                "end_time": end_time,
                "sort_metric": sort_metric,
                "results": rows,
            },
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("Failed to fetch historical metrics")
        return build_error_response(event, f"Unable to fetch Amazon Connect historical metrics: {exc}", status_code=502)
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.exception("Unexpected error while retrieving historical metrics")
        return build_error_response(event, str(exc), status_code=500)
