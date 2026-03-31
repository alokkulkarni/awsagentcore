# Option D: Amazon Connect Agentic Self-Service + AgentCore MCP Gateway
## ARIA Banking Agent — Direct AI Agent Integration Guide (No Lex V2)

> **Official references:**  
> - [Amazon Connect AI Agents – Self-Service](https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-self-service.html)  
> - [Amazon Connect AI Agents – MCP Tools](https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-mcp-tools.html)  
> - [AgentCore Gateway – Building](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building.html)  
> - [AgentCore Gateway – Create](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create.html)  
> - [AgentCore Gateway – Using](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using.html)

---

## Overview

This guide implements **Option D**: Amazon Connect handles the entire PSTN voice pipeline using its native **Agentic Self-Service** AI engine, while ARIA's banking tools are exposed as **MCP tools** through an **AgentCore MCP Gateway**. No Lex V2 bot or Lambda fulfillment bridge is required.

### How It Differs from Path A

| | Path A (Lex + Lambda → AgentCore) | Option D (Connect Agentic + MCP Gateway) |
|---|---|---|
| **Voice handling** | Connect → Lex V2 + Nova Sonic | Connect native AI agent + Nova Sonic |
| **Reasoning engine** | ARIA's Claude Sonnet 4.6 via Strands | Connect's built-in AI orchestrator |
| **Banking tools** | Called by Strands agent directly | Called via AgentCore MCP Gateway |
| **ARIA persona/prompt** | ARIA system prompt in AgentCore | AI Prompt override in Connect |
| **Lex V2 bot needed?** | Yes | **No** |
| **Lambda bridge needed?** | Yes | **No** |
| **Complexity** | Moderate | Moderate (different parts) |
| **Existing ARIA stack** | Used (HTTP /invocations) | Unchanged (browser/chat path unaffected) |

### Architecture

```
PSTN Call
    │
    ▼
Amazon Connect
    │ (Inbound Contact Flow)
    ▼
Connect Agentic Self-Service AI Agent
 • Orchestration type AI agent
 • ARIA persona loaded as AI Prompt override
 • Nova Sonic S2S for voice (ASR + TTS)
 • Multi-turn conversation with full reasoning
    │
    │ MCP protocol (tools/list + tools/call)
    │ via registered AgentCore Gateway URL
    ▼
AgentCore MCP Gateway
 • Inbound auth: IAM (Connect service role)
 • Outbound auth: IAM (Lambda invoke)
    │
    ├──▶ Lambda: aria-banking-auth        (identity verification)
    ├──▶ Lambda: aria-banking-account     (balances, transactions, statements)
    ├──▶ Lambda: aria-banking-customer    (customer profile)
    ├──▶ Lambda: aria-banking-debit-card  (card status, block, replace)
    ├──▶ Lambda: aria-banking-credit-card (card status, block, replace)
    ├──▶ Lambda: aria-banking-mortgage    (mortgage details)
    └──▶ Lambda: aria-banking-escalation  (human handoff signal)

Parallel (unchanged):
Browser / mobile client
    │
    ▼
Existing ARIA AgentCore Runtime
 • POST /invocations → Claude Sonnet 4.6 + Strands (chat)
 • WS /ws → Nova Sonic S2S (voice)
```

> **Key insight**: The existing ARIA AgentCore Runtime is **not modified** by Option D. It continues to serve browser and mobile clients. Option D is a parallel PSTN integration path.

---

## Prerequisites

- Amazon Connect instance in `eu-west-2` (same region as ARIA stack)
- Amazon Connect instance with **AI Agents** feature enabled (available on instances created after mid-2024; enable in instance settings if needed)
- IAM permissions: `bedrock-agentcore:*`, `connect:*`, `lambda:*`, `iam:*`
- Python 3.12 for Lambda functions
- AWS CLI configured for account `395402194296`, region `eu-west-2`

---

## Part 1 — Create Lambda Tool Functions

ARIA's banking tools are currently Strands `@tool`-decorated Python functions inside the AgentCore Runtime container. For Option D, you create standalone Lambda functions that implement the same logic and can be called by the AgentCore MCP Gateway.

### 1.1 — Create the Lambda IAM Execution Role

