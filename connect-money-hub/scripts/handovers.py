#!/usr/bin/env python3
"""
handovers.py
============
ARIA's hand-overs to the card dispute assistant and the mortgage assistant, in a form that works while ARIA has
collaborators (the Money Hub agent).

Why: once an AI agent has collaborators (multiAgentConfigurations), Connect returns the contact to the flow only
through its reserved Complete and Escalate tools. ARIA's own return-to-control tools, StartCardDispute and
StartMortgageApplication, still run, but nothing hands control back: Lex reports Error and the flow carries on with
ARIA. The traces show it: on ARIA v32+ Complete ends with a return_to_agent span (returnReason COMPLETE);
StartCardDispute on v35 ends with nothing.

So ARIA hands over with Complete, saying where the customer goes next:

    Complete  nextStep=none                   the customer needs nothing else (as before)
              nextStep=card_dispute           + handoverSummary      → card dispute assistant
              nextStep=mortgage_application   + handoverSummary, buyerType, screenCode → mortgage assistant

The fields keep the names the two old tools used, so conversation bot flow's existing blocks read them unchanged
($.Lex.SessionAttributes.handoverSummary …). The flow adds one Compare on $.Lex.SessionAttributes.nextStep after
its Complete branch (README, "Hand-overs while ARIA has collaborators").

Used by collaborator.py (ARIA's tools) and build_aria_prompt.py (ARIA's prompt). It only transforms data.
"""

from __future__ import annotations

import json

RETIRED = ("StartCardDispute", "StartMortgageApplication")
NEXT_STEPS = ("none", "card_dispute", "mortgage_application")

COMPLETE_INSTRUCTION = (
    "Use Complete to end your part of the conversation, with nextStep saying what happens next:\n"
    "- none: the customer has confirmed they need nothing else. Ask whether there's anything else first, unless "
    "<money_hub> says they have already said so.\n"
    "- card_dispute: the customer wants to dispute a card payment or doesn't recognise one, as <card_disputes> "
    "describes. The card disputes assistant takes over. Put everything they've said about the payment in "
    "handoverSummary.\n"
    "- mortgage_application: the customer wants to apply for a new mortgage, as <mortgage_applications> describes. "
    "The mortgage assistant takes over. Put what they want in handoverSummary and their situation in buyerType.\n"
    "With card_dispute or mortgage_application, don't ask whether there's anything else and don't say goodbye: the "
    "conversation carries on with the other assistant."
)

COMPLETE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string", "description": "Reason of completion"},
        "nextStep": {
            "type": "string", "enum": list(NEXT_STEPS),
            "description": "none if the customer needs nothing else; card_dispute or mortgage_application if that "
                           "assistant takes over now.",
        },
        "handoverSummary": {
            "type": "string", "maxLength": 300,
            "description": "Only with card_dispute or mortgage_application. card_dispute: everything the customer has "
                           "already said about the payment, in one sentence: the retailer, roughly how much, when, "
                           "which card, whether they made it, whether they still have the card. No card numbers. "
                           "'Wants to dispute a card payment.' if they have said nothing yet. mortgage_application: "
                           "what they want, e.g. first-time buyer, flat in Leeds, has a deposit. No income or date of "
                           "birth.",
        },
        "buyerType": {
            "type": "string", "enum": ["first_time", "home_mover", "remortgage", "unknown"],
            "description": "Only with mortgage_application: the customer's situation if they said it, otherwise unknown.",
        },
        "screenCode": {
            "type": "string", "pattern": "^\\d{6}$",
            "description": "Only with mortgage_application, and only if the customer quoted the 6-digit help code "
                           "shown on their application screen. Leave it out otherwise.",
        },
    },
    "required": ["reason", "nextStep"],
}


def complete_tool(existing: dict | None = None) -> dict:
    """ARIA's Complete tool, carrying nextStep and the hand-over fields (anything else it had is kept)."""
    tool = {**(existing or {}), "toolName": "Complete", "toolType": "RETURN_TO_CONTROL"}
    tool["description"] = ("Ends your part of the conversation: the customer needs nothing else, or the card "
                           "disputes or mortgage assistant takes over (nextStep).")
    tool["instruction"] = {"instruction": COMPLETE_INSTRUCTION, "examples": [
        "<message>Let's sort that out for you.</message> (Complete, nextStep card_dispute)",
        "<message>Thanks for chatting with Nationwide Building Society today. It was great helping you. Take care!"
        "</message> (Complete, nextStep none)",
    ]}
    tool["inputSchema"] = COMPLETE_SCHEMA
    tool.setdefault("userInteractionConfiguration", {"isUserConfirmationRequired": False})
    return tool


