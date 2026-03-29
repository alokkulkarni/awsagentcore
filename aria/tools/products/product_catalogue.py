"""Meridian Bank product catalogue — returns available products filtered by customer holdings."""

from strands import tool
from aria.models.products import Product, ProductCatalogueResponse

# ---------------------------------------------------------------------------
# Meridian Bank product catalogue
# Each product has a category and sub_category.
# Exclusion logic: if the customer already holds a product with the SAME
# sub_category, it is excluded from results for that category search.
# ---------------------------------------------------------------------------
_CATALOGUE: list[Product] = [

    # ── Current Accounts ────────────────────────────────────────────────────
    Product(
        product_id="CA-STANDARD",
        name="Meridian Current Account",
        category="current_account",
        sub_category="standard",
        tagline="Everyday banking with no monthly fee.",
        key_features=[
            "No monthly fee",
            "Contactless Visa Debit card included",
            "Arranged overdraft available (subject to status)",
            "Mobile and online banking",
            "Access to 3,000+ UK ATMs fee-free",
        ],
        monthly_fee=0.0,
        eligibility="UK resident aged 18+. Subject to credit check.",
        how_to_apply="Apply online, via the app, or in any Meridian Bank branch.",
    ),
    Product(
        product_id="CA-PREMIUM",
        name="Meridian Premium Account",
        category="current_account",
        sub_category="premium",
        tagline="Premium banking with travel insurance, breakdown cover, and more.",
        key_features=[
            "£15/month fee",
            "Worldwide travel insurance included",
            "UK breakdown cover included",
            "Mobile phone insurance included",
            "Higher arranged overdraft limits",
            "Dedicated premium customer support line",
        ],
        monthly_fee=15.0,
        eligibility="UK resident aged 18+. Subject to credit check. Min £1,500/month pay-in.",
        how_to_apply="Apply online, via the app, or in any Meridian Bank branch.",
    ),
    Product(
        product_id="CA-STUDENT",
        name="Meridian Student Account",
        category="current_account",
        sub_category="student",
        tagline="Free banking for full-time students with an interest-free overdraft.",
        key_features=[
            "No monthly fee",
            "0% interest overdraft up to £2,000 (year 1); up to £3,000 (years 2-4)",
            "Student Visa Debit card included",
            "Exclusive student discounts and cashback",
        ],
        monthly_fee=0.0,
        eligibility="UK resident aged 18+ enrolled in a full-time undergraduate or postgraduate degree.",
        how_to_apply="Apply online or visit a branch with your university offer letter or enrolment confirmation.",
    ),

    # ── Savings ─────────────────────────────────────────────────────────────
    Product(
        product_id="SAV-INSTANT",
        name="Meridian Instant Access Saver",
        category="savings",
        sub_category="instant_access",
        tagline="Earn interest on your savings with instant access, any time.",
        key_features=[
            "4.10% AER (variable)",
            "Instant access — withdraw any time with no penalty",
            "No minimum balance",
            "Interest paid monthly",
            "Manage online, in app, or in branch",
        ],
        interest_rate="4.10% AER (variable)",
        min_balance=0.0,
        max_balance=250_000.0,
        monthly_fee=0.0,
        eligibility="Existing Meridian Bank current account holders only.",
        how_to_apply="Open instantly via online banking or the Meridian app.",
    ),
    Product(
        product_id="SAV-FIXED-1YR",
        name="Meridian 1-Year Fixed Rate Bond",
        category="savings",
        sub_category="fixed_rate",
        tagline="Lock in a guaranteed rate for 12 months.",
        key_features=[
            "4.75% AER (fixed for 12 months)",
            "No access to funds during the fixed term",
            "Minimum deposit £1,000",
            "Interest paid at maturity or annually",
        ],
        interest_rate="4.75% AER (fixed)",
        min_balance=1_000.0,
        max_balance=500_000.0,
        monthly_fee=0.0,
        eligibility="UK resident aged 18+. Must have or open a Meridian current account.",
        how_to_apply="Apply online, via the app, or in branch. Funds must be transferred within 14 days.",
    ),
    Product(
        product_id="SAV-FIXED-2YR",
        name="Meridian 2-Year Fixed Rate Bond",
        category="savings",
        sub_category="fixed_rate",
        tagline="Maximise your return with a 2-year fixed rate.",
        key_features=[
            "5.10% AER (fixed for 24 months)",
            "No access to funds during the fixed term",
            "Minimum deposit £1,000",
            "Interest paid annually",
        ],
        interest_rate="5.10% AER (fixed)",
        min_balance=1_000.0,
        max_balance=500_000.0,
        monthly_fee=0.0,
        eligibility="UK resident aged 18+. Must have or open a Meridian current account.",
        how_to_apply="Apply online, via the app, or in branch.",
    ),
    Product(
        product_id="SAV-CASH-ISA",
        name="Meridian Cash ISA",
        category="savings",
        sub_category="cash_isa",
        tagline="Tax-free savings up to your annual ISA allowance.",
        key_features=[
            "4.50% AER (variable)",
            "Tax-free interest — no UK income tax on earnings",
            "Save up to £20,000 per tax year (current allowance)",
            "Instant access with no withdrawal penalty",
            "ISA transfers accepted",
        ],
        interest_rate="4.50% AER (variable, tax-free)",
        min_balance=1.0,
        max_balance=20_000.0,
        monthly_fee=0.0,
        eligibility="UK resident aged 18+.",
        how_to_apply="Open online, via the app, or in branch. Only one Cash ISA per tax year.",
    ),
    Product(
        product_id="SAV-REGULAR",
        name="Meridian Regular Saver",
        category="savings",
        sub_category="regular_saver",
        tagline="Save a fixed amount each month and earn a great rate.",
        key_features=[
            "6.00% AER (fixed for 12 months)",
            "Save £25–£500 per month by standing order",
            "No lump sum deposits",
            "One penalty-free withdrawal per year",
        ],
        interest_rate="6.00% AER (fixed)",
        min_balance=25.0,
        max_balance=6_000.0,
        monthly_fee=0.0,
        eligibility="Must hold a Meridian current account. One Regular Saver per customer.",
        how_to_apply="Apply online or in branch. Set up a standing order from your Meridian current account.",
    ),

    # ── Credit Cards ─────────────────────────────────────────────────────────
    Product(
        product_id="CC-STANDARD",
        name="Meridian Classic Credit Card",
        category="credit_card",
        sub_category="standard",
        tagline="A straightforward credit card with no annual fee.",
        key_features=[
            "No annual fee",
            "0% on purchases for 6 months (then 24.9% APR representative)",
            "Up to 56 days interest-free on purchases",
            "Contactless Mastercard",
        ],
        representative_apr="24.9% APR representative (variable)",
        monthly_fee=0.0,
        eligibility="UK resident aged 18+. Subject to credit check.",
        how_to_apply="Apply online, via the app, or in branch.",
    ),
    Product(
        product_id="CC-REWARDS",
        name="Meridian Rewards Credit Card",
        category="credit_card",
        sub_category="rewards",
        tagline="Earn cashback and travel rewards on every purchase.",
        key_features=[
            "1% cashback on all eligible purchases",
            "Double cashback at partner retailers",
            "No foreign transaction fee",
            "Travel insurance included",
            "£10/month fee (waived with £500+ monthly spend)",
            "27.9% APR representative",
        ],
        representative_apr="27.9% APR representative (variable)",
        monthly_fee=10.0,
        eligibility="UK resident aged 18+. Subject to credit check. Min £10,000 annual income.",
        how_to_apply="Apply online or in branch.",
    ),
    Product(
        product_id="CC-BALANCE-TRANSFER",
        name="Meridian Balance Transfer Card",
        category="credit_card",
        sub_category="balance_transfer",
        tagline="Transfer existing card balances and pay 0% interest for 24 months.",
        key_features=[
            "0% on balance transfers for 24 months (2.5% transfer fee applies)",
            "0% on purchases for 3 months",
            "No annual fee",
            "21.9% APR representative after promotional period",
        ],
        representative_apr="21.9% APR representative (variable)",
        monthly_fee=0.0,
        eligibility="UK resident aged 18+. Subject to credit check. Cannot transfer balances from other Meridian products.",
        how_to_apply="Apply online or in branch.",
    ),

    # ── Mortgages ────────────────────────────────────────────────────────────
    Product(
        product_id="MORT-2YR-FIXED",
        name="Meridian 2-Year Fixed Rate Mortgage",
        category="mortgage",
        sub_category="fixed_rate",
        tagline="Peace of mind with a fixed monthly payment for 2 years.",
        key_features=[
            "3.45% fixed rate for 2 years",
            "Overpay up to 10% per year without early repayment charge",
            "Available for purchase and remortgage",
            "Max 90% LTV",
        ],
        interest_rate="3.45% fixed (2 years)",
        eligibility="UK resident. Subject to full mortgage assessment and affordability checks.",
        how_to_apply="Speak with a Meridian mortgage advisor. Book via branch, online, or phone.",
    ),
    Product(
        product_id="MORT-5YR-FIXED",
        name="Meridian 5-Year Fixed Rate Mortgage",
        category="mortgage",
        sub_category="fixed_rate",
        tagline="Longer-term certainty with a 5-year fixed rate.",
        key_features=[
            "3.89% fixed rate for 5 years",
            "Overpay up to 10% per year without early repayment charge",
            "Available for purchase and remortgage",
            "Max 85% LTV",
        ],
        interest_rate="3.89% fixed (5 years)",
        eligibility="UK resident. Subject to full mortgage assessment and affordability checks.",
        how_to_apply="Speak with a Meridian mortgage advisor. Book via branch, online, or phone.",
    ),
    Product(
        product_id="MORT-TRACKER",
        name="Meridian Tracker Mortgage",
        category="mortgage",
        sub_category="tracker",
        tagline="Track the Bank of England base rate with no early repayment charges.",
        key_features=[
            "Bank of England base rate + 0.99% (currently 5.24%)",
            "No early repayment charges",
            "Unlimited overpayments",
            "Max 80% LTV",
        ],
        interest_rate="Base rate + 0.99% (variable)",
        eligibility="UK resident. Subject to full mortgage assessment and affordability checks.",
        how_to_apply="Speak with a Meridian mortgage advisor. Book via branch, online, or phone.",
    ),
]

