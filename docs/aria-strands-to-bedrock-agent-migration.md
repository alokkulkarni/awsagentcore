# Migrating ARIA from Strands AgentCore to Amazon Bedrock Agent
## And Extending to Amazon Connect Chat (Omnichannel)

> **Official references:**
> - [Amazon Bedrock Agents – How it works](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-how.html)
> - [Define OpenAPI schemas for action groups](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-api-schema.html)
> - [Configure Lambda functions for action groups](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html)
> - [Add an action group to your agent](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-action-add.html)
> - [Agent session state and attributes](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-session-state.html)
> - [Memory for agents](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-memory.html)
> - [Best practices: Lex V2 bot with Amazon Connect Chat](https://docs.aws.amazon.com/connect/latest/adminguide/bp-lex-bot-chat.html)
> - [AMAZON.BedrockAgentIntent](https://docs.aws.amazon.com/lexv2/latest/dg/built-in-intent-bedrockagent.html)
> - [AWS sample: omnichannel Lex + Bedrock](https://github.com/aws-samples/omnichannel-experience-bot-with-bedrock-and-lex)

---

## Overview

This document covers two related topics:

**Part A — Migration:** How to port the existing ARIA Strands agent (running on AgentCore Runtime) to a **managed Amazon Bedrock Agent** suitable for use with `AMAZON.BedrockAgentIntent` in Lex V2 (Path E).

**Part B — Chat Extension:** How to extend the same managed Bedrock Agent and the same Lex V2 bot to also serve the **Amazon Connect Chat channel** — so one agent and one bot serves voice (PSTN via Nova Sonic) and digital chat (Connect Chat widget, WhatsApp, SMS) simultaneously.

### What Stays, What Changes

```
BEFORE (current stack)
═════════════════════
Browser/Mobile
    │ WebSocket (voice)    HTTP (chat)
    ▼                      ▼
AgentCore Runtime Container (eu-west-2)
  ├─ agentcore_voice.py   (Nova Sonic S2S WebSocket handler)
  ├─ agentcore_app.py     (HTTP chat handler + session meta + audit)
  ├─ agent.py             (Strands Agent + BedrockModel)
  ├─ memory_client.py     (AgentCore Memory Store)
  ├─ audit_manager.py     (EventBridge + JSONL)
  └─ tools/ (20 tools: @tool decorated Python functions)
       ├─ pii/     (4: detect_redact, vault_store, vault_retrieve, vault_purge)
       ├─ auth/    (4: verify_identity, initiate_auth, validate_auth, cross_validate)
       ├─ customer/ (1: get_customer_details)
       ├─ account/  (1: get_account_details)
       ├─ debit_card/ (2: get_debit_card_details, block_debit_card)
       ├─ credit_card/ (1: get_credit_card_details)
       ├─ mortgage/    (1: get_mortgage_details)
       ├─ products/    (1: get_product_catalogue)
       ├─ analytics/   (1: analyse_spending)
       ├─ knowledge/   (2: search_knowledge_base, get_feature_parity)
       └─ escalation/  (2: generate_transcript_summary, escalate_to_human_agent)

AFTER (Path E addition — existing stack UNCHANGED)
══════════════════════════════════════════════════
Browser/Mobile (unchanged)
    │ WebSocket / HTTP → AgentCore Runtime (unchanged, still running)

PSTN + Chat (new Path E)
    │
Amazon Connect
    │ Voice: Lex V2 + Nova Sonic → AMAZON.BedrockAgentIntent
    │ Chat:  Lex V2 (text)       → AMAZON.BedrockAgentIntent
    ▼
Managed Bedrock Agent: aria-banking-agent
  ├─ Instruction: adapted ARIA system prompt
  ├─ Foundation model: Claude Sonnet 4.6
  ├─ Memory: Bedrock Agent session memory (replaces memory_client.py)
  └─ Action Groups → Lambda Functions
       ├─ pii-tools       → aria-banking-pii       (new Lambda)
       ├─ auth-tools      → aria-banking-auth       (exists)
       ├─ customer-tools  → aria-banking-customer   (exists)
       ├─ account-tools   → aria-banking-account    (exists)
       ├─ card-tools      → aria-banking-cards      (new: merged debit+credit)
       ├─ product-tools   → aria-banking-products   (new Lambda)
       └─ escalation-tools→ aria-banking-escalation (exists)
```

---

# Part A — Migrating ARIA Strands Agent to Managed Bedrock Agent

## A1. System Prompt Migration

### The Challenge

The ARIA system prompt (`aria/system_prompt.py`) is **35 KB / 442 lines** of detailed behavioral instructions across 9 sections. Amazon Bedrock Agent's `instruction` field supports this length — there is no documented hard character limit, and the AWS API payload ceiling (practical limit is tens of kilobytes) comfortably accommodates ARIA's prompt.

> **Official reference:** [Create an agent – instruction field](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-create.html). AWS recommends keeping instructions "clear and concise" but does not impose a hard byte limit for the instruction field specifically.

### What Changes in the Prompt

Three aspects need adapting when moving from Strands to a managed Bedrock Agent:

#### Change 1 — Section 0 Tool Table

**Strands**: The prompt begins with an explicit 20-tool table that Strands requires because tools are registered externally and the model needs to know their names.

**Bedrock Agent**: The agent **already knows its tools** via the action group OpenAPI schemas. The tool table in Section 0 becomes redundant and should be replaced with a brief capability summary, because re-listing tool names that conflict with OpenAPI `operationId` values can confuse the agent's orchestration.

Replace Section 0 entirely with:

```
## 0. Your Capabilities (Tool Reference)
You have access to grouped action sets for: PII handling, customer authentication,
customer profile, account details and transactions, card management (debit and credit),
mortgage details, product catalogue, spending analysis, knowledge base search, and
human escalation. Use tools exactly as described in the sections below. Never invent
or assume tool names — only call tools you are explicitly instructed to call.
```

#### Change 2 — PII Vault (In-Process State → DynamoDB-Backed)

**Strands**: The 4 PII vault tools (`pii_vault_store`, `pii_vault_retrieve`, `pii_vault_purge`, `pii_detect_and_redact`) use an in-memory Python dict (`_VAULT`) inside the AgentCore Runtime container. This is safe because the AgentCore Runtime provides **microVM isolation per session** — the dict lives and dies with the session.

**Bedrock Agent / Lambda**: Each Lambda invocation is stateless. The in-memory dict is destroyed after each call. The PII vault must be backed by an external session store.

**Solution**: DynamoDB PII Vault (see Section A3 for full implementation). The tool interface and system prompt logic stay identical — only the backing store changes.

```python
# Before (in-process, Strands):
_VAULT: dict[str, dict] = {}  # lives for the session

# After (Lambda, DynamoDB-backed):
TABLE = boto3.resource("dynamodb").Table(os.environ["PII_VAULT_TABLE"])
# TTL enforced via DynamoDB TTL attribute (900s)
```

The system prompt sections on PII (Section 2: Steps 1–4) remain **unchanged**. The vault instructions are tool-agnostic.

#### Change 3 — Tool Function Names

Some Strands tool function names differ from the `operationId` values in the existing Lambda OpenAPI schemas (from Option D guide). The system prompt must reference the **operationId names from the OpenAPI schemas**, not the Strands Python function names.

| Strands function name | Bedrock Agent operationId | Change? |
|---|---|---|
| `pii_detect_and_redact` | `pii_detect_and_redact` | No change |
| `pii_vault_store` | `pii_vault_store` | No change |
| `pii_vault_retrieve` | `pii_vault_retrieve` | No change |
| `pii_vault_purge` | `pii_vault_purge` | No change |
| `verify_customer_identity` | `verify_identity` | Update prompt refs |
| `initiate_customer_auth` | `initiate_auth` | Update prompt refs |
| `validate_customer_auth` | `validate_customer` | Update prompt refs |
| `cross_validate_session_identity` | `cross_validate` | Update prompt refs |
| `get_customer_details` | `get_customer_details` | No change |
| `get_account_details` | `get_account_details` | No change |
| `get_debit_card_details` | `get_debit_card_details` | No change |
| `block_debit_card` | `block_debit_card` | No change |
| `get_credit_card_details` | `get_credit_card_details` | No change |
| `get_mortgage_details` | `get_mortgage_details` | No change |
| `get_product_catalogue` | `get_product_catalogue` | No change |
| `analyse_spending` | `analyse_spending` | No change |
| `search_knowledge_base` | `search_knowledge_base` | No change |
| `get_feature_parity` | `get_feature_parity` | No change |
| `generate_transcript_summary` | `generate_transcript_summary` | No change |
| `escalate_to_human_agent` | `escalate_to_human_agent` | No change |

Only 4 auth tool names need updating in the prompt.

#### What Does NOT Change

Everything else in the system prompt migrates verbatim:
- Section 1: Agent identity and role
- Section 2: PII handling flow (all 4 steps — tool names updated per table above)
- Section 3: Channel and context extraction *(already channel-aware — works for chat too)*
- Section 4: Authentication gate, vulnerability protocol (FCA), in-call distress detection
- Section 5: Query handling (account, card, mortgage, products, knowledge)
- Section 6: Escalation protocol
- Section 7: Security guardrails
- Section 8: Tone and voice guidelines
- Section 9: Out-of-scope guardrail *(already channel-aware — chat gets links/numbers, voice escalates)*

> **Important**: Sections 3 and 9 already contain `channel`-aware logic that differentiates between voice and chat. This is fully preserved in the migration and is exactly what enables the bot to serve both channels from a single agent (see Part B).

### Applying the Prompt to the Bedrock Agent

```bash
# Read the adapted prompt from a file (recommended for 35KB prompts)
PROMPT=$(cat aria/system_prompt_bedrock.py | \
  python3 -c "import sys; exec(sys.stdin.read()); print(ARIA_SYSTEM_PROMPT)")

aws bedrock-agent update-agent \
  --agent-id "$AGENT_ID" \
  --agent-name aria-banking-agent \
  --foundation-model "anthropic.claude-sonnet-4-5-v1:0" \
  --agent-resource-role-arn "$AGENT_ROLE_ARN" \
  --instruction "$PROMPT" \
  --idle-session-ttl-in-seconds 900 \
  --region eu-west-2
```

> The `--instruction` field accepts the full prompt string. For prompts this size, passing via a file or Here-Document is more reliable than inline shell strings.

---

## A2. Runtime Injections — Complete Inventory and Migration

The AgentCore implementation does not just send `ARIA_SYSTEM_PROMPT` to the model. Both channels construct a **layered prompt** at runtime by combining the static system prompt with several dynamically-built injections. Each injection must have a clear equivalent in the Bedrock Agent path — or a deliberate decision to drop it.

### Inventory: All Runtime Injections in AgentCore

There are **9 distinct injection points** across the two channels.

---

#### Voice Channel — `agentcore_voice.py`

##### Injection V1 — Voice System Prompt Preamble (`_build_voice_system_prompt`)

**What it is:** A function called once when a voice WebSocket session opens. It returns `preamble + ARIA_SYSTEM_PROMPT` — i.e., the preamble is prepended to (not replacing) the full static system prompt.

**What the preamble contains (authenticated session):**
```
=== VOICE SESSION — CRITICAL OPERATING RULES ===

You are ARIA, Meridian Bank's voice banking assistant, on a LIVE call.

SESSION CONTEXT:
- Channel: voice (WebSocket audio stream via AgentCore Runtime)
- Auth state: authenticated
- Customer ID: CUST-001             ← runtime value
- Session ID: abc-123-xyz           ← runtime value (tools MUST use this for session_id params)
- The caller is already verified. Do NOT ask them to re-authenticate.
- Call get_customer_details("CUST-001") immediately, then greet by preferred_name.

[EMPATHY BLOCK — see Injection V2]

[CARD QUERIES — VOICE OVERRIDE — see Injection V3]

MANDATORY SESSION RULES:
1. Fetch customer profile first, then greet by name.
2. Session stays open until the caller says goodbye.
3. You are on VOICE — speak naturally. Never read full URLs or full card numbers.

=== END VOICE RULES — BANKING INSTRUCTIONS FOLLOW ===

[full ARIA_SYSTEM_PROMPT appended here]
```

**Why it exists:** Nova Sonic S2S is stateless per stream — it has no concept of session metadata. The only way to tell the model who the caller is, what their session ID is, and what channel they are on is by embedding it in the system prompt before the stream opens.

---

##### Injection V2 — `_EMPATHY_BLOCK` (voice-only, inside V1)

**What it is:** A 300-word block embedded inside the preamble (Injection V1). Covers voice-specific empathy and vulnerability detection cues that cannot be handled by the customer's tone of voice in text.

**Content summary:**
- EMPATHY TRIGGERS: what to say first when customer mentions lost card, fraud, bereavement, financial hardship, or sounds distressed
- VULNERABILITY DETECTION: spoken cues (distress/panic → slow pace; confusion/repetition → simplest language; third-party pressure → don't act, escalate; mid-call disclosure → adapt immediately)
- WARM ACKNOWLEDGMENT RULE: say something warm and human BEFORE any tool call on distressing calls

**Why voice-only:** On chat channels, tone cannot be heard. The empathy triggers are more about the absence of verbal warmth. Also, the static `ARIA_SYSTEM_PROMPT` already covers vulnerability detection at the profile-flag level (Section 4) — V2 extends it to real-time spoken signals.

---

##### Injection V3 — `CARD QUERIES — VOICE OVERRIDE` (voice-only, inside V1)

**What it is:** 5 mandatory rules appended to the preamble, specific to card queries over voice.

```
CARD QUERIES — VOICE OVERRIDE (MANDATORY):
After get_customer_details, you know every card_last_four from the profile.
  1. NEVER ask the customer to provide or confirm digits you already have.
  2. NEVER call pii_vault_retrieve for card_last_four — use profile values directly.
  3. ONE card of requested type → use its card_last_four directly. Tell the customer.
  4. MULTIPLE cards of same type → list scheme + last_four, ask which one.
  5. 'Confirm the card' = TELL the customer which card you are using.
```

**Why voice-only:** On voice, asking the customer to say their card number out loud is a security and usability problem. On chat, a customer can type card digits without broadcasting them. This override prevents the model from asking the customer to re-state information the agent already holds in the profile.

---

##### Injection V4 — History Block (AgentCore Memory, prepended to system prompt)

**What it is:** If `AGENTCORE_MEMORY_ID` is set and `memory_client.get_recent_turns()` returns prior conversation turns, a history block is prepended BEFORE the voice preamble:

```
=== RECENT CONVERSATION HISTORY (for context) ===
Customer: I wanted to check my balance
ARIA: Your current balance is £1,245.30. Is there anything else I can help with?
=== END HISTORY ===
```

**Final assembled system prompt for voice (when memory is configured):**
```
{history_block}
{voice_preamble}
{ARIA_SYSTEM_PROMPT}
```

**Why it exists:** Nova Sonic streams are isolated — each stream opening is a fresh model context. Without this, the model has no memory of what was discussed earlier in the session (or in a prior call from the same customer).

---

##### Injection V5 — `SESSION_START` Kickoff (first user message to Nova Sonic)

**What it is:** After the Nova Sonic stream opens but before the customer speaks, the voice handler sends a silent text `USER` turn (`interactive: False`) to trigger ARIA's opening greeting. This is a text event, not audio.

```
SESSION_START: An authenticated customer has connected.
X-Channel: voice. X-Channel-Auth: authenticated.
X-Customer-ID: CUST-001. X-Session-ID: abc-123-xyz.
Call get_customer_details with customer_id="CUST-001" to fetch their profile,
then greet them by their preferred_name and ask how you can help today.
Do not ask them to re-verify their identity.
```

**Why it exists:** Nova Sonic needs something to respond to before the customer speaks. Without this kickoff, ARIA sits silent waiting for the customer to speak first — which is wrong for a banking agent (the agent should greet the customer first).

---

##### Injection V6 — Stream Renewal History (`_build_history_events`)

**What it is:** Nova Sonic has a hard 600-second session limit. The voice handler renews the stream transparently at ~540 seconds. When opening the new stream, the last N turns of conversation (from `self._conversation_history`) are replayed as non-interactive AWS content blocks, so the new stream picks up where the old one left off.

**Budget:** max 40 KB total history, max 1 KB per individual turn, most recent turns prioritised.

**Note on `_build_context_preamble()`:** This method is called at line 623 of `agentcore_voice.py` (`context_preamble = self._build_context_preamble()`) but the method is never defined anywhere in the file, and the variable is never used after being assigned. This is dead/stub code — it has no effect and is not part of the actual renewal logic.

---

#### Chat Channel — `agentcore_app.py`

##### Injection C1 — `SESSION_START` First-Turn Text Injection

**What it is:** On the **first turn only** (`session_id not in _SESSION_STARTED`), the chat handler prepends a `SESSION_START` trigger to the customer's actual first message, combining both into a single LLM call:

```
SESSION_START: An authenticated customer has connected.
X-Channel-Auth: authenticated.
X-Customer-ID: CUST-001.
X-Channel: agentcore-chat.
Call get_customer_details with this customer ID to fetch their profile,
then greet them by their preferred_name and ask how you can help today.
Do not ask them to re-verify their identity.

Customer's first message: What's my account balance?
```

**Critical difference from voice:** Chat does NOT use `_build_voice_system_prompt()`. The Strands agent is created with just `ARIA_SYSTEM_PROMPT` — no voice preamble, no empathy block, no card override. The system prompt alone governs chat behaviour.

---

##### Injection C2 — In-Process Session State (`_SESSION_META`, `_SESSION_STARTED`, `_ENDED_SESSIONS`)

**What it is:** Three in-process dicts/sets maintained in `agentcore_app.py` per microVM lifetime:

| Structure | Type | Content | Purpose |
|---|---|---|---|
| `_CHAT_AGENTS[session_id]` | `dict[str, StrandsAgent]` | One Strands agent per session | Holds the full conversation in `agent.messages` |
| `_SESSION_META[session_id]` | `dict` | `{authenticated, customer_id, vulnerability}` | Carries auth + vulnerability state across turns |
| `_SESSION_STARTED` | `set[str]` | Set of session IDs | Prevents SESSION_START from being injected twice |
| `_ENDED_SESSIONS` | `set[str]` | Set of session IDs | Triggers clean slate when customer reconnects after farewell |

**Why they exist:** AgentCore routes all turns within a `session_id` to the same microVM process. These dicts are the source of truth for session-scoped state (auth, vulnerability flag, conversation history via agent.messages).

---

##### Injection C3 — Vulnerability Flag Detection and Propagation

**What it is:** After every turn, `_extract_vulnerability_from_messages()` scans the new entries in `agent.messages` for a `toolResult` from `get_customer_details` containing a non-null `vulnerability` field. Once detected, it is stored in `_SESSION_META[session_id]["vulnerability"]` and then passed to every subsequent `_emit_audit()` call — tagging all audit events for the session as vulnerable-customer interactions.

This is not a prompt injection — it is a post-turn state extraction that drives audit tagging. But it functions like an implicit session attribute.

---

### Migration Mapping — What Each Injection Becomes

| # | Injection | Current mechanism | Bedrock Agent equivalent | Action required |
|---|---|---|---|---|
| V1 | Voice preamble header + SESSION CONTEXT block | `_build_voice_system_prompt()` | Session attributes from Contact Flow + instruction conditional blocks | Embed channel-conditional sections in `instruction` field |
| V1a | **Session ID in system prompt** (`- Session ID: {session_id}`) | Dynamic f-string in preamble | `event["sessionId"]` in every Lambda invocation | Remove from instruction; tell agent: "the session ID is provided to every tool automatically — do not repeat it in tool calls" |
| V1b | **Customer ID in system prompt** (`- Customer ID: {customer_id}`) | Dynamic f-string in preamble | `sessionAttributes.customerId` set by Contact Flow | `instruction` rule: "If `sessionAttributes.customerId` is present at session start, call `get_customer_details` with that value immediately, then greet by preferred_name" |
| V1c | **Auth state in system prompt** (`Auth state: authenticated`) | Dynamic f-string | `sessionAttributes.authenticated = 'true'` from Contact Flow | `instruction` rule: "If `sessionAttributes.authenticated = 'true'` and `customerId` is present, skip identity verification" |
| V1d | **Channel in system prompt** (`Channel: voice`) | Dynamic f-string | `sessionAttributes.channel` set by Contact Flow | Already handled by Section 3 of ARIA_SYSTEM_PROMPT — no change needed |
| V2 | `_EMPATHY_BLOCK` | Voice preamble only | Add to `instruction` as `[VOICE CHANNEL ONLY]` conditional block | Add to instruction (see section below) |
| V3 | `CARD QUERIES — VOICE OVERRIDE` | Voice preamble only | Add to `instruction` as `[VOICE CHANNEL ONLY]` conditional block | Add to instruction (see section below) |
| V4 | History block (AgentCore Memory) | Prepended to system prompt | Bedrock Agent native `SESSION_SUMMARY` memory | Enable `memoryConfiguration` on the agent — handled automatically |
| V5 | `SESSION_START` kickoff text (voice) | `_send_kickoff()` — first Nova Sonic USER event | Contact Flow session attributes + `instruction` telling agent what to do on first turn | No explicit kickoff needed — agent reads session attributes on turn 1 |
| V5a | `SESSION_START` first-message injection (chat) | `_build_session_start()` prepended to first message | Same as V5 — replaced by session attributes | No explicit injection needed |
| V6 | Stream renewal history (`_build_history_events`) | Nova Sonic stream renewal only | Not applicable — Connect manages session; no 600s limit | Nothing to do |
| — | `_build_context_preamble()` | Dead code (never executes) | Nothing | Nothing |
| C1 | `SESSION_START` first-turn injection (chat) | `agentcore_app.py` per-session flag | Replaced by session attributes + instruction | Session attributes replace this entirely |
| C2 | In-process session state dicts | `_SESSION_META`, `_CHAT_AGENTS` etc. | `sessionAttributes` (Bedrock Agent native, per-session key-value) | Use `sessionAttributes` in Lambdas; pass `vulnerability_flag` back as session attribute |
| C3 | Vulnerability flag extraction | Post-turn scan of `agent.messages` | `get_customer_details` Lambda sets `sessionAttributes.vulnerability_flag` | Lambda-side: after returning customer profile, include vulnerability flag in `sessionAttributes` return |

---

### How Session Attributes Replace Runtime Injections

Session attributes are the Bedrock Agent's equivalent of runtime injection. They are set by the Connect Contact Flow **before** the first customer utterance reaches the bot — so the Bedrock Agent has them from turn 1.

**Contact Flow configuration (Set Contact Attributes block):**

```
channel         = voice          (or "chat")
authenticated   = true           (or "false")
customerId      = CUST-001       (from Connect customer profile lookup, or "" if unknown)
contactId       = $.ContactId    (Connect Contact ID — used as session ID for tools)
```

**What Bedrock Agent Lambda sees on every invocation:**

```json
{
  "sessionId": "abc-123-xyz",
  "sessionAttributes": {
    "channel":       "voice",
    "authenticated": "true",
    "customerId":    "CUST-001",
    "contactId":     "abc-123-xyz"
  }
}
```

> **Note**: `event["sessionId"]` is the Bedrock Agent session ID — typically set to the Connect Contact ID by the Lex V2 integration. Tools should use `event["sessionId"]` as the `session_id` for PII vault calls. They do NOT need it in the system prompt.

**Lambda sets vulnerability back as a session attribute after `get_customer_details`:**

```python
# Inside aria_customer_handler.py, after fetching profile
vulnerability = customer_profile.get("vulnerability")  # e.g. {"flag_type": "financial_difficulty", ...}

return {
    "messageVersion": "1.0",
    "response": { ... },
    "sessionAttributes": {
        **session_attrs,                          # preserve existing attributes
        "vulnerability_flag": "true" if vulnerability else "false",
        "vulnerability_type": vulnerability.get("flag_type", "") if vulnerability else "",
    }
}
```

On all subsequent turns, every Lambda action group will see `sessionAttributes.vulnerability_flag = "true"` and can use it for audit tagging — exactly replicating what `_SESSION_META[session_id]["vulnerability"]` does today.

---

### New Instruction Additions for Bedrock Agent

Because voice-specific injections (V1, V2, V3) can no longer be dynamically prepended at session start, their content must live permanently in the `instruction` field, gated by `sessionAttributes.channel`. Add the following two blocks to the adapted ARIA instruction (after Section 8 Tone Guidelines):

```
## 8b. Voice Channel — Empathy and Tonal Rules
(Apply only when sessionAttributes.channel is 'voice' or 'ivr')

Voice is the most personal channel. Customers can hear warmth and care — use that.

EMPATHY TRIGGERS — acknowledge the customer's feelings FIRST, then respond:
- Lost or stolen card: "I'm really sorry to hear that — let me get that sorted right away."
  Then proceed immediately to identify the card and initiate the block.
- Suspected fraud: "That must be really worrying. Let me look into that straightaway."
- Financial concern or missed payment: Acknowledge calmly, without judgement:
  "I understand — let me pull up the details so we can go through this together."
- Bereavement: Speak very gently. Offer the bereavement specialist team before anything else:
  "I'm so sorry for your loss. I'd like to make sure you get the right support — would it be
  alright if I connected you with our specialist team?"
- Financial hardship: "I hear you, and we want to make sure you get the right support.
  Let me see what options are available for you."
- Customer sounds distressed or overwhelmed: Pause before responding. Speak more slowly.
  Acknowledge: "Take your time — there's no rush at all." Do NOT rush to the task.

VULNERABILITY DETECTION — listen for spoken cues, not just the profile flag:
- Distress or panic → slow your pace, use very short sentences, acknowledge and reassure.
- Confusion or repetition → use simplest possible language, confirm understanding after each step.
- Third-party pressure → do NOT proceed with irreversible actions, escalate to specialist.
- Mid-call disclosure → adapt immediately, offer specialist support before continuing.

WARM ACKNOWLEDGMENT RULE:
On any distressing call — say something warm and human BEFORE any task or tool call.

## 8c. Voice Channel — Card Query Rules
(Apply only when sessionAttributes.channel is 'voice' or 'ivr')

After get_customer_details, you know every card_last_four from the customer profile.
1. NEVER ask the customer to provide or confirm card digits you already have from the profile.
2. NEVER call pii_vault_retrieve for card_last_four — use profile values directly.
3. ONE card of the requested type → use its card_last_four directly. Tell the customer which card.
4. MULTIPLE cards of the same type → list scheme and last four digits, ask which one.
5. "Confirm the card" means TELL the customer which card you are using — not ask them to confirm digits.

## 8d. Session Initialisation Rules

On the FIRST turn of every session:
- Read sessionAttributes.channel to know your channel context.
- If sessionAttributes.authenticated = 'true' AND sessionAttributes.customerId is present:
    Call get_customer_details with that customerId immediately.
    Then greet the customer by their preferred_name and ask how you can help.
    Do NOT ask them to re-verify their identity.
- If sessionAttributes.authenticated = 'false' OR customerId is absent:
    Greet the caller warmly as ARIA from Meridian Bank and begin the identity verification flow.
- The session ID passed to all PII vault and authentication tools is provided automatically
  in the tool event — you do not need to ask for it or track it yourself.
```

---

### Vulnerability Flag — End-to-End Flow in Bedrock Agent

```
Contact Flow
  └─ sessionAttributes: {authenticated: "true", customerId: "CUST-005"}
       │
       ▼
Lex V2 → AMAZON.BedrockAgentIntent
       │
       ▼
Bedrock Agent (turn 1)
  └─ Reads session attributes
  └─ Instruction 8d: authenticated + customerId present
  └─ Calls get_customer_details("CUST-005")
       │
       ▼
aria-banking-customer Lambda
  └─ Fetches customer profile
  └─ Detects vulnerability: {flag_type: "financial_difficulty", refer_to_specialist: true}
  └─ Returns profile in responseBody
  └─ Sets sessionAttributes:
       vulnerability_flag = "true"
       vulnerability_type = "financial_difficulty"
       │
       ▼
Bedrock Agent (turn 1 continues)
  └─ Profile returned: vulnerability present
  └─ System prompt Section 4 applies: specialist referral, suppress promotion/collections
  └─ Greets customer warmly — does NOT mention vulnerability flag
       │
       ▼
All subsequent Lambda invocations for this session:
  └─ event["sessionAttributes"]["vulnerability_flag"] = "true"
  └─ event["sessionAttributes"]["vulnerability_type"] = "financial_difficulty"
  └─ aria_audit.emit() tags all events as HIGH severity, vulnerable_customer=True
```

---

## A3. Tool Migration — 20 Strands Tools → 7 Lambda Action Groups

### Official Lambda Event/Response Contract

Before migrating each tool, understand the **exact** Lambda event format Bedrock Agent sends (from [official docs](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html)):

**Lambda Input Event (API schema-based action group):**
```json
{
  "messageVersion": "1.0",
  "agent": {
    "name": "aria-banking-agent",
    "id": "ABCDEF1234",
    "alias": "TSTALIASID",
    "version": "1"
  },
  "inputText": "What is my account balance?",
  "sessionId": "unique-session-id",
  "actionGroup": "account-tools",
  "apiPath": "/get_account_details",
  "httpMethod": "POST",
  "parameters": [],
  "requestBody": {
    "content": {
      "application/json": {
        "properties": [
          {"name": "customer_id", "type": "string", "value": "CUST-001"},
          {"name": "account_number", "type": "string", "value": "vault://session-id/account_number"},
          {"name": "query_subtype", "type": "string", "value": "balance"}
        ]
      }
    }
  },
  "sessionAttributes": {
    "channel": "voice",
    "contactId": "abc-123"
  },
  "promptSessionAttributes": {}
}
```

**Lambda Response (must match this format exactly):**
```json
{
  "messageVersion": "1.0",
  "response": {
    "actionGroup": "account-tools",
    "apiPath": "/get_account_details",
    "httpMethod": "POST",
    "httpStatusCode": 200,
    "responseBody": {
      "application/json": {
        "body": "{\"account_number_last_four\": \"4821\", \"available_balance\": 1245.30, \"currency\": \"GBP\"}"
      }
    }
  },
  "sessionAttributes": {
    "channel": "voice",
    "contactId": "abc-123"
  },
  "promptSessionAttributes": {}
}
```

> **Key points from official docs:**
> - `responseBody.application/json.body` must be a **JSON-formatted string** (double-encoded), not a raw object
> - Parameters arrive in `requestBody.content.application/json.properties` as a list of `{name, type, value}` — not a flat dict
> - One Lambda receives all operations for an action group (dispatch on `apiPath`)
> - Max 11 API operations per action group
> - `sessionAttributes` passes through and can be read/written by the Lambda

### Tool-to-Action-Group Mapping

All 20 Strands tools map to 7 Lambda action groups, each under the 11-operation limit:

| Action Group | Lambda | Operations (operationId) | Count |
|---|---|---|---|
| `pii-tools` | `aria-banking-pii` | `pii_detect_and_redact`, `pii_vault_store`, `pii_vault_retrieve`, `pii_vault_purge` | 4 |
| `auth-tools` | `aria-banking-auth` | `verify_identity`, `initiate_auth`, `validate_customer`, `cross_validate` | 4 |
| `customer-tools` | `aria-banking-customer` | `get_customer_details` | 1 |
| `account-tools` | `aria-banking-account` | `get_account_details`, `analyse_spending` | 2 |
| `card-tools` | `aria-banking-cards` | `get_debit_card_details`, `block_debit_card`, `get_credit_card_details`, `request_card_replacement` | 4 |
| `product-tools` | `aria-banking-products` | `get_mortgage_details`, `get_product_catalogue`, `search_knowledge_base`, `get_feature_parity` | 4 |
| `escalation-tools` | `aria-banking-escalation` | `generate_transcript_summary`, `escalate_to_human_agent` | 2 |

### Lambda Handler Pattern

All Lambda handlers follow the same pattern — dispatch on `apiPath`, parse from `requestBody.content`, return in the required format:

```python
# aria_banking_template.py — copy this pattern for every Lambda

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: dict, context) -> dict:
    """Standard Bedrock Agent action group Lambda handler."""
    logger.info("Bedrock Agent event: %s", json.dumps(event, default=str))

    action_group = event.get("actionGroup", "")
    api_path     = event.get("apiPath", "")
    http_method  = event.get("httpMethod", "POST")
    session_id   = event.get("sessionId", "")
    session_attrs = event.get("sessionAttributes", {})

    # Parse parameters from requestBody
    params = _parse_params(event)

    # Dispatch on apiPath
    dispatch = {
        "/my_operation": _handle_my_operation,
        # ... add operations
    }

    handler = dispatch.get(api_path)
    if handler is None:
        return _error_response(action_group, api_path, http_method, f"Unknown path: {api_path}")

    try:
        result = handler(params, session_id, session_attrs)
        return _ok_response(action_group, api_path, http_method, result, session_attrs)
    except Exception as exc:
        logger.exception("Tool error for %s", api_path)
        return _error_response(action_group, api_path, http_method, str(exc))


def _parse_params(event: dict) -> dict:
    """Extract parameters from the Bedrock Agent requestBody format."""
    params = {}
    try:
        properties = (
            event
            .get("requestBody", {})
            .get("content", {})
            .get("application/json", {})
            .get("properties", [])
        )
        for prop in properties:
            params[prop["name"]] = prop["value"]
    except (KeyError, TypeError):
        pass
    # Also check top-level parameters list (used when action group defines function details)
    for p in event.get("parameters", []):
        params[p["name"]] = p["value"]
    return params


def _ok_response(action_group, api_path, http_method, body: dict, session_attrs: dict) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(body)   # ← must be a JSON string, not object
                }
            }
        },
        "sessionAttributes": session_attrs,
        "promptSessionAttributes": {}
    }


def _error_response(action_group, api_path, http_method, message: str) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "apiPath": api_path,
            "httpMethod": http_method,
            "httpStatusCode": 500,
            "responseBody": {
                "application/json": {
                    "body": json.dumps({"error": message})
                }
            }
        },
        "sessionAttributes": {},
        "promptSessionAttributes": {}
    }
```

Save this as `scripts/lambdas/bedrock_agent/aria_handler_base.py` and import in each Lambda.

---

## A4. PII Vault Migration — In-Process Dict → DynamoDB

### The Problem

The Strands PII vault uses a Python dict (`_VAULT`) in the AgentCore container process. Each Lambda invocation for a Bedrock Agent action group is **stateless** — the dict is destroyed after each call. Multi-step auth flows (detect → store → retrieve across different turns) will fail without a persistent store.

### Solution: DynamoDB PII Vault

Create a DynamoDB table with TTL for session-scoped PII storage:

```bash
# Create the DynamoDB PII vault table
aws dynamodb create-table \
  --table-name aria-pii-vault \
  --attribute-definitions \
    AttributeName=session_id,AttributeType=S \
    AttributeName=token_key,AttributeType=S \
  --key-schema \
    AttributeName=session_id,KeyType=HASH \
    AttributeName=token_key,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region eu-west-2

# Enable TTL on the expiry_epoch column (items auto-deleted at session end)
aws dynamodb update-time-to-live \
  --table-name aria-pii-vault \
  --time-to-live-specification "Enabled=true,AttributeName=expiry_epoch" \
  --region eu-west-2
```

Grant the `aria-banking-pii` Lambda role access:
```bash
aws iam put-role-policy \
  --role-name aria-banking-tools-lambda-role \
  --policy-name aria-pii-vault-access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:DeleteItem",
        "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:eu-west-2:395402194296:table/aria-pii-vault"
    }]
  }'
```

### DynamoDB-Backed PII Vault Lambda

Create `scripts/lambdas/bedrock_agent/aria_pii_handler.py`:

```python
"""
aria_pii_handler.py — DynamoDB-backed PII vault for Bedrock Agent (Path E)

Replicates the 4 PII vault @tool functions from the Strands ARIA agent
using DynamoDB as the session-scoped store with TTL-based expiry.

Official Lambda event format: https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html
"""

import hashlib
import json
import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_DYNAMODB = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "eu-west-2"))
_TABLE    = _DYNAMODB.Table(os.environ.get("PII_VAULT_TABLE", "aria-pii-vault"))
_MAX_TTL  = 900  # 15 minutes, matching original Strands implementation

# PII patterns (simplified — extend with Comprehend for production)
import re
_PII_PATTERNS = {
    "account_number": r"\b\d{8}\b",
    "sort_code":      r"\b\d{2}-\d{2}-\d{2}\b",
    "card_number":    r"\b(?:\d{4}[\s-]?){3}\d{4}\b",
    "mobile":         r"\b(?:07\d{9}|\+44\d{10})\b",
    "dob":            r"\b\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\b",
}


def lambda_handler(event: dict, context) -> dict:
    action_group = event.get("actionGroup", "")
    api_path     = event.get("apiPath", "")
    http_method  = event.get("httpMethod", "POST")
    session_id   = event.get("sessionId", "")
    session_attrs = event.get("sessionAttributes", {})
    params = _parse_params(event)

    dispatch = {
        "/pii_detect_and_redact": _detect_and_redact,
        "/pii_vault_store":       _vault_store,
        "/pii_vault_retrieve":    _vault_retrieve,
        "/pii_vault_purge":       _vault_purge,
    }
    handler = dispatch.get(api_path)
    if not handler:
        return _error(action_group, api_path, http_method, f"Unknown path: {api_path}")
    try:
        result = handler(params, session_id)
        return _ok(action_group, api_path, http_method, result, session_attrs)
    except Exception as exc:
        logger.exception("PII vault error")
        return _error(action_group, api_path, http_method, str(exc))


def _detect_and_redact(params: dict, session_id: str) -> dict:
    text = params.get("raw_text", "")
    pii_types = params.get("pii_types", list(_PII_PATTERNS.keys()))
    pii_map = {}
    redacted = text

    for ptype in pii_types:
        pattern = _PII_PATTERNS.get(ptype)
        if not pattern:
            continue
        for match in re.finditer(pattern, redacted):
            raw = match.group()
            token_key = f"{ptype}_{hashlib.sha256(raw.encode()).hexdigest()[:8]}"
            pii_map[token_key] = raw
            redacted = redacted.replace(raw, f"[{ptype.upper()}_REDACTED]", 1)

    return {
        "pii_detected": bool(pii_map),
        "redacted_text": redacted,
        "pii_map": pii_map,
        "pii_types_found": list(pii_map.keys()),
    }


def _vault_store(params: dict, session_id: str) -> dict:
    pii_map = params.get("pii_map", {})
    ttl_seconds = min(int(params.get("ttl_seconds", _MAX_TTL)), _MAX_TTL)
    expiry_epoch = int(time.time()) + ttl_seconds
    vault_refs = {}

    for token_key, raw_value in pii_map.items():
        vault_ref = f"vault://{session_id}/{token_key}"
        try:
            _TABLE.put_item(
                Item={
                    "session_id": session_id,
                    "token_key":  token_key,
                    "raw_value":  raw_value,
                    "expiry_epoch": expiry_epoch,
                },
                ConditionExpression="attribute_not_exists(token_key)",  # write-once
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        vault_refs[token_key] = vault_ref

    return {
        "vault_status": "stored",
        "vault_refs": vault_refs,
        "expiry_epoch": expiry_epoch,
    }


def _vault_retrieve(params: dict, session_id: str) -> dict:
    vault_ref = params.get("vault_ref", "")
    # vault_ref format: vault://{session_id}/{token_key}
    token_key = vault_ref.split("/")[-1] if vault_ref.startswith("vault://") else vault_ref

    resp = _TABLE.get_item(Key={"session_id": session_id, "token_key": token_key})
    item = resp.get("Item")
    if not item or int(item.get("expiry_epoch", 0)) < int(time.time()):
        return {"retrieved": False, "reason": "Token not found or expired"}

    return {
        "retrieved": True,
        "token_key": token_key,
        "value": item["raw_value"],
    }


def _vault_purge(params: dict, session_id: str) -> dict:
    purge_reason = params.get("purge_reason", "session_end")
    # Query all tokens for this session
    resp = _TABLE.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("session_id").eq(session_id)
    )
    count = 0
    with _TABLE.batch_writer() as batch:
        for item in resp.get("Items", []):
            batch.delete_item(Key={"session_id": session_id, "token_key": item["token_key"]})
            count += 1

    logger.info("PII vault purged: session=%s reason=%s tokens=%d", session_id, purge_reason, count)
    return {"purged": True, "tokens_purged": count, "purge_reason": purge_reason}


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_params(event: dict) -> dict:
    params = {}
    for p in (event.get("requestBody", {})
              .get("content", {})
              .get("application/json", {})
              .get("properties", [])):
        params[p["name"]] = p["value"]
    for p in event.get("parameters", []):
        params[p["name"]] = p["value"]
    return params


def _ok(ag, path, method, body, session_attrs) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": ag, "apiPath": path, "httpMethod": method,
            "httpStatusCode": 200,
            "responseBody": {"application/json": {"body": json.dumps(body)}}
        },
        "sessionAttributes": session_attrs,
        "promptSessionAttributes": {}
    }


def _error(ag, path, method, msg) -> dict:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": ag, "apiPath": path, "httpMethod": method,
            "httpStatusCode": 500,
            "responseBody": {"application/json": {"body": json.dumps({"error": msg})}}
        },
        "sessionAttributes": {},
        "promptSessionAttributes": {}
    }
```

Deploy this as the `aria-banking-pii` Lambda function:
```bash
cd scripts/lambdas/bedrock_agent
zip aria_pii_handler.zip aria_pii_handler.py

aws lambda create-function \
  --function-name aria-banking-pii \
  --runtime python3.12 \
  --role arn:aws:iam::395402194296:role/aria-banking-tools-lambda-role \
  --handler aria_pii_handler.lambda_handler \
  --zip-file fileb://aria_pii_handler.zip \
  --timeout 25 \
  --environment Variables="{PII_VAULT_TABLE=aria-pii-vault}" \
  --region eu-west-2
```

---

## A5. Migrating the Auth Lambda

The existing `aria-banking-auth` Lambda (`scripts/lambdas/mcp_tools/aria_auth_handler.py`) was written for the MCP Gateway event format (`event["toolName"]`). For Bedrock Agent action groups it must be updated to the **official Bedrock Agent Lambda event format** (`event["apiPath"]`).

Create `scripts/lambdas/bedrock_agent/aria_auth_handler.py`:

```python
"""
aria_auth_handler.py — Auth action group Lambda for Bedrock Agent (Path E)

Migrated from Strands @tool functions:
  verify_customer_identity → /verify_identity
  initiate_customer_auth   → /initiate_auth
  validate_customer_auth   → /validate_customer
  cross_validate_session_identity → /cross_validate

Lambda event format: https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html
"""
import json, logging, os, uuid
logger = logging.getLogger(); logger.setLevel(logging.INFO)

# ── stub customer registry (replace with real auth service) ──────────────────
_CUSTOMERS = {
    "CUST-001": {"name": "James",  "dob": "09/09/1982", "mobile_last_four": "9252"},
    "CUST-002": {"name": "Sarah",  "dob": "14/03/1990", "mobile_last_four": "4471"},
    "CUST-003": {"name": "Robert", "dob": "22/07/1955", "mobile_last_four": "8812"},
    "CUST-004": {"name": "Emma",   "dob": "05/12/1988", "mobile_last_four": "3371"},
    "CUST-005": {"name": "Dorothy","dob": "18/04/1942", "mobile_last_four": "6621"},
}

def lambda_handler(event, context):
    ag      = event.get("actionGroup", "")
    path    = event.get("apiPath", "")
    method  = event.get("httpMethod", "POST")
    session = event.get("sessionId", "")
    session_attrs = event.get("sessionAttributes", {})
    params  = _parse(event)

    dispatch = {
        "/verify_identity":  _verify_identity,
        "/initiate_auth":    _initiate_auth,
        "/validate_customer":_validate_customer,
        "/cross_validate":   _cross_validate,
    }
    fn = dispatch.get(path)
    if not fn:
        return _err(ag, path, method, f"Unknown: {path}")
    try:
        return _ok(ag, path, method, fn(params, session), session_attrs)
    except Exception as e:
        logger.exception("auth error"); return _err(ag, path, method, str(e))

def _verify_identity(p, _):
    header = p.get("header_customer_id", "").strip()
    requested = p.get("requested_customer_id", "").strip()
    match = bool(header and header == requested)
    return {"identity_match": match, "risk_score": 10 if match else 90,
            "auth_level": "full" if match else "none"}

def _initiate_auth(p, _):
    return {"session_started": True,
            "auth_session_id": str(uuid.uuid4()),
            "challenge_type": "knowledge_based",
            "status": "initiated",
            "required_fields": ["date_of_birth", "mobile_last_four"]}

def _validate_customer(p, _):
    cid = p.get("customer_id", "").strip()
    return {"valid": cid in _CUSTOMERS, "customer_found": cid in _CUSTOMERS}

def _cross_validate(p, _):
    cid     = p.get("customer_id", "").strip()
    dob     = p.get("date_of_birth", "").strip()
    mobile4 = p.get("mobile_last_four", "").strip()
    if cid not in _CUSTOMERS:
        return {"verified": False, "reason": "Customer not found."}
    c = _CUSTOMERS[cid]
    if c["dob"] == dob and c["mobile_last_four"] == mobile4:
        return {"verified": True, "customer_id": cid, "name": c["name"], "auth_level": "full"}
    return {"verified": False, "reason": "Verification details do not match our records."}

def _parse(event):
    p = {}
    for x in event.get("requestBody",{}).get("content",{}).get("application/json",{}).get("properties",[]):
        p[x["name"]] = x["value"]
    for x in event.get("parameters", []):
        p[x["name"]] = x["value"]
    return p

def _ok(ag, path, method, body, session_attrs):
    return {"messageVersion":"1.0","response":{"actionGroup":ag,"apiPath":path,"httpMethod":method,
            "httpStatusCode":200,"responseBody":{"application/json":{"body":json.dumps(body)}}},
            "sessionAttributes":session_attrs,"promptSessionAttributes":{}}

def _err(ag, path, method, msg):
    return {"messageVersion":"1.0","response":{"actionGroup":ag,"apiPath":path,"httpMethod":method,
            "httpStatusCode":500,"responseBody":{"application/json":{"body":json.dumps({"error":msg})}}},
            "sessionAttributes":{},"promptSessionAttributes":{}}
```

> **Pattern to follow for all other Lambdas**: The account, customer, card, products, and escalation Lambdas from `scripts/lambdas/mcp_tools/` all need the same adaptation — replace `event["toolName"]` dispatch with `event["apiPath"]` dispatch, and wrap responses in the Bedrock Agent response envelope. The tool logic itself (the stub data, the business rules) stays identical.

---

## A6. Audit Events from Lambda

The Strands `audit_manager.py` emits audit events to EventBridge and local JSONL from within the AgentCore container. In the Lambda path, **each Lambda is responsible for emitting its own audit event** after executing a tool.

Add this helper to each Lambda that handles regulated operations (auth, card actions, escalation):

```python
# aria_audit.py — add to scripts/lambdas/bedrock_agent/

import json, logging, os, uuid
from datetime import datetime, timezone

import boto3

_EB_BUS = os.environ.get("AUDIT_EVENTBRIDGE_BUS", "")
_REGION = os.environ.get("AWS_REGION", "eu-west-2")
_eb     = boto3.client("events", region_name=_REGION) if _EB_BUS else None

logger = logging.getLogger("aria.audit")


def emit(
    tool_name: str,
    session_id: str,
    customer_id: str,
    outcome: str,
    channel: str = "voice",
    vulnerability: dict = None,
    extra: dict = None,
):
    """Emit an audit event to EventBridge (matches audit_manager.py schema)."""
    if not _eb:
        return  # local/test mode

    _TOOL_META = {
        "cross_validate":          ("AUTH_VALIDATION",   "AUTHENTICATION",  1, "HIGH"),
        "verify_identity":         ("IDENTITY_VERIFY",   "AUTHENTICATION",  1, "HIGH"),
        "block_debit_card":        ("CARD_BLOCK",        "CARD_MANAGEMENT", 1, "CRITICAL"),
        "escalate_to_human_agent": ("AGENT_ESCALATION",  "ESCALATION",      1, "HIGH"),
        # extend as needed
    }
    event_type, category, tier, severity = _TOOL_META.get(
        tool_name, ("TOOL_INVOCATION", "GENERAL", 3, "INFO")
    )

    if vulnerability:
        severity = "HIGH"

    detail = {
        "event_id":       str(uuid.uuid4()),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "session_id":     session_id,
        "customer_id":    customer_id,
        "tool_name":      tool_name,
        "event_type":     event_type,
        "category":       category,
        "tier":           tier,
        "severity":       severity,
        "outcome":        outcome,
        "channel":        channel,
        "agent_path":     "path_e_bedrock_agent",
        **({"vulnerable_customer": True,
            "vulnerability_type": vulnerability.get("flag_type"),
            } if vulnerability else {}),
        **(extra or {}),
    }

    try:
        _eb.put_events(Entries=[{
            "Source":       "aria.banking.agent",
            "DetailType":   event_type,
            "Detail":       json.dumps(detail),
            "EventBusName": _EB_BUS,
        }])
    except Exception:
        logger.exception("Audit EventBridge emit failed — non-blocking")
```

Usage in a Lambda:
```python
from aria_audit import emit

# after successful cross_validate:
emit("cross_validate", session_id, customer_id, "success",
     channel=session_attrs.get("channel", "voice"))
```

---

## A7. Session Memory Migration

### Current (AgentCore `memory_client.py`)
`memory_client.py` wraps the AgentCore Memory Store API, saving conversation history across `/invocations` calls using `AGENTCORE_MEMORY_ID`.

### Bedrock Agent Memory
Managed Bedrock Agents have **built-in session memory** that does not require custom code.

> **Official reference**: [Memory for agents in Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-memory.html)

Two memory types are supported:
- `SESSION_SUMMARY` — summarizes completed sessions and stores the summary for future sessions (cross-session memory)
- `RECENT_CONVERSATION_HISTORY` — keeps the last N turns in context within a session

Enable on the agent:
```bash
aws bedrock-agent update-agent \
  --agent-id "$AGENT_ID" \
  --agent-name aria-banking-agent \
  --foundation-model "anthropic.claude-sonnet-4-5-v1:0" \
  --agent-resource-role-arn "$AGENT_ROLE_ARN" \
  --memory-configuration '{
    "enabledMemoryTypes": ["SESSION_SUMMARY"],
    "storageDays": 30
  }' \
  --region eu-west-2
```

> **Note**: `SESSION_SUMMARY` memory requires the agent IAM role to have `bedrock:InvokeModel` permission (already granted). Memory storage up to 30 days is available. PII vault data must NOT be stored in agent memory — it is handled separately via DynamoDB with 900s TTL.

### Migration Mapping

| AgentCore `memory_client.py` | Bedrock Agent equivalent |
|---|---|
| `save_memory(session_id, turn)` | Automatic — agent stores turns natively |
| `retrieve_history(session_id)` | Automatic — injected into context by the agent |
| `AGENTCORE_MEMORY_ID` env var | `memoryConfiguration` on the agent |
| 30-day retention | `storageDays: 30` in `memoryConfiguration` |

The `memory_client.py` module and the `AGENTCORE_MEMORY_ID` environment variable are **not needed** for Path E. They continue to exist in the AgentCore Runtime container unchanged.

---

## A8. Complete Migration Checklist

| Task | File/Resource | Status |
|---|---|---|
| Adapt system prompt (Section 0, tool name updates) | `aria/system_prompt_bedrock.py` (new) | Create |
| Create DynamoDB PII vault table | `aria-pii-vault` (DynamoDB) | Create |
| Deploy `aria-banking-pii` Lambda | `scripts/lambdas/bedrock_agent/aria_pii_handler.py` | Create |
| Update `aria-banking-auth` Lambda for Bedrock event format | `scripts/lambdas/bedrock_agent/aria_auth_handler.py` | Create |
| Update `aria-banking-account` Lambda for Bedrock event format | `scripts/lambdas/bedrock_agent/aria_account_handler.py` | Update |
| Update `aria-banking-customer` Lambda for Bedrock event format | `scripts/lambdas/bedrock_agent/aria_customer_handler.py` | Update |
| Create `aria-banking-cards` Lambda (merged debit + credit) | `scripts/lambdas/bedrock_agent/aria_cards_handler.py` | Create |
| Create `aria-banking-products` Lambda (mortgage + catalogue + KB) | `scripts/lambdas/bedrock_agent/aria_products_handler.py` | Create |
| Update `aria-banking-escalation` Lambda for Bedrock event format | `scripts/lambdas/bedrock_agent/aria_escalation_handler.py` | Update |
| Add audit helper to each Lambda | `scripts/lambdas/bedrock_agent/aria_audit.py` | Create |
| Create managed Bedrock Agent with adapted prompt | `aria-banking-agent` (Bedrock console/CLI) | Create |
| Add 7 action groups with OpenAPI schemas | Bedrock console/CLI | Create |
| Enable User Input on the agent | Bedrock console | Configure |
| Enable session memory | `memoryConfiguration` on agent | Configure |
| Create agent alias | `production` alias | Create |

---

# Part B — Extending to Amazon Connect Chat

## B1. The Single-Bot, Dual-Channel Architecture

The same Lex V2 bot (`ARIA-PathE-Bot`) and the same managed Bedrock Agent (`aria-banking-agent`) can serve **both** Amazon Connect PSTN voice **and** Amazon Connect Chat from a single deployment. AWS officially confirms this pattern:

> *"Amazon Connect allows you to use the same Amazon Lex V2 bot for both voice and chat channels."*
> — [Best practices for using the chat channel and Amazon Lex](https://docs.aws.amazon.com/connect/latest/adminguide/bp-lex-bot-chat.html)

```
Amazon Connect Voice (PSTN)
    │
    ▼  Nova Sonic S2S (speech ↔ text)
Lex V2 bot: ARIA-PathE-Bot (en-GB)
    │  AMAZON.BedrockAgentIntent
    ▼
Bedrock Agent: aria-banking-agent
    │  Action Groups (Lambda tools)
    ▲
Lex V2 bot: ARIA-PathE-Bot (en-GB)  ← same bot
    │  AMAZON.BedrockAgentIntent
    │  text input/output (no Nova Sonic for chat)
    ▼
Amazon Connect Chat
    │
    ▼
Customer chat widget / WhatsApp / SMS
```

**One bot. One agent. Two channels.** The ARIA system prompt's channel-aware logic (Sections 3 and 9) handles all behavioral differences automatically.

## B2. How the ARIA System Prompt Already Handles Both Channels

The existing system prompt already distinguishes voice from chat across multiple sections. No prompt changes are needed for chat — just pass the correct `channel` session attribute.

### Section 3 — Channel Detection (already in prompt)
```
- Voice channels (voice, ivr): Never give phone numbers — customer is already on the phone.
  For out-of-scope, escalate to human agent.
- Digital/Chat channels (chat, mobile, web, branch-kiosk): Providing phone numbers,
  URLs, and self-service links is appropriate.
```

### Section 9 — Out-of-Scope Response (already in prompt, channel-aware)
```
Voice channel: escalate to human agent (no phone numbers, no URLs)
Digital/Chat channel: "For [topic], you can [URL / phone number / branch]"
```

### Session Attribute: `channel`

The bridge between Connect and the agent's channel-aware behavior is a single session attribute. Pass it from the Contact Flow:

| Channel | Value to pass | How |
|---|---|---|
| Voice (PSTN) | `channel=voice` | Contact Flow → Set Contact Attributes → passed to Lex |
| Connect Chat | `channel=chat` | Chat Contact Flow → Set Contact Attributes → passed to Lex |
| Mobile app (future) | `channel=mobile` | Same pattern |

## B3. Chat-Specific Response Considerations

When `channel=chat`, the Bedrock Agent should produce responses appropriate for text rendering. The ARIA system prompt's Section 8 tone guidelines say "short sentences" and "no bullet points" — this is correct for voice but suboptimal for chat.

**Add a channel-adaptive paragraph to the system prompt** (the only chat-specific change needed):

```
## 8a. Channel-Adaptive Formatting

When channel is 'voice' or 'ivr':
- Short sentences (under 20 words)
- No bullet points, numbered lists, or markdown
- No URLs or phone numbers (customer is on the phone)

When channel is 'chat', 'mobile', 'web', or 'branch-kiosk':
- You may use short bullet lists for clarity (2–4 items max)
- You may include self-service URLs from get_feature_parity
- You may provide phone numbers when directing to a team
- Keep responses concise — under 100 words where possible
```

## B4. Amazon Connect Chat Setup

### B4.1 — Enable Chat in Your Connect Instance

1. In the Connect admin console, go to **Channels → Chat**
2. Confirm chat is enabled on your instance (it is on by default for all Connect instances)
3. Note your **Connect instance alias** (e.g., `meridian-aria`)

### B4.2 — Create a Chat Contact Flow

1. In Connect admin console → **Routing → Contact flows**
2. Click **Create contact flow** → **Inbound flow** (type: Chat)
3. Name: `ARIA-PathE-Chat-Flow`

Build with 5 blocks:

**Block 1: Set Contact Attributes**
- Type: **Set contact attributes**
- Add: `channel` = `chat`
- Add: `contactId` = `$.ContactId`

**Block 2: Set Recording and Analytics**
- Type: **Set recording and analytics behavior**
- **Contact Lens real-time analytics: Enabled**
- Chat transcripts: Enabled (stored in S3)

**Block 3: Get Customer Input (Chat bot)**
- Type: **Get customer input**
- Select: **Amazon Lex**
- Bot: `ARIA-PathE-Bot`
- Alias: `production`
- Language: `en-GB`
- Session attributes:
  - `channel` → `chat`
  - `contactId` → `$.ContactId`
- **No voice/SSML settings** — chat uses text only
- Timeout: 5 minutes (chat sessions can be longer than voice)

**Block 4: Check for Escalation**
- Type: **Check contact attributes**
- Check: `$.Attributes.escalation_requested` = `true`
  - True → Block 5
  - No match → Loop to Block 3

**Block 5: Transfer to Queue**
- Type: **Transfer to queue**
- Queue: `CustomerServiceQueue`
- Whisper flow: brief the human agent with chat transcript summary

4. Click **Save** → **Publish**

### B4.3 — Create a Chat Widget for Your Website

```bash
# Create a chat widget security profile (allows unauthenticated chat initiation)
aws connect create-participant \
  --instance-id "$CONNECT_INSTANCE_ID" \
  --contact-id "$CONTACT_ID" \
  --participant-details '{"DisplayName": "Customer"}' \
  --region eu-west-2
```

Or embed the Connect Chat widget in the existing React SPA via the official Amazon Connect Chat UI SDK:

```bash
npm install amazon-connect-chatjs
```

```javascript
// src/components/ARIAChatWidget.jsx
import "amazon-connect-chatjs";

const connectConfig = {
  instanceId: process.env.VITE_CONNECT_INSTANCE_ID,
  contactFlowId: process.env.VITE_CONNECT_CHAT_FLOW_ID, // ARIA-PathE-Chat-Flow ID
  region: "eu-west-2",
  apiGatewayEndpoint: process.env.VITE_CONNECT_API_GW_ENDPOINT,
  // The chat widget sends messages → Connect → Lex bot → BedrockAgentIntent → Bedrock Agent
};

export function ARIAChatWidget() {
  return (
    <div id="aria-chat-container">
      <button onClick={() => window.connect.ChatInterface.initiateChat({
        ...connectConfig,
        name: "Customer",
        username: "customer",
        contactAttributes: JSON.stringify({
          channel: "chat",
          source: "web"
        }),
      })}>
        Chat with ARIA
      </button>
    </div>
  );
}
```

Add to your React SPA's `.env.local`:
```bash
VITE_CONNECT_INSTANCE_ID=<your-connect-instance-id>
VITE_CONNECT_CHAT_FLOW_ID=<ARIA-PathE-Chat-Flow-id>
VITE_CONNECT_API_GW_ENDPOINT=https://<instance-id>.execute-api.eu-west-2.amazonaws.com/Prod
```

> **Official Connect Chat SDK**: [Amazon Connect ChatJS on GitHub](https://github.com/amazon-connect/amazon-connect-chatjs)

### B4.4 — Assign the Chat Flow to Your Connect Instance

The Chat flow doesn't attach to a phone number — it attaches directly to the chat widget and is referenced by Contact Flow ID. Verify by initiating a test chat:

1. Connect admin console → **Test chat** (top right menu)
2. Select `ARIA-PathE-Chat-Flow`
3. Type a message — ARIA should respond via the Bedrock Agent

## B5. Response Rendering Differences (Voice vs Chat)

| Behaviour | Voice | Chat |
|---|---|---|
| Nova Sonic S2S | ✅ Active | ❌ Not used (text only) |
| Response formatting | Plain sentences, no markdown | May use short bullet lists |
| URLs | ❌ Never | ✅ Allowed (get_feature_parity) |
| Phone numbers | ❌ Never (already on the phone) | ✅ Allowed |
| Escalation | Transfer to queue (phone transfer) | Transfer to queue (chat handoff to agent CCP) |
| Session timeout | 15 min idle | 60 min idle (configurable) |
| Barge-in | ✅ Nova Sonic native | N/A |
| Typing indicators | N/A | ✅ Connect native |
| Rich content (cards, buttons) | ❌ | ✅ Via Connect Chat Interactive Messages |

> For interactive messages (quick reply buttons, list pickers) in chat, see [Interactive messages in Amazon Connect Chat](https://docs.aws.amazon.com/connect/latest/adminguide/interactive-messages.html). The Bedrock Agent can return structured JSON from the escalation Lambda to trigger these.

## B6. Testing Both Channels

### Voice Test
```
Phone: Dial your Connect phone number
Expected: Nova Sonic greets as ARIA, auth flow works, banking queries answered,
          escalation routes to CustomerServiceQueue
```

### Chat Test
```
Widget: Open ARIA chat widget on website
Expected: ARIA greets in text, auth flow works, account details returned,
          responses include links and phone numbers where appropriate
Check: sessionAttribute channel=chat reaches the Bedrock Agent Lambda
       (visible in Lambda CloudWatch logs)
```

### Confirm Channel Attribute is Passed

```bash
# Add a log line to your auth Lambda to confirm channel attribute:
logger.info("Session: id=%s channel=%s", session_id, session_attrs.get("channel", "MISSING"))

# Then check:
aws logs tail /aws/lambda/aria-banking-auth --follow --region eu-west-2
```

You should see:
```
Session: id=abc-123 channel=voice   (for PSTN call)
Session: id=def-456 channel=chat    (for chat message)
```

---

## B7. Full Omnichannel Architecture (Path E + Chat)

```
                    ┌─────────────────────────────────┐
                    │        CUSTOMER TOUCHPOINTS      │
                    ├─────────────────────────────────┤
                    │  📞 PSTN Phone call              │
                    │  💬 Website chat widget          │
                    │  📱 WhatsApp (via Connect)       │
                    │  📲 Mobile app web chat          │
                    │  🖥  Existing React SPA (voice)  │
                    └────────┬──────────┬─────────────┘
                             │          │
              ┌──────────────┘          └─────────────────┐
              ▼                                           ▼
  ┌────────────────────┐                    ┌─────────────────────────┐
  │  Amazon Connect    │                    │ CloudFront (existing)   │
  │  Voice (PSTN)      │                    │  React SPA              │
  │  Contact Flow:     │                    │  ├─ WebSocket voice      │
  │  ARIA-PathE-Voice  │                    │  └─ HTTP chat            │
  └────────┬───────────┘                    └──────────┬──────────────┘
           │                                           │
           ▼                                           ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │             Lex V2 Bot: ARIA-PathE-Bot (en-GB)                    │
  │  Voice: Nova Sonic S2S          Chat: Text input/output            │
  │  sessionAttribute: channel=voice     sessionAttribute: channel=chat│
  │              ↓                                  ↓                  │
  │         AMAZON.BedrockAgentIntent ← single shared intent          │
  └──────────────────────────────┬─────────────────────────────────────┘
                                 │ bedrock:InvokeAgent
                                 ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │          Managed Bedrock Agent: aria-banking-agent                 │
  │  Model: Claude Sonnet 4.6 + ARIA system prompt (channel-aware)     │
  │  Memory: SESSION_SUMMARY (30 days)                                  │
  │                                                                     │
  │  Action Groups:                                                     │
  │  ├─ pii-tools       → Lambda: aria-banking-pii   (DynamoDB vault)  │
  │  ├─ auth-tools      → Lambda: aria-banking-auth                    │
  │  ├─ customer-tools  → Lambda: aria-banking-customer                │
  │  ├─ account-tools   → Lambda: aria-banking-account                 │
  │  ├─ card-tools      → Lambda: aria-banking-cards                   │
  │  ├─ product-tools   → Lambda: aria-banking-products                │
  │  └─ escalation-tools→ Lambda: aria-banking-escalation (→ EventBridge│
  │                         audit + Connect queue transfer)             │
  └─────────────────────────────────────────────────────────────────────┘
                      ↑ Existing (unmodified)
  AgentCore Runtime Container
  └─ Serves browser WebSocket voice + HTTP chat (unchanged)
```

---

## B8. Environment Variables Summary

Lambda environment variables to add for the new bedrock_agent Lambda handlers:

| Variable | Value | Which Lambda |
|---|---|---|
| `PII_VAULT_TABLE` | `aria-pii-vault` | `aria-banking-pii` |
| `AUDIT_EVENTBRIDGE_BUS` | EventBridge bus name/ARN | All Lambdas (optional) |
| `AWS_REGION` | `eu-west-2` | All Lambdas |

---

## B9. What the AgentCore Runtime Keeps

Nothing in the existing AgentCore Runtime needs to change. The migration is purely additive:

| Component | AgentCore Runtime | Path E Bedrock Agent |
|---|---|---|
| `aria/system_prompt.py` | Used as-is | Adapted copy in new agent |
| `aria/agent.py` | Strands agent setup | Replaced by managed agent |
| `aria/agentcore_app.py` | HTTP chat handler | Not used (Lex handles chat via agent) |
| `aria/agentcore_voice.py` | WebSocket voice | Not used (Connect handles PSTN voice) |
| `aria/memory_client.py` | AgentCore Memory | Replaced by agent memory config |
| `aria/audit_manager.py` | EventBridge audit | Replicated in each Lambda |
| `aria/tools/` (all 20) | Used by Strands | Replicated as Lambda action groups |
| Browser WebSocket voice | ✅ Continues working | — |
| Browser/mobile HTTP chat | ✅ Continues working | — |

---

*Sources: Amazon Bedrock Agents User Guide (Lambda function format, action groups, memory), Amazon Connect Administrator Guide (Chat setup, best practices for Lex bots, interactive messages), Amazon Lex V2 Developer Guide (BedrockAgentIntent, channel support), AWS sample `aws-samples/omnichannel-experience-bot-with-bedrock-and-lex`.*
