"""Fetches the customer profile for a verified customer ID."""

from strands import tool
from aria.models.customer import (
    CustomerDetailsResponse,
    CustomerAccount,
    CustomerCard,
    VulnerabilityFlag,
)

# Stub customer registry — replace with Meridian Bank CRM / core banking API call.
_CUSTOMER_REGISTRY: dict[str, dict] = {
    "CUST-001": {
        "first_name": "James",
        "last_name": "Hartley",
        "preferred_name": "James",
        "email_masked": "j***@email.com",
        "mobile_last_four": "7741",
        "registered_address_masked": "14 Oak Street, Altrincham",
        "customer_since_year": 2015,
        "status": "active",
        "accounts": [
            CustomerAccount(
                account_number_masked="****4821",
                account_type="current",
                nickname="Main Account",
                sort_code_masked="20-**-67",
                is_primary=True,
            ),
            CustomerAccount(
                account_number_masked="****9104",
                account_type="savings",
                nickname="Holiday Savings",
                sort_code_masked="20-**-67",
                is_primary=False,
            ),
        ],
        "cards": [
            CustomerCard(
                card_last_four="4821",
                card_type="debit",
                card_scheme="Visa",
                nickname="Everyday Debit",
                status="active",
                linked_account_masked="****4821",
            ),
            CustomerCard(
                card_last_four="2291",
                card_type="credit",
                card_scheme="Mastercard",
                nickname="Rewards Credit Card",
                status="active",
                linked_account_masked=None,
            ),
        ],
        "mortgage_refs_masked": ["MR-****-GB"],
        "vulnerability": None,
    },
    "CUST-002": {
        "first_name": "Sarah",
        "last_name": "Chen",
        "preferred_name": "Sarah",
        "email_masked": "s***@email.com",
        "mobile_last_four": "4492",
        "registered_address_masked": "8 Birch Lane, Manchester",
        "customer_since_year": 2021,
        "status": "active",
        "accounts": [
            CustomerAccount(
                account_number_masked="****3317",
                account_type="current",
                nickname="Main Account",
                sort_code_masked="20-**-12",
                is_primary=True,
            ),
        ],
        "cards": [
            CustomerCard(
                card_last_four="3317",
                card_type="debit",
                card_scheme="Visa",
                nickname="Everyday Debit",
                status="active",
                linked_account_masked="****3317",
            ),
        ],
        "mortgage_refs_masked": [],
        "vulnerability": VulnerabilityFlag(
            flag_type="financial_difficulty",
            requires_extra_time=True,
            requires_simplified_language=True,
            refer_to_specialist=True,
            suppress_promotion=True,
            suppress_collections=True,
            debt_signpost=True,
        ),
    },
    "CUST-003": {
        "first_name": "Margaret",
        "last_name": "Okonkwo",
        "preferred_name": "Margaret",
        "email_masked": "m***@email.com",
        "mobile_last_four": "8812",
        "registered_address_masked": "22 Elm Close, Birmingham",
        "customer_since_year": 2008,
        "status": "active",
        "accounts": [
            CustomerAccount(
                account_number_masked="****6612",
                account_type="current",
                nickname="Main Account",
                sort_code_masked="20-**-44",
                is_primary=True,
            ),
        ],
        "cards": [
            CustomerCard(
                card_last_four="6612",
                card_type="debit",
                card_scheme="Visa",
                nickname="Everyday Debit",
                status="active",
                linked_account_masked="****6612",
            ),
        ],
        "mortgage_refs_masked": ["MR-****-BM"],
        "vulnerability": VulnerabilityFlag(
            flag_type="bereavement",
            requires_extra_time=True,
            requires_simplified_language=True,
            refer_to_specialist=False,
            suppress_promotion=True,
            suppress_collections=False,
            debt_signpost=False,
        ),
    },
    "CUST-004": {
        "first_name": "Daniel",
        "last_name": "Walsh",
        "preferred_name": "Daniel",
        "email_masked": "d***@email.com",
        "mobile_last_four": "5503",
        "registered_address_masked": "5 Rosewood Avenue, Leeds",
        "customer_since_year": 2019,
        "status": "active",
        "accounts": [
            CustomerAccount(
                account_number_masked="****7734",
                account_type="current",
                nickname="Main Account",
                sort_code_masked="20-**-55",
                is_primary=True,
            ),
        ],
        "cards": [
            CustomerCard(
                card_last_four="7734",
                card_type="debit",
                card_scheme="Mastercard",
                nickname="Everyday Debit",
                status="active",
                linked_account_masked="****7734",
            ),
        ],
        "mortgage_refs_masked": [],
        "vulnerability": VulnerabilityFlag(
            flag_type="mental_health",
            requires_extra_time=True,
            requires_simplified_language=True,
            refer_to_specialist=True,
            suppress_promotion=True,
            suppress_collections=True,
            debt_signpost=False,
        ),
    },
    "CUST-005": {
        "first_name": "Ethel",
        "last_name": "Parsons",
        "preferred_name": "Ethel",
        "email_masked": "e***@email.com",
        "mobile_last_four": "2209",
        "registered_address_masked": "3 Hawthorn Road, Bristol",
        "customer_since_year": 2003,
        "status": "active",
        "accounts": [
            CustomerAccount(
                account_number_masked="****1155",
                account_type="current",
                nickname="Main Account",
                sort_code_masked="20-**-77",
                is_primary=True,
            ),
            CustomerAccount(
                account_number_masked="****8820",
                account_type="savings",
                nickname="Savings Account",
                sort_code_masked="20-**-77",
                is_primary=False,
            ),
        ],
        "cards": [
            CustomerCard(
                card_last_four="1155",
                card_type="debit",
                card_scheme="Visa",
                nickname="Everyday Debit",
                status="active",
                linked_account_masked="****1155",
            ),
        ],
        "mortgage_refs_masked": [],
        "vulnerability": VulnerabilityFlag(
            flag_type="elderly",
            requires_extra_time=True,
            requires_simplified_language=True,
            refer_to_specialist=False,
            suppress_promotion=True,
            suppress_collections=False,
            debt_signpost=False,
        ),
    },
}


