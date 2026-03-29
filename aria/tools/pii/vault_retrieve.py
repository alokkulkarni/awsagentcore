"""Retrieves specific PII values from the vault for immediate use."""

from datetime import datetime, timezone
from strands import tool
from aria.models.pii import PIIVaultRetrieveResponse
from aria.tools.pii.vault_store import _VAULT


@tool
def pii_vault_retrieve(session_id: str, vault_refs: list[str], purpose: str) -> dict:
    """
    Retrieves specific PII values from the vault immediately before use in tool calls or responses.
    purpose must be one of: auth_validation, tool_param, spoken_response, escalation_handoff.
    Only retrieve the exact PII tokens required for the immediate action — avoid bulk retrieval.
    Bulk retrieval (all vault refs at once) is only permitted when purpose is escalation_handoff.
    vault_refs is a list of vault:// URIs returned by pii_vault_store.
    Returns resolved_values mapping each vault URI to its original value, and a retrieval_status
    of 'success', 'not_found', or 'expired'. If status is 'expired', the session must be terminated.
    """
    resolved: dict[str, str | None] = {}
    status = "success"
    now = datetime.now(timezone.utc)

    session_data = _VAULT.get(session_id, {})
    entries = session_data.get("entries", {})

    for vault_ref in vault_refs:
        # Extract token key from vault://session_id/TOKEN_KEY
        parts = vault_ref.split("/")
        token_key = parts[-1] if len(parts) >= 2 else vault_ref

        if token_key not in entries:
            status = "not_found"
            resolved[vault_ref] = None
            continue

        entry = entries[token_key]
        expiry = datetime.fromisoformat(entry["expiry"])
        if now > expiry:
            status = "expired"
            resolved[vault_ref] = None
        else:
            resolved[vault_ref] = entry["value"]

    return PIIVaultRetrieveResponse(
        resolved_values=resolved,
        retrieval_status=status,
    ).model_dump()