# Map category aliases to canonical names
_CATEGORY_ALIASES: dict[str, str] = {
    "savings": "savings",
    "saving": "savings",
    "saver": "savings",
    "current account": "current_account",
    "current_account": "current_account",
    "current accounts": "current_account",
    "account": "current_account",
    "credit card": "credit_card",
    "credit_card": "credit_card",
    "credit cards": "credit_card",
    "mortgage": "mortgage",
    "mortgages": "mortgage",
}


def _held_sub_categories(customer_id: str, category: str) -> set[str]:
    """Return sub_categories already held by the customer in this product category."""
    from aria.tools.customer.customer_details import _CUSTOMER_REGISTRY
    from aria.models.customer import CustomerAccount, CustomerCard

    record = _CUSTOMER_REGISTRY.get(customer_id, {})
    held: set[str] = set()

    if category == "savings":
        # Match account nicknames / types to catalogue sub_categories
        for acc in record.get("accounts", []):
            atype = acc.account_type if isinstance(acc, CustomerAccount) else acc.get("account_type", "")
            if atype == "savings":
                held.add("instant_access")
            elif atype == "isa":
                held.add("cash_isa")
            # Fixed rate bonds and regular savers can't be detected from account type alone —
            # in production this would come from a product-holdings API

    elif category == "current_account":
        for acc in record.get("accounts", []):
            atype = acc.account_type if isinstance(acc, CustomerAccount) else acc.get("account_type", "")
            if atype == "current":
                held.add("standard")  # assume standard unless premium flag set

    elif category == "credit_card":
        for card in record.get("cards", []):
            ctype = card.card_type if isinstance(card, CustomerCard) else card.get("card_type", "")
            nick = card.nickname if isinstance(card, CustomerCard) else card.get("nickname", "")
            if ctype == "credit":
                if nick and "reward" in nick.lower():
                    held.add("rewards")
                elif nick and "balance" in nick.lower():
                    held.add("balance_transfer")
                else:
                    held.add("standard")

    elif category == "mortgage":
        for ref in record.get("mortgage_refs_masked", []):
            held.add("fixed_rate")  # assume fixed unless tracker flag set

    return held


