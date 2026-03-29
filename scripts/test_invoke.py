"""Quick smoke-test for the deployed AgentCore agent."""
import boto3, json, uuid

RUNTIME_ARN = "arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-RhdjurH3YC"
REGION      = "eu-west-2"

client     = boto3.client("bedrock-agentcore-runtime", region_name=REGION)
session_id = str(uuid.uuid4())

payload = json.dumps({
    "message":       "Hello Aria, can you confirm you are operational?",
    "authenticated": True,
    "customer_id":   "CUST-SMOKETEST",
}).encode()

print(f"Invoking {RUNTIME_ARN} ...")
response = client.invoke_agent_runtime(
    agentRuntimeArn=RUNTIME_ARN,
    runtimeSessionId=session_id,
    payload=payload,
    qualifier="DEFAULT",
)

for chunk in response["response"]:
    print(chunk.decode("utf-8"), end="", flush=True)
print()
