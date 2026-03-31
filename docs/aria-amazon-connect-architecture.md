# ARIA Banking Agent × Amazon Connect — Integration Architecture

> **Status**: Design Document  
> **Scope**: Connecting the existing ARIA / AgentCore / Nova Sonic stack to Amazon Connect for PSTN telephony and omni-channel contact centre capabilities  
> **Sources**: AWS official documentation — Amazon Bedrock AgentCore Developer Guide, Amazon Connect Administrator Guide, Amazon Nova User Guide, Kinesis Video Streams Developer Guide, plus official AWS sample repositories.

---

## 1. Executive Summary

The ARIA banking agent already runs as a production-ready, Nova Sonic–powered conversational AI on **Amazon Bedrock AgentCore**. It exposes:

- A **WebSocket endpoint** for real-time bidirectional voice (client browser ↔ AgentCore ↔ Nova Sonic)
- An **HTTP/REST endpoint** for text-based chat (client browser ↔ AgentCore ↔ Strands ARIA agent)

Amazon Connect is AWS's cloud contact centre platform that handles **PSTN telephony** (inbound/outbound phone calls), **omni-channel routing** (voice, chat, email, SMS, tasks), agent desktops, queuing, call recording, real-time & historical analytics, and human agent escalation.

Integrating ARIA with Amazon Connect unlocks:

| Capability | Without Connect | With Connect |
|---|---|---|
| PSTN phone calls | ❌ Browser only | ✅ Any phone number |
| Inbound call routing & queuing | ❌ | ✅ |
| Human agent escalation (warm transfer) | ❌ | ✅ |
| Supervisor monitoring / barge-in | ❌ | ✅ |
| Call recording & compliance | Manual | ✅ Native |
| SMS / Chat / Email channels | ❌ | ✅ |
| Real-time & historical reporting | Custom | ✅ Native dashboards |
| CCP Agent Desktop integration | ❌ | ✅ |

---

## 2. Current ARIA Stack — Reference Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Customer (Browser)                         │
│  React SPA  ──  CloudFront  ──  S3                           │
│     │ (voice)              │ (chat)                           │
│     │ WebSocket (SigV4)    │ HTTP POST (SigV4)                │
└─────┼──────────────────────┼────────────────────────────────┘
      │                      │
      ▼                      ▼
┌─────────────────────────────────────────────────────────────┐
│          Amazon Bedrock AgentCore Runtime                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ARIA Banking Agent (Strands + Python)               │   │
│  │  ┌─────────────────┐  ┌──────────────────────────┐  │   │
│  │  │ agentcore_voice  │  │  agentcore_app           │  │   │
│  │  │ (WebSocket/Nova  │  │  (HTTP chat handler)     │  │   │
│  │  │  Sonic S2S)      │  │                          │  │   │
│  │  └────────┬────────┘  └──────────┬───────────────┘  │   │
│  │           │                      │                    │   │
│  │  ┌────────▼──────────────────────▼───────────────┐  │   │
│  │  │          Strands ARIA Agent                   │  │   │
│  │  │  Tools: accounts, balances, statements,       │  │   │
│  │  │  debit-card, credit-card, lost/stolen, auth   │  │   │
│  │  └───────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│  Auth: Cognito Identity Pool (unauth) / IAM SigV4           │
└─────────────────────────────────────────────────────────────┘
      │                      │
      ▼                      ▼
 Amazon Nova Sonic       Banking Tool Stubs
 (us-east-1)             (extensible to real core)
```

**Key facts from the AgentCore docs:**
- Runtime endpoint: `wss://bedrock-agentcore.eu-west-2.amazonaws.com/runtimes/{arn}/ws`  
- Bidirectional streaming via WebSocket (SigV4 or OAuth 2.0)  
- Session isolation: each session runs in a dedicated microVM with isolated CPU/memory  
- Extended execution: up to 8 hours; 100 MB payload support  
- Authentication: Amazon Cognito Identity Pool → Cognito unauth role → `InvokeAgentRuntimeWithWebSocketStream` permission

---

## 3. Amazon Connect — Platform Fundamentals

### 3.1 Telephony Layer
Amazon Connect claims PSTN phone numbers (DDI/TFN) and connects them to **Contact Flows** (visual IVR logic). Audio travels over the PSTN into Connect's multi-AZ telephony infrastructure (8 kHz, G.711 μ-law encoding). Connect provides automatic load balancing, failover across ≥3 AZs per region, and zero-downtime maintenance.

### 3.2 Contact Flow Engine
Flows are the orchestration vehicle. They can:
- Play audio prompts (Amazon Polly TTS or pre-recorded)  
- Collect DTMF or speech via **Get Customer Input** blocks  
- Invoke **Amazon Lex V2** bots (NLU + intent classification + slot filling)  
- Invoke **AWS Lambda** functions synchronously (≤8 s) or asynchronously (≤60 s)  
- Set/get **contact attributes** (session state for the call)  
- Route to **queues** and human agents  
- Transfer (warm or cold) to other flows, queues, or external numbers

### 3.3 Native Nova Sonic S2S Support (2025)
Amazon Connect now has **first-class support for Nova Sonic as a Speech-to-Speech model** inside its Conversational AI bot feature. When enabled, the bot:
- Bypasses separate ASR → NLU → TTS pipeline  
- Converts customer speech **directly** into expressive Nova Sonic voice responses  
- Supports barge-in (customer interruption) natively  
- Requires a **Lex V2 bot** as the scaffolding (for intents/slots) but Nova Sonic handles all audio  
- Supported voices: Matthew (en-US), Amy (en-GB), Olivia (en-AU), Lupe (es-US)  
- Configured per-locale under **Bots → Configuration → Speech model → Speech-to-Speech → Amazon Nova Sonic**

