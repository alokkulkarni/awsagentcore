"""
connect_status.py — Real-time status bridge for ARIA tools

Shared utility used by every MCP tool and Lambda that needs to push live
status updates simultaneously to:

  1. The HUMAN AGENT — via connect:UpdateContactAttributes, which refreshes
     the Contact Attributes panel in the agent's CCP in near-real time.

  2. The AI AGENT (ARIA) — by returning rich status data in the tool's own
     return value (retry counts, error codes, step descriptions), which ARIA
     reads and uses to decide what to say to the customer.

USAGE IN A TOOL
---------------
    from aria.tools.connect_status import push_status, make_payment_status

    @tool
    def make_payment(session_id: str, instance_id: str, ...) -> dict:
        contact_id = session_id

        push_status(contact_id, instance_id, {
            "payment_status": "initiating",
            "payment_step":   "Connecting to payment gateway...",
            "payment_retry":  "0",
        })

        for attempt in range(1, MAX_RETRIES + 2):
            try:
                result = call_payment_api(...)
                push_status(contact_id, instance_id, {
                    "payment_status": "authorised",
                    "payment_step":   "Payment authorised",
                    "payment_retry":  str(attempt - 1),
                    "payment_ref":    result["ref"],
                })
                return {**result, "retry_count": attempt - 1}   # ARIA reads this
            except TimeoutError:
                push_status(contact_id, instance_id,
                    make_payment_status("retrying", retry_count=attempt,
                                        retry_reason="Gateway timeout"))
                time.sleep(backoff(attempt))

        push_status(contact_id, instance_id,
            make_payment_status("failed", error_msg="Gateway unavailable after retries"))
        return {"status": "failed", "retry_count": MAX_RETRIES, "error": "..."}

WHY BOTH CHANNELS?
------------------
Human agent:  Is on hold during automated steps (DTMF collection, payment
              processing).  Cannot see raw digits or API details.  Needs a
              running commentary ("Processing payment... Retry 1... Failed:
              Gateway timeout") so they can decide how to help the customer.

AI agent:     Receives status through the tool return value.  Reads retry_count,
              error_code, and step description from the returned dict and uses
              them to explain the situation naturally to the customer without
              making up details.

ENVIRONMENT VARIABLES
---------------------
  INSTANCE_ID  — Amazon Connect instance ID (UUID).  Used as default when
                 the instance_id argument is not passed.
  AWS_REGION   — defaults to eu-west-2.

IAM permission required on every Lambda / tool that calls push_status:
  connect:UpdateContactAttributes  on  arn:aws:connect:<region>:<account>:instance/<id>/*

IMPORTANT — NEVER include PCI data, full card numbers, account numbers, PINs,
passwords, or any other sensitive data in status attribute values.  Status
messages are visible to agents and may be included in Contact Trace Records.
"""

import logging
import os
from typing import Optional

import boto3

logger = logging.getLogger(__name__)

_INSTANCE_ID_ENV = os.environ.get("INSTANCE_ID", "")
_AWS_REGION      = os.environ.get("AWS_REGION", "eu-west-2")
_ATTR_MAX_LEN    = 32_767  # Connect API limit for a single attribute value

_connect_client = None


def _client():
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=_AWS_REGION)
    return _connect_client


# ---------------------------------------------------------------------------
# Core primitive
# ---------------------------------------------------------------------------

def push_status(
    contact_id:  str,
    instance_id: str,
    attributes:  dict,
) -> bool:
    """
    Push key→value status attributes to the active contact.

    Parameters
    ----------
    contact_id  : Connect ContactId.  In ARIA tools this equals session_id.
    instance_id : Connect instance ID (UUID).  Falls back to INSTANCE_ID env var.
    attributes  : Dict of str→str status pairs.  Non-string values are coerced
                  to str and truncated to 32,767 characters.

    Returns True on success.  Never raises — a failed push is logged as a
    warning and execution continues (status updates are non-critical telemetry).
    """
    _instance = instance_id or _INSTANCE_ID_ENV
    if not _instance or not contact_id or contact_id in ("", "unknown", "unknown-session"):
        logger.debug("push_status skipped — missing contact_id or instance_id")
        return False

    safe = {str(k)[:256]: str(v)[:_ATTR_MAX_LEN] for k, v in attributes.items() if k}
    if not safe:
        return False

    try:
        _client().update_contact_attributes(
            InitialContactId=contact_id,
            InstanceId=_instance,
            Attributes=safe,
        )
        logger.debug("Status pushed contact=%s attrs=%s", contact_id, list(safe.keys()))
        return True
    except Exception as exc:
        logger.warning("push_status failed (non-critical) contact=%s: %s", contact_id, exc)
        return False


