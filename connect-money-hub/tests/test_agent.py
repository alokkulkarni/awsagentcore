"""
Tests for the Money Hub agent's tools, prompt and history handling. They need
neither Strands nor AWS: the tools are plain functions over the in-memory store.
"""

import inspect
import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FOLDER))
sys.path.insert(0, str(FOLDER / "agent"))

from history import to_messages  # noqa: E402
from money_tools import Recorder, build_tools  # noqa: E402
from moneyhub import data  # noqa: E402
from moneyhub.service import MoneyHub  # noqa: E402
from moneyhub.store import MemoryStore  # noqa: E402
from prompt import GUIDANCE_DISCLOSURE, system_blocks, system_prompt  # noqa: E402

JAMES = "CUST-001"


class Tools(unittest.TestCase):

    def setUp(self):
        self.hub = MoneyHub(MemoryStore(lambda: 1_800_000_000.0), lambda: 1_800_000_000.0, page_url="https://hub.example")
        self.recorder = Recorder()
        self.tools = {t.__name__: t for t in build_tools(self.hub, JAMES, "CHAT", self.recorder)}

    def test_no_tool_lets_the_model_choose_the_customer(self):
        for name, fn in self.tools.items():
            params = inspect.signature(fn).parameters
            self.assertFalse({"customer_id", "customerId", "customer"} & set(params), name)
            self.assertTrue(fn.__doc__ and len(fn.__doc__) > 30, f"{name} needs a description for the model")

    def test_overview_habits_and_forecast_give_figures_to_explain(self):
        o = self.tools["get_money_overview"]()
        self.assertEqual(o["currentBalance"], data.generate(JAMES)[-1]["balanceAfter"])
        self.assertEqual(o["currentBalance"], self.hub.page_view(JAMES)["overview"]["balance"],
                         "the agent's balance is the page's Balance")
        habits = self.tools["get_spending_habits"]()
        self.assertTrue(any(h["words"] == "Coffee and snacks" for h in habits["habits"]))
        months = self.tools["get_expected_months"](3)["months"]
        self.assertEqual(len(months), 3)
        self.assertIn("endBalance", months[0])

    def test_figures_are_per_month_and_left_over_means_what_the_page_says(self):
        o = self.tools["get_money_overview"]()
        page = self.hub.page_view(JAMES)["overview"]["averageMonth"]
        self.assertAlmostEqual(o["averageMonth"]["leftOver"], round(page["moneyIn"] - page["moneyOut"], 2), places=2)
        self.assertNotIn("net", o["averageMonth"], "no second meaning of left over")
        self.assertIn("ofWhichMovedToSavings", o["averageMonth"])
        habits = {h["words"]: h["perMonth"] for h in self.tools["get_spending_habits"]()["habits"]}
        top = o["topSpendingPerMonth"][0]
        self.assertAlmostEqual(top["perMonth"], habits[top["words"]], delta=1.0, msg="overview and habits agree per month")
        cats = self.tools["get_spending_by_category"]("last_3_months")
        self.assertEqual(cats["monthsInPeriod"], 3)
        first = cats["categories"][0]
        self.assertAlmostEqual(first["perMonth"] * 3, first["totalForPeriod"], delta=0.05)

    def test_finding_and_recategorising_a_transaction(self):
        found = self.tools["find_transactions"](category="coffee", period="last_month")
        self.assertTrue(found["transactions"])
        tx = found["transactions"][0]
        moved = self.tools["recategorise_transaction"](tx["id"], "eating_out")
        self.assertEqual((moved["ok"], moved["transaction"]["category"]), (True, "Eating out"))
        refused = self.tools["recategorise_transaction"](tx["id"], "salary")
        self.assertEqual((refused["ok"], refused["reason"]), (False, "wrong_direction"), "a refusal is an answer")

    def test_savings_goal_plan_and_save(self):
        plan = self.tools["plan_savings_goal"](5000, target_date="2027-06-30")
        self.assertEqual(plan["neededPerMonth"], 625.0)
        self.assertTrue(plan["illustrativeMix"])
        saved = self.tools["save_savings_goal"]("Car", 5000, "2027-06-30")
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["goal"]["name"], "Car")
        self.assertIn("Goals tab", saved["whereToSee"])
        page = self.hub.page_view(JAMES)
        self.assertEqual([g["name"] for g in page["goals"]], ["Car"], "the page reads what the agent saved")
        self.assertEqual(page["goals"][0]["saved"], 0.0, "nothing counted as saved unless they said so")
        bad = self.tools["plan_savings_goal"](5000, target_date="2020-01-01")
        self.assertEqual(bad["reason"], "date_not_ahead")
        self.assertIn("after 15 October 2026", bad["message"], "says what would work, not that something broke")

    def test_the_agent_sees_the_whole_picture_and_the_goals_already_saved(self):
        self.tools["save_savings_goal"]("Holiday", 600, "2027-01")
        pic = self.tools["get_financial_picture"]()
        self.assertEqual([g["name"] for g in pic["goals"]], ["Holiday"])
        self.assertIn("lookingAhead", pic)
        plan = self.tools["plan_savings_goal"](1200, target_date="2027-03")
        self.assertEqual(plan["otherGoalsPerMonthNow"], 200.0, "a new goal allows for the saved one")
        self.assertEqual(self.tools["plan_savings_goal"](600, target_date="2027-01", name="Holiday")["otherGoals"], [])

    def test_goal_dates_come_from_the_tools_not_the_model(self):
        plan = self.tools["plan_savings_goal"](10000, target_date="2027-03")
        self.assertEqual((plan["today"], plan["targetDate"], plan["targetDateWords"]),
                         ("2026-10-15", "2027-03-31", "March 2027"))
        self.assertEqual(plan["reachedWithMix"]["date"][:7], "2028-03", "17 months from 15 October 2026")
        self.assertEqual(plan["monthsWithMix"], 17)
        saved = self.tools["save_savings_goal"]("Car deposit", 10000, plan["reachedWithMix"]["date"][:7])
        self.assertEqual(saved["goal"]["byDate"], "2028-03-31", "a month alone means its last day")
        self.assertEqual(self.tools["save_savings_goal"]("Car", 10000, "March 27")["reason"], "bad_date")

    def test_every_call_is_recorded_for_connects_trace(self):
        self.tools["get_regular_payments"]()
        self.tools["compare_months"]("2026-08", "2026-09")
        names = [c["name"] for c in self.recorder.calls]
        self.assertEqual(names, ["get_regular_payments", "compare_months"])
        for call in self.recorder.calls:
            self.assertLessEqual(call["startNs"], call["endNs"])
            self.assertTrue(call["ok"])

    def test_hand_back_sets_the_finish_the_bridge_sends(self):
        self.assertIsNone(self.recorder.finish)
        self.tools["hand_back"]("escalate", "Customer asked whether to invest; wants a colleague.")
        self.assertEqual(self.recorder.finish["type"], "ESCALATE")
        self.tools["hand_back"]("complete", "Explained subscriptions.")
        self.assertEqual(self.recorder.finish, {"type": "COMPLETE", "reason": "Explained subscriptions."})

    def test_the_link_is_given_on_chat_and_not_on_a_call(self):
        link = self.tools["get_money_hub_link"]()
        self.assertTrue(link["link"].startswith("https://hub.example/#k="))
        voice = {t.__name__: t for t in build_tools(self.hub, JAMES, "VOICE", Recorder())}
        self.assertEqual(voice["get_money_hub_link"]()["link"], "")


