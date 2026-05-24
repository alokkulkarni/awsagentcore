"""
aria_dtmf_status_proxy.py
══════════════════════════════════════════════════════════════════════════════
DTMF Status Proxy Lambda — Amazon Connect Contact Attribute Reader

PURPOSE
───────
Acts as a thin HTTP proxy between the DTMF CCP Status Panel (served from
CloudFront) and the Amazon Connect contact attribute store.

This Lambda handles two routes:

  GET /dtmf-active
    Returns the currently active DTMF session from DynamoDB.
    Used by the launcher iframe and the status panel popup to auto-discover
    the current contactId without any manual input.
    Response: { "contactId": "<uuid>", "status": "<dtmf_status>" }
              { "contactId": null }   when no active session

  GET /dtmf-status?contactId=<uuid>
    Calls connect:GetContactAttributes and returns the DTMF contact
    attributes as JSON.  The panel polls this endpoint every 2 s once
    it has discovered the contactId.
    Response: { dtmf_status, dtmf_masked, dtmf_card_type, ... }

ENVIRONMENT VARIABLES
─────────────────────
  CONNECT_INSTANCE_ID   Amazon Connect instance UUID (required)
  SESSIONS_TABLE_NAME   DynamoDB active-session table (default: dtmf_active_sessions)
══════════════════════════════════════════════════════════════════════════════
"""
import json
import logging
import os

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

connect_client  = boto3.client("connect",  region_name=REGION, config=_BOTO_CONFIG)
dynamodb        = boto3.resource("dynamodb", region_name=REGION, config=_BOTO_CONFIG)

CORS_HEADERS = {
    "Content-Type":                     "application/json",
    "Access-Control-Allow-Origin":      "*",
    "Access-Control-Allow-Methods":     "GET, OPTIONS",
    "Access-Control-Allow-Headers":     "Content-Type",
}


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers":    CORS_HEADERS,
        "body":       json.dumps(body),
    }


def _handle_active_session() -> dict:
    """GET /dtmf-active — return current active DTMF session from DynamoDB."""
    try:
        table    = dynamodb.Table(SESSIONS_TABLE)
        result   = table.get_item(Key={"session_id": "ACTIVE"})
        item     = result.get("Item")
        if item:
            logger.info(
                "Active session found: contact=%s status=%s",
                item.get("contact_id", ""), item.get("status", ""),
            )
            return _response(200, {
                "contactId": item.get("contact_id", ""),
                "status":    item.get("status",     ""),
            })
        return _response(200, {"contactId": None, "status": ""})
    except ClientError as exc:
        logger.exception("DynamoDB error reading active session")
        return _response(500, {"error": str(exc)})


def _handle_status(contact_id: str) -> dict:
    """GET /dtmf-status?contactId=<id> — return DTMF contact attributes."""
    if not INSTANCE_ID:
        logger.error("CONNECT_INSTANCE_ID environment variable not set")
        return _response(500, {"error": "server misconfiguration"})

    try:
        resp  = connect_client.get_contact_attributes(
            InstanceId=INSTANCE_ID,
            InitialContactId=contact_id,
        )
        attrs = resp.get("Attributes") or {}
        logger.info(
            "get_contact_attributes OK contact=%s dtmf_status=%s",
            contact_id, attrs.get("dtmf_status", ""),
        )
        return _response(200, {
            "dtmf_status":            attrs.get("dtmf_status",            ""),
            "dtmf_masked":            attrs.get("dtmf_masked",            ""),
            "dtmf_card_type":         attrs.get("dtmf_card_type",         ""),
            "dtmf_validation_status": attrs.get("dtmf_validation_status", ""),
            "dtmf_error":             attrs.get("dtmf_error",             ""),
            "collectionPurpose":      attrs.get("collectionPurpose",      ""),
        })

    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "ResourceNotFoundException":
            logger.info("Contact not found: %s", contact_id)
            return _response(404, {"error": "contact_not_found"})
        logger.exception("ClientError fetching attributes for %s", contact_id)
        return _response(500, {"error": str(exc)})

    except Exception as exc:
        logger.exception("Unexpected error fetching attributes for %s", contact_id)
        return _response(500, {"error": str(exc)})


def handler(event, context):
    # Handle CORS pre-flight
    method = (
        event.get("requestContext", {})
             .get("http", {})
             .get("method", "GET")
             .upper()
    )
    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS, "body": ""}

    raw_path = event.get("rawPath", "/dtmf-status")

    if raw_path == "/dtmf-active":
        return _handle_active_session()

    # Default: /dtmf-status
    params     = event.get("queryStringParameters") or {}
    contact_id = params.get("contactId", "").strip()
    if not contact_id:
        return _response(400, {"error": "contactId query parameter is required"})

    return _handle_status(contact_id)
