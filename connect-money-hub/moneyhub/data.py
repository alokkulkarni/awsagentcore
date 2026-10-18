"""
data.py
=======
The sample bank's data, the one copy every assistant and page reads, so they all
see the same customer:

    current account   six months of money in and out per test customer, the same
                      every time (seeded): the Money Hub, ARIA's account tools,
                      the internet banking app
    debit card        the current account's card payments (the same rows)
    credit card       its own payments, balance and limit
    customers         names, accounts, cards and mortgages: ARIA's greeting
                      (session injector), ARIA's tools, the card dispute service,
                      the internet banking app

Stdlib only, so any Lambda can carry it: copy moneyhub/__init__.py and this file
into the package and `from moneyhub import data`. Who copies it:
    connect-money-hub (Money Hub page, agent, bridge)   as part of moneyhub/
    connect-banking-app                                  as part of moneyhub/
    connect-card-dispute  aria-card-dispute              deploy_card_dispute.sh
    ARIA's MCP tools      aria-banking-mcp-*-prod        scripts/deploy_mcp_gateway.sh
    session injector      aria-session-injector-qconnect scripts/build_injector_zip.sh

ALL OF THIS IS FICTIONAL TEST DATA. Never put real customer data here.

The account runs from DATA_START to DATA_AS_OF. "Today", for every analysis, is
DATA_AS_OF, so a forecast always looks forward from the end of the data.

Never change generate() or the tables it reads without meaning to move every
figure the Money Hub shows; tests/test_bank_data.py pins them.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

DATA_START = date(2026, 4, 16)
DATA_AS_OF = date(2026, 10, 15)

# Fixed monthly payments and income: (day of month, merchant, category, amount; negative = money out)
_FIXED = {
    "CUST-001": [
        (1, "NATIONWIDE MORTGAGE", "housing", -1050.00),
        (1, "TV LICENCE", "bills", -14.50),
        (2, "PUREGYM", "fitness", -24.99),
        (3, "MANCHESTER CITY COUNCIL TAX", "bills", -168.00),
        (5, "OCTOPUS ENERGY", "bills", -118.00),
        (8, "NETFLIX.COM", "subscriptions", -10.99),
        (9, "AVIVA CAR INSURANCE", "insurance", -61.20),
        (10, "APPLE.COM/BILL ICLOUD", "subscriptions", -2.99),
        (12, "UNITED UTILITIES WATER", "bills", -38.40),
        (14, "AMAZON PRIME", "subscriptions", -8.99),
        (18, "SKY BROADBAND", "bills", -42.00),
        (20, "EE MOBILE", "bills", -28.00),
        (22, "DISNEY PLUS", "subscriptions", -7.99),
        (25, "ACME ENGINEERING LTD SALARY", "salary", 3150.00),
        (26, "TRANSFER TO SAVINGS", "savings", -200.00),
        (27, "SPOTIFY", "subscriptions", -11.99),
    ],
    "CUST-002": [
        (1, "CITY LETTINGS RENT", "housing", -925.00),
        (4, "BRITISH GAS", "bills", -96.00),
        (7, "NETFLIX.COM", "subscriptions", -10.99),
        (15, "VODAFONE", "bills", -22.00),
        (19, "BUPA DENTAL", "insurance", -18.50),
        (28, "NHS TRUST SALARY", "salary", 2480.00),
        (28, "TRANSFER TO SAVINGS", "savings", -100.00),
    ],
}

# Everyday spending: (category, merchants, times a month (low, high), amount (low, high))
_VARIABLE = {
    "CUST-001": [
        ("groceries", ("TESCO STORES", "SAINSBURYS", "ALDI"), (4, 5), (38.0, 96.0)),
        ("coffee", ("PRET A MANGER", "COSTA COFFEE", "STARBUCKS"), (8, 13), (3.10, 5.40)),
        ("takeaways", ("DELIVEROO", "JUST EAT", "UBER EATS"), (3, 6), (17.0, 36.0)),
        ("eating_out", ("NANDOS", "WAGAMAMA", "THE ALBERT PUB"), (2, 4), (24.0, 72.0)),
        ("transport", ("SHELL", "BP"), (2, 3), (52.0, 71.0)),
        ("transport", ("TRAINLINE.COM",), (0, 2), (18.0, 64.0)),
        ("transport", ("UBER TRIP",), (1, 4), (7.5, 21.0)),
        ("shopping", ("AMAZON.CO.UK",), (3, 5), (9.0, 64.0)),
        ("shopping", ("ASOS.COM", "NEXT RETAIL", "ZARA"), (1, 2), (28.0, 92.0)),
        ("entertainment", ("CINEWORLD", "TICKETMASTER", "STEAM GAMES"), (0, 2), (11.0, 58.0)),
        ("cash", ("ATM WITHDRAWAL",), (1, 1), (40.0, 60.0)),
        ("gifts", ("JUSTGIVING", "MOONPIG"), (0, 1), (8.0, 30.0)),
        ("other_income", ("ETSY PAYOUT",), (1, 2), (35.0, 120.0)),
    ],
    "CUST-002": [
        ("groceries", ("LIDL", "CO-OP FOOD"), (4, 5), (28.0, 70.0)),
        ("coffee", ("CAFFE NERO",), (4, 8), (2.90, 4.60)),
        ("takeaways", ("DELIVEROO",), (1, 3), (15.0, 28.0)),
        ("transport", ("TFGM METROLINK",), (6, 10), (2.80, 6.50)),
        ("shopping", ("AMAZON.CO.UK", "PRIMARK"), (2, 4), (8.0, 45.0)),
        ("entertainment", ("ODEON",), (0, 2), (9.0, 22.0)),
    ],
}

# One-off events: (date, merchant, category, amount)
_ONE_OFF = {
    "CUST-001": [
        (date(2026, 7, 3), "EASYJET", "holidays", -238.40),
        (date(2026, 7, 4), "BOOKING.COM", "holidays", -486.00),
        (date(2026, 7, 21), "SPAIN CARD PAYMENTS", "holidays", -164.25),
        (date(2026, 6, 11), "AMAZON.CO.UK REFUND", "refunds", 29.99),
        (date(2026, 8, 30), "HMRC TAX REFUND", "refunds", 142.80),
        (date(2026, 9, 6), "TRANSFER FROM SAVINGS", "transfers_in", 300.00),
        (date(2026, 9, 7), "CURRYS", "shopping", -299.00),
    ],
    "CUST-002": [
        (date(2026, 8, 12), "JET2HOLIDAYS", "holidays", -412.00),
    ],
}

OPENING_BALANCE = {"CUST-001": 1850.00, "CUST-002": 940.00}
CUSTOMERS = tuple(_FIXED)


def _months(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _days_in(year: int, month: int) -> int:
    return ((date(year + (month // 12), month % 12 + 1, 1)) - date(year, month, 1)).days


def generate(customer_id: str) -> list[dict]:
    """Every transaction for the customer, oldest first, with a stable ID and the balance after it."""
    if customer_id not in _FIXED:
        return []
    rng = random.Random(f"moneyhub:{customer_id}")
    rows = []
    for year, month in _months(DATA_START, DATA_AS_OF):
        last = _days_in(year, month)
        for day, merchant, category, amount in _FIXED[customer_id]:
            when = date(year, month, min(day, last))
            if DATA_START <= when <= DATA_AS_OF:
                rows.append((when, merchant, category, amount))
        for category, merchants, (low, high), (a_low, a_high) in _VARIABLE[customer_id]:
            for _ in range(rng.randint(low, high)):
                when = date(year, month, rng.randint(1, last))
                value = round(rng.uniform(a_low, a_high), 2)
                if DATA_START <= when <= DATA_AS_OF:
                    sign = 1 if category in ("other_income", "refunds", "transfers_in", "salary") else -1
                    rows.append((when, rng.choice(merchants), category, sign * value))
    rows += [r for r in _ONE_OFF[customer_id] if DATA_START <= r[0] <= DATA_AS_OF]
    rows.sort(key=lambda r: (r[0], -r[3]))           # money in first on a day, like a statement
    balance = OPENING_BALANCE[customer_id]
    out = []
    for i, (when, merchant, category, amount) in enumerate(rows):
        balance = round(balance + amount, 2)
        out.append({
            "transactionId": f"MH-{customer_id[-3:]}-{when:%Y%m%d}-{i:04d}",
            "date": when.isoformat(), "merchant": merchant, "amount": round(amount, 2),
            "category": category, "balanceAfter": balance,
        })
    return out


def as_of() -> date:
    return DATA_AS_OF


def month_key(day: str) -> str:
    return day[:7]


def add_months(start: date, months: int) -> date:
    year, month = start.year + (start.month - 1 + months) // 12, (start.month - 1 + months) % 12 + 1
    return date(year, month, min(start.day, _days_in(year, month)))


def last_full_months(n: int) -> list[str]:
    """The last n complete months before DATA_AS_OF, oldest first, as 'YYYY-MM'."""
    first_of_this = DATA_AS_OF.replace(day=1)
    keys = []
    cursor = first_of_this - timedelta(days=1)
    for _ in range(n):
        keys.append(f"{cursor:%Y-%m}")
        cursor = cursor.replace(day=1) - timedelta(days=1)
    return list(reversed(keys))


# ── The rest of the bank ─────────────────────────────────────────────────────────────────────────────────────────
# Everything below is read by ARIA, the card dispute service and the internet banking app. Nothing above uses it.

# Who each customer is and what they hold. Card endings are the cards' last four digits; account endings the
# account numbers'. A card's bin is its first six digits (aria-card-bins), which the keypad card check matches with
# the ending. CUST-001 and CUST-002 have a generated current account; the others hold a fixed balance and a fixed
# list of card payments.
SORT_CODE = "07-04-36"
PROFILES: dict[str, dict] = {
    "CUST-001": {
        "preferredName": "James", "fullName": "James Hartley",
        "accounts": [
            {"type": "current", "name": "Current account", "nickname": "Main Account", "ending": "0617"},
            {"type": "savings", "name": "Instant access saver", "nickname": "Holiday Savings", "ending": "3390"},
        ],
        "cards": [
            {"type": "debit", "ending": "4821", "bin": "414900", "scheme": "Visa", "nickname": "Everyday Debit"},
            {"type": "credit", "ending": "2291", "bin": "531908", "scheme": "Mastercard", "nickname": "Rewards Credit Card"},
        ],
    },
    "CUST-002": {
        "preferredName": "Sarah", "fullName": "Sarah Chen",
        "accounts": [{"type": "current", "name": "Current account", "nickname": "Main Account", "ending": "3317"}],
        "cards": [{"type": "debit", "ending": "3317", "bin": "414900", "scheme": "Visa", "nickname": "Everyday Debit"}],
    },
    "CUST-003": {
        "preferredName": "Margaret", "fullName": "Margaret Okonkwo",
        "accounts": [{"type": "current", "name": "Current account", "nickname": "Main Account", "ending": "6612",
                      "balance": 2310.45}],
        "cards": [{"type": "debit", "ending": "6612", "bin": "414900", "scheme": "Visa", "nickname": "Everyday Debit"}],
    },
    "CUST-004": {
        "preferredName": "Daniel", "fullName": "Daniel Walsh",
        "accounts": [{"type": "current", "name": "Current account", "nickname": "Main Account", "ending": "7734",
                      "balance": 640.80}],
        "cards": [{"type": "debit", "ending": "7734", "bin": "543210", "scheme": "Mastercard", "nickname": "Everyday Debit"}],
    },
    "CUST-005": {
        "preferredName": "Ethel", "fullName": "Ethel Parsons",
        "accounts": [
            {"type": "current", "name": "Current account", "nickname": "Main Account", "ending": "1155",
             "balance": 1875.20},
            {"type": "savings", "name": "Savings account", "nickname": "Savings Account", "ending": "8820",
             "balance": 12450.00},
        ],
        "cards": [{"type": "debit", "ending": "1155", "bin": "414900", "scheme": "Visa", "nickname": "Everyday Debit"}],
    },
}

# Mortgages. The monthly payment is the one the current account pays (CUST-001: NATIONWIDE MORTGAGE above).
MORTGAGES: dict[str, dict] = {
    "CUST-001": {"ending": "8842", "outstandingBalance": 210500.00, "monthlyPayment": 1050.00, "interestRate": 4.25,
                 "rateType": "fixed", "rateExpiryDate": "2027-06-30", "termRemainingYears": 18,
                 "nextPaymentDate": "2026-11-01", "propertyMasked": "** Oak Street, Altrincham"},
    "CUST-003": {"ending": "5530", "outstandingBalance": 96200.00, "monthlyPayment": 712.40, "interestRate": 3.89,
                 "rateType": "tracker", "rateExpiryDate": "", "termRemainingYears": 11,
                 "nextPaymentDate": "2026-11-01", "propertyMasked": "** Mill Lane, Bolton"},
}

# The instant access saver: its balance before the data starts, plus what the current account moves into it.
SAVINGS_OPENING = {"CUST-001": 4250.00}

# Card payments are the current account's payments in these categories (never direct debits, salary or transfers).
CARD_CATEGORIES = frozenset({"groceries", "coffee", "takeaways", "eating_out", "transport", "shopping",
                             "entertainment", "gifts", "holidays", "subscriptions"})
CARD_PAYMENTS_SHOWN = 25         # the most recent debit card payments the card tools list

# Customers without a generated current account: their debit card payments, newest first (date, merchant, amount).
_FIXED_CARD_PAYMENTS = (
    ("2026-10-11", "AMAZON.CO.UK", 89.99),
    ("2026-10-10", "TESCO STORES 2041", 42.50),
    ("2026-10-09", "TRAINLINE.COM", 64.20),
    ("2026-10-08", "NETFLIX.COM", 10.99),
    ("2026-10-07", "SHELL MANCHESTER", 55.10),
    ("2026-10-05", "PRET A MANGER", 8.45),
    ("2026-10-03", "ARGOS LTD", 129.99),
    ("2026-10-01", "UBER TRIP", 18.60),
    ("2026-09-29", "SAINSBURYS S/MKT", 63.27),
    ("2026-09-27", "SPOTIFY UK", 11.99),
    ("2026-09-24", "BOOTS 1132", 22.40),
    ("2026-09-20", "ASOS.COM", 74.00),
)

# Credit cards: limit and payments, newest first (date, merchant, amount). The card dispute service's scam and
# retailer scenarios use these payments.
CREDIT_CARDS: dict[str, dict] = {
    "CUST-001": {"limit": 5000.00, "nextPaymentDate": "2026-11-05", "payments": (
        ("2026-10-08", "NETFLIX.COM", 10.99),
        ("2026-10-06", "ELECTROWORLD ONLINE", 349.00),
        ("2026-10-04", "SUNSHINE VILLAS BOOKING", 612.00),
        ("2026-09-30", "BRITISH AIRWAYS", 245.60),
        ("2026-09-22", "JOHN LEWIS", 189.00),
    )},
}


def profile(customer_id: str) -> dict | None:
    return PROFILES.get(customer_id)


def account(customer_id: str, kind: str = "current") -> dict | None:
    """One of the customer's accounts with its balance now, or None."""
    held = next((a for a in (PROFILES.get(customer_id) or {}).get("accounts", []) if a["type"] == kind), None)
    if not held:
        return None
    if kind == "current" and customer_id in _FIXED:
        balance = generate(customer_id)[-1]["balanceAfter"]
    elif kind == "savings" and customer_id in SAVINGS_OPENING:
        moved = sum(-t["amount"] for t in generate(customer_id) if t["category"] == "savings")
        moved -= sum(t["amount"] for t in generate(customer_id) if t["merchant"] == "TRANSFER FROM SAVINGS")
        balance = round(SAVINGS_OPENING[customer_id] + moved + 0.0, 2)
    else:
        balance = held.get("balance", 0.0)
    return {**{k: v for k, v in held.items() if k != "balance"}, "balance": balance}


