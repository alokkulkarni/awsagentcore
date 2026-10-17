"""
analysis.py
===========
Every number the Money Hub shows or the agent says is worked out here, from the
transactions, so the page and the agent always agree and a language model never
does the arithmetic. The agent explains these results; it does not recompute them.

All amounts are pounds, rounded to pence. Money out is reported as a positive
"spent" figure. "Spending" excludes money the customer moved to their own savings.
"""

from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, pstdev

from . import categories as cat
from .data import add_months, as_of, last_full_months, month_key


def friendly(merchant: str) -> str:
    """'APPLE.COM/BILL ICLOUD' -> 'Apple iCloud'-style names for speaking and showing."""
    name = merchant.replace(".COM/BILL", "").replace(".CO.UK", "").replace(".COM", "").title()
    return name.replace("Icloud", "iCloud").replace("Ee ", "EE ")


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def _spent(t: dict) -> float:
    return -t["amount"] if cat.direction(t["category"]) == cat.OUT else 0.0


def _received(t: dict) -> float:
    return t["amount"] if cat.direction(t["category"]) == cat.IN else 0.0


def in_period(transactions: list[dict], start: str = "", end: str = "") -> list[dict]:
    return [t for t in transactions if (not start or t["date"] >= start) and (not end or t["date"] <= end)]


def month_summary(transactions: list[dict], month: str) -> dict:
    rows = [t for t in transactions if month_key(t["date"]) == month]
    money_in = sum(_received(t) for t in rows)
    money_out = sum(_spent(t) for t in rows)
    saved = sum(-t["amount"] for t in rows if cat.direction(t["category"]) == cat.MOVE)
    return {"month": month, "moneyIn": _r(money_in), "moneyOut": _r(money_out), "movedToSavings": _r(saved),
            "net": _r(money_in - money_out - saved), "transactions": len(rows)}


def by_category(transactions: list[dict], direction: str = cat.OUT) -> list[dict]:
    """Totals per category for these transactions, largest first."""
    totals, counts = defaultdict(float), defaultdict(int)
    for t in transactions:
        if cat.direction(t["category"]) == direction:
            totals[t["category"]] += abs(t["amount"])
            counts[t["category"]] += 1
    grand = sum(totals.values()) or 1.0
    return sorted(({"category": c, "words": cat.words(c), "total": _r(v), "count": counts[c],
                    "share": round(100 * v / grand), "discretionary": cat.is_discretionary(c)}
                   for c, v in totals.items()), key=lambda row: -row["total"])


def overview(transactions: list[dict], months: int = 3) -> dict:
    """The current balance, this month so far, and the last few complete months."""
    keys = last_full_months(months)
    this_month = f"{as_of():%Y-%m}"
    window = [t for t in transactions if month_key(t["date"]) in keys]
    summaries = [month_summary(transactions, k) for k in keys]
    return {
        "asOf": as_of().isoformat(),
        "balance": transactions[-1]["balanceAfter"] if transactions else 0.0,
        "thisMonthSoFar": month_summary(transactions, this_month),
        "months": summaries,
        "averageMonth": {k: _r(mean(s[k] for s in summaries)) for k in ("moneyIn", "moneyOut", "movedToSavings", "net")}
                        if summaries else {},
        "topSpending": by_category(window)[:6],
        "moneyInSources": by_category(window, cat.IN),
    }


def monthly_spending(transactions: list[dict], months: int = 3) -> list[dict]:
    """Money out in each of the last few complete months: the total, essentials and spending they choose,
    and each category, so the page can show real months rather than an average."""
    out = []
    for key in last_full_months(months):
        rows = by_category([t for t in transactions if month_key(t["date"]) == key])
        flexible = sum(r["total"] for r in rows if r["discretionary"])
        total = sum(r["total"] for r in rows)
        out.append({"month": key, "total": _r(total), "discretionary": _r(flexible), "essential": _r(total - flexible),
                    "categories": rows})
    return out


def monthly_income(transactions: list[dict], months: int = 3) -> list[dict]:
    """Money in for each of the last few complete months: the total, salary and everything else, and each
    source, so the page can show real months rather than an average."""
    out = []
    for key in last_full_months(months):
        rows = by_category([t for t in transactions if month_key(t["date"]) == key], cat.IN)
        salary = sum(r["total"] for r in rows if r["category"] == "salary")
        total = sum(r["total"] for r in rows)
        out.append({"month": key, "total": _r(total), "salary": _r(salary), "other": _r(total - salary),
                    "categories": rows})
    return out


