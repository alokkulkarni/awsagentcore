"""Initiates an authentication challenge for an unauthenticated customer."""

import uuid
from strands import tool
from aria.models.auth import InitiateAuthResponse


@tool
def initiate_customer_auth(
    customer_id: str,
    auth_method: str,
    channel: str,
    session_id: str,
) -> dict:
    """
    Initiates the authentication flow for an unauthenticated customer.
    auth_method should be 'voice_knowledge_based' for telephone banking.
    channel must be one of: mobile, web, ivr, branch-kiosk.
    Returns an auth_session_id to track this authentication attempt, a challenge_type
    indicating which credentials to collect, and a status of 'initiated'.
    After calling this tool, collect the customer's date of birth and last four digits
    of their registered mobile number, then call validate_customer_auth.
    """
    # TODO: Replace with call to Meridian Bank authentication service
    auth_session_id = str(uuid.uuid4())

    return InitiateAuthResponse(
        auth_session_id=auth_session_id,
        challenge_type="knowledge_based",
        status="initiated",
    ).model_dump()
