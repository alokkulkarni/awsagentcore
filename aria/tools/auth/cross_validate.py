"""Cross-validates that header, auth-verified, and body customer IDs all match."""

from strands import tool
from aria.models.auth import CrossValidateResponse


@tool
def cross_validate_session_identity(
    header_customer_id: str,
    auth_verified_customer_id: str,
    body_customer_id: str,
    session_id: str,
) -> dict:
    """
    Cross-validates that the header customer ID, the authenticated customer ID, and the body
    customer ID all resolve to the same customer record. This is called after authentication
    succeeds and before any account data is accessed.
    Any mismatch must result in immediate session termination, a security event log, and
    escalation to a human agent with escalation_reason: security_event.
    Returns match_status ('match' or 'mismatch'), the resolved customer_id (only when matched),
    and a list of mismatch_fields identifying which sources disagreed.
    Only proceed with query handling when match_status is 'match'.
    """
    mismatches: list[str] = []
    ids = {
        "header": header_customer_id.strip(),
        "auth_verified": auth_verified_customer_id.strip(),
        "body": body_customer_id.strip(),
    }
    ref = ids["header"]
    for source, cid in ids.items():
        if cid != ref:
            mismatches.append(source)

    match = len(mismatches) == 0

    return CrossValidateResponse(
        match_status="match" if match else "mismatch",
        customer_id=ref if match else "",
        mismatch_fields=mismatches,
    ).model_dump()