def card(customer_id: str, kind: str) -> dict | None:
    return next((c for c in (PROFILES.get(customer_id) or {}).get("cards", []) if c["type"] == kind), None)


def owner_of(ending: str) -> tuple[str, dict] | None:
    """(customer, card or account) for a card or account ending, or None. Cards first: a debit card and its
    account can share the digits."""
    for kind in ("cards", "accounts"):
        for customer_id, held in PROFILES.items():
            for item in held.get(kind, []):
                if item["ending"] == str(ending):
                    return customer_id, item
    return None


def held_by(customer_id: str, ending: str) -> dict | None:
    """The customer's own card or account with this ending, or None. Tools answer only for these, so one customer
    can never be shown another's card, account or payments by naming its digits."""
    held = PROFILES.get(customer_id) or {}
    for kind in ("cards", "accounts"):
        for item in held.get(kind, []):
            if item["ending"] == str(ending).strip():
                return item
    return None


def mortgage_reference(customer_id: str) -> str:
    """The masked reference ARIA is given (MR-****-<ending>), or ''."""
    held = MORTGAGES.get(customer_id)
    return f"MR-****-{held['ending']}" if held else ""


def mortgage_owner(reference: str) -> str | None:
    """The customer whose mortgage reference ends with these digits ('MR-****-8842', '8842'), or None."""
    digits = "".join(ch for ch in str(reference) if ch.isdigit())
    return next((c for c, m in MORTGAGES.items() if digits and digits.endswith(m["ending"])), None)


