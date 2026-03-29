"""Transaction spending insights — categorised analysis across accounts and credit cards."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from strands import tool
from aria.models.analytics import (
    CategorisedTransaction,
    CategorySummary,
    SpendingInsightResponse,
)

# ---------------------------------------------------------------------------
# Category normalisation
# Aliases map customer natural language → canonical category name
# ---------------------------------------------------------------------------
_CATEGORY_ALIASES: dict[str, str] = {
    # Dining / eating out
    "dining": "dining",
    "dining out": "dining",
    "eating out": "dining",
    "eat out": "dining",
    "restaurants": "dining",
    "restaurant": "dining",
    "food": "dining",
    "takeaway": "dining",
    "takeout": "dining",
    "take away": "dining",
    "food delivery": "dining",
    "delivery": "dining",
    "cafe": "dining",
    "coffee": "dining",
    # Groceries
    "groceries": "groceries",
    "grocery": "groceries",
    "supermarket": "groceries",
    "food shopping": "groceries",
    "food shop": "groceries",
    "shopping for food": "groceries",
    # Transport
    "transport": "transport",
    "travel": "transport",
    "commute": "transport",
    "public transport": "transport",
    "taxi": "transport",
    "cab": "transport",
    "trains": "transport",
    "train": "transport",
    "bus": "transport",
    "tube": "transport",
    "underground": "transport",
    "parking": "transport",
    # Shopping / retail
    "shopping": "shopping",
    "retail": "shopping",
    "clothes": "shopping",
    "clothing": "shopping",
    "online shopping": "shopping",
    # Entertainment
    "entertainment": "entertainment",
    "streaming": "entertainment",
    "subscriptions": "entertainment",
    "subscription": "entertainment",
    "cinema": "entertainment",
    "movies": "entertainment",
    "music": "entertainment",
    "gaming": "entertainment",
    # Utilities / bills
    "utilities": "utilities",
    "bills": "utilities",
    "energy": "utilities",
    "electricity": "utilities",
    "gas": "utilities",
    "water": "utilities",
    "broadband": "utilities",
    "internet": "utilities",
    "phone bill": "utilities",
    "mobile bill": "utilities",
    # Health & wellness
    "health": "health",
    "pharmacy": "health",
    "doctor": "health",
    "medical": "health",
    "gym": "health",
    "fitness": "health",
    "wellness": "health",
    # Travel / holidays
    "holiday": "travel",
    "holidays": "travel",
    "flights": "travel",
    "hotel": "travel",
    "hotels": "travel",
    "abroad": "travel",
    "foreign": "travel",
    "holiday spending": "travel",
    # General / other
    "other": "other",
    "miscellaneous": "other",
    "misc": "other",
}


def _normalise_category(raw: str) -> str | None:
    """Return canonical category or None if unrecognised."""
    key = raw.lower().strip()
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    # Partial match for multi-word queries
    for alias, canon in sorted(_CATEGORY_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if alias in key:
            return canon
    return None


# ---------------------------------------------------------------------------
# Stub transaction store
# Keyed by (customer_id, source_type, last_four)
# In production this would be replaced by a core banking API call.
# ---------------------------------------------------------------------------

_TX = CategorisedTransaction   # shorthand

_TRANSACTION_STORE: dict[tuple[str, str, str], list[CategorisedTransaction]] = {

    # CUST-001 | credit card | 2291 — 3 months of transactions
    ("CUST-001", "credit_card", "2291"): [
        # ── January 2026 ──────────────────────────────────────────────────
        _TX(date="2026-01-02", description="WAGAMAMA CANARY WHARF", amount=-32.50, category="dining"),
        _TX(date="2026-01-03", description="DELIVEROO", amount=-18.90, category="dining"),
        _TX(date="2026-01-05", description="AMAZON.CO.UK", amount=-45.99, category="shopping"),
        _TX(date="2026-01-06", description="TESCO STORES", amount=-58.30, category="groceries"),
        _TX(date="2026-01-07", description="SPOTIFY PREMIUM", amount=-9.99, category="entertainment"),
        _TX(date="2026-01-08", description="NANDO'S RESTAURANT", amount=-27.80, category="dining"),
        _TX(date="2026-01-10", description="TFL TRAVEL - CONTACTLESS", amount=-15.60, category="transport"),
        _TX(date="2026-01-11", description="NETFLIX.COM", amount=-15.99, category="entertainment"),
        _TX(date="2026-01-12", description="ZARA UK LTD", amount=-89.00, category="shopping"),
        _TX(date="2026-01-14", description="PRET A MANGER", amount=-8.40, category="dining"),
        _TX(date="2026-01-14", description="PAYMENT RECEIVED - THANK YOU", amount=600.00, category="payment"),
        _TX(date="2026-01-15", description="BOOTS PHARMACY", amount=-22.50, category="health"),
        _TX(date="2026-01-16", description="UBER EATS", amount=-23.45, category="dining"),
        _TX(date="2026-01-17", description="LIDL STORES", amount=-34.20, category="groceries"),
        _TX(date="2026-01-18", description="PURE GYM LTD", amount=-24.99, category="health"),
        _TX(date="2026-01-19", description="DISHOOM KING'S CROSS", amount=-55.00, category="dining"),
        _TX(date="2026-01-20", description="WAITROSE 123", amount=-72.15, category="groceries"),
        _TX(date="2026-01-21", description="ODEON CINEMAS", amount=-29.90, category="entertainment"),
        _TX(date="2026-01-22", description="UBER", amount=-12.80, category="transport"),
        _TX(date="2026-01-24", description="COSTA COFFEE", amount=-6.20, category="dining"),
        _TX(date="2026-01-25", description="BRITISH GAS", amount=-85.00, category="utilities"),
        _TX(date="2026-01-26", description="HONEST BURGERS", amount=-34.00, category="dining"),
        _TX(date="2026-01-28", description="H&M STORES", amount=-45.00, category="shopping"),
        _TX(date="2026-01-29", description="FIVE GUYS UK", amount=-19.75, category="dining"),
        _TX(date="2026-01-30", description="AMAZON.CO.UK", amount=-12.99, category="shopping"),
        # ── February 2026 ─────────────────────────────────────────────────
        _TX(date="2026-02-01", description="ITSU RESTAURANT", amount=-14.50, category="dining"),
        _TX(date="2026-02-02", description="SAINSBURYS", amount=-62.40, category="groceries"),
        _TX(date="2026-02-03", description="DELIVEROO", amount=-21.80, category="dining"),
        _TX(date="2026-02-05", description="TFL TRAVEL - CONTACTLESS", amount=-18.20, category="transport"),
        _TX(date="2026-02-06", description="NATIONAL RAIL ENQUIRIES", amount=-67.50, category="transport"),
        _TX(date="2026-02-07", description="WAGAMAMA SOHO", amount=-41.20, category="dining"),
        _TX(date="2026-02-08", description="PAYMENT RECEIVED - THANK YOU", amount=500.00, category="payment"),
        _TX(date="2026-02-09", description="TESCO STORES", amount=-55.10, category="groceries"),
        _TX(date="2026-02-10", description="JUST EAT", amount=-16.90, category="dining"),
        _TX(date="2026-02-11", description="SPOTIFY PREMIUM", amount=-9.99, category="entertainment"),
        _TX(date="2026-02-12", description="ZARA UK LTD", amount=-120.00, category="shopping"),
        _TX(date="2026-02-13", description="NANDO'S RESTAURANT", amount=-29.60, category="dining"),
        _TX(date="2026-02-14", description="HAWKSMOOR RESTAURANT", amount=-112.00, category="dining"),
        _TX(date="2026-02-15", description="PURE GYM LTD", amount=-24.99, category="health"),
        _TX(date="2026-02-16", description="COSTA COFFEE", amount=-5.90, category="dining"),
        _TX(date="2026-02-17", description="AMAZON.CO.UK", amount=-39.99, category="shopping"),
        _TX(date="2026-02-18", description="PRET A MANGER", amount=-9.10, category="dining"),
        _TX(date="2026-02-19", description="WAITROSE 123", amount=-68.75, category="groceries"),
        _TX(date="2026-02-20", description="ODEON CINEMAS", amount=-14.95, category="entertainment"),
        _TX(date="2026-02-21", description="HONEST BURGERS", amount=-28.50, category="dining"),
        _TX(date="2026-02-22", description="TFL TRAVEL - CONTACTLESS", amount=-14.40, category="transport"),
        _TX(date="2026-02-24", description="UBER EATS", amount=-19.95, category="dining"),
        _TX(date="2026-02-25", description="BRITISH GAS", amount=-85.00, category="utilities"),
        _TX(date="2026-02-26", description="NETFLIX.COM", amount=-15.99, category="entertainment"),
        _TX(date="2026-02-27", description="DISHOOM SHOREDITCH", amount=-78.00, category="dining"),
        _TX(date="2026-02-28", description="BOOTS PHARMACY", amount=-18.75, category="health"),
        # ── March 2026 ────────────────────────────────────────────────────
        _TX(date="2026-03-01", description="ITSU RESTAURANT", amount=-12.80, category="dining"),
        _TX(date="2026-03-02", description="SAINSBURYS", amount=-59.20, category="groceries"),
        _TX(date="2026-03-03", description="DELIVEROO", amount=-24.90, category="dining"),
        _TX(date="2026-03-04", description="TFL TRAVEL - CONTACTLESS", amount=-16.80, category="transport"),
        _TX(date="2026-03-05", description="NANDO'S RESTAURANT", amount=-33.00, category="dining"),
        _TX(date="2026-03-06", description="SPOTIFY PREMIUM", amount=-9.99, category="entertainment"),
        _TX(date="2026-03-07", description="AMAZON.CO.UK", amount=-55.00, category="shopping"),
        _TX(date="2026-03-08", description="WAGAMAMA VICTORIA", amount=-38.50, category="dining"),
        _TX(date="2026-03-09", description="TESCO STORES", amount=-48.90, category="groceries"),
        _TX(date="2026-03-10", description="COSTA COFFEE", amount=-5.50, category="dining"),
        _TX(date="2026-03-11", description="UBER", amount=-9.60, category="transport"),
        _TX(date="2026-03-12", description="JUST EAT", amount=-22.40, category="dining"),
        _TX(date="2026-03-13", description="PURE GYM LTD", amount=-24.99, category="health"),
        _TX(date="2026-03-14", description="NETFLIX.COM", amount=-15.99, category="entertainment"),
        _TX(date="2026-03-15", description="PRET A MANGER", amount=-7.80, category="dining"),
        _TX(date="2026-03-16", description="WAITROSE 123", amount=-71.30, category="groceries"),
        _TX(date="2026-03-17", description="H&M STORES", amount=-65.00, category="shopping"),
        _TX(date="2026-03-18", description="HONEST BURGERS", amount=-31.50, category="dining"),
        _TX(date="2026-03-19", description="BRITISH GAS", amount=-85.00, category="utilities"),
        _TX(date="2026-03-20", description="SAINSBURYS", amount=-67.43, category="groceries"),
        _TX(date="2026-03-21", description="UBER EATS", amount=-17.60, category="dining"),
        _TX(date="2026-03-22", description="TFL TRAVEL - CONTACTLESS", amount=-13.20, category="transport"),
        _TX(date="2026-03-23", description="DISHOOM KING'S CROSS", amount=-66.00, category="dining"),
        _TX(date="2026-03-24", description="ODEON CINEMAS", amount=-22.45, category="entertainment"),
        _TX(date="2026-03-25", description="PAYMENT RECEIVED - THANK YOU", amount=500.00, category="payment"),
        _TX(date="2026-03-26", description="AMAZON.CO.UK", amount=-129.99, category="shopping"),
        _TX(date="2026-03-27", description="PRET A MANGER", amount=-6.90, category="dining"),
    ],

    # CUST-001 | current account | 4821 — 3 months of transactions
    ("CUST-001", "current_account", "4821"): [
        _TX(date="2026-01-01", description="SALARY MERIDIAN CORP", amount=3200.00, category="income"),
        _TX(date="2026-01-02", description="TESCO STORES", amount=-42.50, category="groceries"),
        _TX(date="2026-01-05", description="DIRECT DEBIT - EDF ENERGY", amount=-75.00, category="utilities"),
        _TX(date="2026-01-06", description="DIRECT DEBIT - THAMES WATER", amount=-38.00, category="utilities"),
        _TX(date="2026-01-08", description="STARBUCKS", amount=-5.40, category="dining"),
        _TX(date="2026-01-10", description="DIRECT DEBIT - SKY BROADBAND", amount=-45.00, category="utilities"),
        _TX(date="2026-01-14", description="WAITROSE 123", amount=-61.20, category="groceries"),
        _TX(date="2026-01-15", description="PRET A MANGER", amount=-7.20, category="dining"),
        _TX(date="2026-01-18", description="CONTACTLESS - COSTA COFFEE", amount=-4.50, category="dining"),
        _TX(date="2026-01-20", description="LIDL STORES", amount=-31.80, category="groceries"),
        _TX(date="2026-01-25", description="DIRECT DEBIT - LANDLORD RENT", amount=-950.00, category="utilities"),
        _TX(date="2026-01-28", description="TESCO STORES", amount=-38.90, category="groceries"),
        _TX(date="2026-02-01", description="SALARY MERIDIAN CORP", amount=3200.00, category="income"),
        _TX(date="2026-02-03", description="TESCO STORES", amount=-55.10, category="groceries"),
        _TX(date="2026-02-05", description="DIRECT DEBIT - EDF ENERGY", amount=-75.00, category="utilities"),
        _TX(date="2026-02-10", description="STARBUCKS", amount=-6.10, category="dining"),
        _TX(date="2026-02-12", description="WAITROSE 123", amount=-68.75, category="groceries"),
        _TX(date="2026-02-14", description="DIRECT DEBIT - THAMES WATER", amount=-38.00, category="utilities"),
        _TX(date="2026-02-25", description="DIRECT DEBIT - LANDLORD RENT", amount=-950.00, category="utilities"),
        _TX(date="2026-02-27", description="TESCO STORES", amount=-49.30, category="groceries"),
        _TX(date="2026-03-01", description="SALARY MERIDIAN CORP", amount=3200.00, category="income"),
        _TX(date="2026-03-03", description="TESCO STORES", amount=-42.50, category="groceries"),
        _TX(date="2026-03-05", description="DIRECT DEBIT - EDF ENERGY", amount=-75.00, category="utilities"),
        _TX(date="2026-03-10", description="CONTACTLESS - COSTA COFFEE", amount=-4.50, category="dining"),
        _TX(date="2026-03-14", description="WAITROSE 123", amount=-71.30, category="groceries"),
        _TX(date="2026-03-15", description="DIRECT DEBIT - SKY BROADBAND", amount=-45.00, category="utilities"),
        _TX(date="2026-03-24", description="DIRECT DEBIT - EDF ENERGY", amount=-75.00, category="utilities"),
        _TX(date="2026-03-25", description="DIRECT DEBIT - LANDLORD RENT", amount=-950.00, category="utilities"),
        _TX(date="2026-03-27", description="TESCO STORES", amount=-42.50, category="groceries"),
    ],

    # CUST-002 | current account | 7741 — lighter data set
    ("CUST-002", "current_account", "7741"): [
        _TX(date="2026-02-01", description="SALARY PAYMENT", amount=2400.00, category="income"),
        _TX(date="2026-02-03", description="SAINSBURYS", amount=-45.00, category="groceries"),
        _TX(date="2026-02-07", description="DIRECT DEBIT - EDF ENERGY", amount=-68.00, category="utilities"),
        _TX(date="2026-02-12", description="COSTA COFFEE", amount=-4.80, category="dining"),
        _TX(date="2026-02-15", description="TESCO STORES", amount=-38.50, category="groceries"),
        _TX(date="2026-02-20", description="PRET A MANGER", amount=-6.90, category="dining"),
        _TX(date="2026-02-25", description="DIRECT DEBIT - RENT", amount=-800.00, category="utilities"),
        _TX(date="2026-03-01", description="SALARY PAYMENT", amount=2400.00, category="income"),
        _TX(date="2026-03-04", description="SAINSBURYS", amount=-51.20, category="groceries"),
        _TX(date="2026-03-08", description="DIRECT DEBIT - EDF ENERGY", amount=-68.00, category="utilities"),
        _TX(date="2026-03-12", description="NANDO'S RESTAURANT", amount=-22.50, category="dining"),
        _TX(date="2026-03-18", description="TESCO STORES", amount=-44.80, category="groceries"),
        _TX(date="2026-03-25", description="DIRECT DEBIT - RENT", amount=-800.00, category="utilities"),
    ],
}


def _parse_date(ds: str) -> date:
    return datetime.strptime(ds, "%Y-%m-%d").date()


def _resolve_period(period: str | None, date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Return (from_date, to_date) resolving natural period names or explicit dates."""
    today = date.today()

    if date_from and date_to:
        return _parse_date(date_from), _parse_date(date_to)

    if period:
        p = period.lower().strip()
        if p in ("this_month", "this month"):
            return today.replace(day=1), today
        if p in ("last_month", "last month"):
            first_this = today.replace(day=1)
            last_month_end = first_this - timedelta(days=1)
            return last_month_end.replace(day=1), last_month_end
        months = 2  # default
        m = re.search(r"(\d+)\s*month", p)
        if m:
            months = int(m.group(1))
        from_d = (today.replace(day=1) - timedelta(days=1))
        for _ in range(months - 1):
            from_d = (from_d.replace(day=1) - timedelta(days=1))
        return from_d.replace(day=1), today

    # default: last 2 months
    first_this = today.replace(day=1)
    two_months_ago = (first_this - timedelta(days=1)).replace(day=1)
    return two_months_ago, today


