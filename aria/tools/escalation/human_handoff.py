"""Transmits a secure handoff package to the human agent system."""

import uuid
from datetime import datetime
from strands import tool
from aria.models.escalation import EscalateResponse


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
    vulnerability, security_event, tool_failure, out_of_scope_redirect, mortgage_enquiry.
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

    return EscalateResponse(
        handoff_status="accepted",
        agent_id=f"AGT-{uuid.uuid4().hex[:5].upper()}",
        estimated_wait_seconds=30,
        handoff_ref=handoff_ref,
    ).model_dump()
