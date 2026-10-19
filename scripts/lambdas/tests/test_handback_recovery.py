"""
aria-handback-recovery: on a chat where Amazon Connect loses ARIA's hand-back (NullPointerException in Get customer
input), the decision is read back from her trace. The spans below have the shape of contact 77a28b4d's (a dispute)
and 4b92f201's (a Money Hub chat ending).
"""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import handback_recovery as recovery  # noqa: E402

AT = datetime(2026, 10, 17, 18, 43, 29, 677000, tzinfo=timezone.utc)
SESSION = "arn:aws:wisdom:eu-west-2:395402194296:session/e6991ed4-e11c-4194-8d20-13889a36bd15/0bd50837"


def tool_use(name, arguments):
    return {"values": [{"toolUse": {"toolUseId": "t1", "name": name, "arguments": json.dumps(arguments)}}]}


def turn(tool, arguments, at=AT, turn_id="turn-2", back_id="back-2", orchestrator=True):
    """One ARIA turn: her inference (a sentence, then the tool), the tool run, and the hand-back."""
    kind = {"aiAgentType": "ORCHESTRATION"} if orchestrator else {}
    return [
        {"spanId": turn_id, "spanName": "invoke_agent", "startTimestamp": at - timedelta(seconds=11), "attributes": kind},
        {"spanId": turn_id + "-inf", "parentSpanId": turn_id, "spanName": "inference",
         "startTimestamp": at - timedelta(seconds=11), "attributes": {**kind, "outputMessages": [
             {"values": [{"text": {"value": "Let's sort that out for you."}}]}, tool_use(tool, arguments),
             {"values": [{"reasoning": {"value": "…"}}]}]}},
        {"spanId": turn_id + "-tool", "parentSpanId": turn_id, "spanName": "execute_tool",
         "startTimestamp": at - timedelta(milliseconds=60), "attributes": {**kind, "operationName": tool}},
        {"spanId": back_id, "parentSpanId": turn_id, "spanName": "return_to_agent", "startTimestamp": at,
         "attributes": {**kind, "returnReason": "COMPLETE"}},
    ]


DISPUTE = turn("Complete", {"reason": "dispute", "nextStep": "card_dispute",
                            "handoverSummary": "Doesn't recognise a payment on credit card ending 2291."})


class FakeConnect:
    def __init__(self):
        self.updates = []

    def update_contact_attributes(self, **kwargs):
        self.updates.append(kwargs)


class FakeQ:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), 0

    def list_spans(self, **kwargs):
        self.calls += 1
        return {"spans": self.pages[min(self.calls, len(self.pages)) - 1]}


def event(attributes=None):
    return {"Details": {"ContactData": {
        "ContactId": "77a28b4d", "InitialContactId": "77a28b4d",
        "InstanceARN": "arn:aws:connect:eu-west-2:395402194296:instance/f969d4b4",
        "Attributes": {"sessionId": SESSION, **(attributes or {})}}}}


class FindsTheHandBack(unittest.TestCase):
    def test_a_dispute_hand_back_is_found_with_its_fields(self):
        found = recovery.find_hand_back(DISPUTE, "", AT + timedelta(seconds=2))
        self.assertEqual((found["tool"], found["spanId"]), ("Complete", "back-2"))
        self.assertEqual(recovery.decide(found), ("card_dispute", {
            "handoverSummary": "Doesn't recognise a payment on credit card ending 2291.", "entry": "aria"}))

    def test_each_kind_of_hand_back_routes_as_the_flow_would(self):
        cases = {
            ("Complete", "none"): "end",
            ("Complete", "mortgage_application"): "escalate",              # on a chat, as the flow does for chats
            ("StartCardDispute", ""): "card_dispute",
            ("StartMortgageApplication", ""): "escalate",
        }
        for (tool, step), route in cases.items():
            found = recovery.find_hand_back(turn(tool, {"nextStep": step, "handoverSummary": "x"}), "", AT)
            self.assertEqual(recovery.decide(found)[0], route, (tool, step))
        escalated = recovery.decide(recovery.find_hand_back(turn("Escalate", {
            "topicCategory": "credit_card", "escalationReason": "customer_requested", "customerIntent": "talk to someone",
            "conversationSummary": "Wants a person."}), "", AT))
        self.assertEqual(escalated, ("escalate", {"topicCategory": "credit_card", "escalationReason": "customer_requested",
                                                 "customerIntent": "talk to someone", "conversationSummary": "Wants a person."}))
        mortgage = recovery.decide(recovery.find_hand_back(turn("Complete", {
            "nextStep": "mortgage_application", "handoverSummary": "First-time buyer."}), "", AT))[1]
        self.assertEqual((mortgage["topicCategory"], mortgage["conversationSummary"]), ("mortgage_application", "First-time buyer."))

    def test_a_call_mortgage_application_takes_the_phone_mortgage_path_with_its_code(self):
        # As contact e6ddfb80: Complete's fields never reached the flow on a call.
        found = recovery.find_hand_back(turn("Complete", {
            "nextStep": "mortgage_application", "buyerType": "unknown", "screenCode": "303567",
            "handoverSummary": "Wants help filling out a mortgage application; has it open on screen."}), "", AT)
        self.assertEqual(recovery.decide(found, "VOICE"), ("mortgage_application", {
            "handoverSummary": "Wants help filling out a mortgage application; has it open on screen.",
            "buyerType": "unknown", "screenCode": "303567", "entry": "phone"}))
        bad_code = recovery.find_hand_back(turn("Complete", {"nextStep": "mortgage_application", "screenCode": "12ab"}), "", AT)
        self.assertEqual(recovery.decide(bad_code, "VOICE")[1]["screenCode"], "")

    def test_never_invents_or_replays_a_decision(self):
        self.assertIsNone(recovery.find_hand_back([], "", AT), "no trace")
        self.assertIsNone(recovery.find_hand_back(DISPUTE, "back-2", AT), "already handled")
        self.assertIsNone(recovery.find_hand_back(DISPUTE, "", AT + timedelta(minutes=5)), "too old: a later error")
        self.assertIsNone(recovery.find_hand_back(turn("Complete", {}, orchestrator=False), "", AT), "a collaborator's")
        no_tool = [s for s in DISPUTE if s["spanName"] != "inference"]
        self.assertIsNone(recovery.find_hand_back(no_tool, "", AT), "no tool call to read")

    def test_the_newest_hand_back_wins(self):
        earlier = turn("Complete", {"nextStep": "none"}, at=AT - timedelta(seconds=40), turn_id="turn-1", back_id="back-1")
        found = recovery.find_hand_back(earlier + DISPUTE, "back-1", AT)
        self.assertEqual((found["spanId"], recovery.decide(found)[0]), ("back-2", "card_dispute"))


