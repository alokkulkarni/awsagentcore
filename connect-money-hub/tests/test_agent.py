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
from prompt import GUIDANCE_DISCLOSURE, system_prompt  # noqa: E402

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
        self.assertEqual(o["balance"], data.generate(JAMES)[-1]["balanceAfter"])
        habits = self.tools["get_spending_habits"]()
        self.assertTrue(any(h["words"] == "Coffee and snacks" for h in habits["habits"]))
        months = self.tools["get_expected_months"](3)["months"]
        self.assertEqual(len(months), 3)
        self.assertIn("endBalance", months[0])

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
        self.assertEqual(saved["name"], "Car")
        bad = self.tools["plan_savings_goal"](5000, target_date="2020-01-01")
        self.assertEqual(bad["reason"], "bad_date")

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

    def test_voice_and_chat_get_their_own_rules(self):
        self.assertIn("ending 4 8 2 1", system_prompt("VOICE"))
        self.assertIn("at most 45 words", system_prompt("VOICE"))
        self.assertLess(system_prompt("VOICE").index("at most 45 words"), system_prompt("VOICE").index("Your figures"),
                        "channel rules come first, where the model weighs them most")
        self.assertIn("Never read out a link", system_prompt("VOICE"))
        self.assertNotIn("ending 4 8 2 1", system_prompt("CHAT"))


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
