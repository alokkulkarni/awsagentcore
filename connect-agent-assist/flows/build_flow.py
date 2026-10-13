#!/usr/bin/env python3
"""
build_flow.py
=============
Generates flows/aria-agent-assist-flow.json — the importable Amazon Connect
contact flow that switches on agent assist for a contact and then queues it.

The JSON is generated rather than hand-edited so the values that are specific
to an AWS account live in one place (the constants below, or the command-line
flags). This script only writes a local file. It never calls AWS.

Usage:
    python3 connect-agent-assist/flows/build_flow.py
    python3 connect-agent-assist/flows/build_flow.py --assist-agent-version 4
"""

import argparse
import json
from pathlib import Path

# Defaults: the "conversationbot" Connect instance.
REGION = "eu-west-2"
ACCOUNT_ID = "395402194296"
INSTANCE_ID = "f969d4b4-f716-4974-a325-bb7899f2f293"
ASSISTANT_ID = "e6991ed4-e11c-4194-8d20-13889a36bd15"
ASSIST_AGENT_ID = "26ca6380-17fe-4828-bc53-537e1154ecbb"      # my-agent-assistant-agent
ASSIST_AGENT_VERSION = "3"
SCREEN_POP_FLOW_ID = "4b85d55a-3d5d-4ff8-88b1-33034272e86d"   # ARIA-Agent-Screen-Pop-Flow
INJECTOR_FUNCTION = "aria-agent-assist-injector"

FLOW_NAME = "ARIA agent assist"
FLOW_DESCRIPTION = ("Switches on agent assist for a contact (analytics, assistant, handover context), "
                    "then queues it for a human agent. Used by ARIA human handover.")


