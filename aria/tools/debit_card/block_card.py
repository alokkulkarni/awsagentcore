"""Blocks a debit card for loss, theft, or suspected fraud."""

import uuid
from strands import tool
from aria.models.cards import BlockDebitCardResponse


@tool
def block_debit_card(
    customer_id: str,
    card_last_four: str,
    reason: str,
    request_replacement: bool = True,
) -> dict:
    """
    Blocks a debit card for a verified customer due to loss, theft, or suspected fraud.
    card_last_four must be retrieved from the PII vault immediately before calling this tool.
    reason must be one of: lost, stolen, fraud.
    IMPORTANT: Always explicitly confirm the intended block action with the customer before
    calling this tool — state the card last four digits and reason, and wait for verbal confirmation.
    This action is irreversible; the card cannot be unblocked once submitted.
    Replacement cards are dispatched to the registered address on file only — never offer or
    arrange delivery to an unverified or newly provided address.
    Returns block_status, replacement_ordered, replacement_eta_days (typically 5), and block_reference.
    Read block_reference back to the customer as a confirmation number.
    """
    # TODO: Replace with Meridian Bank card management API call
    block_ref = f"BLK-{uuid.uuid4().hex[:8].upper()}"

    return BlockDebitCardResponse(
        card_last_four=card_last_four,
        block_status="blocked",
        replacement_ordered=request_replacement,
        replacement_eta_days=5,
        block_reference=block_ref,
    ).model_dump()