def _find_transactions(
    customer_id: str,
    source_type: str,
    last_four: str,
) -> list[CategorisedTransaction]:
    """Return all transactions for this source; fall back to any matching last_four."""
    direct = _TRANSACTION_STORE.get((customer_id, source_type, last_four))
    if direct:
        return direct
    # Try any source_type with this last_four (in case caller got type slightly wrong)
    for (cid, stype, lf), txs in _TRANSACTION_STORE.items():
        if cid == customer_id and lf == last_four:
            return txs
    return []


@tool
def analyse_spending(
    customer_id: str,
    source_ref_last_four: str,
    source_type: str,
    category_filter: str = "",
    period: str = "last_2_months",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    """
    Analyses spending patterns on a customer's account or credit card.
    Returns categorised transaction totals and individual transactions.

    Use this tool when:
    - Customer asks "how much did I spend on dining / eating out / groceries / transport?"
    - Customer asks "how many times did I eat out last month?"
    - Customer asks to see transactions by category over a period
    - Customer asks for a spending breakdown or summary

    Parameters:
    - source_ref_last_four: last 4 digits of the account or card (from vault or customer profile)
    - source_type: "current_account" or "credit_card"
    - category_filter: optional natural-language category — e.g. "eating out", "dining",
      "groceries", "transport", "shopping", "entertainment", "utilities", "health".
      Leave empty ("") to return ALL categories.
    - period: one of "this_month", "last_month", "last_2_months" (default), "last_3_months",
      "last_6_months". Ignored if date_from and date_to are both provided.
    - date_from / date_to: explicit ISO date strings (YYYY-MM-DD). Optional.

    The response includes:
    - categories: list of CategorySummary objects, each with total_spend, transaction_count,
      largest_transaction, and the individual transactions
    - grand_total_spend: total debits in the period (or in the filtered category)
    - grand_total_credits: total credits (payments, refunds) in the period
    - total_transactions: count of transactions in scope

    How to present results:
    - Lead with the total: "Over the last 2 months, you spent £X across Y transactions on dining."
    - Then list each transaction: date (DD Month YYYY), merchant name, amount in £X.XX format.
    - If there are more than 8 transactions in a category, summarise: list the top 3 largest
      and say "plus X more — full details available in the Meridian Bank app or online banking."
    - Always state the date range covered.
    - For spending totals, use £X.XX numerical format — never spell amounts out as words.
    - Never reveal more than the last 4 digits of any account or card number.
    """
    # Resolve date range
    from_date, to_date = _resolve_period(
        period or None,
        date_from or None,
        date_to or None,
    )

    # Normalise category filter
    canonical_category: str | None = None
    if category_filter and category_filter.strip():
        canonical_category = _normalise_category(category_filter.strip())
        if canonical_category is None:
            return {
                "error": (
                    f"Unrecognised category '{category_filter}'. "
                    "Valid categories: dining, groceries, transport, shopping, entertainment, "
                    "utilities, health, travel, other. Natural language is also accepted: "
                    "'eating out', 'eating out', 'food', 'takeaway', 'coffee', etc."
                ),
                "categories": [],
            }

    # Load and filter transactions
    all_txs = _find_transactions(customer_id, source_type, source_ref_last_four)
    if not all_txs:
        return {
            "error": (
                f"No transaction data found for {source_type} ending {source_ref_last_four}. "
                "Verify the source_type and last four digits are correct."
            ),
            "categories": [],
        }

    in_period = [
        tx for tx in all_txs
        if from_date <= _parse_date(tx.date) <= to_date
    ]

    if canonical_category:
        scoped = [tx for tx in in_period if tx.category == canonical_category]
    else:
        scoped = in_period

    # Aggregate by category
    cat_map: dict[str, list[CategorisedTransaction]] = {}
    for tx in scoped:
        cat_map.setdefault(tx.category, []).append(tx)

    summaries: list[CategorySummary] = []
    grand_spend = 0.0
    grand_credits = 0.0

    for cat, txs in sorted(cat_map.items()):
        debits = [tx for tx in txs if tx.amount < 0]
        credits = [tx for tx in txs if tx.amount >= 0]
        spend = round(sum(abs(tx.amount) for tx in debits), 2)
        grand_spend += spend
        grand_credits += round(sum(tx.amount for tx in credits), 2)
        largest = max((abs(tx.amount) for tx in debits), default=0.0)
        summaries.append(CategorySummary(
            category=cat,
            total_spend=spend,
            transaction_count=len(debits),
            largest_transaction=largest,
            transactions=sorted(txs, key=lambda t: t.date, reverse=True),
        ))

    # Sort by spend descending (most expensive category first)
    summaries.sort(key=lambda s: s.total_spend, reverse=True)

    return SpendingInsightResponse(
        source_ref_last_four=source_ref_last_four,
        source_type=source_type,
        date_from=from_date.isoformat(),
        date_to=to_date.isoformat(),
        category_filter=canonical_category,
        categories=summaries,
        grand_total_spend=round(grand_spend, 2),
        grand_total_credits=round(grand_credits, 2),
        total_transactions=len(scoped),
        note=(
            None if scoped else
            f"No {'categorised' if canonical_category else ''} transactions found in this period "
            f"({from_date} to {to_date})."
        ),
    ).model_dump()
