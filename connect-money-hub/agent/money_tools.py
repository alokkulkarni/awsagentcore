"""
money_tools.py
==============
The Money Hub agent's own tools, as plain Python functions, built per
conversation with the customer bound in (build_tools). The model chooses which
tool to call and with what question; it can never choose whose money it sees.

Every number comes from moneyhub (analysis.py): the tools return figures, the
model explains them. Replies are trimmed to what the model needs, to keep turns
fast on a phone call.

main.py wraps these with Strands' @tool. They are plain functions so they can be
tested without Strands installed.
"""

from __future__ import annotations

import json
import time
from typing import Callable

from moneyhub import categories as cat
from moneyhub.service import MoneyHub, MoneyHubError


class Recorder:
    """What happened on this turn: each tool call with its timing (for Connect's trace) and any hand-back."""

    def __init__(self):
        self.calls: list[dict] = []
        self.finish: dict | None = None

    def wrap(self, fn: Callable) -> Callable:
        def run(*args, **kwargs):
            start = time.time_ns()
            ok = True
            try:
                result = fn(*args, **kwargs)
            except MoneyHubError as error:
                ok, result = False, {"ok": False, "reason": error.code, "message": error.message}
            except (ValueError, TypeError) as error:
                ok, result = False, {"ok": False, "reason": "invalid_input", "message": str(error)}
            self.calls.append({"name": fn.__name__, "input": json.dumps(kwargs or list(args), default=str)[:1000],
                               "output": json.dumps(result, default=str)[:1500], "ok": ok,
                               "startNs": start, "endNs": time.time_ns()})
            return result
        run.__name__, run.__doc__ = fn.__name__, fn.__doc__
        run.__annotations__ = getattr(fn, "__annotations__", {})
        run.__wrapped__ = fn
        return run


def _slim(t: dict) -> dict:
    return {"id": t["transactionId"], "date": t["date"], "merchant": t["merchantName"], "amount": t["amount"],
            "category": t["categoryWords"]}


