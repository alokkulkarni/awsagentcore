# ARIA + Amazon Connect: Voice & Chat Conversational AI — Complete Novice Guide

> **Who this guide is for**: Someone who has never configured Amazon Connect before and wants a complete,
> step-by-step walkthrough for setting up voice and chat using the ARIA Connect AI Agent.
>
> **What you will have at the end**:
> - A phone number in Amazon Connect that callers can dial and speak to ARIA
> - A chat endpoint that visitors can type to and get ARIA responses
> - Both channels using the ARIA Orchestration AI Agent with your custom prompt and tools
> - Contact Lens real-time speech analytics enabled (required for voice)
> - Session context injected (customer ID, auth status, locale, etc.)
>
> **Official AWS documentation references** are linked throughout. Always consult the latest version at
> [https://docs.aws.amazon.com/connect/latest/adminguide/](https://docs.aws.amazon.com/connect/latest/adminguide/).

---

## Table of Contents

1. [Concepts You Must Understand First](#1-concepts-you-must-understand-first)
2. [Prerequisites](#2-prerequisites)
3. [Architecture: What You Are Building](#3-architecture-what-you-are-building)
4. [Part A — Instance & Foundation Setup](#part-a--instance--foundation-setup)
5. [Part B — Enable Contact Lens (Required for Voice AI)](#part-b--enable-contact-lens-required-for-voice-ai)
6. [Part C — Claim a Phone Number](#part-c--claim-a-phone-number)
7. [Part D — Create the ARIA Voice Inbound Flow (Block by Block)](#part-d--create-the-aria-voice-inbound-flow-block-by-block)
8. [Part E — Create the ARIA Chat Flow](#part-e--create-the-aria-chat-flow)
9. [Part F — Connect a Phone Number to the Voice Flow](#part-f--connect-a-phone-number-to-the-voice-flow)
10. [Part G — Test Voice (Call the Number)](#part-g--test-voice-call-the-number)
11. [Part H — Set Up Chat Widget](#part-h--set-up-chat-widget)
12. [Part I — Test Chat](#part-i--test-chat)
13. [Nova Sonic: What It Is and How to Use It with Connect](#nova-sonic-what-it-is-and-how-to-use-it-with-connect)
    - [Three Paths to Voice AI](#three-paths-to-voice-ai-in-amazon-connect)
    - [Step C.1 — Check Nova Sonic Availability](#step-c1--check-nova-sonic-availability-in-eu-west-2)
    - [Step C.2 — Enable Unlimited AI Pricing](#step-c2--enable-unlimited-ai-pricing-on-your-instance)
    - [Step C.3 — Enable Bedrock Model Access](#step-c3--enable-amazon-bedrock-model-access-for-nova-sonic)
    - [Step C.4 — Update the ARIA AI Prompt](#step-c4--update-the-aria-ai-prompt-to-use-nova-sonic)
    - [Step C.5 — Verify Prompt Model for eu-west-2](#step-c5--verify-the-aria-ai-prompt-model-for-eu-west-2)
    - [Step C.6 — Configure Voice Flow for Nova Sonic](#step-c6--configure-the-voice-flow-for-nova-sonic-path-c)
    - [Step C.7 — Verify Nova Sonic is Active](#step-c7--verify-nova-sonic-is-active-on-a-test-call)
    - [Step C.8 — Tune the Nova Sonic Experience](#step-c8--tune-the-nova-sonic-experience)
    - [Step C.9 — Configure Barge-In](#step-c9--configure-barge-in-interruption-handling)
    - [Step C.10 — Multilingual Support](#step-c10--enable-multilingual-support-with-nova-sonic)
    - [Step C.11 — Monitor Voice Quality](#step-c11--monitor-nova-sonic-voice-quality-in-contact-lens)
    - [Nova Sonic vs Polly Comparison](#nova-sonic-vs-polly-feature-comparison-for-aria)
    - [Choosing Your Path](#choosing-your-path-decision-guide)
15. [Understanding Every Block You Used](#understanding-every-block-you-used)
16. [Troubleshooting](#troubleshooting)
17. [Appendix A — Quick Reference: Contact Attributes Injected](#appendix-a--quick-reference-contact-attributes-injected)
18. [Appendix B — IAM Permissions Checklist](#appendix-b--iam-permissions-checklist)

---

## 1. Concepts You Must Understand First

Before you touch the console, read this section so the instructions make sense.

### What is Amazon Connect?

Amazon Connect is AWS's cloud contact centre service. Think of it as a telephone exchange and chat platform
that you configure entirely in a web browser — no hardware, no PABX.

> Official overview: [What is Amazon Connect?](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)

### What is a Contact Flow?

A **contact flow** is a visual programme (a drag-and-drop flowchart) that decides what happens to a caller or
chat user from the moment they connect until the moment they hang up. Each box in the flowchart is called a
**block** or **flow block**. You wire blocks together with arrows.

> Official docs: [Create and manage contact flows](https://docs.aws.amazon.com/connect/latest/adminguide/create-contact-flow.html)

There are several **types** of contact flow. For this guide you use:

| Flow type | When it runs |
|---|---|
| **Inbound flow** | The moment a call arrives or a chat session starts |
| **Customer queue flow** | While the customer waits in queue (hold music) |

### What is a Connect AI Agent (ARIA)?

A Connect AI Agent is an **Orchestration** type agent you configured in the AI Agent Designer. It has:
- An **AI Prompt** (the ARIA system prompt you authored)
- An **AI Guardrail** (safety filters)
- **Tools** (Lambda functions connected to your MCP gateway)

When a contact flow includes a **Connect assistant** block, Connect creates an AI session for that contact
and the AI Agent starts handling the conversation.

> Official docs: [Create AI agents](https://docs.aws.amazon.com/connect/latest/adminguide/create-ai-agents.html)

### What is Contact Lens?

Contact Lens is Amazon Connect's analytics layer. For voice contacts it performs **real-time speech analytics**
— transcribing what the customer says live, detecting sentiment, and enabling ARIA to "hear" the customer.

**Contact Lens real-time is required for voice AI agents.** Without it, the Connect AI Agent cannot receive
the customer's spoken words. For chat, Contact Lens is optional.

> Official docs: [Analyze conversations using conversational analytics](https://docs.aws.amazon.com/connect/latest/adminguide/analyze-conversations.html)

### What is the Session Injector?

The session injector is a Lambda function you deploy (`scripts/lambdas/session_injector.py`). It runs
**after** the Connect assistant block creates an AI session, and injects customer context (name, products,
auth status, etc.) into that session so ARIA can personalise its responses.

> Official docs: [Add customer data to an AI agent session](https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-session.html)

### The Rule of Blocks

Every block has:
- An **input connection point** (top or left) — what wires connect *to* this block
- One or more **output branches** (Success, Error, Timeout, etc.) — what wires connect *from* this block

Always wire every output branch to something. Unconnected branches cause calls to drop silently.

---

## 2. Prerequisites

Complete all of these before starting. Each has a ✅ checklist item.

| # | Item | Where to get it |
|---|---|---|
| 1 | AWS account `395402194296` with admin or Connect-full-access IAM role | AWS console |
| 2 | ARIA Connect AI Agent **published** (not just saved) | `instance.my.connect.aws` → AI Agent Designer |
| 3 | ARIA AI Prompt **published version** selected in the agent | AI Agent Designer → Prompts |
| 4 | ARIA AI Guardrail applied to the agent | AI Agent Designer → Guardrails |
| 5 | `session_injector` Lambda deployed in `eu-west-2` | `scripts/lambdas/session_injector.py` |
| 6 | Session injector Lambda added to the Connect instance allow-list | Connect → Instance settings → Flows → Add Lambda |
| 7 | Contact Lens enabled on the Connect instance | Connect console → Instance → Analytics → Enable Contact Lens |
| 8 | The ARIA assistant (Q Connect assistant) ARN noted down | Connect console → AI Agent Designer → copy ARN |

### How to check the ARIA agent is published

1. Go to `https://<instance-name>.my.connect.aws/`
2. Left menu → **AI Agent Designer** → **AI Agents**
3. Find your ARIA Orchestration agent
4. The **Status** column must show **Published**. If it shows **Draft**, click the agent → **Publish**.

---

## 3. Architecture: What You Are Building

```
┌──────────────────────────────────────────────────────────────┐
│                    CUSTOMER CHANNELS                         │
│                                                              │
│  Phone Call (PSTN)            Chat (Web / Mobile)           │
│       │                              │                       │
└───────┼──────────────────────────────┼───────────────────────┘
        │                              │
        ▼                              ▼
┌───────────────────────────────────────────────────────────────┐
│                  AMAZON CONNECT INSTANCE                      │
│                                                               │
│  ┌─────────────────────┐   ┌──────────────────────┐          │
│  │  ARIA Voice Inbound │   │  ARIA Chat Inbound   │          │
│  │      Flow           │   │       Flow           │          │
│  │                     │   │                      │          │
│  │ [Set Logging]       │   │ [Set Logging]        │          │
│  │ [Set Voice]         │   │ [Set Contact Attrs]  │          │
│  │ [Set Contact Attrs] │   │ [Connect Assistant]  │          │
│  │ [Set Recording]  ◄──┤   │ [Lambda: Injector]   │          │
│  │ [Contact Lens]      │   │ [Set Working Queue]  │          │
│  │ [Connect Assistant] │   │ [Transfer to Queue]  │          │
│  │ [Lambda: Injector]  │   └──────────────────────┘          │
│  │ [Hours of Op Check] │                                      │
│  │ [Set Working Queue] │   ┌──────────────────────┐          │
│  │ [Transfer to Queue] │   │    ARIA AI Agent      │          │
│  └─────────────────────┘   │  (Orchestration Type) │          │
│                             │  - ARIA System Prompt │          │
│  ┌─────────────────────┐   │  - ARIA Guardrail     │          │
│  │  Contact Lens       │   │  - Banking Tools      │          │
│  │  Real-Time          │   └──────────────────────┘          │
│  │  Speech Analytics   │                                      │
│  └─────────────────────┘                                      │
└───────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌───────────────────────────────────────────────────────────────┐
│               SESSION INJECTOR LAMBDA (eu-west-2)             │
│  Reads: ContactId, customerId, authStatus from flow attrs     │
│  Writes: 12 session variables to Q Connect session            │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│              ARIA AgentCore MCP Gateway                       │
│  10 domain Lambdas: accounts, cards, balances, statements...  │
└───────────────────────────────────────────────────────────────┘
```

**Key insight**: The contact flow is the glue. It sets up everything before ARIA takes over the conversation.
Once the Connect AI Agent session is established, ARIA drives the entire conversation, calling tools as
needed, and only routes to a human agent if it determines escalation is required.

---

## Part A — Instance & Foundation Setup

> If your Amazon Connect instance already exists, skip to [Part B](#part-b--enable-contact-lens-required-for-voice-ai).

### Step A.1 — Create a Connect Instance

> Official docs: [Create an Amazon Connect instance](https://docs.aws.amazon.com/connect/latest/adminguide/amazon-connect-instances.html)

1. Go to [https://console.aws.amazon.com/connect/](https://console.aws.amazon.com/connect/)
2. Set your region (top right) to **Europe (London) eu-west-2**
3. Click **Add an instance** (or **Get started** if this is your first)

**Step A.1a — Identity management**
- Select **Store users within Amazon Connect**
- *(You can integrate with SAML or Active Directory later — keep it simple for now)*

**Step A.1b — Access URL**
- Enter a unique subdomain, e.g. `meridian-aria`
- This becomes your admin URL: `https://meridian-aria.my.connect.aws/`

**Step A.1c — Administrator**
- Enter a username (e.g. `admin`) and a secure password
- *(Write this down — you cannot recover it)*

**Step A.1d — Telephony options**
- Check **I want to make and accept calls with Amazon Connect** (for voice)
- Check **I want to make outbound calls with Amazon Connect** (for callbacks)

**Step A.1e — Data storage**
- Keep the defaults (S3 bucket for recordings, CloudWatch for logs)
- Click **Create instance**

Wait 2–3 minutes. You will see "Your instance has been created successfully."

### Step A.2 — Add the Session Injector Lambda to the Instance Allow-list

Amazon Connect can only call Lambda functions that you explicitly add to your instance. This is a security
boundary — the Lambda must be in the same region as Connect.

> Official docs: [Add a Lambda function to your Amazon Connect instance](https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html#add-lambda-function)

1. In the Connect console, click your instance alias
2. Left menu → **Flows**
3. Under **AWS Lambda**, click **Add Lambda Function**
4. From the dropdown, find and select your `session_injector` function (the one you deployed from `scripts/lambdas/session_injector.py`)
5. Click **Add Lambda function**

**Why this matters**: If you skip this step, the AWS Lambda function block in your contact flow will fail
with "Function not found" and the contact will drop to the error branch.

---

## Part B — Enable Contact Lens (Required for Voice AI)

Contact Lens is the analytics engine that provides real-time speech-to-text transcription. The Connect AI
Agent **cannot process voice** without it — the AI agent needs to read the live transcript of what the
customer is saying.

> Official docs: [Enable Contact Lens for your Amazon Connect instance](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html#enable-cl)

1. In the AWS Connect console, click your instance alias
2. Left menu → **Analytics tools**
3. Click **Enable Contact Lens**
4. Click **Save**

You will see a green confirmation banner. Contact Lens is now enabled at the instance level.

**Note**: Enabling Contact Lens at the instance level is the *prerequisite*. You also need to add a
**Set recording and analytics behavior** block to each flow (done in Part D, Step D.5) to activate it
for individual contacts.

---

## Part C — Claim a Phone Number

To receive inbound calls, you need a phone number assigned to your instance.

> Official docs: [Claim a phone number](https://docs.aws.amazon.com/connect/latest/adminguide/claim-phone-number.html)

1. In your Connect admin website (`https://meridian-aria.my.connect.aws/`)
2. Left menu → **Channels** → **Phone numbers**
3. Click **Claim a number**
4. Select:
   - **Type**: DID (Direct Inward Dialling) — for a local number
   - **Country**: United Kingdom (+44)
   - Choose an available number from the list
5. **Description**: `ARIA Banking Voice Line`
6. **Flow**: Leave blank for now (you will assign it in Part F after creating the flow)
7. Click **Save**

Note the number down (e.g. `+44 20 XXXX XXXX`).

---

## Part D — Create the ARIA Voice Inbound Flow (Block by Block)

This is the most important part. You are building the contact flow that runs every time a call arrives.
Every block is explained with both **what to configure** and **why**.

> Official docs: [Create and manage contact flows](https://docs.aws.amazon.com/connect/latest/adminguide/create-contact-flow.html)

### How to open the Flow Designer

1. In your Connect admin website
2. Left menu → **Routing** → **Flows**
3. Click **Create flow**
4. Select type: **Contact flow (inbound)**
5. Name it: `ARIA Banking Voice Inbound`
6. Click **Create**

The Flow Designer canvas opens. You will see a **Start** entry point at the top left. Every flow begins here.

> **Tip**: Use the search bar at the top of the block palette (left side) to quickly find blocks by name.
> Drag and drop blocks onto the canvas, then click on a block to configure it.

---

### Block 1: Set Logging Behavior

**What it is**: Enables detailed flow logs stored in Amazon CloudWatch.

**Why you need it**: Without logging, when something goes wrong (and it will during testing), you have no
way to see what happened. Flow logs show you exactly which block ran, what decision was made, and what
error occurred.

> Official docs: [Set logging behavior](https://docs.aws.amazon.com/connect/latest/adminguide/set-logging-behavior.html)

**Steps**:
1. Search for **Set logging behavior** in the block palette
2. Drag it onto the canvas
3. Connect the **Start** block's output arrow → this block's input
4. Click the block to open its properties
5. Select **Enable flow logging**
6. Click **Save**

**What to connect next**: The single **Success** output branch → Block 2

---

### Block 2: Set Voice

**What it is**: Sets the text-to-speech (TTS) language and voice used for all spoken prompts in this flow.

**Why you need it**: Without this block, Connect uses the default US English voice (Joanna). For a UK
banking contact centre serving UK customers, you want a British English voice.

> Official docs: [Set voice](https://docs.aws.amazon.com/connect/latest/adminguide/set-voice.html)

**Steps**:
1. Search for **Set voice** in the block palette
2. Drag it onto the canvas
3. Connect Block 1's **Success** → Block 2's input
4. Click the block
5. Configure:
   - **Language**: English, British (en-GB)
   - **Voice**: Amy *(British English neural voice from Amazon Polly)*
   - **Override speaking style**: Select **Conversational**
6. Click **Save**

**Available British English voices**: Amy, Brian, Emma. Amy (neural, conversational) is recommended for
a banking assistant — natural, professional, warm.

**What to connect next**: **Success** → Block 3

---

### Block 3: Set Contact Attributes (Locale + Channel)

**What it is**: Stores key-value pairs onto the contact. These attributes travel with the contact for its
entire lifetime and are readable by Lambdas, the AI prompt, and other blocks.

**Why you need it**:
- The `locale` attribute tells the ARIA AI prompt which language to respond in (`{{$.locale}}` in the prompt)
- The `channel` attribute lets the session injector know whether to inject voice-specific context
- The `authStatus` attribute seeds the session as `unauthenticated` — ARIA won't claim the caller is
  authenticated until a downstream Lambda verifies their identity

> Official docs: [Set contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/set-contact-attributes.html)

**Steps**:
1. Search for **Set contact attributes** in the block palette
2. Drag it onto the canvas
3. Connect Block 2's **Success** → Block 3's input
4. Click the block
5. Add the following attributes (click **Add another attribute** for each):

| Destination type | Key | Value |
|---|---|---|
| User-defined | `locale` | `en-GB` |
| User-defined | `channel` | `voice` |
| User-defined | `authStatus` | `unauthenticated` |
| User-defined | `customerId` | *(leave blank — your auth Lambda will populate this later)* |

6. Click **Save**

**Note on `customerId`**: For pre-authenticated flows (e.g. customer dialling from a verified number),
you can set `customerId` here directly using the caller's ANI (Automatic Number Identification) by
choosing **System** namespace and key **Customer number**. For most flows, leave it blank — your
authentication Lambda will set it.

**What to connect next**: **Success** → Block 4

---

### Block 4: Check Hours of Operation

**What it is**: Checks if the current time falls within your defined business hours and routes accordingly.

**Why you need it**: You should not route customers into an AI agent session outside business hours —
ARIA doesn't know your roster is offline. Routing out-of-hours customers to a closed message is polite
and professional.

> Official docs: [Check hours of operation](https://docs.aws.amazon.com/connect/latest/adminguide/check-hours-of-operation.html)

**Prerequisite: Create Hours of Operation**
1. Left menu → **Routing** → **Hours of operation**
2. Click **Add hours of operation**
3. Name: `ARIA Banking Hours`
4. Time zone: `Europe/London`
5. Set Monday-Friday: 08:00 – 20:00, Saturday: 09:00 – 17:00, Sunday: Closed
6. Click **Save**

**Configure the block**:
1. Search for **Check hours of operation**
2. Drag it onto the canvas
3. Connect Block 3's **Success** → Block 4's input
4. Click the block
5. Select **ARIA Banking Hours** from the hours dropdown
6. Click **Save**

**Output branches and what to connect**:
- **In hours** → Block 5 (proceed to AI agent)
- **Out of hours** → Block 5b (play closed message — see below)
- **Error** → Block 5b (treat unexpected errors as out-of-hours to be safe)

**Create a simple out-of-hours handler (Block 5b)**:
1. Drag a **Play prompt** block
2. Click it, select **Text-to-speech**, enter:
   `"Thank you for calling Meridian Bank. Our lines are currently closed. Please call back Monday to Friday between 8am and 8pm, or Saturday between 9am and 5pm."`
3. Wire its output → a **Disconnect / hang up** block

---

### Block 5: Set Recording and Analytics Behavior (Contact Lens Real-Time)

**What it is**: Activates Contact Lens on this specific contact and enables real-time speech analytics.

**Why you MUST have this for voice AI**: Contact Lens real-time is what converts the customer's voice
into a live transcript. The Connect AI Agent reads this transcript to understand what the customer is
saying. Without this block, the AI Agent receives no audio content and cannot respond meaningfully.

> Official docs:
> - [Set recording and analytics behavior](https://docs.aws.amazon.com/connect/latest/adminguide/set-recording-behavior.html)
> - [Enable call recording and speech analytics](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html#enable-callrecording-speechanalytics)

**Steps**:
1. Search for **Set recording and analytics behavior**
2. Drag it onto the canvas
3. Connect Block 4's **In hours** → Block 5's input
4. Click the block
5. Under **Enable recording and analytics** → **Voice**:
   - **Agent and customer voice recording**: Turn **On**
   - Choose **Agent and customer** (both sides of the conversation recorded)
6. Under **Analytics**:
   - **Enable Contact Lens speech analytics**: Turn **On**
   - Select **Real-time analytics** *(not Post-call — you need real-time for the AI agent)*
   - **Language**: English, British (en-GB)
   - **Automated interaction call recording**: Turn **On**
     *(This records the customer's interaction with ARIA, not just agent segments)*
7. Click **Save**

**What to connect next**: **Success** → Block 6

> **Important**: The "Automated interaction call recording" option is specifically for recording
> customer–bot interactions. Enabling it means you will have a recording of the entire ARIA conversation
> for quality assurance, not just the agent-assisted portion.

---

### Block 6: Connect Assistant (Bind ARIA AI Agent)

**What it is**: Associates the ARIA Connect AI Agent domain to this contact. This is the block that
"activates" ARIA for this call. After this block runs, a Q Connect AI Agent session is created and
ARIA begins listening to the real-time transcript.

**Why it is placed here (after Block 5)**: Contact Lens must be enabled before the Connect assistant
block runs. The Connect assistant block itself doesn't care about the order, but the AI agent needs
the real-time transcript feed which Contact Lens provides. Best practice is to enable Contact Lens first.

> Official docs:
> - [Connect assistant block](https://docs.aws.amazon.com/connect/latest/adminguide/connect-assistant-block.html)
> - [Associate an AI agent with a flow](https://docs.aws.amazon.com/connect/latest/adminguide/create-ai-agents.html#associate-ai-agent-flow)

**Steps**:
1. Search for **Connect assistant**
2. Drag it onto the canvas
3. Connect Block 5's **Success** → Block 6's input
4. Click the block
5. Under **Config** tab:
   - **Amazon Connect assistant domain ARN**: Paste your Q Connect assistant ARN
     (format: `arn:aws:wisdom:eu-west-2:395402194296:assistant/<assistant-id>`)
   - **Orchestration AI agent**: Select your published **ARIA Orchestration** agent
6. Click **Save**

> **How to find your assistant ARN**:
> 1. In the Connect admin website → left menu → **AI Agent Designer**
> 2. Click the gear/settings icon to view the assistant details
> 3. Copy the ARN

**What to connect next**: **Success** → Block 7 | **Error** → a **Play prompt** block with a
fallback message ("I'm sorry, our AI assistant is currently unavailable. Connecting you to an agent.")
→ **Set working queue** → **Transfer to queue**

---

### Block 7: AWS Lambda Function (Session Injector)

**What it is**: Calls your `session_injector` Lambda function, which injects 12 session variables
into the Q Connect AI session (the ARIA session that was just created by Block 6).

**Why it must come AFTER Block 6**: The Q Connect session does not exist until the Connect assistant
block creates it. If you call the session injector before Block 6, the Lambda will throw a
`ResourceNotFoundException` because it cannot find a session to update.

**Why this matters for ARIA**: The ARIA system prompt uses template variables like `{{$.Custom.preferredName}}`,
`{{$.Custom.productSummary}}`, `{{$.Custom.authStatus}}`. These are populated by the session injector.
Without this block, ARIA responds as if it knows nothing about the customer.

> Official docs:
> - [AWS Lambda function block](https://docs.aws.amazon.com/connect/latest/adminguide/invoke-lambda-function-block.html)
> - [Add customer data to an AI agent session](https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-session.html)

**Steps**:
1. Search for **AWS Lambda function**
2. Drag it onto the canvas
3. Connect Block 6's **Success** → Block 7's input
4. Click the block
5. **Select an action**: Invoke Lambda
6. **Select a function**: Choose `session_injector` from the dropdown
   *(If it doesn't appear, return to Part A Step A.2 and add it to the instance)*
7. **Execution mode**: **Synchronous**
   *(Wait for the Lambda to finish before proceeding — the session data must be injected before
   the AI agent starts responding)*
8. **Timeout**: 8 seconds *(the maximum for synchronous mode)*
9. **Response validation**: STRING_MAP
10. Under **Send parameters** (optional — for passing contact attributes to the Lambda):
    - Key: `contactId` / Value: `$.ContactId` (System namespace)
    - Key: `customerId` / Value: `$.Attributes.customerId` (User-defined namespace)
    - Key: `authStatus` / Value: `$.Attributes.authStatus`
    - Key: `locale` / Value: `$.Attributes.locale`
    - Key: `channel` / Value: `$.Attributes.channel`
11. Click **Save**

**What to connect next**:
- **Success** → Block 8
- **Error** → Block 8 *(continue even if injection fails — ARIA will still work, just without
  personalised session context)*
- **Timeout** → Block 8 *(same — do not drop the call if the injector is slow)*

> **Why connect Error and Timeout to the same success path?**
> The session injector is enrichment — valuable but not essential. If it fails, ARIA can still
> have the conversation; it just won't have pre-populated customer context. Dropping the call
> because of a data-injection timeout would be a poor customer experience.

---

### Block 8: Check Contact Attributes (Auth Gate — Optional)

**What it is**: Branches the flow based on the value of a contact attribute.

**Why you might want this**: You may want to play a different greeting to customers who are already
authenticated (e.g. via ANI matching or a prior IVR step) versus unauthenticated callers. This is
also where you would branch to a dedicated authentication sub-flow.

> Official docs: [Check contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/check-contact-attributes.html)

**Steps**:
1. Search for **Check contact attributes**
2. Drag it onto the canvas
3. Connect Block 7's **Success** → Block 8's input
4. Click the block
5. Under **Attribute to check**:
   - Namespace: **User-defined**
   - Attribute: `authStatus`
6. Under **Conditions to check**:
   - Click **Add condition**
   - Operator: **Equals**
   - Value: `authenticated`
7. Click **Save**

**Output branches**:
- **authenticated** → Block 9 (proceed — skip greeting, ARIA knows who this is)
- **No match** → Block 9 (also proceed — ARIA will greet as unauthenticated)
- **Error** → Block 9 (same — do not block the flow on an attribute check error)

> **For now, wire all three to Block 9**. As your auth flows mature, the `authenticated` branch
> can skip re-introduction steps.

---

### Block 9: Play Prompt (Opening Greeting)

**What it is**: Plays a spoken message to the caller using Amazon Polly text-to-speech (TTS).

**Why you need it**: Before ARIA takes over the conversation, the caller needs a brief welcome message.
This is also a good time to set expectations ("You are speaking with ARIA, our AI banking assistant").

> Official docs: [Play prompt](https://docs.aws.amazon.com/connect/latest/adminguide/play.html)

**Steps**:
1. Search for **Play prompt**
2. Drag it onto the canvas
3. Connect Block 8's outputs → Block 9's input
4. Click the block
5. Select **Text-to-speech or chat text**
6. Enter the prompt text (this uses the Amy voice you set in Block 2):
   ```
   Welcome to Meridian Bank. I'm ARIA, your AI banking assistant.
   I can help you with your accounts, cards, balances, and statements.
   How can I help you today?
   ```
7. Check **SSML** if you want to add pauses or emphasis:
   ```xml
   <speak>
   Welcome to Meridian Bank. I'm ARIA, your AI banking assistant.
   <break time="300ms"/>
   I can help you with your accounts, cards, balances, and statements.
   How can I help you today?
   </speak>
   ```
8. Click **Save**

**What to connect next**: **Success** → Block 10

---

### Block 10: Set Working Queue

**What it is**: Designates which queue ARIA will transfer the contact to if a human agent is needed.

**Why you need it before Transfer to Queue**: The **Transfer to queue** block (Block 11) looks up whichever
queue was set as the "working queue". If you haven't set one, Transfer to queue will fail with an error.
This is a common beginner mistake.

> Official docs: [Set working queue](https://docs.aws.amazon.com/connect/latest/adminguide/set-working-queue.html)

**Prerequisite: Ensure you have a queue**
1. Left menu → **Routing** → **Queues**
2. You should see at least **BasicQueue** (created automatically with every instance)
3. For banking, create a dedicated queue:
   - Click **Add queue**
   - Name: `ARIA Banking Agents`
   - Description: `Queue for contacts escalated from ARIA`
   - Hours of operation: `ARIA Banking Hours`
   - Outbound caller ID number: your claimed phone number
   - Click **Save**

**Configure the block**:
1. Search for **Set working queue**
2. Drag it onto the canvas
3. Connect Block 9's **Success** → Block 10's input
4. Click the block
5. Under **Set queue**:
   - Select **ARIA Banking Agents** (or BasicQueue if you haven't created a dedicated one)
6. Click **Save**

**What to connect next**: **Success** → Block 11

---

### Block 11: Transfer to Queue (The Handover Point)

**What it is**: Places the contact in the queue. For AI agent flows, the contact enters the queue
where ARIA manages the conversation. When ARIA decides to escalate (or the customer requests a human),
the contact is already in queue to be routed to an available agent.

**Why this is the final block in an AI agent flow**: Once the contact is in queue with a Connect AI
Agent session active, ARIA takes over. The contact flow has done its job — it has:
1. Set up logging (Block 1)
2. Set the voice (Block 2)
3. Set locale and channel attributes (Block 3)
4. Checked business hours (Block 4)
5. Enabled Contact Lens real-time (Block 5)
6. Created the AI session (Block 6)
7. Injected session data (Block 7)
8. Set the working queue (Block 10)

Now ARIA drives the conversation.

> Official docs: [Transfer to queue](https://docs.aws.amazon.com/connect/latest/adminguide/transfer-to-queue.html)

**Steps**:
1. Search for **Transfer to queue**
2. Drag it onto the canvas
3. Connect Block 10's **Success** → Block 11's input
4. Click the block
5. Under the **Transfer to queue** tab — no additional configuration needed; it uses the working
   queue you set in Block 10
6. Click **Save**

**Output branches**:
- **At capacity** → a **Play prompt** block: "Our lines are currently busy. Please call back shortly."
  → **Disconnect / hang up**
- **Error** → same fallback play prompt → disconnect

---

### Block 12: Disconnect / Hang Up

**What it is**: Terminates the contact.

**Why you need it**: Every error branch and the out-of-hours path must end somewhere. Disconnect blocks
are the clean way to end a call. Without one, calls that hit unconnected branches will drop silently,
which is confusing for the customer.

> Official docs: [Disconnect / hang up](https://docs.aws.amazon.com/connect/latest/adminguide/disconnect-hang-up.html)

**Steps**:
1. Search for **Disconnect / hang up**
2. Drag it onto the canvas
3. Connect:
   - The out-of-hours **Play prompt** (Block 5b) → this block
   - The at-capacity **Play prompt** → this block
   - Any other terminal error paths → this block

---

### Save and Publish the Voice Flow

1. Click **Save** (top right) — saves a draft
2. Click **Publish** (top right) — makes the flow live

> **Important**: Only published flows can be assigned to phone numbers and chat widgets. Draft flows
> cannot receive contacts.

---

## Part E — Create the ARIA Chat Flow

Chat flows are simpler — you don't need Contact Lens (it is optional for chat) and there is no voice
or TTS configuration. But the core pattern is the same.

> Official docs:
> - Contact Lens for chat: [Enable chat analytics](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html#enable-chatanalytics)

### Step E.1 — Create a New Flow

1. Left menu → **Routing** → **Flows**
2. Click **Create flow**
3. Type: **Contact flow (inbound)**
4. Name: `ARIA Banking Chat Inbound`
5. Click **Create**

### Chat Flow Block Sequence

The chat flow is shorter than voice because there is no voice/recording setup:

```
[Start]
  ↓
[Block 1: Set Logging Behavior]
  ↓
[Block 2: Set Contact Attributes] (locale=en-GB, channel=chat, authStatus=unauthenticated)
  ↓
[Block 3: Set Recording and Analytics Behavior] (chat analytics, optional but recommended)
  ↓
[Block 4: Connect Assistant] (ARIA AI Agent)
  ↓
[Block 5: AWS Lambda Function] (session_injector)
  ↓
[Block 6: Set Working Queue] (ARIA Banking Agents)
  ↓
[Block 7: Transfer to Queue]
```

#### Chat Block 1: Set Logging Behavior
- Same as Voice Block 1
- Enable flow logging
- Connect **Start** → this block → **Success** → Chat Block 2

#### Chat Block 2: Set Contact Attributes

| Key | Value | Reason |
|---|---|---|
| `locale` | `en-GB` | ARIA prompt locale variable |
| `channel` | `chat` | Session injector knows to skip voice-specific enrichment |
| `authStatus` | `unauthenticated` | Safe default — auth handled by downstream logic |

> **Note**: Chat does not use Check hours of operation in most deployments because chat queues are
> often asynchronous. If you want hours checking on chat, add it — the block supports chat.

#### Chat Block 3: Set Recording and Analytics Behavior (Optional but Recommended)

1. Drag the block, configure:
   - Under **Chat**: Enable **Contact Lens conversational analytics** → **Enable chat analytics**
   - Language: English, British (en-GB)
   - Enable **Redaction** for sensitive data (PII)
2. Why: Contact Lens chat analytics gives you chat transcripts, sentiment analysis, and AI-generated
   post-chat summaries in the Connect analytics dashboard.

#### Chat Block 4: Connect Assistant

Same as Voice Block 6:
- Select your ARIA assistant ARN
- Select the ARIA Orchestration AI agent
- Error → fallback chat message block → disconnect

#### Chat Block 5: AWS Lambda Function (Session Injector)

Same as Voice Block 7:
- Function: `session_injector`
- Mode: **Synchronous**
- Send the same 5 parameters (contactId, customerId, authStatus, locale, channel)
- Wire Success, Error, and Timeout all → Chat Block 6

#### Chat Block 6: Set Working Queue
- Select **ARIA Banking Agents**
- Wire **Success** → Chat Block 7

#### Chat Block 7: Transfer to Queue
- No additional config needed
- Wire **At capacity** and **Error** → a play prompt / send message block → disconnect

### Save and Publish the Chat Flow

1. Click **Save**
2. Click **Publish**

---

## Part F — Connect a Phone Number to the Voice Flow

Now that both flows are published, assign the phone number to the voice flow.

> Official docs: [Assign a phone number to a flow](https://docs.aws.amazon.com/connect/latest/adminguide/associate-claimed-number-contact-flow.html)

1. Left menu → **Channels** → **Phone numbers**
2. Click the phone number you claimed in Part C
3. Under **Contact flow / IVR**: Select **ARIA Banking Voice Inbound**
4. Click **Save**

---

## Part G — Test Voice (Call the Number)

1. Dial the phone number from any phone
2. You should hear the Amy voice welcome prompt (Block 9)
3. After the prompt, say something like: **"I'd like to check my account balance"**
4. ARIA should respond to your query

### What to check if it doesn't work

1. In the Connect admin website → left menu → **Analytics** → **Contact search**
2. Find the contact (your call) by time
3. Click the contact ID
4. Under **Flow logs**: look for the last block that ran and any error messages

Common issues and fixes:

| Symptom | Likely cause | Fix |
|---|---|---|
| Call drops immediately | Flow not published | Publish the flow |
| No greeting plays | Set voice block language mismatch | Ensure Amy (en-GB) is selected |
| Greeting plays but ARIA doesn't respond | Contact Lens not enabled | Check Block 5 (real-time analytics) |
| ARIA responds but has no customer context | Session injector failed | Check Lambda CloudWatch logs |
| "Connect assistant not found" | Wrong ARN or unpublished agent | Re-publish ARIA agent, check ARN |

---

## Part H — Set Up Chat Widget

The chat widget is the web snippet you embed on your website or the Meridian Banking UI.

> Official docs: [Set up your customer's chat experience](https://docs.aws.amazon.com/connect/latest/adminguide/chat.html)

### Step H.1 — Create a Chat Widget

1. Left menu → **Channels** → **Chat**
2. Click **Add a chat widget**
3. Configure:
   - **Widget name**: `ARIA Banking Chat`
   - **Contact flow**: Select **ARIA Banking Chat Inbound**
   - **Website domains**: Add your website URL (e.g. `https://app.meridianbank.co.uk`)
     *(You must whitelist your domain, or the widget won't load)*
4. Customise colours and widget title if desired
5. Click **Create widget**
6. Copy the **Widget snippet code** (the JavaScript `<script>` tag)

### Step H.2 — Embed in Your Website

Add the script snippet before the closing `</body>` tag of your web application:

```html
<!-- ARIA Chat Widget -->
<script type="text/javascript">
  (function(w, d, x, id){
    s=d.createElement('script');
    s.src='https://dtn7rvxwwlhud.cloudfront.net/amazon-connect-chat-interface-client.js';
    s.async=1;
    s.id=id;
    d.getElementsByTagName('head')[0].appendChild(s);
    w[x] =  w[x] || function() { (w[x].ac = w[x].ac || []).push(arguments) };
  })(window, document, 'amazon_connect', 'YOUR-WIDGET-ID');
  amazon_connect('styles', { openChat: { color: '#006EFF', backgroundColor: '#003DA5'}, closeChat: { color: '#FFF', backgroundColor: '#003DA5'} });
  amazon_connect('snippetId', 'YOUR-SNIPPET-ID');
  amazon_connect('supportedMessagingContentTypes', [ 'text/plain', 'text/markdown' ]);
</script>
```

Replace `YOUR-WIDGET-ID` and `YOUR-SNIPPET-ID` with the values from the Connect console.

---

## Part I — Test Chat

1. Open your website (or the Connect Test Chat tool in the admin console)
2. For a quick test without a website: Left menu → **Dashboard** → **Test chat**
3. Select your **ARIA Banking Chat Inbound** flow
4. Click **Start chat**
5. Type **"Hello, I need help with my account"**
6. ARIA should respond

---

## Nova Sonic: What It Is and How to Use It with Connect

### What is Nova Sonic?

Amazon Nova Sonic is AWS's **speech-to-speech (S2S) foundation model** built on Amazon Bedrock.
It fundamentally changes how voice AI works by eliminating the traditional three-step pipeline:

**Traditional IVR/voice bot pipeline:**
```
Customer speaks
    ↓  ASR (Automatic Speech Recognition — e.g. Amazon Transcribe)
Text transcript
    ↓  LLM (e.g. Claude / Nova Pro)
Response text
    ↓  TTS (Text-to-Speech — e.g. Amazon Polly)
Spoken audio back to customer
```
Each arrow above introduces latency and a potential loss of nuance (tone, emotion, pace).

**Nova Sonic speech-to-speech pipeline:**
```
Customer speaks (audio stream)
    ↓
Nova Sonic (processes audio directly — no intermediate text)
    ↓
Spoken audio response back to customer
```

Nova Sonic understands **vocal tone, emphasis, hesitation, and emotional cues** that are lost when
speech is converted to text first. The result is a more natural, lower-latency conversation that
feels genuinely like speaking to a human agent.

> Official docs: [Amazon Connect AI agents (powered by Amazon Bedrock)](https://docs.aws.amazon.com/connect/latest/adminguide/connect-ai-agent.html)

---

### Three Paths to Voice AI in Amazon Connect

| Path | Pipeline | Voice quality | Complexity | When to use |
|---|---|---|---|---|
| **Path A — Native Connect AI Agent** (this guide) | Contact Lens real-time → Connect AI Agent (LLM) → Polly TTS | Good (neural/generative Polly) | Lowest — no extra services | Fastest to deploy; eu-west-2 supported today |
| **Path B — Lex V2 + Nova Sonic S2S** | Connect → Lex V2 bot → Nova Sonic → Lambda → ARIA AgentCore | Excellent — native S2S | Medium — requires Lex bot + bridge Lambda | Best voice quality; full speech-to-speech |
| **Path C — Native AI Voice (Nova Sonic built-in)** | Connect native voice AI with Nova Sonic as the model | Excellent — native S2S | Low once enabled — no Lex needed | Future/current in supported regions; combines Path A ease with Path B quality |

This section covers **Path A in full** (already documented above), then covers **Path C** — using
Nova Sonic natively within the Connect Conversational AI pipeline without Lex — in complete detail.
Path B is documented in `docs/amazon-connect-lex-nova-sonic-setup-guide.md`.

---

### Understanding Path C: Nova Sonic Native in Connect Conversational AI

Connect's native Conversational AI voice path (Path C) integrates Nova Sonic directly as the
speech model powering the Connect AI Agent. Instead of Amazon Polly speaking ARIA's responses,
Nova Sonic generates audio natively, and instead of Contact Lens converting the customer's speech
to text, Nova Sonic processes the customer's audio stream end-to-end.

**How it works under the hood:**

```
Customer speaks (PSTN audio stream arrives at Connect)
        ↓
Amazon Connect streams audio to Nova Sonic
        ↓
Nova Sonic transcribes speech AND feeds it to the Connect AI Agent (LLM layer)
        ↓
Connect AI Agent (ARIA) generates a text response
        ↓
Nova Sonic converts the text response to spoken audio natively (not via Polly)
        ↓
Audio streamed back to customer over PSTN
```

The Connect AI Agent (ARIA with your custom Orchestration prompt and tools) remains the intelligence
layer — Nova Sonic is the voice layer wrapping it. Your ARIA system prompt, tools, guardrails, and
session variables all work identically whether using Polly (Path A) or Nova Sonic (Path C).

---

### Prerequisites for Path C (Nova Sonic Native)

Before enabling Nova Sonic in the native Connect path, you need the following:

| Requirement | Detail |
|---|---|
| **Amazon Connect Unlimited AI Pricing** | Must be enabled on your instance. This is the default for instances created after Nov 2023. It covers Nova Sonic voice costs. |
| **Amazon Bedrock model access** | `amazon.nova-sonic-v1:0` must be enabled in your Bedrock console for `eu-west-2` (or your region). |
| **Contact Lens enabled** | Even in the Nova Sonic path, Contact Lens must be enabled at the instance level for the Connect AI Agent to work with voice. |
| **ARIA AI Agent published** | Your ARIA Orchestration AI agent must be published (not Draft). |
| **eu-west-2 Nova Sonic availability** | Confirm Nova Sonic (`amazon.nova-sonic-v1:0`) is available as a model in your region in Bedrock. See [Supported regions](#step-c1-check-nova-sonic-availability). |

> Official docs: [Amazon Connect Unlimited AI Pricing](https://docs.aws.amazon.com/connect/latest/adminguide/enable-nextgeneration-amazonconnect.html)

---

### Step C.1 — Check Nova Sonic Availability in eu-west-2

> Official docs: [Amazon Bedrock model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)

1. Go to [https://console.aws.amazon.com/bedrock/](https://console.aws.amazon.com/bedrock/)
2. Set your region to **Europe (London) eu-west-2** (top right)
3. Left menu → **Model access** (under **Bedrock configurations**)
4. In the search box, type `Nova Sonic`
5. Look for **Amazon Nova Sonic** in the list

**If Nova Sonic appears**:
- Check whether it shows **Access granted** or **Available to request**
- If **Available to request**: click **Modify model access** → tick **Amazon Nova Sonic** → **Request model access**
- Approval is usually instant for Nova Sonic (it is a standard-tier model)

**If Nova Sonic does not appear**:
- Nova Sonic is not yet available in `eu-west-2` at the time of your check
- Use Path A (Polly neural TTS) for now and return to this step when AWS announces eu-west-2 availability
- Alternatively, deploy a Connect instance in `us-east-1` specifically for voice to use Nova Sonic today

> **Note**: As of 2025, Nova Sonic is available in `us-east-1` and `us-west-2` with expansion ongoing.
> AWS regularly adds regions — always check the Bedrock console for your region's current status.
> The official model ID is `amazon.nova-sonic-v1:0`.

---

### Step C.2 — Enable Unlimited AI Pricing on Your Instance

The native Nova Sonic voice feature is included under Amazon Connect Unlimited AI Pricing.

> Official docs: [Enable unlimited AI pricing](https://docs.aws.amazon.com/connect/latest/adminguide/enable-nextgeneration-amazonconnect.html#how-to-enable-ac)

1. Go to [https://console.aws.amazon.com/connect/](https://console.aws.amazon.com/connect/)
2. Click your instance alias
3. Left navigation → **Amazon Connect** (the top-level page for your instance)
4. Find the section: **Enable unlimited AI pricing across your entire contact center**
5. Check the status:
   - If it shows **Enabled** — you are ready, proceed to Step C.3
   - If it shows **Not enabled** — click **Enable** → confirm in the dialog

**Important pricing note**: Unlimited AI Pricing covers:
- Conversational analytics (Contact Lens)
- AI-powered voice and chat through Connect AI agents
- AI-powered generative voice TTS in Amazon Connect (including Nova Sonic)

When you enable it, any active free trials of individual features end. If you were trialling
Contact Lens separately, those trial credits stop — but the feature remains enabled under the new
all-inclusive pricing.

---

### Step C.3 — Enable Amazon Bedrock Model Access for Nova Sonic

Even though Nova Sonic is accessed through Connect, the underlying call goes through Amazon Bedrock.
You must explicitly grant your Connect instance permission to use the model.

> Official docs: [Amazon Bedrock model access](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)

1. Go to [https://console.aws.amazon.com/bedrock/](https://console.aws.amazon.com/bedrock/)
2. Ensure you are in the same region as your Connect instance (eu-west-2)
3. Left menu → **Model access**
4. Click **Modify model access** (top right)
5. Find **Amazon Nova Sonic** in the list and tick the checkbox
6. Click **Request model access**
7. Wait for status to change to **Access granted** (usually within seconds to minutes)

**Verify the model ID**: After access is granted, note the Model ID: `amazon.nova-sonic-v1:0`
This is what you will reference in the Connect AI prompt model configuration.

---

### Step C.4 — Update the ARIA AI Prompt to Use Nova Sonic

The Connect AI Agent uses an Orchestration AI prompt that runs on a Bedrock LLM. Separately, Nova
Sonic handles the audio. However, for the full native voice path, you configure the **Self-service**
AI agent type (which supports Nova Sonic directly) rather than the Orchestration type.

> **Which agent type uses Nova Sonic?**
> - **Orchestration AI agent** (what ARIA currently uses): Uses Claude/Nova Pro as the LLM backbone;
>   audio handled by Contact Lens + Polly (Path A) or Nova Sonic (Path C upgrade)
> - **Self-service AI agent**: Designed specifically for automated customer self-service voice; uses
>   Nova Sonic as the native speech model when available

For the native Connect + Nova Sonic path, the recommended approach for ARIA is:

**Option 1 — Orchestration agent + Nova Sonic audio layer (Path C)**
Keep your existing ARIA Orchestration agent unchanged. Nova Sonic replaces Polly as the TTS layer
automatically when enabled. This requires no change to your AI prompt or agent.

**Option 2 — Self-service agent with Nova Sonic (Full S2S)**
Create a separate Self-service AI agent type using a Nova Sonic-compatible pre-processing prompt.
This delivers the full speech-to-speech experience.

The steps below cover **Option 1** (keeping your existing ARIA Orchestration agent and enabling
Nova Sonic as the voice layer) as it requires the least configuration change.

---

### Step C.5 — Verify the ARIA AI Prompt Model for eu-west-2

The AI prompt model determines which Bedrock LLM powers ARIA's reasoning. Nova Sonic is the
**voice layer** — the LLM layer is separate. For `eu-west-2`, confirm your ARIA prompt is using a
supported model:

> Official docs: [Supported models for system/custom prompts — eu-west-2](https://docs.aws.amazon.com/connect/latest/adminguide/create-ai-prompts.html#cli-create-aiprompt)

**Supported custom prompt models in eu-west-2:**

| Model ID | Notes |
|---|---|
| `eu.anthropic.claude-4-5-haiku-20251001-v1:0` | Fast, cost-efficient (Cross-Region) |
| `eu.anthropic.claude-4-5-sonnet-20250929-v1:0` | Balanced quality/speed (Cross-Region) — **recommended for ARIA** |
| `global.anthropic.claude-4-5-haiku-20251001-v1:0` | Global CRIS |
| `global.anthropic.claude-4-5-sonnet-20250929-v1:0` | Global CRIS |
| `eu.amazon.nova-pro-v1:0` | Amazon Nova Pro — also excellent for ARIA |
| `eu.amazon.nova-lite-v1:0` | Nova Lite — faster, lower cost |
| `anthropic.claude-3-7-sonnet-20250219-v1:0` | Previous generation, still supported |
| `anthropic.claude-3-haiku-20240307-v1:0` | Previous generation |

**To check/update the model on your ARIA AI prompt:**
1. Connect admin → **AI Agent Designer** → **AI Prompts**
2. Click your ARIA Orchestration prompt
3. In the **Models** section, verify the current model
4. If it shows a `us.*` model (which will fail cross-region from eu-west-2), change it to
   `eu.anthropic.claude-4-5-sonnet-20250929-v1:0` or `eu.amazon.nova-pro-v1:0`
5. Click **Save** → **Publish** to create a new version
6. In **AI Agent Designer** → **AI Agents** → your ARIA agent → update to use the new prompt version → **Publish**

---

### Step C.6 — Configure the Voice Flow for Nova Sonic (Path C)

The contact flow for Path C is nearly identical to Path A. The key difference is how Connect processes
voice — when Nova Sonic is the backend voice model, the audio pipeline upgrades automatically. Your
flow still uses the same blocks; you just make two configuration adjustments.

**Adjustment 1: Set Recording and Analytics Behavior — enable both**

In Block 5 of your voice flow (Set recording and analytics behavior), when Nova Sonic is active you
should enable both real-time **and** automated interaction recording:

1. Open Block 5 (Set recording and analytics behavior)
2. Under **Voice**:
   - **Agent and customer voice recording**: **On** → **Agent and customer**
   - **Contact Lens speech analytics**: **On** → **Real-time analytics**
   - **Language**: `English, British (en-GB)`
   - **Automated interaction call recording**: **On**
     *(Critical for Nova Sonic path — records the full AI conversation for audit and quality)*
3. Under **Contact Lens Generative AI capabilities** (if visible):
   - Enable **Contact summary** — this generates AI post-call summaries using Nova Pro

> Why: Even with Nova Sonic handling audio natively, Contact Lens still generates the transcript and
> analytics. The transcript is what ARIA's LLM layer reads. Nova Sonic handles the audio I/O;
> Contact Lens handles analytics.

**Adjustment 2: Set Voice block — remove explicit Polly voice if Nova Sonic is active**

When Nova Sonic is the active speech model, the Set voice block (Block 2) voice selection has no
effect on the actual audio output — Nova Sonic overrides it. However, **keep the Set voice block**
because:
- It still controls the fallback if Nova Sonic is unavailable
- It sets the language attribute used by Lex (if you ever add a Lex bot to the flow)
- Removing it could cause issues if Nova Sonic is temporarily unavailable and Polly fallback is needed

No other flow changes are needed. The Connect assistant block, Lambda session injector, queue setup,
and Transfer to queue blocks all work identically for Path C.

---

### Step C.7 — Verify Nova Sonic is Active on a Test Call

After completing Steps C.1–C.6, make a test call to your phone number. Nova Sonic produces a
distinctly different voice quality compared to Polly — it sounds more conversational, with natural
pauses, intonation variation, and more realistic cadence.

**How to verify Nova Sonic is being used (not Polly)**:

1. Make a test call
2. In the Connect admin website → **Analytics** → **Contact search**
3. Find the contact → click the Contact ID
4. Under **Contact details** → **Recordings and transcripts**:
   - If Nova Sonic is active, the recording section shows **Nova Sonic** as the speech model
   - The transcript shows the customer's utterances processed by Nova Sonic
5. Under **Contact attributes** at the bottom, look for a `speechModel` attribute if your session
   injector is logging it

**Alternatively, check CloudWatch**:
```bash
aws logs filter-log-events \
  --log-group-name /aws/connect/<instance-id> \
  --filter-pattern "nova-sonic" \
  --region eu-west-2
```

---

### Step C.8 — Tune the Nova Sonic Experience

Nova Sonic's voice can be tuned through the **AI Prompt** rather than traditional Polly voice settings.
Because Nova Sonic generates speech from text natively, the **tone and style** of ARIA's responses in
the prompt directly affect how Nova Sonic speaks them.

**Prompt guidance for natural Nova Sonic voice:**

In your ARIA Orchestration AI prompt (under the `system:` section), add voice guidance:

```yaml
system: |
  You are ARIA, the AI banking assistant for Meridian Bank.
  
  VOICE STYLE GUIDANCE:
  Speak naturally and conversationally. Use short sentences — no more than 20 words per 
  sentence when responding to voice calls. Avoid lists and bullet points as they do not 
  translate well to speech. Use natural speech patterns: contractions (I'll, you've, that's), 
  transitional phrases (right, certainly, of course), and brief acknowledgements before 
  answering (I can help with that, let me check that for you).
  
  When confirming understanding, echo back key details briefly before proceeding.
  For example: "So you'd like to check the balance on your current account — let me pull 
  that up for you now."
  
  [rest of your system prompt]
```

> **Why this matters with Nova Sonic**: Polly reads text mechanically. Nova Sonic interprets the
> style and tone of text and delivers it more naturally. Shorter sentences, conversational language,
> and natural hesitation markers (`hmm`, `let me`, `right`) result in a significantly better
> Nova Sonic output than formal, list-heavy prompt responses.

**SSML is NOT used with Nova Sonic**: Unlike Polly (which supports SSML tags like `<break>` and
`<emphasis>`), Nova Sonic generates speech from natural language. Do not add SSML tags to your ARIA
prompt responses intended for Nova Sonic — they will be spoken literally as text.

---

### Step C.9 — Configure Barge-In (Interruption Handling)

A key benefit of Nova Sonic over Polly is **barge-in support** — the customer can interrupt ARIA
mid-sentence and Nova Sonic will stop speaking and listen. This is critical for natural conversation.

Barge-in is controlled by the **Get customer input** block in the flow. However, with the Connect
AI Agent (Orchestration type), barge-in is managed automatically by the AI session — you do not
need to configure it separately. The Connect AI Agent handles turn-taking natively.

**To verify barge-in is not disabled**:
1. Open your voice flow in the Flow Designer
2. Check that there is no **Store customer input** block between the **Connect assistant** block
   and the **Transfer to queue** block
   *(Store customer input blocks DTMF input and can interfere with voice barge-in)*
3. The flow should go directly from Connect assistant → Lambda injector → queue

**Testing barge-in**:
1. Call the test number
2. Wait for ARIA to start speaking
3. Interrupt by speaking before ARIA finishes
4. ARIA should stop mid-sentence and respond to what you said

---

### Step C.10 — Enable Multilingual Support with Nova Sonic

Nova Sonic supports multiple languages natively. To serve customers in different languages with ARIA:

**Step 1: Dynamic locale detection**

Add a **Check contact attributes** block to your voice flow after the initial greeting to branch
based on the customer's chosen language. Or, set the locale dynamically from your authentication
Lambda based on the customer's profile language preference.

**Step 2: Update Set contact attributes block**

In Block 3 of your flow (Set contact attributes), change the `locale` value to a contact attribute
reference instead of a static value:

| Destination type | Key | Value type | Value |
|---|---|---|---|
| User-defined | `locale` | Dynamic | `$.External.customerLocale` (from your auth Lambda) |

Your authentication Lambda can look up the customer's preferred language and return it as
`customerLocale` (e.g. `en-GB`, `cy-GB` for Welsh, `ur-PK` for Urdu).

**Step 3: Update the ARIA AI Prompt locale instruction**

In your ARIA AI Prompt, ensure the locale instruction is present:
```yaml
  Respond in the language locale specified by {{$.locale}}.
  If {{$.locale}} is en-GB, respond in British English.
  If {{$.locale}} is cy-GB, respond in Welsh.
```

> **Nova Sonic language support**: Nova Sonic supports English (US, UK), Spanish, French, German,
> Italian, Japanese, Korean, Portuguese, and more. Check the current list in the
> [Bedrock console model details](https://console.aws.amazon.com/bedrock/home#/models).

---

### Step C.11 — Monitor Nova Sonic Voice Quality in Contact Lens

Contact Lens provides real-time and post-call analytics even when Nova Sonic is the voice model.
Use these analytics to monitor and improve ARIA's Nova Sonic voice experience.

**What to monitor:**

1. **Sentiment scores**: Contact Lens analyses both customer and agent (ARIA) sentiment in real-time.
   Low customer sentiment during ARIA interactions may indicate Nova Sonic is misunderstanding
   utterances or ARIA's responses are unclear.
   - Connect admin → **Analytics** → **Contact search** → contact → **Sentiment**

2. **Interruption rate**: How often customers interrupt ARIA before it finishes speaking.
   - A high interruption rate suggests ARIA's responses are too long or the customer is impatient
   - Shorten prompt response lengths in your ARIA AI Prompt

3. **Post-call transcript review**: Check transcripts for ASR errors where Nova Sonic
   misheard a customer.
   - Connect admin → **Analytics** → **Contact search** → contact → **Transcript**
   - Look for `[inaudible]` tags or words that don't make sense in context

4. **Call duration distribution**: Nova Sonic should produce shorter average call durations than
   Polly (less waiting time, faster turn-taking). Track this in **Analytics** → **Historical metrics**.

---

### Nova Sonic vs Polly: Feature Comparison for ARIA

| Feature | Amazon Polly (Path A — neural/generative) | Nova Sonic (Path C — S2S) |
|---|---|---|
| Voice naturalness | Good (neural) / Excellent (generative) | Excellent — human-like cadence |
| Latency (time to first audio) | ~200–500ms | ~100–300ms |
| Barge-in support | Via Contact Lens / Lex | Native in Nova Sonic |
| Tone/emotion | Static — same tone always | Dynamic — reflects content tone |
| SSML support | Yes | No — uses natural language |
| Multilingual | 60+ languages via Polly | Core languages (expanding) |
| Cost (eu-west-2) | Included in Unlimited AI Pricing | Included in Unlimited AI Pricing |
| Region availability (eu-west-2) | Available now | Check Bedrock console |
| Configuration required | Set voice block engine | Bedrock model access + enabled instance |
| ARIA prompt changes needed | None | Add voice style guidance (recommended) |

---

### Choosing Your Path: Decision Guide

```
Are you deploying today in eu-west-2?
    │
    ├── Yes: Is Nova Sonic available in Bedrock for eu-west-2?
    │           │
    │           ├── Yes → Use Path C (Nova Sonic native)
    │           │         Steps C.1–C.11 above
    │           │
    │           └── No → Use Path A (Polly neural Amy)
    │                     Parts D–I of this guide
    │                     Upgrade to Path C when Nova Sonic reaches eu-west-2
    │
    └── No / deploying in us-east-1:
            │
            ├── Want best voice quality + speech-to-speech?
            │   → Use Path C (Nova Sonic native) — available in us-east-1 today
            │
            └── Need Lex NLU features (slot filling, intents)?
                → Use Path B (Lex V2 + Nova Sonic)
                   See docs/amazon-connect-lex-nova-sonic-setup-guide.md
```

**Our recommendation for ARIA in production:**
1. **Now** (eu-west-2): Deploy Path A with Amazon Polly neural Amy voice. ARIA works today.
2. **When Nova Sonic reaches eu-west-2**: Enable Bedrock model access (Step C.1), enable Unlimited AI
   Pricing (Step C.2), update prompt for voice style (Step C.8). No other changes needed.
3. **For us-east-1 deployments today**: Use Path C from the start.

---

### Troubleshooting Nova Sonic (Path C)

| Symptom | Likely cause | Fix |
|---|---|---|
| Voice still sounds like Polly after enabling | Nova Sonic not available in region | Check Bedrock model access console |
| `AccessDeniedException` in Connect logs | Bedrock model access not granted | Step C.3 — request model access |
| Contact drops after Connect assistant block | Unlimited AI Pricing not enabled | Step C.2 — enable unlimited pricing |
| ARIA speaks SSML tags aloud (e.g. `<break>`) | Nova Sonic doesn't support SSML | Remove SSML from ARIA prompt responses |
| Customer interruptions not working | Barge-in disabled | Check flow has no blocking Store customer input blocks |
| Transcript shows garbled text | ASR misrecognition | Add domain vocabulary (banking terms) to Contact Lens settings |
| Response latency is high | Prompt too long or model cross-region latency | Use `eu.*` model IDs, enable prompt caching (Step C.5) |

---

## Understanding Every Block You Used

This section is a reference for the blocks used in this guide.

### Set Logging Behavior
- Stores flow execution events in CloudWatch Logs
- Supports all channels: voice, chat, task, email
- Works in all flow types
- **Cost**: No extra charge — only standard CloudWatch storage charges apply
- **Log retention**: Default 90 days; adjust in CloudWatch → Log groups → `/aws/connect/<instance>`

### Set Voice
- Sets the Amazon Polly TTS voice for the entire flow
- On chat/task contacts: takes the Success branch but has **no effect** (chat is text-only)
- Available voices for en-GB: Amy (F, neural), Brian (M, neural), Emma (F, neural)
- Generative voices have higher quality but incur additional Polly charges

### Set Contact Attributes
- Stores up to 32KB of key-value pairs on the contact
- Attributes persist through the entire contact lifecycle including transfers
- Readable by: Lambdas, AI prompts (`{{$.Custom.<key>}}`), other flow blocks
- **User-defined** attributes: your custom keys
- **System** attributes: Contact ID, channel, ANI, DNIS — read-only, set by Connect

### Check Hours of Operation
- Branches: In hours / Out of hours / Error
- Optional branches: named override schedules (for holidays)
- If no hours are specified in the block, uses the hours from the current working queue
- Agent queues do not have hours — this block will always return Error for an agent queue

### Set Recording and Analytics Behavior
- Enables Contact Lens at the contact level (instance-level enablement is the prerequisite)
- Real-time analytics: transcript available during the call (required for voice AI agents)
- Post-call analytics: transcript and summaries available after the call ends
- Automated interaction recording: records bot/AI interactions (not just agent conversations)
- Chat analytics: real-time + post-chat (no distinction between real-time and post-chat for chat)

### Connect Assistant
- Binds a Q Connect assistant domain to the contact
- Creates a Q Connect session for the contact
- Required to use Connect AI agents (in default/non-customised configuration)
- For customised AI agents: use AWS Lambda function block with a custom Lambda instead
- Supports voice, chat, task, email

### AWS Lambda Function
- Synchronous mode: waits up to 8 seconds for the Lambda to respond before proceeding
- Asynchronous mode: contact proceeds immediately; Lambda runs in background (up to 60 seconds)
- Retries on throttle or 500 errors (up to 3 times within the timeout window)
- **Response validation**: STRING_MAP returns flat key-value pairs; JSON returns nested objects
- Returned values accessible as `$.External.<key>` in subsequent blocks

### Check Contact Attributes
- Branches based on attribute value comparison
- Comparisons: Equals, Greater Than, Less Than, Starts With, Contains
- Case-sensitive: "authenticated" ≠ "Authenticated"
- For NULL check: use a Lambda (this block cannot check for null/missing attributes)

### Play Prompt
- Plays audio prompt or TTS to caller (voice) or sends text message (chat)
- On chat: TTS text is sent as a plain text message (audio is ignored)
- SSML supported for voice: add pauses, emphasis, prosody
- Supported audio formats: WAV (8KHz mono, U-Law encoded), max 50MB, max 5 minutes

### Set Working Queue
- Designates the destination queue for Transfer to Queue
- Must appear before Transfer to Queue in the flow
- Set dynamically using the queue ID (not name): find it in Routing → Queues → open queue → URL

### Transfer to Queue
- Places the contact in the queue; ends the current flow segment
- Branches: At capacity / Error
- The contact is now "in queue" — the queue flow runs (hold music) while waiting for an agent
- When a Connect AI Agent session is active, the AI handles the conversation while in queue

### Disconnect / Hang Up
- Terminates the contact and ends the call/chat
- Should be placed at the end of every terminal path (out of hours, errors, etc.)
- Without this block at terminal paths, contacts "fall off" the flow silently

---

## Troubleshooting

### ARIA doesn't respond to voice

**Check 1**: Is Contact Lens real-time enabled in the flow?
- Open the flow → Block 5 (Set recording and analytics behavior)
- Verify **Real-time analytics** is selected (not just Post-call)

**Check 2**: Is the Connect assistant block connecting to the right assistant?
- In Block 6, verify the ARN matches your Q Connect assistant
- In the AI Agent Designer, verify the ARIA agent is **Published** (not Draft)

**Check 3**: Are there CloudWatch errors?
- CloudWatch → Log groups → `/aws/connect/<instance-id>`
- Find log events at the time of your test call
- Look for error messages on the Connect assistant block or Lambda block

### ARIA doesn't respond to chat

**Check 1**: Contact Lens is not required for chat — the Connect assistant block can process chat
messages directly. If ARIA doesn't respond in chat, the issue is likely:
- The Connect assistant block has an incorrect ARN
- The ARIA AI agent is not published

**Check 2**: Is the chat flow published? Draft flows cannot receive chat contacts.

### Session injector Lambda fails

**Symptom**: ARIA responds but uses no customer context (no name, generic product info).

**Check 1**: Is the Lambda in the same region as Connect? (`eu-west-2`)
**Check 2**: Is the Lambda added to the Connect instance allow-list? (Part A, Step A.2)
**Check 3**: Lambda CloudWatch logs:
- CloudWatch → Log groups → `/aws/lambda/session_injector`
- Look for `ResourceNotFoundException` (Lambda ran before Connect assistant block)
- Look for `AccessDeniedException` (missing `qconnect:UpdateSessionData` IAM permission)

### ARIA says "I don't have information about that" for everything

**Cause**: The MCP gateway tools are not being called. Possible reasons:
1. The ARIA AI Prompt's tool definitions are not correctly configured
2. The MCP domain Lambdas are not returning valid JSON
3. The AgentCore runtime is not reachable from the MCP gateway

**Fix**: Test the MCP gateway directly using the AgentCore playground in the Bedrock console.

### Call drops as soon as it enters the flow

**Cause**: A block has an unconnected output branch (usually an Error branch).

**Fix**: Open the flow and look for any blocks with red/unconnected output branches. Connect every
branch to something — even if it is just a Disconnect block.

---

## Appendix A — Quick Reference: Contact Attributes Injected

The session injector Lambda injects the following variables into the Q Connect session.
These are available in AI prompts as `{{$.Custom.<key>}}`.

| Variable | Description | Example value |
|---|---|---|
| `sessionId` | Q Connect session identifier | `abc123-def456...` |
| `customerId` | Internal customer ID | `CUST-001` |
| `authStatus` | Authentication level | `unauthenticated` / `authenticated` |
| `channel` | Contact channel | `voice` / `chat` |
| `dateTime` | ISO timestamp of contact start | `2025-01-15T14:30:00Z` |
| `instanceId` | Connect instance ID | `a1b2c3d4-...` |
| `locale` | Customer locale | `en-GB` |
| `preferredName` | Customer preferred first name | `Alex` |
| `productSummary` | Natural-language product overview | `"You have a current account and two credit cards."` |
| `productContext` | Serialised JSON of account/card references | `{"accounts": [...], "cards": [...]}` |
| `vulnerabilityContext` | Serialised vulnerability flags (silent, internal only) | `{"financially_vulnerable": false}` |
| `priorSummary` | Summary of previous session (from DynamoDB) | `"Called last week about card dispute."` |

---

## Appendix B — IAM Permissions Checklist

### Session Injector Lambda execution role

| Permission | Reason |
|---|---|
| `qconnect:UpdateSessionData` | Inject variables into the Q Connect session |
| `wisdom:UpdateSessionData` | Legacy alias — same API, required for older integrations |
| `connect:DescribeContact` | Look up the contact to find the Q Connect session ID |
| `logs:CreateLogGroup` | CloudWatch logging |
| `logs:CreateLogStream` | CloudWatch logging |
| `logs:PutLogEvents` | CloudWatch logging |

### Connect service role (managed by AWS)

Amazon Connect automatically creates a service-linked role. Ensure your Connect instance has permission
to invoke your session injector Lambda:

1. Lambda console → your session_injector function → **Configuration** → **Permissions**
2. Under **Resource-based policy**, verify there is a policy allowing:
   ```json
   {
     "Principal": { "Service": "connect.amazonaws.com" },
     "Action": "lambda:InvokeFunction",
     "Condition": {
       "StringEquals": {
         "aws:SourceAccount": "395402194296"
       }
     }
   }
   ```
3. This policy is added automatically when you add the Lambda to the Connect instance allow-list
   (Part A, Step A.2). If it is missing, add it manually.

---

*Guide authored for ARIA Banking Agent — AWS Account `395402194296`, region `eu-west-2`.*
*Always verify against the latest [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/).*