### 3.4 Live Media Streaming (Kinesis Video Streams)
Connect can stream raw PCM audio to **Kinesis Video Streams**:
- 8 kHz sampling rate, multi-track: `AUDIO_FROM_CUSTOMER` + `AUDIO_TO_CUSTOMER`  
- 1 KVS stream consumed per active call  
- Retention configurable (minimum 5 minutes)  
- Used for: AI/ML processing, real-time transcription, compliance recording

### 3.5 Key Integration Points for AI
| Integration | Mechanism | Latency | Use For |
|---|---|---|---|
| Native Lex V2 + Nova Sonic S2S | Direct Connect integration | Very low | Full voice AI in the flow |
| Lambda invoke (sync) | Contact flow block | ≤8 s | Data dips, routing decisions |
| Lambda invoke (async) | Contact flow block | ≤60 s | Long-running backend tasks |
| KVS Live Streaming | Start Media Streaming block | Near real-time | Raw audio to custom processors |
| Connect Chat API | REST API | Low | Text chat channel |
| Amazon Connect Streams SDK | Browser JS | Low | Custom agent desktop |

---

## 4. Integration Architecture — Four Approaches

> **Updated**: Path E has been added as the recommended new approach following discovery of `AMAZON.BedrockAgentIntent` support in Lex V2. See [§4.4](#44-path-e-lex-v2-nova-sonic--amazon-bedrockagentintent--managed-bedrock-agent-recommended) and the full guide `docs/amazon-connect-path-e-bedrock-agent-lex-guide.md`.

### Approach Comparison at a Glance

| | **Path A** | **Path E** ⭐ | **Option D** | **Path B** |
|---|---|---|---|---|
| Voice (Nova Sonic) | ✅ Lex V2 S2S | ✅ Lex V2 S2S | ✅ Connect native | ✅ AgentCore WS |
| Reasoning engine | Lambda proxy → AgentCore | ✅ Managed Bedrock Agent | Connect built-in AI | ARIA AgentCore |
| Multi-tool per voice turn | ❌ One turn = one proxy call | ✅ Agent calls N tools | ✅ Via MCP | ✅ |
| Lambda bridge needed | Yes | **No** | No | No |
| Lex V2 required | Yes | Yes | No | No |
| MCP Gateway | No | No | ✅ Yes | No |
| Complexity | Low | Low–Moderate | Moderate | High |
| Best for | Preserve ARIA code as-is | Best voice + reasoning balance | Connect-native simplicity | Sub-200ms latency |

---

### 4.1 Path A: Native Connect Nova Sonic + Lambda → AgentCore HTTP

This is the **cleanest and most production-ready approach**. Amazon Connect manages all telephony and Nova Sonic voice; our ARIA AgentCore handles all intelligence and tool execution.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PSTN / Telephone Network                         │
│   Customer dials Meridian Bank number (+44 xxx xxx xxxx)            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ PSTN
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Amazon Connect (eu-west-2)                        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  INBOUND CONTACT FLOW                                        │   │
│  │                                                              │   │
│  │  [Entry Point]                                               │   │
│  │      ↓                                                       │   │
│  │  [Set Voice: Amy, Generative (Nova Sonic)]                  │   │
│  │      ↓                                                       │   │
│  │  [Set Contact Attributes: channel=voice, new_session=true]  │   │
│  │      ↓                                                       │   │
│  │  [Invoke Lambda: aria-connect-session-init]  ←──────────┐   │   │
│  │   ↙ Success  ↘ Error                                    │   │   │
│  │  ↓            [Play error prompt → Disconnect]          │   │   │
│  │  [Get Customer Input: ARIA Lex Bot]                      │   │   │
│  │   ↓ (any intent)                                         │   │   │
│  │  [Invoke Lambda: aria-connect-fulfillment] ─────────────┘   │   │
│  │   ↙ Success      ↘ Error/Transfer                           │   │
│  │  ↓                ↓                                          │   │
│  │  [Loop back to   [Set Queue: human-agents]                   │   │
│  │   Get Customer    [Transfer to Queue]                        │   │
│  │   Input block]    (warm transfer)                            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ARIA Conversational AI Bot (Lex V2 + Nova Sonic S2S)               │
│  • All speech processed by Nova Sonic (no Polly for bot turns)      │
│  • Voice: Amy (en-GB, Feminine, Generative)                         │
│  • Intents: FallbackIntent (catch-all), TransferToAgent             │
│  • Lambda fulfillment on every FallbackIntent turn                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ Lambda invoke (sync, ≤8s)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│         AWS Lambda: aria-connect-fulfillment (eu-west-2)            │
│                                                                      │
│  1. Extract contact attributes:                                      │
│     - ContactId (stable session key)                                 │
│     - inputTranscript (customer speech → text, from Lex)            │
│     - sessionState.sessionAttributes (auth status, customer ID)     │
│  2. Build HTTP request to AgentCore:                                 │
│     - POST /invocations                                              │
│     - Header: X-Amzn-Bedrock-AgentCore-Runtime-Session-Id: {CID}   │
│     - Body: { "prompt": inputTranscript }                           │
│     - Auth: IAM SigV4 (Lambda execution role)                       │
│  3. Parse ARIA response text                                         │
│  4. Check for escalation signals in response                         │
│     - "transfer to agent", "speak to someone", etc.                 │
│  5. Return Lex fulfillment response:                                 │
│     - dialogAction: { type: "ElicitSlot" | "Close" }                │
│     - messages: [{ contentType: "PlainText", content: ariaReply }]  │
│     - sessionAttributes: { ariaSessionId, authStatus, ... }         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP POST (SigV4)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│       Amazon Bedrock AgentCore Runtime (eu-west-2)                  │
│                                                                      │
│  ARIA Banking Agent (existing, unchanged)                            │
│  - Session keyed on ContactId from X-Amzn-...Session-Id header      │
│  - Full Strands agent with all banking tools                         │
│  - Authentication flow (auth/unauth mode)                            │
│  - Returns text response                                             │
│       │                                                              │
│       └── Tools: accounts, balances, statements,                    │
│               debit-card, credit-card, lost/stolen, auth            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
                    Nova Sonic speaks ARIA's text response
                    back to the customer on the phone
                    via Connect's native S2S pipeline
```

#### Why This Approach is Recommended

1. **Zero changes to ARIA AgentCore** — only a new Lambda function and Connect configuration
2. **Nova Sonic native quality** — Connect manages the audio pipeline with proper barge-in, endpointing, and voice selection
3. **All Connect benefits** — recording, queuing, routing, CCP, analytics, supervisor monitoring
4. **Session continuity** — `ContactId` (stable for the lifetime of the call) is used as the AgentCore session ID
5. **Well-documented path** — AWS officially supports Lambda fulfillment in Lex V2 bots within Connect
6. **Graceful escalation** — ARIA detects escalation intent → Lambda returns escalation signal → Connect routes to human queue

#### Limitations to Manage
- **Lambda 8-second timeout** on sync invocations: ARIA tool calls (account lookups, auth checks) must complete within ~7 s. For complex multi-tool turns, consider async Lambda (60 s) with a Wait block.
- **Text-only bridge**: Nova Sonic in Connect handles voice; AgentCore receives text (the transcript). For ultra-low latency audio (sub-200ms), Path B below may be preferred.
- **Lex V2 bot scaffolding required**: A minimal Lex V2 bot must exist as the container (single FallbackIntent is sufficient).

---

### 4.2 Path B: Kinesis Video Streams Audio Bridge → AgentCore WebSocket (ADVANCED)

This path streams raw PSTN audio from Connect to a custom bridge service, which connects directly to the AgentCore WebSocket and Nova Sonic. Audio latency can be lower, and no Lex bot is required.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     PSTN / Telephone Network                         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Amazon Connect                                     │
│                                                                      │
│  Contact Flow:                                                        │
│  [Entry] → [Set Attributes] → [Start Media Streaming]               │
│    ↓                                                                  │
│  [Invoke Lambda: aria-connect-bridge-start]                          │
│    ↓  (returns immediately; bridge runs async)                       │
│  [Wait block: up to 60s / poll for session state]                    │
│    ↓                                                                  │
│  [Loop: check DynamoDB for session-ended or escalation flag]         │
│    ↓ escalation                ↓ session end                         │
│  [Transfer to Queue]           [Disconnect]                          │
└──────┬──────────────────────────────────────────────────────────────┘
       │ Live Media Streaming (8kHz PCM)
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│            Amazon Kinesis Video Streams                              │
│                                                                      │
│  AUDIO_FROM_CUSTOMER track (8 kHz μ-law → PCM16)                   │
│  AUDIO_TO_CUSTOMER  track (what customer hears)                      │
└──────┬──────────────────────────────────────────────────────────────┘
       │ KVS GetMedia API (continuous)
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│    KVS→AgentCore Bridge Service (ECS Fargate, eu-west-2)            │
│                                                                      │
│  Per-call container instance:                                         │
│  1. Subscribe to KVS stream via GetMedia API                         │
│  2. Parse MKV/Matroska fragments → extract AUDIO_FROM_CUSTOMER      │
│  3. Resample: 8 kHz PCM16 → 16 kHz PCM16 (Nova Sonic input format) │
│  4. Open AgentCore WebSocket (SigV4)                                 │
│  5. Send SESSION_START_EVENT with ARIA system prompt                 │
│  6. Stream resampled audio chunks → AgentCore WebSocket             │
│  7. Receive Nova Sonic audio output (24 kHz PCM16) from AgentCore   │
│  8. Resample: 24 kHz → 8 kHz                                        │
│  9. Inject audio back to customer via Connect:                       │
│     → Option A: Lambda + Connect StartContactStreaming API           │
│     → Option B: AWS Chime SDK Voice Connector media gateway          │
│  10. On barge-in: detect INTERRUPTED event from AgentCore           │
│      → drain buffer; continue streaming customer audio              │
│  11. On session end: update DynamoDB session table → Connect polls  │
│      → Connect disconnects or transfers                              │
└──────────────────────────────────────────────────────────────────────┘
       │ WebSocket (SigV4)
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│         Amazon Bedrock AgentCore Runtime (existing ARIA)            │
│         Bidirectional WebSocket voice (Nova Sonic S2S)              │
└─────────────────────────────────────────────────────────────────────┘
```

#### Considerations for Path B
- **Higher complexity**: custom bridge service needs to handle KVS parsing (MKV), audio resampling, WebSocket lifecycle
- **Audio injection**: feeding processed audio back into an active Connect call is the hardest part — Connect does not natively support external audio injection on an active call; this requires Chime SDK Voice Connector or a third-party SIP gateway
- **Best for**: ultra-low latency requirements, or when you need the full power of AgentCore's native Nova Sonic pipeline on PSTN calls
- **Not recommended** for initial implementation

---

### 4.3 Path C: Amazon Connect Chat → AgentCore HTTP (Text Chat Channel)

For the **Connect chat channel** (website chat widget, WhatsApp, SMS via Pinpoint), ARIA can respond directly via Lambda.

```
Customer (website chat widget)
    ↓ Connect Chat API (StartChatContact)
Amazon Connect Chat
    ↓ Contact Flow → Lex bot → Lambda fulfillment
aria-connect-chat-fulfillment (Lambda)
    ↓ HTTP POST (SigV4)
AgentCore HTTP endpoint (/invocations)
    → ARIA Strands agent (text-only mode, no Nova Sonic)
    ← text response
    ↓
Lambda → Lex fulfillment response → Connect Chat → Customer
```

This is identical in structure to Path A but for the chat channel. The same Lambda function can serve both voice (transcript → text) and chat (message text) by detecting the channel type from contact attributes.

---

### 4.4 Path E: Lex V2 (Nova Sonic) + AMAZON.BedrockAgentIntent → Managed Bedrock Agent (RECOMMENDED FOR NEW DEPLOYMENTS)

This is the **optimal PSTN voice architecture** when you want native Bedrock Agent reasoning without writing a Lambda proxy bridge. Discovered after `AMAZON.BedrockAgentIntent` was made generally available in Lex V2.

```
┌──────────────────────────────────────────────────────────────────────┐
│                    PSTN / Telephone Network                           │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ PSTN
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                   Amazon Connect (eu-west-2)                          │
│                                                                       │
│  Inbound Contact Flow: ARIA-PathE-Banking-Flow                       │
│  [Set Voice: Amy, Generative (Nova Sonic S2S)]                       │
│      ↓                                                                │
│  [Set Recording + Contact Lens Real-time]                            │
│      ↓                                                                │
│  [Get Customer Input: ARIA-PathE-Bot (Lex V2)]                       │
│      ↓ customer speaks                                                │
│  Nova Sonic S2S: speech → text                                       │
│      ↓                                                                │
│  AMAZON.BedrockAgentIntent ← entire conversation delegated here      │
│      ↓ on escalation_requested=true                                   │
│  [Transfer to Queue: CustomerServiceQueue]                            │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ bedrock:InvokeAgent
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│      Managed Amazon Bedrock Agent: aria-banking-agent (eu-west-2)   │
│                                                                       │
│  Foundation model: Claude Sonnet 4.6                                 │
│  System prompt: Full ARIA banking persona                            │
│  User Input: ENABLED (allows multi-turn clarification)               │
│  Session TTL: 900 s                                                  │
│                                                                       │
│  Action Groups (Lambda-backed):                                       │
│  ├── auth-tools     → aria-banking-auth       (authenticate)         │
│  ├── account-tools  → aria-banking-account    (balance, statement)   │
│  ├── customer-tools → aria-banking-customer   (profile, vuln flag)   │
│  ├── debit-card     → aria-banking-debit-card (block, replace)       │
│  ├── credit-card    → aria-banking-credit-card (block, replace)      │
│  ├── mortgage-tools → aria-banking-mortgage   (details, balance)     │
│  └── escalation     → aria-banking-escalation (human handoff)        │
└──────────────────────────────────────────────────────────────────────┘
                               ↑
                    Existing ARIA AgentCore Runtime
                    (unchanged — continues to serve browser/mobile)
```

#### Why AMAZON.BedrockAgentIntent Changes Everything

The `AMAZON.BedrockAgentIntent` is a Lex V2 built-in intent that, when triggered, **delegates the entire conversation to a managed Amazon Bedrock Agent**. The key differences from Path A's Lambda bridge:

| Aspect | Path A (Lambda Bridge) | Path E (BedrockAgentIntent) |
|---|---|---|
| Per-turn Lambda | Yes — one proxy call per utterance | **No Lambda bridge** |
| Reasoning | None (dumb proxy) | Full Claude reasoning |
| Tools per turn | One sequential chain, must finish in ≤8 s | Agent calls N tools, manages state |
| Multi-turn auth flow | Lambda reads/writes session attrs manually | Agent handles natively |
| Session state | Lambda passes session attributes | Agent-native memory |
| Escalation detection | String matching in Lambda | Agent calls `escalate_to_human` tool |

#### Managed Agent vs Inline Agent vs AgentCore Runtime (Critical Distinction)

| | Managed Bedrock Agent | Inline Agent SDK | AgentCore Runtime |
|---|---|---|---|
| Used with BedrockAgentIntent | ✅ Yes | ❌ No | ❌ No |
| Tool mechanism | Lambda Action Groups | `mcp_clients=[]` | `@tool` decorators |
| MCP Gateway natively | ❌ No | ✅ Yes | ✅ Yes |

**`AMAZON.BedrockAgentIntent` requires a managed agent (Agent ID + Alias ID). It cannot be pointed at an AgentCore Runtime or an Inline Agent.**

#### Why Not MCP Gateway in Path E?

Since Path E uses Lambda Action Groups (not MCP), a question arises: could you add the AgentCore MCP Gateway instead?

No — managed Bedrock Agents do not natively speak MCP. The `mcp_clients` feature in the AWS MCP blog is exclusively for the **Inline Agent SDK**, not console-managed agents. Adding MCP Gateway in Path E would require an extra Lambda proxy that calls the Gateway (Lambda → MCP Gateway → Lambda) — a redundant hop with no benefit.

**Correct pairings:**
- Path E → Lambda Action Groups directly
- Option D (Connect Agentic) → AgentCore MCP Gateway
- These are separate integration paths; each is optimal for its invocation mechanism.

#### Limitations

- Requires creation of a separate managed Bedrock Agent (ARIA's AgentCore Runtime code is not reused — the prompt and tool definitions are replicated as Lambda Action Groups)
- Lambda Action Groups have individual timeouts (25 s recommended; 30 s hard limit from Bedrock Agent)
- On cold starts, multi-tool turns may add 2–5 s over Path A's cached AgentCore response

> **Full step-by-step setup**: `docs/amazon-connect-path-e-bedrock-agent-lex-guide.md`

---

## 5. Recommended Full Architecture — ARIA × Amazon Connect

Combining Path A (voice) and Path C (chat) into a unified architecture:

```
                    ╔══════════════════════════════════╗
                    ║      CUSTOMER TOUCHPOINTS        ║
                    ╠══════════════════════════════════╣
                    ║  📞 Phone (PSTN)                 ║
                    ║  💬 Website Chat Widget          ║
                    ║  📱 Mobile App (React Native)    ║
                    ║  🖥  Web App (existing, S3/CF)   ║
                    ╚═══════════╤══════════════════════╝
                                │
              ┌─────────────────┼──────────────────────┐
              │                 │                       │
              ▼                 ▼                       ▼
    ┌──────────────┐   ┌──────────────────┐   ┌────────────────┐
    │ Amazon       │   │  Amazon Connect  │   │ CloudFront     │
    │ Connect      │   │  Chat Channel    │   │ (existing)     │
    │ Voice (PSTN) │   │                  │   │ React SPA      │
    └──────┬───────┘   └────────┬─────────┘   └───────┬────────┘
           │                    │                      │
           ▼                    ▼                      │
    ┌──────────────────────────────────────┐           │
    │    Amazon Connect Contact Flows      │           │
    │                                      │           │
    │  Voice Flow:                         │           │
    │  Entry→SetVoice(Amy/Generative)      │           │
    │  →Get Customer Input (ARIA Lex Bot   │           │
    │    + Nova Sonic S2S)                 │           │
    │  →Lambda fulfillment on every turn   │           │
    │  →Escalation: Transfer to Queue      │           │
    │                                      │           │
    │  Chat Flow:                          │           │
    │  Entry→Lambda fulfillment on msg     │           │
    │  →Escalation: Transfer to Queue      │           │
    └──────────────────┬───────────────────┘           │
                       │                               │
                       ▼                               ▼
    ┌──────────────────────────────────────────────────────────┐
    │               AWS Lambda Layer                           │
    │                                                          │
    │  aria-connect-fulfillment                               │
    │  ┌──────────────────────────────────────────────────┐  │
    │  │  Input: Lex event                                │  │
    │  │   - inputTranscript (voice) or inputText (chat)  │  │
    │  │   - sessionAttributes: { contactId, channel,    │  │
    │  │     authStatus, customerId, ... }                │  │
    │  │  Process:                                        │  │
    │  │   1. Detect channel (voice/chat)                 │  │
    │  │   2. Build AgentCore POST request:               │  │
    │  │      POST /invocations                           │  │
    │  │      X-Amzn-...Session-Id: contactId            │  │
    │  │      { "prompt": userText }                      │  │
    │  │   3. SigV4 sign with Lambda execution role       │  │
    │  │   4. Parse ARIA response                         │  │
    │  │   5. Detect escalation keywords                  │  │
    │  │   6. Return Lex fulfillment response             │  │
    │  └──────────────────────────────────────────────────┘  │
    └──────────────────────┬───────────────────────────────────┘
                           │ HTTPS / SigV4
                           ▼
    ┌──────────────────────────────────────────────────────────┐
    │      Amazon Bedrock AgentCore Runtime (eu-west-2)        │
    │                                                          │
    │   ARIA Banking Agent (existing, unchanged)               │
    │   HTTP endpoint: POST /invocations                       │
    │   Session ID from X-Amzn-...Session-Id header           │
    │                                                          │
    │   ┌─────────────────────────────────────────────────┐   │
    │   │           Strands ARIA Agent                    │   │
    │   │  Authentication │ Account tools │ Card tools    │   │
    │   │  Balances      │ Statements    │ Lost/Stolen   │   │
    │   └─────────────────────────────────────────────────┘   │
    └──────────────────────────────────────────────────────────┘
                 ↑
          (existing WebSocket voice path for browser clients
           continues to work in parallel, unchanged)
```

### Human Escalation Flow

```
ARIA detects escalation intent
    ↓
Lambda returns: { sessionAttributes: { escalate: "true" } }
    ↓
Lex fulfillment → Contact Flow checks escalate attribute
    ↓
[Set Queue: meridian-bank-agents]
    ↓
[Get Queue Metrics: estimate wait time]
    ↓
[Play prompt: "Connecting you to an advisor. Expected wait ~X mins"]
    ↓
[Transfer to Queue]
    ↓
Human agent receives call on CCP
    + Contact attributes passed: customerId, authStatus, ariaTranscriptSummary
    + Screen pop (via CCP Streams API) shows customer context
```

---

## 6. Component Specifications

### 6.1 Amazon Connect Instance Configuration

| Setting | Value |
|---|---|
| Region | eu-west-2 (London, same as AgentCore) |
| Phone number type | DID (DDI) or Freephone (TFN) |
| Data storage | S3 bucket for call recordings |
| Live media streaming | Enabled (for analytics/compliance) |
| Logging | CloudWatch log group: `/aws/connect/aria-meridian` |

### 6.2 Amazon Lex V2 Bot — ARIA-Connect-Bot

**Purpose**: Scaffolding container for Nova Sonic S2S. Handles intent classification and Lambda fulfillment trigger.

| Property | Value |
|---|---|
| Bot name | ARIA-Connect-Bot |
| Region | eu-west-2 |
| Language/Locale | en_GB (maps to Amy voice) |
| Speech model | Speech-to-Speech: Amazon Nova Sonic |
| Voice | Amy (en-GB, Feminine, Generative style) |
| Intents | FallbackIntent (catch-all) + TransferToAgent |
| Fulfillment | Lambda: aria-connect-fulfillment (every turn) |
| Idle session timeout | 5 minutes |
| Clarification prompts | Disabled (ARIA handles clarification) |

**Intent design rationale**: Using a single `FallbackIntent` as catch-all means every utterance is forwarded to Lambda → AgentCore. ARIA handles all NLU and conversation logic; Lex is purely the audio + Lambda plumbing layer.

### 6.3 Lambda Function — aria-connect-fulfillment

```python
# aria_connect_fulfillment.py  (new file to be created)

import json, os, boto3, uuid
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
import urllib3

AGENTCORE_ENDPOINT = os.environ["AGENTCORE_ENDPOINT"]
# e.g. https://bedrock-agentcore.eu-west-2.amazonaws.com/runtimes/{arn}/invocations

ESCALATION_PHRASES = [
    "speak to an agent", "speak to someone", "transfer me",
    "human agent", "real person", "talk to a person"
]

def lambda_handler(event, context):
    # 1. Extract inputs
    intent_name    = event["sessionState"]["intent"]["name"]
    transcript     = event.get("inputTranscript", "")
    session_attrs  = event["sessionState"].get("sessionAttributes", {})
    contact_id     = session_attrs.get("contactId") or event.get("sessionId", str(uuid.uuid4()))

    # 2. Handle explicit TransferToAgent intent
    if intent_name == "TransferToAgent":
        return build_response("Connecting you now.", session_attrs, close=True, escalate=True)

    # 3. Call AgentCore ARIA
    aria_response = call_agentcore(transcript, contact_id)

    # 4. Detect escalation in ARIA response
    escalate = any(p in aria_response.lower() for p in ESCALATION_PHRASES)
    if escalate:
        session_attrs["escalate"] = "true"

    return build_response(aria_response, session_attrs, close=escalate, escalate=escalate)


def call_agentcore(user_text: str, session_id: str) -> str:
    session = boto3.Session()
    creds   = session.get_credentials().get_frozen_credentials()

    payload = json.dumps({"prompt": user_text}).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }

    request = AWSRequest(
        method="POST",
        url=AGENTCORE_ENDPOINT,
        data=payload,
        headers=headers,
    )
    SigV4Auth(creds, "bedrock-agentcore", "eu-west-2").add_auth(request)

    http = urllib3.PoolManager()
    resp = http.request(
        "POST", AGENTCORE_ENDPOINT,
        body=payload,
        headers=dict(request.headers),
        timeout=7.0,
    )

    if resp.status != 200:
        return "I'm sorry, I encountered a technical issue. Please hold."

    body = json.loads(resp.data.decode())
    return body.get("response") or body.get("content") or str(body)


def build_response(message, session_attrs, close=False, escalate=False):
    if escalate:
        session_attrs["escalate"] = "true"
    return {
        "sessionState": {
            "dialogAction": {
                "type": "Close" if close else "ElicitSlot",
                **({"slotToElicit": "__dummy__"} if not close else {}),
            },
            "intent": {
                "name": "FallbackIntent",
                "state": "Fulfilled" if close else "InProgress",
            },
            "sessionAttributes": session_attrs,
        },
        "messages": [{"contentType": "PlainText", "content": message}],
    }
```

**IAM Role for Lambda** (aria-connect-fulfillment-role):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:InvokeAgentRuntime"
      ],
      "Resource": "arn:aws:bedrock-agentcore:eu-west-2:395402194296:runtime/aria_banking_agent-ubLoKG8xsY"
    }
  ]
}
```

### 6.4 Contact Flow Logic (Pseudo-code)

```
INBOUND CONTACT FLOW: Meridian-ARIA-Voice

