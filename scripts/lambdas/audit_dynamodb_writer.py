"""
Lambda function: EventBridge → DynamoDB
Routes ARIA banking audit events to a DynamoDB table for real-time operational
queries (complaint handling, fraud investigation). TTL-expires records after
TTL_DAYS to keep the table lean; older records are archived in S3 WORM.

Environment variables:
  DYNAMODB_TABLE  — table name (default: aria-audit-events)
  TTL_DAYS        — days before record expires (default: 90)
  AWS_REGION      — region of the DynamoDB table (default: eu-west-2)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "aria-audit-events")
TTL_DAYS = int(os.environ.get("TTL_DAYS", "90"))
_region = os.environ.get("AWS_REGION", "eu-west-2")
_dynamodb = boto3.resource("dynamodb", region_name=_region)
_table = _dynamodb.Table(TABLE_NAME)


def handler(event, context):
    detail = event.get("detail", {})
    event_id = detail.get("event_id", context.aws_request_id)
    customer_id = detail.get("customer_id", "UNKNOWN")
    timestamp = detail.get("timestamp",
                           datetime.now(timezone.utc).isoformat())

    ttl_epoch = int(time.time()) + (TTL_DAYS * 86_400)

    item = {
        "customer_id": customer_id,
        "timestamp": timestamp,
        "event_id": event_id,
        "ttl": ttl_epoch,
        **{k: v for k, v in detail.items()
           if k not in ("customer_id", "timestamp", "event_id")},
    }

    try:
        _table.put_item(Item=item)
        logger.info("DynamoDB write OK event_id=%s customer=%s",
                    event_id, customer_id)
    except Exception as exc:
        logger.error("DynamoDB write FAILED event_id=%s: %s", event_id, exc)
        raise

    return {"status": "ok", "event_id": event_id}
