#!/usr/bin/env python3
"""
build_screen_pop_flow.py
========================
Generates flows/aria-agent-screen-pop-flow.json: the agent's screen pop, with
the assistant's arrival briefing added to the flow that is live today.

The two views the live flow already shows (the ARIA handoff summary, and the
mortgage application view) keep everything they had. Each gains five lines,
read from contact attributes that aria-agent-assist-injector fills in: what to
do first, the verification position, the likely reasons, the product details
and the related guidance. Each attribute holds one line of plain text, the same
way the existing "Summary" line works.

"Refresh briefing" shows the view again, which re-reads the attributes, for the
case where the agent accepted before the assistant had finished writing.

This script only writes a local file. It never calls AWS.

Usage:
    python3 connect-agent-assist/flows/build_screen_pop_flow.py
"""

import json
from pathlib import Path

FLOW_NAME = "ARIA-Agent-Screen-Pop-Flow"
FLOW_DESCRIPTION = "Agent screen pop: ARIA handoff summary and the assistant's arrival briefing."
DETAIL_VIEW = "arn:aws:connect:eu-west-2:aws:view/detail:1"   # AWS-managed "Detail" view
REFRESH_ACTION, DONE_ACTION = "Refresh briefing", "Got it"

# Label on screen -> contact attribute written by aria-agent-assist-injector.
BRIEFING_ITEMS = [
    ("Do first", "assistBriefFirst"),
    ("Verification", "assistBriefVerification"),
    ("Likely reasons", "assistBriefReasons"),
    ("Product details", "assistBriefProduct"),
    ("Related guidance", "assistBriefGuidance"),
]


def build() -> dict:
    briefing = {"Items": [{"Label": label, "Value": f"$.Attributes.{attribute}"}
                          for label, attribute in BRIEFING_ITEMS]}

    def view(identifier: str, view_data: dict) -> dict:
        return {
            "Identifier": identifier,
            "Type": "ShowView",
            "Parameters": {"ViewResource": {"Id": DETAIL_VIEW}, "InvocationTimeLimitSeconds": "600",
                           "ViewData": {**view_data, "Actions": [REFRESH_ACTION, DONE_ACTION]}},
            "Transitions": {
                "NextAction": "End",
                "Conditions": [
                    {"NextAction": "CheckButton", "Condition": {"Operator": "Equals", "Operands": ["ActionSelected"]}},
                    {"NextAction": "End", "Condition": {"Operator": "Equals", "Operands": ["Back"]}},
                ],
                "Errors": [{"NextAction": "End", "ErrorType": error}
                           for error in ("NoMatchingCondition", "NoMatchingError", "TimeLimitExceeded")],
            },
        }

    def choose(identifier: str, value: str, equals: str, then: str, otherwise: str) -> dict:
        return {
            "Identifier": identifier,
            "Type": "Compare",
            "Parameters": {"ComparisonValue": value},
            "Transitions": {
                "NextAction": otherwise,
                "Conditions": [{"NextAction": then, "Condition": {"Operator": "Equals", "Operands": [equals]}}],
                "Errors": [{"NextAction": otherwise, "ErrorType": "NoMatchingCondition"}],
            },
        }

    laid_out = [
        ({
            "Identifier": "EnableLogging",
            "Type": "UpdateFlowLoggingBehavior",
            "Parameters": {"FlowLoggingBehavior": "Enabled"},
            "Transitions": {"NextAction": "CheckTopic"},
        }, 200, 200),
        (choose("CheckTopic", "$.Attributes.topicCategory", "mortgage_application",
                "MortgageApplicationView", "HandoffView"), 440, 200),
        (view("HandoffView", {
            "Heading": "ARIA Handoff Summary",
            "Sections": [
                {"Items": [
                    {"Label": "Customer Intent", "Value": "$.Attributes.ariaCustomerIntent"},
                    {"Label": "Escalation Reason", "Value": "$.Attributes.ariaEscalationReason"},
                    {"Label": "Summary", "Value": "$.Attributes.ariaSummary"},
                ]},
                briefing,
            ],
        }), 700, 320),
        (view("MortgageApplicationView", {
            "Heading": "Mortgage application",
            "AttributeBar": [
                {"Label": "Application ID", "Value": "$.Attributes.applicationId", "Copyable": True},
                {"Label": "Stage reached", "Value": "$.Attributes.stage"},
                {"Label": "Decision in Principle", "Value": "$.Attributes.dipDecision"},
                {"Label": "Product selected", "Value": "$.Attributes.productId"},
                {"Label": "Documents outstanding", "Value": "$.Attributes.docsOutstanding"},
            ],
            "Sections": [
                {"TemplateString": "**Arrived via:** $.Attributes.entry ($.Channel)"},
                {"TemplateString": "**Why transferred:** $.Attributes.ariaEscalationReason"},
                {"TemplateString": "$.Attributes.ariaSummary"},
                briefing,
            ],
        }), 700, 60),
        # "Refresh briefing" shows the same view again, which re-reads the attributes.
        (choose("CheckButton", "$.Views.Action", REFRESH_ACTION, "CheckTopic", "End"), 960, 200),
        ({"Identifier": "End", "Type": "EndFlowExecution", "Parameters": {}, "Transitions": {}}, 1220, 200),
    ]

    return {
        "Version": "2019-10-30",
        "StartAction": "EnableLogging",
        "Metadata": {
            "entryPointPosition": {"x": 40, "y": 200},
            "ActionMetadata": {a["Identifier"]: {"position": {"x": x, "y": y}} for a, x, y in laid_out},
            "Annotations": [],
            "name": FLOW_NAME,
            "description": FLOW_DESCRIPTION,
            "type": "contactFlow",
            "status": "saved",
        },
        "Actions": [a for a, _, _ in laid_out],
    }


def main() -> None:
    output = Path(__file__).parent / "aria-agent-screen-pop-flow.json"
    flow = build()
    output.write_text(json.dumps(flow, indent=2) + "\n")
    print(f"Wrote {output} ({len(flow['Actions'])} blocks)")


if __name__ == "__main__":
    main()
