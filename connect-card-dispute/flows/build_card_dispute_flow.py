#!/usr/bin/env python3
"""
build_card_dispute_flow.py
==========================
Generates flows/card-dispute-flow.json: the Connect flow ARIA's bot flow
transfers to when ARIA calls its StartCardDispute tool (SPEC Part 4).

    Set contact attributes            records the channel (VOICE or CHAT), so the
          │                           service knows whether to text the form link
          ▼                           or post it in the chat
    Agentic CX block "Card dispute"   the CX designer disputes assistant does the dispute
          │  any way out except the caller hanging up
          ▼
    Back to ARIA?                     the assistant's BackToARIA flow escalates with
          │  escalationReason back_to_aria: the customer has finished with the
          │  dispute and wants something else (or nothing else). Their next
          │  question goes on the contact (returnSummary, entry=returned) and the
          │  contact goes back to ARIA's bot flow, which carries on without
          │  greeting them again (SPEC rule R15)
          ▼  anything else
    Lambda aria-card-dispute          builds the hand-over from the dispute record:
          │                           team, summary, dispute reference
          ▼
    Set contact attributes            the same attributes ARIA's Escalate tool sets
          ▼
    Transfer to flow: ARIA human handover   the same path ARIA's own escalations take

It works the same on a phone call and on chat.

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
ARIA_FLOW_ID = "2b4f7b5c-1351-42c8-acac-add07d0cbd00"            # ARIA conversation bot flow (modular)
BACK_TO_ARIA = "back_to_aria"                                     # the BackToARIA flow's escalationReason
DISPUTE_FUNCTION = "aria-card-dispute"

FLOW_NAME = "Card dispute assistant"
FLOW_DESCRIPTION = ("ARIA hands a card dispute to the CX designer disputes assistant, which does it end to end; "
                    "then the call goes to an adviser through ARIA human handover.")
NOT_CHOSEN = "CHOOSE-IN-THE-BLOCK"

# What Connect passes in. At most ten per block. No customer ID and no verification
# flag: the dispute service finds the customer from the contact itself and refuses
# an unverified one on every call (rules R7, R11). All but "channel" already exist
# in the workspace, created for the mortgage assistant.
CONTEXT_IN = {
    "entry": "$.Attributes.entry",
    "contactId": "$.ContactId",
    "firstName": "$.Attributes.preferredName",
    "handoverSummary": "$.Attributes.handoverSummary",
    "channel": "$.Channel",
}
# What the assistant sets on its way out, read back here.
CONTEXT_OUT = ("summary", "escalationReason")
# The Lambda's reply, copied onto the contact under the names ARIA human handover reads.
HANDOVER_ATTRIBUTES = ("topicCategory", "customerIntent", "escalationReason", "conversationSummary", "disputeId")
# Set on the way back to ARIA: her bot flow and session injector read them (connect-bot-flow-modular).
RETURN_ATTRIBUTES = {"entry": "returned", "returnedFrom": "card_dispute", "handbackRoute": "returned"}
FALLBACK_SUMMARY = ("Card dispute: the hand-over summary could not be built. The details the assistant saved are "
                    "on the dispute form; open it from this screen pop.")


def build(region, account_id, instance_id, workspace_id, application_id, alias, handover_flow_id, function,
          aria_flow_id=ARIA_FLOW_ID) -> dict:
    handover_arn = f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}/contact-flow/{handover_flow_id}"
    aria_arn = f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}/contact-flow/{aria_flow_id}"
    from_assistant = lambda name: f"$.AgenticCX.ContextVariables.{name}"        # noqa: E731

    laid_out = [
        ({
            # Read by the dispute service from Connect's record of the contact, like customerId.
            "Identifier": "RecordChannel",
            "Type": "UpdateContactAttributes",
            "Parameters": {"Attributes": {"disputeChannel": "$.Channel"}, "TargetContact": "Current"},
            "Transitions": {"NextAction": "CardDisputeAssistant",
                            "Errors": [{"NextAction": "CardDisputeAssistant", "ErrorType": "NoMatchingError"}]},
        }, 160, 100),
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
            # Every way out reaches a person, through the record, except the caller hanging up and the assistant's
            # own way back to ARIA (an Escalation with escalationReason back_to_aria).
            "Transitions": {
                "NextAction": "BuildHandover",
                "Conditions": [{"NextAction": "CheckBackToAria",
                                "Condition": {"Operator": "Equals", "Operands": ["Escalation"]}}],
                "Errors": [{"NextAction": "BuildHandover", "ErrorType": "NoMatchingError"},
                           {"NextAction": "BuildHandover", "ErrorType": "NoMatchingCondition"},
                           {"NextAction": "Disconnect", "ErrorType": "InputTimeLimitExceeded"}],
            },
        }, 420, 100),
        ({
            "Identifier": "CheckBackToAria",
            "Type": "Compare",
            "Parameters": {"ComparisonValue": from_assistant("escalationReason")},
            "Transitions": {"NextAction": "BuildHandover",
                            "Conditions": [{"NextAction": "SetBackToAria",
                                            "Condition": {"Operator": "Equals", "Operands": [BACK_TO_ARIA]}}],
                            "Errors": [{"NextAction": "BuildHandover", "ErrorType": "NoMatchingCondition"}]},
        }, 560, -120),
        ({
            "Identifier": "SetBackToAria",
            "Type": "UpdateContactAttributes",
            "Parameters": {"Attributes": {**RETURN_ATTRIBUTES, "returnSummary": from_assistant("summary")},
                           "TargetContact": "Current"},
            "Transitions": {"NextAction": "ToAria",
                            "Errors": [{"NextAction": "BuildHandover", "ErrorType": "NoMatchingError"}]},
        }, 840, -200),
        ({
            "Identifier": "ToAria",
            "Type": "TransferToFlow",
            "Parameters": {"ContactFlowId": aria_arn},
            "Transitions": {"NextAction": "BuildHandover",
                            "Errors": [{"NextAction": "BuildHandover", "ErrorType": "NoMatchingError"}]},
        }, 1120, -200),
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
        }, 700, 100),
        ({
            "Identifier": "SetHandover",
            "Type": "UpdateContactAttributes",
            "Parameters": {"Attributes": {name: f"$.External.{name}" for name in HANDOVER_ATTRIBUTES},
                           "TargetContact": "Current"},
            "Transitions": {"NextAction": "ToHumanHandover",
                            "Errors": [{"NextAction": "HandoverUnavailable", "ErrorType": "NoMatchingError"}]},
        }, 980, 20),
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
        }, 980, 240),
        ({
            "Identifier": "ToHumanHandover",
            "Type": "TransferToFlow",
            "Parameters": {"ContactFlowId": handover_arn},
            "Transitions": {"NextAction": "Disconnect",
                            "Errors": [{"NextAction": "Disconnect", "ErrorType": "NoMatchingError"}]},
        }, 1260, 100),
        ({"Identifier": "Disconnect", "Type": "DisconnectParticipant", "Parameters": {}, "Transitions": {}}, 1540, 100),
    ]

    metadata = {a["Identifier"]: {"position": {"x": x, "y": y}} for a, x, y in laid_out}
    # What the designer itself saves for these blocks, so the import opens with every value in place.
    metadata["CardDisputeAssistant"]["parameters"] = {
        "AgentConfiguration": {"ContextVariables": {name: {"displayName": name, "useDynamic": True}
                                                    for name in CONTEXT_IN}},
        "IdleChatTimeoutSeconds": {"unit": 60}}
    metadata["RecordChannel"]["parameters"] = {"Attributes": {"disputeChannel": {"useDynamic": True}}}
    metadata["RecordChannel"]["dynamicParams"] = ["disputeChannel"]
    lambda_attributes = next(a for a, _, _ in laid_out if a["Identifier"] == "BuildHandover")["Parameters"]["LambdaInvocationAttributes"]
    metadata["BuildHandover"]["parameters"] = {
        "LambdaFunctionARN": {"displayName": function},
        "LambdaInvocationAttributes": {k: {"useDynamic": True} for k, v in lambda_attributes.items() if v.startswith("$.")}}
    metadata["BuildHandover"]["dynamicMetadata"] = {k: v.startswith("$.") for k, v in lambda_attributes.items()}
    metadata["SetHandover"]["parameters"] = {"Attributes": {name: {"useDynamic": True} for name in HANDOVER_ATTRIBUTES}}
    metadata["SetHandover"]["dynamicParams"] = list(HANDOVER_ATTRIBUTES)
    metadata["HandoverUnavailable"]["dynamicParams"] = []
    metadata["SetBackToAria"]["parameters"] = {"Attributes": {"returnSummary": {"useDynamic": True}}}
    metadata["SetBackToAria"]["dynamicParams"] = ["returnSummary"]

    return {
        "Version": "2019-10-30",
        "StartAction": "RecordChannel",
        "Metadata": {"entryPointPosition": {"x": 20, "y": 100}, "ActionMetadata": metadata, "Annotations": [],
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
    parser.add_argument("--aria-flow-id", default=ARIA_FLOW_ID, help="ID of ARIA's bot flow (the way back to ARIA)")
    parser.add_argument("--output", default=str(Path(__file__).parent / "card-dispute-flow.json"))
    args = parser.parse_args()
    # The block needs the environment's alias CODE (like MyX46JWMLhtmdRWZgXTDe), not its name.
    # Given "Production", CX designer answers "NLX Streaming Request Failed With Status: 400".
    if args.alias.lower() in ("production", "development", "prod", "dev", "test", "staging"):
        parser.error(f"--alias {args.alias} is the environment's name. Use its alias code (a random-looking "
                     "string such as MyX46JWMLhtmdRWZgXTDe), or leave --alias off and choose the environment "
                     "in the Agentic CX block after import.")

    flow = build(args.region, args.account_id, args.instance_id, args.workspace_id, args.application_id,
                 args.alias, args.handover_flow_id, args.function, args.aria_flow_id)
    Path(args.output).write_text(json.dumps(flow, indent=2) + "\n")
    print(f"Wrote {args.output} ({len(flow['Actions'])} blocks)")
    if NOT_CHOSEN in (args.application_id, args.alias):
        print("  No application was given: after importing, open the Agentic CX block and choose "
              "the 'Card dispute' application and its environment.")


if __name__ == "__main__":
    main()
