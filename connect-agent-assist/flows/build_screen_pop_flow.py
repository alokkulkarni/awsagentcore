#!/usr/bin/env python3
"""
build_screen_pop_flow.py
========================
Generates flows/aria-agent-screen-pop-flow.json: the agent's screen pop, with
one addition to the flow that is live today, an "Assistant briefing" button.

The two views the live flow already shows (the ARIA handoff summary, and the
mortgage application view) are reproduced unchanged apart from that button.
Pressing it opens a third view that shows the contact attribute
"assistBriefing", which aria-agent-assist-injector fills in with the
assistant's briefing. "Refresh" on that view re-reads the attribute, for the
case where the agent accepted before the assistant had finished writing.

This script only writes a local file. It never calls AWS.

Usage:
    python3 connect-agent-assist/flows/build_screen_pop_flow.py
"""

import json
from pathlib import Path

FLOW_NAME = "ARIA-Agent-Screen-Pop-Flow"
FLOW_DESCRIPTION = "Agent screen pop: ARIA handoff summary, with the assistant's briefing one click away."
DETAIL_VIEW = "arn:aws:connect:eu-west-2:aws:view/detail:1"   # AWS-managed "Detail" view
BRIEFING_ACTION, REFRESH_ACTION, DONE_ACTION = "Assistant briefing", "Refresh", "Got it"


def build() -> dict:
    def view(identifier: str, view_data: dict, then: str) -> dict:
        return {
            "Identifier": identifier,
            "Type": "ShowView",
            "Parameters": {"ViewResource": {"Id": DETAIL_VIEW}, "InvocationTimeLimitSeconds": "600",
                           "ViewData": view_data},
            "Transitions": {
                "NextAction": "End",
                "Conditions": [
                    {"NextAction": then, "Condition": {"Operator": "Equals", "Operands": ["ActionSelected"]}},
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
        (choose("CheckTopic", "$.Attributes.topicCategory", "mortgage_application",
                "MortgageApplicationView", "HandoffView"), 200, 200),
        (view("HandoffView", {
            "Heading": "ARIA Handoff Summary",
            "Sections": [{"Items": [
                {"Label": "Customer Intent", "Value": "$.Attributes.ariaCustomerIntent"},
                {"Label": "Escalation Reason", "Value": "$.Attributes.ariaEscalationReason"},
                {"Label": "Summary", "Value": "$.Attributes.ariaSummary"},
            ]}],
            "Actions": [BRIEFING_ACTION, DONE_ACTION],
        }, "CheckButton"), 460, 320),
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
            ],
            "Actions": [BRIEFING_ACTION, DONE_ACTION],
        }, "CheckButton"), 460, 60),
        (choose("CheckButton", "$.Views.Action", BRIEFING_ACTION, "BriefingView", "End"), 720, 200),
        (view("BriefingView", {
            "Heading": "Assistant briefing",
            "Sections": [{"TemplateString": "$.Attributes.assistBriefing"}],
            "Actions": [REFRESH_ACTION, DONE_ACTION],
        }, "CheckBriefingButton"), 980, 200),
        # "Refresh" shows the same view again, which re-reads the attribute.
        (choose("CheckBriefingButton", "$.Views.Action", REFRESH_ACTION, "BriefingView", "End"), 1240, 200),
        ({"Identifier": "End", "Type": "EndFlowExecution", "Parameters": {}, "Transitions": {}}, 1500, 200),
    ]

    return {
        "Version": "2019-10-30",
        "StartAction": "CheckTopic",
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