1. Entry Point
2. Set Voice
   └── Voice provider: Amazon
   └── Language: en-GB
   └── Voice: Amy
   └── Override speaking style: Generative  ← enables Nova Sonic
3. Set Contact Attributes
   └── contactId = $.ContactId
   └── channel = voice
4. Get Customer Input → ARIA-Connect-Bot (FallbackIntent)
   └── On DTMF/Speech: invoke Lambda aria-connect-fulfillment
   └── Check sessionAttributes.escalate
       ├── "true": → Step 5 (escalation)
       └── else:   → loop back to Get Customer Input
5. [Escalation Branch]
   Get Queue Metrics (meridian-bank-agents)
   Play Prompt: "Transferring you to an advisor. Estimated wait: {$.Queue.EstimatedWaitTime} minutes."
   Set Queue: meridian-bank-agents
   Transfer to Queue
   └── Error: Play "All agents busy" → Offer callback → Disconnect
```

### 6.5 Session State Management

| Attribute | Source | Purpose |
|---|---|---|
| `contactId` | `$.ContactId` (Connect) | AgentCore session ID — stable for call lifetime |
| `channel` | Set in flow | ARIA knows it's a phone call |
| `authStatus` | Returned from ARIA via Lambda | Track auth state across turns |
| `customerId` | Returned from ARIA via Lambda | Pre-populate CCP screen pop |
| `escalate` | Set by Lambda on detection | Trigger escalation branch in flow |
| `ariaTranscript` | Captured turn by turn | Passed to human agent on transfer |

---

## 7. Amazon Connect Chat Integration (Path C Detail)

For the chat channel (Connect Chat API + website widget):

```javascript
// connect-chat-widget.js  (new file, embedded in React SPA)
// Initialises Amazon Connect Chat widget, routes messages through ARIA