def build_tools(hub: MoneyHub, customer_id: str, channel: str, recorder: Recorder, loa: str = "") -> list[Callable]:
    """The tools for one conversation, with the customer bound in. Each records its call on the recorder.
    loa is the contact's assurance level, recorded on any page link minted here."""

    def get_money_overview() -> dict:
        """The customer's current account balance today (currentBalance: what's in the account now, the figure
        their Money Hub page shows as Balance), money in and money out this month so far, the last three complete
        months, the monthly average (leftOver is per month, not a balance), and their biggest spending categories
        (per month, on average). Start here for "how am I doing" and for "how much have I got"."""
        o = hub.overview(customer_id)
        months = max(1, len(o["months"]))

        def plain(m: dict) -> dict:
            # One meaning of "left over" everywhere (the page, goals): money in minus money out. What they move
            # to savings comes out of it, so it's shown as part of it, never taken off again.
            return {**{k: m[k] for k in ("moneyIn", "moneyOut") if k in m},
                    "leftOver": round(m.get("moneyIn", 0) - m.get("moneyOut", 0), 2),
                    "ofWhichMovedToSavings": m.get("movedToSavings", 0), **({"month": m["month"]} if "month" in m else {})}
        return {"asOf": o["asOf"], "currentBalance": o["balance"], "thisMonthSoFar": plain(o["thisMonthSoFar"]),
                "lastThreeMonths": [plain(m) for m in o["months"]], "averageMonth": plain(o["averageMonth"]),
                "topSpendingPerMonth": [{"words": c["words"], "perMonth": round(c["total"] / months, 2),
                                         "share": c["share"], "discretionary": c["discretionary"]}
                                        for c in o["topSpending"]],
                "moneyInPerMonth": [{"words": c["words"], "perMonth": round(c["total"] / months, 2)}
                                    for c in o["moneyInSources"]]}

    def get_spending_by_category(period: str = "last_3_months", money: str = "out") -> dict:
        """Spending (or income) by category for a period, as an amount per month (on average, for periods of
        several months) and the total for the period. period: this_month, last_month, last_3_months or
        last_6_months. money: out (spending) or in (income)."""
        result = hub.spending(customer_id, period, cat.IN if money == "in" else cat.OUT)
        months = {"last_3_months": 3, "last_6_months": 6}.get(period, 1)
        result["monthsInPeriod"] = months
        result["categories"] = [{"words": c["words"], "category": c["category"],
                                 "perMonth": round(c["total"] / months, 2), "totalForPeriod": c["total"],
                                 "count": c["count"], "share": c["share"], "discretionary": c["discretionary"]}
                                for c in result["categories"]]
        return result

    def find_transactions(category: str = "", merchant: str = "", period: str = "", money: str = "",
                          page: int = 1) -> dict:
        """The customer's transactions, newest first, ten at a time. Narrow by category (e.g. coffee, takeaways),
        merchant name, period (this_month, last_month, last_3_months, last_6_months) or money (in or out).
        page 2, 3 and so on for older ones."""
        start, end = ("", "")
        if period:
            from moneyhub.analysis import period_bounds
            start, end = period_bounds(period)
        listed = hub.list_transactions(customer_id, start, end, category, {"in": cat.IN, "out": cat.OUT}.get(money, ""),
                                       merchant, page, 10)
        return {**{k: listed[k] for k in ("page", "totalPages", "total", "hasMore")},
                "transactions": [_slim(t) for t in listed["transactions"]],
                "totalAmount": round(sum(t["amount"] for t in listed["transactions"]), 2)}

    def get_regular_payments() -> dict:
        """Payments and income that come about every month: salary, mortgage or rent, bills, subscriptions,
        transfers to savings. With the usual amount and when the next one is expected."""
        rows = hub.recurring(customer_id)
        return {"regular": [{k: r[k] for k in ("merchant", "words", "direction", "amount", "nextExpected",
                                               "discretionary")} for r in rows],
                "subscriptionsPerMonth": round(sum(r["amount"] for r in rows if r["category"] == "subscriptions"), 2)}

    def get_expected_months(months: int = 3) -> dict:
        """The months ahead (1 to 6): expected money in, regular payments with dates, everyday spending at its
        recent average, and the balance at each month end. An estimate from past patterns, not a promise."""
        f = hub.forecast(customer_id, months)
        return {"startBalance": f["startBalance"], "basis": f["basis"], "months": [
            {"month": m["month"], "expectedIn": m["expectedIn"], "expectedOut": m["expectedOut"],
             "endBalance": m["endBalance"],
             "regularOut": [{k: e[k] for k in ("merchant", "amount", "date")} for e in m["regularOut"]],
             "everydaySpending": m["everydaySpending"]} for m in f["months"]]}

    def get_spending_habits() -> dict:
        """Essential versus discretionary spending per month, and habits: how often and how much each time
        (e.g. coffee 11 times a month at £4 each), with the top places. Use for "where does my money go"."""
        d = hub.discretionary(customer_id)
        return {**{k: d[k] for k in ("months", "essentialPerMonth", "discretionaryPerMonth", "discretionaryShare")},
                "habits": [{k: h[k] for k in ("words", "discretionary", "perMonth", "timesPerMonth", "averageEach",
                                              "topMerchants")} for h in d["habits"]]}

    def get_financial_picture() -> dict:
        """The customer's whole money picture in one call: balance now; each of the last three months (money in,
        money out, left over, and oneOffs: the big one-off spending that made a month stand out); a typical month;
        bills and essentials against spending they choose; regular payments; the months ahead (lookingAhead:
        expected left over and the lowest month-end balance); and every saved goal with what it needs a month
        (perMonth) and whether it's on track. freeEachMonth is the typical month's left over less what their saved
        goals need now. Use it before suggesting a new goal or how much they could put aside, and for
        "how am I doing" or "can I afford…"."""
        return hub.financial_picture(customer_id)

    def plan_savings_goal(target_amount: float, target_date: str = "", months: int = 0,
                          already_saved: float = 0.0, name: str = "") -> dict:
        """What reaching a savings target takes, from the customer's own figures: the monthly amount needed, what
        is left over now, the gap, and illustrative changes to discretionary spending (with how much each frees
        up) that would close it. target_date as YYYY-MM (a month) or YYYY-MM-DD, or months. The result gives
        today, targetDateWords, and when they'd reach it at their current rate (reachedAtCurrentRate) and with the
        changes (reachedWithMix), as dates in words: use those dates, never work dates out yourself. These are
        illustrations, never advice. already_saved: only what they say they've put aside for this goal (not
        their balance); 0 if they haven't said.
        The plan already allows for their other saved goals: otherGoals (each needs its perMonth every month from
        now until its byDateWords, at the same time as this one), otherGoalsPerMonthNow, and freeForThisGoalPerMonth (what's free for this goal on average once the
        others have theirs; the gap is against this). It also gives recentMonths (with oneOffs) and lookingAhead
        to say how steady that is. wouldLeaveShort lists saved goals that are on track now but wouldn't be with
        this one too. name: only when re-planning one of their saved goals (so it isn't counted
        against itself)."""
        return hub.goal_plan(customer_id, float(target_amount), int(months) or None, float(already_saved or 0),
                             target_date or "", name=name or "")

    def save_savings_goal(name: str, target_amount: float, target_date: str, already_saved: float = 0.0) -> dict:
        """Save a savings goal to the customer's Money Hub, so it shows on their page. Only when they ask.
        target_date as YYYY-MM (a month; saved as its last day) or YYYY-MM-DD, after today. To save it for when
        they'd reach it, use the date in reachedWithMix (or reachedAtCurrentRate) from plan_savings_goal.
        already_saved is only money the customer says they've already put aside for this goal; never their
        account balance. 0 if they haven't said."""
        goal = hub.save_goal(customer_id, name, float(target_amount), target_date, float(already_saved or 0))["goal"]
        return {"saved": True, "goal": goal, "goalsNow": [g["name"] for g in hub.goals(customer_id)],
                "whereToSee": "the Goals tab of their Money Hub page (it updates while you talk)"}

    def compare_months(month_a: str, month_b: str) -> dict:
        """Spending by category in two months (YYYY-MM), and what changed most."""
        c = hub.compare(customer_id, month_a, month_b)
        c["rows"] = c["rows"][:8]
        return c

    def recategorise_transaction(transaction_id: str, category: str) -> dict:
        return {"ok": True, "transaction": _slim(hub.recategorise(customer_id, transaction_id, category, "agent")
                                                 ["transaction"])}

    recategorise_transaction.__doc__ = (
        "Move one transaction (its id from find_transactions) to another category, when the customer asks. "
        "category is one of: " + ", ".join(cat.CATEGORIES) + ". Money in stays money in; money out stays money out.")

    def get_money_hub_link() -> dict:
        """A link to the customer's Money Hub page, where they can see all of this and change categories."""
        if channel != "CHAT":
            return {"link": "", "message": "On a phone call there is no way to send the link. Say they can ask for it "
                                           "in a chat with us."}
        return {"link": hub.mint_link(customer_id, loa), "message": "Post the link exactly as given, on its own line."}

    def hand_back(outcome: str, reason: str) -> dict:
        """Hand the conversation back to ARIA. outcome: complete (their Money Hub questions are answered, or they
        asked about something else) or escalate (they want a person, ask for financial advice or show signs of
        vulnerability or financial difficulty). reason: one or two sentences for ARIA, including what they want next;
        start it "Finished:" if they said they need nothing else at all."""
        recorder.finish = {"type": "ESCALATE" if outcome.lower().startswith("esc") else "COMPLETE",
                           "reason": " ".join(str(reason).split())[:500] or "Money Hub conversation finished."}
        return {"ok": True, "message": "Say one short sentence, not a goodbye (ARIA closes), without saying you are "
                                       "transferring."}

    tools = [get_money_overview, get_financial_picture, get_spending_by_category, find_transactions, get_regular_payments,
             get_expected_months, get_spending_habits, plan_savings_goal, save_savings_goal, compare_months,
             recategorise_transaction, get_money_hub_link, hand_back]
    return [recorder.wrap(t) for t in tools]
