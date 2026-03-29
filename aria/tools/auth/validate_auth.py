"""Validates the customer's knowledge-based authentication credentials."""

from strands import tool
from aria.models.auth import ValidateAuthResponse

# Simple in-memory attempt tracker — replace with real auth service
_auth_attempts: dict[str, int] = {}


@tool
def validate_customer_auth(
    session_id: str,
    customer_id: str,
    dob: str,
    mobile_last_four: str,
    memorable_word: str = None,
) -> dict:
    """
    Validates the customer's knowledge-based authentication credentials.
    dob and mobile_last_four must be retrieved from the PII vault immediately before calling
    this tool — never pass raw values captured directly from the conversation.
    Returns auth_status (success|failed|locked), attempts_remaining (max 3), customer_id_verified,
    and auth_level (full|partial|none).
    On auth_status 'failed' with attempts_remaining of 0, the session must be locked immediately
    and the customer informed they cannot proceed via this channel.
    On auth_status 'locked', escalate to a human agent with reason: security_event.
    Do not reveal which specific credential was incorrect.
    """
    # TODO: Replace with call to Meridian Bank authentication service
    attempts = _auth_attempts.get(session_id, 0)

    if attempts >= 3:
        return ValidateAuthResponse(
            auth_status="locked",
            attempts_remaining=0,
            customer_id_verified="",
            auth_level="none",
        ).model_dump()

    # Stub: treat any non-empty dob + 4-digit mobile as success
    if dob and mobile_last_four and len(mobile_last_four) == 4:
        _auth_attempts.pop(session_id, None)
        return ValidateAuthResponse(
            auth_status="success",
            attempts_remaining=3,
            customer_id_verified=customer_id,
            auth_level="full",
        ).model_dump()
    else:
        _auth_attempts[session_id] = attempts + 1
        remaining = max(0, 3 - _auth_attempts[session_id])
        return ValidateAuthResponse(
            auth_status="failed",
            attempts_remaining=remaining,
            customer_id_verified="",
            auth_level="none",
        ).model_dump()
