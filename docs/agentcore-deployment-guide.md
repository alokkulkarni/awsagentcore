# ARIA — AgentCore Deployment Guide

How to deploy ARIA to Amazon Bedrock AgentCore Runtime (eu-west-2), including
cross-region access to Nova Sonic 2 (eu-north-1) and Claude Sonnet 4.6 (eu-west-2).

---

## Pre-deployment checklist

Before running any commands, confirm the following are in place:

| Item | Action |
|---|---|
| **AWS account + CLI** | `aws configure` or export `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` |
| **Model access — Claude** | Bedrock console → Model access → enable Claude Sonnet 4.x in **eu-west-2** |
| **Model access — Nova Sonic** | Bedrock console → Model access → enable Nova Sonic 2 in **eu-north-1** |
| **AgentCore availability** | AgentCore Runtime is GA in `eu-west-2` — confirmed |
| **Toolkit installed** | `bedrock-agentcore-starter-toolkit` is in `requirements.txt`; verify with `agentcore --help` |
| **Docker** | Only needed for `--local-build` mode. Default deploy uses AWS CodeBuild — no local Docker required |
| **S3 bucket for transcripts** | `aws s3 mb s3://meridian-aria-transcripts-<account-id> --region eu-west-2` |

---

## Configure `.bedrock_agentcore.yaml`

The file already exists in the project root. Verify the region, entrypoint, and
environment variables match your account:

```yaml
bedrock_agentcore:
  name: aria-banking-agent
  region: eu-west-2                # AgentCore Runtime region
  entrypoint: aria/agentcore_app.py
  deployment_type: container       # uses your Dockerfile
  ecr:
    auto: true                     # toolkit creates the ECR repo automatically
  environment:
    AWS_REGION: eu-west-2                                     # Claude region
    NOVA_SONIC_REGION: eu-north-1                             # Nova Sonic 2 region
    TRANSCRIPT_S3_BUCKET: meridian-aria-transcripts-<account-id>
    TRANSCRIPT_S3_PREFIX: transcripts
    LOG_LEVEL: INFO
```

---

## Deployment commands

### Option A — Default (recommended, no Docker needed)

CodeBuild builds the ARM64 container in the cloud:

```bash
# From the project root (awsagentcore/)
agentcore launch
```

This single command:
1. Packages your code and sends it to AWS CodeBuild
2. Builds the ARM64 Docker image in the cloud (no local Docker required)
3. Pushes the image to ECR (`bedrock-agentcore-aria-banking-agent`)
4. Deploys the container to AgentCore Runtime in `eu-west-2`
5. Creates the execution IAM role, CloudWatch log group, and runtime endpoint
6. Prints the **Agent Runtime ARN** — save it, you need it to invoke the agent

### Option B — Local Docker build, cloud deploy

Build the image on your Mac first, then push and deploy:

```bash
agentcore launch --local-build
```

Requires Docker Desktop. The toolkit handles the `--platform linux/arm64` flag automatically.

### Option C — Fully local (dev / test only)

Run the full container stack on your machine without deploying to AWS:

```bash
agentcore launch --local        # starts on localhost:8080
agentcore invoke --dev '{"message": "Hello Aria"}'
```

Equivalent to running `uvicorn aria.agentcore_app:app --port 8080` but with the
full AgentCore Runtime environment variables injected.

---

## IAM execution role — additions required

The `agentcore launch` command auto-creates an execution role. You need to attach
**two additional inline policies** to that role for ARIA's cross-region access pattern.

Find the role: AWS Console → IAM → Roles → search `BedrockAgentCore`.

### Policy 1: Cross-region Bedrock (Claude + Nova Sonic)

```json
{
  "Sid": "BedrockCrossRegion",
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "bedrock:InvokeModelWithBidirectionalStream"
  ],
  "Resource": "arn:aws:bedrock:*::foundation-model/*"
}
```

The `*` region wildcard allows the eu-west-2 container to call both
`bedrock-runtime.eu-west-2.amazonaws.com` (Claude) and
`bedrock-runtime.eu-north-1.amazonaws.com` (Nova Sonic) without separate statements.

### Policy 2: S3 transcript writes

```json
{
  "Sid": "TranscriptS3Write",
  "Effect": "Allow",
  "Action": ["s3:PutObject"],
  "Resource": "arn:aws:s3:::meridian-aria-transcripts-<account-id>/transcripts/*"
}
```

---

## Cross-region model access: eu-west-2 runtime → eu-north-1 Nova Sonic

**Yes, this works — completely.** The container makes outbound HTTPS API calls to
Bedrock endpoints. There is no restriction on calling a Bedrock endpoint in a
different region from your compute. AWS SDK calls are just HTTPS — any region is
reachable from any compute.

```
AgentCore Runtime microVM (eu-west-2)
    │
    ├── Claude Sonnet 4.6 ──► bedrock-runtime.eu-west-2.amazonaws.com  (same region, ~5 ms)
    │
    └── Nova Sonic 2 ────────► bedrock-runtime.eu-north-1.amazonaws.com (cross-region, ~50 ms)
```

