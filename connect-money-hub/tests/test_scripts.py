"""
Tests for the configuration helpers: adding the Money Hub collaborator to ARIA
without disturbing anything else, and building ARIA's prompt.
"""

import sys
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FOLDER / "scripts"))

import build_aria_prompt as builder  # noqa: E402
import collaborator  # noqa: E402
import handovers  # noqa: E402
import tool_scopes  # noqa: E402

ARIA = {"orchestrationAIAgentConfiguration": {
    "orchestrationAIPromptId": "prompt-1", "toolConfigurations": [{"toolName": "Escalate"}],
    "multiAgentConfigurations": [{"handoffAgentConfiguration": {"agentTarget": {"aiAgentId": "disputes"},
                                                                "instruction": {"instruction": "card disputes"}}}]}}


class Collaborator(unittest.TestCase):

    def test_adding_keeps_everything_else_and_is_idempotent(self):
        once = collaborator.apply(ARIA, "app-1")
        twice = collaborator.apply(once, "app-1")
        self.assertEqual(once, twice)
        orchestration = once["orchestrationAIAgentConfiguration"]
        self.assertEqual(orchestration["orchestrationAIPromptId"], "prompt-1")
        self.assertEqual(orchestration["toolConfigurations"], [{"toolName": "Escalate"}])
        self.assertEqual(len(orchestration["multiAgentConfigurations"]), 2, "the disputes collaborator stays")
        added = orchestration["multiAgentConfigurations"][1]["handoffAgentConfiguration"]
        self.assertEqual((added["agentTarget"], added["audioStreamingEnabled"], added["immediateHandoff"]),
                         ({"applicationId": "app-1"}, False, False))
        self.assertIn("never gives financial advice", added["instruction"]["instruction"])
        self.assertEqual(ARIA["orchestrationAIAgentConfiguration"]["multiAgentConfigurations"][0]["handoffAgentConfiguration"]
                         ["instruction"]["instruction"], "card disputes", "the input isn't modified")

    def test_removing_takes_off_only_the_money_hub(self):
        removed = collaborator.apply(collaborator.apply(ARIA, "app-1"), "app-1", remove=True)
        self.assertEqual(removed, ARIA)
        alone = collaborator.apply({"orchestrationAIAgentConfiguration": {}}, "app-1")
        self.assertNotIn("multiAgentConfigurations",
                         collaborator.apply(alone, "app-1", remove=True)["orchestrationAIAgentConfiguration"])


class Versions(unittest.TestCase):

    def test_prompt_and_guardrail_versions_are_set_and_nothing_else_changes(self):
        config = {"orchestrationAIAgentConfiguration": {"orchestrationAIPromptId": "p-1:20",
                                                        "orchestrationAIGuardrailId": "g-1:1", "locale": "en_GB"}}
        pinned = collaborator.pin_versions(collaborator.apply(config, "app-1"), "22", "3")
        o = pinned["orchestrationAIAgentConfiguration"]
        self.assertEqual((o["orchestrationAIPromptId"], o["orchestrationAIGuardrailId"], o["locale"]),
                         ("p-1:22", "g-1:3", "en_GB"))
        self.assertEqual(len(o["multiAgentConfigurations"]), 1)
        same = collaborator.pin_versions(config)
        self.assertEqual(same, config, "no versions given: left as they are")
        no_guardrail = collaborator.pin_versions({"orchestrationAIAgentConfiguration": {"orchestrationAIPromptId": "p:1"}},
                                                 "2", "3")
        self.assertNotIn("orchestrationAIGuardrailId", no_guardrail["orchestrationAIAgentConfiguration"],
                         "a guardrail isn't invented")
        with self.assertRaises(ValueError):
            collaborator.pin_versions(config, "latest")


class Prompt(unittest.TestCase):
    PROMPT = "system: |\n  <rules>\n  </rules>\n  <assurance_levels>\n  L2\n  </assurance_levels>\n  <tail/>\nmessages:\n- x\n"

    def test_the_section_goes_after_assurance_levels_once(self):
        block = builder.BLOCK_FILE.read_text()
        built = builder.add_block(self.PROMPT, block)
        self.assertEqual(builder.add_block(built, block), built, "running it again doesn't duplicate")
        self.assertLess(built.index("</assurance_levels>"), built.index("<money_hub>"))
        self.assertLess(built.index("</money_hub>"), built.index("<tail/>"))
        self.assertEqual(builder.problems(built), [])
        with self.assertRaises(ValueError):
            builder.add_block("system: |\n  nothing here\n", block)

    def test_the_block_never_lets_aria_advise_or_announce(self):
        block = builder.BLOCK_FILE.read_text()
        for must in ("Level 2", "Never say you are passing", "Never give financial advice", "Money Hub:",
                     "never recap it"):
            self.assertIn(must, block)
        self.assertNotIn("{{", block, "adds no custom variables")




ARIA_TOOLS = {"orchestrationAIAgentConfiguration": {"toolConfigurations": [
    {"toolName": "Escalate", "toolId": "Escalate"},
    {"toolName": "Complete", "toolType": "RETURN_TO_CONTROL", "inputSchema": {"type": "object"}},
    {"toolName": "StartCardDispute", "toolType": "RETURN_TO_CONTROL"},
    {"toolName": "StartMortgageApplication", "toolType": "RETURN_TO_CONTROL"},
    {"toolName": "aria_banking_account___get_account_balance", "toolType": "MODEL_CONTEXT_PROTOCOL"}]}}

