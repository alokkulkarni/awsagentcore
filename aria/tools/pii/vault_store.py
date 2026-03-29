"""Stores PII tokens in the in-memory vault with TTL."""

from datetime import datetime, timedelta, timezone
from strands import tool
from aria.models.pii import PIIVaultStoreResponse

# In-memory vault — replace with AWS Secrets Manager, HashiCorp Vault, etc.
_VAULT: dict[str, dict] = {}


@tool
def pii_vault_store(session_id: str, pii_map: dict, ttl_seconds: int = 900) -> dict:
    """
    Stores PII tokens in the secure vault with a session-scoped TTL.
    Returns vault reference URIs that replace raw PII in the model context.
    Must be called immediately after pii_detect_and_redact when pii_detected is true.
    TTL must not exceed 900 seconds (15 minutes); values above this are capped automatically.
    The returned vault_refs dict maps each token key to a vault:// URI — use these URIs
    anywhere you would otherwise reference raw PII within the session.
    """
    if ttl_seconds > 900:
        ttl_seconds = 900

    expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    vault_refs: dict[str, str] = {}

    if session_id not in _VAULT:
        _VAULT[session_id] = {"entries": {}, "expiry": expiry.isoformat()}

    for token_key, raw_value in pii_map.items():
        vault_ref = f"vault://{session_id}/{token_key}"
        # Write-once per token per session to prevent overwrite attacks
        if token_key not in _VAULT[session_id]["entries"]:
            _VAULT[session_id]["entries"][token_key] = {
                "value": raw_value,
                "expiry": expiry.isoformat(),
            }
        vault_refs[token_key] = vault_ref

    return PIIVaultStoreResponse(
        vault_status="stored",
        vault_refs=vault_refs,
        expiry=expiry.isoformat(),
    ).model_dump()