def recurring(transactions: list[dict]) -> list[dict]:
    """
    Payments and income that arrive about monthly for a similar amount: subscriptions,
    direct debits, salary. Three or more, 25 to 35 days apart, amounts within 15%.
    """
    groups = defaultdict(list)
    for t in transactions:
        groups[(t["merchant"], t["category"])].append(t)
    found = []
    for (merchant, category), rows in groups.items():
        if len(rows) < 3:
            continue
        days = [date.fromisoformat(r["date"]) for r in rows]
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        amounts = [abs(r["amount"]) for r in rows]
        if not all(25 <= g <= 35 for g in gaps) or pstdev(amounts) > 0.15 * mean(amounts):
            continue
        last = days[-1]
        found.append({
            "merchant": merchant, "merchantName": friendly(merchant), "category": category, "words": cat.words(category),
            "direction": cat.direction(category), "amount": _r(mean(amounts)),
            "dayOfMonth": round(mean(d.day for d in days)), "lastPaid": last.isoformat(),
            "nextExpected": add_months(last, 1).isoformat(), "discretionary": cat.is_discretionary(category),
        })
    return sorted(found, key=lambda r: (r["direction"] != cat.IN, -r["amount"]))


def forecast(transactions: list[dict], months: int = 3) -> dict:
    """
    The expected next few months: recurring payments and income on their usual day,
    plus everyday spending at its recent monthly average, and the balance that leaves.
    An estimate from past patterns, not a promise.
    """
    regular = recurring(transactions)
    regular_keys = {(r["merchant"], r["category"]) for r in regular}
    recent = last_full_months(3)
    everyday = defaultdict(float)
    for t in transactions:
        if month_key(t["date"]) in recent and (t["merchant"], t["category"]) not in regular_keys:
            if cat.direction(t["category"]) == cat.OUT and t["category"] != "holidays":
                everyday[t["category"]] += _spent(t) / len(recent)
            elif cat.direction(t["category"]) == cat.IN and t["category"] == "other_income":
                everyday[t["category"]] -= t["amount"] / len(recent)       # negative = money in
    balance = transactions[-1]["balanceAfter"] if transactions else 0.0
    start = as_of().replace(day=1)
    out = []
    for n in range(1, months + 1):
        month = add_months(start, n)
        key = f"{month:%Y-%m}"
        last_day = calendar.monthrange(month.year, month.month)[1]

        def on(r: dict) -> str:          # its usual day, or the month's last day if the month is shorter
            return f"{key}-{min(int(r['dayOfMonth']), last_day):02d}"
        expected_in = [{"merchant": r["merchant"], "merchantName": friendly(r["merchant"]), "words": r["words"],
                        "category": r["category"], "amount": r["amount"], "date": on(r)}
                       for r in regular if r["direction"] == cat.IN]
        expected_out = [{"merchant": r["merchant"], "merchantName": friendly(r["merchant"]), "words": r["words"],
                         "category": r["category"], "amount": r["amount"], "date": on(r)}
                        for r in regular if r["direction"] in (cat.OUT, cat.MOVE)]
        variable = {c: _r(v) for c, v in everyday.items() if v > 0}
        side_income = _r(-everyday.get("other_income", 0.0))
        money_in = sum(e["amount"] for e in expected_in) + side_income
        money_out = sum(e["amount"] for e in expected_out) + sum(variable.values())
        balance = balance + money_in - money_out
        out.append({"month": key, "expectedIn": _r(money_in), "expectedOut": _r(money_out),
                    "regularIn": sorted(expected_in, key=lambda e: e["date"]),
                    "regularOut": sorted(expected_out, key=lambda e: e["date"]),
                    "everydaySpending": [{"category": c, "words": cat.words(c), "amount": v}
                                         for c, v in sorted(variable.items(), key=lambda kv: -kv[1])],
                    "sideIncome": side_income, "endBalance": _r(balance)})
    return {"asOf": as_of().isoformat(), "startBalance": transactions[-1]["balanceAfter"] if transactions else 0.0,
            "months": out, "basis": "Regular payments on their usual day; everyday spending at its average for "
                                    f"{recent[0]} to {recent[-1]}; one-off holidays left out."}


