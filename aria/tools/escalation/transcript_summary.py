"""Generates a structured transcript summary for escalation handoff."""

from datetime import datetime, timezone
from strands import tool
from aria.models.escalation import TranscriptSummaryResponse, TranscriptSummary


@tool
def generate_transcript_summary(
    session_id: str,
    include_vault_refs: bool,
    summary_format: str,
) -> dict:
    """
    Generates a structured summary of the current session for escalation handoff.
    This is the first step in the escalation handoff package compilation — always call this
    before pii_vault_retrieve (purpose: escalation_handoff) and escalate_to_human_agent.
    Uses only vault references in the summary — no raw PII is included.
    summary_format should be 'structured'.
    include_vault_refs should be True when the handoff requires PII to be transmitted
    to the receiving agent (e.g., for identity verification on their side).
    In production this tool reads from the session state store; the stub returns a template
    that should be reviewed and updated with actual session details before handoff.
    """
    # In production this would pull from the session state store
    summary = TranscriptSummary(
        session_id=session_id,
        channel="ivr",
        call_start=datetime.now(timezone.utc).isoformat(),
        auth_status="authenticated",
        auth_method="voice_knowledge_based",
        auth_level="full",
        customer_id="CUST-UNKNOWN",
        query_type="unknown",
        query_detail="Summary generated at time of escalation.",
        actions_taken=[],
        escalation_reason="agent_requested",
        risk_score=10,
        pii_vault_refs={},
    )

    return TranscriptSummaryResponse(summary=summary).model_dump()
