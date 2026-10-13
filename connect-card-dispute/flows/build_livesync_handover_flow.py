#!/usr/bin/env python3
"""
build_livesync_handover_flow.py
===============================
Generates flows/card-dispute-livesync-handover-flow.json: the Connect flow that
hands a caller from ARIA to the CX designer "Card dispute" assistant, and from
there to an adviser.

It mirrors the live flow "Mortgage Live Sync handover", block for block:

    Agentic CX block ──Escalation──► Set contact attributes ──► Transfer to flow: ARIA human handover
          │
          └─ anything else ────────► Set contact attributes (assistant unavailable) ─► same transfer

The topic the adviser's queue is chosen by comes from the assistant
(fraud_security, debit_card or credit_card). If it sends none, the contact goes
to fraud_security rather than nowhere.

This script only writes a local file. It never calls AWS.

Usage:
    python3 connect-card-dispute/flows/build_livesync_handover_flow.py \\
        --application-id <id> --alias <alias>

Both come from the CX designer application you deployed. Without them the flow
is still written, with the block left for you to point at the application
after import.
"""

import argparse
import json
from pathlib import Path

REGION = "eu-west-2"
ACCOUNT_ID = "395402194296"
INSTANCE_ID = "f969d4b4-f716-4974-a325-bb7899f2f293"
WORKSPACE_ID = "55c49fa0-22f3-4dd3-823d-e353f4aee139"        # ariaworkspace
HUMAN_HANDOVER_FLOW_ID = "0978883b-6892-41ab-81f4-528e0e0cc9bf"   # ARIA human handover

FLOW_NAME = "Card dispute Live Sync handover"
FLOW_DESCRIPTION = ("Hands a caller from ARIA to the CX designer card dispute assistant, which fills the dispute "
                    "form on the customer's screen, then to an adviser.")
NOT_CHOSEN = "CHOOSE-IN-THE-BLOCK"

# What Connect passes in. At most ten per block.
CONTEXT_IN = {
    "entry": "$.Attributes.entry",
    "contactId": "$.ContactId",
    "firstName": "$.Attributes.preferredName",
    "verification": "$.Attributes.authStatus",
    "handoverSummary": "$.Attributes.handoverSummary",
    "screenCode": "$.Attributes.screenCode",
}
INTENT = "Dispute a card transaction"


def build(region, account_id, instance_id, workspace_id, application_id, alias, handover_flow_id) -> dict:
    handover_arn = f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}/contact-flow/{handover_flow_id}"
    from_assistant = lambda name: f"$.AgenticCX.ContextVariables.{name}"        # noqa: E731

    def set_attributes(identifier: str, attributes: dict) -> dict:
        return {"Identifier": identifier, "Type": "UpdateContactAttributes",
                "Parameters": {"Attributes": attributes, "TargetContact": "Current"},
                "Transitions": {"NextAction": "ToHumanHandover",
                                "Errors": [{"NextAction": "ToHumanHandover", "ErrorType": "NoMatchingError"}]}}

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
            "Transitions": {
                "NextAction": "AssistantUnavailable",
                "Conditions": [{"NextAction": "CheckTopic",
                                "Condition": {"Operator": "Equals", "Operands": ["Escalation"]}}],
                "Errors": [{"NextAction": "AssistantUnavailable", "ErrorType": "NoMatchingError"},
                           {"NextAction": "AssistantUnavailable", "ErrorType": "NoMatchingCondition"},
                           {"NextAction": "Disconnect", "ErrorType": "InputTimeLimitExceeded"}],
            },
        }, 280, 100),
        ({
            # The assistant names the team. If it named one of the three, use it.
            "Identifier": "CheckTopic",
            "Type": "Compare",
            "Parameters": {"ComparisonValue": from_assistant("topicCategory")},
            "Transitions": {
                "NextAction": "EscalatedTopicUnknown",
                "Conditions": [{"NextAction": "Escalated", "Condition": {"Operator": "Equals", "Operands": [topic]}}
                               for topic in ("fraud_security", "debit_card", "credit_card")],
                "Errors": [{"NextAction": "EscalatedTopicUnknown", "ErrorType": "NoMatchingCondition"}],
            },
        }, 560, 20),
        (set_attributes("Escalated", {
            "topicCategory": from_assistant("topicCategory"), "customerIntent": INTENT,
            "escalationReason": from_assistant("escalationReason"),
            "conversationSummary": from_assistant("summary")}), 840, -60),
        (set_attributes("EscalatedTopicUnknown", {
            "topicCategory": "fraud_security", "customerIntent": INTENT,
            "escalationReason": from_assistant("escalationReason"),
            "conversationSummary": from_assistant("summary")}), 840, 120),
        (set_attributes("AssistantUnavailable", {
            "topicCategory": "fraud_security", "customerIntent": INTENT,
            "escalationReason": "card_dispute_assistant_error",
            "conversationSummary": "Card dispute not drafted. The on-screen assistant was not available."}), 840, 300),
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
    # What the designer itself stores for these blocks, so the import opens with every value in place.
    metadata["CardDisputeAssistant"]["parameters"] = {
        "AgentConfiguration": {"ContextVariables": {name: {"displayName": name, "useDynamic": True}
                                                    for name in CONTEXT_IN}},
        "IdleChatTimeoutSeconds": {"unit": 60}}
    for name in ("Escalated", "EscalatedTopicUnknown"):
        dynamic = [key for key, value in next(a for a, _, _ in laid_out if a["Identifier"] == name)
                   ["Parameters"]["Attributes"].items() if value.startswith("$.")]
        metadata[name]["parameters"] = {"Attributes": {key: {"useDynamic": True} for key in dynamic}}
        metadata[name]["dynamicParams"] = dynamic
    metadata["AssistantUnavailable"]["dynamicParams"] = []

    return {
        "Version": "2019-10-30",
        "StartAction": "CardDisputeAssistant",
        "Metadata": {"entryPointPosition": {"x": 40, "y": 100}, "ActionMetadata": metadata, "Annotations": [],
                     "name": FLOW_NAME, "description": FLOW_DESCRIPTION, "type": "contactFlow", "status": "saved"},
        "Actions": [a for a, _, _ in laid_out],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the card dispute Live Sync handover flow JSON.")
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--account-id", default=ACCOUNT_ID)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--workspace-id", default=WORKSPACE_ID, help="CX designer workspace (default: ariaworkspace)")
    parser.add_argument("--application-id", default=NOT_CHOSEN, help="The 'Card dispute' CX designer application's ID")
    parser.add_argument("--alias", default=NOT_CHOSEN, help="The alias of the environment you deployed it to")
    parser.add_argument("--handover-flow-id", default=HUMAN_HANDOVER_FLOW_ID, help="ID of 'ARIA human handover'")
    parser.add_argument("--output", default=str(Path(__file__).parent / "card-dispute-livesync-handover-flow.json"))
    args = parser.parse_args()

    flow = build(args.region, args.account_id, args.instance_id, args.workspace_id, args.application_id,
                 args.alias, args.handover_flow_id)
    Path(args.output).write_text(json.dumps(flow, indent=2) + "\n")
    print(f"Wrote {args.output} ({len(flow['Actions'])} blocks)")
    if NOT_CHOSEN in (args.application_id, args.alias):
        print("  No application was given: after importing, open the Agentic CX block and choose "
              "the 'Card dispute' application and its environment.")


if __name__ == "__main__":
    main()
