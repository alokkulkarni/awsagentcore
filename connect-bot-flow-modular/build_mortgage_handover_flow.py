#!/usr/bin/env python3
"""
build_mortgage_handover_flow.py
===============================
Writes flows/mortgage-live-sync-handover.json: the Connect flow "Mortgage Live Sync handover" (the mortgage
assistant behind ARIA's bot flow), ready to import over the live one. It is the flow connect-livesync-mortgage's
GUIDE Part 6.8 builds by hand (v1.24: FR-39 and FR-40), with the live flow's Agentic CX block kept exactly as it is
(reference/mortgage-live-sync-handover-live.json, read from Connect on 21 Oct 2026):

    Agentic CX "MortgageAssistant"
      ├─ Escalation ─► CheckEscalation (escalationReason)
      │                  ├─ back_to_aria ─► BackToHelp (returnIntent=help) ─────────────┐
      │                  └─ anything else ─► HandoffNotes ─► ColleagueNeeded ───────────┤
      ├─ Error ────────► ErrorNotes (mortgage_assistant_error) ─► ColleagueNeeded ──────┤
      ├─ Default ──────► CheckDefault (escalationReason)                                │
      │                  ├─ back_to_aria (first: it has an underscore) ─► BackToHelp     │
      │                  ├─ contains "_" or = other (HandToAdviser ran) ─► HandoffNotes   │
      │                  └─ no match (the assistant said goodbye) ─► Disconnect           │
      └─ Idle timeout ─► Disconnect                                                       ▼
                                          ToAria: Transfer to "ARIA conversation bot flow (modular)"
                                          ToHuman: "ARIA human handover", only if the way back to ARIA fails

Only ARIA escalates to a person (FR-40): the adviser's notes stay on the contact for the screen pop, and the
customer goes back to her with returnIntent=escalate, the reason and the notes; she escalates with them.

This script only writes a local file. It never calls AWS.

    python3 connect-bot-flow-modular/build_mortgage_handover_flow.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE = HERE / "reference" / "mortgage-live-sync-handover-live.json"
OUTPUT = HERE / "flows" / "mortgage-live-sync-handover.json"
INSTANCE = "arn:aws:connect:eu-west-2:395402194296:instance/f969d4b4-f716-4974-a325-bb7899f2f293"
ARIA_FLOW = f"{INSTANCE}/contact-flow/2b4f7b5c-1351-42c8-acac-add07d0cbd00"          # ARIA conversation bot flow (modular)
HUMAN_HANDOVER = f"{INSTANCE}/contact-flow/0978883b-6892-41ab-81f4-528e0e0cc9bf"     # ARIA human handover
LIVE_ASSISTANT = "99788c16-05fd-467b-a4e3-4391f71980de"                            # the live Agentic CX block
BACK_TO_ARIA = "back_to_aria"
CX = "$.AgenticCX.ContextVariables."

RETURNED = {"entry": "returned", "returnedFrom": "mortgage", "handbackRoute": "returned"}
BACK_TO_HELP = {**RETURNED, "returnIntent": "help", "returnSummary": f"{CX}summary"}
HANDOFF_NOTES = {"topicCategory": "mortgage_application", "customerIntent": "start_mortgage_application",
                 **{k: f"{CX}{v}" for k, v in (("escalationReason", "escalationReason"), ("conversationSummary", "summary"),
                                                ("applicationId", "applicationId"), ("stage", "stage"),
                                                ("dipDecision", "dipDecision"), ("productId", "productId"),
                                                ("docsOutstanding", "docsOutstanding"))}}
ERROR_NOTES = {"escalationReason": "mortgage_assistant_error", "topicCategory": "mortgage_application",
               "customerIntent": "start_mortgage_application"}
COLLEAGUE_NEEDED = {**RETURNED, "returnIntent": "escalate", "returnReason": "$.Attributes.escalationReason",
                    "returnSummary": "$.Attributes.conversationSummary"}


def _set(identifier: str, attributes: dict, after: str, on_error: str) -> dict:
    return {"Identifier": identifier, "Type": "UpdateContactAttributes",
            "Parameters": {"Attributes": attributes, "TargetContact": "Current"},
            "Transitions": {"NextAction": after, "Errors": [{"NextAction": on_error, "ErrorType": "NoMatchingError"}]}}


def _transfer(identifier: str, flow_arn: str, after: str) -> dict:
    return {"Identifier": identifier, "Type": "TransferToFlow", "Parameters": {"ContactFlowId": flow_arn},
            "Transitions": {"NextAction": after, "Errors": [{"NextAction": after, "ErrorType": "NoMatchingError"}]}}


def _check(identifier: str, conditions: list[tuple[str, str, str]], otherwise: str) -> dict:
    """conditions: (operator, value, next) in order: Connect takes the first that matches."""
    return {"Identifier": identifier, "Type": "Compare", "Parameters": {"ComparisonValue": f"{CX}escalationReason"},
            "Transitions": {"NextAction": otherwise,
                            "Conditions": [{"NextAction": target, "Condition": {"Operator": op, "Operands": [value]}}
                                           for op, value, target in conditions],
                            "Errors": [{"NextAction": otherwise, "ErrorType": "NoMatchingCondition"}]}}


def _condition_metadata(identifier: str, conditions: list[tuple[str, str, str]]) -> list[dict]:
    """What the designer saves for a Check contact attributes block's conditions (as the live flow's own)."""
    shown = {"Equals": ("Equals", "="), "TextContains": ("Contains", "contains")}
    return [{"id": f"{identifier.lower()}-{n}", "operator": {"name": shown[op][0], "value": shown[op][0],
                                                              "shortDisplay": shown[op][1]}, "value": value}
            for n, (op, value, _) in enumerate(conditions)]


def build(live: dict) -> dict:
    assistant = next(a for a in live["Actions"] if a["Identifier"] == LIVE_ASSISTANT)
    assistant_meta = live["Metadata"]["ActionMetadata"][LIVE_ASSISTANT]
    escalation_checks = [("Equals", BACK_TO_ARIA, "BackToHelp")]
    # back_to_aria contains an underscore: it must come before the safety net's "contains _".
    default_checks = [("Equals", BACK_TO_ARIA, "BackToHelp"), ("TextContains", "_", "HandoffNotes"),
                      ("Equals", "other", "HandoffNotes")]
    laid_out = [
        ({**assistant, "Identifier": "MortgageAssistant", "Transitions": {
            "NextAction": "ErrorNotes",
            "Conditions": [{"NextAction": "CheckEscalation", "Condition": {"Operator": "Equals", "Operands": ["Escalation"]}}],
            "Errors": [{"NextAction": "ErrorNotes", "ErrorType": "NoMatchingError"},
                       {"NextAction": "CheckDefault", "ErrorType": "NoMatchingCondition"},
                       {"NextAction": "Disconnect", "ErrorType": "InputTimeLimitExceeded"}]}}, 280, 100),
        (_check("CheckEscalation", escalation_checks, "HandoffNotes"), 560, -120),
        (_check("CheckDefault", default_checks, "Disconnect"), 560, 360),
        (_set("BackToHelp", BACK_TO_HELP, "ToAria", "HandoffNotes"), 840, -280),
        (_set("HandoffNotes", HANDOFF_NOTES, "ColleagueNeeded", "ColleagueNeeded"), 840, -40),
        (_set("ErrorNotes", ERROR_NOTES, "ColleagueNeeded", "ToHuman"), 840, 200),
        (_set("ColleagueNeeded", COLLEAGUE_NEEDED, "ToAria", "ToHuman"), 1120, 40),
        (_transfer("ToAria", ARIA_FLOW, "ToHuman"), 1400, -120),       # ARIA unreachable: the safety net
        (_transfer("ToHuman", HUMAN_HANDOVER, "Disconnect"), 1680, 120),
        ({"Identifier": "Disconnect", "Type": "DisconnectParticipant", "Parameters": {}, "Transitions": {}}, 1960, 280),
    ]
    metadata = {a["Identifier"]: {"position": {"x": x, "y": y}} for a, x, y in laid_out}
    metadata["MortgageAssistant"] = {**assistant_meta, "position": {"x": 280, "y": 100}}
    for name, conditions in (("CheckEscalation", escalation_checks), ("CheckDefault", default_checks)):
        metadata[name].update({"conditions": [], "conditionMetadata": _condition_metadata(name, conditions)})
    for name, attributes in (("BackToHelp", BACK_TO_HELP), ("HandoffNotes", HANDOFF_NOTES),
                             ("ErrorNotes", ERROR_NOTES), ("ColleagueNeeded", COLLEAGUE_NEEDED)):
        dynamic = [k for k, v in attributes.items() if v.startswith("$.")]
        metadata[name].update({"parameters": {"Attributes": {k: {"useDynamic": True} for k in dynamic}},
                               "dynamicParams": dynamic})
    metadata["ToAria"].update({"parameters": {"ContactFlowId": {"displayName": "ARIA conversation bot flow (modular)"}},
                               "ContactFlow": {"text": "ARIA conversation bot flow (modular)"}})
    metadata["ToHuman"].update({"parameters": {"ContactFlowId": {"displayName": "ARIA human handover"}},
                                "ContactFlow": {"text": "ARIA human handover"}})
    return {"Version": "2019-10-30", "StartAction": "MortgageAssistant",
            "Metadata": {"entryPointPosition": {"x": 40, "y": 100}, "ActionMetadata": metadata, "Annotations": []},
            "Actions": [a for a, _, _ in laid_out]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Mortgage Live Sync handover flow JSON.")
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()
    flow = build(json.loads(LIVE.read_text()))
    Path(args.output).write_text(json.dumps(flow, indent=2) + "\n")
    print(f"Wrote {args.output} ({len(flow['Actions'])} blocks)")


if __name__ == "__main__":
    main()
