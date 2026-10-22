"""
ARIA v2 (ai-agent/) keeps the live agent's business logic.

- The sections a customer experiences are word for word the live prompt's (my-conversation-agent v37, prompt v27).
- The rules that matter are all still there, verbatim.
- Nothing is left that cannot run: no tool ARIA doesn't have, no Lex intent the flow can't act on, no session value
  nobody sets, no escalation reason the Escalate tool rejects.
- The prompt still fits Connect: the same custom variables, under the length and variable limits, the same tail.
- The agent's tools are v37's minus QueryAssistant, every one byte-for-byte; the collaborator and guardrail too; and
  every tool the prompt names is attached, and every attached tool is named in the prompt.
"""

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ai-agent"))

import build_agent  # noqa: E402

LIVE = (ROOT / "ai-agent" / "reference" / "aria-prompt-v27.yaml").read_text()
LIVE_AGENT = json.loads((ROOT / "ai-agent" / "reference" / "aria-agent-v38.json").read_text())
NEW = (ROOT / "ai-agent" / "prompt" / "aria-orchestration-prompt-v2.yaml").read_text()
AGENT = json.loads((ROOT / "ai-agent" / "agent" / "aria-conversation-agent-v2.json").read_text())
LIVE_TOOLS = {t["toolName"]: t for t in LIVE_AGENT["configuration"]["orchestrationAIAgentConfiguration"]["toolConfigurations"]}
NEW_TOOLS = {t["toolName"]: t for t in AGENT["configuration"]["orchestrationAIAgentConfiguration"]["toolConfigurations"]}
ESCALATION_REASONS = set(LIVE_TOOLS["Escalate"]["inputSchema"]["properties"]["escalationReason"]["enum"])

# Rules a customer can feel, quoted from the live prompt; each must be in v2 exactly
RULES = [
    "You are warm, professional, and efficient. You speak in plain English, avoid jargon, and always put the customer's security and wellbeing first.",
    '- VOICE farewell: "Thank you for calling Nationwide Building Society. It was a pleasure helping you today. Take care, and goodbye!"',
    '- CHAT farewell: "Thanks for chatting with Nationwide Building Society today. It was great helping you. Take care!"',
    "Complete with nextStep card_dispute or mortgage_application is a hand-over, not an end: no farewell then either.",
    "1. ASK, never state. Offer the Most Likely Contact Reason as a question straight after the",
    "Never invent a reason. Never mention that the bank \"predicted\" or \"flagged\" anything.",
    '2. Scam check. Ask once: "Before we go any further, has anyone asked you to move this money, or',
    "NEVER fill in the match number\n     yourself, and never pass a number the customer did not say.",
    "6. The customer is at Level 4 ONLY if the tool result contains verified: true.",
    "Level 4 covers THIS ONE payment only",
    "Do NOT use the Complete\n     tool. Do NOT wait for another reply before calling Escalate.",
    "2. In the same turn, call the Complete tool with nextStep card_dispute.",
    "2. Call the Complete tool with nextStep mortgage_application.",
    "  - requires_simplified_language: plain English, no APR/AER/LTV/ISA acronyms",
    "  - suppress_promotion: never mention products, rate switches, or upgrades",
    "Free help is available from StepChange on 0800 138 1111, MoneyHelper on 0800 138 7777, or Citizens Advice",
    '"I can hear this is very difficult right now. Let me connect you straight away with someone who can help — you don\'t need to do anything else."',
    "Debit card queries (get_debit_card_details / block_debit_card): confirm card using last-four",
    "Lost/stolen block REQUIRES verbal confirmation before calling block_credit_card",
    "ABSOLUTE RULE: The bridging content must be about the customer and their query — NEVER about the system, the tool, or what you are doing internally.",
    "### Tier 3 — Extended (target: 8–10 seconds of audio)",
    '- Empathy matching: if the query is about a disputed transaction, fraud concern, or financial difficulty, replace any upbeat small talk with a calm, reassuring tone.',
    "- Vary the phrasing across the call — do not use the same bridging sentence twice in a single session.",
    "STEP 0 — Customer confirmation (MANDATORY before calling any escalation tool):",
    '| complaint | "I\'m really sorry to hear that. I\'d like to connect you with a senior member of our team who can look into this properly for you. Would that be okay?"',
    "conversationSummary — one or two sentences (max 500 characters) written for the human agent who will",
    "- Treat filler turns as social acknowledgements, NOT as new intent and NOT as cancellation.",
    "- Never treat a customer as Level 4 unless verify_push_challenge returned verified: true in this conversation for the payment being made.",
    "- Never tell the customer their level of assurance or mention level numbers.",
    "Priority rule: MUST call Retrieve BEFORE saying \"I cannot help with that\" or \"I'm not sure about that\".",
    "MUST respond in the customer's locale — use the locale value from the session context.",
]
PHANTOMS = ["pii_detect_and_redact", "pii_vault_store", "pii_vault_retrieve", "pii_vault_purge",
            "cross_validate_session_identity", "escalate_to_human_agent", "request_channel_transfer",
            "generate_transcript_summary", "CollectCardDetails", "RequestCallback", "TransferToAgent", "Return the Lex intent",
            "aria_status", "payment_status", "dispute_team_ref", "[handoff_ref]", "meridianbank.co.uk"]