@tool
def get_customer_details(customer_id: str) -> dict:
    """
    Fetches the full customer profile and 360-degree product view for a verified customer.
    Must only be called after the customer is authenticated (auth_level: full) or when
    X-Channel-Auth is 'authenticated' at session start.

    Returns:
    - preferred_name: use this when addressing the customer in all responses
    - accounts: list of all accounts with masked numbers, types, and nicknames
    - cards: list of all debit and credit cards with last four digits and nicknames
    - mortgage_refs_masked: list of masked mortgage references
    - vulnerability: if present, adjust communication style accordingly —
        requires_extra_time: allow more pauses, do not rush
        requires_simplified_language: use plain simple language, avoid jargon
        refer_to_specialist: warm-transfer directly to specialist team at session start (no asking)
        suppress_promotion: never upsell, cross-sell, or mention rate switches
        suppress_collections: never mention arrears, overdue balances, or request payments
        debt_signpost: proactively mention StepChange, MoneyHelper, Citizens Advice once

    When the customer asks about a product (e.g. 'my account balance', 'my card'):
    - If they have exactly one matching product: use it directly without asking
    - If they have multiple: present the options using nickname and masked number/last-four,
      and ask which one they mean before calling any data tool
    """
    record = _CUSTOMER_REGISTRY.get(customer_id)

    if not record:
        return CustomerDetailsResponse(
            customer_id=customer_id,
            first_name="",
            last_name="",
            full_name="",
            preferred_name="",
            email_masked="",
            mobile_last_four="",
            registered_address_masked="",
            customer_since_year=0,
            status="not_found",
            accounts=[],
            cards=[],
            mortgage_refs_masked=[],
            vulnerability=None,
        ).model_dump()

    full_name = f"{record['first_name']} {record['last_name']}"
    return CustomerDetailsResponse(
        customer_id=customer_id,
        first_name=record["first_name"],
        last_name=record["last_name"],
        full_name=full_name,
        preferred_name=record["preferred_name"],
        email_masked=record["email_masked"],
        mobile_last_four=record["mobile_last_four"],
        registered_address_masked=record["registered_address_masked"],
        customer_since_year=record["customer_since_year"],
        status=record["status"],
        accounts=record["accounts"],
        cards=record["cards"],
        mortgage_refs_masked=record["mortgage_refs_masked"],
        vulnerability=record["vulnerability"],
    ).model_dump()
