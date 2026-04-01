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
7. [Part D — Create the ARIA Unified Inbound Flow (Block by Block)](#part-d--create-the-aria-unified-inbound-flow-block-by-block)
    - [Why One Flow for Both Channels?](#why-one-flow-for-both-channels)
    - [Unified Flow Overview](#unified-flow-overview)
    - [Block 1: Set Logging Behavior](#block-1-set-logging-behavior)
    - [Block 2: Check Contact Attributes — Channel Branch](#block-2-check-contact-attributes--channel-branch)
    - [Voice Path: Block 3V – Set Voice](#voice-path-block-3v--set-voice)
    - [Voice Path: Block 4V – Set Contact Attributes](#voice-path-block-4v--set-contact-attributes)
    - [Voice Path: Block 5V – Check Hours of Operation](#voice-path-block-5v--check-hours-of-operation)
    - [Voice Path: Block 6V – Set Recording and Analytics (Real-Time Speech)](#voice-path-block-6v--set-recording-and-analytics-real-time-speech)
    - [Voice Path: Block 7V – Play Prompt (Opening Greeting)](#voice-path-block-7v--play-prompt-opening-greeting)
    - [Chat Path: Block 3C – Set Contact Attributes](#chat-path-block-3c--set-contact-attributes)
    - [Chat Path: Block 4C – Set Recording and Analytics (Chat Analytics)](#chat-path-block-4c--set-recording-and-analytics-chat-analytics)
    - [Block 8: Connect Assistant (Bind ARIA AI Agent)](#block-8-connect-assistant-bind-aria-ai-agent)
    - [Block 9: AWS Lambda Function (Session Injector)](#block-9-aws-lambda-function-session-injector)
    - [Block 10: Set Working Queue](#block-10-set-working-queue)
    - [Block 11: Transfer to Queue](#block-11-transfer-to-queue)
    - [Block 12: Disconnect / Hang Up](#block-12-disconnect--hang-up)
8. [Part E — Connect Channels to the Unified Flow](#part-e--connect-channels-to-the-unified-flow)
9. [Part F — Test Voice (Call the Number)](#part-f--test-voice-call-the-number)
10. [Part G — Set Up Chat Widget](#part-g--set-up-chat-widget)
11. [Part H — Test Chat](#part-h--test-chat)
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
┌─────────────────────────────────────────────────────────────────────────┐
│                         CUSTOMER CHANNELS                               │
│                                                                         │
│   Phone Call (PSTN / DID)              Chat (Web Widget / Mobile App)   │
│          │                                        │                     │
└──────────┼────────────────────────────────────────┼─────────────────────┘
           │                                        │
           ▼                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       AMAZON CONNECT INSTANCE                           │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              ARIA Banking Unified Inbound Flow                    │   │
│  │                                                                  │   │
│  │  [Block 1] Set Logging Behavior       ← ALL channels             │   │
│  │         │                                                        │   │
│  │  [Block 2] Check Channel                                         │   │
│  │    System / Channel / Equals CHAT ← branch point                 │   │
│  │         │                    │                                   │   │
│  │   CHAT branch          No Match (VOICE) branch                   │   │
│  │         │                    │                                   │   │
│  │  [3C] Set Contact Attrs  [3V] Set Voice (Amy, en-GB)             │   │
│  │  [4C] Set Recording      [4V] Set Contact Attrs                  │   │
│  │       (chat analytics)   [5V] Check Hours of Operation           │   │
│  │         │                [6V] Set Recording (real-time)          │   │
│  │         │                [7V] Play Prompt (voice greeting)       │   │
│  │         │                    │                                   │   │
│  │         └──────────┬─────────┘   ← paths converge               │   │
│  │                    │                                             │   │
│  │  [Block 8] Connect Assistant (ARIA AI Agent)  ← ALL channels     │   │
│  │  [Block 9] Lambda Session Injector            ← ALL channels     │   │
│  │  [Block 10] Set Working Queue                 ← ALL channels     │   │
│  │  [Block 11] Transfer to Queue                 ← ALL channels     │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                       ARIA AI Agent                              │   │
│  │   Type: Orchestration  │  System Prompt: ARIA Banking            │   │
│  │   Model: Claude Sonnet │  Guardrail: ARIA Banking Guardrail      │   │
│  │   Tools: AgentCore MCP Gateway (10 domain Lambdas)               │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────┐                           │
│  │    Contact Lens (voice path only)        │                           │
│  │    Real-Time Speech Analytics           │                           │
│  │    Provides live transcript to ARIA      │                           │
│  └─────────────────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│               SESSION INJECTOR LAMBDA (eu-west-2)                       │
│  Reads: ContactId, customerId, authStatus, channel from flow attrs      │
│  Writes: 12 session variables to Q Connect session (both channels)      │
└─────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              ARIA AgentCore MCP Gateway                                 │
│  10 domain Lambdas: accounts, cards, balances, statements...            │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key insight — One flow, two channels**: Amazon Connect officially supports a single contact flow that
handles both voice and chat. You do NOT need separate flows. The `Check contact attributes` block reads
the AWS system attribute `Channel` (automatically set by Connect to `VOICE` or `CHAT`) and routes
each contact down the appropriate setup path. Both paths converge at the Connect Assistant block, where
ARIA takes over the conversation for both voice and chat.

> Official docs: [Personalise experience based on channel](https://docs.aws.amazon.com/connect/latest/adminguide/use-channel-contact-attribute.html)

**Benefits of a unified flow**:
- One flow to maintain, test, and publish — half the operational overhead
- Session injector runs once for both channels — consistent customer context
- ARIA agent configuration is shared — one system prompt, one guardrail, one set of tools
- Analytics and metrics are channel-aware automatically — Contact Lens differentiates by channel

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

## Part D — Create the ARIA Unified Inbound Flow (Block by Block)

You are building a **single contact flow** that handles both voice (phone) and chat customers.
Amazon Connect natively supports this — the same flow can be assigned to both a phone number and a
chat widget. A `Check contact attributes` block reads the system `Channel` attribute and routes each
contact to the right setup steps before converging at ARIA.

> Official docs:
> - [Create and manage contact flows](https://docs.aws.amazon.com/connect/latest/adminguide/create-contact-flow.html)
> - [Personalise experience based on channel](https://docs.aws.amazon.com/connect/latest/adminguide/use-channel-contact-attribute.html)
> - [System attributes available in flows](https://docs.aws.amazon.com/connect/latest/adminguide/connect-attrib-list.html#attribs-system-table)

### Why One Flow for Both Channels?

Before you start building, it is worth understanding why this is the right approach:

| Aspect | Two separate flows | One unified flow |
|---|---|---|
| Maintenance | Two flows to update when ARIA changes | One flow to update |
| Configuration drift | Easy for flows to diverge over time | Always in sync |
| Session injector | Must be kept identical in two places | Single source of truth |
| Testing | Must test both flows separately | One flow to test |
| Publishing | Must publish twice after every change | One publish |

Amazon Connect's official guidance is that "chat activities integrate into your existing contact
center flows and the automation that you built for voice. You build your flows once and reuse them
across multiple channels." — [Amazon Connect Chat documentation](https://docs.aws.amazon.com/connect/latest/adminguide/chat.html)

### Unified Flow Overview

Here is the complete block sequence. Voice-only and chat-only blocks are clearly labelled.

```
[Start]
  │
  ▼
[Block 1]  Set Logging Behavior                ← ALL channels
  │ Success
  ▼
[Block 2]  Check Contact Attributes            ← Branch point: VOICE or CHAT?
           System Namespace → Channel → Equals CHAT
  │                    │
  │ CHAT               │ No Match (VOICE)
  ▼                    ▼
[Block 3C]           [Block 3V]
Set Contact Attrs    Set Voice
(chat, en-GB,        (Amy, en-GB,
 unauthenticated)     neural)
  │                    │
  ▼                    ▼
[Block 4C]           [Block 4V]
Set Recording        Set Contact Attrs
(chat analytics)     (voice, en-GB,
                      unauthenticated)
  │                    │
  │                    ▼
  │                 [Block 5V]
  │                 Check Hours of Operation
  │                  │ In hours  │ Out of hours
  │                  │           ▼
  │                  │       [Block OOH-A]
  │                  │       Play Prompt (closed)
  │                  │           │
  │                  │       [Block OOH-B]
  │                  │       Disconnect
  │                  │
  │                  ▼
  │               [Block 6V]
  │               Set Recording (real-time voice analytics)
  │                  │
  │                  ▼
  │               [Block 7V]
  │               Play Prompt (voice greeting)
  │                  │
  └──────────────────┘
                   │  (both paths join here)
                   ▼
[Block 8]  Connect Assistant (ARIA AI Agent)   ← ALL channels
  │ Success  │ Error
  │          ▼
  │      [Block 8E]  Play Prompt / Send Message (AI unavailable)
  │          │
  │          ▼  → [Block 10] → [Block 11]
  ▼
[Block 9]  AWS Lambda Function (Session Injector)  ← ALL channels
  │ Success / Error / Timeout (all → Block 10)
  ▼
[Block 10]  Set Working Queue (ARIA Banking Agents)  ← ALL channels
  │ Success
  ▼
[Block 11]  Transfer to Queue                    ← ALL channels
  │ At capacity / Error
  ▼
[Block 12]  Disconnect / Hang Up
```

**How the "join" works in Connect**: In the Flow Designer, you simply draw the output arrow from
Block 4C (chat path) AND the output arrow from Block 7V (voice path) both to the same Block 8 input.
Connect accepts multiple inputs to the same block — this is the native "merge" mechanism.

---

### How to Open the Flow Designer

1. In your Connect admin website
2. Left menu → **Routing** → **Flows**
3. Click **Create flow**
4. Select type: **Contact flow (inbound)**
5. Name it: `ARIA Banking Unified Inbound`
6. Click **Create**

The Flow Designer canvas opens. You will see a **Start** entry point at the top left. Every flow
begins here.

> **Tip**: Use the search bar at the top of the block palette (left side) to quickly find blocks
> by name. Drag and drop blocks onto the canvas, then click a block to open its configuration panel.

---

### Block 1: Set Logging Behavior

**What it is**: Enables detailed flow execution logs stored in Amazon CloudWatch.

**Why you need it**: Without logging, when something goes wrong (and it will during testing), you have
no way to see what happened. Flow logs show you exactly which block ran, what decision was made, and
what error occurred. This is the single most useful debugging tool available.

> Official docs: [Set logging behavior](https://docs.aws.amazon.com/connect/latest/adminguide/set-logging-behavior.html)

**Applies to**: Both voice and chat contacts.

**Steps**:
1. Search for **Set logging behavior** in the block palette
2. Drag it onto the canvas
3. Connect the **Start** block's output arrow → this block's input
4. Click the block to open its properties panel
5. Select **Enable flow logging**
6. Click **Save**

**Connect next**: **Success** → Block 2

---

### Block 2: Check Contact Attributes — Channel Branch

**What it is**: Reads a contact attribute and branches the flow based on its value. In this case, it
reads the AWS system attribute `Channel` to determine whether the contact arrived via voice or chat.

**Why this is the key block of the unified flow**: Every contact that enters this flow will be either
a voice call or a chat message. The `Channel` attribute is automatically set by Amazon Connect the
moment the contact is created — you do not need to set it manually. Its value is always:
- `VOICE` — for phone calls
- `CHAT` — for web chat, mobile chat, or SMS
- `TASK` — for tasks (not used here)

By branching on this attribute early in the flow, you can run voice-specific setup steps (Set Voice,
Contact Lens, greeting) only on voice contacts, and chat-specific setup (chat analytics) only on chat
contacts.

> Official docs:
> - [Check contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/check-contact-attributes.html)
> - [System attributes — Channel](https://docs.aws.amazon.com/connect/latest/adminguide/connect-attrib-list.html#attribs-system-table)

**Steps**:
1. Search for **Check contact attributes** in the block palette
2. Drag it onto the canvas
3. Connect Block 1's **Success** → Block 2's input
4. Click the block
5. Under **Attribute to check**:
   - **Namespace**: `System`
   - **Attribute**: `Channel`
6. Under **Conditions to check**:
   - Click **Add condition**
   - **Operator**: `Equals`
   - **Value**: `CHAT`
     *(Type exactly `CHAT` in uppercase — Connect attribute values are case-sensitive)*
7. Click **Save**

**Output branches**:
- **CHAT** (the `Equals CHAT` condition matches) → Block 3C *(chat setup path)*
- **No Match** (everything that is NOT chat — i.e. voice) → Block 3V *(voice setup path)*
- **Error** → Block 3V *(treat errors as voice, the more conservative path)*

> **Why is "No Match" the voice branch?** Because the condition only checks for `CHAT`. Any contact
> that is not chat falls through to `No Match`. In practice, this will always be `VOICE` for this
> flow. Using `No Match` as the voice path is simpler than adding a second condition for `VOICE` and
> is the AWS-recommended pattern for this use case.

---

### Voice Path: Block 3V — Set Voice

**What it is**: Sets the text-to-speech (TTS) language and voice for all spoken prompts in this flow.

**Why it is in the voice path only**: This block controls spoken audio output. Chat contacts receive
text — there is no audio — so this block is irrelevant for chat. While Connect will not error if a
chat contact hits this block, placing it on the voice-only path keeps the flow clean and intentional.

**Why you need it**: Without this block, Connect uses the default US English voice (Joanna). For a UK
banking contact centre, you want a British English voice. This block sets Amy (neural, en-GB) for all
spoken output — including ARIA's AI-generated responses when using the Polly TTS path.

> Official docs: [Set voice](https://docs.aws.amazon.com/connect/latest/adminguide/set-voice.html)

**Steps**:
1. Search for **Set voice** in the block palette
2. Drag it onto the canvas
3. Connect Block 2's **No Match** (voice) → Block 3V's input
4. Click the block
5. Configure:
   - **Language**: `English, British (en-GB)`
   - **Voice**: `Amy` *(British English neural voice from Amazon Polly)*
   - **Override speaking style**: `Conversational`
6. Click **Save**

**Available British English neural voices**: Amy (recommended — warm, professional), Brian (male,
professional), Emma (young, energetic). Amy neural conversational is the standard choice for UK
banking assistants.

**Connect next**: **Success** → Block 4V

---

### Voice Path: Block 4V — Set Contact Attributes

**What it is**: Stores key-value pairs onto the voice contact. These attributes travel with the
contact for its entire lifetime and are readable by Lambdas, the AI prompt, and other blocks.

**Why you need it**:
- `locale` tells the ARIA system prompt which language to respond in (`{{$.locale}}` in the prompt template)
- `channel` lets the session injector know this is a voice contact, enabling voice-specific context enrichment
- `authStatus` seeds the session as `unauthenticated` — ARIA will not claim the caller is authenticated until a downstream Lambda explicitly verifies identity

> Official docs: [Set contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/set-contact-attributes.html)

**Steps**:
1. Search for **Set contact attributes** in the block palette
2. Drag it onto the canvas
3. Connect Block 3V's **Success** → Block 4V's input
4. Click the block
5. Add the following attributes (click **Add another attribute** for each):

| Destination type | Key | Value |
|---|---|---|
| User-defined | `locale` | `en-GB` |
| User-defined | `channel` | `voice` |
| User-defined | `authStatus` | `unauthenticated` |
| User-defined | `customerId` | *(leave blank — auth Lambda will populate)* |

6. Click **Save**

> **Note on `customerId`**: For pre-authenticated callers (e.g. calling from a verified number),
> you can auto-populate `customerId` using the System namespace key `Customer number` (the caller's
> ANI). For most flows, leave it blank — your downstream authentication Lambda sets it.

**Connect next**: **Success** → Block 5V

---

### Voice Path: Block 5V — Check Hours of Operation

**What it is**: Checks if the current time falls within your defined business hours.

**Why it is in the voice path only**: Voice callers experience real-time wait and silence — they
need to be told immediately if lines are closed. Chat is often asynchronous (customers can send a
message and check back later), so hours checking is optional for chat. If you do want business hours
enforcement on chat, you can add this block to the chat path too — it supports both channels.

**Why you need it for voice**: Without this block, voice contacts arriving outside business hours
will be placed in queue indefinitely with no agents to answer them. The caller hears hold music for
hours. This is a poor experience and generates complaints.

> Official docs: [Check hours of operation](https://docs.aws.amazon.com/connect/latest/adminguide/check-hours-of-operation.html)

**Prerequisite — Create your hours of operation first**:
1. Left menu → **Routing** → **Hours of operation**
2. Click **Add hours of operation**
3. Name: `ARIA Banking Hours`
4. Time zone: `Europe/London`
5. Set:
   - Monday–Friday: 08:00 – 20:00
   - Saturday: 09:00 – 17:00
   - Sunday: Closed
6. Click **Save**

**Configure Block 5V**:
1. Search for **Check hours of operation**
2. Drag it onto the canvas
3. Connect Block 4V's **Success** → Block 5V's input
4. Click the block
5. Select **ARIA Banking Hours** from the hours dropdown
6. Click **Save**

**Out-of-hours handler (Blocks OOH-A and OOH-B)**:

These are not main-path blocks — they handle the "closed" case only.

1. Drag a **Play prompt** block onto the canvas
2. Click it → select **Text-to-speech** → enter:
   > *"Thank you for calling Meridian Bank. Our lines are currently closed. We are open Monday to
   > Friday between 8am and 8pm, and Saturday between 9am and 5pm. Please call back during our
   > opening hours, or visit our website at any time."*
3. Drag a **Disconnect / hang up** block and connect the Play prompt's **Success** → Disconnect
4. Connect Block 5V's **Out of hours** → the Play prompt (OOH-A)
5. Connect Block 5V's **Error** → the Play prompt (OOH-A) *(errors default to safe behaviour)*

**Connect the in-hours path**: Block 5V's **In hours** → Block 6V

---

### Voice Path: Block 6V — Set Recording and Analytics Behavior (Real-Time Speech)

**What it is**: Enables Contact Lens on this specific contact and activates real-time speech analytics.

**Why this block is mandatory for ARIA voice**: Contact Lens real-time speech analytics is the engine
that converts the customer's live audio into a text transcript. The Connect AI Agent (ARIA) reads this
transcript to understand what the customer is saying. Without this block, the AI Agent receives no
audio content and cannot generate a meaningful response.

**Why it is in the voice path only**: Contact Lens real-time *speech* analytics is a voice-only
feature. Chat contacts use Contact Lens *chat* analytics (configured in Block 4C), which is separate.
If you place this block on both paths, chat contacts will silently succeed through it but the speech
analytics configuration will have no effect — it is cleaner to keep it voice-only.

> Official docs:
> - [Set recording and analytics behavior](https://docs.aws.amazon.com/connect/latest/adminguide/set-recording-behavior.html)
> - [Enable call recording and speech analytics](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html#enable-callrecording-speechanalytics)

**Steps**:
1. Search for **Set recording and analytics behavior**
2. Drag it onto the canvas
3. Connect Block 5V's **In hours** → Block 6V's input
4. Click the block
5. Under **Enable recording and analytics** → **Voice**:
   - **Agent and customer voice recording**: Turn **On**
   - Choose **Agent and customer** *(both sides of the call are recorded)*
6. Under **Analytics**:
   - **Enable Contact Lens speech analytics**: Turn **On**
   - Select **Real-time analytics** *(NOT post-call — you need real-time for the AI agent to work)*
   - **Language**: `English, British (en-GB)`
   - **Automated interaction call recording**: Turn **On**
     *(This records the ARIA–customer conversation, not just the agent-assisted portion)*
7. Click **Save**

> **Critical detail — Real-time vs Post-call**: ARIA's Connect AI Agent reads the live transcript
> feed from Contact Lens real-time analytics. Post-call analytics only produces a transcript after
> the call ends. If you select post-call by mistake, ARIA will not receive the transcript during the
> call and will be unable to respond.

> **Why "Automated interaction call recording"**: ARIA is an "automated interaction" (a bot). Enabling
> this option captures the entire AI conversation in the recording — useful for quality assurance,
> compliance auditing, and debugging ARIA's responses.

**Connect next**: **Success** → Block 7V

---

### Voice Path: Block 7V — Play Prompt (Opening Greeting)

**What it is**: Plays a spoken welcome message to the caller before ARIA begins the conversation.

**Why it is in the voice path only**: Voice callers need immediate audio feedback from the moment
their call is answered. There is typically a 1–3 second delay as the Connect AI Agent session
initialises. This greeting plays during that initialisation, so the caller hears something right away
rather than silence (which callers often interpret as a dropped call).

For chat, ARIA sends its own opening message as the first chat turn. There is no need for a separate
flow-level greeting in chat — the chat interface visually indicates the session is connecting, and
ARIA's first text message IS the greeting.

> Official docs: [Play prompt](https://docs.aws.amazon.com/connect/latest/adminguide/play.html)

**Steps**:
1. Search for **Play prompt**
2. Drag it onto the canvas
3. Connect Block 6V's **Success** → Block 7V's input
4. Click the block
5. Select **Text-to-speech or chat text**
6. Enter the greeting text:
   ```
   Welcome to Meridian Bank. I'm ARIA, your AI banking assistant.
   I can help you with your accounts, cards, balances, and statements.
   How can I help you today?
   ```
7. Optionally, use SSML for natural pauses:
   ```xml
   <speak>
   Welcome to Meridian Bank. I'm ARIA, your AI banking assistant.
   <break time="300ms"/>
   I can help you with your accounts, cards, balances, and statements.
   How can I help you today?
   </speak>
   ```
8. Click **Save**

> **If you are using Nova Sonic (Path C)**: Remove the SSML markup. Nova Sonic does not support SSML.
> Write the greeting as natural text only. Also note that Nova Sonic overrides the Amy voice set in
> Block 3V for AI responses — but this greeting block (Block 7V) uses Polly directly for the
> pre-session announcement. They are separate audio paths.

**Connect next**: **Success** → Block 8 *(the first shared block — this is the "join" point)*

---

### Chat Path: Block 3C — Set Contact Attributes

**What it is**: Stores key-value attributes onto the chat contact — the chat equivalent of Voice
Block 4V.

**Why the values differ from the voice version**: The `channel` attribute is set to `chat` so that
the session injector (Block 9) knows to apply chat-specific context enrichment. Everything else is
identical — same locale, same auth starting point.

> Official docs: [Set contact attributes](https://docs.aws.amazon.com/connect/latest/adminguide/set-contact-attributes.html)

**Steps**:
1. Search for **Set contact attributes** in the block palette
2. Drag it onto the canvas
3. Connect Block 2's **CHAT** branch → Block 3C's input
4. Click the block
5. Add the following attributes:

| Destination type | Key | Value |
|---|---|---|
| User-defined | `locale` | `en-GB` |
| User-defined | `channel` | `chat` |
| User-defined | `authStatus` | `unauthenticated` |
| User-defined | `customerId` | *(leave blank — auth logic will populate)* |

6. Click **Save**

**Connect next**: **Success** → Block 4C

---

### Chat Path: Block 4C — Set Recording and Analytics Behavior (Chat Analytics)

**What it is**: Enables Contact Lens chat analytics for this chat contact.

**Why it is separate from Block 6V**: Voice analytics (Block 6V) and chat analytics are different
features in Contact Lens and must be configured separately. This block specifically enables chat
transcript analytics, sentiment analysis, and post-chat AI summaries.

**Is this block required?**: Technically optional — the Connect AI Agent works without it. However,
it is strongly recommended because:
1. Contact Lens chat analytics gives you a full conversation transcript in the Connect analytics dashboard
2. Sentiment analysis for each chat turn helps you identify frustrated customers
3. AI-generated post-chat summaries appear automatically in the Contact details view
4. PII redaction in chat transcripts helps meet data protection requirements (GDPR/FCA)

> Official docs:
> - [Set recording and analytics behavior](https://docs.aws.amazon.com/connect/latest/adminguide/set-recording-behavior.html)
> - [Enable chat analytics](https://docs.aws.amazon.com/connect/latest/adminguide/enable-analytics.html#enable-chatanalytics)

**Steps**:
1. Search for **Set recording and analytics behavior**
2. Drag it onto the canvas
3. Connect Block 3C's **Success** → Block 4C's input
4. Click the block
5. Under **Chat** (NOT Voice):
   - **Enable Contact Lens conversational analytics**: Turn **On**
   - Select **Enable chat analytics**
   - **Language**: `English, British (en-GB)`
6. Under **Redaction** (recommended for banking):
   - Enable **Redact sensitive data** *(removes PII from stored transcripts)*
7. Click **Save**

**Connect next**: **Success** → Block 8 *(the join point — same block the voice path ends at)*

> **The join**: At this point, both paths converge. Block 4C (chat) and Block 7V (voice) both
> connect their **Success** outputs to the same **Block 8: Connect Assistant** input. In the
> Flow Designer, you will draw two separate arrows both pointing to Block 8's left-side input.

---

### Block 8: Connect Assistant (Bind ARIA AI Agent)

**What it is**: Associates the ARIA Connect AI Agent with this contact and creates a Q Connect AI
session. This is the block that "activates" ARIA for both voice and chat contacts.

**Why it is placed here (after channel setup)**: The channel-specific blocks (Contact Lens for voice,
chat analytics for chat) must run before the AI session is created. The AI agent session reads the
Contact Lens real-time feed for voice and the chat transcript for chat. Getting the analytics
pipeline started first ensures the AI session has a data feed to work with.

**This block works identically for voice and chat** — Connect automatically routes the contact's
transcription feed (voice transcript from Contact Lens, or chat message stream) to the ARIA session.

> Official docs:
> - [Connect assistant block](https://docs.aws.amazon.com/connect/latest/adminguide/connect-assistant-block.html)
> - [Associate an AI agent with a flow](https://docs.aws.amazon.com/connect/latest/adminguide/create-ai-agents.html#associate-ai-agent-flow)

**Steps**:
1. Search for **Connect assistant**
2. Drag it onto the canvas
3. Connect Block 7V's **Success** (voice path) → Block 8's input
4. Also connect Block 4C's **Success** (chat path) → Block 8's same input
   *(Both arrows go into Block 8's input — this is the join)*
5. Click the block
6. Under the **Config** tab:
   - **Amazon Connect assistant domain ARN**: Paste your Q Connect assistant ARN
     (format: `arn:aws:wisdom:eu-west-2:395402194296:assistant/<assistant-id>`)
   - **Orchestration AI agent**: Select your published **ARIA Orchestration** agent
7. Click **Save**

> **How to find your assistant ARN**:
> 1. Connect admin website → left menu → **AI Agent Designer**
> 2. Click the gear icon → **Settings** or **Assistant details**
> 3. Copy the ARN from the details panel

**Connect next**:
- **Success** → Block 9
- **Error** → a **Play prompt** / **Send message** block with a fallback message:
  *"I'm sorry, our AI assistant is currently unavailable. Connecting you to an agent now."*
  → then → Block 10 → Block 11 *(route directly to human agent queue)*

---

### Block 9: AWS Lambda Function (Session Injector)

**What it is**: Calls the `session_injector` Lambda, which writes 12 session variables into the Q
Connect AI session created by Block 8. These variables populate the ARIA system prompt template,
giving ARIA knowledge of who the customer is before the first utterance.

**Why it must come AFTER Block 8**: The Q Connect session does not exist until Block 8 creates it.
If you run the injector before Block 8, the Lambda throws `ResourceNotFoundException` because there
is no session to write to.

**Why it works for both channels**: The session injector is channel-aware. It reads the `channel`
contact attribute (set in Block 4V or Block 3C) and applies the correct enrichment profile. Voice
contacts get full CRM lookup; chat contacts get the same data with chat-specific context flags.

> Official docs:
> - [AWS Lambda function block](https://docs.aws.amazon.com/connect/latest/adminguide/invoke-lambda-function-block.html)
> - [Add customer data to an AI agent session](https://docs.aws.amazon.com/connect/latest/adminguide/ai-agent-session.html)

**Steps**:
1. Search for **AWS Lambda function**
2. Drag it onto the canvas
3. Connect Block 8's **Success** → Block 9's input
4. Click the block
5. **Select an action**: `Invoke Lambda`
6. **Select a function**: Choose `session_injector` from the dropdown
   *(If not visible, return to Part A Step A.2 and add it to the instance allow-list)*
7. **Execution mode**: **Synchronous**
   *(The flow waits for the Lambda to finish before proceeding — the session data must be injected
   before ARIA starts responding to the first customer utterance)*
8. **Timeout**: `8 seconds` *(maximum for synchronous invocation)*
9. **Response validation**: `STRING_MAP`
10. Under **Send parameters** — pass these contact attributes to the Lambda:

| Key | Namespace | Attribute |
|---|---|---|
| `contactId` | System | `ContactId` |
| `customerId` | User-defined | `customerId` |
| `authStatus` | User-defined | `authStatus` |
| `locale` | User-defined | `locale` |
| `channel` | User-defined | `channel` |

11. Click **Save**

**Connect next** (all three branches → Block 10):
- **Success** → Block 10
- **Error** → Block 10 *(continue even if injection fails — ARIA will work without personalisation)*
- **Timeout** → Block 10 *(same — do not drop the contact over a slow enrichment call)*

> **Why wire Error and Timeout to success path?** The session injector provides personalisation
> enrichment, not critical flow control. If it fails, ARIA can still serve the customer — it just
> won't know the customer's name, products, or recent activity. Dropping a call because a CRM lookup
> timed out would be a far worse outcome.

---

### Block 10: Set Working Queue

**What it is**: Designates which agent queue this contact belongs to if escalation is needed.

**Why you must set this before Transfer to Queue**: Block 11 (Transfer to queue) looks up whatever
queue was last set as the "working queue." If no queue has been set, Transfer to queue fails with an
error. Setting the working queue is a required prerequisite step. This is the single most common
beginner mistake in Connect flows — adding Transfer to queue without this block first.

**Works identically for voice and chat**: The same agent queue handles both voice and chat contacts.
Agents see them as separate contact types in the CCP (Contact Control Panel) but they sit in the
same queue.

> Official docs: [Set working queue](https://docs.aws.amazon.com/connect/latest/adminguide/set-working-queue.html)

**Prerequisite — Create a dedicated queue** (if you haven't already):
1. Left menu → **Routing** → **Queues**
2. Click **Add queue**
3. Name: `ARIA Banking Agents`
4. Description: `Queue for contacts escalated from ARIA`
5. Hours of operation: `ARIA Banking Hours`
6. Outbound caller ID number: your claimed phone number
7. Click **Save**

**Configure Block 10**:
1. Search for **Set working queue**
2. Drag it onto the canvas
3. Connect Block 9's **Success / Error / Timeout** → Block 10's input
4. Click the block
5. Select **ARIA Banking Agents** (or `BasicQueue` if using the default)
6. Click **Save**

**Connect next**: **Success** → Block 11

---

### Block 11: Transfer to Queue (The Handover Point)

**What it is**: Places the contact in the queue. With a Connect AI Agent session active, ARIA manages
the conversation directly in the queue. If ARIA determines the customer needs a human agent, the
contact is escalated to the next available agent — it is already in queue, so no additional transfer
is needed.

**Why this is the final block in an AI agent flow**: Once the contact enters the queue with an active
ARIA session, the flow's job is done. It has:
1. Logged the flow execution (Block 1)
2. Detected the channel and branched accordingly (Block 2)
3. Set up channel-specific configuration (Blocks 3V–7V for voice, 3C–4C for chat)
4. Created the AI session (Block 8)
5. Injected customer context (Block 9)
6. Set the escalation queue (Block 10)

**Now ARIA drives the conversation** — for both voice and chat.

> Official docs: [Transfer to queue](https://docs.aws.amazon.com/connect/latest/adminguide/transfer-to-queue.html)

**Steps**:
1. Search for **Transfer to queue**
2. Drag it onto the canvas
3. Connect Block 10's **Success** → Block 11's input
4. Click the block
5. Under the **Transfer to queue** tab — no additional configuration needed; it uses the working
   queue set in Block 10
6. Click **Save**

**Error branches**:
- **At capacity** → a **Play prompt** (voice) / **Send message** (chat) block:
  *"Our lines are currently busy. Please try again shortly."*
  → **Disconnect / hang up**
- **Error** → same fallback → **Disconnect / hang up**

---

### Block 12: Disconnect / Hang Up

**What it is**: Terminates the contact cleanly.

**Why you need it**: Every error path, the out-of-hours path, and the at-capacity path must end
somewhere. The Disconnect block is the clean terminal. Without it, contacts that hit unconnected
branches will drop silently — the caller hears a click and the call ends without explanation.

> Official docs: [Disconnect / hang up](https://docs.aws.amazon.com/connect/latest/adminguide/disconnect-hang-up.html)

**Steps**:
1. Search for **Disconnect / hang up**
2. Drag it onto the canvas (you may use one shared Disconnect block for all error paths, or multiple)
3. Connect:
   - Out-of-hours Play prompt (Block OOH-A) **Success** → Disconnect
   - At-capacity Play prompt **Success** → Disconnect
   - Block 8 (Connect assistant) **Error** fallback → (escalation path) → ...eventually reaches Disconnect if no agents available
   - Any other unconnected error branches → Disconnect

---

### Save and Publish the Unified Flow

1. Click **Save** (top right) — saves a draft
2. Review the flow canvas to ensure:
   - Every block has its output branches connected (no unconnected orange/red arrows)
   - Both Block 7V (voice) and Block 4C (chat) connect into Block 8
   - Block 9 Error and Timeout also connect to Block 10 (not left dangling)
3. Click **Publish** (top right) — makes the flow live

> **Important**: Only published flows can receive live contacts. Draft flows will not answer calls
> or accept chat connections. You must publish after every change you want to go live.

> **After publishing**: If you need to make changes, edit the draft and re-publish. Your published
> version handles live contacts while you work on the draft.

---

## Part E — Connect Channels to the Unified Flow

With the `ARIA Banking Unified Inbound` flow published, you now assign it to both channels. This is
the key difference from the old two-flow approach — one published flow, one assignment to the phone
number and a second assignment to the chat widget. Both channels hit the same entry point.

> Official docs:
> - [Assign a phone number to a flow](https://docs.aws.amazon.com/connect/latest/adminguide/associate-claimed-number-contact-flow.html)
> - [Set up your customer's chat experience](https://docs.aws.amazon.com/connect/latest/adminguide/chat.html)

### Step E.1 — Assign the Phone Number to the Unified Flow

Voice calls to your claimed phone number will now enter the unified flow. The flow's Channel branch
(Block 2) will route them to the voice path automatically.

1. Left menu → **Channels** → **Phone numbers**
2. Click the phone number you claimed in Part C
3. Under **Contact flow / IVR**: Select **ARIA Banking Unified Inbound**
4. Click **Save**

> After saving, any call to this number will immediately enter the unified flow (no delay).

### Step E.2 — Assign the Chat Widget to the Unified Flow

Chat contacts initiated via the chat widget will enter the same flow. Block 2 will detect `Channel =
CHAT` and route them to the chat path.

1. Left menu → **Channels** → **Chat**
2. Click **Add a chat widget** (or edit an existing widget)
3. Configure:
   - **Widget name**: `ARIA Banking Chat`
   - **Contact flow**: Select **ARIA Banking Unified Inbound** ← same flow as the phone number
   - **Website domains**: Add your website URL (e.g. `https://app.meridianbank.co.uk`)
     *(You must whitelist your domain, or the widget script will be blocked by the browser)*
4. Customise colours and widget title if desired
5. Click **Create widget** (or **Save**)
6. Copy the **Widget snippet code** — the JavaScript `<script>` tag

### Step E.3 — Embed the Chat Widget in Your Website

Add the snippet before the closing `</body>` tag:

```html
<!-- ARIA Banking Chat Widget -->
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

Replace `YOUR-WIDGET-ID` and `YOUR-SNIPPET-ID` with the values shown in the Connect console after
creating the widget.

---

## Part F — Test Voice (Call the Number)

1. Dial the phone number you assigned to the unified flow
2. You should hear the Amy voice welcome greeting (Block 7V)
3. After the greeting, say something like: **"I'd like to check my account balance"**
4. ARIA should respond to your query

### What to check if voice does not work

1. Connect admin website → **Analytics** → **Contact search**
2. Find your test call by timestamp
3. Click the Contact ID → **Flow logs**
4. Look for the last block that ran and any error messages

| Symptom | Likely cause | Fix |
|---|---|---|
| Call drops immediately | Flow not published | Re-publish the unified flow |
| No greeting plays | Set voice block missing or wrong language | Check Block 3V — Amy en-GB selected? |
| Phone goes to wrong flow | Old phone number assignment not updated | Re-check Part E Step E.1 |
| Greeting plays but ARIA silent | Contact Lens real-time not enabled | Check Block 6V — real-time analytics on? |
| ARIA responds but no customer context | Session injector failed | Check Lambda CloudWatch logs for `session_injector` |
| "Connect assistant not found" | Wrong ARN or unpublished agent | Re-publish ARIA agent and update Block 8 ARN |
| Channel check block showing VOICE going to CHAT | Block 2 condition misconfigured | Confirm value is `CHAT` (uppercase), namespace is `System`, attribute is `Channel` |

---

## Part G — Set Up and Test Chat

### Step G.1 — Quick Test Without a Website

Before embedding the widget, test the chat connection directly from the Connect admin console:

1. Left menu → **Dashboard** → **Test chat**
2. From the dropdown, select **ARIA Banking Unified Inbound** ← your unified flow
3. Click **Start chat**
4. Type: **"Hello, I need help with my account"**
5. ARIA should respond within 2–3 seconds

> **What happens when you click Start chat**: Connect creates a test chat contact and sends it through
> the unified flow. Block 2 detects `Channel = CHAT`, the contact follows the chat path (Blocks 3C,
> 4C), then reaches Block 8 (Connect assistant). ARIA's first text reply is its opening greeting.

### Step G.2 — Test the Chat Widget on Your Website

1. Embed the widget snippet (from Part E Step E.3) into your test page
2. Load the page — you should see the chat button (blue circle, bottom right)
3. Click the chat button
4. Type: **"Hello ARIA"**
5. ARIA responds

### What to check if chat does not work

| Symptom | Likely cause | Fix |
|---|---|---|
| Widget does not appear on page | Domain not whitelisted in widget | Add your domain in Channels → Chat → widget settings |
| Chat starts but ARIA does not reply | Connect assistant block error | Check CloudWatch Flow logs — look for Block 8 errors |
| Chat goes to wrong path (voice steps run) | Block 2 condition wrong | Check Block 2 — value should be `CHAT` not `chat` (case matters) |
| Session injector fails for chat | Lambda policy missing chat permission | Check session_injector CloudWatch logs |
| Chat widget says "Chat ended" immediately | Flow published but error before queue | Check flow logs for the test contact |

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

### Step C.6 — Configure the Unified Flow for Nova Sonic (Path C)

The ARIA Banking Unified Inbound flow works with Nova Sonic with minimal changes. When Nova Sonic
is active, the audio pipeline upgrades automatically inside Connect. The flow structure remains
identical — you only need to verify two blocks in the **voice path** of the unified flow.

**Why the unified flow works for Nova Sonic**: Nova Sonic is a voice-channel technology. The unified
flow routes voice contacts through Blocks 3V–7V (the voice path) which includes Contact Lens
real-time analytics (Block 6V) and the greeting (Block 7V). Nova Sonic replaces Polly as the TTS
engine after the AI session starts — the flow blocks themselves do not change.

**Adjustment 1: Block 6V — Set Recording and Analytics Behavior — confirm both options enabled**

When Nova Sonic is active, you should ensure Block 6V (in the voice path) has both real-time
analytics AND automated interaction recording enabled:

1. In the unified flow canvas, click **Block 6V** (Set recording and analytics behavior — on the voice path)
2. Under **Voice**:
   - **Agent and customer voice recording**: **On** → **Agent and customer**
   - **Contact Lens speech analytics**: **On** → **Real-time analytics**
   - **Language**: `English, British (en-GB)`
   - **Automated interaction call recording**: **On**
     *(Critical for Nova Sonic path — records the full AI conversation for audit and quality review)*
3. Under **Contact Lens Generative AI capabilities** (if visible):
   - Enable **Contact summary** — generates AI post-call summaries using Nova Pro
4. Click **Save**

> Why: Even with Nova Sonic handling audio natively, Contact Lens still generates the transcript and
> analytics. The transcript is what ARIA's LLM layer reads to understand context. Nova Sonic handles
> audio I/O; Contact Lens handles analytics. Both are needed.

**Adjustment 2: Block 3V — Set Voice — keep it, do not remove it**

When Nova Sonic is the active speech model, the Set Voice block (Block 3V in the voice path) voice
selection has no effect on the actual audio output — Nova Sonic overrides the Polly voice. However,
**keep Block 3V in place** because:
- It controls the Polly fallback voice if Nova Sonic is unavailable
- It sets the language used by any Lex components you may add later
- Removing it risks audio silence on voice contacts if Nova Sonic is temporarily unavailable

No other flow changes are needed. Block 8 (Connect assistant), Block 9 (Lambda session injector),
Block 10 (Set working queue), and Block 11 (Transfer to queue) all work identically with Nova Sonic.
The chat path (Blocks 3C, 4C) is completely unaffected by Nova Sonic.

**Adjustment 3: Block 7V — Play Prompt greeting — remove SSML markup**

If you added SSML to the Block 7V greeting (e.g. `<speak>` tags with `<break time="300ms"/>`),
remove the SSML when using Nova Sonic. Nova Sonic does not process SSML — it will read the tags
as literal text. Use plain natural language only:

```
Welcome to Meridian Bank. I'm ARIA, your AI banking assistant.
I can help you with your accounts, cards, balances, and statements.
How can I help you today?
```

> Note: This Block 7V greeting still uses Polly (the flow-level TTS) because it runs before the
> ARIA session fully activates. Nova Sonic takes over only once the AI agent session is running —
> i.e. after Block 8 completes. So the greeting uses Polly Amy; ARIA's conversational responses
> use Nova Sonic.

After making these adjustments, save and re-publish the unified flow.

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
    │                     Parts D–G of this guide
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

### Check Contact Attributes — Channel Branch (Block 2 in unified flow)
- The core mechanism for a single flow that handles multiple channels
- Uses **System** namespace, **Channel** attribute (automatically set by Connect)
- Valid values: `VOICE`, `CHAT`, `TASK`, `EMAIL`
- Always uppercase — condition checks are case-sensitive
- **No Match** branch fires for any value not matching your conditions (used as the voice branch here)
- Multiple conditions can be added (e.g. also check for `TASK` if needed)
- Official docs: [Use channel contact attribute](https://docs.aws.amazon.com/connect/latest/adminguide/use-channel-contact-attribute.html)

### Set Voice
- Sets the Amazon Polly TTS voice for the entire flow
- On chat/task contacts: takes the Success branch but has **no effect** (chat is text-only)
- Available voices for en-GB: Amy (F, neural), Brian (M, neural), Emma (F, neural)
- Generative voices have higher quality but incur additional Polly charges
- When Nova Sonic is active, this block's voice selection is overridden for AI responses (Polly only for flow-level prompts)

### Set Contact Attributes
- Stores up to 32KB of key-value pairs on the contact
- Attributes persist through the entire contact lifecycle including transfers
- Readable by: Lambdas, AI prompts (`{{$.Custom.<key>}}`), other flow blocks
- **User-defined** attributes: your custom keys (e.g. `locale`, `channel`, `authStatus`)
- **System** attributes: Contact ID, channel, ANI, DNIS — read-only, set by Connect

### Check Hours of Operation
- Branches: In hours / Out of hours / Error
- Optional branches: named override schedules (for holidays)
- If no hours are specified in the block, uses the hours from the current working queue
- Supports voice, chat, task — can be used on both the voice and chat paths of a unified flow

### Set Recording and Analytics Behavior
- Enables Contact Lens at the contact level (instance-level enablement is the prerequisite)
- **Voice real-time analytics**: transcript available during the call — required for voice AI agents
- **Voice post-call analytics**: transcript and summaries available after the call ends
- **Automated interaction recording**: records bot/AI interactions (not just agent conversations)
- **Chat analytics**: real-time + post-chat combined (no distinction between real-time and post-chat for chat)
- In the unified flow, use this block TWICE: once in the voice path (Block 6V), once in the chat path (Block 4C)

### Connect Assistant
- Binds a Q Connect assistant domain to the contact
- Creates a Q Connect session for the contact
- Required to use Connect AI agents (in default/non-customised configuration)
- For customised AI agents: use AWS Lambda function block with a custom Lambda instead
- Supports voice, chat, task, email — single block serves both channels in the unified flow

### AWS Lambda Function
- Synchronous mode: waits up to 8 seconds for the Lambda to respond before proceeding
- Asynchronous mode: contact proceeds immediately; Lambda runs in background (up to 60 seconds)
- Retries on throttle or 500 errors (up to 3 times within the timeout window)
- **Response validation**: STRING_MAP returns flat key-value pairs; JSON returns nested objects
- Returned values accessible as `$.External.<key>` in subsequent blocks

### Play Prompt
- Plays audio prompt or TTS to caller (voice) or sends text message (chat)
- On chat: TTS text is sent as a plain text message (audio is ignored)
- SSML supported for voice: add pauses, emphasis, prosody (NOT supported with Nova Sonic)
- Supported audio formats: WAV (8KHz mono, U-Law encoded), max 50MB, max 5 minutes
- In the unified flow, Block 7V (voice greeting) is in the voice path only — ARIA sends its own greeting for chat

### Set Working Queue
- Designates the destination queue for Transfer to Queue
- Must appear before Transfer to Queue in the flow
- Set dynamically using the queue ID (not name): find it in Routing → Queues → open queue → URL

### Transfer to Queue
- Places the contact in the queue; ends the current flow segment
- Branches: At capacity / Error
- The contact is now "in queue" — the queue flow runs (hold music/wait) while waiting for an agent
- When a Connect AI Agent session is active, the AI handles the conversation while in queue
- Single Transfer to Queue block at the end of the unified flow handles both voice and chat contacts

### Disconnect / Hang Up
- Terminates the contact and ends the call/chat
- Should be placed at the end of every terminal path (out of hours, errors, etc.)
- Without this block at terminal paths, contacts "fall off" the flow silently

---

## Troubleshooting

### ARIA doesn't respond to voice

**Check 1**: Is Contact Lens real-time enabled in the voice path of the unified flow?
- Open the unified flow canvas → find **Block 6V** (Set recording and analytics behavior — on the
  voice/No Match branch)
- Verify **Real-time analytics** is selected (not just Post-call)

**Check 2**: Is the Connect assistant block (Block 8) connecting to the right assistant?
- In Block 8, verify the ARN matches your Q Connect assistant
- In the AI Agent Designer, verify the ARIA agent is **Published** (not Draft)

**Check 3**: Is the contact entering the voice path (not the chat path)?
- In CloudWatch flow logs, look for Block 2's routing decision
- It should show `No Match` for voice — if it shows `CHAT`, the Channel attribute has an unexpected value

**Check 4**: Are there CloudWatch errors?
- CloudWatch → Log groups → `/aws/connect/<instance-id>`
- Find log events at the time of your test call
- Look for error messages on the Connect assistant block or Lambda block

### ARIA doesn't respond to chat

**Check 1**: Did the chat contact hit the CHAT branch?
- In CloudWatch flow logs, Block 2 should show the `CHAT` condition matched
- If it shows `No Match` instead, verify Block 2 condition value is `CHAT` (uppercase)

**Check 2**: Contact Lens is not required for chat — the Connect assistant block processes chat
messages directly. If ARIA doesn't respond in chat, the issue is likely:
- Block 8 (Connect assistant) has an incorrect ARN
- The ARIA AI agent is not published

**Check 3**: Is the unified flow published? Draft flows cannot receive any contacts (voice or chat).

**Check 4**: Is the chat widget pointing to the unified flow?
- Channels → Chat → edit widget → verify **Contact flow** is `ARIA Banking Unified Inbound`

### Session injector Lambda fails

**Symptom**: ARIA responds but uses no customer context (no name, generic product info).

**Check 1**: Is the Lambda in the same region as Connect? (`eu-west-2`)
**Check 2**: Is the Lambda added to the Connect instance allow-list? (Part A, Step A.2)
**Check 3**: Lambda CloudWatch logs:
- CloudWatch → Log groups → `/aws/lambda/session_injector`
- Look for `ResourceNotFoundException` (Lambda ran before Connect assistant block — Block 9 must come AFTER Block 8)
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
branch to something — even if it is just a Disconnect block. In the unified flow, this often happens
on the out-of-hours blocks or the Block 8 Error branch.

### Voice goes to chat path / chat goes to voice path

**Cause**: Block 2 condition is misconfigured.

**Fix**: Click Block 2 → verify:
- Namespace: **System** (not User-defined)
- Attribute: **Channel**
- Operator: **Equals**
- Value: `CHAT` (uppercase, no spaces)
- No Match = voice path

### SSML tags being read aloud

**Cause**: Nova Sonic does not process SSML. If you used SSML in the Block 7V greeting or in ARIA's prompt, Nova Sonic reads them as literal text.

**Fix**: Remove all SSML markup (`<speak>`, `<break>`, `<prosody>`) from Block 7V and from the ARIA prompt responses. Use natural language only.

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
