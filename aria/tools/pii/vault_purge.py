"""Purges all PII vault entries for a session."""

from strands import tool
from aria.tools.pii.vault_store import _VAULT


@tool
def pii_vault_purge(session_id: str, purge_reason: str) -> dict:
    """
    Purges all PII vault entries for the given session.
    Must be called at session end, timeout, security event, or after confirmed escalation handoff.
    Never call this tool before confirming that escalation handoff delivery was accepted or queued.
    purge_reason must be one of: session_end, timeout, security_event, escalation.
    Returns purge_status, session_id, tokens_purged count, and purge_reason for audit logging.
    After a successful purge the vault entries are unrecoverable — ensure all required downstream
    actions (tool calls, handoff) have been completed first.
    """
    tokens_purged = 0
    if session_id in _VAULT:
        tokens_purged = len(_VAULT[session_id].get("entries", {}))
        del _VAULT[session_id]

    return {
        "purge_status": "purged",
        "session_id": session_id,
        "tokens_purged": tokens_purged,
        "purge_reason": purge_reason,
    }
