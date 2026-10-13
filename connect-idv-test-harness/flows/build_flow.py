#!/usr/bin/env python3
"""
build_flow.py
=============
Generates flows/aria-idv-test-harness-flow.json — the importable Amazon Connect
contact flow for the ARIA ID&V test harness.

The JSON is generated rather than hand-edited so the three values that are
specific to an AWS account live in one place (the constants below, or the
command-line flags). This script only writes a local file. It never calls AWS.

Usage:
    python3 connect-idv-test-harness/flows/build_flow.py
    python3 connect-idv-test-harness/flows/build_flow.py \\
        --region eu-west-2 --account-id 111122223333 \\
        --instance-id <connect-instance-id> --main-flow-id <flow-id>
"""

import argparse
import json
from pathlib import Path

# Defaults: the "conversationbot" Connect instance and its "conversation bot flow".
REGION = "eu-west-2"
ACCOUNT_ID = "395402194296"
INSTANCE_ID = "f969d4b4-f716-4974-a325-bb7899f2f293"
MAIN_FLOW_ID = "f6d6545f-c9ae-4ca4-a4d8-6fdc8ba0494f"
HARNESS_FUNCTION = "aria-idv-test-harness"

FLOW_NAME = "ARIA IDV Test Harness"
FLOW_DESCRIPTION = ("TEST ONLY. Pick any session-injector test customer, simulate the calling line, run CLI "
                    "identification and caller verification, then hand over to the conversation bot flow.")

# Every value the Lambda returns is copied to a contact attribute after each
# invocation. idvState carries the conversation between invocations; the rest
# are what the main flow, the session injector and the contact record read.
SAVED_ATTRIBUTES = [
    "idvState", "customerId", "authStatus", "LoA", "idvMethod", "cliRelationship", "riskScore",
    "reasonCodes", "idvStatus", "idvIntent", "idvDecision", "idvObligations", "idvSummary",
]


