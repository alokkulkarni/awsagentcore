"""
data.py
=======
Sample current-account transactions for the Money Hub: six months of money in
and money out per test customer, the same every time (seeded), so the page,
the agent and the tests all see identical numbers.

ALL OF THIS IS FICTIONAL TEST DATA. Never put real customer data here.

The account runs from DATA_START to DATA_AS_OF. "Today", for every analysis, is
DATA_AS_OF, so a forecast always looks forward from the end of the data.
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
