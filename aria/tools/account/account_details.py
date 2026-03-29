"""Retrieves account information for a verified customer."""

from strands import tool
from aria.models.account import AccountDetailsResponse, Transaction


@tool
def get_account_details(
    customer_id: str,
    account_number: str,
    query_subtype: str,
) -> dict:
    """
    Retrieves account information for a verified and authenticated customer.
    account_number must be retrieved from the PII vault immediately before calling this tool —
    never use a raw account number passed directly through the conversation.
    query_subtype must be one of: balance, transactions, statement, standing_orders.
    Returns account balance, recent transactions (max 5 spoken verbally), statement URL, or
    standing orders depending on query_subtype.
    Only the last 4 digits of the account number and last 2 digits of sort code are returned
    in responses — never disclose the full account number or sort code verbally.
    Transactions are read-only — never make or authorise payments via this tool.
    """
    # TODO: Replace with Meridian Bank core banking API call
    acct_last_four = account_number[-4:] if len(account_number) >= 4 else account_number

    stub_transactions = [
        Transaction(date="2026-03-27", description="TESCO STORES", amount=-42.50, type="debit", running_balance=1245.30),
        Transaction(date="2026-03-26", description="SALARY MERIDIAN CORP", amount=3200.00, type="credit", running_balance=1287.80),
        Transaction(date="2026-03-25", description="AMAZON.CO.UK", amount=-89.99, type="debit", running_balance=-1912.20),
        Transaction(date="2026-03-24", description="DIRECT DEBIT - EDF ENERGY", amount=-75.00, type="debit", running_balance=-1747.21),
        Transaction(date="2026-03-23", description="CONTACTLESS - COSTA COFFEE", amount=-4.50, type="debit", running_balance=-1742.71),
    ]

    return AccountDetailsResponse(
        account_number_last_four=acct_last_four,
        sort_code_last_two="67",
        account_type="current",
        available_balance=1245.30,
        cleared_balance=1300.00,
        currency="GBP",
        recent_transactions=stub_transactions if query_subtype == "transactions" else [],
        standing_orders=[
            {"payee": "LANDLORD RENT", "amount": 950.00, "frequency": "monthly", "next_date": "2026-04-01"}
        ] if query_subtype == "standing_orders" else [],
        statement_url=f"https://secure.meridianbank.co.uk/statements/{customer_id}/{acct_last_four}" if query_subtype == "statement" else None,
        query_subtype=query_subtype,
    ).model_dump()