def apply(configuration: dict) -> dict:
    """ARIA's configuration with the two old hand-over tools gone and Complete carrying nextStep."""
    config = json.loads(json.dumps(configuration))
    orchestration = config.setdefault("orchestrationAIAgentConfiguration", {})
    tools = [t for t in orchestration.get("toolConfigurations") or [] if t.get("toolName") not in RETIRED]
    existing = next((t for t in tools if t.get("toolName") == "Complete"), None)
    tools = [t for t in tools if t.get("toolName") != "Complete"] + [complete_tool(existing)]
    orchestration["toolConfigurations"] = tools
    return config


# ── The prompt ───────────────────────────────────────────────────────────────────────────────────────────────────
# Each edit is (what the live prompt says, what it says after). Applying twice changes nothing.

DISPUTE_OLD = "  2. In the same turn, call the StartCardDispute tool. In handoverSummary put,"
DISPUTE_NEW = "  2. In the same turn, call the Complete tool with nextStep card_dispute. In handoverSummary put,"

FAREWELL_OLD = ("NEVER say a farewell when you are transferring or escalating to a colleague: the call is continuing, "
                "not ending.")
FAREWELL_NEW = (FAREWELL_OLD + " Complete with nextStep card_dispute or mortgage_application is a hand-over, not an "
                "end: no farewell then either.")

NEVER_OLD = "  - Never say a farewell or use the Complete tool when handing a customer to a colleague. Use the Escalate tool."
NEVER_NEW = ("  - Never say a farewell or use the Complete tool when handing a customer to a colleague. Use the Escalate "
             "tool. (Passing them to the card disputes or mortgage assistant is not a colleague: that is Complete with "
             "its nextStep, without a farewell.)")

MORTGAGE_SECTION = """
  <mortgage_applications>
  A customer may want to apply for a new mortgage or start a mortgage application. You do not take the
  application. The mortgage assistant does, and works through it with them on screen.

  Use this only for a new application, never for questions about an existing mortgage.

  Your part:
  1. Ask once: "Do you have your application open on screen? If so, there's a 6-digit code under 'Get help by
     phone' - could you read it to me?" If they read one, include it as screenCode (digits only). If they don't
     have it open, carry on without it.
  2. Call the Complete tool with nextStep mortgage_application. In handoverSummary put what they want (for
     example first-time buyer, flat in Leeds, has a deposit; no income or date of birth) and in buyerType their
     situation, or unknown.
  3. In <message> say one short sentence such as "I'll pass you to our mortgage application assistant, who can
     work through it with you on screen." No farewell.
  </mortgage_applications>
"""
MORTGAGE_ANCHOR = "  </card_disputes>\n"


def fix_prompt(prompt: str) -> str:
    """ARIA's prompt with its hand-overs going through Complete (raises if the live prompt has moved on)."""
    for old, new in ((DISPUTE_OLD, DISPUTE_NEW), (FAREWELL_OLD, FAREWELL_NEW), (NEVER_OLD, NEVER_NEW)):
        if new in prompt:
            continue
        if prompt.count(old) != 1:
            raise ValueError(f"Expected this once in the prompt, found {prompt.count(old)}: {old[:70]}…")
        prompt = prompt.replace(old, new, 1)
    if "<mortgage_applications>" not in prompt:
        if prompt.count(MORTGAGE_ANCHOR) != 1:
            raise ValueError("Expected one '</card_disputes>' line to put the mortgage section after.")
        prompt = prompt.replace(MORTGAGE_ANCHOR, MORTGAGE_ANCHOR + MORTGAGE_SECTION, 1)
    left = [name for name in RETIRED if name in prompt]
    if left:
        raise ValueError(f"The prompt still names {', '.join(left)}; change those lines by hand.")
    return prompt
