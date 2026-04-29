# ARIA — Callback & Chat-to-Voice Context Transfer Guide

**For novices. Every step is explained with what to do and why.**

> This guide covers two features that build on the existing ARIA Connect AI Agent setup:
> 1. **Customer-requested callback** — the customer asks to be called back instead of waiting
> 2. **Chat-to-voice context carry-over** — when a customer transfers from chat to a voice call,
>    ARIA picks up the conversation exactly where it left off in chat
>
> Before reading this guide, you should understand the existing `ARIA Banking Unified Inbound`
> flow and how the Connect AI Agent works. That is documented in
> `docs/aria-connect-voice-chat-novice-guide.md`.

---

## Table of Contents

1. [How ARIA Works — The Current Architecture](#1-how-aria-works--the-current-architecture)
2. [How ARIA Signals Connect to Do Things](#2-how-aria-signals-connect-to-do-things)
3. [Feature 1 — Customer-Requested Callback](#3-feature-1--customer-requested-callback)
   - [3a. Queue-Full / Out-of-Hours Callback (Inbound Voice)](#3a-queue-full--out-of-hours-callback-inbound-voice)
   - [3b. Chat-to-Voice Callback (Customer Asks ARIA)](#3b-chat-to-voice-callback-customer-asks-aria)
4. [Feature 2 — Chat-to-Voice Context Transfer (ARIA Remembers the Chat)](#4-feature-2--chat-to-voice-context-transfer-aria-remembers-the-chat)
5. [What Is Already Built vs. What Needs to Be Added](#5-what-is-already-built-vs-what-needs-to-be-added)
6. [Step-by-Step — Changes to the Unified Inbound Flow](#6-step-by-step--changes-to-the-unified-inbound-flow)
7. [Step-by-Step — New Flow: ARIA-Callback-Offer](#7-step-by-step--new-flow-aria-callback-offer)
8. [Step-by-Step — New Flow: ARIA-Outbound-Callback](#8-step-by-step--new-flow-aria-outbound-callback)
9. [Testing End-to-End](#9-testing-end-to-end)
10. [Troubleshooting](#10-troubleshooting)
11. [Component Reference](#11-component-reference)

---

## 1. How ARIA Works — The Current Architecture

ARIA is a **Connect AI Agent** — an Orchestration-type agent configured inside Amazon Connect's
**AI Agent Designer**. It is NOT a separate service running somewhere else. It lives inside your
Connect instance and uses:

- An **AI Prompt** (the ARIA Banking Orchestration Prompt you published in AI Agent Designer)
- An **AI Guardrail** (safety layer filtering inputs and outputs)
- An **AI model** (Claude Sonnet, accessed cross-region via the `eu.` prefix)
- **Tools** — Lambda functions connected to the ARIA AgentCore MCP Gateway for account lookups,
  card queries, PII handling, escalation, and channel transfer

> **What is the AgentCore MCP Gateway?** It is a single HTTPS endpoint deployed by
> `scripts/deploy_mcp_gateway.sh`. ARIA calls this gateway using the MCP protocol. The gateway
> routes each tool call to the correct domain Lambda (accounts, cards, mortgages, etc.). ARIA
> does not call individual Lambdas directly — it calls one gateway endpoint and the gateway
> handles routing. This keeps ARIA's tool list clean and maintainable.

### The Current Deployed Flow — 12 Blocks

The `ARIA Banking Unified Inbound` flow handles both voice AND chat contacts in a single flow.
Here is the complete structure:

```
[Block 1]  Set Logging Behaviour         — enables CloudWatch flow logs
    ↓
[Block 2]  Check Contact Attributes      — Channel == CHAT? (branches here)
    │ CHAT branch                         │ No Match (VOICE) branch
    ↓                                     ↓
[Block 3C] Set Contact Attrs (chat)      [Block 3V] Set Voice (Amy, en-GB)
[Block 4C] Set Recording (chat)          [Block 4V] Set Contact Attrs (voice)
    │                                     [Block 5V] Check Hours of Operation
    │                                     [Block 6V] Set Recording (real-time)
    │                                     [Block 7V] Play Prompt (voice greeting)
    └──────────────┬──────────────────────┘
                   │  ← both paths join here
                   ↓
[Block 8]  Connect Assistant             — ARIA AI Agent (Orchestration) handles
           (ARIA AI Agent)                 the full conversation for ALL channels
                   ↓ (after ARIA's session ends)
[Block 9]  AWS Lambda: Session Injector  — injects customer context into the
           (session_injector_qconnect)     Q Connect session for ARIA
                   ↓ (Success / Error / Timeout — all route to Block 10)
[Block 10] Set Working Queue             — sets ARIA Banking Agents queue
                   ↓
[Block 11] Transfer to Queue             — places contact in queue for human agents
                   ↓ (At capacity / Error)
[Block 12] Disconnect / Hang Up
```

### The session injector and Block 8 — how context gets to ARIA

Block 8 (Connect Assistant) **creates the Q Connect AI session** the moment the contact reaches it.
Block 9 (session injector Lambda) then runs **immediately after** — it writes customer context
(name, products, auth status, prior summaries, prior transcripts) into that Q Connect session using
the AWS Q Connect API. ARIA reads this context via `{{$.Custom.*}}` template variables in its
prompt. This is how ARIA knows who the customer is on the very first turn.

> **Why does Block 9 run after Block 8?** The Q Connect session does not exist until Block 8
> creates it. The injector Lambda needs the session ID (returned by Block 8) to write context
> into it. If Block 9 ran before Block 8, there would be no session to inject into.

---

## 2. How ARIA Signals Connect to Do Things

ARIA is an AI agent inside the Connect Assistant block. It cannot directly re-route a call or invoke
a Lambda. Instead, it signals Connect by:

1. **Returning an intent** — ARIA outputs a named Lex intent string alongside its response. The
   Connect flow checks these intents **after** Block 8 exits.
2. **Setting contact attributes** — ARIA's tools (running via the MCP Gateway) can call
   `connect:UpdateContactAttributes` to set key-value pairs on the contact. The flow reads
   these in subsequent blocks.
3. **Populating the Escalate tool's schema** — the built-in **Escalate (Return to Control)** tool
   causes the Connect Assistant block to exit. ARIA fills in structured fields (topicCategory,
   escalationReason, conversationSummary, customerIntent) as it does so. These are stored as
   Lex session attributes which the flow can read immediately after Block 8 exits.

### The three signal types used today

| Signal type | How ARIA sends it | What the flow does |
|---|---|---|
| **Escalate** (Return to Control) | ARIA calls the Escalate tool with structured fields | Block 8 exits → Check Contact Attrs detects `Tool = Escalate` → routing Lambda → Transfer to Queue |
| **CollectCardDetails** intent | ARIA returns this as a Lex intent name | Block 8 exits → intent check → Transfer to DTMF secure capture sub-flow |
| **RequestCallback** intent | ARIA returns this as a Lex intent name + sets `callbackReason` | Block 8 exits → intent check → `ARIA-Callback-Offer` flow (to be created) |

### What happens AFTER Block 8 exits — the current post-AI logic

When ARIA's Connect Assistant session ends (because ARIA called the Escalate tool, returned an intent,
or the conversation naturally concluded), the flow resumes at Block 9. After the session injector runs,
Block 10 sets the queue and Block 11 transfers the contact.

The escalation routing happens **within the queue** via a **Check Contact Attributes** block added
after Block 8 exits (see Part J of `docs/aria-connect-voice-chat-novice-guide.md`). The flow checks
`Tool = "Escalate"` in the Lex session attributes namespace, copies ARIA's structured handoff fields
(topicCategory, escalationReason, etc.) to permanent contact attributes, calls the `aria-routing-lookup`
Lambda to resolve the right queue, then transfers the contact.

For the new features in this guide, **we add new intent checks after Block 8** to detect
`RequestCallback` and `requestVoiceTransfer` signals before the standard escalation path runs.

---

## 3. Feature 1 — Customer-Requested Callback

### 3a. Queue-Full / Out-of-Hours Callback (Inbound Voice)

#### What happens today (without this feature)

A customer rings Meridian Bank. All advisors are busy. The call queues indefinitely. There is no
press-2-for-callback option. Block 5V (Check Hours of Operation) disconnects out-of-hours callers
with a message but offers no callback.

#### What the feature adds

Block 5V gets a new branch after the "Out of hours" path: instead of immediately disconnecting,
the customer is transferred to a new flow called `ARIA-Callback-Offer`. That flow plays *"Press 1
to hold, press 2 for a callback"*, collects the digit, and schedules a native Connect callback.

Separately, ARIA itself can detect callback intent mid-conversation and return the `RequestCallback`
intent. When Block 8 exits, the flow detects this intent and routes to `ARIA-Callback-Offer`
(skipping the queue). ARIA's system prompt already contains the `## Callback Handling` section that
tells ARIA exactly when to use this intent — no system prompt changes are needed.

#### Components involved

| Component | File / Location | Status |
|---|---|---|
| `aria-callback-scheduler` Lambda | `scripts/lambdas/aria_callback_scheduler.py` | ✅ Built |
| Deploy script | `scripts/deploy_callback_lambda.sh` | ✅ Built |
| `aria-routing-config` DynamoDB table | seeded by `deploy_routing_lambda.sh` | ✅ Deployed |
| ARIA system prompt `## Callback Handling` section | `docs/aria-connect-voice-chat-novice-guide.md` line 1418 | ✅ Already in deployed prompt |
| `ARIA-Callback-Offer` contact flow | does not exist yet | ❌ Must be created |
| `ARIA-Outbound-Whisper` flow | does not exist yet | ❌ Must be created |
| Callback queue in Connect console | must be created manually | ❌ Must be configured |
| `RequestCallback` intent check after Block 8 | not in Unified Inbound flow yet | ❌ Must be added |

#### How the `aria-callback-scheduler` Lambda works

When invoked from the flow, it:
1. Reads `topicCategory` from contact attributes (ARIA sets this when it returns `RequestCallback`)
2. Queries `aria-routing-config` DynamoDB for the correct callback queue for that topic
3. Returns `callbackQueueId`, `callbackQueueName`, `callbackQueueArn`, and echoes `conversationSummary`
4. Falls back to `general_banking` row if no specific topic matches
5. Falls back to main queue if `callbackQueueId` is still a PLACEHOLDER — safe during initial setup

---

### 3b. Chat-to-Voice Callback (Customer Asks ARIA)

#### What happens today (without this feature)

A customer is chatting with ARIA. They say "Can you call me?". ARIA has the `request_channel_transfer`
tool available and the system prompt contains the `## Channel Transfer Protocol` section (line 1264)
telling ARIA exactly what to do. However, the **contact flow has no block that checks for
`requestVoiceTransfer = "true"` after Block 8 exits** — so the signal is never acted on.

#### What the feature adds

Two new blocks after Block 8 in the Unified Inbound flow: a `Check Contact Attributes` block tests
`requestVoiceTransfer == "true"`. If it matches, the flow invokes `chat_to_voice_transfer` Lambda
which stores the full chat transcript in DynamoDB and calls the customer back on voice.

The ARIA system prompt already handles this correctly:
- Line 1264: `## Channel Transfer Protocol` — tells ARIA to call `request_channel_transfer` then
  `escalate_to_human_agent` with `escalation_reason='channel_transfer'`
- Line 1293: `request_channel_transfer(session_id, instance_id, target_channel, customer_phone, reason)`
- Line 1301: `Call escalate_to_human_agent with escalation_reason='channel_transfer'` — this causes
  Block 8 to exit, allowing the flow to act on the `requestVoiceTransfer` contact attribute

No system prompt changes are required.

#### Components involved

| Component | File / Location | Status |
|---|---|---|
| `request_channel_transfer` MCP tool | `aria/tools/channels/request_transfer.py` | ✅ Built, in MCP Gateway |
| `chat_to_voice_transfer` Lambda | `scripts/lambdas/chat_to_voice_transfer.py` | ✅ Deployed |
| `aria-transcript-store` DynamoDB table | created by `deploy_mcp_gateway.sh` | ✅ Deployed |
| ARIA system prompt Channel Transfer Protocol | deployed prompt, line 1264 | ✅ Already correct |
| `requestVoiceTransfer` check block after Block 8 | not in Unified Inbound flow | ❌ Must be added |
| `ARIA-Outbound-Callback` contact flow | does not exist yet | ❌ Must be created |

---

## 4. Feature 2 — Chat-to-Voice Context Transfer (ARIA Remembers the Chat)

### The problem

When `chat_to_voice_transfer` Lambda calls `StartOutboundVoiceContact`, Amazon Connect creates a
**brand-new voice contact**. That new contact starts with no memory of the chat. Without any
intervention ARIA would answer the voice call cold and ask the customer to repeat everything.

### The solution — already fully wired in the ARIA prompt

The ARIA system prompt at `docs/aria-connect-voice-chat-novice-guide.md` already contains everything
needed on the AI side:

- Line 933: `Cross-channel transfer (only on CHAT→VOICE or VOICE→CHAT transfer): priorChannel, priorContactId, priorTranscript` — injected by session injector
- Line 951: `- Prior Transcript: {{$.Custom.priorTranscript}}` — template variable in the prompt
- Lines 955–963: `<personalization_guidelines>` — "If a prior transcript (priorTranscript) is present, the customer has transferred from another channel — acknowledge the transfer naturally and avoid asking them to repeat themselves"
- Lines 1500–1503: Example response for cross-channel transfer: `"Hello [preferredName], I can see you were chatting with us just now. I have the full history of your conversation so you won't need to repeat anything."`

### How the data flows from chat to voice

```
STEP 1 — request_channel_transfer MCP tool (triggered by ARIA on chat)
  Writes contact attribute: requestVoiceTransfer = "true"
  Writes contact attribute: customerPhone = <phone customer provided>

STEP 2 — chat_to_voice_transfer Lambda (invoked from contact flow — NEW BLOCK)
  Fetches full chat transcript from Contact Lens V2 API
  Stores transcript in DynamoDB aria-transcript-store, keyed by chatContactId
  Calls StartOutboundVoiceContact with these contact attributes:
    chatContactId       = <original chat contact ID>
    voiceTransferSource = "chat"
    channel             = "voice"

STEP 3 — session_injector_qconnect Lambda (Block 9 of ARIA-Outbound-Callback flow)
  Reads voiceTransferSource == "chat" and chatContactId from contact attributes
  Queries DynamoDB aria-transcript-store for the transcript
  Writes into Q Connect session:
    priorTranscript  = full chat text
    priorSummary     = brief 6-turn summary
    priorChannel     = "chat"
    priorContactId   = original chat contact ID
  These become {{$.Custom.priorTranscript}} etc. in the ARIA prompt

STEP 4 — ARIA (via Connect AI Agent in Block 8 of ARIA-Outbound-Callback flow)
  Reads {{$.Custom.priorTranscript}} and {{$.Custom.priorChannel}} from session context
  Opens with: "Hello [name], I can see you were chatting with us just now. I have the
  full history of your conversation so you won't need to repeat anything."
```

### What is currently missing

The `_get_cross_channel_transcript` function **already exists** in
`scripts/lambdas/session_injector_qconnect.py` at line 447. It detects
`voiceTransferSource = 'chat'`, queries DynamoDB, and returns the prior transcript.
The data pipeline is complete. What is missing is the **wiring**:

1. The Unified Inbound flow (chat path) has no block checking `requestVoiceTransfer = "true"` after Block 8 exits
2. The `ARIA-Outbound-Callback` contact flow does not exist (the voice flow for the outbound call back to the customer)
3. `chat_to_voice_transfer` Lambda needs the `ARIA-Outbound-Callback` flow ID and outbound phone number as env vars

---

## 5. What Is Already Built vs. What Needs to Be Added

### Already built and deployed

| Component | Purpose |
|---|---|
| ARIA Connect AI Agent (Orchestration type) | Handles all customer conversations on voice and chat |
| ARIA system prompt | Contains callback handling, channel transfer, cross-channel context, DTMF — already published |
| `ARIA Banking Unified Inbound` flow (12 blocks) | Single flow handles voice and chat |
| `session_injector_qconnect` Lambda | Injects context into Q Connect session; detects `voiceTransferSource=chat` and retrieves prior transcript |
| `chat_to_voice_transfer` Lambda | Stores chat transcript; initiates outbound voice call |
| `voice_to_chat_transfer` Lambda | Creates new chat from a voice call; sends SMS link |
| `request_channel_transfer` MCP tool | Sets `requestVoiceTransfer` or `requestChatTransfer` on contact |
| `escalate_to_human_agent` MCP tool | Triggers Escalate Return to Control; exits Block 8 |
| `aria-callback-scheduler` Lambda | Resolves callback queue ID from topicCategory |
| `aria-transcript-store` DynamoDB | Stores cross-channel transcripts with 7-day TTL |
| `aria-routing-config` DynamoDB | Contains queue IDs per topic |
| DTMF secure capture sub-flow | Handles sensitive digit collection via DTMF |

### Needs to be added (priority order)

| # | What | Where | Complexity |
|---|---|---|---|
| 1 | `requestVoiceTransfer` check block after Block 8 in Unified Inbound flow | Connect flow designer | Low — 4 new blocks |
| 2 | `RequestCallback` intent check after Block 8 in Unified Inbound flow | Connect flow designer | Low — 3 new blocks |
| 3 | `ARIA-Callback-Offer` contact flow | Connect console — new flow | Medium — 12 blocks |
| 4 | `ARIA-Outbound-Callback` contact flow | Connect console — new flow | Medium — 10 blocks |
| 5 | Callback queue created in Connect console | Connect console — Queues | Config only |
| 6 | `callbackQueueId` values updated in DynamoDB | `deploy_callback_lambda.sh update-queues` | Script run |
| 7 | `CONTACT_FLOW_ID` env var on `chat_to_voice_transfer` Lambda | Lambda console | Config only |

---

## 6. Step-by-Step — Changes to the Unified Inbound Flow

The existing 12-block flow is working. These changes add new branches **after Block 8** to intercept
callback and channel-transfer signals before the contact reaches Block 10 (Set Working Queue).

> **Where to make changes**: Open `ARIA Banking Unified Inbound` in the Connect flow designer
> (Routing → Flows → click the flow → Edit draft).

### Current Block 8 exit connections

Today Block 8 (Connect Assistant) has its **Success** output connected to Block 9 (session injector).
You need to intercept this path and add new check blocks **between** Block 8 Success and Block 9.

Reconnect as follows after adding all blocks:
```
Block 8 Success → NEW Block 8A (Check requestVoiceTransfer)
Block 8A Match  → NEW Block 8B (Lambda: chat_to_voice_transfer)
Block 8A No Match → NEW Block 8C (Check RequestCallback intent)
Block 8C Match  → NEW Block 8D (Lambda: aria-callback-scheduler) → ... → Disconnect
Block 8C No Match → Block 9 (existing — session injector, unchanged)
```

### New Block 8A — Check Contact Attributes: requestVoiceTransfer

| Setting | Value |
|---|---|
| **Block type** | Check contact attributes |
| **Attribute to check** | `requestVoiceTransfer` |
| **Namespace** | User Defined |
| **Condition** | Equals `true` |
| **Match output →** | Block 8B (Lambda: chat_to_voice_transfer) |
| **No match output →** | Block 8C (Check RequestCallback) |

> **Why this check comes FIRST**: The `request_channel_transfer` MCP tool sets `requestVoiceTransfer = "true"`
> on the contact attribute store via `connect:UpdateContactAttributes`. After ARIA calls
> `escalate_to_human_agent` to exit Block 8, this attribute is the first thing to check because
> it means ARIA has already confirmed a callback and we must NOT route to the human queue.

### New Block 8B — Invoke Lambda: chat_to_voice_transfer

| Setting | Value |
|---|---|
| **Block type** | Invoke AWS Lambda function |
| **Function** | `aria-banking-chat-to-voice-transfer-prod` |
| **Invocation timeout** | 8 seconds |
| **Parameter — contactId** | Namespace: System, Key: `ContactId` |
| **Parameter — customerId** | Namespace: User-defined, Key: `customerId` |
| **Parameter — authStatus** | Namespace: User-defined, Key: `authStatus` |
| **Parameter — customerPhone** | Namespace: User-defined, Key: `customerPhone` |
| **Parameter — locale** | Namespace: User-defined, Key: `locale` |
| **Parameter — transferMode** | Namespace: Static, Value: `aria` |
| **Success output →** | Block 8B-ok (Play confirmation) |
| **Error output →** | Block 8B-err (Play error) |

> **`transferMode = aria`** tells the Lambda that the outbound call should go to the
> `ARIA-Outbound-Callback` contact flow (where ARIA handles the call), not to a human queue.
> This is how the Lambda selects the correct contact flow ARN when calling
> `StartOutboundVoiceContact`.

### New Block 8B-ok — Play Prompt / Send Message: Callback Confirmation

| Setting | Value |
|---|---|
| **Block type (voice)** | Play prompt |
| **Block type (chat)** | Send message (use a single block with channel-aware text, or use a Check Channel branch) |
| **Text (TTS / message)** | `We are calling you now on the number you provided. You can end this chat. Goodbye.` |
| **Language** | English (British) |
| **Success output →** | Block 8B-disc (Disconnect) |

### New Block 8B-err — Play Prompt / Send Message: Callback Error

| Setting | Value |
|---|---|
| **Block type** | Play prompt (voice) or Send message (chat) |
| **Text** | `I'm sorry, I was unable to schedule a callback at this time. Please call us on 0161 900 9000.` |
| **Language** | English (British) |
| **Success output →** | Block 8B-disc (Disconnect) |

### New Block 8B-disc — Disconnect / Hang Up

| Setting | Value |
|---|---|
| **Block type** | Disconnect / hang up |

> Once the outbound call is initiated, the chat session ends here. The customer will receive
> the voice call within seconds. Keeping the chat open would cause confusion.

---

### New Block 8C — Check Contact Attributes: RequestCallback Intent

| Setting | Value |
|---|---|
| **Block type** | Check contact attributes |
| **Attribute to check** | Intent returned by the AI agent |
| **Namespace** | Lex – Session attributes |
| **Attribute** | `intent` (or check the Lex intent output from Block 8 — the attribute name depends on how your AI agent returns it; in some configurations you check the Connect Assistant output directly) |
| **Condition** | Equals `RequestCallback` |
| **Match output →** | Block 8D (Set Contact Attributes — copy callback fields) |
| **No match output →** | Block 9 (existing session injector — unchanged path) |

> **Note on checking the intent**: The Connect Assistant block (Block 8) returns the AI agent's
> intent via the Lex session attributes namespace. The exact key name depends on your Connect
> instance version. Check in the Connect flow designer by looking at Block 8's outputs — there
> will be a named output for `RequestCallback` if ARIA has been set up to return it. If a named
> output already appears on Block 8 for `RequestCallback`, connect it directly to Block 8D instead
> of using a separate Check block.

### New Block 8D — Set Contact Attributes: Copy Callback Fields from Lex

Before invoking `aria-callback-scheduler`, copy ARIA's structured callback fields from Lex session
attributes into permanent contact attributes (the Lambda cannot read Lex session attributes directly).

| Setting | Value |
|---|---|
| **Block type** | Set contact attributes |
| **Attribute 1 — Destination key** | `topicCategory`, Namespace: Lex – Session attributes, Attr: `topicCategory` |
| **Attribute 2 — Destination key** | `conversationSummary`, Namespace: Lex – Session attributes, Attr: `conversationSummary` |
| **Attribute 3 — Destination key** | `customerIntent`, Namespace: Lex – Session attributes, Attr: `customerIntent` |
| **Attribute 4 — Destination key** | `callbackReason`, Namespace: Static, Value: `customer_request` |
| **Success output →** | Block 8E (Lambda: aria-callback-scheduler) |

> **Why copy these fields?** ARIA fills them in as part of returning `RequestCallback`. The
> `aria-callback-scheduler` Lambda reads `topicCategory` to find the right callback queue.
> `conversationSummary` is forwarded to the agent whisper flow so the advisor knows what
> the callback is about before the customer picks up.

### New Block 8E — Invoke Lambda: aria-callback-scheduler

| Setting | Value |
|---|---|
| **Block type** | Invoke AWS Lambda function |
| **Function** | `aria-callback-scheduler:prod` |
| **Invocation timeout** | 3 seconds |
| **Parameter — topicCategory** | Namespace: User-defined, Key: `topicCategory` |
| **Parameter — conversationSummary** | Namespace: User-defined, Key: `conversationSummary` |
| **Parameter — customerIntent** | Namespace: User-defined, Key: `customerIntent` |
| **Parameter — callbackReason** | Namespace: User-defined, Key: `callbackReason` |
| **Success output →** | Block 8F (Set Working Queue — dynamic) |
| **Error output →** | Block 8G (Play error) → Disconnect |

### New Block 8F — Set Working Queue (Dynamic from Lambda)

| Setting | Value |
|---|---|
| **Block type** | Set working queue |
| **Set dynamically** | Yes |
| **Namespace** | External |
| **Key** | `callbackQueueId` |
| **Success output →** | Block 8H (Transfer to Queue — Callback type) |
| **Error output →** | Block 8G (Play error) → Disconnect |

### New Block 8G — Play Prompt: Callback Scheduling Error

| Setting | Value |
|---|---|
| **Block type** | Play prompt |
| **Text** | `I'm sorry, I'm unable to schedule a callback at this time. Please call us on 0161 900 9000 during business hours.` |
| **Success output →** | Disconnect |

### New Block 8H — Transfer to Queue (Callback Type)

| Setting | Value |
|---|---|
| **Block type** | Transfer to queue |
| **Transfer type** | **Callback** ← this specific option schedules a native Connect callback |
| **Queue** | (already set dynamically in Block 8F — no further configuration) |
| **Success output →** | Disconnect |
| **Error output →** | Block 8G (Play error) → Disconnect |

> **What "Callback" transfer type does**: Instead of connecting the customer to an agent right now,
> Connect saves their place in the queue. When the queue clears and an agent becomes available,
> Connect automatically dials the customer back on the number they called from. The customer can
> hang up immediately after the confirmation message.

### Updated post-Block-8 flow diagram

```
[Block 8]  Connect Assistant (ARIA AI Agent)
    ↓ Success
[NEW Block 8A]  Check requestVoiceTransfer == "true"
    ↓ Match                          ↓ No match
[NEW Block 8B]  Lambda:             [NEW Block 8C]  Check RequestCallback intent
chat_to_voice_transfer
    ↓ Success  ↓ Error               ↓ Match               ↓ No match
[8B-ok]       [8B-err]              [NEW 8D] Set Attrs     [Block 9 — existing]
"Calling you" "Unable to call"      (copy callback fields)
    ↓               ↓                   ↓
[8B-disc]       [8B-disc]           [NEW 8E] Lambda: aria-callback-scheduler
Disconnect      Disconnect              ↓ Success    ↓ Error
                                    [NEW 8F]     [NEW 8G] Error → Disconnect
                                    Set Queue
                                        ↓
                                    [NEW 8H] Transfer to Queue (Callback)
                                        ↓
                                    Disconnect
```

---

## 7. Step-by-Step — New Flow: ARIA-Callback-Offer

This is a **brand-new contact flow** for when the inbound queue is full or outside business hours.
The customer is transferred to this flow and offered the choice to hold or request a callback.

### How to create it

1. Connect admin console → **Routing → Flows → Create flow**
2. Name: `ARIA-Callback-Offer`
3. Type: **Contact flow** (inbound)

### Blocks in order

**Block 1 — Enable Logging**

| Setting | Value |
|---|---|
| **Block type** | Set logging behaviour |
| **Logging** | Enabled |
| **Success →** | Block 2 |

**Block 2 — Set callbackReason**

| Setting | Value |
|---|---|
| **Block type** | Set contact attributes |
| **Key** | `callbackReason`, Type: Static, Value: `queue_full` |
| **Success →** | Block 3 |

> This is passed through to the agent whisper flow so advisors know the customer didn't want
> to hold — they chose to be called back.

**Block 3 — Play Choice Prompt**

| Setting | Value |
|---|---|
| **Block type** | Play prompt |
| **Text (TTS)** | `All our advisors are with other customers. To continue holding, press 1. To receive a callback on this number when an advisor is free, press 2.` |
| **Language** | English (British) |
| **Success →** | Block 4 |

**Block 4 — Collect DTMF Digit**

| Setting | Value |
|---|---|
| **Block type** | Store customer input |
| **Input type** | DTMF |
| **Maximum digits** | 1 |
| **Input timeout (seconds)** | 10 |
| **Success →** | Block 5 |
| **Timeout →** | Block 6 (assume callback — customer put down phone mid-hold) |

> **Why "Store customer input" not "Get customer input" (Lex)?** This is a simple press-1-or-2
> choice — no AI understanding is needed. "Store customer input" collects DTMF digits and
> stores the result in `$.StoredCustomerInput`. Faster and cheaper than invoking a Lex bot
> for a binary choice.

**Block 5 — Check Digit Pressed**

| Setting | Value |
|---|---|
| **Block type** | Check contact attributes |
| **Attribute** | `$.StoredCustomerInput` |
| **Namespace** | System |
| **Condition** | Equals `1` |
| **Match →** | Block 5a (Transfer to main queue — customer wants to hold) |
| **No match →** | Block 6 (proceed to callback scheduling) |

**Block 5a — Transfer to Queue (Hold Path)**

| Setting | Value |
|---|---|
| **Block type** | Transfer to queue |
| **Queue** | Your main inbound queue (e.g. `ARIA Banking Agents`) |
| **Success / Error →** | Disconnect |

**Block 6 — Invoke Lambda: aria-callback-scheduler**

| Setting | Value |
|---|---|
| **Block type** | Invoke AWS Lambda function |
| **Function** | `aria-callback-scheduler:prod` |
| **Invocation timeout** | 3 seconds |
| **Parameter — topicCategory** | User-defined, Key: `topicCategory` |
| **Parameter — conversationSummary** | User-defined, Key: `conversationSummary` |
| **Parameter — callbackReason** | User-defined, Key: `callbackReason` |
| **Parameter — customerIntent** | User-defined, Key: `customerIntent` |
| **Success →** | Block 7 |
| **Error →** | Block 11 (error message) |

**Block 7 — Check for Scheduling Error**

| Setting | Value |
|---|---|
| **Block type** | Check contact attributes |
| **Namespace** | External |
| **Key** | `schedulingError` |
| **Condition** | Equals `true` |
| **Match →** | Block 11 (error message) |
| **No match →** | Block 8 |

**Block 8 — Copy Lambda Result to Contact Attributes**

| Setting | Value |
|---|---|
| **Block type** | Set contact attributes |
| **Attr 1** | `callbackQueueId` — Namespace: External, Key: `callbackQueueId` |
| **Attr 2** | `callbackQueueName` — Namespace: External, Key: `callbackQueueName` |
| **Attr 3** | `conversationSummary` — Namespace: External, Key: `conversationSummary` |
| **Success →** | Block 9 |

> **Why copy External to User-defined?** `$.External.*` values only exist immediately after the
> Lambda returns. If any subsequent block reads them and they are no longer "current", you get empty
> values. Copying to `$.Attributes.*` (User-defined) makes them permanent for this contact's lifetime.

**Block 9 — Set Working Queue (Dynamic)**

| Setting | Value |
|---|---|
| **Block type** | Set working queue |
| **Set dynamically** | Yes |
| **Namespace** | User Defined |
| **Key** | `callbackQueueId` |
| **Success →** | Block 10 |
| **Error →** | Block 11 (error message) |

**Block 10 — Play Confirmation then Transfer**

| Setting | Value |
|---|---|
| **Block type** | Play prompt |
| **Text (TTS)** | `Thank you. We will call you back on this number as soon as an advisor is free. Goodbye.` |
| **Language** | English (British) |
| **Success →** | Block 12 (Transfer to Queue — Callback) |

**Block 11 — Play Error Message**

| Setting | Value |
|---|---|
| **Block type** | Play prompt |
| **Text** | `I'm sorry, I'm unable to schedule a callback at this time. You can continue to hold or call back later on 0161 900 9000.` |
| **Success →** | Block 13 (Disconnect) |

**Block 12 — Transfer to Callback Queue**

| Setting | Value |
|---|---|
| **Block type** | Transfer to queue |
| **Transfer type** | **Callback** |
| **Success / Error →** | Block 13 (Disconnect) |

**Block 13 — Disconnect**

No configuration needed.

### How to connect this flow to the main voice flow

In the **Unified Inbound flow**, Block 5V (Check Hours of Operation) currently has:
- **Out of hours** → Play OOH prompt → Disconnect

Change the out-of-hours path to:
- **Out of hours** → **Transfer to flow** → select `ARIA-Callback-Offer`

Optionally, also add a **Get queue metrics** block before Block 8 on the voice path to detect
queue full conditions and redirect to `ARIA-Callback-Offer` when wait time exceeds your threshold:
- Get queue metrics → Check contact attributes (`$.External.MetricResults[0].Value`) > threshold
  → Transfer to flow: `ARIA-Callback-Offer`

---

## 8. Step-by-Step — New Flow: ARIA-Outbound-Callback

This is the flow that runs when `chat_to_voice_transfer` Lambda calls `StartOutboundVoiceContact`.
The customer picks up their phone and this is what they hear — ARIA handling the call as normal, but
with the full context of the prior chat conversation available via `{{$.Custom.priorTranscript}}`.

### How to create it

1. Connect admin console → **Routing → Flows → Create flow**
2. Name: `ARIA-Outbound-Callback`
3. Type: **Contact flow** (inbound)

After creating the flow, copy its **Flow ID** (shown in the ARN in the browser URL:
`flows/<flow-id>`). Set this as the `CONTACT_FLOW_ID` environment variable on the
`aria-banking-chat-to-voice-transfer-prod` Lambda.

### Blocks in order

**Block 1 — Enable Logging**

| Setting | Value |
|---|---|
| **Block type** | Set logging behaviour |
| **Logging** | Enabled |
| **Success →** | Block 2 |

**Block 2 — Set Voice**

| Setting | Value |
|---|---|
| **Block type** | Set voice |
| **Language** | English (British) |
| **Voice** | Amy |
| **Override speaking style** | Conversational |
| **Success →** | Block 3 |

**Block 3 — Set Contact Attributes (channel = voice)**

| Setting | Value |
|---|---|
| **Block type** | Set contact attributes |
| **Key** | `channel`, Type: Static, Value: `voice` |
| **Key** | `locale`, Type: Static, Value: `en-GB` |
| **Success →** | Block 4 |

> These are required so the session injector Lambda (Block 5) and ARIA know they are on a voice call.

**Block 4 — Connect Assistant (ARIA AI Agent)**

> ⚠️ **This block MUST come before the session injector Lambda**. The Q Connect session
> does not exist until this block runs. If you put the Lambda before this block, the injector
> cannot find the session to inject into and `priorTranscript` injection silently fails.

| Setting | Value |
|---|---|
| **Block type** | Amazon Q in Connect (Connect Assistant) |
| **Assistant** | Select your Q Connect assistant (same one used in the Unified Inbound flow) |
| **Success →** | Block 5 (session injector) |
| **Error →** | Block 5 (continue — ARIA will work without injection as fallback) |

> **How ARIA knows to use the prior chat context**: The session injector Lambda (Block 5) detects
> `voiceTransferSource = "chat"` on this outbound contact, queries DynamoDB for the chat transcript,
> and injects `priorTranscript` and `priorSummary` into the Q Connect session. The ARIA prompt reads
> these via `{{$.Custom.priorTranscript}}`. ARIA's personalization guidelines tell it to open with:
> "Hello [name], I can see you were chatting with us just now. I have the full history..."

**Block 5 — Invoke Lambda: session_injector_qconnect**

| Setting | Value |
|---|---|
| **Block type** | Invoke AWS Lambda function |
| **Function** | `aria-banking-session-injector-prod` |
| **Invocation timeout** | 5 seconds |
| **Parameter — contactId** | Namespace: System, Key: `ContactId` |
| **Parameter — channel** | Namespace: User-defined, Key: `channel` |
| **Parameter — locale** | Namespace: User-defined, Key: `locale` |
| **Success →** | Block 6 |
| **Error →** | Block 7 (Set Working Queue — skip context injection, continue call) |
| **Timeout →** | Block 7 |

> **What this Lambda does specifically for a chat-transferred call**:
> 1. Reads `voiceTransferSource = "chat"` and `chatContactId` from contact attributes
> 2. Queries `aria-transcript-store` DynamoDB table for `chatContactId`
> 3. Finds the chat transcript stored by `chat_to_voice_transfer` Lambda
> 4. Injects into the Q Connect session: `priorTranscript`, `priorSummary`, `priorChannel`, `customerId`
> 5. Returns all injected values as `$.External.*`

**Block 6 — Set Contact Attributes (Copy Lambda Result)**

| Setting | Value |
|---|---|
| **Block type** | Set contact attributes |
| **Attr: customerId** | Namespace: External, Key: `customerId` |
| **Attr: authStatus** | Namespace: External, Key: `authStatus` |
| **Attr: preferredName** | Namespace: External, Key: `preferredName` |
| **Attr: productSummary** | Namespace: External, Key: `productSummary` |
| **Success →** | Block 7 |

> Only copy the attributes you need as permanent contact attributes. `priorTranscript` and
> `priorSummary` are already injected directly into the Q Connect session by the Lambda — they
> do not need to be stored as contact attributes.

**Block 7 — Set Working Queue**

| Setting | Value |
|---|---|
| **Block type** | Set working queue |
| **Queue** | `ARIA Banking Agents` (same queue as in the Unified Inbound flow) |
| **Success →** | Block 8 |

**Block 8 — Transfer to Queue**

| Setting | Value |
|---|---|
| **Block type** | Transfer to queue |
| **At capacity / Error →** | Block 9 (Disconnect) |

**Block 9 — Disconnect / Hang Up**

No configuration needed.

### Post-escalation handling (identical to Unified Inbound)

When ARIA calls the Escalate tool inside this outbound callback call, Block 4 (Connect Assistant)
exits and the contact proceeds to Block 5 (session injector) → Block 7 (Set Working Queue) →
Block 8 (Transfer to Queue). The contact is already set up correctly for agent escalation.

If you want full intelligent routing (using `aria-routing-lookup` Lambda to select the right queue
by topic), add the same post-Block 4 escalation chain described in Part I of
`docs/aria-connect-voice-chat-novice-guide.md`.

---

## 9. Testing End-to-End

### Test 1 — Queue-full callback (ARIA-Callback-Offer flow)

1. Temporarily wire Block 5V "Out of hours" output → Transfer to flow: `ARIA-Callback-Offer`
2. Call the Meridian Bank number outside business hours (or temporarily set hours to all-closed)
3. Press 2 when prompted
4. Verify: confirmation message plays, call disconnects, callback scheduled
5. Verify in Connect console: Routing → Queues → your callback queue → Scheduled callbacks
6. Reset Block 5V back to the play-message path after testing

### Test 2 — ARIA-triggered callback

1. Call the Meridian Bank number during business hours
2. Say: "I'd like a callback please. Call me on 07700 900000"
3. Verify: ARIA confirms the callback request and says goodbye
4. Verify: Block 8 exits via `RequestCallback` intent
5. Verify: Block 8D/8E/8F/8H run (CloudWatch flow logs)
6. Verify: callback appears in your callback queue

### Test 3 — Chat-to-voice callback

1. Open the chat widget and start a conversation with ARIA
2. Say: "I'd like to speak to someone, can you call me on 07700 900000?"
3. Verify: ARIA confirms and says it has requested a callback
4. Verify: `requestVoiceTransfer = "true"` is set on the contact (CloudWatch Lambda logs)
5. Verify: Block 8 exits (ARIA calls `escalate_to_human_agent` with `channel_transfer`)
6. Verify: Block 8A detects `requestVoiceTransfer = "true"` (flow logs)
7. Verify: Block 8B (chat_to_voice_transfer Lambda) invoked successfully
8. Verify: an outbound call arrives on 07700 900000 within 10 seconds
9. Answer the call — verify ARIA greets you with context from the chat

### Test 4 — Context carry-over on outbound call

1. Complete Test 3 above (initiate chat, request callback)
2. Answer the outbound call
3. Verify: ARIA opens with "I can see you were chatting with us just now. I have the full history"
4. Verify: ARIA does NOT ask you to verify identity again if you were authenticated in chat
5. Verify: ARIA does NOT ask you to repeat why you called
6. Start a new query — verify ARIA knows your prior context

### Test 5 — Escalation still works after changes

1. Call the number normally
2. Say "I want to speak to a human"
3. Verify: ARIA escalates, Block 8 exits via Escalate tool
4. Verify: Block 8A No match → Block 8C No match → Block 9 onwards (normal escalation path)
5. Verify: contact reaches an agent

---

## 10. Troubleshooting

### "ARIA doesn't know about the chat transcript on the outbound call"

**Diagnosis chain (check in order)**:

1. **DynamoDB — was the transcript stored?**
   Open AWS Console → DynamoDB → `aria-transcript-store` → Explore items → search for the chat
   contact ID. If the item is missing, `chat_to_voice_transfer` Lambda did not write it.
   Check CloudWatch Logs for `aria-banking-chat-to-voice-transfer-prod`.

2. **Lambda — did session injector detect `voiceTransferSource`?**
   Open CloudWatch Logs for `aria-banking-session-injector-prod`. Search for
   `voiceTransferSource` and `_get_cross_channel_transcript`. If missing, the Lambda is not
   receiving the outbound contact's attributes. Check that `chat_to_voice_transfer` Lambda is
   passing `chatContactId` and `voiceTransferSource = "chat"` to `StartOutboundVoiceContact`.

3. **Connect Assistant block — was the Q Connect session created before the Lambda?**
   In the `ARIA-Outbound-Callback` flow, Block 4 (Connect Assistant) MUST come before Block 5
   (Lambda). If they are in the wrong order, the Lambda cannot inject into the session.

4. **Q Connect session — were the values injected?**
   In CloudWatch Logs for `aria-banking-session-injector-prod`, look for lines like
   `priorTranscript injected` or `Injecting session attributes`. If the Lambda ran but
   `priorTranscript` is empty, the DynamoDB query returned nothing (step 1 above).

### "The chat flow doesn't trigger the voice callback"

1. Verify `request_channel_transfer` tool is in the ARIA AI Agent's tool list (AI Agent Designer
   → your agent → Tools → find `request_channel_transfer` from the MCP Gateway)
2. Open CloudWatch Logs for the MCP Gateway Lambda — search for `requestVoiceTransfer`. Verify
   the tool call succeeded and set the attribute.
3. In Connect flow logs for the chat contact, verify Block 8A fired and its condition matched.
4. Verify the `customerPhone` attribute was set — the Lambda needs this to dial the customer.

### "Block 8C — RequestCallback intent — never matches"

1. Verify ARIA returned `RequestCallback` by checking the Lex session attributes in the flow logs.
2. Verify the intent name exactly matches (case-sensitive). The exact string is `RequestCallback`.
3. If Block 8 has a named output for `RequestCallback`, use that output connection directly
   instead of the Check Contact Attributes block.

### "Callback queue scheduling always fails"

1. Check CloudWatch Logs for `aria-callback-scheduler`.
2. Look for: "No routing config for..." — the `aria-routing-config` DynamoDB table has no row for
   this `topicCategory` and no `general_banking` fallback row.
3. Fix: Run `./scripts/deploy_callback_lambda.sh update-queues` to seed DynamoDB rows.
4. Also ensure `callbackQueueId` values in DynamoDB are real queue UUIDs, not PLACEHOLDER strings.
   Get the real queue UUID from Connect console → Routing → Queues → click a queue → copy UUID from URL.

### "ARIA asks the customer to verify identity again on the outbound call"

**Cause**: `authStatus` was not passed from the chat session to the outbound voice contact.

**Fix**: Ensure `chat_to_voice_transfer` Lambda passes `authStatus` as a contact attribute to
`StartOutboundVoiceContact`. The session injector Lambda then reads this and injects
`authStatus = "authenticated"` into the Q Connect session, so the ARIA prompt's pre-authentication
section (`authStatus in session context is "authenticated"`) skips the identity gate.

---

## 11. Component Reference

### Contact attributes used across these features

| Attribute | Set by | Read by | Meaning |
|---|---|---|---|
| `requestVoiceTransfer` | `request_channel_transfer` MCP tool (via `connect:UpdateContactAttributes`) | Unified Inbound Block 8A | ARIA has confirmed a voice callback request |
| `customerPhone` | `request_channel_transfer` MCP tool | `chat_to_voice_transfer` Lambda (Block 8B param) | Phone number to call back |
| `voiceTransferSource` | `chat_to_voice_transfer` Lambda (`StartOutboundVoiceContact` attrs) | `session_injector_qconnect` Lambda | This outbound voice call came from a chat session |
| `chatContactId` | `chat_to_voice_transfer` Lambda | `session_injector_qconnect` Lambda | Original chat contact to look up transcript in DynamoDB |
| `callbackReason` | Block 8D (copy from Lex session attrs) or Block 2 of `ARIA-Callback-Offer` | `aria-callback-scheduler` Lambda | Why the callback was requested (`customer_request` or `queue_full`) |
| `topicCategory` | ARIA (Escalate tool schema field → Lex session attrs → Block 8D copies it) | `aria-callback-scheduler` Lambda | Banking topic to route the callback queue |
| `callbackQueueId` | `aria-callback-scheduler` Lambda via Block 8F copy | Block 8F Set Working Queue | Dynamic queue ID for the callback |
| `authStatus` | Block 4V/3C (initial value: `unauthenticated`) or auth Lambda | Session injector → ARIA `{{$.Custom.authStatus}}` | Authentication state so ARIA knows whether to run the identity gate |

### DynamoDB tables used

| Table | Key | Written by | Read by |
|---|---|---|---|
| `aria-transcript-store` | `contactId` (= chatContactId) | `chat_to_voice_transfer` Lambda | `session_injector_qconnect` Lambda |
| `aria-routing-config` | `topicCategory` | `deploy_routing_lambda.sh` / `deploy_callback_lambda.sh` | `aria-routing-lookup`, `aria-callback-scheduler` Lambdas |
| `aria-session-memory` | `customerId` | ARIA session end (via MCP escalation tool) | `session_injector_qconnect` Lambda — provides `priorSummary` |

### Lambdas involved

| Lambda | Trigger | Purpose |
|---|---|---|
| `aria-banking-session-injector-prod` | Block 9 in Unified Inbound / Block 5 in ARIA-Outbound-Callback | Injects customer context + cross-channel transcript into Q Connect session |
| `aria-banking-chat-to-voice-transfer-prod` | Block 8B in Unified Inbound (chat path) | Stores chat transcript; initiates outbound voice call |
| `aria-banking-voice-to-chat-transfer-prod` | Equivalent block on voice path (if added) | Creates new chat contact; sends SMS link |
| `aria-callback-scheduler` | Block 8E in Unified Inbound / Block 6 in ARIA-Callback-Offer | Resolves callback queue from topicCategory |
| `aria-routing-lookup` | Post-Block 8 escalation chain (Part I of main guide) | Resolves human agent queue from topicCategory |

### Environment variables to set after creating the flows

| Lambda | Variable | Value |
|---|---|---|
| `aria-banking-chat-to-voice-transfer-prod` | `CONTACT_FLOW_ID` | Flow ID of `ARIA-Outbound-Callback` (from ARN in Connect console → Routing → Flows) |
| `aria-banking-chat-to-voice-transfer-prod` | `QUEUE_ID` | Default outbound queue ARN |
| `aria-banking-chat-to-voice-transfer-prod` | `SOURCE_PHONE_NUMBER` | Your Meridian Bank E.164 number (e.g. `+441619009000`) |

### What the ARIA system prompt already covers (no changes needed)

| Feature | Where in system prompt | Notes |
|---|---|---|
| Callback handling | `## Callback Handling` (line 1418) | ARIA knows when to return `RequestCallback` intent |
| Channel transfer | `## Channel Transfer Protocol` (line 1264) | ARIA knows when/how to call `request_channel_transfer` |
| Prior chat transcript | `{{$.Custom.priorTranscript}}` in `<customer_context>` | Already in deployed prompt |
| Cross-channel greeting | Response example at lines 1500–1503 | "I have the full history of your conversation" |
| `request_channel_transfer` tool | Listed in `<tool_usage_strategy>` (line 1045) | Already included in the tool list |
| `escalate_to_human_agent` for channel transfer | Line 1301 | ARIA calls this after `request_channel_transfer` to exit Block 8 |