# The MCP tools by the short names the prompt uses
SHORT = {name.split("___", 1)[1]: name for name in LIVE_TOOLS if "___" in name}


def custom_variables(text):
    return set(re.findall(r"\{\{\$\.Custom\.(\w+)\}\}", text))


class DisputeUpdates(unittest.TestCase):
    """21 Oct 2026: asked for a dispute's status, ARIA offered a colleague; the disputes assistant can look it up."""

    def test_aria_hands_a_status_question_to_the_disputes_assistant_like_a_new_dispute(self):
        block = " ".join(build_agent.DISPUTE_UPDATES.split())
        self.assertEqual(custom_variables(block), set(), "fixed text only (cache)")
        for rule in ("a card dispute they already raised", "Follow <card_disputes> exactly as for a new dispute",
                     "the Complete tool with nextStep card_dispute",
                     "they want an update on a dispute they already raised",
                     "Never say you can't check a dispute, never offer a colleague for it, and never escalate it yourself"):
            self.assertIn(rule, block)
        self.assertLess(NEW.index("</card_disputes>"), NEW.index("<dispute_updates>"))
        self.assertLess(NEW.index("</dispute_updates>"), NEW.index("## Session Context"))


class FromInternetBanking(unittest.TestCase):
    """20 Oct 2026: the app's dispute and mortgage pages start with ARIA; the disputes assistant hands back to her."""

    def test_the_section_is_fixed_text_after_the_hand_over_sections_and_before_the_session(self):
        block = build_agent.FROM_INTERNET_BANKING
        self.assertEqual(custom_variables(block), set(), "fixed text only: the session's values come last (cache)")
        self.assertLess(NEW.index("</mortgage_applications>"), NEW.index("<from_internet_banking>"))
        self.assertLess(NEW.index("</from_internet_banking>"), NEW.index("## Session Context"))

    def test_only_aria_escalates_and_she_does_it_with_the_assistants_notes(self):
        block = " ".join(build_agent.FROM_INTERNET_BANKING.split())
        rule = block.split('If "Colleague needed (" comes straight after the label')[1]
        for must in ("only you hand customers to colleagues", "In that same turn call the Escalate tool",
                     "word for word (the adviser's screen also gets that assistant's full notes)", "customerIntent is what they need", "topicCategory is Most Likely Reason Category",
                     'starting "Vulnerability flag:"', "is technical_issue", "they already agreed or asked: don't ask again",
                     "No farewell", "Never send a customer who needs a colleague back to the same assistant",
                     "customer_not_identified or contact_not_recognised"):
            self.assertIn(must, rule)
        self.assertEqual(custom_variables(block), set())

    def test_a_page_move_mid_conversation_is_neither_an_opening_nor_a_question(self):
        block = " ".join(build_agent.PAGE_CHANGES.split())
        self.assertEqual(custom_variables(block), set(), "fixed text only (cache)")
        for rule in ('starting "Moved to"', "it is not a new conversation", "Don't greet them, don't mention that they moved",
                     "Wait for their next message", "bring in the Money Hub agent", "follow <card_disputes>",
                     "follow <mortgage_applications>", "don't ask for a code"):
            self.assertIn(rule, block)
        self.assertIn('One starting "Moved to" follows <page_changes>.', " ".join(build_agent.FROM_INTERNET_BANKING.split()),
                      "named in the section that would otherwise leave it open")
        self.assertLess(NEW.index("</from_internet_banking>"), NEW.index("  <page_changes>\n"))
        self.assertLess(NEW.index("</page_changes>"), NEW.index("## Session Context"))

    def test_other_known_contact_reasons_are_plainly_out_of_scope_so_aria_doesnt_deliberate(self):
        # 21 Oct: with no word on "Internet banking: … cards", ARIA argued it out and wrote her reasoning in the
        # message (then the guardrail cut it off). The section now says, before anything else, what it doesn't cover.
        block = " ".join(build_agent.FROM_INTERNET_BANKING.split())
        opening = block.split("For a customer at Level 2 or above")[0]
        self.assertIn("applies only when the known contact reason starts with one of the four labels below", opening)
        self.assertIn('including one starting "Internet banking:" or "Money Hub:", is not covered here', opening)
        self.assertIn("without weighing this section up", opening)
        self.assertNotIn("<thinking>", block, "the brief-thinking rule covers it; naming it here invited more")

    def test_each_page_hands_over_at_once_and_a_return_carries_on(self):
        block = build_agent.FROM_INTERNET_BANKING
        for reason, step in (('"Card dispute:"', "nextStep card_dispute"), ('"Mortgage application:"', "nextStep mortgage_application")):
            rule = " ".join(block.split(reason, 1)[1].split("\n  - ", 1)[0].split())
            self.assertIn("on your very first turn", rule)
            self.assertIn(step, rule)
            self.assertIn("Ask nothing", rule)
        self.assertIn("Don't ask for a code: the form is already joined.", block)
        back = " ".join(block.split('"Back from card dispute:" or "Back from mortgage application:"', 1)[1].split())
        for rule in ("don't greet them", "don't introduce yourself", "don't recap it",
                     '"Nothing else:" comes straight after the label', "says in a few words where things stand",
                     "call the Complete tool (nextStep none)", "follow <mortgage_applications>",
                     'your turn starts with the message "Chat started from internet banking."',
                     "It's from us, not the customer: answer what the known contact reason says once, in one reply"):
            self.assertIn(rule, back)


