"""
Lambda function: EventBridge → CloudTrail Lake
Routes ARIA banking audit events to a CloudTrail Lake channel for immutable,
cryptographically-signed, SQL-queryable compliance storage (7-year retention).

Environment variables:
  CLOUDTRAIL_CHANNEL_ARN  — ARN of the CloudTrail Lake custom channel
  AWS_REGION              — region where the channel lives (default: eu-west-2)
"""

import json
import logging
import os
import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

CHANNEL_ARN = os.environ["CLOUDTRAIL_CHANNEL_ARN"]
_region = os.environ.get("AWS_REGION", "eu-west-2")
_client = boto3.client("cloudtrail-data", region_name=_region)


def handler(event, context):
    detail = event.get("detail", {})
    event_id = detail.get("event_id", context.aws_request_id)

    audit_event = {
        "eventData": json.dumps(detail),
        "id": event_id,
    }

    try:
        _client.put_audit_events(
            auditEvents=[audit_event],
            channelArn=CHANNEL_ARN,
        )
        logger.info("CloudTrail Lake write OK event_id=%s customer=%s",
                    event_id, detail.get("customer_id", "UNKNOWN"))
    except Exception as exc:
        logger.error("CloudTrail Lake write FAILED event_id=%s: %s", event_id, exc)
        raise

    return {"status": "ok", "event_id": event_id}
