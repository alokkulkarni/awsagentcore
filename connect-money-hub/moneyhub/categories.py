"""
categories.py
=============
The categories a transaction can be in, which way the money goes, and whether
the spending is essential or discretionary. "Discretionary" is the spending a
customer could choose to change; it is what a savings plan can flex. It is a
label for explaining, never a judgement about the customer.
"""

from __future__ import annotations

IN, OUT, MOVE = "in", "out", "move"     # MOVE: the customer's own money moving (to savings), not spending

# name: (direction, discretionary, words)
CATEGORIES: dict[str, tuple[str, bool, str]] = {
    "salary":        (IN, False, "Salary"),
    "other_income":  (IN, False, "Other income"),
    "refunds":       (IN, False, "Refunds"),
    "transfers_in":  (IN, False, "Transfers in"),
    "housing":       (OUT, False, "Mortgage or rent"),
    "bills":         (OUT, False, "Bills and utilities"),
    "insurance":     (OUT, False, "Insurance"),
    "groceries":     (OUT, False, "Groceries"),
    "transport":     (OUT, False, "Transport"),
    "subscriptions": (OUT, True, "Subscriptions"),
    "eating_out":    (OUT, True, "Eating out"),
    "takeaways":     (OUT, True, "Takeaways"),
    "coffee":        (OUT, True, "Coffee and snacks"),
    "shopping":      (OUT, True, "Shopping"),
    "entertainment": (OUT, True, "Entertainment"),
    "holidays":      (OUT, True, "Holidays and travel"),
    "fitness":       (OUT, True, "Health and fitness"),
    "gifts":         (OUT, True, "Gifts and charity"),
    "cash":          (OUT, False, "Cash withdrawals"),
    "savings":       (MOVE, False, "Moved to savings"),
}


def direction(category: str) -> str:
    return CATEGORIES[category][0]


def is_discretionary(category: str) -> bool:
    return CATEGORIES[category][1]


def words(category: str) -> str:
    return CATEGORIES[category][2]


def choices_for(dir_: str) -> list[dict]:
    """The categories a transaction going this way can be moved to, for the page and the agent."""
    return [{"category": name, "words": w} for name, (d, _, w) in CATEGORIES.items() if d == dir_]


def allowed_move(old: str, new: str) -> bool:
    """Money in stays money in and money out stays money out; a transfer to savings can be relabelled as spending."""
    if new not in CATEGORIES:
        return False
    a, b = direction(old), direction(new)
    return a == b or {a, b} == {OUT, MOVE}
