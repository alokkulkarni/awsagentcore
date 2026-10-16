#!/usr/bin/env python3
"""
collaborator_config.py
======================
Works out the change attach_disputes_collaborator.sh makes to ARIA's AI agent:
adding, refreshing or removing the disputes agent as a collaborator.

It never calls AWS. It reads the agent the script fetched (get-ai-agent output)
and writes the configuration to send back.

The whole configuration is returned, changed in one place only, so the prompt,
tools, guardrail and locale cannot be lost to a partial update.
"""

import copy
import json
import sys

MAX_COLLABORATORS = 5       # Connect's limit per AI agent
# Our collaborator is told apart from any other by this marker in its instruction,
# so only ours is ever replaced or removed.
MARKER = "[card-disputes]"
INSTRUCTION = (
    MARKER + " Hand the conversation to this agent when an authenticated customer at Level 2 or above wants to "
    "dispute, challenge, query or claim back a card payment, or does not recognise a card payment. Do your initial "
    "checks first and ask nothing else: this agent handles the dispute end to end, including the customer's screen. "
    "Do not announce the hand-off to the customer. In the message you hand over, state the customer ID from session "
    "context, the level of assurance, the channel, everything the customer has already said about the payment "
    "(retailer, amount, date, whether they made it, whether they still have the card), and any dispute reference "
    "(DSP-...) from earlier in the conversation. The agent gives the conversation back with a reason that begins "
    "'Card dispute' when the dispute is ready for a colleague, or that begins 'Customer asked about something else'. "
    "Do not use it for card blocking on its own, lost cards, payments that need making, or anything that is not a "
    "dispute about one card transaction."
)


def _body(entry: dict) -> dict:
    return entry.get("handoffAgentConfiguration") or entry.get("delegateAgentConfiguration") or {}


def _is_ours(entry: dict, collaborator_id: str) -> bool:
    body = _body(entry)
    if MARKER in (body.get("instruction") or {}).get("instruction", ""):
        return True
    return bool(collaborator_id) and (body.get("agentTarget") or {}).get("aiAgentId", "").split(":")[0] == collaborator_id


def describe(entries: list) -> list[str]:
    return [("handoff" if "handoffAgentConfiguration" in entry else "delegate") + " -> "
            + (_body(entry).get("agentTarget") or {}).get("aiAgentId", "?") for entry in entries]


def apply(configuration: dict, collaborator_id: str = "", remove: bool = False) -> tuple[dict, bool]:
    """
    The agent's configuration with the disputes collaborator added (or removed),
    and whether that differs from what was passed in. Raises ValueError if the
    agent cannot take a collaborator.
    """
    configuration = copy.deepcopy(configuration)
    orchestration = configuration.get("orchestrationAIAgentConfiguration")
    if orchestration is None:
        raise ValueError("This is not an Orchestration AI agent; collaborators cannot be added to it.")
    before = orchestration.get("multiAgentConfigurations") or []
    after = [entry for entry in before if not _is_ours(entry, collaborator_id)]
    if not remove:
        if not collaborator_id:
            raise ValueError("The disputes agent's ID is needed.")
        after.append({"handoffAgentConfiguration": {
            "agentTarget": {"aiAgentId": collaborator_id},
            "instruction": {"instruction": INSTRUCTION},
            # ARIA decides from the instruction; the disputes agent does not take every contact.
            "immediateHandoff": False,
        }})
    if len(after) > MAX_COLLABORATORS:
        raise ValueError(f"ARIA would have more than {MAX_COLLABORATORS} collaborators, which is Connect's limit.")
    if after or "multiAgentConfigurations" in orchestration:
        orchestration["multiAgentConfigurations"] = after
    return configuration, after != before


def check_collaborator(agent: dict) -> list[str]:
    """Why this agent cannot be a collaborator that talks to the customer, or an empty list."""
    config = (agent.get("configuration") or {}).get("orchestrationAIAgentConfiguration")
    if agent.get("type") != "ORCHESTRATION" or config is None:
        return [f"'{agent.get('name')}' is not an Orchestration AI agent."]
    tools = {tool.get("toolName") for tool in config.get("toolConfigurations", [])}
    # An agent that talks to the customer can only give the conversation back with these.
    return [f"'{agent.get('name')}' has no {name} tool. Add it in AI agent designer, publish, and run this again."
            for name in ("Complete", "Escalate") if name not in tools]


def main() -> None:
    build, collaborator_id, remove = sys.argv[1], sys.argv[2], sys.argv[3] == "true"
    aria = json.load(open(f"{build}/aria.json"))["aiAgent"]
    if not remove:
        problems = check_collaborator(json.load(open(f"{build}/collaborator.json"))["aiAgent"])
        if problems:
            sys.exit("\n".join("  " + problem for problem in problems))
    try:
        configuration, changed = apply(aria["configuration"], collaborator_id, remove)
    except ValueError as error:
        sys.exit(f"  {error}")
    json.dump(configuration, open(f"{build}/configuration.json", "w"))
    json.dump({"savedFrom": aria.get("aiAgentArn"), "configuration": aria["configuration"]},
              open(f"{build}/backup.json", "w"), indent=2)
    open(f"{build}/changed", "w").write("yes" if changed else "no")
    old, new = aria["configuration"]["orchestrationAIAgentConfiguration"], configuration["orchestrationAIAgentConfiguration"]
    print("  Collaborators now  :", describe(old.get("multiAgentConfigurations") or []) or "none")
    print("  Collaborators after:", describe(new.get("multiAgentConfigurations") or []) or "none")
    print("  Tools kept         :", len(new.get("toolConfigurations", [])))
    print("  Prompt kept        :", new.get("orchestrationAIPromptId"))


if __name__ == "__main__":
    main()
