#!/usr/bin/env python3
"""
build_card_dispute_flow.py
==========================
Generates flows/card-dispute-flow.json: the Connect flow ARIA's bot flow
transfers to when ARIA calls its StartCardDispute tool (SPEC Part 4).

    Agentic CX block "Card dispute"   the CX designer disputes assistant does the dispute
          │  any way out except the caller hanging up
          ▼
    Lambda aria-card-dispute          builds the hand-over from the dispute record:
          │                           team, summary, dispute reference
          ▼
    Set contact attributes            the same attributes ARIA's Escalate tool sets
          ▼
    Transfer to flow: ARIA human handover   the same path ARIA's own escalations take

So the adviser gets an ARIA hand-over in every way: the same flow, the same
attributes, the same screen pop, with the dispute's details in it.

If the Lambda fails, the contact still goes to a person, on the fraud_security
team, with a summary saying the details are on the dispute form.

This script only writes a local file. It never calls AWS.

Usage:
    python3 connect-card-dispute/flows/build_card_dispute_flow.py --application-id <id> --alias <alias>

Both come from the CX designer application you deployed. Without them the flow
is still written; choose the application in the block after import.
"""

import argparse
import json
from pathlib import Path

REGION = "eu-west-2"
ACCOUNT_ID = "395402194296"
INSTANCE_ID = "f969d4b4-f716-4974-a325-bb7899f2f293"
WORKSPACE_ID = "55c49fa0-22f3-4dd3-823d-e353f4aee139"        # ariaworkspace
HUMAN_HANDOVER_FLOW_ID = "0978883b-6892-41ab-81f4-528e0e0cc9bf"   # ARIA human handover
DISPUTE_FUNCTION = "aria-card-dispute"

FLOW_NAME = "Card dispute assistant"
FLOW_DESCRIPTION = ("ARIA hands a card dispute to the CX designer disputes assistant, which does it end to end; "
                    "then the call goes to an adviser through ARIA human handover.")
NOT_CHOSEN = "CHOOSE-IN-THE-BLOCK"

# What Connect passes in. At most ten per block. No customer ID: the dispute
# service finds the customer from the contact itself (rule R7).
CONTEXT_IN = {
    "entry": "$.Attributes.entry",
    "contactId": "$.ContactId",
    "firstName": "$.Attributes.preferredName",
    "verification": "$.Attributes.authStatus",
    "handoverSummary": "$.Attributes.handoverSummary",
}
# What the assistant sets on its way out, read back here.
CONTEXT_OUT = ("summary", "escalationReason")
# The Lambda's reply, copied onto the contact under the names ARIA human handover reads.
HANDOVER_ATTRIBUTES = ("topicCategory", "customerIntent", "escalationReason", "conversationSummary", "disputeId")
FALLBACK_SUMMARY = ("Card dispute: the hand-over summary could not be built. The details the assistant saved are "
                    "on the dispute form; open it from this screen pop.")