def discretionary(transactions: list[dict], months: int = 3) -> dict:
    """Essential and discretionary spending per month on average, with habits: how often, how much each time."""
    keys = last_full_months(months)
    window = [t for t in transactions if month_key(t["date"]) in keys and cat.direction(t["category"]) == cat.OUT]
    per_cat = defaultdict(lambda: {"total": 0.0, "count": 0, "merchants": defaultdict(float)})
    for t in window:
        row = per_cat[t["category"]]
        row["total"] += _spent(t)
        row["count"] += 1
        row["merchants"][t["merchant"]] += _spent(t)
    habits = []
    for c, row in per_cat.items():
        habits.append({
            "category": c, "words": cat.words(c), "discretionary": cat.is_discretionary(c),
            "perMonth": _r(row["total"] / len(keys)), "timesPerMonth": round(row["count"] / len(keys), 1),
            "averageEach": _r(row["total"] / row["count"]),
            "topMerchants": [{"merchant": m, "perMonth": _r(v / len(keys))}
                             for m, v in sorted(row["merchants"].items(), key=lambda kv: -kv[1])[:3]],
        })
    habits.sort(key=lambda h: -h["perMonth"])
    essential = sum(h["perMonth"] for h in habits if not h["discretionary"])
    flexible = sum(h["perMonth"] for h in habits if h["discretionary"])
    return {"months": keys, "essentialPerMonth": _r(essential), "discretionaryPerMonth": _r(flexible),
            "discretionaryShare": round(100 * flexible / ((essential + flexible) or 1)),
            "habits": habits}


def month_words(day: date) -> str:
    """'March 2028': how a person says a goal date."""
    return day.strftime("%B %Y")


def goal_commitments(goals: list[dict], exclude: str = "") -> list[dict]:
    """The customer's other saved goals that are still ahead, with what each needs a month from now to its date."""
    today = as_of()
    out = []
    for g in goals:
        if exclude and g["name"].lower() == exclude.lower():
            continue
        end = date.fromisoformat(g["byDate"])
        months = (end.year - today.year) * 12 + end.month - today.month
        remaining = max(0.0, float(g["target"]) - float(g.get("saved") or 0))
        if months < 1 or remaining <= 0:
            continue
        out.append({"name": g["name"], "target": _r(float(g["target"])), "byDate": g["byDate"],
                    "byDateWords": month_words(end), "months": months, "perMonth": _r(remaining / months)})
    return out


def one_offs(transactions: list[dict], key: str, minimum: float = 150.0) -> list[dict]:
    """Big spending in a month that isn't a regular payment (a holiday, a new TV): why one month can look unlike
    the others."""
    regular = {(r["merchant"], r["category"]) for r in recurring(transactions)}
    rows = [t for t in transactions if month_key(t["date"]) == key and cat.direction(t["category"]) == cat.OUT
            and (t["merchant"], t["category"]) not in regular and _spent(t) >= minimum]
    return [{"merchantName": friendly(t["merchant"]), "words": cat.words(t["category"]), "amount": _r(_spent(t)),
             "date": t["date"]} for t in sorted(rows, key=_spent, reverse=True)[:3]]


def recent_months(transactions: list[dict], months: int = 3) -> list[dict]:
    """Each recent complete month: money in, money out, what was left over (and of it, moved to savings), and the
    one-off spending that explains a month that stands out."""
    out = []
    for key in last_full_months(months):
        m = month_summary(transactions, key)
        out.append({"month": key, "moneyIn": m["moneyIn"], "moneyOut": m["moneyOut"],
                    "leftOver": _r(m["moneyIn"] - m["moneyOut"]), "ofWhichMovedToSavings": m["movedToSavings"],
                    "oneOffs": one_offs(transactions, key)})
    return out


def looking_ahead(transactions: list[dict], months: int = 3) -> dict:
    """The months ahead in brief: what's expected to be left over each month and the lowest month-end balance."""
    f = forecast(transactions, months)
    rows = [{"month": m["month"], "expectedIn": m["expectedIn"], "expectedOut": m["expectedOut"],
             "expectedLeftOver": _r(m["expectedIn"] - m["expectedOut"]), "endBalance": m["endBalance"]}
            for m in f["months"]]
    lowest = min(rows, key=lambda r: r["endBalance"]) if rows else None
    return {"months": rows, "expectedLeftOverPerMonth": _r(mean(r["expectedLeftOver"] for r in rows)) if rows else 0.0,
            "lowestEndBalance": {"month": lowest["month"], "amount": lowest["endBalance"]} if lowest else None,
            "basis": f["basis"]}