@tool
def get_product_catalogue(customer_id: str, product_category: str) -> dict:
    """
    Returns available Meridian Bank products for a given category, automatically
    excluding products the customer already holds in the same sub-category.

    product_category must be one of: savings, current_account, credit_card, mortgage.
    Common aliases are accepted (e.g. 'saving', 'credit card', 'account').

    Use this tool when:
    - A customer asks "what savings accounts do you offer?"
    - A customer says "I'm looking for a better rate" or "what products do you have?"
    - A customer wants to know what they can apply for

    The response includes:
    - products: list of available products with features and rates (already-held sub-categories excluded)
    - excluded_count: how many were excluded because the customer already holds them
    - excluded_reason: plain-language note on what was excluded

    Present each product by name, tagline, and top 2-3 key features.
    Do NOT quote APR or interest rates as a sales pitch — only state them factually if asked.
    Always close with: "Would you like more details on any of these, or shall I connect you
    with one of our advisors to discuss your options?"
    Mortgage and regulated products must always be referred to a qualified advisor — never
    attempt to advise or recommend a specific mortgage product.
    """
    canonical = _CATEGORY_ALIASES.get(product_category.lower().strip())
    if not canonical:
        return {
            "error": f"Unknown product category '{product_category}'. "
                     "Valid categories: savings, current_account, credit_card, mortgage.",
            "products": [],
            "total_available": 0,
            "excluded_count": 0,
        }

    held_subs = _held_sub_categories(customer_id, canonical)
    all_in_cat = [p for p in _CATALOGUE if p.category == canonical]
    available = [p for p in all_in_cat if p.sub_category not in held_subs]
    excluded_count = len(all_in_cat) - len(available)

    excluded_reason: str | None = None
    if held_subs:
        held_names = [
            p.name for p in all_in_cat if p.sub_category in held_subs
        ]
        if held_names:
            excluded_reason = (
                f"Excluded {excluded_count} product(s) already held: "
                + ", ".join(held_names)
            )

    return ProductCatalogueResponse(
        category=canonical,
        total_available=len(available),
        products=available,
        excluded_count=excluded_count,
        excluded_reason=excluded_reason,
    ).model_dump()