```bash
aws iam create-role \
  --role-name aria-banking-tools-lambda-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam attach-role-policy \
  --role-name aria-banking-tools-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

> **Note:** Attach additional policies (e.g., `secretsmanager:GetSecretValue`, `dynamodb:*`) when replacing the stub data with real banking API calls.

### 1.2 — Lambda Deployment Structure

Create the following directory inside `scripts/lambdas/mcp_tools/`:

```
scripts/lambdas/mcp_tools/
├── aria_auth_handler.py
├── aria_account_handler.py
├── aria_customer_handler.py
├── aria_debit_card_handler.py
├── aria_credit_card_handler.py
├── aria_mortgage_handler.py
└── aria_escalation_handler.py
```

### 1.3 — Lambda: Authentication Handler

Create `scripts/lambdas/mcp_tools/aria_auth_handler.py`:

```python
"""
Lambda handler: ARIA Authentication Tools (MCP Gateway target)

Tools exposed:
  - initiate_auth      — begins customer authentication session
  - validate_customer  — validates customer ID exists
  - cross_validate     — verifies DOB + last 4 mobile against record
  - verify_identity    — confirms identity match for data access

Invoked by AgentCore MCP Gateway on behalf of Connect Agentic Self-Service.
"""

import json

MOCK_CUSTOMERS = {
    "CUST-001": {
        "name": "James",
        "dob": "09/09/1982",
        "mobile_last_four": "9252",
        "status": "active",
    }
}


def lambda_handler(event: dict, context) -> dict:
    tool_name = event.get("toolName") or event.get("tool_name", "")
    params = event.get("parameters") or event.get("params", {})

    if tool_name == "initiate_auth":
        return _initiate_auth(params)
    elif tool_name == "validate_customer":
        return _validate_customer(params)
    elif tool_name == "cross_validate":
        return _cross_validate(params)
    elif tool_name == "verify_identity":
        return _verify_identity(params)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def _initiate_auth(params: dict) -> dict:
    return {
        "session_started": True,
        "message": "Authentication session initiated. Please provide customer ID.",
        "required_fields": ["customer_id"],
    }


def _validate_customer(params: dict) -> dict:
    cid = params.get("customer_id", "").strip()
    if cid in MOCK_CUSTOMERS:
        return {"valid": True, "name": MOCK_CUSTOMERS[cid]["name"]}
    return {"valid": False, "message": "Customer ID not found."}


def _cross_validate(params: dict) -> dict:
    """Verifies DOB and last 4 digits of mobile number."""
    cid = params.get("customer_id", "").strip()
    dob = params.get("date_of_birth", "").strip()
    mobile4 = params.get("mobile_last_four", "").strip()

    if cid not in MOCK_CUSTOMERS:
        return {"verified": False, "reason": "Customer not found."}

    cust = MOCK_CUSTOMERS[cid]
    dob_match = cust["dob"] == dob
    mobile_match = cust["mobile_last_four"] == mobile4

    if dob_match and mobile_match:
        return {
            "verified": True,
            "customer_id": cid,
            "name": cust["name"],
            "auth_level": "full",
        }
    return {
        "verified": False,
        "reason": "Verification details do not match our records.",
    }


def _verify_identity(params: dict) -> dict:
    """Confirms the authenticated identity before data access."""
    header_cid = params.get("header_customer_id", "").strip()
    requested_cid = params.get("requested_customer_id", "").strip()
    match = header_cid == requested_cid
    return {
        "identity_match": match,
        "risk_score": 10 if match else 90,
        "auth_level": "full" if match else "none",
    }
```

### 1.4 — Lambda: Account Handler

Create `scripts/lambdas/mcp_tools/aria_account_handler.py`:

```python
"""
Lambda handler: ARIA Account Tools (MCP Gateway target)

Tools exposed:
  - get_account_details — balance, transactions, statement, standing orders
"""

import json


