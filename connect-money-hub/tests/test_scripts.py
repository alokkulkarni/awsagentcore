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


if __name__ == "__main__":
    unittest.main()
