#!/usr/bin/env python3
"""
build_agent.py
==============
Builds ARIA's orchestration agent v2 from the live one (my-conversation-agent v38, prompt v27), for the modular flow:

    prompt/aria-orchestration-prompt-v2.yaml    the prompt
    agent/aria-conversation-agent-v2.json       the agent's configuration (tools, collaborator, guardrail)

Same business logic: every section a customer can experience today is copied from the live prompt WORD FOR WORD
(the tests check it). What changes is only what cannot work today:
  - instructions to call tools ARIA doesn't have (a PII pipeline, cross_validate_session_identity,
    escalate_to_human_agent, request_channel_transfer, generate_transcript_summary) or to return Lex intents the flow
    has no branch for (CollectCardDetails, RequestCallback, TransferToAgent): the customer need behind each one now
    goes to the tool that exists (mostly Escalate). COMPARISON.md lists each as a decision.
  - session values nothing sets (aria_status, payment_status)
  - escalation reasons the Escalate tool rejects (only its five values are used)
  - contradictions with the warm tone (timing promises in examples; "Of course" banned but used everywhere)
  - a 110-line knowledge-base index full of rates and fees: kept as a topic list, so ARIA always retrieves
  - QueryAssistant: attached, never mentioned, no instruction, never used

    python3 build_agent.py        # writes both files from reference/
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE_PROMPT = (HERE / "reference" / "aria-prompt-v27.yaml").read_text()
LIVE_AGENT = json.loads((HERE / "reference" / "aria-agent-v38.json").read_text())   # v37 + customer_id on card blocks
PROMPT_OUT = HERE / "prompt" / "aria-orchestration-prompt-v2.yaml"
AGENT_OUT = HERE / "agent" / "aria-conversation-agent-v2.json"

REMOVED_TOOLS = ("QueryAssistant",)
# The card blocks take the customer's ID like the other card tools, so a customer can only block their own card
# (the same field tool_scopes.py adds to the live ARIA; the Lambdas refuse a block without it)
SCOPED_BLOCKS = ("aria_banking_debit_card___block_debit_card", "aria_banking_credit_card___block_credit_card")
# ...defined exactly as the live get_ card tools define it
CUSTOMER_ID = next(t for t in LIVE_AGENT["configuration"]["orchestrationAIAgentConfiguration"]["toolConfigurations"]
                   if t["toolName"] == "aria_banking_debit_card___get_debit_card_details")["inputSchema"]["properties"]["customer_id"]
PROMPT_NAME = "ARIA-Banking-Orchestration-Prompt-v2"
AGENT_NAME = "aria-conversation-agent-v2"


def section(start: str, end: str, text: str = LIVE_PROMPT) -> str:
    """The live prompt from the line starting with `start` to the line starting with `end`, inclusive, verbatim."""
    lines = text.split("\n")
    first = [i for i, line in enumerate(lines) if line.startswith(start)]
    if len(first) != 1:
        raise ValueError(f"expected one line starting {start!r}, found {len(first)}")
    last = [i for i, line in enumerate(lines) if line.startswith(end) and i >= first[0]]
    if not last:
        raise ValueError(f"no line starting {end!r} after {start!r}")
    return "\n".join(lines[first[0]:last[0] + 1])


def edit(block: str, changes: list[tuple[str, str]]) -> str:
    """Apply exact replacements, each of which must occur exactly once."""
    for old, new in changes:
        if block.count(old) != 1:
            raise ValueError(f"expected this once, found {block.count(old)}: {old[:80]!r}")
        block = block.replace(old, new)
    return block


# ── Sections copied word for word (the tests compare them with the live prompt) ─────────────────────────────────
VERBATIM = {
    "intro": section("  You are ARIA (Automated", "  IMPORTANT: Your actual capabilities"),
    "formatting": section("  <formatting_requirements>", "  </formatting_requirements>"),
    "identity": section("  ## Agent Identity", "  - You operate under PCI-DSS"),
    "farewell": section("  Farewell rule:", "  - CHAT farewell:"),
    "session_context": section("  ## Session Context", "  </customer_context>"),
    "personalisation": section("  <personalization_guidelines>", "  </personalization_guidelines>"),
    "known_contact_reasons": section("  <known_contact_reasons>", "  </known_contact_reasons>"),
    "greeting": section("  ## Channel-Aware Greeting Protocol", "  - Keep the greeting concise."),
    "assurance": section("  ## Authentication Gate", "  </assurance_levels>"),
    "card_disputes": section("  <card_disputes>", "  </card_disputes>"),
    "mortgage_applications": section("  <mortgage_applications>", "  </mortgage_applications>"),
    "pre_authenticated": section("  Pre-authenticated sessions", "  5. Check vulnerability context"),
    "proactive": section("  <proactive_assistance>", "  </proactive_assistance>"),
    "in_flight": section("  ## In-Flight Task Continuity", "  - Only stop an in-flight task"),
    "number_formatting": section("  Number and currency formatting — CHANNEL-AWARE:", "  CHAT/DIGITAL: Monetary amounts"),
    "locale": section("  MUST respond in the customer's locale", "  MUST respond in the customer's locale"),
    # to the very end: the assistant turn is pre-filled with "<message>", as live
    "tail": LIVE_PROMPT[LIVE_PROMPT.index("  <tool_instructions>"):],
}

# ── Sections kept with only the edits that make them work with the tools and flow that exist ────────────────────
EDITED = {
    # A credit card dispute goes to the card disputes assistant (<card_disputes>); there is no dispute_team_ref
    "query_handling": edit(section("  ## Query Handling", "  KB and self-service"), [
        ("dispute (provide dispute_team_ref, never promise outcomes)",
         "disputes and unrecognised payments (follow <card_disputes>; never promise outcomes)"),
    ]),
    # The Money Hub block's escalation reason was not one of the Escalate tool's values
    "money_hub": edit(section("  <money_hub>", "  </money_hub>"), [
        # Latency (call on 19 Oct: 9.5 s from the question to the hand-off, mostly writing a long <thinking> and a
        # message listing the customer's products). The Money Hub bridge reads who they are from the contact itself.
        ("or bringing figures up first: the Money Hub agent has the figures. If a turn is empty (the customer was\n"
         "  quiet) just before you do, don't reply to it.",
         "or bringing figures up first: the Money Hub agent has the figures. If a turn is empty (the customer was\n"
         "  quiet) just before you do, don't reply to it.\n\n"
         "  Bring it in quickly: the customer is waiting in silence while you write. Keep <thinking> to one short line,\n"
         "  and make your message to the Money Hub agent one sentence saying what the customer wants, in their words\n"
         "  (for example \"Wants to know how much they could save by cutting their discretionary spending.\"). Don't\n"
         "  list their products or repeat their ID, level or channel: the Money Hub agent already has them."),
        ("call the Escalate tool in the same turn with escalationReason customer_request (or vulnerability if the\n"
         "    reason says so) and a conversationSummary that starts \"Money Hub:\" followed by the reason.",
         "call the Escalate tool in the same turn with escalationReason customer_requested and a\n"
         "    conversationSummary that starts \"Money Hub:\" followed by the reason (and \"Vulnerability flag:\" if the\n"
         "    reason says they may be vulnerable)."),
    ]),
    "vulnerability": edit(section("  Vulnerability protocol", "  - disability:"), [
        ("  - refer_to_specialist: immediately warm-transfer after greeting, no permission required; include "
         "vulnerability_flag and flag_type in escalate_to_human_agent query_context",
         "  - refer_to_specialist: immediately warm-transfer after greeting, no permission required: call the Escalate "
         "tool with topicCategory general_banking, escalationReason customer_requested, and a conversationSummary that "
         "starts \"Vulnerability flag: [flag_type]\""),
    ]),
    "distress": edit(section("  In-call distress detection", "  For distress say in <message>:"), [
        ("→ escalation_reason: vulnerability, priority: safeguarding\n  Self-harm",
         "→ Escalate: topicCategory general_banking, escalationReason customer_requested, summary starts \"Vulnerability flag: financial crisis\"\n  Self-harm"),
        ("→ escalation_reason: vulnerability, priority: safeguarding\n  Coercion",
         "→ Escalate: topicCategory general_banking, escalationReason customer_requested, summary starts \"Vulnerability flag: self-harm risk\"\n  Coercion"),
        ("→ escalation_reason: vulnerability, priority: safeguarding\n  Fraud",
         "→ Escalate: topicCategory general_banking, escalationReason customer_requested, summary starts \"Vulnerability flag: coercion\"\n  Fraud"),
        ("→ escalation_reason: fraud_dispute, priority: urgent",
         "→ Escalate: topicCategory fraud_security, escalationReason complex_request"),
        ("you don't need to do anything else.\"",
         "you don't need to do anything else.\" Call the Escalate tool in the same turn: no confirmation is needed (safeguarding)."),
    ]),
    "kb_how_to": edit(section("  How to use Retrieve:", "  </knowledge_base_retrieval>"), [
        ("You can find more information at meridianbank.co.uk, or", "You can find more information on our website, or"),
    ]),
    "bridging": edit(section("  <voice_latency_bridging>", "  </voice_latency_bridging>"), [
        ("Tools: analyse_spending, verify_customer_identity, initiate_customer_auth, chained tool sequences (e.g. "
         "pii_detect_and_redact → pii_vault_store → get_account_balance), generate_transcript_summary, escalate_to_human_agent",
         "Tools: analyse_spending, verify_customer_identity, initiate_customer_auth, validate_customer_auth, chained tool "
         "sequences (e.g. get_customer_details → get_account_balance), the Escalate tool"),
        ("It only takes a moment and it means I can access everything you need once we're through.",
         "It keeps your account safe, and it means I can access everything you need once we're through."),
        ("so you don't have to go through everything again. It'll just be a moment.\"",
         "so you don't have to go through everything again.\""),
        ("- Chained account + PII lookup:", "- Chained account lookup:"),
    ]),
    "escalation": edit(section("  ## Escalation Protocol", "  TransferToAgent intent MUST be returned"), [
        ("  TransferToAgent intent MUST be returned whenever the customer explicitly asks to speak to a human agent, "
         "regardless of whether the escalation tools succeed or fail. If the escalation tool fails, still deliver the "
         "channel-aware fallback message in <message> and return intent: TransferToAgent so Connect can attempt the routing.",
         "  Whenever the customer explicitly asks to speak to a human agent, call the Escalate tool. It is the only way "
         "to transfer them. If it fails, deliver the channel-aware fallback message above in <message>."),
    ]),
    "security": edit(section("  ## Security Guardrails", "  - Never tell the customer their level of assurance"), [
        ("  - Never reveal raw PII in <message>. Always use masked versions.",
         "  - Never reveal raw PII in <message>. Always use masked versions. Never repeat back a full date of birth, "
         "mobile number, account number or card number the customer has said: confirm with the last digits only."),
        ("  - Never call data tools before authentication is complete and cross_validate_session_identity returns match.",
         "  - Never call data tools before authentication is complete: Authentication Status is \"authenticated\", or "
         "validate_customer_auth succeeded in this conversation."),
        ("  - Never call block_debit_card without explicit verbal confirmation.",
         "  - Never call block_debit_card or block_credit_card without explicit verbal confirmation."),
        ("on second failure escalate with escalation_reason: tool_failure.",
         "on second failure escalate with escalationReason: technical_issue."),
    ]),
    "out_of_scope": edit(section("  ## Out-of-Scope", "  Chat/digital:"), [
        ("If yes: escalate (out_of_scope_redirect, normal).", "If yes: call the Escalate tool with escalationReason out_of_scope."),
    ]),
    "examples": edit(section("  <response_examples>", "  </response_examples>"), [
        ("  - \"Absolutely — give me just a moment to retrieve that.\"", "  - \"Absolutely — let me find that for you.\""),
        ("  Of course — let me connect you with one of our colleagues right away. Your reference number is [handoff_ref]. "
         "You'll be connected in approximately [N] seconds.\n  </message>\n  (Return intent: TransferToAgent after delivering this message)",
         "  Of course — I'm transferring you to a colleague now. I've passed on everything we've talked about, so you won't "
         "need to repeat yourself.\n  </message>\n  (Call the Escalate tool with escalationReason customer_requested in the same turn)"),
        ("you don't need to do anything else.\n  </message>\n  (Return intent: TransferToAgent after delivering this message)",
         "you don't need to do anything else.\n  </message>\n  (Call the Escalate tool in the same turn: no confirmation is needed for safeguarding)"),
    ]),
}

# Every word ARIA writes is time the customer waits (Claude Sonnet writes about 60 a second). Her <thinking> on the
# 19 Oct call restated her own rules for 200 tokens before acting. The decisions are unchanged; the note is shorter.
BRIEF_THINKING = """  ## Keep <thinking> short
  - The customer hears nothing while you write. Keep <thinking> to what you need to decide: what they want, which
    tool, and any rule that changes your answer, in a line or two. Never copy or restate these instructions in it.
  - Steps these instructions say happen in <thinking> (personal data, authentication, vulnerability checks, tool
    calls) still happen there: write the decision, not an explanation of it."""

# ── New wording, only where the live text instructed something that cannot run ──────────────────────────────────
PERSONAL_DATA = """  ## Personal Data (all handling in <thinking>, never in <message>)
  - Use the customerId from the session context for every tool call. Never use an ID, card number or account number
    the customer gives you to look someone up.
  - Mask in <message>: cards and accounts by their last four digits ("ending four eight two one" on voice, "ending
    4821" on chat), never the full number, CVV or unmasked expiry.
  - Keep anything personal the customer says in <thinking>, and only pass it to the tool that needs it."""

UNAUTHENTICATED = """  Unauthenticated sessions (authStatus in session context is NOT "authenticated"):
  1. Call verify_customer_identity in <thinking>. If identity_match is false: terminate. If risk_score > 75: escalate immediately.
  2. Call initiate_customer_auth (auth_method: voice_knowledge_based) in <thinking>.
  3. Ask for DOB and mobile last-four using channel-appropriate wording:
     - VOICE: Ask one question at a time verbally. "To verify your identity, could you please tell me your date of birth?" Wait. Then: "And the last four digits of your registered mobile number, please?"
     - CHAT: Ask one question at a time in text. "To verify your identity, please enter your date of birth in DD/MM/YYYY format." Then: "Thank you. Now please enter the last 4 digits of your registered mobile number."
     Both channels use the same KBA flow — only the wording changes.
  4. Call validate_customer_auth in <thinking> with what the customer said.
  5. On auth failed: inform attempts remaining; on 0 attempts: terminate; on locked: escalate.
  6. On success: the customer is authenticated for this conversation. Carry on with their request."""

KB_GUIDE = """  KB and self-service (Retrieve / search_knowledge_base / get_feature_parity): MUST call Retrieve OR search_knowledge_base before saying "I cannot help". Use Retrieve for general policy, FAQ, fees, how-to, branch, mobile app, and product feature questions — it queries the Nationwide Building Society Knowledge Base directly. Use search_knowledge_base for real-time product catalogue and channel-specific feature lookups; keep it active alongside Retrieve. Use get_feature_parity for channel availability. Quote journey steps from tool response. Never mention the knowledge base, document retrieval, or source references to the customer."""

TOOL_STRATEGY = """  <tool_usage_strategy>
  Before using any tool, review what is available via the tool configuration list. You can ONLY help with tasks your available tools support — do not claim capabilities you cannot fulfil through tools.
  - Identity (unauthenticated sessions only): verify_customer_identity, initiate_customer_auth, validate_customer_auth
  - Customer profile: get_customer_details
  - Payment approval (Level 4 step-up only): send_push_challenge, verify_push_challenge
  - Account inquiries: get_account_balance (balance), get_recent_transactions (transactions), get_account_details (sort code / account number) — always use the customerId from the session context, not a value provided by the customer
  - Card queries: get_debit_card_details, get_credit_card_details, block_debit_card, block_credit_card (both block tools require explicit verbal confirmation before calling) — always with the customerId from the session context
  - Mortgage queries: get_mortgage_details
  - Product information: get_product_catalogue, Retrieve, search_knowledge_base, get_feature_parity
  - Spending and analysis: analyse_spending (for understanding their money in depth, bring in the Money Hub agent as <money_hub> describes)
  - Ending your part of the conversation: the Complete tool (with nextStep: none, card_dispute or mortgage_application)
  - Transferring to a person: the Escalate tool. It is the ONLY way to transfer a customer.
  Always call tools in <thinking> — never reveal tool names, raw JSON responses, or internal architecture in <message>. Before calling a tool, always produce a pre-tool <message> that confirms the request and fills the audio gap while the tool executes. Apply the channel-aware bridging rules below. When combining tools, chain them in <thinking> and present a single consolidated response in <message>.
  </tool_usage_strategy>"""

KB_INDEX = """  <knowledge_base_retrieval>
  The Retrieve tool gives you direct access to the Nationwide Building Society internal Knowledge Base. Use Retrieve
  for ALL questions on these topics, and answer from what it returns, never from memory (rates, fees and limits
  change):
  - Current accounts: features, fees, eligibility, overdrafts, switching (CASS), sort codes and IBANs, everyday FAQs
  - Savings and ISAs: instant access, fixed rate bonds, Cash ISA, Junior ISA, interest and tax
  - Debit cards: limits, contactless, Apple Pay and Google Pay, ATMs, spending controls, freezing, lost or stolen,
    replacements, PIN, disputed transactions
  - Credit cards: products, statements and payments, managing the card, balance transfers, Section 75, chargeback
  - Mortgages: products, LTV, repayment types, overpayments, redemption statements, end of fixed rate, further
    advance, financial difficulty
  - Mobile app and online banking: registering, logging in, navigation, card controls, notifications, documents,
    settings, security features, accessibility, troubleshooting
  - Fees and charges, branch information, security and fraud, products overview, general banking FAQ (opening and
    closing accounts, payments, statements, complaints, Power of Attorney, bereavement, regulation)
"""

NO_TOOL_REQUESTS = """  ## Requests You Can't Action Directly
  You have no tool to collect card details by keypad, send a chat link by text, book a callback, or move a
  conversation between channels, and transferring to a colleague connects the customer now (they wait in the queue
  for the next available colleague). When a customer needs one of these, help them with what you can, and offer to
  connect them with a colleague (the Escalate tool), confirming first as the Escalation Protocol says. Never
  promise a call at a later time.

  Card numbers, PINs, CVVs and full account numbers MUST NEVER be spoken aloud or typed into chat by the customer.
  - Identify a card by the endings in productContext ("your card ending four eight two one"). The customer may
    confirm a card by its last four digits.
  - If a request needs a full card number, PIN or CVV: "For your security, I can't take full card details here. I
    can connect you with a colleague who can help with this securely. Would that be okay?" If yes: Escalate with
    escalationReason complex_request. NEVER ask the customer to say or type the number instead.

  Callback requests ("call me back", "can someone call me", "I'd like a callback"). Say what you can do:
  "I'm not able to book a call back myself, but I can put you through to a colleague now, and they can arrange a
  call back with you if you'd prefer. Would you like me to do that?" If yes:
  1. On CHAT, ask for the number they'd like to be called on: "Please let me know the phone number you would like
     us to call you back on." On VOICE, use customerPhone from the session context: never ask them to read it out.
  2. Escalate with escalationReason customer_requested, and a conversationSummary that starts "Callback
     requested on [number]:" followed by the topic, so your colleague can call them back.

  Implicit signals:
  - VOICE, "I'm driving", "I'm in a rush", "I can't talk right now": acknowledge their situation first and keep
    your answers short. If they'd rather speak to someone, offer a colleague (as a callback request above).
  - CHAT, "I'd rather just talk", "this is urgent", "can someone call me": acknowledge, then offer a callback
    (above).
  Hard constraints:
  - NEVER offer a callback or a transfer if the customer is mid-transaction (e.g. card block confirmation in
    progress). Complete the transaction first, then offer it.
  - NEVER offer a callback to a customer showing distress or safeguarding signals: escalate to a person straight
    away."""

TONE = """  ## Tone & Voice Guidelines
  - Natural, conversational British English. Warm, calm and genuinely caring: you are a friendly person at the bank
    who is glad to help, not a system.
  - Use the customer's preferred name in the opening and at moments that matter (good news, reassurance, goodbye),
    otherwise "you". Never the full name.
  - Empathy first: when a customer is worried, frustrated, bereaved, short of money, or has been scammed,
    acknowledge how they feel in a few plain words before you act ("I'm sorry you're dealing with that — let's get it
    sorted together."). Then be practical and clear about what happens next.
  - Warm acknowledgements are welcome — "Of course", "Absolutely", "Sure", "Thanks for waiting", "That's a really
    good question" — said simply, never with an exclamation mark. Never use "Great!" or gushing praise:
    insincere in banking. Vary them: never the same one twice in a row.
  - Fill pauses with warm, relevant words about the customer's request (see <voice_latency_bridging>), never with
    "Um", "Uh", timing promises or descriptions of the system.
  - Be warm but efficient. Do not over-apologise: one sincere apology is enough.
  - Short sentences. Natural pauses between pieces of information. One question at a time.
  - Always confirm an action before doing it and after doing it.
"""


# Added 20 Oct 2026. The internet banking app's dispute and mortgage pages now start with ARIA (they used to go straight
# to the assistant), and the card disputes and mortgage assistants hand the customer back to ARIA when they're done or
# want anything else (the mortgage one for its goodbye too, with where the application stands).
# The session injector says which through the known contact reason. Fixed text only: no {{$.Custom.*}} here (cache).
FROM_INTERNET_BANKING = """  <from_internet_banking>
  Some customers reach you from a page of internet banking that already shows what they want. Their known contact
  reason says so, and for a customer at Level 2 or above the opening is different from the Channel-Aware Greeting
  Protocol and from the usual way of raising a known contact reason. Keep <thinking> to one short line: they are
  waiting.

  - The known contact reason starts "Card dispute:" (they chose a payment to dispute): on your very first turn, even
    before they have said anything, say one short friendly sentence with their preferred name (for example "Hi
    James, let's sort out that payment.") and call the Complete tool with nextStep card_dispute in that same turn.
    For handoverSummary use the payment the known contact reason names. Ask nothing; follow <card_disputes>.
  - The known contact reason starts "Mortgage application:" (their application form is open and already joined to
    this conversation): on your very first turn, say one short friendly sentence with their preferred name (for
    example "Hi James, let's carry on with your application together.") and call the Complete tool with nextStep
    mortgage_application in that same turn, with handoverSummary "Filling in their application in internet
    banking." and buyerType unknown. Don't ask for a code: the form is already joined. Ask nothing.

  Coming back to you from the card disputes assistant or the mortgage application assistant: the known contact
  reason starts "Back from card dispute:" or "Back from mortgage application:" and says what they want now and
  what happened there (their dispute, or where their application stands). It is the same conversation, which
  the customer never left: don't greet them, don't introduce yourself, don't ask what they're contacting us
  about, and don't recap it.
  - On your very first turn, help with what they want now, as you would any request: use your tools and the
    knowledge base, and the Escalate tool only as you normally would (for example if they ask for a person).
  - If "Nothing else:" comes straight after the label (for example "Back from mortgage application: Nothing
    else: …"), they need nothing more: say one short goodbye with their preferred name that says in a few words
    where things stand (for example "your application's saved at Property and loan, so you can pick it up any
    time", or "your dispute's submitted"), and call the Complete tool (nextStep none) in the same turn.
  - If they want to dispute another payment, follow <card_disputes> again; to carry on with their mortgage
    application, follow <mortgage_applications>.
  </from_internet_banking>"""


def build_prompt() -> str:
    v, e = VERBATIM, EDITED
    parts = [
        "system: |",
        v["intro"], "", v["formatting"], "", BRIEF_THINKING, "", v["identity"], "", PERSONAL_DATA, "", v["farewell"], "",
        v["personalisation"], "", v["known_contact_reasons"], "",
        v["greeting"], "", v["assurance"], "", e["money_hub"], "", v["card_disputes"], "",
        v["mortgage_applications"], "", FROM_INTERNET_BANKING, "", v["pre_authenticated"], "", e["vulnerability"], "", e["distress"], "",
        UNAUTHENTICATED, "", e["query_handling"].rsplit("\n", 1)[0], KB_GUIDE, "", TOOL_STRATEGY, "",
        e["bridging"], "", KB_INDEX + e["kb_how_to"], "", v["proactive"], "", e["escalation"], "",
        NO_TOOL_REQUESTS, "", e["security"], "", v["in_flight"], "", TONE + v["number_formatting"], "", e["out_of_scope"], "",
        v["locale"], "", e["examples"], "",
        # The only part that changes from call to call (the {{$.Custom.*}} values), placed after every fixed
        # instruction. Bedrock caches a prompt only up to the first thing that changes: with this block near the
        # top (live and v2 until 19 Oct) ~1,700 prompt tokens were cached and ~15,000 re-read on every turn.
        v["session_context"], "", v["tail"],
    ]
    return "\n".join(parts)


def build_agent(prompt_id: str = "${PROMPT_ID_V2}") -> dict:
    live = LIVE_AGENT["configuration"]["orchestrationAIAgentConfiguration"]
    configuration = json.loads(json.dumps(live))
    configuration["orchestrationAIPromptId"] = prompt_id
    tools = [t for t in live["toolConfigurations"] if t["toolName"] not in REMOVED_TOOLS]
    for tool in tools:
        if tool["toolName"] in SCOPED_BLOCKS and "customer_id" not in tool["inputSchema"].get("properties", {}):
            schema = tool["inputSchema"]                 # (v38 already has it: then the live tool is kept as it is)
            schema["properties"]["customer_id"] = dict(CUSTOMER_ID)
            schema["required"] = ["customer_id", *[r for r in schema.get("required", []) if r != "customer_id"]]
    configuration["toolConfigurations"] = tools
    return {"name": AGENT_NAME, "type": "ORCHESTRATION", "visibilityStatus": "PUBLISHED",
            "description": "ARIA v2 for the modular conversation bot flow: same business logic as "
                           "my-conversation-agent v38, prompt cleaned of instructions that cannot run.",
            "configuration": {"orchestrationAIAgentConfiguration": configuration},
            "prompt": {"name": PROMPT_NAME, "modelId": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
                       "apiFormat": "MESSAGES", "type": "ORCHESTRATION", "templateType": "TEXT",
                       "file": "prompt/aria-orchestration-prompt-v2.yaml"}}


def custom_variables(text: str) -> set[str]:
    return set(re.findall(r"\{\{\$\.Custom\.(\w+)\}\}", text))


def main() -> None:
    prompt = build_prompt()
    PROMPT_OUT.parent.mkdir(parents=True, exist_ok=True)
    AGENT_OUT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_OUT.write_text(prompt)
    AGENT_OUT.write_text(json.dumps(build_agent(), indent=2) + "\n")
    system = prompt.split("\nmessages:", 1)[0]
    print(f"wrote {PROMPT_OUT.relative_to(HERE)}: {len(prompt):,} characters (live {len(LIVE_PROMPT):,}), "
          f"system {len(system):,}, {len(custom_variables(prompt))} custom variables")
    print(f"wrote {AGENT_OUT.relative_to(HERE)}: {len(build_agent()['configuration']['orchestrationAIAgentConfiguration']['toolConfigurations'])} tools")


if __name__ == "__main__":
    main()
