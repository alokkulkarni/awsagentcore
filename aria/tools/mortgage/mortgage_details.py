"""Retrieves mortgage information for a verified customer."""

from strands import tool
from aria.models.mortgage import MortgageDetailsResponse


@tool
def get_mortgage_details(
    customer_id: str,
    mortgage_reference: str,
    query_subtype: str,
) -> dict:
    """
    Retrieves mortgage information for a verified and authenticated customer.
    mortgage_reference must be retrieved from the PII vault immediately before calling this tool.
    query_subtype must be one of: balance, rate, monthly_payment, overpayment, redemption_statement, term.
    Always confirm the last four characters of the mortgage reference with the customer before
    disclosing any figures — say "I can see a mortgage ending in XXXX, is that correct?".
    Rate switches and remortgage advice are regulated activities — always escalate these requests
    to a qualified mortgage advisor using escalate_to_human_agent with reason: rate_switch_advice.
    Redemption statements are issued via secure email to the registered address only — never
    dictate full redemption figures verbally. Inform the customer the statement will arrive
    within 2 working days.
    Overpayment queries: state the annual allowance and year-to-date used, then advise the
    customer to use the online portal to submit overpayments.
    """
    # TODO: Replace with Meridian Bank mortgage API call
    mort_last_four = mortgage_reference[-4:] if len(mortgage_reference) >= 4 else mortgage_reference

    return MortgageDetailsResponse(
        mortgage_ref_last_four=mort_last_four,
        outstanding_balance=182400.00,
        interest_rate=3.45,
        rate_type="fixed",
        rate_valid_until="2027-10-01",
        monthly_payment=987.50,
        remaining_term_months=264,
        overpayment_allowance_annual=18240.00,
        overpayment_used_ytd=0.00,
        redemption_statement_available=True,
        query_subtype=query_subtype,
        details={
            "property_address_masked": "14 Oak Street, Altrincham",
            "lender": "Meridian Bank",
            "product_name": "2-Year Fixed Rate",
            "redemption_statement_note": "Redemption statement will be sent to your registered email within 2 working days." if query_subtype == "redemption_statement" else None,
        },
    ).model_dump()
