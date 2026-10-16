#!/usr/bin/env python3
"""
collaborator.py
===============
Adds the Money Hub agent to ARIA's configuration as an external collaborator
that talks to the customer (handoffAgentConfiguration), or takes it off.
Used by connect_collaborator.sh; it only transforms JSON on stdin/stdout.

    python3 collaborator.py add <applicationId>    < get-ai-agent.json > configuration.json
    python3 collaborator.py remove <applicationId> < get-ai-agent.json > configuration.json

Every other collaborator and setting on ARIA is kept exactly as it was. Adding
twice replaces, never duplicates.
"""

from __future__ import annotations

import json
import sys

INSTRUCTION = (
    "Hand the conversation to this agent when a verified customer (Level 2 or above) wants to understand their own "
    "money: where it goes, spending by category, regular payments and subscriptions, what's expected in the coming "
    "months, spending habits, or how to reach a savings goal. It explains with their real figures and never gives "
    "financial advice. It hands back with COMPLETE when done (or when they ask about something else) and ESCALATE "
    "when they want a person, ask for advice or seem vulnerable; the reason says what they want next. "
    "Do not use it for payments, disputes, cards or products."
)


def apply(configuration: dict, application_id: str, remove: bool = False) -> dict:
    """ARIA's orchestration configuration with the Money Hub collaborator added (or removed)."""
    config = json.loads(json.dumps(configuration))
    orchestration = config.setdefault("orchestrationAIAgentConfiguration", {})
    kept = [c for c in orchestration.get("multiAgentConfigurations") or []
            if ((c.get("handoffAgentConfiguration") or c.get("delegateAgentConfiguration") or {})
                .get("agentTarget") or {}).get("applicationId") != application_id]
    if not remove:
        kept.append({"handoffAgentConfiguration": {
            "agentTarget": {"applicationId": application_id},
            "instruction": {"instruction": INSTRUCTION},
            "audioStreamingEnabled": False,          # Connect does the speech, in ARIA's voice
            "immediateHandoff": False,               # ARIA decides when, from the instruction
        }})
    orchestration["multiAgentConfigurations"] = kept
    if not kept:
        orchestration.pop("multiAgentConfigurations")
    return config


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("add", "remove"):
        sys.exit("usage: collaborator.py add|remove <applicationId> < get-ai-agent.json")
    agent = json.load(sys.stdin)["aiAgent"]
    print(json.dumps(apply(agent["configuration"], sys.argv[2], remove=sys.argv[1] == "remove")))


if __name__ == "__main__":
    main()