const connectChatConfig = {
  instanceId: "CONNECT_INSTANCE_ID",
  contactFlowId: "ARIA_CHAT_FLOW_ID",
  region: "eu-west-2",
  // The chat widget proxies messages to the same aria-connect-fulfillment Lambda
};
```

**Chat Contact Flow** is simpler than voice:
```
Customer sends message → Lambda(aria-connect-fulfillment) → AgentCore HTTP
ARIA replies text → Lambda → Connect Chat → Customer
(No Lex bot needed for chat; Lambda is called directly from the flow)
```

---

## 8. Security Architecture

### 8.1 IAM Trust Chain

```
Amazon Connect Service Role
    → Allowed to invoke: ARIA-Connect-Bot (Lex)

Lex V2 Execution Role  
    → Allowed to invoke: aria-connect-fulfillment (Lambda)

aria-connect-fulfillment Lambda Role
    → Allowed to call: bedrock-agentcore:InvokeAgentRuntime on ARIA runtime ARN
    → NOT allowed to read customer data directly (all via ARIA tools)

ARIA AgentCore Runtime (existing)
    → IAM role for Nova Sonic: bedrock:InvokeModel on amazon.nova-2-sonic-v1:0
    → Banking tool stubs (extensible to real core banking API via VPC + PrivateLink)