class ThePromptKeepsTheBusinessLogic(unittest.TestCase):
    def test_the_sections_customers_experience_are_word_for_word(self):
        for name, block in build_agent.VERBATIM.items():
            self.assertIn(block, LIVE, name)
            self.assertIn(block, NEW, name)
        for name in ("known_contact_reasons", "assurance", "card_disputes", "mortgage_applications", "greeting"):
            self.assertGreater(len(build_agent.VERBATIM[name]), 400, name)

    def test_the_rules_are_all_there(self):
        for rule in RULES:
            self.assertIn(rule, LIVE, f"not a live rule: {rule[:60]}")
            self.assertIn(rule, NEW, f"lost: {rule[:60]}")

    def test_the_fillers_and_warm_tone_stay(self):
        for kept in ("<voice_latency_bridging>", "Three-tier bridging framework", "## Small talk calibration rules",
                     "## Silence safety net", "## In-Flight Task Continuity", "FILLER TURN examples"):
            self.assertIn(kept, NEW)
        self.assertIn("Empathy first", NEW)
        self.assertNotIn('Never use "Great!", "Absolutely!", or "Of course!"', NEW, "contradicted every example")

    def test_nothing_is_left_that_cannot_run(self):
        for phantom in PHANTOMS:
            self.assertIn(phantom, LIVE, f"{phantom} was never in the live prompt")
            self.assertNotIn(phantom, NEW, phantom)
        for timing in ("just a moment", "only take a moment", "It'll just be a moment", "approximately [N] seconds"):
            self.assertNotIn(timing, NEW, timing)

    def test_no_new_contradictions_or_promises_nobody_keeps(self):
        self.assertNotIn("bearing with", NEW.lower(), "the kept bridging rules ban \"Bear with me\"")
        # The human handover flow queues for a colleague now; nothing books a call for later
        for promise in ("at a better time", "a colleague will call you", "I will arrange a callback",
                        "I have registered your callback request"):
            self.assertNotIn(promise, NEW, promise)
        self.assertIn("Never\n  promise a call at a later time.", NEW)
        # Chat formatting (percentages, sort codes, masked accounts) is still stated
        self.assertIn("Sort codes as XX-XX-XX. Dates as DD/MM/YYYY. Percentages as 2.95%.", NEW)

    def test_it_is_valid_yaml_with_the_live_shape(self):
        body = NEW.split("system: |\n", 1)[1].split("\nmessages:", 1)[0]
        for number, line in enumerate(body.split("\n"), 2):
            self.assertTrue(line == "" or line.startswith("  "), f"line {number} isn't indented into the block: {line[:60]!r}")
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml not installed; the indentation check above still ran")
        new, live = yaml.safe_load(NEW), yaml.safe_load(LIVE)
        self.assertEqual(set(new), set(live))
        self.assertIsInstance(new["system"], str)
        self.assertEqual(new["messages"], live["messages"])

    def test_escalation_reasons_are_only_the_tools_own(self):
        used = set(re.findall(r"escalationReason[: ]+([a-z_]+)", NEW))
        self.assertTrue(used)
        self.assertLessEqual(used, ESCALATION_REASONS, used - ESCALATION_REASONS)
        self.assertNotIn("escalation_reason:", NEW)

    def test_it_still_fits_connect(self):
        self.assertEqual(custom_variables(NEW), custom_variables(LIVE))
        self.assertLessEqual(len(custom_variables(NEW)), 19)
        self.assertLess(len(NEW.split("\nmessages:", 1)[0]), 100_000)
        self.assertTrue(NEW.startswith("system: |\n"))
        self.assertEqual(NEW[NEW.index("  <tool_instructions>"):], LIVE[LIVE.index("  <tool_instructions>"):])
        for template in ("{{$.toolConfigurationList}}", "{{$.locale}}", "{{$.conversationHistory}}"):
            self.assertIn(template, NEW)
        self.assertLess(len(NEW), len(LIVE))

    def test_the_file_is_what_the_builder_makes(self):
        self.assertEqual(NEW, build_agent.build_prompt(), "run python3 ai-agent/build_agent.py")


