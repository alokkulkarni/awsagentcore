"""Creates or updates ARIA v2's AI agent with boto3, for create_agent.sh.

The AWS CLI's built-in model can lag the API: CLI 2.35 rejects the agent's
multiAgentConfigurations (the Money Hub collaborator) before sending anything. boto3's
model has it, so the agent calls go through here. Every request is first checked against
boto3's own model, offline, so a bad payload fails before anything is sent.

    python3 qconnect_agent.py check  CONFIG
    python3 qconnect_agent.py create CONFIG --assistant-id A --region R --name N --description D --tag K=V
    python3 qconnect_agent.py update CONFIG --assistant-id A --region R --agent-id ID

create prints the new agent's ID. Run it with the deploy venv's python
(~/.venvs/aria-deploy/bin/python3); it needs botocore that knows multiAgentConfigurations.
"""
import argparse
import json
import sys

import boto3
import botocore.session
from botocore.validate import validate_parameters

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["check", "create", "update"])
parser.add_argument("config")
parser.add_argument("--assistant-id", default="e6991ed4-e11c-4194-8d20-13889a36bd15")
parser.add_argument("--region", default="eu-west-2")
parser.add_argument("--name")
parser.add_argument("--description", default="")
parser.add_argument("--tag")
parser.add_argument("--agent-id")
args = parser.parse_args()

configuration = json.load(open(args.config))
model = botocore.session.get_session().get_service_model("qconnect")
known = model.shape_for("OrchestrationAIAgentConfiguration").members
if "multiAgentConfigurations" not in known:
    sys.exit("this botocore doesn't know multiAgentConfigurations: run "
             "~/.venvs/aria-deploy/bin/pip install -U boto3")

if args.action == "update":
    if not args.agent_id:
        sys.exit("update needs --agent-id")
    operation = "UpdateAIAgent"
    params = {"assistantId": args.assistant_id, "aiAgentId": args.agent_id,
              "visibilityStatus": "PUBLISHED", "configuration": configuration}
else:
    operation = "CreateAIAgent"
    key, _, value = (args.tag or "project=connect-bot-flow-modular").partition("=")
    params = {"assistantId": args.assistant_id, "name": args.name or "aria-conversation-agent-v2",
              "type": "ORCHESTRATION", "visibilityStatus": "PUBLISHED",
              "description": args.description, "configuration": configuration,
              "tags": {key: value}}

validate_parameters(params, model.operation_model(operation).input_shape)   # raises if invalid
if args.action == "check":
    tools = len(configuration["orchestrationAIAgentConfiguration"].get("toolConfigurations", []))
    print(f"valid {operation} request: {tools} tools, "
          f"{len(configuration['orchestrationAIAgentConfiguration'].get('multiAgentConfigurations', []))} collaborator(s)")
    sys.exit(0)

client = boto3.client("qconnect", region_name=args.region)
if operation == "CreateAIAgent":
    print(client.create_ai_agent(**params)["aiAgent"]["aiAgentId"])
else:
    client.update_ai_agent(**params)