```

### 8.2 Data Flow & PII Handling

| Data Item | In Transit | At Rest |
|---|---|---|
| Customer voice audio | TLS (PSTN → Connect) | KMS-encrypted S3 (call recordings) |
| Transcripts (Lex ASR) | TLS | Connect contact records |
| ARIA session state | TLS (Lambda → AgentCore) | AgentCore microVM (ephemeral) |
| Contact attributes | In-memory in flow | Connect CTR (Contact Trace Record) |
| Authentication data (DOB, mobile) | Never stored by ARIA | Only verified, not persisted |

### 8.3 Network Security
- Lambda runs in VPC (optional but recommended) with VPC endpoint for AgentCore
- AgentCore runtime in eu-west-2; Nova Sonic model in us-east-1 (cross-region, AWS backbone)
- Connect instance in eu-west-2 (data residency for UK/EU compliance)
- All inter-service calls authenticated via IAM SigV4 (no API keys in code)

### 8.4 PCI DSS / Regulatory Considerations
Amazon Connect is **PCI DSS Level 1 certified**. For Meridian Bank:
- Enable **Contact Lens** for real-time redaction of card numbers and sort codes in transcripts
- Configure ARIA to use DTMF (keypad) for card PIN entry — never spoken aloud
- Call recordings encrypted with customer-managed KMS key
- Retention policies: 90 days for regulatory compliance, then S3 Glacier

---

## 9. Human Agent Escalation & CCP Integration

### 9.1 Contact Control Panel (CCP) Screen Pop

When ARIA escalates to a human agent:
1. Connect passes contact attributes to the agent's CCP
2. Custom CCP application (built with Amazon Connect Streams JS SDK) reads:
   - `customerId` → look up customer profile
   - `authStatus` → show verified/unverified badge
   - `ariaTranscriptSummary` → show conversation summary
   - `lastIntent` → show what customer was trying to do

### 9.2 Agent Assist (Future Enhancement)
- Contact Lens Real-Time can flag compliance issues live
- AgentCore could be called from agent-side Lambda to provide suggested responses
- ARIA could generate a post-call summary for agent wrap-up

### 9.3 Escalation Decision Matrix

| Trigger | Action |
|---|---|
| ARIA detects escalation intent | Lambda sets `escalate=true` → Transfer to Queue |
| ARIA auth fails 3× | Lambda returns special code → Transfer to ID&V specialist queue |
| Customer says "cancel my card" and says lost/stolen | ARIA handles directly; escalates if dispute reported |
| Queue wait > 10 mins | Offer callback via Lambda + Connect contact flow |
| Out of hours (outside 8am–8pm GMT) | Play ARIA-generated message → Voicemail/callback |

---

## 10. Call Recording, Analytics & Observability

### 10.1 Native Connect Recording
- All calls automatically recorded (S3, KMS-encrypted)
- Contact Lens transcription + sentiment analysis
- Post-call survey (optional)

### 10.2 Custom Analytics Pipeline

```
Amazon Connect → Kinesis Data Streams (Contact Records)
    ↓
