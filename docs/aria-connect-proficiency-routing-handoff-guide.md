# ARIA — Proficiency-Based Routing & Agent Handoff Summary Guide

> **Companion document to:**
> [ARIA + Amazon Connect: Voice & Chat Conversational AI — Complete Novice Guide](./aria-connect-voice-chat-novice-guide.md)
> → Steps D.6b (Proficiency Routing) and the Agent Handoff Summary extension
>
> **Read this after:** Step D.6a (TransferToAgent Intent) in the main guide.
> **Purpose:** Complete walkthrough of how to route escalated contacts to the right specialist
> queue based on what the customer was asking about, and how to pass the full conversation
> summary to the human agent so the customer never has to repeat themselves.

---

## Table of Contents

1. [What This Guide Covers](#1-what-this-guide-covers)
2. [How It All Fits Together](#2-how-it-all-fits-together)
3. [Component Overview](#3-component-overview)
4. [Part A — Update the Escalate Tool in the AI Agent](#part-a--update-the-escalate-tool-in-the-ai-agent)
5. [Part B — DynamoDB Routing Table](#part-b--dynamodb-routing-table)
6. [Part C — Routing Lambda Function](#part-c--routing-lambda-function)
7. [Part D — Contact Flow Changes](#part-d--contact-flow-changes)
8. [Part E — Passing the Summary to the Human Agent](#part-e--passing-the-summary-to-the-human-agent)
   - [E.1 Voice Channel — Agent Whisper Flow](#e1-voice-channel--agent-whisper-flow)
   - [E.2 Chat Channel — System Message Injection](#e2-chat-channel--system-message-injection)
   - [E.3 CCP Screen Pop — Set Event Flow Block](#e3-ccp-screen-pop--set-event-flow-block)
   - [E.4 CCP Contact Attributes Tab (Zero Config Fallback)](#e4-ccp-contact-attributes-tab-zero-config-fallback)
9. [Complete Flow Diagram (All Parts Together)](#complete-flow-diagram-all-parts-together)
10. [What the Agent Experiences](#what-the-agent-experiences)
11. [Troubleshooting](#troubleshooting)
12. [IAM Permissions Checklist](#iam-permissions-checklist)

---

## 1. What This Guide Covers

When ARIA cannot resolve a customer's request and escalates to a human agent, two things need
to happen that a basic transfer does not do:

1. **The right queue** must be chosen automatically based on what the customer was discussing —
   a customer asking about their mortgage should reach the Mortgage Advisors team, not the
   general queue. Agents in each queue hold a specific **proficiency** level for that topic.

2. **The conversation summary** must be passed to the agent the moment they answer, so they
   already know the customer's name, topic, what was attempted, and why the transfer happened —
   without the customer having to repeat any of it.

This guide covers both, end to end, for both voice and chat channels.

---

## 2. How It All Fits Together

Here is the journey of a single escalated contact from start to finish:

```
Customer talks to ARIA (AI agent)
           │
           │  Customer says "I'd like to speak to someone"
           ▼
ARIA fills in the Escalate tool fields:
  - topicCategory   = "mortgage"
  - escalationReason = "customer_requested"
  - customerIntent  = "discuss overpayment options"
  - conversationSummary = "Customer asked about 10% overpayment
                           allowance on their 5-year fixed rate."
           │
           ▼
Contact flow receives control (Default output of GCI block)
           │
           ▼
Check Contact Attributes confirms Tool = "Escalate"
           │
           ▼
Set Contact Attributes copies the 4 fields from
Lex session attributes → contact attributes
           │
           ▼
Lambda looks up "mortgage" in DynamoDB
→ returns queueId for Mortgage Advisors queue
           │
           ▼
Set Working Queue (dynamic) uses the returned queueId
           │
           ▼
Set Contact Attributes saves summary as ariaSummary,
ariaTopicCategory etc. for the agent to read
           │
           ▼
Set Event Flow (CCP screen pop configured)
           │
           ▼
Transfer to Queue → Mortgage Advisors queue
           │
           ▼  (voice)                    (chat)
Agent Whisper Flow plays        System message injected into
summary privately to agent      chat transcript before agent connects
before customer can hear
           │                              │
           └──────────────┬───────────────┘
                          ▼
              Agent answers already knowing:
              - Customer name & topic
              - What ARIA tried
              - Why they were transferred
              - No need to ask customer to repeat themselves
```

---

## 3. Component Overview

| Component | What it does | Where it lives |
|---|---|---|
| Escalate tool input schema | Forces ARIA to capture topic + summary before handing off | AI Agent Designer |
| DynamoDB table `aria-routing-config` | Maps each topic to a queue ID | AWS DynamoDB |
| Lambda `aria-routing-lookup` | Reads topic from contact, queries DynamoDB, returns queue ID | AWS Lambda |
| Set Contact Attributes (x2) | Bridges Lex session attrs → contact attrs; stores summary | Contact Flow |
| Invoke Lambda block | Calls the routing Lambda | Contact Flow |
| Set Working Queue (dynamic) | Sets the correct queue from Lambda result | Contact Flow |
| Set Event Flow block | Configures CCP screen pop for the agent | Contact Flow |
| Agent Whisper Flow | Plays spoken summary privately to agent before connection (voice) | Connect Flow |
| Summary injection Lambda | Injects summary as SYSTEM message in chat transcript (chat) | AWS Lambda |

---

## Part A — Update the Escalate Tool in the AI Agent

> **Concept — What is the Escalate tool?**
>
> When ARIA decides a customer needs a human agent, it calls its built-in **Escalate**
> Return to Control tool. "Calling" this tool ends the AI conversation and hands control
> back to your contact flow. By adding an **input schema** to the Escalate tool, you force
> ARIA to fill in structured fields — like a structured handoff form — every single time it
> escalates. Without this, your contact flow has no idea what the customer was discussing.

### Steps

1. Amazon Connect console → **AI Agent Designer** → **AI Agents**
2. Open your **ARIA-Banking-Orchestration-Agent**
3. Under **Tools**, find **Escalate** → click **Edit**
4. Click **Edit input schema** and replace with:

```json
{
  "type": "object",
  "properties": {
    "topicCategory": {
      "type": "string",
      "description": "The primary banking topic the customer was enquiring about",
      "enum": [
        "current_account",
        "savings_account",
        "mortgage",
        "credit_card",
        "debit_card",
        "fraud_security",
        "complaint",
        "general_banking"
      ]
    },
    "escalationReason": {
      "type": "string",
      "description": "Why ARIA is escalating to a human agent",
      "enum": [
        "customer_requested",
        "complex_request",
        "complaint",
        "technical_issue",
        "out_of_scope"
      ]
    },
    "conversationSummary": {
      "type": "string",
      "description": "One or two sentence summary of the conversation for the human agent to read when they pick up",
      "maxLength": 500
    },
    "customerIntent": {
      "type": "string",
      "description": "Brief phrase describing what the customer was trying to accomplish"
    }
  },
  "required": ["topicCategory", "escalationReason", "customerIntent"]
}
```

5. In the **Instructions** field for the Escalate tool, paste:

```
When escalating to a human agent, always populate the input fields as follows:

- topicCategory: choose the closest match to the subject of the customer's enquiry.
  For example: "mortgage" if they asked about their mortgage balance or overpayments,
  "fraud_security" if they reported a suspicious transaction, "complaint" if they
  expressed dissatisfaction.

- escalationReason: set to "customer_requested" if they asked for a human agent.
  Set to "complaint" if they used complaint language or expressed frustration.
  Set to "complex_request" if the issue is beyond your available tools.
  Set to "technical_issue" if a tool returned repeated errors.

- customerIntent: a brief phrase, e.g. "wants to discuss mortgage overpayment options"
  or "reporting suspected card fraud" or "query about ISA interest rate".

- conversationSummary: one or two sentences summarising what was discussed and what the
  customer needs, so the human agent does not have to ask the customer to repeat
  themselves. Include any relevant context (e.g. account type, amount mentioned).
```

6. **Save** → **Publish** the agent

> ✅ After publishing, every time ARIA escalates, Connect automatically stores all four
> fields as **Amazon Lex session attributes** using the field names exactly as defined in
> the schema. Your contact flow reads them in the next block.

---

## Part B — DynamoDB Routing Table

> **Concept — Why DynamoDB?**
>
> Your Connect instance has multiple queues — each linked to agents who hold a specific
> proficiency in a topic (Mortgage, Fraud, Cards, etc.). Instead of hard-coding queue IDs
> into your contact flow (which means editing the flow every time a queue changes), you
> store the mapping in a DynamoDB table. The Lambda function looks up the right queue at
> runtime. Change the table, never touch the flow.

### Create the Table

1. AWS Console → **DynamoDB** → **Create table**
2. **Table name**: `aria-routing-config`
3. **Partition key**: `topicCategory` (type: **String**)
4. Leave all other settings as default → **Create table**

### Find Your Queue IDs

> ⚠️ The **Set Working Queue** block in Connect requires the **Queue UUID**, not the queue
> name or ARN. Find it like this:
>
> Connect console → **Routing** → **Queues** → click a queue → look at the browser URL bar.
> The UUID is the last segment after `/queue/`. Example:
> `https://...console.aws.amazon.com/connect/.../queues/queue/aaaa-bbbb-cccc-dddd-1111111111`
> → Queue ID = `aaaa-bbbb-cccc-dddd-1111111111`

### Add Routing Rows

Click **Explore table items** → **Create item** → switch to **JSON view** and add one row
per topic. Replace every `YOUR-...-UUID` with the actual queue UUID from your Connect instance.

```json
{ "topicCategory": "mortgage",        "queueId": "YOUR-MORTGAGE-QUEUE-UUID",    "queueName": "Mortgage Advisors",  "proficiencyLevel": "3", "proficiencySkill": "Mortgage"    }
{ "topicCategory": "credit_card",     "queueId": "YOUR-CARDS-QUEUE-UUID",       "queueName": "Cards Team",         "proficiencyLevel": "2", "proficiencySkill": "Cards"       }
{ "topicCategory": "debit_card",      "queueId": "YOUR-CARDS-QUEUE-UUID",       "queueName": "Cards Team",         "proficiencyLevel": "2", "proficiencySkill": "Cards"       }
{ "topicCategory": "fraud_security",  "queueId": "YOUR-FRAUD-QUEUE-UUID",       "queueName": "Fraud Team",         "proficiencyLevel": "4", "proficiencySkill": "Fraud"       }
{ "topicCategory": "complaint",       "queueId": "YOUR-COMPLAINTS-QUEUE-UUID",  "queueName": "Senior Advisors",    "proficiencyLevel": "3", "proficiencySkill": "Complaints"  }
{ "topicCategory": "current_account", "queueId": "YOUR-RETAIL-QUEUE-UUID",      "queueName": "Retail Banking",     "proficiencyLevel": "1", "proficiencySkill": "Retail"      }
{ "topicCategory": "savings_account", "queueId": "YOUR-RETAIL-QUEUE-UUID",      "queueName": "Retail Banking",     "proficiencyLevel": "1", "proficiencySkill": "Retail"      }
{ "topicCategory": "general_banking", "queueId": "YOUR-DEFAULT-QUEUE-UUID",     "queueName": "General Queue",      "proficiencyLevel": "1", "proficiencySkill": "General"     }
```

> The `general_banking` row is your **fallback**. If ARIA cannot determine the topic, the
> Lambda falls back to this row. Always keep it — even if you only have one queue.

---

## Part C — Routing Lambda Function

> **Concept — What does this Lambda do?**
>
> It receives the contact details from Connect (including the `topicCategory` contact
> attribute set earlier in the flow), queries the DynamoDB table, and returns the matching
> Queue ID. Connect uses that Queue ID in the **Set Working Queue** block immediately after.

### Create the Lambda

1. AWS Console → **Lambda** → **Create function**
2. **Name**: `aria-routing-lookup`
3. **Runtime**: Python 3.12
4. **Execution role**: create a new role, then add the DynamoDB permission below

### IAM Permission (add to Lambda execution role)

```json
{
  "Effect": "Allow",
  "Action": ["dynamodb:GetItem"],
  "Resource": "arn:aws:dynamodb:eu-west-2:YOUR-ACCOUNT-ID:table/aria-routing-config"
}
```

### Lambda Code

Paste this into the function editor and click **Deploy**:

```python
import boto3
import os

dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ.get('ROUTING_TABLE', 'aria-routing-config')
DEFAULT_TOPIC = 'general_banking'


def handler(event, context):
    """
    Called by Amazon Connect after ARIA escalates.

    Input:  event.Details.ContactData.Attributes contains the contact attributes
            set by the Set Contact Attributes block in the flow — including
            topicCategory, conversationSummary, customerIntent, escalationReason.

    Output: Flat dict of strings returned to Connect under the External namespace.
            Connect reads $.External.queueId to set the working queue.
    """
    attrs = (
        event.get('Details', {})
             .get('ContactData', {})
             .get('Attributes', {})
    )
    topic = attrs.get('topicCategory', DEFAULT_TOPIC).strip().lower()

    print(f"Routing lookup for topic: {topic}")

    table = dynamodb.Table(TABLE_NAME)

    # Try the specific topic first
    item = _get_item(table, topic)

    # Fall back to general_banking if no row found
    if not item:
        print(f"No config for '{topic}', falling back to '{DEFAULT_TOPIC}'")
        item = _get_item(table, DEFAULT_TOPIC)

    if not item:
        print("ERROR: No fallback row in DynamoDB. Returning error flag.")
        return {'routingError': 'true'}

    return {
        'queueId':            item.get('queueId', ''),
        'queueName':          item.get('queueName', 'General Queue'),
        'proficiencyLevel':   str(item.get('proficiencyLevel', '1')),
        'proficiencySkill':   item.get('proficiencySkill', 'General'),
        'topicCategory':      topic,
        # Pass summary through so the flow can store it as a contact attribute
        'conversationSummary': attrs.get('conversationSummary', ''),
        'customerIntent':      attrs.get('customerIntent', ''),
        'escalationReason':    attrs.get('escalationReason', ''),
    }


def _get_item(table, topic):
    response = table.get_item(Key={'topicCategory': topic})
    return response.get('Item')
```

> ⚠️ **Important:** Every value in the returned dict must be a **string**. Connect reads
> Lambda results in STRING_MAP mode and cannot parse nested objects or numbers.

### Add Lambda to Connect

1. Amazon Connect console → your instance → **AWS Lambda** (left menu)
2. **Add Lambda function** → select `aria-routing-lookup` → **Add Lambda**

---

## Part D — Contact Flow Changes

> **Where to make these changes:**
> Open your **Inbound Contact Flow** in the Flow Designer. Find the **Check Contact
> Attributes** block that tests `Tool = Escalate` (added in Step D.6a of the main guide).
> Everything below connects after the `Escalate` condition output of that block.

### Full Block Chain

```
[Check Contact Attributes: Tool = "Escalate"]
         │
         ▼
[D1] Set Contact Attributes        copies 4 fields from Lex session → contact attrs
         │
         ▼
[D2] Invoke Lambda                 aria-routing-lookup → DynamoDB → returns queueId
         │              │
       Success        Error
         │              └──────→ [Set Working Queue: DefaultQueue fallback]
         ▼                                │
[D3] Set Working Queue (dynamic)          ▼
         │                       [Transfer to Queue]  ← error/fallback path
         ▼
[D4] Set Contact Attributes        stores summary + topic for agent screen pop
         │
         ▼
[D5] Set Event Flow                configures CCP screen pop (optional)
         │
         ▼
[D6] Invoke Lambda (chat only)     injects SYSTEM message into chat transcript
   (use Check channel branch to skip on voice)
         │
         ▼
[D7] Transfer to Queue             ← happy path
```

---

### Block D1 — Set Contact Attributes (Lex → Contact)

> **Why this block is needed:**
> ARIA's output fields (`topicCategory` etc.) are stored by Connect as *Lex session
> attributes*. Lambda functions can only read *contact attributes*. This block copies the
> four Lex session attributes into contact attributes so the Lambda in the next block can
> read them.

Configure each row as **Set dynamically**:

| Destination key (User Defined) | Source Namespace | Source Key |
|---|---|---|
| `topicCategory` | Lex – Session attributes | `topicCategory` |
| `escalationReason` | Lex – Session attributes | `escalationReason` |
| `customerIntent` | Lex – Session attributes | `customerIntent` |
| `conversationSummary` | Lex – Session attributes | `conversationSummary` |

---

### Block D2 — Invoke Lambda

| Field | Value |
|---|---|
| Function | `aria-routing-lookup` |
| Execution mode | Synchronous |
| Timeout | 5 seconds |
| Response validation | STRING_MAP |

- **Success** branch → connect to Block D3 (Set Working Queue)
- **Error** branch → connect to a **Set Working Queue** block pre-set to your default
  fallback queue, then to **Transfer to Queue**

---

### Block D3 — Set Working Queue (dynamic)

| Field | Value |
|---|---|
| By queue | Set dynamically |
| Namespace | External |
| Key | `queueId` |

> **What is "External"?** When a Lambda returns values to Connect, they are accessible
> under the **External** namespace. `$.External.queueId` refers to the `queueId` key your
> Lambda returned from DynamoDB.
>
> ⚠️ This block needs the Queue **UUID**, not the name or ARN. Your Lambda returns the
> UUID from the DynamoDB `queueId` column — which you populated with the UUID from the
> queue URL when setting up the table.

---

### Block D4 — Set Contact Attributes (Agent Screen Pop Store)

Stores the summary and routing context so it is available to downstream agent UI flows
and is recorded in the Contact Trace Record (CTR) for reporting.

| Destination key (User Defined) | Source Namespace | Source Key |
|---|---|---|
| `ariaSummary` | External | `conversationSummary` |
| `ariaTopicCategory` | External | `topicCategory` |
| `ariaEscalationReason` | External | `escalationReason` |
| `ariaCustomerIntent` | External | `customerIntent` |
| `ariaQueueName` | External | `queueName` |

---

### Block D5 — Set Event Flow (CCP Screen Pop)

Add a **Set event flow** block after Block D4.

| Field | Value |
|---|---|
| Event | Default flow for agent UI |
| Flow | Select or create an agent UI flow (see Part E.3) |

This configures what appears in the agent's CCP sidebar when they accept the contact.

---

### Block D6 — Chat Summary Injection (Chat Channel Only)

> Skip this block for voice. To run it only on chat, add a **Check contact attributes**
> block before it that branches on `$.Channel = CHAT`.

Add an **Invoke Lambda** block pointing to your summary injection Lambda (see Part E.2).

| Field | Value |
|---|---|
| Function | `aria-chat-summary-injector` |
| Execution mode | Synchronous |
| Timeout | 5 seconds |
| Response validation | STRING_MAP |

Both the **Success** and **Error** branches connect to Block D7 (Transfer to Queue) — if
the injection fails, the transfer still proceeds.

---

## Part E — Passing the Summary to the Human Agent

The contact attributes `ariaSummary`, `ariaTopicCategory`, `ariaCustomerIntent`, and
`ariaEscalationReason` are now attached to the contact. The sections below describe how
to surface them to the agent at the right moment, by channel.

---

### E.1 Voice Channel — Agent Whisper Flow

> **What is an Agent Whisper Flow?**
> A special Connect flow type that plays **only to the agent**, privately, before the
> customer can hear them. The agent hears a spoken summary the moment they answer the
> call. The customer hears ringing and is unaware. This is the cleanest voice handoff
> mechanism — the agent knows the full context before they say a single word.

#### Create the Whisper Flow

1. Connect console → **Routing → Flows → Create flow**
2. Change the flow type (dropdown, top right) to **Agent whisper flow**
3. Name it: `ARIA-Agent-Handoff-Whisper`
4. Drag a **Play prompt** block onto the canvas and connect it to **Entry**
5. In the Play prompt block:
   - Choose **Text-to-speech or chat text**
   - Select **Set dynamically**
   - Enter the following (Connect reads `$.Attributes.X` for contact attributes):

```
ARIA Handoff Summary.
Topic: $.Attributes.ariaTopicCategory.
Customer intent: $.Attributes.ariaCustomerIntent.
Summary: $.Attributes.ariaSummary.
Escalation reason: $.Attributes.ariaEscalationReason.
```

6. Connect Play prompt → **End flow / Resume**
7. **Save** → **Publish**

#### Link the Whisper Flow to Each Queue

1. Connect console → **Routing → Queues**
2. Open each specialist queue (Mortgage Advisors, Fraud Team, Cards Team, etc.)
3. Scroll to **Agent whisper flow**
4. Select `ARIA-Agent-Handoff-Whisper`
5. **Save**

> You can use the same whisper flow for all queues — it reads the attributes dynamically
> so the correct summary is always played regardless of which queue the agent is in.

#### What the Agent Hears

When the agent answers the call, before the customer hears them, they hear:

```
ARIA Handoff Summary.
Topic: mortgage.
Customer intent: discuss overpayment options on fixed rate.
Summary: Customer asked about the 10% annual overpayment
allowance on their 5-year fixed-rate mortgage. They are
within the allowance limit. Customer requested human agent.
Escalation reason: customer requested.
```

The customer then hears the line open and the agent says: *"Hello, I understand you'd
like to discuss your mortgage overpayment options — let me help you with that."*

---

### E.2 Chat Channel — System Message Injection

> **What is a SYSTEM message?**
> In Amazon Connect chat, **SYSTEM** messages are visible only to the agent in their CCP.
> The customer never sees them. By injecting a SYSTEM message before the agent connects,
> the summary appears at the top of the agent's chat transcript before they type their
> first message.

#### How It Works

A Lambda function calls the Amazon Connect **SendMessage** API on behalf of the SYSTEM
participant, injecting a formatted summary message into the chat session.

#### Create the Lambda

1. AWS Console → Lambda → **Create function**
2. **Name**: `aria-chat-summary-injector`
3. **Runtime**: Python 3.12

**IAM permissions needed** (add to execution role):

```json
{
  "Effect": "Allow",
  "Action": ["connect:SendMessage"],
  "Resource": "arn:aws:connect:eu-west-2:YOUR-ACCOUNT-ID:instance/YOUR-INSTANCE-ID/*"
}
```

**Lambda code:**

```python
import boto3
import os

connect = boto3.client('connect')
INSTANCE_ID = os.environ['CONNECT_INSTANCE_ID']


def handler(event, context):
    """
    Injects an ARIA handoff summary as a SYSTEM message into the chat transcript.
    Only visible to the agent — the customer never sees SYSTEM messages.
    """
    contact_data = event.get('Details', {}).get('ContactData', {})
    attrs = contact_data.get('Attributes', {})
    contact_id = contact_data.get('ContactId', '')

    topic    = attrs.get('ariaTopicCategory', 'general_banking')
    intent   = attrs.get('ariaCustomerIntent', '')
    summary  = attrs.get('ariaSummary', '')
    reason   = attrs.get('ariaEscalationReason', '')
    queue    = attrs.get('ariaQueueName', '')

    message = (
        f"──── ARIA HANDOFF SUMMARY ────\n"
        f"Routing to: {queue}\n"
        f"Topic: {topic}\n"
        f"Customer intent: {intent}\n"
        f"Escalation reason: {reason}\n"
        f"Summary: {summary}\n"
        f"─────────────────────────────"
    )

    try:
        connect.send_message(
            InstanceId=INSTANCE_ID,
            ContactId=contact_id,
            ContentType='text/plain',
            Content=message,
        )
        return {'status': 'ok'}
    except Exception as e:
        print(f"Failed to inject summary message: {e}")
        # Non-fatal — the transfer still proceeds
        return {'status': 'error', 'message': str(e)}
```

**Environment variable to set on the Lambda:**

| Key | Value |
|---|---|
| `CONNECT_INSTANCE_ID` | Your Connect instance ID (from Connect console → Instance → Overview) |

**Add to Connect:**
Connect console → your instance → **AWS Lambda** → **Add Lambda function** → select
`aria-chat-summary-injector`

#### What the Agent Sees

When they open the chat, before typing their first message:

```
──── ARIA HANDOFF SUMMARY ────
Routing to: Mortgage Advisors
Topic: mortgage
Customer intent: discuss overpayment options on fixed rate
Escalation reason: customer_requested
Summary: Customer asked about the 10% annual overpayment
allowance on their 5-year fixed-rate mortgage. They are
within the allowance limit. Customer requested human agent.
─────────────────────────────

[Customer] Hi, I'd like to talk to someone about my mortgage...
[ARIA] Of course! I can see you'd like to discuss your...
```

---

### E.3 CCP Screen Pop — Set Event Flow Block

> **What is the CCP (Contact Control Panel)?**
> The interface agents use to accept calls and chats. When an agent accepts a contact, you
> can configure a **screen pop** — a panel in the CCP sidebar that displays contact
> attributes. This works for both voice and chat.

#### Create the Agent Event Flow

1. Connect console → **Routing → Flows → Create flow**
2. Change flow type to **Default agent UI**
3. Name it: `ARIA-Agent-Screen-Pop`
4. Add a **Set contact attributes** block that references the `aria*` attributes to display
5. **Save** → **Publish**

#### Link It in the Contact Flow

In your inbound contact flow, add a **Set event flow** block (Block D5 above):

| Field | Value |
|---|---|
| Event | Default flow for agent UI |
| Flow | `ARIA-Agent-Screen-Pop` |

#### What the Agent Sees in the CCP

When they accept the contact, a panel appears in their CCP sidebar:

```
┌──────────────────────────────────────┐
│  ARIA Handoff                        │
│  Topic:   Mortgage                   │
│  Intent:  Discuss overpayment opts   │
│  Queue:   Mortgage Advisors          │
│  Summary: Customer asked about the   │
│  10% overpayment allowance on their  │
│  5-year fixed rate mortgage...       │
└──────────────────────────────────────┘
```

---

### E.4 CCP Contact Attributes Tab (Zero Config Fallback)

Every contact attribute set in Block D4 is **automatically visible** in the agent's CCP
under the **Contact attributes** tab — no extra configuration needed. This is the baseline
fallback if the whisper flow, system message, or screen pop are not yet configured.

The agent clicks the **Contact attributes** tab in their CCP and sees:

| Attribute | Value |
|---|---|
| `ariaSummary` | Customer asked about 10% overpayment allowance... |
| `ariaTopicCategory` | mortgage |
| `ariaEscalationReason` | customer_requested |
| `ariaCustomerIntent` | discuss overpayment options |
| `ariaQueueName` | Mortgage Advisors |

> Downside: agents must know to click the tab and often won't. Use this as your baseline,
> not your primary mechanism.

---

## Complete Flow Diagram (All Parts Together)

```
[Get Customer Input — Lex / AMAZON.QinConnectIntent]
   │
   └── Default output
          │
          ▼
   [Check Contact Attributes]
      Lex → Session attributes → Tool
          │
          ├── = "Complete" ─────────────────────────────→ [Disconnect]
          │
          └── = "Escalate"
                 │
                 ▼
          [D1: Set Contact Attributes]
          Copies from Lex session → contact attrs:
          topicCategory, escalationReason,
          customerIntent, conversationSummary
                 │
                 ▼
          [D2: Invoke Lambda: aria-routing-lookup]
          Reads topicCategory → DynamoDB → returns queueId
                 │              │
               Success        Error
                 │              └──→ [Set Working Queue: default] → [Transfer to Queue]
                 ▼
          [D3: Set Working Queue]
          Dynamic: $.External.queueId
                 │
                 ▼
          [D4: Set Contact Attributes]
          Stores ariaSummary, ariaTopicCategory,
          ariaEscalationReason, ariaCustomerIntent,
          ariaQueueName for agent screen pop
                 │
                 ▼
          [D5: Set Event Flow]
          Configures CCP screen pop (agent UI flow)
                 │
                 ▼
          [Check channel: CHAT?]
          ├── Yes → [D6: Invoke Lambda: aria-chat-summary-injector]
          │         Injects SYSTEM message into chat transcript
          │         (both Success and Error → Transfer to Queue)
          └── No  ──────────────────────────────────────┐
                                                         ▼
                                                  [D7: Transfer to Queue]
                                                         │
                                          ┌──────────────┴──────────────┐
                                        Voice                         Chat
                                          │                              │
                                          ▼                              ▼
                               [Agent Whisper Flow]           [SYSTEM message already
                               Plays spoken summary           in transcript — agent
                               privately to agent             reads it on connect]
                               before customer hears
                                          │                              │
                                          └──────────────┬───────────────┘
                                                         ▼
                                              Agent answers with full context
                                              Customer does not repeat themselves
```

---

## What the Agent Experiences

### Voice Agent

1. Phone rings in their CCP
2. Agent clicks **Accept**
3. Customer hears ringing — cannot hear the agent yet
4. Agent hears privately (whisper flow):
   *"ARIA Handoff Summary. Topic: mortgage. Customer intent: discuss overpayment options
   on fixed rate. Summary: Customer asked about the 10% annual overpayment allowance.
   Escalation reason: customer requested."*
5. Line opens to customer
6. Agent says: *"Hello, I understand you'd like to discuss your mortgage overpayment
   options — I can see the details ARIA passed over. Let me pull up your account."*

### Chat Agent

1. Chat notification appears in their CCP
2. Agent clicks **Accept**
3. Chat transcript opens. At the top they see:
   ```
   ──── ARIA HANDOFF SUMMARY ────
   Routing to: Mortgage Advisors
   Topic: mortgage
   Customer intent: discuss overpayment options on fixed rate
   Escalation reason: customer_requested
   Summary: Customer asked about the 10% annual overpayment
   allowance on their 5-year fixed-rate mortgage.
   ─────────────────────────────
   [Customer] Hi, I'd like to talk to someone...
   ```
4. Agent types: *"Hi! I can see you'd like to discuss your mortgage overpayment options.
   I've already got the context from ARIA — no need to repeat yourself."*

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| Customer always goes to the default/general queue | `topicCategory` is empty or not being set by ARIA | Open CloudWatch Logs for the contact — check whether the Lex session attribute `Tool` contains the `topicCategory` field alongside the tool name. If missing, verify the Escalate tool input schema is saved and the agent is Published |
| `Set Working Queue` block fails (Error branch fires) | Wrong value in `queueId` DynamoDB column | The `queueId` column must contain the 36-character Queue **UUID** (from the queue URL), not the queue name, ARN, or display name |
| Lambda returns empty / `routingError = true` | `general_banking` fallback row missing from DynamoDB | Ensure the `general_banking` row exists in `aria-routing-config`. This is the catch-all for any unrecognised topic |
| Agent whisper plays but says "null" or empty fields | Contact attributes not set before transfer | Verify Block D4 (Set Contact Attributes) is in the flow and executes before the Transfer to Queue block |
| Chat agent does not see the summary system message | `aria-chat-summary-injector` Lambda not added to Connect instance allow-list | Go to Connect console → instance → AWS Lambda → confirm the Lambda appears in the list |
| CCP screen pop does not appear | Set Event Flow block missing or agent UI flow not published | Confirm Block D5 is in the flow and the agent event flow it references is Published |
| Agent hears whisper but it is cut off | Whisper flow Play Prompt text too long | Shorten the `ariaSummary` text — keep it under 200 characters. Instruct ARIA in the Escalate tool instructions to keep summaries concise |
| No attributes visible in CTR | Block D4 not saving attributes | Check the Block D4 Set Contact Attributes configuration — ensure Namespace is `External` and the keys match the Lambda return values exactly (case-sensitive) |

---

## IAM Permissions Checklist

### `aria-routing-lookup` Lambda execution role

```json
{
  "Effect": "Allow",
  "Action": ["dynamodb:GetItem"],
  "Resource": "arn:aws:dynamodb:eu-west-2:ACCOUNT-ID:table/aria-routing-config"
}
```

### `aria-chat-summary-injector` Lambda execution role

```json
{
  "Effect": "Allow",
  "Action": ["connect:SendMessage"],
  "Resource": "arn:aws:connect:eu-west-2:ACCOUNT-ID:instance/INSTANCE-ID/*"
}
```

### Both Lambdas — base execution role (auto-created by AWS)

```json
{
  "Effect": "Allow",
  "Action": [
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
  ],
  "Resource": "arn:aws:logs:*:*:*"
}
```

---

*Part of the ARIA Meridian Bank AI Banking Assistant documentation suite.*
*Main guide: [aria-connect-voice-chat-novice-guide.md](./aria-connect-voice-chat-novice-guide.md)*
