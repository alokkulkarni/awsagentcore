"""
service.py
==========
The Money Hub for one customer: their transactions (with the categories they
chose), the analyses, recategorising, savings goals and page links. The agent's
tools, the web page and the gateway tools all go through this, so a rule here
holds whoever is asking.

The customer ID always comes from the caller of these methods: the bridge (from
Connect's record of the contact), or a page link. Never from a language model.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import date, timedelta
from typing import Callable

from . import analysis
from . import categories as cat
from . import data

LINK_SECONDS = 24 * 60 * 60
MAX_GOALS = 5
_GOAL_NAME = re.compile(r"^[\w £&'().,-]{1,40}$")


def goal_date(value: str) -> str:
    """A goal date as YYYY-MM-DD. A month alone (YYYY-MM) means its last day. It must be after today."""
    text = str(value or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", text):
            year, month = map(int, text.split("-"))
            day = data.add_months(date(year, month, 1), 1).replace(day=1) - timedelta(days=1)
        else:
            day = date.fromisoformat(text)
    except (TypeError, ValueError):
        raise MoneyHubError("bad_date", "Give the date as a month and year, for example 2028-03.")
    today = data.as_of()
    if day <= today:
        raise MoneyHubError("date_not_ahead", f"Choose a date after {today.day} {today:%B %Y}, for example "
                                              f"{data.add_months(today, 12):%B %Y}.")
    return day.isoformat()


class MoneyHubError(Exception):
    """A request that was understood and refused. `code` is safe to show and log."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class MoneyHub:
    def __init__(self, store, clock: Callable[[], float], page_url: str = ""):
        self.store, self.clock, self.page_url = store, clock, page_url.rstrip("/")

    # ── transactions ────────────────────────────────────────────────────────────

    def transactions(self, customer_id: str) -> list[dict]:
        """Oldest first, with the customer's own categories applied and readable words."""
        rows = data.generate(customer_id)
        if not rows:
            raise MoneyHubError("customer_not_found", "No Money Hub for this customer.", 404)
        chosen = (self.store.get(f"ovr#{customer_id}") or {}).get("categories") or {}
        out = []
        for t in rows:
            category = chosen.get(t["transactionId"], t["category"])
            out.append({**t, "category": category, "categoryWords": cat.words(category),
                        "direction": cat.direction(category), "merchantName": analysis.friendly(t["merchant"]),
                        "recategorised": t["transactionId"] in chosen})
        return out

    def list_transactions(self, customer_id: str, start: str = "", end: str = "", category: str = "",
                          direction: str = "", merchant: str = "", page: int = 1, per_page: int = 10) -> dict:
        """Newest first, filtered, one page at a time."""
        rows = [t for t in reversed(self.transactions(customer_id))
                if (not start or t["date"] >= start) and (not end or t["date"] <= end)
                and (not category or t["category"] == category) and (not direction or t["direction"] == direction)
                and (not merchant or merchant.lower() in t["merchant"].lower())]
        per_page = max(1, min(int(per_page or 10), 50))
        pages = max(1, -(-len(rows) // per_page))
        page = max(1, int(page or 1))
        return {"transactions": rows[(page - 1) * per_page: page * per_page], "page": page, "totalPages": pages,
                "total": len(rows), "hasMore": page < pages}

    def recategorise(self, customer_id: str, transaction_id: str, category: str, who: str) -> dict:
        """Put one transaction in another category. Money in stays money in, money out stays money out."""
        rows = {t["transactionId"]: t for t in data.generate(customer_id)}
        if transaction_id not in rows:
            raise MoneyHubError("transaction_not_found", "That transaction isn't on this account.", 404)
        if category not in cat.CATEGORIES:
            raise MoneyHubError("unknown_category", "Choose one of: " + ", ".join(cat.CATEGORIES) + ".")
        if not cat.allowed_move(rows[transaction_id]["category"], category):
            raise MoneyHubError("wrong_direction", "Money in can only go in a money-in category, and money out "
                                                   "in a money-out one.")
        key = f"ovr#{customer_id}"
        item = self.store.get(key) or {"categories": {}, "history": []}
        if category == rows[transaction_id]["category"]:
            item["categories"].pop(transaction_id, None)          # back to the bank's own category
        else:
            item["categories"][transaction_id] = category
        item["history"] = (item.get("history") or [])[-49:] + [
            {"transactionId": transaction_id, "category": category, "by": who, "at": int(self.clock())}]
        self.store.put(key, item)
        changed = next(t for t in self.transactions(customer_id) if t["transactionId"] == transaction_id)
        return {"transaction": changed}

    # ── analyses ────────────────────────────────────────────────────────────────

    def overview(self, customer_id: str) -> dict:
        return analysis.overview(self.transactions(customer_id))

    def spending(self, customer_id: str, period: str = "last_3_months", direction: str = cat.OUT) -> dict:
        start, end = analysis.period_bounds(period)
        rows = analysis.in_period(self.transactions(customer_id), start, end)
        return {"period": period, "from": start, "to": end, "categories": analysis.by_category(rows, direction)}

    def recurring(self, customer_id: str) -> list[dict]:
        return analysis.recurring(self.transactions(customer_id))

    def forecast(self, customer_id: str, months: int = 3) -> dict:
        return analysis.forecast(self.transactions(customer_id), max(1, min(int(months or 3), 6)))

    def discretionary(self, customer_id: str) -> dict:
        return analysis.discretionary(self.transactions(customer_id))

    def goal_plan(self, customer_id: str, target: float, months: int | None = None, saved: float = 0.0,
                  by_date: str = "") -> dict:
        if not (0 < float(target) <= 1_000_000):
            raise MoneyHubError("bad_target", "The target must be an amount of money above zero.")
        by_date = goal_date(by_date) if by_date else ""
        return analysis.goal_plan(self.transactions(customer_id), float(target), months, float(saved or 0), by_date)

    def compare(self, customer_id: str, month_a: str, month_b: str) -> dict:
        return analysis.compare(self.transactions(customer_id), month_a, month_b)

    # ── savings goals ───────────────────────────────────────────────────────────

    def goals(self, customer_id: str) -> list[dict]:
        return (self.store.get(f"goals#{customer_id}") or {}).get("goals") or []

    def save_goal(self, customer_id: str, name: str, target: float, by_date: str, saved: float = 0.0) -> dict:
        name = " ".join(str(name or "").split())
        if not _GOAL_NAME.match(name):
            raise MoneyHubError("bad_name", "Give the goal a short name, up to 40 letters.")
        by_date = goal_date(by_date)
        plan = self.goal_plan(customer_id, target, by_date=by_date, saved=saved)
        goals = [g for g in self.goals(customer_id) if g["name"].lower() != name.lower()]
        if len(goals) >= MAX_GOALS:
            raise MoneyHubError("too_many_goals", f"Up to {MAX_GOALS} goals can be saved.")
        goal = {"name": name, "target": plan["target"], "byDate": by_date, "saved": plan["alreadySaved"],
                "neededPerMonth": plan["neededPerMonth"], "onTrack": plan["onTrack"]}
        self.store.put(f"goals#{customer_id}", {"goals": goals + [goal]})
        return {"goal": goal, "plan": plan}

    def delete_goal(self, customer_id: str, name: str) -> dict:
        goals = [g for g in self.goals(customer_id) if g["name"].lower() != str(name).lower()]
        self.store.put(f"goals#{customer_id}", {"goals": goals})
        return {"goals": goals}

    # ── page links ──────────────────────────────────────────────────────────────

    def mint_link(self, customer_id: str, loa: str = "", expires: bool = True) -> str:
        """A link to this customer's Money Hub page. The secret is after '#', so it never reaches a server log.
        loa is the assurance level of the contact that asked for the link ("" when none, as for a demo link);
        a call or chat started from the page is treated as verified only when it is 2 or above.
        expires=False makes a link that never expires: for the demo link to the sample data only."""
        if not data.generate(customer_id):
            raise MoneyHubError("customer_not_found", "No Money Hub for this customer.", 404)
        token = secrets.token_urlsafe(32)
        level = str(loa).strip()
        item = {"customerId": customer_id, "loa": level if level.isdigit() else ""}
        if expires:
            item["expiresAt"] = self.clock() + LINK_SECONDS
        self.store.put(f"link#{_hash(token)}", item)
        return f"{self.page_url}/#k={token}"

    def link_session(self, token: str) -> dict:
        """{customerId, loa} for a live page link."""
        item = self.store.get(f"link#{_hash(token)}") if token else None
        if not item:
            raise MoneyHubError("link_expired", "This link has expired. Ask for a new one.", 403)
        return {"customerId": item["customerId"], "loa": str(item.get("loa") or "")}

    def customer_of_link(self, token: str) -> str:
        return self.link_session(token)["customerId"]

    def goals_with_plans(self, customer_id: str) -> list[dict]:
        """Each saved goal with its plan today (the same sums the agent explains), for the page's goal details."""
        out = []
        for goal in self.goals(customer_id):
            try:
                plan = self.goal_plan(customer_id, goal["target"], by_date=goal["byDate"], saved=goal.get("saved", 0))
            except MoneyHubError:                       # the date has passed
                out.append({**goal, "plan": None})
                continue
            out.append({**goal, "plan": {
                k: plan[k] for k in ("months", "neededPerMonth", "leftOverPerMonth", "alreadyMovingToSavings",
                                     "gapPerMonth", "onTrack", "reachedAtCurrentRate", "reachedWithMix",
                                     "mixSavesPerMonth", "targetDateWords")}
                | {"changes": [{"change": m["change"], "savesPerMonth": m["savesPerMonth"]}
                               for m in plan["illustrativeMix"][:4]]}})
        return out

    def page_view(self, customer_id: str) -> dict:
        """Everything the page shows on load, in one call."""
        return {"overview": self.overview(customer_id), "forecast": self.forecast(customer_id),
                "monthlySpending": analysis.monthly_spending(self.transactions(customer_id)),
                "monthlyIncome": analysis.monthly_income(self.transactions(customer_id)),
                "recurring": self.recurring(customer_id), "discretionary": self.discretionary(customer_id),
                "goals": self.goals_with_plans(customer_id),
                "choices": {"in": cat.choices_for(cat.IN), "out": cat.choices_for(cat.OUT) + cat.choices_for(cat.MOVE)}}
