"""
The "Mortgage Live Sync handover" flow (build_mortgage_handover_flow.py): the live flow's mortgage assistant, with
connect-livesync-mortgage v1.24's routing: back to ARIA to help (FR-39), and only ARIA escalates (FR-40).
"""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import build_mortgage_handover_flow as builder  # noqa: E402

LIVE = json.loads(builder.LIVE.read_text())
FLOW = json.loads(builder.OUTPUT.read_text())
BLOCKS = {a["Identifier"]: a for a in FLOW["Actions"]}


def follow(start, escalation_reason="", failing=()):
    """Where a contact ends, and the attributes set on the way. failing: blocks that take their error branch."""
    current, attributes, steps = start, {}, 0
    while True:
        steps += 1
        assert steps < 50
        block = BLOCKS[current]
        t, tr = block["Type"], block["Transitions"]
        errors = {e["ErrorType"]: e["NextAction"] for e in tr.get("Errors", [])}
        if t == "DisconnectParticipant":
            return ("disconnect", attributes)
        if t == "TransferToFlow":
            if current in failing:
                current = errors["NoMatchingError"]; continue
            return (block["Parameters"]["ContactFlowId"].rsplit("/", 1)[-1][:8], attributes)
        if t == "UpdateContactAttributes":
            if current in failing:
                current = errors["NoMatchingError"]; continue
            attributes.update(block["Parameters"]["Attributes"])
            current = tr["NextAction"]; continue
        if t == "Compare":
            match = None
            for c in tr["Conditions"]:
                op, value = c["Condition"]["Operator"], c["Condition"]["Operands"][0]
                if (op == "Equals" and escalation_reason == value) or (op == "TextContains" and value in escalation_reason):
                    match = c["NextAction"]; break
            current = match or errors["NoMatchingCondition"]; continue
        raise AssertionError(f"unexpected block {current}")


def leave(branch):
    """The assistant block's exit for a branch: Escalation, Default, Error or Timeout."""
    tr = BLOCKS["MortgageAssistant"]["Transitions"]
    errors = {e["ErrorType"]: e["NextAction"] for e in tr["Errors"]}
    return {"Escalation": tr["Conditions"][0]["NextAction"], "Default": errors["NoMatchingCondition"],
            "Error": errors["NoMatchingError"], "Timeout": errors["InputTimeLimitExceeded"]}[branch]


class TheMortgageHandoverFlow(unittest.TestCase):

    def test_the_written_file_is_what_the_builder_makes(self):
        self.assertEqual(builder.build(LIVE), FLOW)

    def test_the_mortgage_assistant_block_is_the_live_one_unchanged(self):
        live = next(a for a in LIVE["Actions"] if a["Type"] == "ConnectParticipantWithAgenticCX")
        self.assertEqual(BLOCKS["MortgageAssistant"]["Parameters"], live["Parameters"])
        self.assertEqual(FLOW["StartAction"], "MortgageAssistant")

    def test_back_to_aria_goes_to_her_to_help_from_either_branch(self):
        for branch in ("Escalation", "Default"):
            ended, attributes = follow(leave(branch), "back_to_aria")
            self.assertEqual(ended, "2b4f7b5c", branch)
            self.assertEqual((attributes["entry"], attributes["returnedFrom"], attributes["returnIntent"]),
                             ("returned", "mortgage", "help"), branch)
            self.assertEqual(attributes["returnSummary"], "$.AgenticCX.ContextVariables.summary")

    def test_only_aria_escalates_every_adviser_reason_goes_back_to_her_with_the_notes(self):
        for branch, reason in (("Escalation", "advice_requested"), ("Escalation", "customer_request"),
                               ("Default", "tool_failure"), ("Default", "other"), ("Error", "")):
            ended, attributes = follow(leave(branch), reason)
            self.assertEqual(ended, "2b4f7b5c", (branch, reason))
            self.assertEqual((attributes["returnIntent"], attributes["returnReason"], attributes["returnSummary"]),
                             ("escalate", "$.Attributes.escalationReason", "$.Attributes.conversationSummary"))
            self.assertEqual(attributes["topicCategory"], "mortgage_application", "the screen pop's application view")
        _, notes = follow(leave("Escalation"), "advice_requested")
        for key in ("applicationId", "stage", "dipDecision", "productId", "docsOutstanding", "conversationSummary"):
            self.assertEqual(notes[key], f"$.AgenticCX.ContextVariables.{'summary' if key == 'conversationSummary' else key}")

    def test_a_person_directly_only_when_the_way_back_to_aria_fails(self):
        self.assertEqual(follow(leave("Escalation"), "customer_request", failing=("ToAria",))[0], "0978883b")
        self.assertEqual(follow(leave("Error"), "", failing=("ColleagueNeeded",))[0], "0978883b")
        to_human = {a["Identifier"] for a in FLOW["Actions"]
                    if "ToHuman" in [a["Transitions"].get("NextAction")] + [e["NextAction"] for e in a["Transitions"].get("Errors", [])]}
        self.assertEqual(to_human, {"ToAria", "ColleagueNeeded", "ErrorNotes"})

    def test_a_goodbye_and_a_quiet_customer_end_the_contact(self):
        self.assertEqual(follow(leave("Default"), "")[0], "disconnect", "an Exit application: the assistant said goodbye")
        self.assertEqual(leave("Timeout"), "Disconnect")

    def test_back_to_aria_is_checked_before_the_safety_net_that_matches_any_underscore(self):
        conditions = BLOCKS["CheckDefault"]["Transitions"]["Conditions"]
        self.assertEqual(conditions[0]["Condition"], {"Operator": "Equals", "Operands": ["back_to_aria"]})
        self.assertEqual(conditions[1]["Condition"], {"Operator": "TextContains", "Operands": ["_"]})
        meta = FLOW["Metadata"]["ActionMetadata"]["CheckDefault"]["conditionMetadata"]
        self.assertEqual([m["value"] for m in meta], ["back_to_aria", "_", "other"], "the designer shows them in order")

    def test_every_block_has_a_position_and_no_condition_is_empty(self):
        self.assertEqual(set(FLOW["Metadata"]["ActionMetadata"]), set(BLOCKS))
        for block in FLOW["Actions"]:
            for c in block["Transitions"].get("Conditions", []):
                self.assertTrue(all(str(o).strip() for o in c["Condition"]["Operands"]), block["Identifier"])


if __name__ == "__main__":
    unittest.main()
