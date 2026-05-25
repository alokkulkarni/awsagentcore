# Deployment Runbook — ARIA Platform

| Field | Value |
|---|---|
| **Document ID** | RNB-ARIA-001 |
| **Companion Playbook** | PLY-ARIA-001 |
| **Version** | 1.0 |
| **Status** | Active |
| **Owner** | Platform Engineering |
| **Last Updated** | 2026-05-25 |
| **Classification** | Internal |

> **How to use this document:**  Execute each step in sequence. Do not skip steps.  
> Every step includes a **✓ Verify** block — do not proceed until it passes.  
> Steps marked **[DTMF]**, **[ANALYTICS]**, **[EVALUATOR]**, etc. are component-specific; skip if not deploying that component.

---

## Table of Contents

1. [Pre-Deployment Checklist](#1-pre-deployment-checklist)
2. [Phase 1 — Foundation Infrastructure](#2-phase-1--foundation-infrastructure)
3. [Phase 2 — ARIA Banking Agent (AgentCore)](#3-phase-2--aria-banking-agent-agentcore)
4. [Phase 3 — Connect Integration Layer](#4-phase-3--connect-integration-layer)
5. [Phase 4 — Connect Analytics Agent](#5-phase-4--connect-analytics-agent)
6. [Phase 5 — DTMF Secure Capture (Marketplace)](#6-phase-5--dtmf-secure-capture-marketplace)
7. [Phase 6 — Frontends and Chat Widgets](#7-phase-6--frontends-and-chat-widgets)
8. [Phase 7 — Supporting Applications](#8-phase-7--supporting-applications)
9. [Phase 8 — Knowledgebase Sync](#9-phase-8--knowledgebase-sync)
10. [Phase 9 — End-to-End Smoke Tests](#10-phase-9--end-to-end-smoke-tests)
11. [Local Docker Deployment](#11-local-docker-deployment)
12. [Teardown Procedures](#12-teardown-procedures)
13. [Troubleshooting Guide](#13-troubleshooting-guide)
14. [Quick Reference — All Commands](#14-quick-reference--all-commands)

---

## 1. Pre-Deployment Checklist

Work through every item before issuing any deployment command. Record the result for audit purposes.

### 1.1 Environment Validation

```bash
# 1. Confirm AWS identity
aws sts get-caller-identity
# Expected: JSON with Account, UserId, Arn — no error

# 2. Confirm region
echo "Region: $(aws configure get region)"
# Expected: eu-west-2 (or your target region)

# 3. Confirm Bedrock access — Claude
aws bedrock list-foundation-models \
  --region eu-west-2 \
  --query "modelSummaries[?contains(modelId, 'claude')].[modelId,modelLifecycle.status]" \
  --output table
# Expected: claude-sonnet rows with status ACTIVE

# 4. Confirm Bedrock access — Nova Sonic 2
aws bedrock list-foundation-models \
  --region eu-north-1 \
  --query "modelSummaries[?contains(modelId, 'nova-sonic')].[modelId,modelLifecycle.status]" \
  --output table
# Expected: nova-sonic-2 row with status ACTIVE

# 5. Confirm Amazon Connect instance
export CONNECT_INSTANCE_ID="<your-instance-id>"
aws connect describe-instance \
  --instance-id "$CONNECT_INSTANCE_ID" \
  --query "Instance.[InstanceStatus,ServiceRole]" \
  --output table
# Expected: ACTIVE status

# 6. Confirm tooling
aws --version      # aws-cli/2.x.x
docker --version   # Docker version 24+
node --version     # v20.x.x
python3 --version  # Python 3.12+
jq --version       # jq-1.7+
agentcore --version || pip install bedrock-agentcore-starter-toolkit
```

### 1.2 Environment Variables

Set the following before any deployment. Save to a file (never commit):

```bash
# Core
export AWS_REGION="eu-west-2"
export AGENTCORE_REGION="eu-west-2"
export CONNECT_INSTANCE_ID="<uuid>"
export STACK_SUFFIX="prod"        # or "staging"

# ARIA Banking Agent
export BEDROCK_MODEL_ID="eu.anthropic.claude-sonnet-4-6"

# Connect Analytics Agent
export BEDROCK_MODEL_ID_ANALYTICS="us.anthropic.claude-sonnet-4-5"

# DTMF (after key generation — see Phase 5)
export DTMF_PRIVATE_KEY_SECRET_ARN=""
export DTMF_KMS_KEY_ARN=""
export DTMF_CONNECT_KEY_ID=""      # Key ID from Connect Security Profile
```

### 1.3 Repository State

```bash
cd /path/to/awsagentcore

# Confirm clean working tree (no uncommitted changes)
git status
# Expected: nothing to commit, working tree clean

# Confirm correct branch/tag
git log --oneline -5

# Back up deploy state files if they exist
[ -f scripts/.deploy-state.json ] && \
  cp scripts/.deploy-state.json "scripts/.deploy-state.json.bak-$(date +%Y%m%d%H%M)"
[ -f connect-analytics-agent/.deploy-state.json ] && \
  cp connect-analytics-agent/.deploy-state.json \
     "connect-analytics-agent/.deploy-state.json.bak-$(date +%Y%m%d%H%M)"
```

---

## 2. Phase 1 — Foundation Infrastructure

> Executed as part of `scripts/deploy.sh deploy agentcore`. Steps 2.1–2.3 are automated but logged here for visibility and manual recovery reference.

### 2.1 Deploy ARIA Foundation Resources

The main deploy script handles foundation resources in dependency order. Run interactively:

```bash
cd /path/to/awsagentcore
./scripts/deploy.sh deploy agentcore
```

The script will prompt for:
- Amazon Connect instance ID (if not in environment)
- Confirmation before creating paid resources

**What it creates (in order):**

| Step | Resource | AWS Service |
|---|---|---|
| 1 | `meridian-aria-transcripts-<suffix>` | S3 |
| 2 | `meridian-aria-audit-<suffix>` (WORM) | S3 |
| 3 | `meridian-aria-client-<suffix>` | S3 |
| 4 | `aria-audit-events` | DynamoDB |
| 5 | `aria-audit` bus | EventBridge |
| 6 | `aria-banking-audit` (7yr retention) | CloudTrail Lake |
| 7 | `aria-lambda-audit-role` | IAM |
| 8 | `aria-lambda-fulfillment-role` | IAM |
| 9 | `aria-lambda-session-injector-role` | IAM |
| 10 | `aria-firehose-audit-role` | IAM |
| 11 | `audit_cloudtrail_writer` | Lambda |
| 12 | `audit_dynamodb_writer` | Lambda |
| 13 | `aria-audit-firehose` | Kinesis Firehose |
| 14 | EventBridge rules → audit Lambdas | EventBridge |

**✓ Verify Phase 1:**

```bash
# Check S3 buckets
aws s3 ls | grep meridian-aria

# Check DynamoDB table
aws dynamodb describe-table \
  --table-name aria-audit-events \
  --query "Table.TableStatus"
# Expected: "ACTIVE"

# Check EventBridge bus
aws events describe-event-bus \
  --name aria-audit \
  --query "Arn"
# Expected: arn:aws:events:...

# Check audit Lambdas
aws lambda get-function --function-name audit_cloudtrail_writer \
  --query "Configuration.State"
# Expected: "Active"
```

---

## 3. Phase 2 — ARIA Banking Agent (AgentCore)

### 3.1 Launch AgentCore Runtime

Continues as part of the same `./scripts/deploy.sh deploy agentcore` run started in Phase 1.

The script will:
1. Build the ARIA container image from `Dockerfile`
2. Push to ECR repository `bedrock-agentcore-aria-banking-agent`
3. Launch the AgentCore runtime in `eu-west-2`
4. Deploy the `aria_connect_fulfillment` Lambda (Lex V2 integration)
5. Deploy the `aria-session-injector` Lambda (Q in Connect)

**Note:** AgentCore container build can take 5–15 minutes on first run.

**✓ Verify Phase 2:**

```bash
# Check AgentCore runtime status
./scripts/deploy.sh status
# Expected: ARIA AgentCore Runtime: ACTIVE

# Check fulfillment Lambda
aws lambda get-function --function-name aria-lex-fulfillment \
  --query "Configuration.State"
# Expected: "Active"

# Check session injector Lambda
aws lambda get-function --function-name aria-session-injector \
  --query "Configuration.State"
# Expected: "Active"

# Test ARIA chat directly (get endpoint from status output first)
ARIA_ENDPOINT=$(./scripts/deploy.sh status 2>/dev/null | grep "AgentCore Chat URL" | awk '{print $NF}')
curl -s -X POST "$ARIA_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is my account balance?"}' \
  | python3 -m json.tool
# Expected: JSON response with AI reply
```

### 3.2 Deploy Cognito Identity Pool

Also part of the same deploy.sh run. The script creates a Cognito Identity Pool and an unauthenticated IAM role for the React client.

**✓ Verify Phase 2 — Cognito:**

```bash
# Get pool ID from state
python3 -c "import json; s=json.load(open('scripts/.deploy-state.json')); print(s.get('cognito_identity_pool_id','NOT FOUND'))"
# Expected: us-east-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (or your region)
```

---

## 4. Phase 3 — Connect Integration Layer

These are independent scripts in `scripts/`. Run each in the order specified.

### 4.1 Deploy MCP Gateway

```bash
cd /path/to/awsagentcore
bash scripts/deploy_mcp_gateway.sh
```

**✓ Verify:**
```bash
aws lambda get-function --function-name aria-mcp-gateway \
  --query "Configuration.State"
# Expected: "Active"
```

### 4.2 Deploy Routing Lambda

```bash
bash scripts/deploy_routing_lambda.sh
```

**✓ Verify:**
```bash
aws lambda get-function --function-name aria-routing-lookup \
  --query "Configuration.State"
# Expected: "Active"
```

### 4.3 Deploy Callback Lambda

```bash
bash scripts/deploy_callback_lambda.sh
```

**✓ Verify:**
```bash
aws lambda get-function --function-name aria-callback-scheduler \
  --query "Configuration.State"
# Expected: "Active"
```

### 4.4 Deploy WebRTC API

```bash
bash scripts/deploy_webrtc_api.sh
```

**✓ Verify:**
```bash
# Check API Gateway stage for WebRTC
aws apigateway get-rest-apis \
  --query "items[?contains(name,'webrtc')].[name,id]" \
  --output table
# Expected: webrtc API listed
```

### 4.5 Deploy Meeting ID Lambda

```bash
bash scripts/deploy_meeting_id_lambda.sh
```

**✓ Verify:**
```bash
aws lambda get-function --function-name aria-meeting-id-capture \
  --query "Configuration.State"
# Expected: "Active"
```

### 4.6 Deploy Session Injector (Q in Connect)

```bash
bash scripts/deploy_session_injector_qconnect.sh
```

**✓ Verify:**
```bash
aws lambda get-function --function-name aria-session-injector-qconnect \
  --query "Configuration.State"
# Expected: "Active"
```

### 4.7 Configure Amazon Connect Contact Flows

Import or update the contact flows in the Amazon Connect console:

1. Open Amazon Connect console → your instance → **Contact flows**
2. Import the flows from `marketplace/contact-flows/` as needed
3. For ARIA integration, ensure the flow contains:
   - **Session Injector Lambda** block (calls `aria-session-injector-qconnect`)
   - **Lex V2** block (points to your Lex V2 bot associated with `aria-lex-fulfillment`)
   - **DTMF** blocks (if deploying marketplace DTMF)

**✓ Verify:**
```bash
aws connect list-contact-flows \
  --instance-id "$CONNECT_INSTANCE_ID" \
  --contact-flow-types CONTACT_FLOW \
  --query "ContactFlowSummaryList[*].[Name,ContactFlowType]" \
  --output table
```

---

## 5. Phase 4 — Connect Analytics Agent

### 5.1 Deploy Full Analytics Stack

```bash
cd /path/to/awsagentcore/connect-analytics-agent

# Set required variables
export AWS_REGION="us-east-1"          # Adjust to match your Connect instance region
export CONNECT_INSTANCE_ID="<uuid>"
export STACK_SUFFIX="prod"             # or "staging"
export BEDROCK_MODEL_ID="us.anthropic.claude-sonnet-4-5"

./deploy.sh deploy
```

**What it creates:**

| Resource | Detail |
|---|---|
| IAM roles × 3 | `lambda-tools-role`, `agent-role`, `gateway-role` |
| Lambda × 9 | `realtime-metrics`, `historical-metrics`, `agent-states`, `search-contacts`, `contact-detail`, `transcript`, `keyword-search`, `recording-url`, `contact-flow-events` |
| AgentCore Gateway | `connect-analytics-gateway-<suffix>` |
| Agent Lambda | `connect-analytics-agent-<suffix>` |
| API Gateway | REST API for React frontend |
| Cognito | Identity pool for frontend auth |
| S3 + CloudFront | Frontend hosting |

**Duration:** 10–20 minutes

**✓ Verify Phase 4:**

```bash
# Check all 9 tool Lambdas
for tool in realtime-metrics historical-metrics agent-states search-contacts \
            contact-detail transcript keyword-search recording-url contact-flow-events; do
  STATUS=$(aws lambda get-function \
    --function-name "connect-analytics-${tool}-${STACK_SUFFIX}" \
    --query "Configuration.State" --output text 2>/dev/null || echo "NOT FOUND")
  echo "$tool: $STATUS"
done
# Expected: all show "Active"

# Test the agent Lambda
aws lambda invoke \
  --function-name "connect-analytics-agent-${STACK_SUFFIX}" \
  --payload '{"action":"chat","message":"How many agents are available?"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/analytics-test-response.json
cat /tmp/analytics-test-response.json
# Expected: JSON with an AI response about agent counts

# Check CloudFront
ANALYTICS_CF=$(python3 -c "
import json
s = json.load(open('.deploy-state.json'))
print(s.get('cloudfront_domain', 'NOT FOUND'))
")
echo "Analytics Dashboard: https://$ANALYTICS_CF"
curl -s -o /dev/null -w "%{http_code}" "https://$ANALYTICS_CF"
# Expected: 200
```

---

## 6. Phase 5 — DTMF Secure Capture (Marketplace)

> Skip this phase if the marketplace DTMF product is not being deployed.

### 6.1 Generate RSA Key Pair

> **Security note:** This step must be performed by a Security Officer or authorised engineer. The generated private key ARN must be stored securely. Never log or print private key material.

```bash
cd /path/to/awsagentcore

bash scripts/setup_dtmf_keys.sh
# Prompts for:
#   Region:      eu-west-2
#   Secret name: aria/dtmf-private-key
#   KMS alias:   alias/aria-dtmf-cmk
```

**Save the output to a secure secrets manager or vault:**
```
PrivateKeySecretArn: arn:aws:secretsmanager:<region>:<account>:secret:aria/dtmf-private-key-XXXXXX
KmsKeyArn:           arn:aws:kms:<region>:<account>:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Public Key:          -----BEGIN PUBLIC KEY----- ... -----END PUBLIC KEY-----
```

```bash
# Export for subsequent steps
export DTMF_PRIVATE_KEY_SECRET_ARN="arn:aws:secretsmanager:..."
export DTMF_KMS_KEY_ARN="arn:aws:kms:..."
```

### 6.2 Add Public Key to Amazon Connect

1. Open **Amazon Connect Console** → your instance → **Security keys**
2. Click **Add key** → paste full `-----BEGIN PUBLIC KEY-----` ... `-----END PUBLIC KEY-----` block
3. Click **Add** → copy the Key ID (UUID format)

```bash
export DTMF_CONNECT_KEY_ID="<key-id-from-connect-console>"
```

### 6.3 Deploy DTMF CloudFormation Stack

```bash
aws cloudformation deploy \
  --template-file marketplace/cloudformation/dtmf-secure-capture.yaml \
  --stack-name dtmf-secure-capture-${STACK_SUFFIX} \
  --region "$AWS_REGION" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    PrivateKeySecretArn="$DTMF_PRIVATE_KEY_SECRET_ARN" \
    KmsKeyArn="$DTMF_KMS_KEY_ARN" \
    ConnectInstanceId="$CONNECT_INSTANCE_ID" \
    ConnectKeyId="$DTMF_CONNECT_KEY_ID"
```

### 6.4 Deploy DTMF Lambdas

```bash
bash scripts/deploy_dtmf_lambda.sh
```

**What it deploys:**
- `aria-dtmf-start-session` — initialises DynamoDB session
- `aria-dtmf-decrypt` — RSA decrypts DTMF digits
- `aria-dtmf-validate` — Luhn check + BIN validation + ownership
- `aria-dtmf-status-proxy` — polled by agent browser panel

**✓ Verify Phase 5:**

```bash
# Check CloudFormation stack
aws cloudformation describe-stacks \
  --stack-name "dtmf-secure-capture-${STACK_SUFFIX}" \
  --query "Stacks[0].StackStatus"
# Expected: "CREATE_COMPLETE" or "UPDATE_COMPLETE"

# Check all 4 DTMF Lambdas
for fn in aria-dtmf-start-session aria-dtmf-decrypt aria-dtmf-validate aria-dtmf-status-proxy; do
  STATUS=$(aws lambda get-function \
    --function-name "$fn" \
    --query "Configuration.State" --output text 2>/dev/null || echo "NOT FOUND")
  echo "$fn: $STATUS"
done
# Expected: all "Active"

# Test session creation
aws lambda invoke \
  --function-name aria-dtmf-start-session \
  --payload '{"contactId":"test-123","purpose":"card_last_four"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/dtmf-test.json
cat /tmp/dtmf-test.json
# Expected: {"sessionId": "...", "status": "pending"}
```

---

## 7. Phase 6 — Frontends and Chat Widgets

### 7.1 Deploy Meridian Chat Widget

```bash
cd /path/to/awsagentcore
bash scripts/deploy_connect_widget.sh
```

**✓ Verify:**
```bash
# URL will be printed by the script
MERIDIAN_WIDGET_URL=$(cat scripts/.deploy-state.json | python3 -c \
  "import json,sys; s=json.load(sys.stdin); print(s.get('meridian_widget_url',''))")
curl -s -o /dev/null -w "%{http_code}" "$MERIDIAN_WIDGET_URL"
# Expected: 200
```

### 7.2 Deploy Nationwide Chat Widget

```bash
bash scripts/deploy_nationwide_chat_widget.sh
```

**✓ Verify:**
```bash
# Navigate to the deployed URL and confirm widget loads
# URL printed by script at completion
```

### 7.3 Verify ARIA React Client (deployed by scripts/deploy.sh)

The React client is built and deployed to CloudFront by `scripts/deploy.sh`. Verify it:

```bash
./scripts/deploy.sh status
# Note the CloudFront URL, e.g.:
# CloudFront: https://d1abcdef12345.cloudfront.net

ARIA_CF_URL="<cloudfront-url-from-status>"
curl -s -o /dev/null -w "%{http_code}" "$ARIA_CF_URL"
# Expected: 200

# Open in browser and confirm:
# - Login page (Cognito) or main dashboard loads
# - No console errors
```

### 7.4 Verify Client DTMF Agent Panel (if marketplace deployed)

The DTMF panel is served from S3/CloudFront as part of the marketplace CloudFormation.

```bash
DTMF_PANEL_URL=$(aws cloudformation describe-stacks \
  --stack-name "dtmf-secure-capture-${STACK_SUFFIX}" \
  --query "Stacks[0].Outputs[?OutputKey=='PanelUrl'].OutputValue" \
  --output text)
echo "DTMF Panel: $DTMF_PANEL_URL"
curl -s -o /dev/null -w "%{http_code}" "$DTMF_PANEL_URL"
# Expected: 200
```

---

## 8. Phase 7 — Supporting Applications

### 8.1 ARIA Evaluator TS — Cloud Deployment (ECS)

```bash
cd /path/to/awsagentcore/aria-evaluator-ts

# Build Docker image
docker build -t aria-evaluator-ts .

# Get ECR login
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com/aria-evaluator-ts"
aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ECR_REPO"

# Tag and push
docker tag aria-evaluator-ts:latest "${ECR_REPO}:latest"
docker push "${ECR_REPO}:latest"

# Deploy CloudFormation
aws cloudformation deploy \
  --template-file infra/cloudformation/ecs-cloudfront-lowcost.yaml \
  --stack-name aria-evaluator-ts-${STACK_SUFFIX} \
  --region "$AWS_REGION" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    AppName=aria-evaluator-ts \
    AppImageUri="${ECR_REPO}:latest" \
    DesiredCount=1
```

**✓ Verify Phase 7 — Evaluator:**

```bash
EVAL_URL=$(aws cloudformation describe-stacks \
  --stack-name "aria-evaluator-ts-${STACK_SUFFIX}" \
  --query "Stacks[0].Outputs[?contains(OutputKey,'CloudFront')].OutputValue" \
  --output text)
echo "Evaluator: https://$EVAL_URL"
curl -s -o /dev/null -w "%{http_code}" "https://$EVAL_URL"
# Expected: 200
```

### 8.2 Brainstorming Agent — Cloud Deployment

```bash
cd /path/to/awsagentcore/brainstorming-agent

# Set AWS credentials in docker/.env
cp docker/.env.example docker/.env
# Edit docker/.env:
#   AWS_ACCESS_KEY_ID=...
#   AWS_SECRET_ACCESS_KEY=...
#   AWS_DEFAULT_REGION=eu-west-2
#   BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-6

./deploy.sh deploy
```

**✓ Verify Phase 7 — Brainstorming:**

```bash
# URL printed by deploy.sh
# Navigate to URL in browser
# Confirm: workspace loads, new brainstorm session can be started
```

---

## 9. Phase 8 — Knowledgebase Sync

### 9.1 Upload Meridian Knowledgebase to S3

```bash
cd /path/to/awsagentcore

# Set the target bucket (created in Phase 1 or existing)
export KB_S3_BUCKET="meridian-aria-knowledgebase-${STACK_SUFFIX}"

bash scripts/upload_knowledgebase_to_s3.sh
```

This script uploads all documents from `knowledgebase/meridian-bank/` to the configured S3 bucket for Q in Connect.

**✓ Verify:**

```bash
aws s3 ls "s3://${KB_S3_BUCKET}/meridian-bank/" --recursive | wc -l
# Expected: > 0 (number of uploaded documents)
```

### 9.2 Sync Q in Connect Knowledge Base

After uploading documents, trigger a sync in the Amazon Connect console:

1. **Amazon Connect Console** → your instance → **Amazon Q** → **Knowledge bases**
2. Select the Meridian knowledgebase
3. Click **Sync now**
4. Wait for sync status to show **Sync successful**

---

## 10. Phase 9 — End-to-End Smoke Tests

### 10.1 ARIA Banking Agent — Chat

```bash
# Get the endpoint from deploy state
ARIA_ENDPOINT=$(./scripts/deploy.sh status 2>/dev/null | grep -i "chat url\|endpoint" | tail -1 | awk '{print $NF}')

# Test banking query
curl -s -X POST "$ARIA_ENDPOINT" \
  -H "Content-Type: application/json" \
  -d '{"message": "What are your current mortgage rates?"}' \
  | python3 -m json.tool

# Expected: JSON with conversational AI response about Meridian mortgage rates
```

### 10.2 Connect Analytics — Dashboard Query

```bash
# Open the analytics CloudFront URL in browser
# Navigate to chat interface
# Type: "How many agents are currently available?"
# Expected: Response with current queue/agent counts from Amazon Connect
```

### 10.3 DTMF Capture — Integration Test [DTMF]

```bash
# Simulate a DTMF session lifecycle
SESSION=$(aws lambda invoke \
  --function-name aria-dtmf-start-session \
  --payload '{"contactId":"smoke-test-001","purpose":"card_last_four"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/dtmf-smoke.json && cat /tmp/dtmf-smoke.json | python3 -c \
  "import json,sys; print(json.load(sys.stdin).get('sessionId',''))")

# Poll status
aws lambda invoke \
  --function-name aria-dtmf-status-proxy \
  --payload "{\"sessionId\":\"$SESSION\"}" \
  --cli-binary-format raw-in-base64-out \
  /tmp/dtmf-status.json && cat /tmp/dtmf-status.json
# Expected: {"status": "pending", ...}
```

### 10.4 Chat Widget — Browser Test

1. Open the Meridian chat widget URL in Chrome/Edge
2. Click the chat bubble / widget trigger
3. Confirm widget initialises and shows "Connecting..."
4. Confirm connection establishes within 10 seconds
5. Type "Hello" — confirm Amazon Connect routes to ARIA flow

### 10.5 CloudWatch — No Errors

```bash
# Check Lambda errors in last 30 minutes
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=audit_cloudtrail_writer \
  --start-time "$(date -u -v-30M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u --date='30 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 1800 \
  --statistics Sum \
  --query "Datapoints[0].Sum"
# Expected: 0 or null (no errors)
```

### 10.6 Smoke Test Sign-Off Checklist

Record results:

```
[ ] ARIA chat response received
[ ] ARIA voice call connected (if applicable)
[ ] Analytics dashboard loaded and returned data
[ ] DTMF session created and polled successfully
[ ] Meridian chat widget loads and initiates chat
[ ] Nationwide chat widget loads
[ ] Brainstorming agent accessible
[ ] ARIA Evaluator UI accessible
[ ] CloudWatch: 0 Lambda errors in last 30 min
[ ] CloudWatch: 0 AgentCore errors in last 30 min
[ ] Cost baseline check: within expected range
```

---

## 11. Local Docker Deployment

Use local mode for development and pre-cloud validation. No AWS AgentCore resources are created. Lambda tools run with `MOCK_MODE=true`.

### 11.1 ARIA Banking Agent — Local

```bash
cd /path/to/awsagentcore

# Install Python dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set up local environment
./scripts/deploy.sh local
# Prompts for any missing config

# Start the agent (local mode)
./scripts/deploy.sh deploy local
```

### 11.2 Connect Analytics Agent — Local

```bash
cd /path/to/awsagentcore/connect-analytics-agent

./deploy.sh local
# Prompts once for config, saves to .env
# Docker builds: agent + frontend
# Access:
#   Frontend:  http://localhost:5274
#   Agent API: http://localhost:8000
```

**After first run, use `update` to rebuild without re-prompting:**

```bash
./deploy.sh update
```

**Stop local environment:**

```bash
./deploy.sh local-stop
```

### 11.3 Brainstorming Agent — Local

```bash
cd /path/to/awsagentcore/brainstorming-agent

cp docker/.env.example docker/.env
# Edit docker/.env — add AWS credentials and region

docker compose -f docker/docker-compose.yml up --build
# Access:
#   Frontend:  http://localhost:3000
#   Agent API: http://localhost:8000
```

### 11.4 ARIA Evaluator — Local

```bash
cd /path/to/awsagentcore/aria-evaluator-ts

# Install dependencies
npm install

# Set environment
cp .env.example .env 2>/dev/null || true
# Edit .env with your Connect and Bedrock config

# Run locally
npm run dev
# Access: http://localhost:5173

# Or run via Docker
docker compose -f infra/docker/docker-compose.yml up --build
```

### 11.5 Local Verification

```bash
# ARIA agent API health check
curl http://localhost:8000/health
# Expected: {"status": "ok"}

# Analytics dashboard
curl -s -o /dev/null -w "%{http_code}" http://localhost:5274
# Expected: 200

# Brainstorming agent API
curl http://localhost:8000/health
# Expected: {"status": "ok"}
```

---

## 12. Teardown Procedures

> **Warning:** Teardown is irreversible for S3 data, DynamoDB data, and deployed Lambda code (unless backed up). Confirm with the team before running in production.

### 12.1 ARIA Banking Agent — Teardown

```bash
cd /path/to/awsagentcore
./scripts/deploy.sh teardown
```

Removes: AgentCore runtime, ECR images, S3 buckets, DynamoDB, EventBridge, CloudTrail, all Lambdas, IAM roles, CloudFront, Cognito.

### 12.2 Connect Analytics Agent — Teardown

```bash
cd /path/to/awsagentcore/connect-analytics-agent
./deploy.sh teardown
```

### 12.3 DTMF Marketplace — Teardown

```bash
# Delete CloudFormation stack
aws cloudformation delete-stack \
  --stack-name "dtmf-secure-capture-${STACK_SUFFIX}"

# Wait for completion
aws cloudformation wait stack-delete-complete \
  --stack-name "dtmf-secure-capture-${STACK_SUFFIX}"
echo "DTMF stack deleted"

# Delete DTMF Lambdas (if deployed separately)
for fn in aria-dtmf-start-session aria-dtmf-decrypt aria-dtmf-validate aria-dtmf-status-proxy; do
  aws lambda delete-function --function-name "$fn" 2>/dev/null && echo "Deleted: $fn"
done

# Delete RSA private key (schedule for deletion with 7-day window)
aws secretsmanager delete-secret \
  --secret-id aria/dtmf-private-key \
  --recovery-window-in-days 7
```

### 12.4 ARIA Evaluator — Teardown

```bash
aws cloudformation delete-stack \
  --stack-name "aria-evaluator-ts-${STACK_SUFFIX}"
aws cloudformation wait stack-delete-complete \
  --stack-name "aria-evaluator-ts-${STACK_SUFFIX}"
```

### 12.5 Brainstorming Agent — Teardown

```bash
cd /path/to/awsagentcore/brainstorming-agent
./deploy.sh teardown
```

### 12.6 Connect Lambda Scripts — Teardown

```bash
# Remove each Lambda individually
for fn in aria-mcp-gateway aria-routing-lookup aria-callback-scheduler \
          aria-webrtc-api aria-meeting-id-capture aria-session-injector-qconnect; do
  aws lambda delete-function --function-name "$fn" 2>/dev/null && echo "Deleted: $fn"
done

# Remove API Gateways created by deploy scripts
# (retrieve IDs from deploy state or list)
aws apigateway get-rest-apis \
  --query "items[?contains(name,'aria')].[id,name]" \
  --output table
# Then delete each:
# aws apigateway delete-rest-api --rest-api-id <id>
```

### 12.7 Cost Check After Teardown

```bash
./scripts/deploy.sh costs
# All resources removed; spend should drop to near zero within 24 hours
# (CloudFront distributions can take up to 15 min to fully disable)
```

---

## 13. Troubleshooting Guide

### 13.1 AgentCore Runtime Won't Start

| Symptom | Check | Fix |
|---|---|---|
| Status: `FAILED` | CloudWatch → `/aws/bedrock-agentcore/<runtime>` logs | Check IAM role has `bedrock:InvokeModel` |
| Docker build fails | Run `docker build .` locally | Fix Dockerfile; check base image tag |
| ECR push rejected | `aws ecr get-login-password` → pipe to docker | Re-authenticate to ECR |
| Container OOM | ECS task memory limit too low | Increase in `agentcore` config |

```bash
# View AgentCore runtime logs
aws logs tail "/aws/bedrock-agentcore/aria_banking_agent" --follow
```

### 13.2 Lambda Deployment Fails

```bash
# Check Lambda creation errors
aws lambda get-function --function-name <name> 2>&1

# View Lambda logs
aws logs tail "/aws/lambda/<function-name>" --follow --since 10m

# Check IAM role trust policy
aws iam get-role --role-name aria-lambda-audit-role \
  --query "Role.AssumeRolePolicyDocument"
```

### 13.3 CloudFront Returns 403/404

```bash
# Check S3 bucket policy allows CloudFront OAC
aws s3api get-bucket-policy --bucket <bucket-name>

# Trigger a CloudFront cache invalidation
DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='<distribution-comment>'].Id" \
  --output text)
aws cloudfront create-invalidation \
  --distribution-id "$DIST_ID" \
  --paths "/*"
```

### 13.4 Analytics Agent Returns No Data

```bash
# Check Connect instance access
aws connect list-queues --instance-id "$CONNECT_INSTANCE_ID" | head -20

# Verify Lambda environment variables
aws lambda get-function-configuration \
  --function-name "connect-analytics-realtime-metrics-${STACK_SUFFIX}" \
  --query "Environment.Variables"
# CONNECT_INSTANCE_ID must be set correctly

# Test Lambda directly
aws lambda invoke \
  --function-name "connect-analytics-realtime-metrics-${STACK_SUFFIX}" \
  --payload '{"instance_id":"<your-connect-id>"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/test.json
cat /tmp/test.json
```

### 13.5 DTMF Decryption Fails

```bash
# Verify secret exists
aws secretsmanager get-secret-value \
  --secret-id aria/dtmf-private-key \
  --query "SecretString" 2>&1 | head -5
# Must not return AccessDenied

# Verify Connect key ID matches deployed key
aws connect describe-instance \
  --instance-id "$CONNECT_INSTANCE_ID" \
  --query "Instance.InstanceId"
# Then check security keys in console
```

### 13.6 Cognito 403 from React Client

```bash
# Get pool and role from deploy state
python3 -c "
import json
s = json.load(open('scripts/.deploy-state.json'))
print('Pool:', s.get('cognito_identity_pool_id'))
print('Role:', s.get('cognito_unauth_role_arn'))
"

# Verify unauthenticated access enabled
aws cognito-identity describe-identity-pool \
  --identity-pool-id <pool-id> \
  --query "AllowUnauthenticatedIdentities"
# Expected: true
```

### 13.7 Contact Flow Not Routing to ARIA

1. Verify Lex V2 bot is associated with the Connect instance
2. Verify `aria-lex-fulfillment` Lambda ARN is correct in the Lex bot alias
3. Check Lambda permission: `aws lambda get-policy --function-name aria-lex-fulfillment`
4. Check Lex bot alias status: should be `InService`
5. Review Connect contact flow — ensure the Lex V2 block is reached before agent queue

---

## 14. Quick Reference — All Commands

### 14.1 Deploy Commands

```bash
# ARIA Banking Agent (full stack + CloudFront React client)
cd awsagentcore && ./scripts/deploy.sh deploy agentcore

# ARIA local development
cd awsagentcore && ./scripts/deploy.sh deploy local

# Connect Analytics Agent (cloud)
cd awsagentcore/connect-analytics-agent && ./deploy.sh deploy

# Connect Analytics Agent (local Docker)
cd awsagentcore/connect-analytics-agent && ./deploy.sh local

# Brainstorming Agent (Docker)
cd awsagentcore/brainstorming-agent && \
  docker compose -f docker/docker-compose.yml up --build

# Brainstorming Agent (cloud)
cd awsagentcore/brainstorming-agent && ./deploy.sh deploy

# DTMF keys + stack
bash scripts/setup_dtmf_keys.sh
aws cloudformation deploy --template-file marketplace/cloudformation/dtmf-secure-capture.yaml \
  --stack-name dtmf-secure-capture-prod --capabilities CAPABILITY_NAMED_IAM
bash scripts/deploy_dtmf_lambda.sh

# Connect Lambda platform scripts
bash scripts/deploy_mcp_gateway.sh
bash scripts/deploy_routing_lambda.sh
bash scripts/deploy_callback_lambda.sh
bash scripts/deploy_webrtc_api.sh
bash scripts/deploy_meeting_id_lambda.sh
bash scripts/deploy_session_injector_qconnect.sh

# Chat widgets
bash scripts/deploy_connect_widget.sh
bash scripts/deploy_nationwide_chat_widget.sh

# Knowledgebase
bash scripts/upload_knowledgebase_to_s3.sh
```

### 14.2 Status Commands

```bash
# ARIA stack status
./scripts/deploy.sh status

# ARIA costs
./scripts/deploy.sh costs

# Analytics agent status (shows state file)
cat connect-analytics-agent/.deploy-state.json | python3 -m json.tool

# DTMF stack status
aws cloudformation describe-stacks \
  --stack-name dtmf-secure-capture-prod \
  --query "Stacks[0].StackStatus"
```

### 14.3 Teardown Commands

```bash
# ARIA full teardown
./scripts/deploy.sh teardown

# Analytics agent teardown
cd connect-analytics-agent && ./deploy.sh teardown

# DTMF stack teardown
aws cloudformation delete-stack --stack-name dtmf-secure-capture-prod

# Evaluator ECS teardown
aws cloudformation delete-stack --stack-name aria-evaluator-ts-prod

# Brainstorming agent teardown
cd brainstorming-agent && ./deploy.sh teardown
```

### 14.4 Quick Health Checks

```bash
# All Lambda states (quick grep)
aws lambda list-functions \
  --query "Functions[?contains(FunctionName,'aria') || contains(FunctionName,'connect-analytics')].[FunctionName,State]" \
  --output table

# All CloudFront distributions
aws cloudfront list-distributions \
  --query "DistributionList.Items[*].[Comment,DomainName,Status]" \
  --output table

# AgentCore runtimes
aws bedrock-agentcore list-agent-runtimes \
  --region eu-west-2 \
  --query "agentRuntimes[*].[agentRuntimeName,status]" \
  --output table 2>/dev/null || echo "AgentCore CLI not configured"

# Recent Lambda errors (last hour)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --start-time "$(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || \
                  date -u --date='1 hour ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 3600 \
  --statistics Sum \
  --query "Datapoints[0].Sum" \
  --output text
```

---

*This runbook is maintained alongside the codebase. For issues or corrections, submit a pull request to `docs/deployment-runbook.md`.*  
*Companion document: [deployment-playbook.md](deployment-playbook.md)*