# ---------------------------------------------------------------------------
# Convenience builders — return a ready-to-push dict of attributes
# ---------------------------------------------------------------------------

def make_payment_status(
    status:           str,
    *,
    step:             str = "",
    error_code:       str = "",
    error_msg:        str = "",
    retry_count:      int = 0,
    retry_reason:     str = "",
    amount_display:   str = "",
    transaction_ref:  str = "",
) -> dict:
    """
    Build a payment status attribute dict.

    status values:
      initiating  — starting the payment process
      authorising — request sent to gateway, awaiting response
      authorised  — payment approved
      declined    — payment declined by issuer
      failed      — terminal failure after all retries
      timeout     — gateway did not respond in time
      retrying    — attempt failed, automatic retry in progress
      cancelled   — payment cancelled before completion

    amount_display: pre-masked display string e.g. "£150.00".  Never include
                    card numbers, account numbers, or raw sensitive values.
    transaction_ref: short reference e.g. "TXN-A1B2C3".  No account numbers.
    """
    attrs: dict = {
        "payment_status":      status,
        "payment_retry_count": str(retry_count),
    }
    if step:            attrs["payment_step"]         = step
    if error_code:      attrs["payment_error_code"]   = error_code
    if error_msg:       attrs["payment_error_msg"]    = error_msg
    if retry_reason:    attrs["payment_retry_reason"] = retry_reason
    if amount_display:  attrs["payment_amount"]       = amount_display
    if transaction_ref: attrs["payment_ref"]          = transaction_ref
    return attrs


def make_api_status(
    api_name:       str,
    status:         str,
    *,
    step:           str = "",
    error_summary:  str = "",
    retry_count:    int = 0,
) -> dict:
    """
    Build a generic API call status attribute dict.

    status values:  calling | success | failed | retrying | timeout | partial
    api_name:       friendly name visible to agents, e.g. "Balance enquiry"
    """
    attrs: dict = {
        "api_last_call":    api_name,
        "api_last_status":  status,
        "api_retry_count":  str(retry_count),
    }
    if step:           attrs["api_step"]          = step
    if error_summary:  attrs["api_error_summary"] = error_summary
    return attrs


def make_dtmf_status(
    status:       str,
    *,
    step:         str = "",
    error_msg:    str = "",
    retry_count:  int = 0,
) -> dict:
    """
    Build a DTMF collection/validation status attribute dict.

    status values:
      waiting_for_input  — customer prompt played, awaiting keypress
      collecting         — customer is entering digits
      processing         — digits captured, calling decrypt Lambda
      validating         — decrypted, calling validation Lambda
      card_validated     — all validation checks passed
      card_invalid       — Luhn check or BIN check failed (format error)
      card_not_yours     — card not registered to this customer
      collection_failed  — customer failed to enter digits after all retries
      system_error       — technical failure in decrypt or validate Lambda
    """
    attrs: dict = {
        "dtmf_status":       status,
        "dtmf_retry_count":  str(retry_count),
    }
    if step:       attrs["dtmf_step"]      = step
    if error_msg:  attrs["dtmf_error_msg"] = error_msg
    return attrs


def make_aria_status(
    status:     str,
    *,
    step:       str = "",
    tool_name:  str = "",
    error_msg:  str = "",
) -> dict:
    """
    Build an ARIA AI processing status attribute dict.

    status values:
      thinking   — AI agent processing the customer's message
      calling    — AI agent is executing a tool / API call
      retrying   — tool call failed, automatic retry in progress
      complete   — AI agent has a response
      error      — AI agent encountered an unrecoverable error
      escalating — AI agent is arranging handoff to human
    """
    attrs: dict = {"aria_status": status}
    if step:       attrs["aria_step"]      = step
    if tool_name:  attrs["aria_tool_name"] = tool_name
    if error_msg:  attrs["aria_error_msg"] = error_msg
    return attrs
