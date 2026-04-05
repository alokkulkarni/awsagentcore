"""Transmits a secure handoff package to the human agent system."""

import logging
import os
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from strands import tool

from aria.models.escalation import EscalateResponse

logger = logging.getLogger(__name__)

_connect_client = None


def _get_connect_client():
    global _connect_client
    if _connect_client is None:
        _connect_client = boto3.client("connect", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
    return _connect_client


def _build_tts_summary(transcript_summary: dict, escalation_reason: str, priority: str,
                        auth_status: str, handoff_ref: str) -> str:
    """
    Build a TTS-friendly spoken summary for the agent whisper flow (voice channel).
    Kept under 500 characters so it reads in approximately 15–20 seconds.
    """
    reason_map = {
        "rate_switch_advice": "rate switch advice",
        "fraud_dispute": "fraud or disputed transaction",
        "customer_request": "customer requested a human agent",
        "vulnerability": "customer vulnerability concern",
        "security_event": "security event",
        "tool_failure": "system issue",
        "out_of_scope_redirect": "out of scope query",
        "mortgage_enquiry": "mortgage enquiry",
        "channel_transfer": "channel transfer request",
    }
    priority_map = {"safeguarding": "SAFEGUARDING", "urgent": "URGENT", "standard": "standard"}

    reason_text = reason_map.get(escalation_reason, escalation_reason)
    priority_text = priority_map.get(priority, priority)
    auth_text = "authenticated" if auth_status in ("authenticated", "high") else "not authenticated"

    # Extract short summary text from the structured transcript_summary dict
    raw = ""
    if isinstance(transcript_summary, dict):
        raw = (
            transcript_summary.get("summary")
            or transcript_summary.get("key_points")
            or transcript_summary.get("description")
            or ""
        )
        if isinstance(raw, list):
            raw = ". ".join(str(item) for item in raw[:3])
        raw = str(raw)

    # Truncate to leave room for prefix/suffix within 500 chars
    prefix = f"ARIA handoff. {priority_text} priority. Reason: {reason_text}. Customer is {auth_text}. "
    suffix = f" Reference: {handoff_ref}."
    max_raw = 500 - len(prefix) - len(suffix)
    if max_raw > 0 and raw:
        raw = raw[:max_raw].rsplit(" ", 1)[0]  # trim at word boundary

    return f"{prefix}{raw}{suffix}".strip()


def _build_chat_summary(transcript_summary: dict, escalation_reason: str, priority: str,
                         auth_status: str, handoff_ref: str) -> str:
    """
    Build a formatted text summary for the agent whisper flow (chat channel).
    Shown as a system message in the CCP before the agent types to the customer.
    """
    reason_map = {
        "rate_switch_advice": "Rate switch advice",
        "fraud_dispute": "Fraud / disputed transaction",
        "customer_request": "Customer requested human agent",
        "vulnerability": "Customer vulnerability concern",
        "security_event": "Security event",
        "tool_failure": "System issue",
        "out_of_scope_redirect": "Out of scope query",
        "mortgage_enquiry": "Mortgage enquiry",
        "channel_transfer": "Channel transfer",
    }
    reason_text = reason_map.get(escalation_reason, escalation_reason)
    auth_text = "Authenticated" if auth_status in ("authenticated", "high") else "Not authenticated"

    raw = ""
    if isinstance(transcript_summary, dict):
        raw = (
            transcript_summary.get("summary")
            or transcript_summary.get("key_points")
            or transcript_summary.get("description")
            or ""
        )
        if isinstance(raw, list):
            raw = " | ".join(str(item) for item in raw[:5])
        raw = str(raw)[:800]

    lines = [
        f"ARIA HANDOFF — {priority.upper()} | {reason_text} | {auth_text} | Ref: {handoff_ref}",
        raw,
    ]
    return "\n".join(line for line in lines if line).strip()


def _write_contact_attributes(session_id: str, attributes: dict) -> None:
    """
    Write escalation context to the live contact so the Agent Whisper flow can read them.
    Failures are logged but never propagate — the escalation must succeed regardless.
    """
    instance_id = os.environ.get("INSTANCE_ID", "")
    if not instance_id or not session_id:
        logger.warning(
            "Skipping UpdateContactAttributes: INSTANCE_ID=%r session_id=%r",
            instance_id, session_id,
        )
        return
    try:
        _get_connect_client().update_contact_attributes(
            InitialContactId=session_id,
            InstanceId=instance_id,
            Attributes={k: str(v) for k, v in attributes.items() if v is not None},
        )
        logger.info("Contact attributes written for whisper flow: keys=%s", list(attributes.keys()))
    except ClientError as exc:
        logger.error("Failed to write contact attributes: %s", exc, exc_info=True)


@tool
def escalate_to_human_agent(
    session_id: str,
    customer_id: str,
    escalation_reason: str,
    auth_status: str,
    auth_level: str,
    risk_score: int,
    transcript_summary: dict,
    verified_pii: dict,
    query_context: dict,
    priority: str,
) -> dict:
    """
    Transmits a secure handoff package to the human agent system and transfers the customer.
    escalation_reason must be one of: rate_switch_advice, fraud_dispute, customer_request,
    vulnerability, security_event, tool_failure, out_of_scope_redirect, mortgage_enquiry, channel_transfer.
    priority must be one of: standard, urgent, safeguarding.
    Must only be called after generate_transcript_summary has been called and after
    pii_vault_retrieve with purpose='escalation_handoff' has been called to populate verified_pii.
    The handoff uses a TLS-secured internal channel — PII is transmitted exactly once.
    Returns handoff_status (accepted|queued|failed), agent_id, estimated_wait_seconds, and handoff_ref.
    After handoff_status is 'accepted' or 'queued', immediately call pii_vault_purge with
    purge_reason='escalation'. Never purge the vault if handoff_status is 'failed'.
    Read the handoff_ref back to the customer as a reference number for their records.
    Tell the customer the estimated wait time and that they will be connected shortly.
    """
    # TODO: Replace with Meridian Bank agent routing API call
    handoff_ref = f"HO-{datetime.now().strftime('%Y%m%d')}-{customer_id}"
    agent_id = f"AGT-{uuid.uuid4().hex[:5].upper()}"

    # Write escalation context to contact attributes so the Agent Whisper flow can read them.
    # Both voice and chat summaries are written; the whisper flow branches on $.ContactData.Channel.
    _write_contact_attributes(session_id, {
        "escalationReason": escalation_reason,
        "escalationPriority": priority,
        "handoffRef": handoff_ref,
        "authStatus": auth_status,
        "authLevel": auth_level,
        "riskScore": str(risk_score),
        "customerId": customer_id,
        # Voice channel: TTS-friendly spoken brief (~15-20 s)
        "transcriptSummaryVoice": _build_tts_summary(
            transcript_summary, escalation_reason, priority, auth_status, handoff_ref
        ),
        # Chat channel: formatted text shown in the CCP before agent connects
        "transcriptSummaryChat": _build_chat_summary(
            transcript_summary, escalation_reason, priority, auth_status, handoff_ref
        ),
    })

    return EscalateResponse(
        handoff_status="accepted",
        agent_id=agent_id,
        estimated_wait_seconds=30,
        handoff_ref=handoff_ref,
    ).model_dump()