class Prompt(unittest.TestCase):

    def test_it_never_advises_and_carries_the_disclosure(self):
        text = system_prompt("CHAT", "James")
        for must in ("never give financial advice", "Never recommend a financial product",
                     "Don't say \"you should\"", "Only if they choose the colleague, use hand_back with outcome escalate", GUIDANCE_DISCLOSURE,
                     "don't hand back straight away",
                     "Every number comes from your tools", "Never name another company's product"):
            self.assertIn(must, text)
        self.assertIn("James", text)

    def test_saving_is_only_claimed_after_the_tool_saves(self):
        text = system_prompt("CHAT", "James", "", "15 October 2026")
        self.assertIn("call save_savings_goal in that same turn", text)
        self.assertIn("Never say something is done unless a tool has done it", text)
        self.assertIn("account balance is not money saved towards a goal", text)

    def test_goals_are_planned_against_the_whole_picture(self):
        text = " ".join(system_prompt("CHAT", "James", "", "15 October 2026").split())
        for must in ("use get_financial_picture", "what their saved goals already need from that",
                     "(wouldLeaveShort), say which one", "together need more than they have left over"):
            self.assertIn(must, text)

    def test_it_knows_today_and_never_blames_a_problem(self):
        text = system_prompt("CHAT", "James", "", "15 October 2026")
        self.assertIn("Today is 15 October 2026", text)
        self.assertIn("never count months into a date yourself", text)
        self.assertIn('Never\n  mention errors, issues, systems or problems "on my end"', text)
        self.assertIn("March 2027 here", text)

    def test_voice_and_chat_get_their_own_rules(self):
        self.assertIn("ending 4 8 2 1", system_prompt("VOICE"))
        self.assertIn("at most 45 words", system_prompt("VOICE"))
        self.assertLess(system_prompt("VOICE").index("at most 45 words"), system_prompt("VOICE").index("Your figures"),
                        "channel rules come first, where the model weighs them most")
        self.assertIn("Never read out a link", system_prompt("VOICE"))
        self.assertNotIn("ending 4 8 2 1", system_prompt("CHAT"))