def goal_plan(transactions: list[dict], target: float, months: int | None = None, saved: float = 0.0,
              by_date: str = "", other_goals: list[dict] | None = None) -> dict:
    """
    What reaching a savings target takes, from this customer's own figures:
    the monthly amount needed, what they have left over now, what their other
    saved goals already need from that (month by month, as each runs to its
    date), and illustrative changes to discretionary spending that would close
    any gap. With it, the context that qualifies the plan: how much the recent
    months varied and why, and what the months ahead are expected to leave over.
    The changes are examples to explain, not recommendations; the customer decides.
    """
    other_goals = other_goals or []
    if by_date:
        end = date.fromisoformat(by_date)
        months = max(1, (end.year - as_of().year) * 12 + end.month - as_of().month)
    months = max(1, int(months or 12))
    remaining = max(0.0, target - saved)
    needed = remaining / months
    over = overview(transactions)["averageMonth"]
    # Left over each month = what comes in, less what goes out; money moved to savings already counts towards it.
    left_over = over.get("moneyIn", 0.0) - over.get("moneyOut", 0.0)

    def committed(i: int) -> float:
        """What the other goals need in month i from now (1 = next month); a goal stops needing it after its date."""
        return sum(g["perMonth"] for g in other_goals if g["months"] >= i)

    def free(i: int, extra: float = 0.0) -> float:
        """What's free for this goal in month i. Saved goals come first: a month where they need more than is
        left over counts against this one, so the gap is exactly what would reach it on time."""
        return left_over + extra - committed(i)
    # What's free for this goal on average over its months, once the other goals have what they need.
    free_per_month = sum(free(i) for i in range(1, months + 1)) / months
    gap = needed - free_per_month
    flex = discretionary(transactions)
    subs = [r for r in recurring(transactions) if r["category"] == "subscriptions"]
    options = []
    for h in flex["habits"]:
        # Subscriptions are offered one by one below; holidays are one-off, not a monthly habit.
        if not h["discretionary"] or h["category"] in ("subscriptions", "holidays") or h["perMonth"] < 15:
            continue
        for share in (0.25, 0.5):
            options.append({"change": f"Spend {int(share * 100)}% less on {h['words'].lower()}",
                            "category": h["category"], "kind": "reduce", "share": share,
                            "savesPerMonth": _r(h["perMonth"] * share),
                            "today": f"about £{h['perMonth']:.0f} a month, {h['timesPerMonth']:g} times, "
                                     f"£{h['averageEach']:.2f} each"})
    for s in subs:
        options.append({"change": f"Cancel or pause {friendly(s['merchant'])}", "category": "subscriptions",
                        "kind": "subscription", "savesPerMonth": s["amount"], "today": f"£{s['amount']:.2f} a month"})
    # An illustrative mix: one change per category, biggest first, until the gap is covered.
    mix, covered, used = [], 0.0, set()
    for o in sorted((o for o in options if o.get("share", 0.25) == 0.25 or o["kind"] == "subscription"),
                    key=lambda o: -o["savesPerMonth"]):
        if covered >= gap:
            break
        if o["kind"] == "reduce" and o["category"] in used:
            continue
        mix.append(o)
        covered += o["savesPerMonth"]
        used.add(o["category"])
    # Still short: show the bigger change (half rather than a quarter) for the reductions already in the mix.
    if covered < gap:
        for i, o in enumerate(mix):
            if covered >= gap:
                break
            if o["kind"] == "reduce":
                bigger = next(x for x in options if x["category"] == o["category"] and x.get("share") == 0.5)
                covered += bigger["savesPerMonth"] - o["savesPerMonth"]
                mix[i] = bigger

    def months_to(extra: float) -> int | None:
        """Whole months to save what is left, with what's free each month (plus extra); None if never."""
        if remaining <= 0:
            return 0
        last_other = max((g["months"] for g in other_goals), default=0)
        total, i = 0.0, 0
        while total < remaining:
            i += 1
            if i > last_other and free(i, extra) <= 0:
                return None                      # nothing free, even once the other goals are done
            total += free(i, extra)
        return i

    # Dates are worked out here, from the Money Hub's today, so the agent never has to.
    today = as_of()
    target_day = date.fromisoformat(by_date) if by_date else add_months(today, months)
    at_rate, with_mix = months_to(0.0), months_to(covered)

    def reached(n: int | None) -> dict | None:
        if n is None:
            return None
        day = add_months(today, n)
        return {"date": day.isoformat(), "words": month_words(day)}

    return {
        "today": today.isoformat(), "todayWords": today.strftime("%-d %B %Y"),
        "targetDate": target_day.isoformat(), "targetDateWords": month_words(target_day),
        "target": _r(target), "alreadySaved": _r(saved), "months": months,
        "neededPerMonth": _r(needed), "leftOverPerMonth": _r(left_over),
        "alreadyMovingToSavings": over.get("movedToSavings", 0.0),
        "otherGoals": other_goals, "otherGoalsPerMonthNow": _r(committed(1)),
        "freeForThisGoalPerMonth": _r(free_per_month),
        "allGoalsPerMonthNow": _r(committed(1) + needed),
        "gapPerMonth": _r(max(0.0, gap)), "onTrack": gap <= 0,
        "monthsAtCurrentRate": at_rate, "reachedAtCurrentRate": reached(at_rate),
        "illustrativeMix": mix, "mixSavesPerMonth": _r(covered),
        "monthsWithMix": with_mix, "reachedWithMix": reached(with_mix),
        "allOptions": sorted(options, key=lambda o: -o["savesPerMonth"])[:12],
        "recentMonths": recent_months(transactions), "lookingAhead": looking_ahead(transactions),
        "currentBalance": transactions[-1]["balanceAfter"] if transactions else 0.0,
        "note": "Based on the last three complete months, after what the customer's other saved goals need. "
                "These are illustrations, not advice.",
    }


