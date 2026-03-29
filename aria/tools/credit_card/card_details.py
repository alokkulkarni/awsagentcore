"""Retrieves credit card information for a verified customer."""

from strands import tool
from aria.models.cards import CreditCardDetailsResponse, CreditCardTransaction


@tool
def get_credit_card_details(
    customer_id: str,
    card_last_four: str,
    query_subtype: str,
) -> dict:
    """
    Retrieves credit card information for a verified and authenticated customer.
    card_last_four must be retrieved from the PII vault immediately before calling this tool.
    query_subtype must be one of: balance, limit, minimum_payment, statement, interest_rate, dispute.
    State the APR (interest_rate_apr) only when the customer directly asks for it — never volunteer
    it as a selling point or recommendation.
    Never proactively suggest credit limit increases or upsell credit products.
    For disputes: inform the customer that disputes must go to the disputes team and provide
    the reference number from details.dispute_team_ref. Do not promise outcomes or timelines.
    For statement queries: provide the statement_url from details — do not read out transactions
    in full; summarise the three most recent only.
    """
    # TODO: Replace with Meridian Bank credit card API call
    stub_transactions = [
        CreditCardTransaction(date="2026-03-26", description="AMAZON.CO.UK", amount=-129.99, type="debit"),
        CreditCardTransaction(date="2026-03-25", description="PAYMENT RECEIVED - THANK YOU", amount=500.00, type="credit"),
        CreditCardTransaction(date="2026-03-20", description="SAINSBURYS", amount=-67.43, type="debit"),
    ]

    return CreditCardDetailsResponse(
        card_last_four=card_last_four,
        card_status="active",
        credit_limit=5000.00,
        available_credit=3200.00,
        current_balance=1800.00,
        minimum_payment_amount=45.00,
        minimum_payment_due_date="2026-04-14",
        interest_rate_apr=24.9,
        query_subtype=query_subtype,
        details={
            "recent_transactions": [t.model_dump() for t in stub_transactions] if query_subtype in ("statement", "balance") else [],
            "statement_url": f"https://secure.meridianbank.co.uk/credit/{customer_id}/{card_last_four}/statement" if query_subtype == "statement" else None,
            "dispute_team_ref": "0161 900 9001 option 3" if query_subtype == "dispute" else None,
        },
    ).model_dump()