def build(region, account_id, instance_id, workspace_id, application_id, alias, handover_flow_id, function) -> dict:
    handover_arn = f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}/contact-flow/{handover_flow_id}"
    from_assistant = lambda name: f"$.AgenticCX.ContextVariables.{name}"        # noqa: E731

    laid_out = [
        ({
            "Identifier": "CardDisputeAssistant",
            "Type": "ConnectParticipantWithAgenticCX",
            "Parameters": {
                "AgentConfiguration": {"WorkspaceId": workspace_id, "ContextVariables": CONTEXT_IN,
                                       "ApplicationId": application_id, "Alias": alias},
                "SpeechRecognitionConfiguration": {"SpeechRecognitionEngine": "AMAZON_AGENTIC_VOICE"},
                "AudioFillerConfiguration": {"Enabled": True, "AudioType": "TYPING_QUIET_QWERTY",
                                             "StartDelayInMilliseconds": 2500,
                                             "MinimumPlayDurationInMilliseconds": 3000,
                                             "ResponseDeliveryDelayInMilliseconds": 500},
                "IdleChatTimeoutSeconds": 600,
            },
            # Every way out reaches a person, through the record, except the caller hanging up.
            "Transitions": {
                "NextAction": "BuildHandover",
                "Conditions": [{"NextAction": "BuildHandover",
                                "Condition": {"Operator": "Equals", "Operands": ["Escalation"]}}],
                "Errors": [{"NextAction": "BuildHandover", "ErrorType": "NoMatchingError"},
                           {"NextAction": "BuildHandover", "ErrorType": "NoMatchingCondition"},
                           {"NextAction": "Disconnect", "ErrorType": "InputTimeLimitExceeded"}],
            },
        }, 280, 100),
        ({
            "Identifier": "BuildHandover",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": f"arn:aws:lambda:{region}:{account_id}:function:{function}",
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "LambdaInvocationAttributes": {"operation": "handover",
                                               "assistantSummary": from_assistant("summary"),
                                               "assistantReason": from_assistant("escalationReason")},
                "ResponseValidation": {"ResponseType": "STRING_MAP"},
            },
            "Transitions": {"NextAction": "SetHandover",
                            "Errors": [{"NextAction": "HandoverUnavailable", "ErrorType": "NoMatchingError"}]},
        }, 560, 100),
        ({
            "Identifier": "SetHandover",
            "Type": "UpdateContactAttributes",
            "Parameters": {"Attributes": {name: f"$.External.{name}" for name in HANDOVER_ATTRIBUTES},
                           "TargetContact": "Current"},
            "Transitions": {"NextAction": "ToHumanHandover",
                            "Errors": [{"NextAction": "HandoverUnavailable", "ErrorType": "NoMatchingError"}]},
        }, 840, 20),
        ({
            "Identifier": "HandoverUnavailable",
            "Type": "UpdateContactAttributes",
            "Parameters": {"Attributes": {"topicCategory": "fraud_security",
                                          "customerIntent": "Dispute a card transaction",
                                          "escalationReason": "tool_failure",
                                          "conversationSummary": FALLBACK_SUMMARY},
                           "TargetContact": "Current"},
            "Transitions": {"NextAction": "ToHumanHandover",
                            "Errors": [{"NextAction": "ToHumanHandover", "ErrorType": "NoMatchingError"}]},
        }, 840, 240),
        ({
            "Identifier": "ToHumanHandover",
            "Type": "TransferToFlow",
            "Parameters": {"ContactFlowId": handover_arn},
            "Transitions": {"NextAction": "Disconnect",
                            "Errors": [{"NextAction": "Disconnect", "ErrorType": "NoMatchingError"}]},
        }, 1120, 100),
        ({"Identifier": "Disconnect", "Type": "DisconnectParticipant", "Parameters": {}, "Transitions": {}}, 1400, 100),
    ]

    metadata = {a["Identifier"]: {"position": {"x": x, "y": y}} for a, x, y in laid_out}
    # What the designer itself saves for these blocks, so the import opens with every value in place.
    metadata["CardDisputeAssistant"]["parameters"] = {
        "AgentConfiguration": {"ContextVariables": {name: {"displayName": name, "useDynamic": True}
                                                    for name in CONTEXT_IN}},
        "IdleChatTimeoutSeconds": {"unit": 60}}
    lambda_attributes = laid_out[1][0]["Parameters"]["LambdaInvocationAttributes"]
    metadata["BuildHandover"]["parameters"] = {
        "LambdaFunctionARN": {"displayName": function},
        "LambdaInvocationAttributes": {k: {"useDynamic": True} for k, v in lambda_attributes.items() if v.startswith("$.")}}
    metadata["BuildHandover"]["dynamicMetadata"] = {k: v.startswith("$.") for k, v in lambda_attributes.items()}
    metadata["SetHandover"]["parameters"] = {"Attributes": {name: {"useDynamic": True} for name in HANDOVER_ATTRIBUTES}}
    metadata["SetHandover"]["dynamicParams"] = list(HANDOVER_ATTRIBUTES)
    metadata["HandoverUnavailable"]["dynamicParams"] = []

    return {
        "Version": "2019-10-30",
        "StartAction": "CardDisputeAssistant",
        "Metadata": {"entryPointPosition": {"x": 40, "y": 100}, "ActionMetadata": metadata, "Annotations": [],
                     "name": FLOW_NAME, "description": FLOW_DESCRIPTION, "type": "contactFlow", "status": "saved"},
        "Actions": [a for a, _, _ in laid_out],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the card dispute assistant flow JSON.")
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--account-id", default=ACCOUNT_ID)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--workspace-id", default=WORKSPACE_ID, help="CX designer workspace (default: ariaworkspace)")
    parser.add_argument("--application-id", default=NOT_CHOSEN, help="The 'Card dispute' CX designer application's ID")
    parser.add_argument("--alias", default=NOT_CHOSEN, help="The alias of the environment you deployed it to")
    parser.add_argument("--handover-flow-id", default=HUMAN_HANDOVER_FLOW_ID, help="ID of 'ARIA human handover'")
    parser.add_argument("--function", default=DISPUTE_FUNCTION, help="The dispute Lambda's name")
    parser.add_argument("--output", default=str(Path(__file__).parent / "card-dispute-flow.json"))
    args = parser.parse_args()

    flow = build(args.region, args.account_id, args.instance_id, args.workspace_id, args.application_id,
                 args.alias, args.handover_flow_id, args.function)
    Path(args.output).write_text(json.dumps(flow, indent=2) + "\n")
    print(f"Wrote {args.output} ({len(flow['Actions'])} blocks)")
    if NOT_CHOSEN in (args.application_id, args.alias):
        print("  No application was given: after importing, open the Agentic CX block and choose "
              "the 'Card dispute' application and its environment.")


if __name__ == "__main__":
    main()
