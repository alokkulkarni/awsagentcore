# ARIA — AgentCore Deployment Guide

How to deploy ARIA to Amazon Bedrock AgentCore Runtime (eu-west-2), including
cross-region access to Nova Sonic 2 (eu-north-1) and Claude Sonnet 4.6 (eu-west-2).

> **Recommended:** Use the automated deployment script — it handles all AWS resource
> creation, YAML patching, and IAM policy attachment in one interactive flow:
> ```bash
> ./scripts/deploy.sh deploy    # full interactive deploy
> ./scripts/deploy.sh teardown  # destroy all resources
> ./scripts/deploy.sh status    # print deployment state
> ```
> The manual steps below are the reference for what the script does.

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

---

## Audit event configuration

ARIA records a structured JSON audit event for every tool call (card block,
authentication, account data access, PII vault operations, etc.).

### Local mode — no configuration needed

Audit events are automatically written to JSONL files under `./audit/` when
running via `main.py`.  Each file is append-only:

```
audit/
  CUST-001/
    2026-03-29/
      audit.jsonl     ← one JSON line per tool call
```

Sample event written locally:

```json
{"event_id": "a3f7c2d1-...", "event_type": "CARD_BLOCK", "category": "CARD_MANAGEMENT",
 "tier": 1, "severity": "CRITICAL", "timestamp": "2026-03-29T10:58:32Z",
 "session_id": "...", "customer_id": "CUST-001", "channel": "voice",
 "actor": "ARIA", "tool_name": "block_debit_card",
 "parameters": {"card_last_four": "1234", "reason": "lost"},
 "outcome": "SUCCESS", "authenticated": true}
```

Add `audit/` to `.gitignore` (already done) so local audit files are never committed.

### Cloud mode — EventBridge setup

#### Step 1 — Create the EventBridge custom bus

```bash
aws events create-event-bus --name aria-audit --region eu-west-2
# Note the ARN: arn:aws:events:eu-west-2:<account>:event-bus/aria-audit
```

#### Step 2 — Set AUDIT_EVENTBRIDGE_BUS in .bedrock_agentcore.yaml

```yaml
environment:
  AUDIT_STORE: eventbridge         # or "both" to also write local JSONL
  AUDIT_EVENTBRIDGE_BUS: aria-audit
  AUDIT_REGION: eu-west-2
```

#### Step 3 — Add IAM permission to the execution role

```json
{
  "Sid": "AuditEventBridge",
  "Effect": "Allow",
  "Action": ["events:PutEvents"],
  "Resource": "arn:aws:events:eu-west-2:<account>:event-bus/aria-audit"
}
```

#### Step 4 — Create EventBridge rules (fan-out)

Create rules on the `aria-audit` bus to route events to downstream stores.
All three rules use the same event pattern (all ARIA audit events):

```json
{ "source": ["com.meridianbank.aria"], "detail-type": ["BankingAuditEvent"] }
```

**Rule A — CloudTrail Lake** (immutable, 7-year, SQL-queryable):

```bash
# 1. Create a CloudTrail Lake event data store
aws cloudtrail create-event-data-store \
  --name aria-banking-audit \
  --retention-period 2557 \
  --region eu-west-2

# 2. Create a channel for custom events (note the channel ARN output)
aws cloudtrail create-channel \
  --name aria-audit-channel \
  --source Custom \
  --destinations '[{"Type":"EVENT_DATA_STORE","Location":"<event-data-store-arn>"}]' \
  --region eu-west-2

# 3. Create EventBridge rule targeting CloudTrail via Lambda or direct API
#    (use a Lambda that calls cloudtrail-data:PutAuditEvents)
```

**Rule B — DynamoDB** (hot queries, 90-day TTL):

```bash
# Create table
aws dynamodb create-table \
  --table-name aria-audit-events \
  --attribute-definitions \
      AttributeName=customer_id,AttributeType=S \
      AttributeName=timestamp,AttributeType=S \
  --key-schema \
      AttributeName=customer_id,KeyType=HASH \
      AttributeName=timestamp,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region eu-west-2

# Add EventBridge rule → Lambda → DynamoDB PutItem
# Set TTL attribute: add 90 days to the timestamp in the Lambda
```

**Rule C — S3 WORM** (7-year compliance archive via Kinesis Firehose):

```bash
# Create delivery stream (S3 destination with Object Lock)
aws firehose create-delivery-stream \
  --delivery-stream-name aria-audit-firehose \
  --s3-destination-configuration \
      "BucketARN=arn:aws:s3:::meridian-aria-audit-<account>,..." \
  --region eu-west-2

# S3 bucket must have Object Lock enabled (COMPLIANCE mode) + Versioning
```

### IAM permissions summary

Add all three to the AgentCore Runtime execution role:

```json
[
  {
    "Sid": "AuditEventBridge",
    "Effect": "Allow",
    "Action": ["events:PutEvents"],
    "Resource": "arn:aws:events:eu-west-2:<account>:event-bus/aria-audit"
  },
  {
    "Sid": "AuditCloudTrailLake",
    "Effect": "Allow",
    "Action": ["cloudtrail-data:PutAuditEvents"],
    "Resource": "arn:aws:cloudtrail:eu-west-2:<account>:channel/<channel-id>"
  },
  {
    "Sid": "AuditDynamoDB",
    "Effect": "Allow",
    "Action": ["dynamodb:PutItem"],
    "Resource": "arn:aws:dynamodb:eu-west-2:<account>:table/aria-audit-events"
  }
]
```

### Querying audit events

**CloudTrail Lake** (SQL — official audit/compliance source):

```sql
-- All card blocks for a customer in the last 30 days
SELECT eventData
FROM   <event-data-store-id>
WHERE  json_extract_scalar(eventData, '$.customer_id') = 'CUST-001'
AND    json_extract_scalar(eventData, '$.event_type')  = 'CARD_BLOCK'
AND    eventTime > DATE_ADD('day', -30, NOW())
```

**DynamoDB** (fast operational lookup):

```python
import boto3
dynamodb = boto3.resource("dynamodb", region_name="eu-west-2")
table = dynamodb.Table("aria-audit-events")
response = table.query(
    KeyConditionExpression="customer_id = :cid",
    ExpressionAttributeValues={":cid": "CUST-001"},
    ScanIndexForward=False,    # newest first
    Limit=50,
)
```

**S3 / Athena** (bulk analytics across all customers):

```sql
-- All Tier 1 actions in the last month across all customers
SELECT customer_id, event_type, tool_name, outcome, timestamp
FROM   audit_events_table
WHERE  tier = 1
AND    timestamp >= date_format(date_add('month', -1, now()), '%Y-%m')
ORDER  BY timestamp DESC;
```