def savings_transactions(customer_id: str) -> list[dict]:
    """The saver's movements, newest first: what the current account moved in, and what came back out."""
    if customer_id not in SAVINGS_OPENING:
        return []
    moves = [{"date": t["date"], "merchant": "FROM CURRENT ACCOUNT", "amount": -t["amount"]}
             for t in generate(customer_id) if t["category"] == "savings"]
    moves += [{"date": t["date"], "merchant": "TO CURRENT ACCOUNT", "amount": -t["amount"]}
              for t in generate(customer_id) if t["merchant"] == "TRANSFER FROM SAVINGS"]
    return sorted(moves, key=lambda t: t["date"], reverse=True)


def current_account_transactions(customer_id: str) -> list[dict]:
    """The current account, newest first: {date, merchant, amount, category, balanceAfter}."""
    if customer_id in _FIXED:
        return list(reversed(generate(customer_id)))
    debit = card(customer_id, "debit")
    if not debit:
        return []
    return [{"date": day, "merchant": merchant, "amount": -amount, "category": "card_payment"}
            for day, merchant, amount in _FIXED_CARD_PAYMENTS]


def card_payments(customer_id: str, kind: str) -> list[dict]:
    """A card's recent payments, newest first, each {transactionId, date, merchant, amount} (amount positive). The
    ids are stable (TXN-<card ending>-<date>-<pence>), so a payment can be named back to start a dispute."""
    held = card(customer_id, kind)
    if not held:
        return []
    if kind == "credit":
        rows = [(d, m, a) for d, m, a in CREDIT_CARDS.get(customer_id, {}).get("payments", ())]
    elif customer_id in _FIXED:
        rows = [(t["date"], t["merchant"], -t["amount"]) for t in reversed(generate(customer_id))
                if t["category"] in CARD_CATEGORIES and t["amount"] < 0][:CARD_PAYMENTS_SHOWN]
    else:
        rows = list(_FIXED_CARD_PAYMENTS)
    return [{"transactionId": f"TXN-{held['ending']}-{d.replace('-', '')}-{round(a * 100)}",
             "date": d, "merchant": m, "amount": round(a, 2)} for d, m, a in rows]


def credit_card(customer_id: str) -> dict | None:
    """The credit card's balance, limit and minimum payment, from its payments."""
    held, terms = card(customer_id, "credit"), CREDIT_CARDS.get(customer_id)
    if not held or not terms:
        return None
    balance = round(sum(a for _, _, a in terms["payments"]), 2)
    return {**held, "limit": terms["limit"], "balance": balance, "available": round(terms["limit"] - balance, 2),
            "minimumPayment": round(max(25.0, balance * 0.03), 2), "nextPaymentDate": terms["nextPaymentDate"]}


def mortgage(customer_id: str) -> dict | None:
    return MORTGAGES.get(customer_id)

