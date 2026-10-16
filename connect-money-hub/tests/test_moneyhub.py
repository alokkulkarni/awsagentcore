"""
Unit tests for the Money Hub core: the sample data, the analyses, recategorising,
goals and page links. No AWS: the in-memory store, with a clock the tests set.

    python3 -m unittest discover -s connect-money-hub/tests
"""

import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FOLDER))

from moneyhub import analysis, data  # noqa: E402
from moneyhub import categories as cat  # noqa: E402
from moneyhub.service import MoneyHub, MoneyHubError  # noqa: E402
from moneyhub.store import DynamoStore, MemoryStore  # noqa: E402

JAMES, SARAH = "CUST-001", "CUST-002"


class SampleData(unittest.TestCase):

    def test_each_customer_has_well_over_100_transactions_in_and_out(self):
        for customer in data.CUSTOMERS:
            rows = data.generate(customer)
            self.assertGreaterEqual(len(rows), 100, customer)
            self.assertTrue(any(t["amount"] > 0 for t in rows) and any(t["amount"] < 0 for t in rows))
            self.assertEqual({cat.direction(t["category"]) for t in rows} >= {cat.IN, cat.OUT}, True)

    def test_the_data_is_the_same_every_time_with_stable_ids(self):
        self.assertEqual(data.generate(JAMES), data.generate(JAMES))
        ids = [t["transactionId"] for t in data.generate(JAMES)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_balances_run_through_the_statement(self):
        rows = data.generate(JAMES)
        running = data.OPENING_BALANCE[JAMES]
        for t in rows:
            running = round(running + t["amount"], 2)
            self.assertAlmostEqual(t["balanceAfter"], running, places=2)
        self.assertEqual((rows[0]["date"] >= "2026-04-16", rows[-1]["date"] <= "2026-10-15"), (True, True))

    def test_james_has_the_patterns_the_agent_explains(self):
        found = {t["category"] for t in data.generate(JAMES)}
        for needed in ("salary", "other_income", "refunds", "housing", "bills", "subscriptions", "groceries",
                       "coffee", "takeaways", "eating_out", "shopping", "holidays", "savings"):
            self.assertIn(needed, found)

    def test_an_unknown_customer_has_nothing(self):
        self.assertEqual(data.generate("CUST-999"), [])


class Analyses(unittest.TestCase):

    def setUp(self):
        self.rows = data.generate(JAMES)

    def test_overview_matches_the_statement(self):
        o = analysis.overview(self.rows)
        self.assertEqual(o["balance"], self.rows[-1]["balanceAfter"])
        self.assertEqual([m["month"] for m in o["months"]], ["2026-07", "2026-08", "2026-09"])
        july = [t for t in self.rows if t["date"].startswith("2026-07")]
        spent = round(sum(-t["amount"] for t in july if cat.direction(t["category"]) == cat.OUT), 2)
        self.assertEqual(o["months"][0]["moneyOut"], spent)
        self.assertNotIn("savings", [c["category"] for c in o["topSpending"]], "moving to savings isn't spending")

    def test_recurring_finds_salary_bills_and_subscriptions_but_not_coffee(self):
        found = {r["merchant"]: r for r in analysis.recurring(self.rows)}
        for merchant in ("ACME ENGINEERING LTD SALARY", "NATIONWIDE MORTGAGE", "NETFLIX.COM", "SPOTIFY"):
            self.assertIn(merchant, found)
        self.assertEqual(found["NETFLIX.COM"]["amount"], 10.99)
        self.assertNotIn("PRET A MANGER", found)

    def test_forecast_looks_three_months_ahead_from_the_end_of_the_data(self):
        f = analysis.forecast(self.rows)
        self.assertEqual([m["month"] for m in f["months"]], ["2026-11", "2026-12", "2027-01"])
        nov = f["months"][0]
        self.assertGreater(nov["expectedIn"], 3000)
        self.assertIn("NATIONWIDE MORTGAGE", [e["merchant"] for e in nov["regularOut"]])
        self.assertAlmostEqual(nov["endBalance"], round(f["startBalance"] + nov["expectedIn"] - nov["expectedOut"], 2), 1)
        self.assertNotIn("holidays", [e["category"] for e in nov["everydaySpending"]], "one-offs aren't repeated")

    def test_discretionary_splits_spending_and_describes_habits(self):
        d = analysis.discretionary(self.rows)
        coffee = next(h for h in d["habits"] if h["category"] == "coffee")
        self.assertTrue(coffee["discretionary"])
        self.assertGreater(coffee["timesPerMonth"], 5)
        self.assertAlmostEqual(d["essentialPerMonth"] + d["discretionaryPerMonth"],
                               sum(h["perMonth"] for h in d["habits"]), 0)

    def test_an_ambitious_goal_shows_the_gap_and_an_honest_mix(self):
        g = analysis.goal_plan(self.rows, 5000, by_date="2027-06-30")
        self.assertEqual((g["months"], g["neededPerMonth"], g["onTrack"]), (8, 625.0, False))
        self.assertGreater(g["gapPerMonth"], 0)
        self.assertTrue(g["illustrativeMix"])
        self.assertTrue(all(o["category"] != "holidays" for o in g["allOptions"]), "one-offs aren't a habit")
        self.assertLess(g["monthsWithMix"], g["monthsAtCurrentRate"])
        self.assertIn("not advice", g["note"])

    def test_a_reachable_goal_needs_no_changes(self):
        g = analysis.goal_plan(self.rows, 1200, months=12)
        self.assertEqual((g["onTrack"], g["gapPerMonth"], g["illustrativeMix"]), (True, 0.0, []))

    def test_periods_and_comparisons(self):
        self.assertEqual(analysis.period_bounds("last_month"), ("2026-09-01", "2026-09-30"))
        self.assertEqual(analysis.period_bounds("this_month"), ("2026-10-01", "2026-10-15"))
        with self.assertRaises(ValueError):
            analysis.period_bounds("last_decade")
        c = analysis.compare(self.rows, "2026-08", "2026-09")
        self.assertEqual(c["from"], "2026-08")
        self.assertTrue(c["rows"])

    def test_names_are_readable(self):
        self.assertEqual(analysis.friendly("APPLE.COM/BILL ICLOUD"), "Apple iCloud")
        self.assertEqual(analysis.friendly("NETFLIX.COM"), "Netflix")


class Service(unittest.TestCase):

    def setUp(self):
        self.now = 1_800_000_000.0
        self.hub = MoneyHub(MemoryStore(lambda: self.now), lambda: self.now, page_url="https://hub.example")

    def coffee(self):
        return next(t for t in data.generate(JAMES) if t["category"] == "coffee")

    def test_a_customer_can_move_a_payment_to_another_category_and_every_view_follows(self):
        t = self.coffee()
        before = analysis.by_category(self.hub.transactions(JAMES))
        changed = self.hub.recategorise(JAMES, t["transactionId"], "eating_out", "page")["transaction"]
        self.assertEqual((changed["category"], changed["recategorised"]), ("eating_out", True))
        after = {r["category"]: r["total"] for r in analysis.by_category(self.hub.transactions(JAMES))}
        before = {r["category"]: r["total"] for r in before}
        self.assertAlmostEqual(after["eating_out"] - before["eating_out"], -t["amount"], 2)
        back = self.hub.recategorise(JAMES, t["transactionId"], "coffee", "agent")["transaction"]
        self.assertFalse(back["recategorised"], "choosing the original category undoes it")

    def test_money_in_and_money_out_never_swap(self):
        salary = next(t for t in data.generate(JAMES) if t["category"] == "salary")
        with self.assertRaises(MoneyHubError) as e:
            self.hub.recategorise(JAMES, salary["transactionId"], "shopping", "page")
        self.assertEqual(e.exception.code, "wrong_direction")
        for bad in (("MH-nope", "coffee", "transaction_not_found"), (self.coffee()["transactionId"], "lottery", "unknown_category")):
            with self.assertRaises(MoneyHubError) as e:
                self.hub.recategorise(JAMES, bad[0], bad[1], "page")
            self.assertEqual(e.exception.code, bad[2])

    def test_one_customer_can_never_touch_anothers_transactions(self):
        with self.assertRaises(MoneyHubError):
            self.hub.recategorise(SARAH, self.coffee()["transactionId"], "eating_out", "page")

    def test_lists_page_newest_first_and_filter(self):
        first = self.hub.list_transactions(JAMES, per_page=5)
        self.assertEqual(len(first["transactions"]), 5)
        self.assertGreaterEqual(first["transactions"][0]["date"], first["transactions"][-1]["date"])
        coffee = self.hub.list_transactions(JAMES, category="coffee", per_page=50)
        self.assertTrue(all(t["category"] == "coffee" for t in coffee["transactions"]))
        self.assertTrue(self.hub.list_transactions(JAMES, merchant="netflix")["total"] >= 6)

    def test_goals_are_saved_with_their_plan_and_limited(self):
        saved = self.hub.save_goal(JAMES, "New car", 5000, "2027-06-30")
        self.assertEqual(saved["goal"]["neededPerMonth"], 625.0)
        self.assertEqual([g["name"] for g in self.hub.goals(JAMES)], ["New car"])
        self.hub.save_goal(JAMES, "new car", 4000, "2027-06-30")
        self.assertEqual(len(self.hub.goals(JAMES)), 1, "same name replaces")
        for bad in (("<script>", 100, "2027-01-01"), ("Trip", -5, "2027-01-01"), ("Trip", 100, "2020-01-01"),
                    ("Trip", 100, "soon")):
            with self.assertRaises(MoneyHubError):
                self.hub.save_goal(JAMES, *bad)
        self.assertEqual(self.hub.delete_goal(JAMES, "NEW CAR")["goals"], [])

    def test_page_links_carry_the_secret_after_the_hash_and_expire(self):
        link = self.hub.mint_link(JAMES)
        self.assertTrue(link.startswith("https://hub.example/#k="))
        token = link.split("#k=")[1]
        self.assertEqual(self.hub.customer_of_link(token), JAMES)
        self.now += 24 * 60 * 60 + 1
        with self.assertRaises(MoneyHubError):
            self.hub.customer_of_link(token)
        with self.assertRaises(MoneyHubError):
            self.hub.mint_link("CUST-999")

    def test_the_page_view_has_everything_the_page_needs(self):
        view = self.hub.page_view(JAMES)
        self.assertEqual(set(view), {"overview", "forecast", "recurring", "discretionary", "goals", "choices"})
        self.assertIn("savings", [c["category"] for c in view["choices"]["out"]])


class FakeTable:
    def __init__(self):
        self.rows = {}

    def get_item(self, Key, ConsistentRead=False):
        row = self.rows.get(Key["pk"])
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item):
        self.rows[Item["pk"]] = dict(Item)


class DynamoStoreBehavesLikeMemory(unittest.TestCase):

    def test_round_trip_floats_and_expiry(self):
        now = [1000.0]
        store = DynamoStore("t", lambda: now[0], table=FakeTable())
        store.put("k", {"amount": 12.34, "nested": [{"x": 1.5}], "expiresAt": 1100})
        self.assertEqual(store.get("k"), {"amount": 12.34, "nested": [{"x": 1.5}], "expiresAt": 1100})
        now[0] = 1101
        self.assertIsNone(store.get("k"))
        hub = MoneyHub(DynamoStore("t", lambda: 1.0, table=FakeTable()), lambda: 1.0)
        hub.save_goal(JAMES, "Holiday", 1500.50, "2027-08-01")
        self.assertEqual(hub.goals(JAMES)[0]["target"], 1500.5)


if __name__ == "__main__":
    unittest.main()
