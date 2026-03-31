# Path E: Amazon Connect + Lex V2 (Nova Sonic) + Managed Bedrock Agent + Lambda Action Groups
## ARIA Banking Agent — Optimal PSTN Voice Architecture

> **Official references:**
> - [AMAZON.BedrockAgentIntent – Amazon Lex V2](https://docs.aws.amazon.com/lexv2/latest/dg/built-in-intent-bedrockagent.html)
> - [Using BedrockAgentIntent in Lex V2](https://docs.aws.amazon.com/lexv2/latest/dg/bedrock-agent-intent.html)
> - [Configure Amazon Nova Sonic S2S – Amazon Connect](https://docs.aws.amazon.com/connect/latest/adminguide/nova-sonic-speech-to-speech.html)
> - [Amazon Bedrock Agents – Creating Agents](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
> - [Amazon Bedrock Agents – Action Groups](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-action-create.html)
> - [Permissions for AMAZON.BedrockAgentIntent](https://docs.aws.amazon.com/lexv2/latest/dg/bedrock-agent-intent-permissions.html)
> - [AWS Sample: Connect + Bedrock Agent Voice Integration](https://github.com/aws-samples/sample-amazon-connect-bedrock-agent-voice-integration)

---

## Why Path E Exists — The Design Rationale

### What Was Wrong with Path A (Lambda Bridge)

Path A (documented separately) routes every customer utterance through a **dumb Lambda bridge** that does nothing except proxy text to AgentCore HTTP:

```
Connect → Lex V2 (Nova Sonic) → FallbackIntent → Lambda (proxy) → AgentCore HTTP
                                                      ^^^^
                                          No reasoning. Forwards text. Returns text.
                                          One tool call per Lambda invocation max.
```

The Lambda bridge is stateless and single-shot: it sends one text message to ARIA, gets one text response back, and returns it to Lex. If ARIA internally needs to call three tools (authenticate → get customer → get balance) before responding, the Lambda waits for the entire chain — potentially hitting the 8-second Lex sync timeout on complex multi-tool turns.

### What Path E Does Differently

Path E replaces the dumb Lambda bridge with a **managed Amazon Bedrock Agent** wired directly to Lex V2 via the built-in `AMAZON.BedrockAgentIntent`:

```
Connect → Lex V2 (Nova Sonic S2S) → AMAZON.BedrockAgentIntent → Managed Bedrock Agent
                                                                        │
                                              ┌─────────────────────────┤
                                              │                         │
                                     Reasoning: Claude             Tool execution:
                                     Multi-turn dialogue            Lambda Action Groups
                                     Full ARIA system prompt        (7 banking functions)
                                     Manages its own session
```

**The Bedrock Agent does the reasoning.** Lex V2 is purely the voice pipe. The banking tools are Lambda functions (same code, different invocation path).

---

## Architecture Overview

### Full Call Flow

```
Customer dials +44 xxx xxx xxxx (Meridian Bank)
    │
    ▼
Amazon Connect (eu-west-2)
    │  PSTN audio
    ▼
Inbound Contact Flow: ARIA-PathE-Banking-Flow
    │
    ├─ [Block 1] Set Voice: Amy (en-GB), Speaking Style: Generative  ← Nova Sonic
    ├─ [Block 2] Set Recording & Analytics (Contact Lens: Real-time)
    ├─ [Block 3] Set Contact Attributes: channel=voice, ContactId
    │
    ▼
[Block 4] Get Customer Input → ARIA-PathE-Bot (Lex V2, en-GB)
    │  Customer speaks
    ▼
Nova Sonic S2S (speech → text → Bedrock Agent → text → speech)
    │  Every utterance routed to AMAZON.BedrockAgentIntent
    ▼
AMAZON.BedrockAgentIntent → Managed Bedrock Agent: aria-banking-agent
    │  Lex delegates entire conversation to the Agent
    │  Session persists inside the Bedrock Agent until Agent marks FINISH
    ▼
Bedrock Agent: aria-banking-agent
    │  Claude Sonnet 4.6 reasoning
    │  ARIA system prompt (banking persona)
    │  Multi-turn: can call N tools before responding
    │
    ├──▶ Action Group: auth-tools     → Lambda: aria-banking-auth
    ├──▶ Action Group: account-tools  → Lambda: aria-banking-account
    ├──▶ Action Group: customer-tools → Lambda: aria-banking-customer
    ├──▶ Action Group: debit-card     → Lambda: aria-banking-debit-card
    ├──▶ Action Group: credit-card    → Lambda: aria-banking-credit-card
    ├──▶ Action Group: mortgage-tools → Lambda: aria-banking-mortgage
    └──▶ Action Group: escalation     → Lambda: aria-banking-escalation
    │
    ▼
Agent response text → Lex BedrockAgentIntent response
    │
    ▼
Nova Sonic speaks response to customer
    │
    ▼ (if escalation Lambda returns escalation_requested: true)
Contact Flow checks contact attributes
    │
    ▼
Transfer to Queue: CustomerServiceQueue → Human agent CCP
```

### What Is NOT Changed

```
Existing ARIA AgentCore Runtime (unchanged):
    Browser voice  → WebSocket → AgentCore → Nova Sonic (direct S2S)
    Browser chat   → HTTP POST → AgentCore → Claude Sonnet 4.6
    ↑ Continues working exactly as before. Path E is a parallel PSTN path.
```

---

## Key Concepts — Managed Agent vs Inline Agent vs AgentCore MCP Gateway

This is critical to understand before implementation.

### Amazon Bedrock Agent Types

| | **Managed Bedrock Agent** | **Inline Agent (SDK)** | **AgentCore Runtime** |
|---|---|---|---|
| What it is | Console-created, has Agent ID + Alias | Ephemeral, programmatic | Custom container (your ARIA/Strands code) |
| Referenced by `AMAZON.BedrockAgentIntent` | ✅ Yes (Agent ID + Alias ID) | ❌ No | ❌ No |
| Tool source | Lambda Action Groups | `mcp_clients=[]` in code | `@tool` Python functions |
| MCP Gateway supported natively | ❌ No | ✅ Yes (Inline Agent SDK) | ✅ Yes (via AgentCore Gateway) |
| Production ready for Connect PSTN | ✅ Yes | ❌ Not designed for this | Via Lambda bridge (Path A) |
| Session management | Agent-native | Caller manages | AgentCore session headers |

### Why Not MCP Gateway for Path E?

A common question: since the Lambda tools in Path E are the same Lambdas used in Option D's MCP Gateway, why not connect Path E to the MCP Gateway directly?

**Answer**: `AMAZON.BedrockAgentIntent` only works with a **managed Bedrock Agent**. Managed agents use **Lambda Action Groups** — not MCP. The `mcp_clients` syntax in the AWS MCP blog is exclusively for the **Inline Agent SDK** and cannot be wired to a Lex V2 intent.

```
# This ONLY works for Inline Agent SDK (not for AMAZON.BedrockAgentIntent):
ActionGroup(name="banking", mcp_clients=[mcp_client])  ← Inline only

# For AMAZON.BedrockAgentIntent you must use:
# Managed Agent → Lambda Action Groups (this guide)
```

Wiring MCP Gateway through Path E would require a Lambda action group that calls the MCP Gateway, which calls another Lambda — adding a redundant hop with no benefit.

**Rule of thumb:**
- **Path E** (Lex V2 + BedrockAgentIntent) → Lambda Action Groups directly ✅
- **Option D** (Connect Agentic Self-Service) → AgentCore MCP Gateway ✅
- Do not mix them — each is optimised for its own invocation path.

### Path Comparison at a Glance

| | **Path A** | **Path E (this guide)** | **Option D** |
|---|---|---|---|
| Voice (Nova Sonic) | ✅ Lex V2 S2S | ✅ Lex V2 S2S | ✅ Connect native |
| Reasoning engine | Lambda proxy → AgentCore | ✅ Managed Bedrock Agent | Connect built-in AI |
| Multi-tool per turn | ❌ One turn = one proxy | ✅ Agent calls N tools | ✅ MCP multi-tool |
| Lambda bridge needed | Yes | **No** | No |
| Lex V2 required | Yes | Yes | No |
| Tools | ARIA Strands (in container) | Lambda Action Groups | MCP Gateway → Lambda |
| Uses existing ARIA code | Yes (unchanged) | No (replicated) | No (replicated) |
| MCP Gateway | No | No | Yes |
| Best for | Preserve full ARIA code | Best voice+reason balance | Simpler Connect-native |

**Path E is the recommended path if you want native Bedrock Agent reasoning on PSTN voice without the Lambda proxy bottleneck.**

---

## Prerequisites

| Item | Requirement |
|---|---|
| AWS Account | `395402194296` |
| Region | `eu-west-2` (London) throughout unless stated |
| Amazon Connect instance | Created in eu-west-2 (from Path A guide or Option D guide) |
| IAM | Admin or permissions: `bedrock:*`, `lambda:*`, `lex:*`, `iam:*` |
| AWS CLI | Configured for `eu-west-2` |
| Lambda banking tools | Deployed (from Option D guide — `scripts/lambdas/mcp_tools/`) |
| Phone number | Claimed in Connect (from prior guide) |

> **If you have already followed the Option D guide**, the 7 Lambda functions (`aria-banking-auth`, `aria-banking-account`, etc.) are already deployed. **Skip Part 1 — go directly to Part 2.**

---

## Part 1 — Deploy Lambda Action Group Functions

The same 7 Lambda functions used in Option D serve as the action groups here.
If they are already deployed, skip this part.

### 1.1 — Verify Lambda Functions Exist

```bash
for fn in auth account customer debit-card credit-card mortgage escalation; do
  echo -n "aria-banking-$fn: "
  aws lambda get-function \
    --function-name aria-banking-$fn \
    --region eu-west-2 \
    --query 'Configuration.FunctionName' \
    --output text 2>/dev/null || echo "NOT FOUND"
done
```

If any are missing, deploy them from `scripts/lambdas/mcp_tools/`:

```bash
cd /path/to/awsagentcore/scripts/lambdas/mcp_tools

for handler in auth account customer debit_card credit_card mortgage escalation; do
  fn_name="aria-banking-${handler//_/-}"
  handler_file="aria_${handler}_handler.py"
  zip "${handler}.zip" "${handler_file}"

  aws lambda create-function \
    --function-name "$fn_name" \
    --runtime python3.12 \
    --role arn:aws:iam::395402194296:role/aria-banking-tools-lambda-role \
    --handler "aria_${handler}_handler.lambda_handler" \
    --zip-file "fileb://${handler}.zip" \
    --timeout 25 \
    --region eu-west-2
done
```

### 1.2 — Bedrock Agent Lambda Invocation Permission

For each Lambda, Bedrock Agent needs permission to invoke it.
Add a resource-based policy to each function:

```bash
for fn in auth account customer debit-card credit-card mortgage escalation; do
  aws lambda add-permission \
    --function-name "aria-banking-$fn" \
    --statement-id "AllowBedrockAgentInvoke" \
    --action "lambda:InvokeFunction" \
    --principal "bedrock.amazonaws.com" \
    --source-account "395402194296" \
    --region eu-west-2
done
```

> **Note:** `--source-arn` can also be specified once you have the Bedrock Agent ARN (after Part 2). The above is permissive for initial setup; tighten post-deployment.

---

## Part 2 — Create the Bedrock Agent IAM Role

The managed Bedrock Agent needs an IAM execution role to call Claude and invoke Lambda.

```bash
# 1. Create the role
aws iam create-role \
  --role-name aria-bedrock-agent-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "bedrock.amazonaws.com"},
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "395402194296"
        }
      }
    }]
  }'

# 2. Attach Bedrock model invocation permission
aws iam put-role-policy \
  --role-name aria-bedrock-agent-role \
  --policy-name aria-bedrock-model-access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:eu-west-2::foundation-model/anthropic.claude-sonnet-4-5-v1:0",
        "arn:aws:bedrock:eu-west-2::foundation-model/us.anthropic.claude-sonnet-4-5-20241022-v2:0"
      ]
    }]
  }'

# 3. Attach Lambda invoke permission for all banking tools
aws iam put-role-policy \
  --role-name aria-bedrock-agent-role \
  --policy-name aria-lambda-action-groups \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "arn:aws:lambda:eu-west-2:395402194296:function:aria-banking-*"
    }]
  }'
```

---

## Part 3 — Create the Managed Bedrock Agent

### 3.1 — Create the Agent via CLI

```bash
AGENT_ROLE_ARN=$(aws iam get-role \
  --role-name aria-bedrock-agent-role \
  --query 'Role.Arn' --output text)

AGENT_ID=$(aws bedrock-agent create-agent \
  --agent-name aria-banking-agent \
  --description "ARIA Banking Agent - Meridian Bank virtual assistant for PSTN voice via Amazon Connect" \
  --foundation-model "anthropic.claude-sonnet-4-5-v1:0" \
  --agent-resource-role-arn "$AGENT_ROLE_ARN" \
  --idle-session-ttl-in-seconds 900 \
  --instruction "$(cat << 'PROMPT'
You are ARIA (Automated Retail Intelligence Assistant), the intelligent virtual banking assistant for Meridian Bank. You serve customers over the telephone. Be concise — this is a voice call, not text chat. Keep sentences short. Avoid bullet points or markdown in your responses.

## Identity & Persona
- Name: ARIA
- Bank: Meridian Bank
- Channel: Telephone (voice call via Amazon Connect)
- Language: British English
- Tone: Professional, warm, empathetic, reassuring

## Authentication — MANDATORY FIRST STEP
Every session MUST begin with identity verification before accessing any account data.

Steps:
1. Call initiate_auth to start the session
2. Ask: "Could I take your Customer ID please?"
3. Call validate_customer with the provided ID
4. Ask: "And your date of birth in day, month, year format please?"
5. Ask: "The last four digits of your registered mobile number?"
6. Call cross_validate with customer_id, date_of_birth, last_four_mobile
7. If verified: "Thank you, I've confirmed your identity. Welcome, [first name]. How can I help you today?"
8. If not verified after 3 attempts: escalate to ID&V specialist queue

NEVER access account data before cross_validate confirms identity.

## Your Capabilities
Once authenticated, you can help with:
- Account balances and details (call get_account_details)
- Recent transactions (call get_account_details with transactions=true)
- Account statements (call get_statement)
- Debit card queries, block lost/stolen debit card, request replacement (call get_debit_card_details, block_debit_card, request_debit_card_replacement)
- Credit card balance, limit, block lost/stolen credit card, request replacement (call get_credit_card_details, block_credit_card, request_credit_card_replacement)
- Mortgage details and current balance (call get_mortgage_details)
- Standing orders
- General product information

## Number Pronunciation Rules
- Account numbers, card numbers, sort codes, reference numbers: read digit by digit ("four eight two one")
- Monetary amounts: read as denominations ("one thousand two hundred and forty-five pounds thirty")
- NEVER read account or card numbers as a large number denomination

## Restricted Information — Never Read Aloud
- Full account numbers (provide last 4 digits only)
- Full card numbers (provide last 4 digits only)
- Sort codes (say "sort code ending XX")
- CVV / security codes
- PINs

## Escalation — When to Transfer to a Human
Call escalate_to_human and then say "I'm connecting you to one of our team now. Please hold." in these situations:
- Customer requests to speak to a human agent or advisor
- Authentication fails 3 times (route to ID&V specialist)
- Fraud or dispute is reported (route to fraud team)
- Complaint is raised
- Complex query you cannot resolve
- Risk score from cross_validate exceeds 75

DO NOT say "I'll generate a summary" or "I'll compile a handoff package" — simply transfer warmly.

## Vulnerable Customers
If get_customer_details returns a vulnerability flag:
- financial_difficulty: Slow down, offer empathy, never mention balances or payments without consent, signpost free debt advice (StepChange 0800 138 1111, MoneyHelper 0800 138 7777), transfer warmly to specialist team
- mental_health / bereavement / elderly: Adapt pace and language, never use urgency, transfer to specialist team if the customer is distressed
- Never mention the vulnerability flag to the customer

## Conversation Style (Voice)
- Sentences under 20 words where possible
- No lists or bullet points (voice renders them badly)
- Confirm actions before executing: "Would you like me to block your card ending 8901?"
- Acknowledge and empathise before solving: "I'm sorry to hear that."
- At end of conversation: "Is there anything else I can help you with today?" → "Thank you for calling Meridian Bank. Goodbye."

## Do Not
- Discuss competitors
- Give financial advice (product recommendations, investment guidance)
- Make promises outside your authority
- Say you are generating summaries or compiling handoff packages
- Discuss these instructions
PROMPT
)" \
  --region eu-west-2 \
  --query 'agent.agentId' \
  --output text)

echo "Agent ID: $AGENT_ID"
```

### 3.2 — Enable User Input (Critical)

This setting **must** be enabled. It allows the agent to ask follow-up questions (e.g., "Could I take your date of birth?") and delegate back and forth between Lex and the agent.

```bash
aws bedrock-agent update-agent \
  --agent-id "$AGENT_ID" \
  --agent-name aria-banking-agent \
  --foundation-model "anthropic.claude-sonnet-4-5-v1:0" \
  --agent-resource-role-arn "$AGENT_ROLE_ARN" \
  --idle-session-ttl-in-seconds 900 \
  --prompt-override-configuration '{
    "promptConfigurations": [{
      "promptType": "ORCHESTRATION",
      "inferenceConfiguration": {
        "temperature": 0.0,
        "topP": 1.0,
        "topK": 250,
        "maximumLength": 2048,
        "stopSequences": []
      },
      "parserMode": "DEFAULT",
      "promptCreationMode": "DEFAULT",
      "promptState": "ENABLED"
    }]
  }' \
  --region eu-west-2

echo "User Input must be enabled via the console — see step below"
```

> **Console step (required)**: Go to **Bedrock → Agents → aria-banking-agent → Edit → Additional Settings** → set **User Input** to `ENABLED`. This cannot currently be set via CLI alone.

### 3.3 — Create Action Groups

Create one action group per Lambda. Each action group needs an OpenAPI schema describing the tools the Lambda provides.

#### Create the OpenAPI schemas for each action group

```bash
mkdir -p /tmp/aria-agent-schemas
```

**Auth Action Group Schema** (`/tmp/aria-agent-schemas/auth.json`):

```json
{
  "openapi": "3.0.0",
  "info": {"title": "ARIA Auth Tools", "version": "1.0"},
  "paths": {
    "/initiate_auth": {
      "post": {
        "operationId": "initiate_auth",
        "summary": "Initiate a new authentication session",
        "responses": {"200": {"description": "Session initiated"}}
      }
    },
    "/validate_customer": {
      "post": {
        "operationId": "validate_customer",
        "summary": "Validate that a customer ID exists in the system",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["customer_id"],
                "properties": {
                  "customer_id": {"type": "string", "description": "The customer ID provided by the caller"}
                }
              }
            }
          }
        },
        "responses": {"200": {"description": "Validation result"}}
      }
    },
    "/cross_validate": {
      "post": {
        "operationId": "cross_validate",
        "summary": "Cross-validate customer identity using customer ID, date of birth, and last 4 mobile digits",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["customer_id", "date_of_birth", "last_four_mobile"],
                "properties": {
                  "customer_id": {"type": "string"},
                  "date_of_birth": {"type": "string", "description": "DD/MM/YYYY"},
                  "last_four_mobile": {"type": "string", "description": "Last 4 digits of registered mobile"}
                }
              }
            }
          }
        },
        "responses": {"200": {"description": "Cross-validation result with verified flag and risk_score"}}
      }
    }
  }
}
```

#### Create the action groups via CLI

```bash
# Helper: upload schema to S3 (Bedrock Agent requires schemas in S3)
SCHEMA_BUCKET="aria-agent-schemas-395402194296"
aws s3 mb "s3://$SCHEMA_BUCKET" --region eu-west-2 2>/dev/null || true

# Upload each schema
for schema in auth account customer debit_card credit_card mortgage escalation; do
  aws s3 cp "/tmp/aria-agent-schemas/${schema}.json" \
    "s3://$SCHEMA_BUCKET/schemas/${schema}.json" \
    --region eu-west-2
done

# Create auth action group
aws bedrock-agent create-agent-action-group \
  --agent-id "$AGENT_ID" \
  --agent-version DRAFT \
  --action-group-name auth-tools \
  --description "Customer authentication and identity verification" \
  --action-group-executor '{
    "lambda": "arn:aws:lambda:eu-west-2:395402194296:function:aria-banking-auth"
  }' \
  --api-schema '{
    "s3": {
      "s3BucketName": "'"$SCHEMA_BUCKET"'",
      "s3ObjectKey": "schemas/auth.json"
    }
  }' \
  --action-group-state ENABLED \
  --region eu-west-2
```

Repeat for each action group (`account-tools`, `customer-tools`, `debit-card-tools`, `credit-card-tools`, `mortgage-tools`, `escalation-tools`), changing `--action-group-name`, `--description`, `--lambda ARN`, and `--s3ObjectKey` accordingly.

> **Console alternative**: Bedrock Agent console provides a schema editor UI under **Agents → aria-banking-agent → Action groups → Add**. Paste each JSON schema directly.

### 3.4 — Prepare and Create Agent Alias

```bash
# Prepare the agent (builds the working draft)
aws bedrock-agent prepare-agent \
  --agent-id "$AGENT_ID" \
  --region eu-west-2

# Wait for preparation to complete (~30 seconds)
sleep 30

# Create an alias pointing to the prepared DRAFT version
ALIAS_ID=$(aws bedrock-agent create-agent-alias \
  --agent-id "$AGENT_ID" \
  --agent-alias-name production \
  --description "Production alias for ARIA banking agent (Path E)" \
  --region eu-west-2 \
  --query 'agentAlias.agentAliasId' \
  --output text)

echo "Agent ID:  $AGENT_ID"
echo "Alias ID:  $ALIAS_ID"
```

Save both values — you need them in Part 4.

---

## Part 4 — Configure Lex V2 Bot with AMAZON.BedrockAgentIntent

### 4.1 — Create or Reuse the Lex V2 Bot

If you already have `ARIA-Connect-Bot` from the Path A guide, you can add the `AMAZON.BedrockAgentIntent` to it. Otherwise, create a new bot:

```bash
# Create bot
BOT_ID=$(aws lexv2-models create-bot \
  --bot-name ARIA-PathE-Bot \
  --description "ARIA Lex bot for Path E — delegates to Managed Bedrock Agent" \
  --role-arn "arn:aws:iam::395402194296:role/aria-lex-bot-role" \
  --data-privacy '{"childDirected": false}' \
  --idle-session-ttl-in-seconds 900 \
  --region eu-west-2 \
  --query 'botId' \
  --output text)

echo "Bot ID: $BOT_ID"
```

> The Lex bot role (`aria-lex-bot-role`) must be created if it doesn't exist — see Step 4.2.

### 4.2 — Create the Lex Bot IAM Role

```bash
# Create role with Lex trust
aws iam create-role \
  --role-name aria-lex-bot-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lexv2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach Bedrock InvokeAgent permission
aws iam put-role-policy \
  --role-name aria-lex-bot-role \
  --policy-name aria-lex-bedrock-agent \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": "bedrock:InvokeAgent",
        "Resource": "arn:aws:bedrock:eu-west-2:395402194296:agent-alias/'"$AGENT_ID"'/'"$ALIAS_ID"'"
      },
      {
        "Effect": "Allow",
        "Action": [
          "bedrock:ListFoundationModels",
          "bedrock:ListInferenceProfiles"
        ],
        "Resource": "*"
      }
    ]
  }'
```

> **Console note**: If you create the bot via the Lex console with a **service-linked role**, AWS auto-generates the required `bedrock:InvokeAgent` policy when you add the `AMAZON.BedrockAgentIntent` through the Generative AI configuration screen.

### 4.3 — Create the Bot Locale (en-GB)

```bash
aws lexv2-models create-bot-locale \
  --bot-id "$BOT_ID" \
  --bot-version DRAFT \
  --locale-id en_GB \
  --description "British English locale for ARIA banking voice" \
  --nlu-intent-confidence-threshold 0.40 \
  --voice-settings '{
    "voiceId": "Amy",
    "engine": "generative"
  }' \
  --region eu-west-2
```

> Setting `"engine": "generative"` on the voice enables **Nova Sonic S2S** for this locale.

### 4.4 — Enable Generative AI and Add AMAZON.BedrockAgentIntent

> **This step must be done via the Lex V2 console** — the BedrockAgentIntent cannot be added via CLI alone.

1. Open [https://console.aws.amazon.com/lexv2/home](https://console.aws.amazon.com/lexv2/home)
2. Select your bot (`ARIA-PathE-Bot`)
3. In the left nav, go to **All languages → English (GB)**
4. Click **Generative AI** in the left nav
5. Toggle **Enable generative AI features** to **On**
6. Click **Save**
7. Now go to **Intents** (left nav)
8. Click **Add intent** → **Use built-in intent**
9. Select **AMAZON.BedrockAgentIntent**
10. Configure:
    - **Amazon Bedrock Agent Id**: paste your `$AGENT_ID`
    - **Amazon Bedrock Agent Alias Id**: paste your `$ALIAS_ID`
    - **Override FallbackIntent**: ✅ Check this — routes all unclassified utterances to the Agent
11. Click **Add**

> **Critical**: Ensure **User Input** is `ENABLED` on the Bedrock Agent (set in Part 3.2 console step). Without this, the agent cannot ask clarifying or follow-up questions and the multi-turn authentication flow breaks.

### 4.5 — Enable Nova Sonic S2S on the Locale

If Nova Sonic S2S is not already enabled via the voice settings above:

1. In the Lex console, go to **English (GB) → Configuration**
2. Under **Speech model**, select **Speech-to-Speech**
3. Choose **Amazon Nova Sonic**
4. Voice: **Amy** (en-GB, Feminine, Generative)
5. Click **Save**

### 4.6 — Build the Bot Locale

```bash
aws lexv2-models build-bot-locale \
  --bot-id "$BOT_ID" \
  --bot-version DRAFT \
  --locale-id en_GB \
  --region eu-west-2

# Poll until build is complete
echo "Waiting for bot locale build..."
while true; do
  STATUS=$(aws lexv2-models describe-bot-locale \
    --bot-id "$BOT_ID" \
    --bot-version DRAFT \
    --locale-id en_GB \
    --region eu-west-2 \
    --query 'botLocaleStatus' \
    --output text)
  echo "Status: $STATUS"
  [ "$STATUS" = "Built" ] && break
  [ "$STATUS" = "Failed" ] && echo "Build failed!" && exit 1
  sleep 10
done
echo "Bot built."
```

### 4.7 — Create Bot Version and Alias

```bash
# Create a numbered version
BOT_VERSION=$(aws lexv2-models create-bot-version \
  --bot-id "$BOT_ID" \
  --bot-version-locale-specification '{"en_GB": {"sourceBotVersion": "DRAFT"}}' \
  --region eu-west-2 \
  --query 'botVersion' \
  --output text)

sleep 20

# Create an alias pointing to that version
BOT_ALIAS_ID=$(aws lexv2-models create-bot-alias \
  --bot-id "$BOT_ID" \
  --bot-alias-name production \
  --bot-version "$BOT_VERSION" \
  --region eu-west-2 \
  --query 'botAliasId' \
  --output text)

echo "Bot ID:       $BOT_ID"
echo "Bot Alias ID: $BOT_ALIAS_ID"
echo "Bot Version:  $BOT_VERSION"
```

---

## Part 5 — Register the Bot with Amazon Connect

### 5.1 — Add the Lex Bot to Your Connect Instance

```bash
CONNECT_INSTANCE_ID="<your-connect-instance-id>"  # From prior setup

aws connect associate-lex-bot \
  --instance-id "$CONNECT_INSTANCE_ID" \
  --lex-bot '{
    "Name": "ARIA-PathE-Bot",
    "LexRegion": "eu-west-2"
  }' \
  --region eu-west-2
```

Or via console:
1. Amazon Connect admin console → **Channels → Amazon Lex**
2. Click **Add Amazon Lex Bot**
3. Select `ARIA-PathE-Bot`, Region `eu-west-2`
4. Click **Save**

### 5.2 — (Optional) Add the Bot to Connect's Conversational AI Bot Interface

For Nova Sonic S2S to be configured:

1. In the Connect admin console, navigate to **AI → Conversational AI bots**
2. Select `ARIA-PathE-Bot`
3. Select alias **production**
4. Under **en-GB locale**, verify **Speech model: Speech-to-Speech (Amazon Nova Sonic)**
5. Click **Build locale** if not already built

---

## Part 6 — Create the Contact Flow

### 6.1 — Create a New Inbound Contact Flow

1. In the Connect admin console, go to **Routing → Contact flows**
2. Click **Create contact flow** → **Inbound flow**
3. Name: `ARIA-PathE-Banking-Flow`

### 6.2 — Build the Flow (7 Blocks)

#### Block 1: Set Voice
- Type: **Set voice**
- Voice provider: Amazon
- Language: English (en-GB)
- Voice: **Amy**
- Speaking style: **Generative** ← **Required for Nova Sonic S2S**

#### Block 2: Set Recording and Analytics
- Type: **Set recording and analytics behavior**
- **Contact Lens real-time analytics: Enabled** ← Required for AI features
- Call recording: Enabled (S3 bucket, KMS encrypted)

#### Block 3: Set Contact Attributes
- Type: **Set contact attributes**
- Add attribute: `channel` = `voice`
- Add attribute: `contactId` = `$.ContactId`

#### Block 4: Get Customer Input (Core Block)
- Type: **Get customer input**
- Select **Amazon Lex**
- Bot: `ARIA-PathE-Bot`
- Alias: `production`
- Language: `en-GB`
- Session attributes:
  - `contactId` → `$.ContactId`
  - `channel` → `voice`
- **Intent**: `AMAZON.BedrockAgentIntent` (or FallbackIntent if BedrockAgentIntent overrides it)
- Timeout: 30 seconds
- Maximum retries: 3

Branches from this block:
- **Any intent / Fulfilled** → Loop back to Block 4 (agent continues conversation)
- **Timeout / Error** → Block 5 (error handling)
- On session attribute `escalation_requested` = `true` → Block 6 (escalation)

> **How the loop works**: The Bedrock Agent manages the conversation internally. Lex returns to the flow after each Agent response. The flow checks whether to loop (continue conversation) or escalate. The Agent signals it is done by marking the session `FINISH`.

#### Block 5: Error Handling
- Type: **Play prompt**
- Text-to-Speech: "I'm sorry, I'm having difficulty right now. Please try again or call back shortly."
- Connect to: **Disconnect** block

#### Block 6: Check for Escalation
- Type: **Check contact attributes**
- Attribute: `$.Attributes.escalation_requested`
- Condition: `= true`
  - **True** → Block 7 (transfer to queue)
  - **No match** → Loop back to Block 4

#### Block 7: Transfer to Human Agent Queue
- Type: **Transfer to queue**
- Queue: `CustomerServiceQueue` (or `IdVSpecialistQueue` based on `escalation_type` attribute)
- Set a whisper flow to brief the agent: "Incoming ARIA transfer — [customer name, auth status, last topic]"

### 6.3 — Save and Publish

1. Click **Save**
2. Click **Publish**

---

## Part 7 — Assign the Phone Number

1. In Connect admin console → **Channels → Phone numbers**
2. Select the phone number (e.g., +44 xxx xxx xxxx)
3. Under **Contact flow / IVR**: select `ARIA-PathE-Banking-Flow`
4. Click **Save**

---

## Part 8 — Test and Validate

### 8.1 — Test via Connect Test Console

1. Connect admin → **Test chat/voice simulator**
2. Select `ARIA-PathE-Banking-Flow`
3. Start a simulated voice call

**Happy path test:**
```
ARIA: "Thank you for calling Meridian Bank. I'm ARIA, your virtual assistant. 
       Could I take your Customer ID please?"
You:  "CUST-001"
ARIA: "Thank you. And your date of birth in day, month, year format?"
You:  "ninth of September nineteen eighty two"   [or "09/09/1982"]
ARIA: "And the last four digits of your registered mobile number?"
You:  "nine two five two"
ARIA: "Thank you. I've confirmed your identity. Welcome, James. 
       How can I help you today?"
You:  "What's my account balance?"
ARIA: "Your current account balance is [amount]."
```

### 8.2 — Verify Bedrock Agent Tool Invocations

```bash
# Watch Lambda logs in real-time during a test call
aws logs tail /aws/lambda/aria-banking-auth \
  --follow --region eu-west-2 &

aws logs tail /aws/lambda/aria-banking-account \
  --follow --region eu-west-2
```

Expected: you should see `toolName` and successful invocations in the logs during each test call.

### 8.3 — Test Multi-Tool Turn

Ask: "What's my balance and can you also tell me about my debit card?"

Expected: the Bedrock Agent calls `get_account_details` AND `get_debit_card_details` in the same turn before speaking a single combined response — this is the key advantage over Path A.

### 8.4 — Test Lost Card

```
You:  "I've lost my debit card"
ARIA: "I'm sorry to hear that. Let me look up your card details."
      [Agent calls get_debit_card_details]
ARIA: "I can see a debit card ending in eight nine zero one on your account.
       Would you like me to block this card now?"
You:  "Yes please"
ARIA: "Done. Your card ending eight nine zero one has been blocked.
       A replacement will be dispatched and should arrive within three to five working days."
```

### 8.5 — Test Escalation

```
You:  "I'd like to speak to someone"
ARIA: "Of course. I'm connecting you to one of our team now. Please hold."
      [Agent calls escalate_to_human; escalation_requested=true set in session]
      [Contact Flow detects attribute; transfers to CustomerServiceQueue]
```

### 8.6 — Test Authentication Failure

Say a wrong date of birth three times. Expected: ARIA escalates to the ID&V specialist queue, not the general queue.

---

## Part 9 — Monitoring and Troubleshooting

### 9.1 — CloudWatch Metrics to Monitor

| Metric | Where | Alert Threshold |
|---|---|---|
| Lambda duration | `/aws/lambda/aria-banking-*` | > 20 s |
| Lambda errors | `/aws/lambda/aria-banking-*` | Any error |
| Bedrock Agent invocations | CloudWatch → `AWS/Bedrock` namespace | — |
| Bedrock Agent latency | CloudWatch → `InvokeAgent` duration | > 5 s average |
| Lex session failures | CloudWatch → Lex V2 metrics | > 5% |
| Connect escalation rate | Connect Analytics | > 30% (investigate prompt) |
| Connect self-service rate | Connect Analytics | < 60% (investigate) |

### 9.2 — Enable Bedrock Agent Logging

```bash
aws bedrock-agent update-agent \
  --agent-id "$AGENT_ID" \
  --agent-name aria-banking-agent \
  --foundation-model "anthropic.claude-sonnet-4-5-v1:0" \
  --agent-resource-role-arn "$AGENT_ROLE_ARN" \
  --region eu-west-2
```

Enable detailed logging in the Bedrock console: **Agents → aria-banking-agent → Logging** → enable CloudWatch Logs.

### 9.3 — Common Issues and Fixes

**Issue: Agent keeps re-asking for authentication (loop)**
- Check that `cross_validate` Lambda returns `{"authenticated": true, "customer_name": "..."}` on success
- Verify `User Input` is `ENABLED` on the Agent (console: Additional Settings)
- Check the ARIA instruction prompt — "NEVER access account data before cross_validate" should use `cross_validate` result correctly

**Issue: Nova Sonic not speaking (silence)**
- Confirm Block 1 (Set Voice) has **Speaking style: Generative**
- Confirm Contact Lens real-time analytics is enabled (Block 2)
- Confirm Lex locale en-GB has Speech model = Speech-to-Speech (Amazon Nova Sonic)

**Issue: AMAZON.BedrockAgentIntent not triggering**
- Verify Generative AI features are enabled on the Lex bot locale
- Verify the intent is set to override FallbackIntent
- Rebuild and re-publish the bot locale after any changes

**Issue: Lambda permission error from Bedrock Agent**
- Confirm resource-based policy on Lambda allows `bedrock.amazonaws.com`
- Confirm the Agent IAM role has `lambda:InvokeFunction` on `aria-banking-*`
- Tighten: add `--source-arn arn:aws:bedrock:eu-west-2:395402194296:agent/$AGENT_ID` to Lambda permission

**Issue: Escalation not triggering**
- Check that `escalate_to_human` Lambda sets `{"escalation_requested": true}` in its return
- Check the Bedrock Agent passes this back as a session attribute
- Check Contact Flow Block 6 is reading `$.Attributes.escalation_requested`

**Issue: Long pauses during multi-tool turns**
- Bedrock Agent is calling multiple Lambdas sequentially before responding
- Ensure each Lambda cold start is minimised (add provisioned concurrency for `aria-banking-auth`)
- Consider adding an interim "thinking" response pattern to the Agent prompt for long operations

### 9.4 — Useful CLI Diagnostics

```bash
# Check Agent status
aws bedrock-agent get-agent \
  --agent-id $AGENT_ID \
  --region eu-west-2 \
  --query 'agent.{name:agentName,status:agentStatus,model:foundationModel}'

# Check all action groups
aws bedrock-agent list-agent-action-groups \
  --agent-id $AGENT_ID \
  --agent-version DRAFT \
  --region eu-west-2

# Check Lex bot status
aws lexv2-models describe-bot \
  --bot-id $BOT_ID \
  --region eu-west-2 \
  --query 'botStatus'

# Recent Lambda errors across all banking tools
for fn in auth account customer debit-card credit-card mortgage escalation; do
  echo "=== aria-banking-$fn ==="
  aws logs filter-log-events \
    --log-group-name /aws/lambda/aria-banking-$fn \
    --filter-pattern "ERROR" \
    --start-time $(python3 -c "import time; print(int((time.time()-3600)*1000))") \
    --region eu-west-2 \
    --query "events[].message" \
    --output text 2>/dev/null
done
```

---

## Part 10 — Why Not MCP Gateway Here? (Full Explanation)

This section documents the architectural reasoning explored when designing Path E.

### The Question

The Lambda Action Group functions in Path E are identical to the Lambda functions behind the AgentCore MCP Gateway used in Option D. Could you replace Lambda Action Groups with the MCP Gateway in Path E?

### The Answer: Two Types of Bedrock Agent, Two Tool Mechanisms

| | **Managed Bedrock Agent** | **Inline Agent (SDK)** |
|---|---|---|
| How invoked | `bedrock-agent:InvokeAgent` (Agent ID + Alias) | `InlineAgent(...).invoke()` in application code |
| Used with `AMAZON.BedrockAgentIntent` | ✅ Yes | ❌ No |
| Tool source | Lambda Action Groups (OpenAPI schema) | `mcp_clients=[]` directly in code |
| Supports MCP Gateway natively | ❌ No | ✅ Yes |

The `mcp_clients` syntax from the [AWS MCP + Bedrock Agents blog](https://aws.amazon.com/blogs/machine-learning/harness-the-power-of-mcp-servers-with-amazon-bedrock-agents/) is exclusively for the **Inline Agent SDK** — an ephemeral, programmatically-invoked agent pattern. It is not available for managed agents referenced via Agent ID.

`AMAZON.BedrockAgentIntent` in Lex V2 calls a **managed** Bedrock Agent. Managed agents support Lambda Action Groups (with OpenAPI schemas), not `mcp_clients`.

### What Happens If You Try to Add MCP Indirection

```
Lex → BedrockAgentIntent → Managed Agent
                              → Lambda Action Group: "gateway-proxy"  ← extra hop
                                   → AgentCore MCP Gateway
                                        → Lambda tools
```

This adds a redundant lambda-to-mcp-gateway-to-lambda chain. Zero benefit, additional latency, additional failure points.

### Correct Mapping

| Use Case | Architecture | Tool Mechanism |
|---|---|---|
| PSTN voice via Lex V2 (Path E) | Managed Bedrock Agent | Lambda Action Groups |
| PSTN voice via Connect Agentic (Option D) | Connect AI Agent | AgentCore MCP Gateway |
| Programmatic / app invocation | Inline Agent SDK | `mcp_clients=[]` |

Each pattern is purpose-built. Path E and Option D both result in the same phone call experience — choose based on whether you want the Bedrock Agent's full reasoning power (Path E) or simpler Connect-native management (Option D).

---

## Part 11 — Supervisor Monitoring, Barge-In and Real-Time Oversight

> **Official references used in this section:**
> - [Monitor live conversations – Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/monitor-conversations.html)
> - [Barge live conversations – Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/monitor-barge.html)
> - [Set recording and analytics behavior – Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/set-recording-behavior.html)
> - [Enable Contact Lens conversational analytics – Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html)
> - [Alert supervisors in real time – Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/add-rules-for-alerts.html)
> - [TransferContact – Amazon Connect API Reference](https://docs.aws.amazon.com/connect/latest/APIReference/API_TransferContact.html)

---

### 11.1 The Fundamental Constraint — What the Docs Actually Say

Amazon Connect's native CCP **Silent Monitor** and **Barge-In** capabilities are designed for calls where a **human agent** is present on the contact. Supervisors reach those calls via:

> *Analytics and optimization → Real-time metrics → Agents → click the eye icon on a Voice channel*

In Path E, during the ARIA bot phase, the contact is handled entirely by the **Lex V2 bot + Nova Sonic + Bedrock Agent** pipeline. There is **no human agent assigned to the contact**. The contact does not appear in any agent row in the Real-time metrics Agents table. The standard CCP monitor/barge workflow cannot reach the call while ARIA is handling it.

This is a structural constraint, not a configuration gap. The official docs describe the barge feature as follows:

> *"Supervisors and managers can barge into live voice and chat conversations **between agents and customers**."*
> — [Barge live conversations, Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/monitor-barge.html)

The key phrase is **between agents and customers**. A bot-only call is not that conversation.

---

### 11.2 What DOES Work Natively — Official AWS Capabilities

The following table distinguishes what is confirmed by official AWS documentation from what requires custom implementation:

| Capability | ARIA bot phase (Lex + Nova Sonic) | After transfer to human agent | Source |
|---|---|---|---|
| **Automated interaction call recording** | ✅ Native — enable in `Set recording and analytics behavior` block | ✅ Continuous | [Set recording behavior](https://docs.aws.amazon.com/connect/latest/adminguide/set-recording-behavior.html) |
| **Lex bot transcripts in Contact Details** | ✅ Native — enable "Bot Analytics and Transcripts" on instance | ✅ Combined transcript | [Set recording behavior – Bot Analytics note](https://docs.aws.amazon.com/connect/latest/adminguide/set-recording-behavior.html) |
| **Contact Lens real-time keyword/phrase alerts** | ✅ Native — fires on customer speech during bot phase | ✅ | [Alert supervisors in real time](https://docs.aws.amazon.com/connect/latest/adminguide/add-rules-for-alerts.html) |
| **Contact Lens real-time transcript** | ✅ Supervisor sees live transcript when alert fires | ✅ | [Alert supervisors in real time](https://docs.aws.amazon.com/connect/latest/adminguide/add-rules-for-alerts.html) |
| **Contact Lens sentiment scoring** | ✅ Customer sentiment tracked through bot phase | ✅ | [Enable Contact Lens](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html) |
| **Contact Lens post-call analytics** | ✅ Full bot + agent transcript, sentiment, categories | ✅ | [Enable Contact Lens](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html) |
| **CCP silent monitor (supervisor hears audio)** | ❌ Not supported — no agent on the call | ✅ Full CCP support | [Monitor live conversations](https://docs.aws.amazon.com/connect/latest/adminguide/monitor-conversations.html) |
| **CCP barge-in (supervisor speaks into call)** | ❌ Not supported — no agent on the call | ✅ Full CCP support | [Barge live conversations](https://docs.aws.amazon.com/connect/latest/adminguide/monitor-barge.html) |
| **Whisper coaching** | ❌ N/A — no agent to coach | ✅ Agent hears supervisor only | [Monitor live conversations](https://docs.aws.amazon.com/connect/latest/adminguide/monitor-conversations.html) |
| **Force-transfer via TransferContact API** | ❌ Not for voice — TASK and EMAIL only | N/A | [TransferContact API](https://docs.aws.amazon.com/connect/latest/APIReference/API_TransferContact.html) |

> **Contact Lens + multi-party calling limitation (official docs):**
> Contact Lens supports calls with **up to 2 participants**. AWS recommends disabling Contact Lens in the `Set recording and analytics behavior` block for contacts expected to have 3 or more participants (e.g., conference transfers). Keep Contact Lens enabled only while the call has at most 2 participants.
> — [Multi-party calls and conversational analytics](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html#multiparty-calls-contactlens)

---

### 11.3 Enabling Bot-Phase Recording and Analytics — Step by Step

#### Step 1 — Enable Bot Analytics on the Connect instance

In the Amazon Connect console:

1. Choose your instance alias
2. Navigation pane → **Flows**
3. Enable **"Bot Analytics and Transcripts in Amazon Connect"**

This includes Lex bot turn-by-turn transcripts in the **Contact Details** page and in Amazon Connect analytics dashboards. Without this, the bot conversation is a black box to the supervisory layer.

#### Step 2 — Configure the contact flow

In your ARIA inbound contact flow, place a `Set recording and analytics behavior` block **before** the bot interaction. Configure it as follows:

```
Voice section:
  ├── Agent and customer voice recording: ON (Agent and customer)
  ├── Automated interaction call recording: ON          ← captures bot phase audio
  └── Contact Lens speech analytics: Real-time analytics ← enables live alerts

Analytics section:
  ├── Language: en-GB
  ├── Enable Contact Lens conversational analytics: ON
  └── Enable sentiment analysis: ON
```

> **Important:** The `Set recording and analytics behavior` block must run **before** the `Get customer input` (Lex) block in the flow. If placed after, recording starts too late.

If ARIA transfers to a human agent queue, add a **second** `Set recording and analytics behavior` block in the **Transfer to queue flow** to continue analytics on the second contact record generated by the transfer. This is required because a transfer creates a new `contactId` — Contact Lens must be explicitly re-enabled on that record.

---

### 11.4 Real-Time Supervisor Alerts — What Fires and How

Contact Lens real-time rules fire on the customer's **speech** during the bot phase. When a rule triggers, the supervisor sees an alert on the real-time metrics dashboard with:
- The keyword/phrase that matched
- A live transcript of the conversation up to that point
- Customer sentiment trend

**Recommended keyword rules for the ARIA vulnerability and distress protocol:**

| Rule name | Phrases (customer speech) | Priority |
|---|---|---|
| Distress — Financial hardship | `struggling to pay`, `can't afford`, `lost my job`, `in debt`, `behind on payments` | High |
| Distress — Emotional | `really stressed`, `very worried`, `upset`, `frustrated`, `can't cope` | High |
| Bereavement | `someone has died`, `passed away`, `bereavement`, `they've died` | High |
| Transfer request | `speak to someone`, `speak to a person`, `speak to an agent`, `human`, `real person` | Medium |
| Fraud concern | `didn't make this payment`, `wasn't me`, `stolen`, `fraud`, `unauthorised` | High |

Configure these under: **Analytics and optimization → Rules → Create a rule → Conversational analytics → When: real-time analysis**

When any of these fire during an ARIA call, the supervisor sees the alert immediately. From the alert, they can see the live transcript. The next step — intervening — is described in 11.5.

---

### 11.5 Supervisor Intervention on an ARIA Bot Call — Three Patterns

Because CCP barge is not available during the bot phase, intervention requires one of the following patterns. These are ranked by complexity and latency.

---

#### Pattern A — ARIA escalates herself (preferred — already built)

**How it works:** ARIA's vulnerability protocol and distress detection (`system_prompt.py`, Section 4) already triggers `escalate_to_human_agent` when specific conditions are met. This routes the contact out of the bot and into the specialist queue. Once connected to a human agent, the supervisor can use full CCP monitor/barge immediately.

**Supervisor role:** Passive monitoring via Contact Lens alerts. If the alert shows ARIA has already responded appropriately (offering transfer), no action is required.

**Latency to supervisor control:** ~30–60 seconds (ARIA completes the escalation tool sequence, queue routes to agent, supervisor clicks monitor).

---

#### Pattern B — Contact attribute flag → ARIA detects and self-escalates

**How it works:** A supervisor dashboard calls `UpdateContactAttributes` to set a contact attribute on the live contact:

```json
{ "supervisor_override": "true" }
```

ARIA's escalation Lambda (or a check in the Bedrock Agent's session) reads contact attributes at each tool invocation turn via the Lambda event:

```python
# In any Lambda Action Group handler
contact_attrs = event.get("sessionAttributes", {})
if contact_attrs.get("supervisor_override") == "true":
    # Return a special tool response that tells the agent to escalate immediately
    return {"action": "escalate", "reason": "supervisor_override"}
```

The Bedrock Agent instruction includes a rule:

```
§ Supervisor override:
If sessionAttributes.supervisor_override is "true", immediately call
escalate_to_human_agent with escalation_reason: customer_request,
priority: urgent. Do not ask the customer. Say: "I'm going to connect
you with a colleague right away."
```

**Supervisor role:** Active — supervisor opens a custom dashboard, finds the live contact by contact ID, calls `UpdateContactAttributes` via API or a one-click button.

```python
import boto3
connect = boto3.client('connect', region_name='eu-west-2')

connect.update_contact_attributes(
    InstanceId='<your-instance-id>',
    InitialContactId='<contact-id-from-alert>',
    Attributes={'supervisor_override': 'true'}
)
```

**Latency to supervisor control:** ~10–15 seconds (attribute set → next ARIA turn detects it → escalation → queue → agent answers → supervisor monitors).

---

#### Pattern C — Contact Lens alert → EventBridge rule → Lambda → auto-escalate

**How it works:** Contact Lens fires a real-time event to Amazon EventBridge when a keyword rule matches. An EventBridge rule catches it and invokes a Lambda that calls `UpdateContactAttributes` automatically — no supervisor manual action required.

```
Contact Lens alert fires (keyword: "struggling to pay")
    ↓
EventBridge rule: source=aws.connect, detail-type=Contact Lens Realtime Analysis
    ↓
Lambda: check flag_type on customer profile → if financial_difficulty → set supervisor_override
    ↓
ARIA detects attribute on next turn → escalates to specialist queue
```

EventBridge event structure for Contact Lens real-time alert:

```json
{
  "source": "aws.connect",
  "detail-type": "Contact Lens Realtime Analysis",
  "detail": {
    "instanceArn": "arn:aws:connect:eu-west-2:...",
    "contactId": "abc-123",
    "channel": "VOICE",
    "matchedCategories": ["Distress-Financial-Hardship"],
    "matchedDetails": {
      "Distress-Financial-Hardship": {
        "pointsOfInterest": [{ "beginOffsetMillis": 4200, "endOffsetMillis": 5800 }]
      }
    }
  }
}
```

**Supervisor role:** Passive — the automation handles it. Supervisor is informed via the dashboard alert but does not need to click anything.

**Latency to supervisor control:** ~5–10 seconds to attribute set; ~20–30 seconds to human agent answered.

---

### 11.6 What the Supervisor Experience Looks Like End-to-End

```
1. ARIA is handling a live call (bot phase, no agent in CCP)
       │
       ├── Contact Lens: recording bot audio + generating live transcript
       ├── Contact Lens: scoring customer sentiment turn by turn
       └── Contact Lens: watching for keyword rule matches

2. Customer says "I've been struggling to pay for months"
       │
       └── Contact Lens keyword rule fires → alert appears on supervisor dashboard
             • Shows: customer sentiment (negative/declining)
             • Shows: live transcript of the bot conversation so far
             • Shows: which keyword matched and when

3. Supervisor sees the alert
       ├── Pattern A: ARIA's own vulnerability protocol already triggered → no action needed
       ├── Pattern B: Supervisor clicks "Override to human" → API call sets attribute
       └── Pattern C: EventBridge/Lambda already set the attribute automatically

4. ARIA detects escalation trigger → calls escalate_to_human_agent tool
       │
       └── Contact flow routes to specialist vulnerable-customer queue

5. Human agent answers
       │
       ├── Supervisor sees agent + customer in Real-time metrics Agents table
       ├── Supervisor clicks eye icon → CCP opens in Monitor mode
       └── Supervisor can toggle Monitor → Barge if they need to speak

6. Full transcript (bot phase + agent phase) available in Contact Lens Contact Details
       └── ARIA's handoff package (handoff_ref, transcript_summary) carried as
           contact attributes into the agent contact record
```

---

### 11.7 Contact Flow Changes Required

Add these two blocks to the ARIA inbound contact flow:

#### Block 1 — Before the Lex bot interaction

```
[Set contact attributes]
  └── supervisor_override = ""   (initialise as empty string)

[Set recording and analytics behavior]
  ├── Automated interaction call recording: ON
  ├── Agent and customer voice recording: ON
  └── Contact Lens speech analytics: Real-time analytics
        └── Language: en-GB

[Get customer input]
  └── Lex bot: ARIA-PathE-Bot
```

#### Block 2 — In the Transfer to queue flow (post-escalation)

```
[Set recording and analytics behavior]   ← second block on the transferred contact
  ├── Agent and customer voice recording: ON
  └── Contact Lens speech analytics: Real-time analytics OR Post-call analytics
```

> This second block is required because a queue transfer generates a new `contactId`. Contact Lens must be re-configured on the new contact record or the agent phase transcript will not be captured.

---

### 11.8 Security Profile Permissions Required

For supervisors to perform the functions in this section:

| Permission | Purpose | Where to assign |
|---|---|---|
| `Access metrics` | View real-time metrics dashboard and Contact Lens alerts | Security profile → Analytics |
| `Real-time contact monitoring` | Listen to live calls (after transfer to agent) | Security profile → Contact Control Panel |
| `Real-time contact barge-in` | Speak into live calls (after transfer to agent) | Security profile → Contact Control Panel |
| `Access Contact Control Panel` | Open the CCP | Security profile → Contact Control Panel |
| `Rules – Create/Edit` | Configure Contact Lens keyword alert rules | Security profile → Analytics |
| Connect API `connect:UpdateContactAttributes` | Set `supervisor_override` attribute (Pattern B) | IAM policy on supervisor tool role |

Assign supervisors the **CallCenterManager** security profile and the **Agent** security profile. The agent profile is required to open the CCP (which is the interface for live monitoring/barge once the call reaches an agent).

---

| Resource | Value |
|---|---|
| AWS Account | `395402194296` |
| Region | `eu-west-2` |
| Lambda tools role | `arn:aws:iam::395402194296:role/aria-banking-tools-lambda-role` |
| Bedrock Agent role | `arn:aws:iam::395402194296:role/aria-bedrock-agent-role` |
| Lex bot role | `arn:aws:iam::395402194296:role/aria-lex-bot-role` |
| Lex bot name | `ARIA-PathE-Bot` |
| Connect locale | `en_GB` |
| Connect voice | Amy (Nova Sonic Generative) |
| Lambda timeout | 25 seconds |
| Agent idle session TTL | 900 seconds (15 minutes) |
| Nova Sonic model region | `us-east-1` (cross-region from eu-west-2) |

---

*Path E architecture derived from: AWS official documentation — AMAZON.BedrockAgentIntent (Amazon Lex V2 Developer Guide), Amazon Bedrock Agents User Guide (Action Groups), Configure Amazon Nova Sonic Speech-to-Speech (Amazon Connect Administrator Guide), AWS sample repository `aws-samples/sample-amazon-connect-bedrock-agent-voice-integration`. MCP Gateway architectural distinction documented from: AWS ML Blog "Harness the power of MCP servers with Amazon Bedrock Agents" (June 2025). Supervisor monitoring and Contact Lens section (Part 11) derived from: Monitor live conversations, Barge live conversations, Set recording and analytics behavior, Enable Contact Lens conversational analytics, Alert supervisors in real time, and TransferContact API Reference — all Amazon Connect Administrator Guide / API Reference (AWS official documentation).*