def build(region, account_id, instance_id, assistant_id, agent_id, agent_version, screen_pop_flow_id) -> dict:
    instance_arn = f"arn:aws:connect:{region}:{account_id}:instance/{instance_id}"
    assistant_arn = f"arn:aws:wisdom:{region}:{account_id}:assistant/{assistant_id}"
    agent_arn = f"arn:aws:wisdom:{region}:{account_id}:ai-agent/{assistant_id}/{agent_id}:{agent_version}"

    def on_error(target: str, *extra: str) -> list[dict]:
        return [{"NextAction": target, "ErrorType": kind} for kind in ("NoMatchingError", *extra)]

    # (action, x, y) — positions only affect how the flow looks in the designer.
    # Every failure before the queue carries on towards the queue: a problem
    # with agent assist must never stop the customer reaching a person.
    laid_out = [
        ({
            "Identifier": "EnableLogging",
            "Type": "UpdateFlowLoggingBehavior",
            "Parameters": {"FlowLoggingBehavior": "Enabled"},
            "Transitions": {"NextAction": "CheckChannel"},
        }, 200, 40),
        ({
            "Identifier": "CheckChannel",
            "Type": "Compare",
            "Parameters": {"ComparisonValue": "$.Channel"},
            "Transitions": {
                "NextAction": "VoiceAnalytics",
                "Conditions": [{"NextAction": "ChatAnalytics",
                                "Condition": {"Operator": "Equals", "Operands": ["CHAT"]}}],
                "Errors": [{"NextAction": "VoiceAnalytics", "ErrorType": "NoMatchingCondition"}],
            },
        }, 440, 40),
        ({
            # Calls: the assistant only makes suggestions when real-time
            # conversational analytics is on for the contact.
            "Identifier": "VoiceAnalytics",
            "Type": "UpdateContactRecordingAndAnalyticsBehavior",
            "Parameters": {"VoiceBehavior": {
                "VoiceRecordingBehavior": {"RecordedParticipants": ["Agent", "Customer"],
                                           "IVRRecordingBehavior": "Enabled"},
                "VoiceAnalyticsBehavior": {
                    "Enabled": "True", "AnalyticsLanguage": "en-GB",
                    "AnalyticsModes": ["RealTime", "AutomatedInteraction"],
                    "ConversationalAnalyticsRedactionConfiguration": {"Enabled": "False"},
                    "SentimentConfiguration": {"Enabled": "True"},
                    "SummaryConfiguration": {"SummaryModes": ["PostContact", "AutomatedInteraction"]},
                }}},
            "Transitions": {"NextAction": "ConnectAssistant",
                            "Errors": on_error("ConnectAssistant", "ChannelMismatch")},
        }, 680, -80),
        ({
            "Identifier": "ChatAnalytics",
            "Type": "UpdateContactRecordingAndAnalyticsBehavior",
            "Parameters": {"ChatBehavior": {"ChatAnalyticsBehavior": {
                "Enabled": "True", "AnalyticsLanguage": "en-GB", "AnalyticsModes": ["ContactLens"],
                "ConversationalAnalyticsRedactionConfiguration": {"Enabled": "False"},
                "InFlightChatRedactionConfiguration": {"Enabled": "False"},
                "SentimentConfiguration": {"Enabled": "True"},
                "SummaryConfiguration": {"SummaryModes": ["PostContact", "AutomatedInteraction"]},
            }}},
            "Transitions": {"NextAction": "ConnectAssistant",
                            "Errors": on_error("ConnectAssistant", "ChannelMismatch",
                                               "InFlightRedactionConfigurationFailed")},
        }, 680, 160),
        ({
            # "Connect assistant": starts a NEW assistant session for the human
            # agent, separate from the one ARIA used with the customer.
            "Identifier": "ConnectAssistant",
            "Type": "CreateWisdomSession",
            "Parameters": {"WisdomAssistantArn": assistant_arn,
                           "OrchestrationAIAgentConfiguration": {"AgentAssistanceAgentVersionArn": agent_arn}},
            "Transitions": {"NextAction": "SetAssistantSession", "Errors": on_error("SetAgentScreen")},
        }, 920, 40),
        ({
            "Identifier": "SetAssistantSession",
            "Type": "UpdateContactData",
            "Parameters": {"WisdomSessionArn": "$.Wisdom.SessionArn"},
            "Transitions": {"NextAction": "InjectContext", "Errors": on_error("SetAgentScreen")},
        }, 1160, 40),
        ({
            "Identifier": "InjectContext",
            "Type": "InvokeLambdaFunction",
            "Parameters": {
                "LambdaFunctionARN": f"arn:aws:lambda:{region}:{account_id}:function:{INJECTOR_FUNCTION}",
                "InvocationTimeLimitSeconds": "8",
                "InvocationType": "SYNCHRONOUS",
                "ResponseValidation": {"ResponseType": "STRING_MAP"},
            },
            "Transitions": {"NextAction": "SetAgentScreen", "Errors": on_error("SetAgentScreen")},
        }, 1400, 40),
        ({
            # "Set event flow": the screen pop the agent sees when the contact arrives.
            "Identifier": "SetAgentScreen",
            "Type": "UpdateContactEventHooks",
            "Parameters": {"EventHooks": {"DefaultAgentUI": f"{instance_arn}/contact-flow/{screen_pop_flow_id}"}},
            "Transitions": {"NextAction": "SetQueue", "Errors": on_error("SetQueue")},
        }, 1640, 40),
        ({
            # The handover flow passes the queue it chose in the ariaQueueId
            # attribute. If that is missing, the working queue already set on
            # the contact is used, so the error branch simply carries on.
            "Identifier": "SetQueue",
            "Type": "UpdateContactTargetQueue",
            "Parameters": {"QueueId": "$.Attributes.ariaQueueId"},
            "Transitions": {"NextAction": "TransferToQueue", "Errors": on_error("TransferToQueue")},
        }, 1880, 40),
        ({
            "Identifier": "TransferToQueue",
            "Type": "TransferContactToQueue",
            "Parameters": {},
            "Transitions": {"NextAction": "QueueProblem",
                            "Errors": on_error("QueueProblem", "QueueAtCapacity")},
        }, 2120, 40),
        ({
            "Identifier": "QueueProblem",
            "Type": "MessageParticipant",
            "Parameters": {"SkipWhenDTMFBufferEnabled": "false",
                           "Text": "I'm sorry, I wasn't able to connect you to a colleague just now. "
                                   "Please try again shortly."},
            "Transitions": {"NextAction": "Disconnect", "Errors": on_error("Disconnect")},
        }, 2120, 240),
        ({"Identifier": "Disconnect", "Type": "DisconnectParticipant", "Parameters": {}, "Transitions": {}},
         2360, 240),
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
    parser = argparse.ArgumentParser(description="Generate the ARIA agent assist contact flow JSON.")
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--account-id", default=ACCOUNT_ID)
    parser.add_argument("--instance-id", default=INSTANCE_ID)
    parser.add_argument("--assistant-id", default=ASSISTANT_ID)
    parser.add_argument("--assist-agent-id", default=ASSIST_AGENT_ID)
    parser.add_argument("--assist-agent-version", default=ASSIST_AGENT_VERSION,
                        help="Published version of the agent-assistance AI agent to pin (default: %(default)s)")
    parser.add_argument("--screen-pop-flow-id", default=SCREEN_POP_FLOW_ID)
    parser.add_argument("--output", default=str(Path(__file__).parent / "aria-agent-assist-flow.json"))
    args = parser.parse_args()

    flow = build(args.region, args.account_id, args.instance_id, args.assistant_id, args.assist_agent_id,
                 args.assist_agent_version, args.screen_pop_flow_id)
    Path(args.output).write_text(json.dumps(flow, indent=2) + "\n")
    print(f"Wrote {args.output} ({len(flow['Actions'])} blocks, assist agent version {args.assist_agent_version})")


if __name__ == "__main__":
    main()