def financial_picture(transactions: list[dict], goals: list[dict]) -> dict:
    """
    The whole picture in one place, for "how am I doing" and before suggesting a goal: the balance now, each
    recent month (and what made one stand out), a typical month, bills and essentials against spending they
    choose, regular commitments, the months ahead, and every saved goal with what it needs a month. "Free each
    month" is the typical month's left over less what the saved goals need now.
    """
    over = overview(transactions)["averageMonth"]
    left_over = over.get("moneyIn", 0.0) - over.get("moneyOut", 0.0)
    flex = discretionary(transactions)
    regular = recurring(transactions)
    goal_rows = goal_commitments(goals)
    goals_now = sum(g["perMonth"] for g in goal_rows)
    lefts = [m["leftOver"] for m in recent_months(transactions)]
    return {
        "asOf": as_of().isoformat(), "currentBalance": transactions[-1]["balanceAfter"] if transactions else 0.0,
        "recentMonths": recent_months(transactions),
        "typicalMonth": {"moneyIn": over.get("moneyIn", 0.0), "moneyOut": over.get("moneyOut", 0.0),
                         "leftOver": _r(left_over), "ofWhichMovedToSavings": over.get("movedToSavings", 0.0)},
        "leftOverRange": {"lowest": min(lefts), "highest": max(lefts)} if lefts else None,
        "billsAndEssentialsPerMonth": flex["essentialPerMonth"], "spendingYouChoosePerMonth": flex["discretionaryPerMonth"],
        "regularOutPerMonth": _r(sum(r["amount"] for r in regular if r["direction"] in (cat.OUT, cat.MOVE))),
        "subscriptionsPerMonth": _r(sum(r["amount"] for r in regular if r["category"] == "subscriptions")),
        "lookingAhead": looking_ahead(transactions),
        "goals": goal_rows,
        "goalsNeedPerMonthNow": _r(goals_now), "freeEachMonth": _r(left_over - goals_now),
        "basis": "Typical month: the average of the last three complete months. The months ahead are an estimate "
                 "from past patterns, not a promise.",
    }


def compare(transactions: list[dict], month_a: str, month_b: str) -> dict:
    """Spending by category in two months, and what changed."""
    def totals(month):
        return {r["category"]: r["total"] for r in by_category([t for t in transactions if month_key(t["date"]) == month])}
    a, b = totals(month_a), totals(month_b)
    rows = [{"category": c, "words": cat.words(c), month_a: a.get(c, 0.0), month_b: b.get(c, 0.0),
             "change": _r(b.get(c, 0.0) - a.get(c, 0.0))} for c in sorted(set(a) | set(b))]
    return {"from": month_a, "to": month_b, "rows": sorted(rows, key=lambda r: -abs(r["change"])),
            "totalFrom": _r(sum(a.values())), "totalTo": _r(sum(b.values()))}


def period_bounds(period: str) -> tuple[str, str]:
    """Named periods the agent may use: this_month, last_month, last_3_months, last_6_months."""
    today = as_of()
    first = today.replace(day=1)
    if period == "this_month":
        return first.isoformat(), today.isoformat()
    if period == "last_month":
        end = first - timedelta(days=1)
        return end.replace(day=1).isoformat(), end.isoformat()
    if period in ("last_3_months", "last_6_months"):
        n = 3 if period == "last_3_months" else 6
        keys = last_full_months(n)
        end = first - timedelta(days=1)
        return f"{keys[0]}-01", end.isoformat()
    raise ValueError("period must be this_month, last_month, last_3_months or last_6_months")