### Requirements for cross-region to work

1. IAM execution role has `bedrock:Invoke*` with resource `arn:aws:bedrock:*::foundation-model/*`
   (wildcard region — covered by Policy 1 above)
2. Runtime env vars: `AWS_REGION=eu-west-2` (Claude) and `NOVA_SONIC_REGION=eu-north-1` (Nova Sonic)
3. Model access enabled in **both** regions in the Bedrock console

### Why not run AgentCore Runtime in eu-north-1?

You could, but:

- **Claude Sonnet 4.6 is not available in eu-north-1** — you'd need cross-region Claude calls instead,
  same trade-off in reverse but with a more important model (your primary reasoning model)
- `eu-west-2` (London) is geographically closer to a UK banking customer base
- Running Runtime in eu-west-2 keeps the chat channel entirely within the same region for latency

The ~50 ms cross-region hop for Nova Sonic audio stream setup is negligible in a
voice session where Nova Sonic's own processing latency is measured in seconds.

### Important: do NOT set `AWS_REGION=eu-north-1`

`AWS_REGION` controls the Claude (Strands) boto3 session.
`NOVA_SONIC_REGION` is a separate env var used only by `voice_agent.py` and
`agentcore_voice.py` to build their own boto3 session for the bidirectional stream.
They are intentionally decoupled so each model uses the correct region.

---

## Testing your deployed agent

### Via the starter toolkit CLI

```bash
# Chat turn
agentcore invoke '{"message": "Hello Aria", "authenticated": true, "customer_id": "CUST-001"}'

# Stop the current session (saves cost — default idle timeout is 15 min)
agentcore stop-session
```

### Via boto3 (programmatic)

```python
import boto3, json, uuid

client = boto3.client("bedrock-agentcore", region_name="eu-west-2")

response = client.invoke_agent_runtime(
    agentRuntimeArn="arn:aws:bedrock-agentcore:eu-west-2:<account>:agent-runtime/<id>",
    runtimeSessionId=str(uuid.uuid4()),     # new UUID per session
    payload=json.dumps({
        "message":       "Hello Aria",
        "authenticated": True,
        "customer_id":   "CUST-001"
    }).encode(),
    qualifier="DEFAULT"
)

for chunk in response["response"]:
    print(chunk.decode("utf-8"), end="")
```

### Multi-turn chat (same session)

Pass the **same** `runtimeSessionId` on every call within a session. AgentCore
routes all requests with the same session ID to the same microVM, preserving
the in-memory agent and conversation state.

```python
session_id = str(uuid.uuid4())   # create once, reuse for all turns

# Turn 1 — first call includes auth info
client.invoke_agent_runtime(..., runtimeSessionId=session_id,
    payload=json.dumps({"message": "Hello", "authenticated": True, "customer_id": "CUST-001"}).encode())

# Turn 2 — subsequent calls only need the message
client.invoke_agent_runtime(..., runtimeSessionId=session_id,
    payload=json.dumps({"message": "What is my balance?"}).encode())
```

---

## Where to find resources after deployment

| Resource | AWS Console location |
|---|---|
| Agent Runtime ARN | Printed by `agentcore launch`; also in `.bedrock_agentcore.yaml` (hidden section) |
| Agent logs | CloudWatch → Log groups → `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT` |
| Container image | ECR → Repositories → `bedrock-agentcore-aria-banking-agent` |
| CodeBuild build logs | CodeBuild → Build history |
| IAM execution role | IAM → Roles → search `BedrockAgentCore` |
| Transcripts | S3 → `s3://meridian-aria-transcripts-<account>/transcripts/` |
| Metrics + traces | CloudWatch → GenAI Observability dashboard |

---

## Teardown

```bash
agentcore stop-session   # stop the running session immediately (cost saving)
agentcore destroy        # delete ALL AWS resources created by the toolkit
                         # (ECR repo, IAM role, Runtime endpoint, CloudWatch group)
```

> **Note:** `agentcore destroy` does not delete the S3 transcript bucket or its
> contents. Delete those separately if required.

---

## Full deployment architecture

```
Developer machine
  └── agentcore launch
        │
        ├── AWS CodeBuild (eu-west-2)
        │     └── docker build --platform linux/arm64 .
        │           └── ECR: bedrock-agentcore-aria-banking-agent (eu-west-2)
        │
        └── AgentCore Runtime (eu-west-2)
              ├── Container: aria/agentcore_app.py  port 8080
              │     ├── GET  /ping         → health check
              │     ├── POST /invocations  → chat (Strands + Claude Sonnet 4.6)
              │     │         └── bedrock-runtime.eu-west-2.amazonaws.com
              │     └── WS   /ws           → voice (Nova Sonic 2 S2S)
              │               └── bedrock-runtime.eu-north-1.amazonaws.com
              │
              ├── CloudWatch Logs  /aws/bedrock-agentcore/runtimes/...
              ├── X-Ray traces
              └── S3 transcripts   s3://meridian-aria-transcripts.../
```