def build(region: str, account_id: str, instance_id: str, main_flow_id: str) -> dict:
    harness_arn = f"arn:aws:lambda:{region}:{account_id}:function:{HARNESS_FUNCTION}"
    main_flow_arn = f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}/contact-flow/{main_flow_id}"

    def invoke(identifier: str, parameters: dict) -> dict:
        return {
            "Identifier": identifier,
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": harness_arn,
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": parameters,
                "ResponseValidation": {"ResponseType": "STRING_MAP"},
            },
            "Transitions": {"NextAction": "SaveResult",
                            "Errors": [{"NextAction": "HarnessError", "ErrorType": "NoMatchingError"}]},
        }

    def say(identifier: str, text: str, then: str) -> dict:
        return {
            "Identifier": identifier,
            "Type": "MessageParticipant",
            "Parameters": {"SkipWhenDTMFBufferEnabled": "false", "Text": text},
            "Transitions": {"NextAction": then,
                            "Errors": [{"NextAction": then, "ErrorType": "NoMatchingError"}]},
        }

    # (action, x, y) — positions only affect how the flow looks in the designer.
    laid_out = [
        ({
            "Identifier": "EnableLogging",
            "Type": "UpdateFlowLoggingBehavior",
            "Parameters": {"FlowLoggingBehavior": "Enabled"},
            "Transitions": {"NextAction": "SetVoice"},
        }, 200, 40),
        ({
            "Identifier": "SetVoice",
            "Type": "UpdateContactTextToSpeechVoice",
            "Parameters": {"TextToSpeechVoice": "Amy", "TextToSpeechEngine": "Generative",
                           "TextToSpeechStyle": "None"},
            "Transitions": {"NextAction": "StartHarness",
                            "Errors": [{"NextAction": "StartHarness", "ErrorType": "NoMatchingError"}]},
        }, 440, 40),
        (invoke("StartHarness", {"operation": "start"}), 680, 40),
        ({
            "Identifier": "SaveResult",
            "Type": "UpdateContactAttributes",
            "Parameters": {"Attributes": {name: f"$.External.{name}" for name in SAVED_ATTRIBUTES},
                           "TargetContact": "Current"},
            "Transitions": {"NextAction": "CheckAction",
                            "Errors": [{"NextAction": "HarnessError", "ErrorType": "NoMatchingError"}]},
        }, 920, 40),
        ({
            "Identifier": "CheckAction",
            "Type": "Compare",
            "Parameters": {"ComparisonValue": "$.External.action"},
            "Transitions": {
                "NextAction": "SayGoodbye",
                "Conditions": [
                    {"NextAction": "CollectInput", "Condition": {"Operator": "Equals", "Operands": ["input"]}},
                    {"NextAction": "SayHandoff", "Condition": {"Operator": "Equals", "Operands": ["handoff"]}},
                    {"NextAction": "SayGoodbye", "Condition": {"Operator": "Equals", "Operands": ["end"]}},
                ],
                "Errors": [{"NextAction": "SayGoodbye", "ErrorType": "NoMatchingCondition"}],
            },
        }, 1160, 40),
        ({
            # "Store customer input": voice only. Plays the Lambda's prompt and
            # stores the keyed digits in $.StoredCustomerInput.
            "Identifier": "CollectInput",
            "Type": "GetParticipantInput",
            "Parameters": {
                "Text": "$.External.prompt",
                "StoreInput": "True",
                "InputTimeLimitSeconds": "10",
                "InputValidation": {"CustomValidation": {"MaximumLength": "12"}},
                "DTMFConfiguration": {"InputTerminationSequence": "#", "DisableCancelKey": "False",
                                      "InterdigitTimeLimitSeconds": "4"},
            },
            "Transitions": {
                "NextAction": "StepHarness",
                "Errors": [{"NextAction": "StepTimeout", "ErrorType": "InputTimeLimitExceeded"},
                           {"NextAction": "StepTimeout", "ErrorType": "NoMatchingError"}],
            },
        }, 1400, 240),
        (invoke("StepHarness", {"operation": "step", "input": "$.StoredCustomerInput"}), 920, 300),
        (invoke("StepTimeout", {"operation": "step", "input": "Timeout"}), 920, 520),
        (say("SayHandoff", "$.External.prompt", "TransferToMain"), 1400, 40),
        ({
            "Identifier": "TransferToMain",
            "Type": "TransferToFlow",
            "Parameters": {"ContactFlowId": main_flow_arn},
            "Transitions": {"NextAction": "Disconnect",
                            "Errors": [{"NextAction": "Disconnect", "ErrorType": "NoMatchingError"}]},
        }, 1640, 40),
        (say("SayGoodbye", "$.External.prompt", "Disconnect"), 1400, -160),
        (say("HarnessError", "Sorry, the test harness is not available right now. Goodbye.", "Disconnect"),
         1160, -160),
        ({"Identifier": "Disconnect", "Type": "DisconnectParticipant", "Parameters": {}, "Transitions": {}},
         1880, -160),
    ]

    return {
        "Version": "2019-10-30",
        "StartAction": "EnableLogging",
        "Metadata": {
            "entryPointPosition": {"x": 40, "y": 40},
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
    parser = argparse.ArgumentParser(description="Generate the ARIA ID&V test harness contact flow JSON.")
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--account-id", default=ACCOUNT_ID)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--main-flow-id", default=MAIN_FLOW_ID,
                        help="ID of the flow to hand over to (the main conversational bot flow)")
    parser.add_argument("--output", default=str(Path(__file__).parent / "aria-idv-test-harness-flow.json"))
    args = parser.parse_args()

    flow = build(args.region, args.account_id, args.instance_id, args.main_flow_id)
    Path(args.output).write_text(json.dumps(flow, indent=2) + "\n")
    print(f"Wrote {args.output} ({len(flow['Actions'])} blocks)")


if __name__ == "__main__":
    main()