class PromptCaching(unittest.TestCase):
    """The fixed part is cached once and shared; only the date, the customer and the page come after it."""

    def test_the_fixed_part_is_the_same_for_every_customer_date_and_page(self):
        for channel in ("VOICE", "CHAT"):
            a = system_blocks(channel, "Priya", "out", "15 October 2026")      # (the prompt's own examples say "James")
            b = system_blocks(channel, "Sarah", "", "16 October 2026", "they asked about a refund")
            self.assertEqual(a[0], b[0], channel)
            self.assertEqual(a[1], {"cachePoint": {"type": "default"}})
            for personal in ("Priya", "Sarah", "October 2026", "refund", "Money out tab"):
                self.assertNotIn(personal, a[0]["text"], f"{personal} would break the shared cache")

    def test_what_changes_comes_after_the_cache_point_and_nothing_is_lost(self):
        blocks = system_blocks("VOICE", "James", "out", "15 October 2026", "they asked about bills")
        after = blocks[2]["text"]
        for must in ("Today is 15 October 2026.", "Customer: James", "on the Money out tab",
                     "Earlier, before you joined: they asked about bills"):
            self.assertIn(must, after)
        self.assertEqual(system_prompt("VOICE", "James", "out", "15 October 2026", "they asked about bills"),
                         blocks[0]["text"] + "\n\n" + after, "the same words as the one-string prompt")


class History(unittest.TestCase):

    def test_history_starts_with_the_customer_alternates_and_holds_back_the_last_user_turn(self):
        messages, preface = to_messages([
            {"role": "assistant", "text": "Hi James, how can I help?"},
            {"role": "user", "text": "I want to look at my spending"},
            {"role": "user", "text": "especially takeaways"},
            {"role": "assistant", "text": "Of course."},
            {"role": "user", "text": "and coffee"},
        ])
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertIn("especially takeaways", messages[0]["content"][0]["text"])
        self.assertIn("Hi James", preface)
        self.assertIn("and coffee", preface)
        self.assertEqual(to_messages([]), ([], ""))


if __name__ == "__main__":
    unittest.main()
