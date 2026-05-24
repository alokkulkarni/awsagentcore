"""
aria_dtmf_start_session.py — DTMF Secure Capture Session Start Lambda
Meridian Bank / ARIA AgentCore

Called from the Amazon Connect flow at the START of the secure DTMF capture
block, BEFORE the customer enters any digits.

This Lambda does two things:
  1. Writes an ACTIVE session record to the dtmf_active_sessions DynamoDB table.
     The launcher iframe (dtmf-launcher/index.html) polls the /dtmf-active API
     endpoint backed by this table. When it detects a new session it brings the
     DTMF status panel popup to the foreground automatically (or opens it if it
     was closed).

  2. Sets dtmf_status = "awaiting_trigger" on the Connect contact attributes so
     the status panel immediately renders the initial waiting state.

Expected event payload (Amazon Connect Lambda block):
{
    "Details": {
        "ContactData": {
            "ContactId":        "<transfer-leg uuid>",
            "InitialContactId": "<original inbound uuid>",
            ...
        },
        "Parameters": {}
    }
}

Returns:
    {"status": "ok"}    on success (or partial success)
    {"status": "failed", "error": "<reason>"}   on hard failure

Environment variables:
    CONNECT_INSTANCE_ID   Amazon Connect instance UUID (required)
    SESSIONS_TABLE_NAME   DynamoDB sessions table (default: dtmf_active_sessions)
    AWS_REGION            Set automatically by Lambda runtime

IAM permissions required:
    connect:UpdateContactAttributes   on the Connect instance
    dynamodb:PutItem                  on dtmf_active_sessions
"""

import logging
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION         = os.environ.get("AWS_REGION",          "eu-west-2")
INSTANCE_ID    = os.environ.get("CONNECT_INSTANCE_ID", "")
SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE_NAME", "dtmf_active_sessions")

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

dynamodb       = boto3.resource("dynamodb", region_name=REGION, config=_BOTO_CONFIG)
connect_client = boto3.client("connect",   region_name=REGION, config=_BOTO_CONFIG)


def handler(event: dict, context) -> dict:
    contact_data = event.get("Details", {}).get("ContactData", {})
    contact_id   = (
        contact_data.get("InitialContactId")
        or contact_data.get("ContactId", "")
    )

    if not contact_id:
        logger.error("No ContactId in Connect event")
        return {"status": "failed", "error": "no_contact_id"}

    logger.info("DTMF session start: contact=%s", contact_id)

    # ── 1. Write ACTIVE session record to DynamoDB ────────────────────────
    try:
        table = dynamodb.Table(SESSIONS_TABLE)
        table.put_item(Item={
            "session_id": "ACTIVE",
            "contact_id": contact_id,
            "status":     "awaiting_trigger",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ttl":        int(time.time()) + 3600,   # auto-expire after 1 h
        })
        logger.info("Session written OK: contact=%s status=awaiting_trigger", contact_id)
    except ClientError as exc:
        # Non-fatal — status attribute push proceeds regardless
        logger.error("Failed to write session record: %s", exc, exc_info=True)

    # ── 2. Set dtmf_status contact attribute ──────────────────────────────
    if not INSTANCE_ID:
        logger.warning("CONNECT_INSTANCE_ID not set — skipping contact attribute update")
        return {"status": "ok"}

    try:
        connect_client.update_contact_attributes(
            InitialContactId=contact_id,
            InstanceId=INSTANCE_ID,
            Attributes={"dtmf_status": "awaiting_trigger"},
        )
        logger.info(
            "Contact attribute set: dtmf_status=awaiting_trigger contact=%s", contact_id
        )
    except Exception as exc:
        logger.warning("Failed to set contact attribute: %s", exc)

    return {"status": "ok"}