LIVE_LIKE_PROMPT = """  Farewell rule: a farewell is ONLY for the end. NEVER say a farewell when you are transferring or escalating to a colleague: the call is continuing, not ending.
  <card_disputes>
  2. In the same turn, call the StartCardDispute tool. In handoverSummary put, in one sentence, everything.
  </card_disputes>
  - Never say a farewell or use the Complete tool when handing a customer to a colleague. Use the Escalate tool.
"""


class HandOvers(unittest.TestCase):
    """With a collaborator, Connect returns the contact to the flow only through Complete and Escalate."""

    def tools(self, config):
        return {t["toolName"]: t for t in config["orchestrationAIAgentConfiguration"]["toolConfigurations"]}

    def test_the_old_hand_over_tools_go_and_complete_carries_where_next(self):
        tools = self.tools(handovers.apply(ARIA_TOOLS))
        self.assertNotIn("StartCardDispute", tools)
        self.assertNotIn("StartMortgageApplication", tools)
        self.assertIn("aria_banking_account___get_account_balance", tools)
        schema = tools["Complete"]["inputSchema"]
        self.assertEqual(schema["properties"]["nextStep"]["enum"], ["none", "card_dispute", "mortgage_application"])
        self.assertEqual(schema["required"], ["reason", "nextStep"])
        # The names the flow's existing blocks already read
        for field in ("handoverSummary", "buyerType", "screenCode"):
            self.assertIn(field, schema["properties"])
        self.assertEqual(tools["Complete"]["toolType"], "RETURN_TO_CONTROL")

    def test_applying_twice_changes_nothing_and_the_input_is_untouched(self):
        once = handovers.apply(ARIA_TOOLS)
        self.assertEqual(handovers.apply(once), once)
        self.assertIn("StartCardDispute", self.tools(ARIA_TOOLS))

    def test_the_collaborator_script_always_includes_the_hand_overs(self):
        for remove in (False, True):
            config = handovers.apply(collaborator.apply(ARIA_TOOLS, "app-1", remove=remove))
            self.assertNotIn("StartCardDispute", self.tools(config))

    def test_the_prompt_hands_over_with_complete_and_never_names_the_old_tools(self):
        fixed = handovers.fix_prompt(LIVE_LIKE_PROMPT)
        self.assertIn("call the Complete tool with nextStep card_dispute", fixed)
        self.assertIn("<mortgage_applications>", fixed)
        self.assertIn("nextStep mortgage_application", fixed)
        self.assertNotIn("StartCardDispute", fixed)
        self.assertIn("is a hand-over, not an end", fixed)
        self.assertEqual(handovers.fix_prompt(fixed), fixed)

    def test_a_prompt_that_has_moved_on_is_refused_rather_than_guessed(self):
        with self.assertRaises(ValueError):
            handovers.fix_prompt(LIVE_LIKE_PROMPT.replace("call the StartCardDispute tool", "use StartCardDispute"))




class ToolScopes(unittest.TestCase):
    """ARIA's card, mortgage and spending tools take the customer's ID, so they answer only for that customer."""

    CONFIG = {"orchestrationAIAgentConfiguration": {"toolConfigurations": [
        {"toolName": "aria_banking_credit_card___get_credit_card_details",
         "inputSchema": {"type": "object", "properties": {"card_last_four": {"type": "string"}},
                         "required": ["card_last_four"]}},
        {"toolName": "aria_banking_products___analyse_spending",
         "inputSchema": {"type": "object", "properties": {"period": {"type": "string"}}}},
        {"toolName": "aria_banking_debit_card___block_debit_card",
         "inputSchema": {"type": "object", "properties": {"card_last_four": {"type": "string"}},
                         "required": ["card_last_four"]}},
        {"toolName": "aria_banking_account___get_account_balance",
         "inputSchema": {"type": "object", "properties": {}, "required": ["customer_id"]}}]}}

    def tools(self, config):
        return {t["toolName"]: t for t in config["orchestrationAIAgentConfiguration"]["toolConfigurations"]}

    def test_the_scoped_tools_require_the_customer_and_others_are_untouched(self):
        scoped = tool_scopes.apply(self.CONFIG)
        tools = self.tools(scoped)
        self.assertEqual(tools["aria_banking_credit_card___get_credit_card_details"]["inputSchema"]["required"],
                         ["customer_id", "card_last_four"])
        self.assertEqual(tools["aria_banking_products___analyse_spending"]["inputSchema"]["required"], ["customer_id"])
        self.assertEqual(tools["aria_banking_debit_card___block_debit_card"]["inputSchema"]["required"],
                         ["customer_id", "card_last_four"])
        self.assertEqual(tools["aria_banking_account___get_account_balance"],
                         self.tools(self.CONFIG)["aria_banking_account___get_account_balance"])
        self.assertEqual(tool_scopes.apply(scoped), scoped)
        self.assertNotIn("customer_id", self.tools(self.CONFIG)["aria_banking_credit_card___get_credit_card_details"]
                         ["inputSchema"]["properties"], "the input is left as it was")

if __name__ == "__main__":
    unittest.main()
