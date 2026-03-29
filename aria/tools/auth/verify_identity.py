"""Validates that the authenticated identity matches the requested customer."""

from strands import tool
from aria.models.auth import VerifyIdentityResponse


@tool
def verify_customer_identity(
    header_customer_id: str,
    requested_customer_id: str,
    session_id: str,
) -> dict:
    """
    Validates that the authenticated identity in the request header matches the customer
    whose data is being requested. Called on every interaction before any data access.
    Returns identity_match (bool), risk_score (0-100), and auth_level (full|partial|none).
    If identity_match is false, the session must be terminated immediately — do not proceed
    with any data retrieval or query handling.
    If risk_score > 75, escalate to a human agent immediately regardless of identity_match.
    This tool must be the first tool called when a session begins.
    """
    # TODO: Replace with call to Meridian Bank identity service
    match = header_customer_id.strip() == requested_customer_id.strip()
    risk_score = 10 if match else 90

    return VerifyIdentityResponse(
        identity_match=match,
        risk_score=risk_score,
        auth_level="full" if match else "none",
    ).model_dump()