def lambda_handler(event: dict, context) -> dict:
    tool_name = event.get("toolName") or event.get("tool_name", "")
    params = event.get("parameters") or event.get("params", {})

    if tool_name == "get_account_details":
        return _get_account_details(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_account_details(params: dict) -> dict:
    account_number = params.get("account_number", "")
    query_subtype = params.get("query_subtype", "balance")
    last_four = account_number[-4:] if len(account_number) >= 4 else account_number

    base = {
        "account_number_last_four": last_four,
        "sort_code_last_two": "67",
        "account_type": "current",
        "available_balance": 1245.30,
        "cleared_balance": 1300.00,
        "currency": "GBP",
        "query_subtype": query_subtype,
    }

    if query_subtype == "transactions":
        base["recent_transactions"] = [
            {"date": "2026-03-27", "description": "TESCO STORES", "amount": -42.50},
            {"date": "2026-03-26", "description": "SALARY MERIDIAN CORP", "amount": 3200.00},
            {"date": "2026-03-25", "description": "AMAZON.CO.UK", "amount": -89.99},
            {"date": "2026-03-24", "description": "DIRECT DEBIT - EDF ENERGY", "amount": -75.00},
            {"date": "2026-03-23", "description": "CONTACTLESS - COSTA COFFEE", "amount": -4.50},
        ]
    elif query_subtype == "standing_orders":
        base["standing_orders"] = [
            {"payee": "LANDLORD RENT", "amount": 950.00, "frequency": "monthly", "next_date": "2026-04-01"}
        ]
    elif query_subtype == "statement":
        customer_id = params.get("customer_id", "unknown")
        base["statement_url"] = f"https://secure.meridianbank.co.uk/statements/{customer_id}/{last_four}"

    return base
```

### 1.5 — Lambda: Debit Card Handler

Create `scripts/lambdas/mcp_tools/aria_debit_card_handler.py`:

```python
"""
Lambda handler: ARIA Debit Card Tools (MCP Gateway target)

Tools exposed:
  - get_debit_card_details — card status, limits, lost/stolen, replacement
  - block_debit_card       — block a debit card (lost/stolen)
"""


def lambda_handler(event: dict, context) -> dict:
    tool_name = event.get("toolName") or event.get("tool_name", "")
    params = event.get("parameters") or event.get("params", {})

    if tool_name == "get_debit_card_details":
        return _get_debit_card_details(params)
    elif tool_name == "block_debit_card":
        return _block_debit_card(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_debit_card_details(params: dict) -> dict:
    card_last_four = params.get("card_last_four", "****")
    return {
        "card_last_four": card_last_four,
        "card_status": "active",
        "card_type": "Visa Debit",
        "daily_atm_limit": 500.00,
        "daily_pos_limit": 5000.00,
        "expiry_masked": "**/**",
        "replacement_available": True,
        "contactless_enabled": True,
        "online_payments_enabled": True,
    }


def _block_debit_card(params: dict) -> dict:
    card_last_four = params.get("card_last_four", "****")
    reason = params.get("reason", "lost_stolen")
    return {
        "blocked": True,
        "card_last_four": card_last_four,
        "reason": reason,
        "message": f"Card ending {card_last_four} has been blocked. A replacement will be issued within 3-5 working days.",
        "reference": f"BLOCK-{card_last_four}-001",
    }
```

### 1.6 — Lambda: Credit Card Handler

Create `scripts/lambdas/mcp_tools/aria_credit_card_handler.py`:

```python
"""
Lambda handler: ARIA Credit Card Tools (MCP Gateway target)

Tools exposed:
  - get_credit_card_details — balance, limit, transactions, lost/stolen
  - block_credit_card       — block a credit card (lost/stolen)
"""


def lambda_handler(event: dict, context) -> dict:
    tool_name = event.get("toolName") or event.get("tool_name", "")
    params = event.get("parameters") or event.get("params", {})

    if tool_name == "get_credit_card_details":
        return _get_credit_card_details(params)
    elif tool_name == "block_credit_card":
        return _block_credit_card(params)
    return {"error": f"Unknown tool: {tool_name}"}


def _get_credit_card_details(params: dict) -> dict:
    card_last_four = params.get("card_last_four", "****")
    query_subtype = params.get("query_subtype", "status")
    return {
        "card_last_four": card_last_four,
        "card_type": "Rewards Credit Card",
        "card_status": "active",
        "credit_limit": 5000.00,
        "available_credit": 3250.00,
        "outstanding_balance": 1750.00,
        "minimum_payment": 35.00,
        "next_payment_date": "2026-04-15",
        "expiry_masked": "**/**",
        "query_subtype": query_subtype,
    }


def _block_credit_card(params: dict) -> dict:
    card_last_four = params.get("card_last_four", "****")
    reason = params.get("reason", "lost_stolen")
    return {
        "blocked": True,
        "card_last_four": card_last_four,
        "reason": reason,
        "message": f"Credit card ending {card_last_four} has been blocked. A replacement will be issued within 3-5 working days.",
        "reference": f"CC-BLOCK-{card_last_four}-001",
    }
```

### 1.7 — Lambda: Customer, Mortgage, and Escalation Handlers

Create `scripts/lambdas/mcp_tools/aria_customer_handler.py`:

```python
"""Lambda handler: ARIA Customer Profile Tools (MCP Gateway target)"""

MOCK_CUSTOMERS = {
    "CUST-001": {
        "name": "James",
        "accounts": [
            {"type": "current", "nickname": "Main Account", "number_last_four": "4521"},
            {"type": "savings", "nickname": "Holiday Savings", "number_last_four": "7832"},
        ],
        "debit_cards": [{"nickname": "Everyday Debit", "last_four": "8901"}],
        "credit_cards": [{"nickname": "Rewards Credit Card", "last_four": "3456"}],
        "has_mortgage": True,
    }
}


def lambda_handler(event: dict, context) -> dict:
    tool_name = event.get("toolName") or event.get("tool_name", "")
    params = event.get("parameters") or event.get("params", {})

    if tool_name == "get_customer_profile":
        cid = params.get("customer_id", "")
        if cid in MOCK_CUSTOMERS:
            return {"customer_id": cid, **MOCK_CUSTOMERS[cid]}
        return {"error": "Customer not found"}
    return {"error": f"Unknown tool: {tool_name}"}
```

Create `scripts/lambdas/mcp_tools/aria_mortgage_handler.py`:

```python
"""Lambda handler: ARIA Mortgage Tools (MCP Gateway target)"""


def lambda_handler(event: dict, context) -> dict:
    tool_name = event.get("toolName") or event.get("tool_name", "")
    params = event.get("parameters") or event.get("params", {})

    if tool_name == "get_mortgage_details":
        return {
            "customer_id": params.get("customer_id"),
            "outstanding_balance": 210500.00,
            "monthly_payment": 1245.00,
            "interest_rate": 4.25,
            "rate_type": "fixed",
            "rate_expiry_date": "2027-06-30",
            "term_remaining_years": 18,
            "next_payment_date": "2026-04-01",
            "property_address_masked": "** Oak Street, Altrincham",
        }
    return {"error": f"Unknown tool: {tool_name}"}
```

Create `scripts/lambdas/mcp_tools/aria_escalation_handler.py`:

```python
"""Lambda handler: ARIA Escalation Tools (MCP Gateway target)"""


def lambda_handler(event: dict, context) -> dict:
    tool_name = event.get("toolName") or event.get("tool_name", "")
    params = event.get("parameters") or event.get("params", {})

    if tool_name == "escalate_to_human":
        reason = params.get("reason", "Customer request")
        return {
            "escalation_requested": True,
            "reason": reason,
            "message": "Transferring you to one of our team now. Please hold.",
            "transfer_queue": "CustomerServiceQueue",
        }
    return {"error": f"Unknown tool: {tool_name}"}
```

### 1.8 — Deploy Lambda Functions

Package and deploy each handler. Repeat for all seven handlers:

```bash
cd scripts/lambdas/mcp_tools

# Example for the auth handler
zip aria_auth_handler.zip aria_auth_handler.py

aws lambda create-function \
  --function-name aria-banking-auth \
  --runtime python3.12 \
  --role arn:aws:iam::395402194296:role/aria-banking-tools-lambda-role \
  --handler aria_auth_handler.lambda_handler \
  --zip-file fileb://aria_auth_handler.zip \
  --timeout 25 \
  --region eu-west-2
```

Repeat with:
- `aria-banking-account` → `aria_account_handler.lambda_handler`
- `aria-banking-customer` → `aria_customer_handler.lambda_handler`
- `aria-banking-debit-card` → `aria_debit_card_handler.lambda_handler`
- `aria-banking-credit-card` → `aria_credit_card_handler.lambda_handler`
- `aria-banking-mortgage` → `aria_mortgage_handler.lambda_handler`
- `aria-banking-escalation` → `aria_escalation_handler.lambda_handler`

> **MCP tool timeout:** AgentCore Gateway enforces a **30-second** timeout per tool invocation. Lambda timeout should be ≤ 25 seconds to allow for Gateway overhead.

---

## Part 2 — Create the AgentCore MCP Gateway

### 2.1 — Open the AgentCore Console

1. Navigate to **AWS Console → Amazon Bedrock → AgentCore → Gateways**
   (direct URL: `https://console.aws.amazon.com/bedrock-agentcore/home#`)
2. Choose **Create gateway**

### 2.2 — Configure Gateway Details

| Field | Value |
|---|---|
| Gateway name | `aria-banking-mcp-gateway` |
| Description | `MCP Gateway exposing ARIA banking tools to Amazon Connect Agentic Self-Service` |
| Enable semantic search | ✅ (recommended — allows Connect's AI to find tools by natural language description) |
| Exception level debug | ✅ (during initial setup; disable in production) |

> **Important:** Semantic search cannot be enabled after creation. Enable it now.

### 2.3 — Configure Inbound Authorization

Amazon Connect will call the Gateway using **IAM credentials** (the Connect service role). Select:

- **Inbound Auth:** `Use an IAM service role`
- **IAM Role:** `Create and use a new service role`
  - Service role name: `aria-gateway-invoke-role`

The auto-created role will have `bedrock-agentcore:InvokeGateway` permissions.

### 2.4 — Add First Target (Auth Tools)

In the **Target** section during gateway creation:

| Field | Value |
|---|---|
| Target name | `auth-tools` |
| Target type | `Lambda` |
| Lambda function | Select `aria-banking-auth` |
| Outbound auth | `IAM` (auto-creates role with `lambda:InvokeFunction` permission) |

Click **Add another target** and repeat for each Lambda:

| Target name | Lambda function |
|---|---|
| `account-tools` | `aria-banking-account` |
| `customer-tools` | `aria-banking-customer` |
| `debit-card-tools` | `aria-banking-debit-card` |
| `credit-card-tools` | `aria-banking-credit-card` |
| `mortgage-tools` | `aria-banking-mortgage` |
| `escalation-tools` | `aria-banking-escalation` |

### 2.5 — Create the Gateway

Click **Create gateway**.

After creation, record the **Gateway endpoint URL** — it will look like:
```
https://gateway.bedrock-agentcore.eu-west-2.amazonaws.com/mcp/<gateway-id>
```

This URL is used when registering the gateway with Amazon Connect.

### 2.6 — Verify the Gateway

Test that tools are discoverable via the MCP `tools/list` operation:

```bash
# Get the gateway ID
GATEWAY_ID=$(aws bedrock-agentcore list-gateways \
  --region eu-west-2 \
  --query "gateways[?name=='aria-banking-mcp-gateway'].gatewayId" \
  --output text)

echo "Gateway ID: $GATEWAY_ID"

# List available tools (requires SigV4 signing — use AWS CLI with --no-sign-request for IAM)
aws bedrock-agentcore invoke-gateway \
  --gateway-id $GATEWAY_ID \
  --body '{"jsonrpc":"2.0","id":"1","method":"tools/list","params":{}}' \
  --region eu-west-2
```

You should see all banking tool names listed in the response.

---

## Part 3 — Configure Permissions for Connect → Gateway

Grant Amazon Connect permission to invoke the AgentCore Gateway.

### 3.1 — Find Your Connect Service Role

```bash
aws connect describe-instance \
  --instance-id <your-connect-instance-id> \
  --region eu-west-2 \
  --query "Instance.ServiceRole" \
  --output text
```

### 3.2 — Attach Gateway Invoke Permission

```bash
aws iam put-role-policy \
  --role-name <connect-service-role-name> \
  --policy-name aria-gateway-invoke \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["bedrock-agentcore:InvokeGateway"],
      "Resource": "arn:aws:bedrock-agentcore:eu-west-2:395402194296:gateway/*"
    }]
  }'
```

---

## Part 4 — Set Up Amazon Connect AI Agents Domain

> Skip this part if you already created a domain in Part 4 of the **Path A guide**.

### 4.1 — Enable AI Agents on Your Connect Instance

1. Open **AWS Console → Amazon Connect**
2. Select your instance alias
3. In the navigation pane, choose **AI Agents**
4. Choose **Add domain** → **Create a domain**
5. Enter domain name: `meridian-bank-ai-domain`
6. Under **Encryption**, use the default AWS managed key (or specify your own KMS key)
7. Click **Add domain**

> **Note:** One Connect instance can be associated with only one domain.

### 4.2 — (Optional) Add a Knowledge Base Integration

For ARIA's "product information" and FAQ capabilities, add an S3 knowledge base integration:

1. On the **AI Agents** page, choose **Add integration**
2. Select **Amazon S3** as the source
3. Configure your S3 bucket containing Meridian Bank FAQs and product information
4. Set sync frequency to **Daily**
5. Click **Add integration**

---

## Part 5 — Register the AgentCore Gateway with Amazon Connect

Amazon Connect requires the AgentCore Gateway to be registered as a **third-party application** before it can be used as an MCP tool source.

### 5.1 — Register via AWS CLI

```bash
aws connect create-integration-association \
  --instance-id <your-connect-instance-id> \
  --integration-type CASES_DOMAIN \
  --integration-arn "arn:aws:bedrock-agentcore:eu-west-2:395402194296:gateway/<gateway-id>" \
  --region eu-west-2
```

> **Alternative — Console registration:**
> 1. In Amazon Connect admin console, go to **Admin → AWS service integrations**
> 2. Choose **Add integration**
> 3. Select **Amazon Bedrock AgentCore Gateway**
> 4. Enter the Gateway ARN or ID
> 5. Save

### 5.2 — Verify Registration

The gateway should now appear as an available MCP tool source in the Connect AI Agent builder.

---

## Part 6 — Create the ARIA Orchestration AI Agent

This is the core of Option D: a Connect AI Agent of type **Orchestration** that has the ARIA persona and can invoke banking tools via MCP.

### 6.1 — Create the AI Prompt (ARIA Persona)

1. In Amazon Connect admin console, go to **AI Agent Designer → AI Prompts**
2. Choose **Create AI Prompt**
3. Configure:
   - **Name:** `aria-banking-orchestration-prompt`
   - **Type:** `Orchestration`
4. Enter the following prompt content:

```
You are ARIA (Automated Retail Intelligence Assistant), the virtual banking assistant for Meridian Bank. You are professional, empathetic, and security-focused.

## Your Capabilities
You can help customers with:
- Account details, balances, recent transactions, and statements
- Standing orders
- Debit card queries, blocking lost/stolen cards, requesting replacements
- Credit card balances, limits, and blocking lost/stolen cards
- Mortgage details
- General product information

## Authentication Requirements
EVERY session MUST begin with identity verification. Never access account data without completing authentication.

Authentication steps:
1. Call initiate_auth to start the session
2. Ask for the customer's Customer ID
3. Call validate_customer to confirm the ID exists
4. Ask for date of birth (DD/MM/YYYY)
5. Ask for last 4 digits of registered mobile number
6. Call cross_validate with all three inputs
7. If verified, welcome the customer by name

## Conversation Rules
- Always verify identity FIRST before accessing any account data
- Never read out full account numbers, card numbers, sort codes, CVVs, or PINs
- Only share the last 4 digits of account/card numbers
- If risk_score > 75 from verify_identity, escalate immediately
- For lost or stolen cards, confirm the customer's intent before calling block_debit_card or block_credit_card
- For escalation requests, call escalate_to_human and then transfer the call
- Keep responses concise — this is a phone call, not a text conversation
- When the customer says goodbye or ends the conversation, close warmly

## Tone
Professional, warm, and reassuring. Use plain English. Avoid jargon. Keep sentences short for voice clarity.

## Escalation Triggers
Escalate immediately if the customer:
- Requests to speak to a human agent
- Has a complex dispute or complaint
- Risk score exceeds 75 (potential fraud)
- Requests something outside your capabilities
```

5. Click **Save** then **Publish** to create version 1

### 6.2 — Create the Orchestration AI Agent

1. In **AI Agent Designer → AI Agents**, choose **Create AI Agent**
2. Configure:
   - **AI Agent type:** `Orchestration`
   - **Name:** `aria-banking-orchestration-agent`
   - **Locale:** `en_GB`
3. Under **AI Prompts**, select the published version of `aria-banking-orchestration-prompt`
4. Under **Tools (MCP)**, click **Add tool**:
   - Select **Third-party (AgentCore Gateway)**
   - Choose the registered `aria-banking-mcp-gateway`
   - All tools will be listed — ensure all banking tools are enabled
5. (Optional) Add an **AI Guardrail** to prevent ARIA from discussing non-banking topics
6. Click **Save** then **Publish**

---

## Part 7 — Configure the Contact Flow

### 7.1 — Create a New Inbound Contact Flow

1. In Amazon Connect admin console, go to **Contact flows**
2. Choose **Create contact flow** → select **Inbound flow** type
3. Name it: `ARIA-Agentic-Banking-Flow`

### 7.2 — Build the Flow

Add the following blocks in order:

**Block 1: Set Voice**
- Block type: `Set voice`
- Voice: `Amy` (en-GB)
- Speaking style: `Generative` ← **Required for Nova Sonic S2S output**

**Block 2: Set Recording and Analytics Behavior**
- Block type: `Set recording and analytics behavior`
- Contact Lens: **Enable real-time analytics** ← Required for Connect AI Agents with voice
- Recording: Enable as per your data retention policy

**Block 3: Set Connect Assistant**
- Block type: `Connect assistant`  
- Select the domain: `meridian-bank-ai-domain`
- Orchestration AI Agent: `aria-banking-orchestration-agent` (published version)

**Block 4: Check for Escalation**
- Block type: `Check contact attributes`
- Condition: Check if `$.ContactAttribute.escalation_requested` = `true`
  - **True branch** → Transfer to Queue block (see Block 5)
  - **False / No match** → End flow block (see Block 6)

**Block 5: Transfer to Queue (Escalation)**
- Block type: `Transfer to queue`
- Queue: `CustomerServiceQueue`
- Optionally set a whisper flow to brief the human agent

**Block 6: Disconnect**
- Block type: `Disconnect`

### 7.3 — Save and Publish

1. Click **Save** then **Publish**

---

## Part 8 — Assign a Phone Number

1. In Amazon Connect admin console, go to **Channels → Phone numbers**
2. Choose **Claim a number** (or select an existing number)
3. Under **Flow / IVR**, select `ARIA-Agentic-Banking-Flow`
4. Click **Save**

The phone number is now live. Calls will be handled by the ARIA Agentic Self-Service flow.

---

## Part 9 — Test and Validate

### 9.1 — Test via Amazon Connect Test Console

1. In the Connect admin console, go to **Test chat/voice simulator**
2. Select the `ARIA-Agentic-Banking-Flow`
3. Start a simulated call

Expected flow:
- ARIA greets the customer and asks for Customer ID
- Customer provides `CUST-001`
- ARIA asks for DOB: `09/09/1982`
- ARIA asks for last 4 of mobile: `9252`
- ARIA confirms identity: "Welcome back, James."
- Customer asks about account balance
- ARIA calls `get_account_details` via MCP Gateway
- ARIA responds with balance using Nova Sonic voice

### 9.2 — Validate MCP Tool Invocations

Check Lambda invocation logs:

```bash
aws logs tail /aws/lambda/aria-banking-auth \
  --follow \
  --region eu-west-2

aws logs tail /aws/lambda/aria-banking-account \
  --follow \
  --region eu-west-2
```

Look for:
- `toolName` being set correctly in the event
- Successful response returned within 25 seconds
- No auth errors from the Gateway

### 9.3 — Test Lost Card Scenario

Say: "I've lost my debit card"

Expected:
- ARIA acknowledges and confirms intent
- ARIA calls `get_debit_card_details` to retrieve card info
- ARIA confirms card ending in `8901`
- ARIA asks: "Would you like me to block this card now?"
- Customer confirms
- ARIA calls `block_debit_card`
- ARIA confirms: "Your card ending 8901 has been blocked. A replacement will arrive in 3-5 working days."

### 9.4 — Test Escalation

Say: "I'd like to speak to someone"

Expected:
- ARIA calls `escalate_to_human`
- ARIA says: "Transferring you to one of our team now. Please hold."
- Call transfers to `CustomerServiceQueue`

---

## Part 10 — Monitoring and Troubleshooting

### 10.1 — CloudWatch Metrics to Monitor

| Metric | Where | Alert Threshold |
|---|---|---|
| Lambda duration | `/aws/lambda/aria-banking-*` | > 20s (approaching 30s MCP timeout) |
| Lambda errors | `/aws/lambda/aria-banking-*` | Any error |
| MCP tool invocations | AgentCore Gateway console | Track per-tool usage |
| Contact resolution rate | Connect Analytics | < 70% = investigate |
| Escalation rate | Connect Analytics | > 30% = AI prompt needs tuning |

### 10.2 — Common Issues

**Issue: "Tool not found" from the AI Agent**
- Check that the AgentCore Gateway is registered in Connect and all targets are active
- Enable `Exception level debug` on the Gateway to see detailed errors
- Verify Lambda function names match the target configuration

**Issue: MCP timeout (30-second limit exceeded)**
- Check Lambda execution time in CloudWatch Logs Insights
- Optimise the Lambda handler (reduce cold start, increase memory)
- Consider provisioned concurrency for high-traffic scenarios

**Issue: Authentication loop (AI agent keeps asking for credentials)**
- Review the Orchestration AI Prompt — ensure the `cross_validate` tool result is being used to set authentication state
- Check that `validate_customer` Lambda returns `{"valid": true}` for correct IDs
- Review Connect AI agent session logs in CloudWatch

**Issue: Nova Sonic not speaking (silence after text is generated)**
- Confirm the `Set voice` block has **Speaking style: Generative** set
- Confirm Contact Lens real-time is enabled (required for voice AI agents)
- Check the bot locale in Connect instance settings supports en_GB

**Issue: Call not transferring on escalation**
- Verify the `escalate_to_human` Lambda returns `{"escalation_requested": true}`
- Confirm the Contact Flow has the `Check contact attributes` block configured correctly
- Check that `CustomerServiceQueue` exists and has agents available

### 10.3 — Useful CLI Diagnostics

```bash
# List all Gateway targets and their status
aws bedrock-agentcore list-gateway-targets \
  --gateway-id <gateway-id> \
  --region eu-west-2

# Check Connect AI Agent configuration
aws qconnect get-ai-agent \
  --assistant-id <connect-assistant-id> \
  --ai-agent-id <ai-agent-id>

# View recent Lambda errors for all banking tools
for fn in auth account customer debit-card credit-card mortgage escalation; do
  echo "=== aria-banking-$fn ==="
  aws logs filter-log-events \
    --log-group-name /aws/lambda/aria-banking-$fn \
    --filter-pattern "ERROR" \
    --start-time $(date -v-1H +%s000) \
    --region eu-west-2 \
    --query "events[].message" \
    --output text 2>/dev/null
done
```

---

## Comparison: Option D vs Path A

Use this to decide which approach fits your use case.

| Criteria | Path A (Lex + Lambda → AgentCore) | Option D (Connect Agentic + MCP) |
|---|---|---|
| **AI reasoning engine** | Claude Sonnet 4.6 (your ARIA agent) | Connect's built-in AI orchestrator |
| **Reasoning customisation** | Full — Strands agent, custom tools, full prompt control | Via AI Prompts only |
| **Tool invocation** | Strands agent directly calls Python tools | MCP Gateway → Lambda |
| **Lex V2 required** | Yes | No |
| **Lambda bridge required** | Yes | No |
| **Components to manage** | Lex bot + Lambda + AgentCore Runtime | MCP Gateway + Lambda tools + Connect AI Agent |
| **Voice quality** | Nova Sonic (via Lex) | Nova Sonic (via Connect native) |
| **Session continuity** | ContactId → AgentCore session | Connect AI Agent session (managed by Connect) |
| **MCP tool timeout** | Not applicable | 30 seconds per tool |
| **Cost model** | Lex invocations + Lambda + AgentCore | Connect AI Agent usage + Lambda + Gateway |
| **Best for** | Maximum ARIA intelligence, full customisation | Simpler deployment, Connect-native management |
| **ARIA browser/mobile** | Same AgentCore Runtime | Same AgentCore Runtime (unaffected) |

### Recommendation

- **Choose Path A** if you want ARIA's full intelligence (Claude Sonnet 4.6 + Strands reasoning) and maximum control over the banking conversation logic.
- **Choose Option D** if you prefer a simpler architecture with fewer moving parts and are comfortable with Connect's built-in AI handling the reasoning, using your banking tools via MCP.

Both paths can be deployed simultaneously for A/B testing or redundancy — they use completely independent Connect Contact Flows and phone numbers.

---

## Reference Values (This Stack)

| Resource | Value |
|---|---|
| AWS Account | `395402194296` |
| Region | `eu-west-2` |
| ARIA AgentCore Runtime ARN | `arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY` |
| Lambda tool role | `arn:aws:iam::395402194296:role/aria-banking-tools-lambda-role` |
| Lambda timeout | 25 seconds (under 30s MCP Gateway limit) |
| Connect locale | `en_GB` |
| Connect voice | Amy (Nova Sonic Generative) |
| MCP Gateway timeout | 30 seconds (AWS hard limit) |