Amazon Kinesis Firehose
    ↓
Amazon S3 → AWS Glue → Amazon Athena
    ↓
Amazon QuickSight dashboards:
  - Self-service rate (% handled by ARIA without escalation)
  - Authentication success/fail rates
  - Most common customer intents
  - Average handle time (ARIA vs human)
  - First-call resolution rate
```

### 10.3 AgentCore Observability (existing)
- OpenTelemetry traces: every ARIA tool invocation
- CloudWatch metrics: latency, error rates, token usage
- Distributed tracing: Connect → Lambda → AgentCore → Nova Sonic → tools

---

## 11. Implementation Roadmap

### Phase 1 — Voice Channel (Path E — Recommended for new deployments)
1. Create Amazon Connect instance in eu-west-2
2. Claim a UK phone number (+44)
3. Deploy 7 Lambda Action Group functions (`aria-banking-*`)
4. Create managed Bedrock Agent (`aria-banking-agent`) with ARIA system prompt and Lambda action groups
5. Create Lex V2 bot (`ARIA-PathE-Bot`, en-GB, Nova Sonic S2S) with `AMAZON.BedrockAgentIntent`
6. Build Inbound Contact Flow (SetVoice → ContactLens → GetCustomerInput → Escalation check)
7. Assign flow to phone number
8. Test: call the number, ARIA greets, auth works, multi-tool banking queries work, escalation routes to test queue

### Phase 1 (Alternative) — Voice Channel (Path A — Use if preserving existing ARIA container code)
1. Create Amazon Connect instance in eu-west-2
2. Claim a UK phone number (+44)
3. Create ARIA-Connect-Bot (Lex V2, en-GB locale, Nova Sonic S2S)
4. Deploy `aria-connect-fulfillment` Lambda with IAM role
5. Build Inbound Contact Flow (Entry → SetVoice → GetCustomerInput → Lambda → Escalation)
6. Assign flow to phone number
7. Test: call the number, ARIA answers, banking queries work, escalation routes to test queue

### Phase 2 — Chat Channel (Path C)
1. Create Amazon Connect Chat flow
2. Embed Connect Chat widget in existing React SPA (alongside existing HTTP chat)
3. Reuse `aria-connect-fulfillment` Lambda for chat (detect `channel=chat`)
4. Test: chat from website → ARIA responds

### Phase 3 — Human Agent Capability
1. Create Agent user accounts and routing profiles in Connect
2. Configure queues: `meridian-bank-general`, `meridian-bank-id-v`, `meridian-bank-complaints`
3. Build custom CCP with Streams SDK (screen pop from contact attributes)
4. Enable Contact Lens for PII redaction and sentiment
5. Set up supervisor monitoring and real-time dashboards

### Phase 4 — Analytics & Compliance
1. Enable Kinesis stream for contact records
2. Build Glue/Athena pipeline
3. QuickSight dashboards
4. Configure call recording retention policy (90 days + Glacier)
5. Enable CloudTrail auditing on all Connect API calls

### Phase 5 — Advanced (Optional)
1. Outbound dialling campaigns (payment reminders, statement notifications)
2. SMS channel via Pinpoint
3. WhatsApp Business via Connect
4. Amazon Q in Connect for real-time agent assist
5. Evaluate Option D (Connect Agentic + MCP Gateway) as an A/B test against Path E
6. Evaluate Path B (KVS bridge) if sub-200ms latency becomes a hard requirement

---

## 12. Key Architecture Decisions & Rationale

| Decision | Chosen Approach | Rationale |
|---|---|---|
| Voice AI engine | Native Connect Nova Sonic S2S | Officially supported; best audio quality; zero custom audio plumbing |
| Agent intelligence (new deployments) | Managed Bedrock Agent via BedrockAgentIntent (Path E) | Native reasoning; no Lambda bridge; multi-tool per turn |
| Agent intelligence (existing ARIA code) | Existing AgentCore ARIA via Lambda bridge (Path A) | Preserves all banking tools, auth logic, session management |
| Bridge mechanism (Path A) | Lambda fulfillment in Lex V2 | Standard AWS pattern; well-documented; ≤8s latency acceptable |
| Bridge mechanism (Path E) | AMAZON.BedrockAgentIntent (no bridge) | Lex delegates directly to Bedrock Agent; agent handles all reasoning |
| Tools in Path E | Lambda Action Groups on Managed Bedrock Agent | Only mechanism compatible with BedrockAgentIntent |
| Tools in Option D | AgentCore MCP Gateway → Lambda | Designed for Connect Agentic Self-Service native integration |
| MCP Gateway in Path E | Not used | Managed agents don't natively speak MCP; Inline Agent SDK does, but can't be used with BedrockAgentIntent |
| Session continuity | `ContactId` as AgentCore session ID (Path A) / Bedrock Agent native session (Path E) | Both stable for call lifetime |
| Channel routing | Single Lambda, channel-aware (Path A/C) | DRY; ARIA's text-based chat path works for both voice and chat |
| Escalation | Contact attribute + flow branch | Native Connect pattern; no custom state machine needed |
| Auth in Connect | Agent handles auth natively (all paths) | No change to existing auth flow; auth state in session |
| Recording | Native Connect S3 recording | PCI DSS compliant; no custom recording infrastructure |
| PII | Contact Lens redaction | Regulatory requirement for banking |

---

## 13. Integration Readiness Checklist

### Path A (Lambda Bridge → AgentCore)
Before going live on Connect:

- [ ] Amazon Connect instance created (eu-west-2)
- [ ] Phone number claimed and assigned to Meridian Bank
- [ ] ARIA-Connect-Bot (Lex V2) created with Nova Sonic S2S enabled
- [ ] `aria-connect-fulfillment` Lambda deployed and tested
- [ ] Lambda IAM role has `bedrock-agentcore:InvokeAgentRuntime` permission
- [ ] Contact Flow published and assigned to phone number
- [ ] AgentCore endpoint URL set as Lambda environment variable
- [ ] ContactId-based session routing validated (multi-turn voice conversation)
- [ ] Escalation branch tested (warm transfer to human agent queue)
- [ ] Call recording enabled (S3, KMS)
- [ ] Contact Lens enabled (PII redaction)
- [ ] CloudWatch alarms configured (Lambda errors, AgentCore latency)
- [ ] Load tested (10+ concurrent calls)

### Path E (BedrockAgentIntent → Managed Bedrock Agent) ⭐ Recommended
- [ ] 7 Lambda Action Group functions deployed (`aria-banking-*`)
- [ ] Bedrock Agent IAM role created (`aria-bedrock-agent-role`)
- [ ] Managed Bedrock Agent created (`aria-banking-agent`) with ARIA system prompt
- [ ] User Input set to ENABLED on the Agent (console: Additional Settings)
- [ ] All 7 action groups added with OpenAPI schemas and Lambda targets
- [ ] Agent prepared and production alias created
- [ ] Lex bot created (`ARIA-PathE-Bot`, en-GB, Nova Sonic Generative voice)
- [ ] Generative AI features enabled on the Lex locale
- [ ] `AMAZON.BedrockAgentIntent` added with Agent ID + Alias ID, overriding FallbackIntent
- [ ] Lex bot IAM role has `bedrock:InvokeAgent` permission on the Agent Alias ARN
- [ ] Bot built, versioned, and alias published
- [ ] Bot registered in Amazon Connect instance
- [ ] Nova Sonic S2S confirmed enabled on en-GB locale
- [ ] Contact Flow created with Set Voice (Amy, Generative) + Contact Lens enabled
- [ ] Escalation branch tested (escalation_requested attribute → queue transfer)
- [ ] Multi-tool turn tested (auth + balance + card in one utterance)
- [ ] Authentication failure flow tested (3 failed → ID&V queue)
- [ ] Call recording enabled (S3, KMS)
- [ ] CloudWatch alarms: Lambda errors, Bedrock Agent latency
- [ ] Load tested (10+ concurrent calls)

### Option D (Connect Agentic + MCP Gateway)
Refer to `docs/amazon-connect-agentic-mcp-setup-guide.md` for the full checklist.

---

*Document generated from official AWS sources: Amazon Bedrock AgentCore Developer Guide, Amazon Connect Administrator Guide (inc. native Nova Sonic S2S configuration), Amazon Nova User Guide, Kinesis Video Streams Developer Guide. Architecture validated against official AWS sample: `aws-samples/sample-amazon-connect-bedrock-agent-voice-integration`.*