class TheLambda(unittest.TestCase):
    def setUp(self):
        self.connect = FakeConnect()
        recovery.POLL_SECONDS = 0.01
        recovery.WAIT_SECONDS = 0.05

    def run_with(self, pages, attributes=None, parameters=None, channel="CHAT"):
        self.q = FakeQ(pages)
        recovery._clients.update({"connect": self.connect, "qconnect": self.q})
        real_now = recovery.datetime

        class Clock(real_now):
            @classmethod
            def now(cls, tz=None):
                return AT + timedelta(seconds=2)
        recovery.datetime = Clock
        try:
            ev = event(attributes)
            ev["Details"]["ContactData"]["Channel"] = channel
            ev["Details"]["Parameters"] = parameters or {}
            return recovery.lambda_handler(ev)
        finally:
            recovery.datetime = real_now

    def test_sets_the_attributes_the_dispute_flow_reads_and_marks_the_hand_back_handled(self):
        self.assertEqual(self.run_with([DISPUTE]), {"route": "card_dispute", "recoveredTool": "Complete"})
        self.assertEqual(self.connect.updates, [{
            "InitialContactId": "77a28b4d", "InstanceId": "f969d4b4",
            "Attributes": {"handoverSummary": "Doesn't recognise a payment on credit card ending 2291.", "entry": "aria",
                           "handledHandback": "back-2"}}])

    def test_waits_for_the_trace_to_be_written(self):
        self.assertEqual(self.run_with([[], [], DISPUTE])["route"], "card_dispute")
        self.assertEqual(self.q.calls, 3)

    def test_nothing_to_recover_leaves_the_flow_as_it_was(self):
        self.assertEqual(self.run_with([[]]), {"route": "none"})
        self.assertEqual(self.run_with([DISPUTE], {"handledHandback": "back-2"}), {"route": "none"})
        self.assertEqual(self.connect.updates, [])

    def test_from_the_complete_branch_nothing_recovered_means_the_conversation_ends(self):
        self.assertEqual(self.run_with([[]], parameters={"whenNothing": "end"}), {"route": "end"})
        self.assertEqual(self.run_with([DISPUTE], {"handledHandback": "back-2"}, {"whenNothing": "end"}), {"route": "end"})

    def test_a_call_recovers_into_the_phone_mortgage_path(self):
        mortgage = turn("Complete", {"nextStep": "mortgage_application", "buyerType": "first_time",
                                     "screenCode": "303567", "handoverSummary": "First-time buyer."})
        self.assertEqual(self.run_with([mortgage], parameters={"whenNothing": "end"}, channel="VOICE")["route"],
                         "mortgage_application")
        self.assertEqual(self.connect.updates[-1]["Attributes"]["screenCode"], "303567")

    def test_any_failure_falls_back_to_the_flows_loop(self):
        class Broken:
            def list_spans(self, **kwargs):
                raise RuntimeError("AccessDenied")
        recovery._clients.update({"connect": self.connect, "qconnect": Broken()})
        self.assertEqual(recovery.lambda_handler(event()), {"route": "none"})


if __name__ == "__main__":
    unittest.main()