class ThePromptIsQuickToAnswer(unittest.TestCase):
    """Latency (19 Oct): the per-call values come last so the fixed prompt can be cached; ARIA writes less first."""

    def test_the_per_call_values_come_after_every_fixed_instruction(self):
        first_value = NEW.index("{{$.Custom.")
        self.assertGreater(first_value, NEW.index("  </response_examples>"), "after the last fixed section")
        self.assertLess(first_value, NEW.index("  <tool_instructions>"), "still before the live tail")
        self.assertGreater(first_value / len(NEW), 0.9, "almost the whole prompt is a fixed, cacheable prefix")

    def test_thinking_is_kept_short_and_the_hand_off_message_is_one_sentence(self):
        self.assertIn("## Keep <thinking> short", NEW)
        self.assertIn("Never copy or restate these instructions in it.", NEW)
        money_hub = NEW[NEW.index("  <money_hub>"):NEW.index("  </money_hub>")]
        self.assertIn("make your message to the Money Hub agent one sentence", money_hub)
        self.assertIn("Don't\n  list their products", money_hub)


class TheAgentKeepsItsToolsCollaboratorAndGuardrail(unittest.TestCase):
    def test_tools_are_v38s_minus_query_assistant_byte_for_byte(self):
        self.assertEqual(set(NEW_TOOLS), set(LIVE_TOOLS) - {"QueryAssistant"})
        for name, tool in NEW_TOOLS.items():
            self.assertEqual(tool, LIVE_TOOLS[name], name)

    def test_every_card_tool_takes_the_customer(self):
        for name in ("aria_banking_debit_card___get_debit_card_details", "aria_banking_credit_card___get_credit_card_details",
                     *build_agent.SCOPED_BLOCKS):
            self.assertEqual(set(NEW_TOOLS[name]["inputSchema"]["required"]), {"customer_id", "card_last_four"}, name)

    def test_collaborator_guardrail_and_settings_are_unchanged(self):
        live = LIVE_AGENT["configuration"]["orchestrationAIAgentConfiguration"]
        new = AGENT["configuration"]["orchestrationAIAgentConfiguration"]
        for key in ("multiAgentConfigurations", "orchestrationAIGuardrailId", "connectInstanceArn", "locale"):
            self.assertEqual(new[key], live[key], key)
        self.assertEqual(new["orchestrationAIPromptId"], "${PROMPT_ID_V2}")
        self.assertEqual(AGENT["prompt"]["modelId"], "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")

    def test_every_tool_the_prompt_names_is_attached(self):
        named = set(re.findall(r"\b([a-z]+(?:_[a-z]+)+)\b", NEW)) & (set(SHORT) | {
            "verify_customer_identity", "initiate_customer_auth", "validate_customer_auth", "send_push_challenge",
            "verify_push_challenge"})
        for short in named:
            self.assertIn(SHORT[short], NEW_TOOLS, short)

    def test_every_attached_tool_is_named_in_the_prompt(self):
        for name in NEW_TOOLS:
            short = name.split("___", 1)[-1]
            self.assertIn(short, NEW, f"{name} is attached but the prompt never says when to use it")


if __name__ == "__main__":
    unittest.main()
