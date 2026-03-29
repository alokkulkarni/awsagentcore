"""Retrieves debit card information for a verified customer."""

from strands import tool
from aria.models.cards import DebitCardDetailsResponse


@tool
def get_debit_card_details(
    customer_id: str,
    card_last_four: str,
    query_subtype: str,
) -> dict:
    """
    Retrieves debit card information for a verified and authenticated customer.
    card_last_four must be retrieved from the PII vault immediately before calling this tool.
    query_subtype must be one of: status, block, unblock, limits, lost_stolen, replacement.
    Never return full card numbers, CVV codes, or unmasked expiry dates — only masked data.
    For lost or stolen card requests, direct the customer to confirm before calling block_debit_card.
    For replacement requests where no block is needed, check replacement_available in the response.
    """
    # TODO: Replace with Meridian Bank card management API call
    return DebitCardDetailsResponse(
        card_last_four=card_last_four,
        card_status="active",
        card_type="Visa Debit",
        daily_atm_limit=500.00,
        daily_pos_limit=5000.00,
        expiry_masked="**/**",
        replacement_available=True,
        query_subtype=query_subtype,
        details={
            "registered_address": "14 Oak Street, Altrincham, WA14 1AB",
            "contactless_enabled": True,
            "online_payments_enabled": True,
        },
    ).model_dump()
