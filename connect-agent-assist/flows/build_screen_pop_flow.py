#!/usr/bin/env python3
"""
build_screen_pop_flow.py
========================
Generates flows/aria-agent-screen-pop-flow.json: the agent's screen pop, with
the assistant's arrival briefing added to the flow that is live today.

The two views the live flow already shows (the ARIA handoff summary, and the
mortgage application view) keep everything they had. Each gains five lines:
what to do first, the verification position, the likely reasons, the product
details and the related guidance.

The flow fetches those lines by calling aria-agent-assist-injector with
operation = "get_briefing" before it shows the view. "Refresh briefing" calls
it again, for the case where the agent accepted before the assistant had
finished writing. "Got it" ends the flow.

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

REGION, ACCOUNT_ID = "eu-west-2", "395402194296"
INJECTOR_FUNCTION = "aria-agent-assist-injector"

# Label on screen -> key returned by aria-agent-assist-injector (operation get_briefing).
BRIEFING_ITEMS = [
    ("Do first", "first"),
    ("Verification", "verification"),
    ("Likely reasons", "reasons"),
    ("Product details", "product"),
    ("Related guidance", "guidance"),
]


def build() -> dict:
    briefing = {"Items": [{"Label": label, "Value": f"$.External.{key}"} for label, key in BRIEFING_ITEMS]}

    def view(identifier: str, view_data: dict) -> dict:
        return {
            "Identifier": identifier,
            "Type": "ShowView",
            "Parameters": {"ViewResource": {"Id": DETAIL_VIEW}, "InvocationTimeLimitSeconds": "600",
                           "ViewData": {**view_data, "Actions": [REFRESH_ACTION, DONE_ACTION],
                                        # A second, separate way out: "Back" is its own branch.
                                        "Back": {"Label": "Close"}}},
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
            "Transitions": {"NextAction": "GetBriefing"},
        }, 200, 200),
        ({
            # Fetches the five briefing lines. Runs again on every refresh.
            "Identifier": "GetBriefing",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{INJECTOR_FUNCTION}",
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {"operation": "get_briefing"},
                "ResponseValidation": {"ResponseType": "STRING_MAP"},
            },
            "Transitions": {"NextAction": "CheckTopic",
                            "Errors": [{"NextAction": "CheckTopic", "ErrorType": "NoMatchingError"}]},
        }, 320, 380),
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
        # Which button was pressed. "$.Views.Action" only says that a button was
        # pressed ("ActionSelected"); the button's name is in the view's output.
        # Anything but "Got it" fetches the briefing again and re-shows the view.
        (choose("CheckButton", "$.Views.ViewResultData.actionName", DONE_ACTION, "End", "GetBriefing"), 960, 200),
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
