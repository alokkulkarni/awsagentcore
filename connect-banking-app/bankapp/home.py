"""
home.py
=======
The internet banking pages' figures, all from the sample bank's one copy of its data
(connect-money-hub/moneyhub/data.py), which ARIA, the Money Hub and the card dispute assistant read too:

    current account   its transactions and balance (the Money Hub's, with the customer's own categories)
    savings           what the current account moves into the saver, on top of its opening balance
    mortgage          the mortgage the current account pays
    cards             the card dispute service's cards and card payments, which come from the same data, so a
                      payment the customer disputes from the Cards page is the one the dispute assistant finds

ALL OF THIS IS FICTIONAL SAMPLE DATA, labelled as such on the page.
"""

from __future__ import annotations

from moneyhub import categories as cat
from moneyhub import data as bank
from moneyhub.service import MoneyHub

try:                                # the dispute service's sample cards, packaged alongside (unchanged)
    import dispute_model
except ImportError:                 # pragma: no cover - running without the dispute code: no cards
    dispute_model = None


def _r(x: float) -> float:
    return round(float(x) + 0.0, 2)


def accounts(hub: MoneyHub, customer_id: str) -> dict:
    """The customer's accounts, as the Home and Accounts pages show them."""
    overview = hub.overview(customer_id)
    current, savings, mortgage = (bank.account(customer_id, "current"), bank.account(customer_id, "savings"),
                                  bank.mortgage(customer_id))
    rows = [{"id": "current", "name": current["name"], "ending": current["ending"],
             "balance": overview["balance"], "kind": "current"}]
    if savings:
        rows.append({"id": "savings", "name": savings["name"], "ending": savings["ending"],
                     "balance": _r(savings["balance"]), "kind": "savings",
                     "note": f"£{overview['averageMonth'].get('movedToSavings', 0):,.0f} a month goes in from your "
                             "current account"})
    if mortgage:
        rows.append({"id": "mortgage", "name": "Mortgage", "ending": mortgage["ending"], "kind": "mortgage",
                     "monthly": _r(mortgage["monthlyPayment"]), "note": "Paid on the 1st of each month"})
    return {"asOf": overview["asOf"], "accounts": rows}


def recent(hub: MoneyHub, customer_id: str, count: int = 6) -> list[dict]:
    """The current account's latest payments, newest first."""
    listed = hub.list_transactions(customer_id, per_page=count)
    return [{"date": t["date"], "merchantName": t["merchantName"], "merchant": t["merchant"], "amount": t["amount"],
             "category": t["categoryWords"], "in": cat.direction(t["category"]) == cat.IN}
            for t in listed["transactions"]]


def cards(customer_id: str) -> dict:
    """The customer's cards and their recent payments (the dispute service's own sample data)."""
    if dispute_model is None:
        return {"cards": [], "payments": []}
    owned = dispute_model.customer_cards(customer_id)
    payments = [{"id": t["transaction_id"], "date": t["date"], "merchant": t["merchant"], "amount": float(t["amount"]),
                 "card": t["card_type"], "ending": t["card_last_four"]}
                for t in dispute_model.card_transactions(customer_id)]
    return {"cards": [{"type": c["card_type"], "ending": c["card_last_four"],
                       "name": "Visa debit card" if c["card_type"] == "debit" else "Credit card"} for c in owned],
            "payments": payments}


def home(hub: MoneyHub, customer_id: str) -> dict:
    """Everything the Home page shows, in one call."""
    summary = accounts(hub, customer_id)
    return {**summary, "recent": recent(hub, customer_id), "firstName": first_name(customer_id),
            "cards": cards(customer_id)["cards"]}


def first_name(customer_id: str) -> str:
    """The customer's preferred name, as ARIA's greeting uses it."""
    return (bank.profile(customer_id) or {}).get("preferredName", "")
