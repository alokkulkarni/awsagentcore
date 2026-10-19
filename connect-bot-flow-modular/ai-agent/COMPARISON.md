# ARIA review: live (my-conversation-agent v38) vs v2

Read on 18 Oct 2026 from Connect, read-only:
- the agent: v38 (v37 plus `customer_id` on the card block tools; published 18 Oct 10:22), prompt
  `ARIA-Banking-Ochestration-Prompt` v27, guardrail `ARIA-Banking-Guardrail` v3, the Money
  Hub collaborator;
- ARIA's traces for every contact in the last 14 days (97 contacts, 44 with a trace).

v2 lives in this folder. It is **new**: nothing live was changed.

## Verdict in one paragraph

ARIA's business logic is sound, and v2 keeps all of it. But the prompt, written over many iterations, still tells
her to call **9 tools she doesn't have**, to return **3 Lex intents the flow can't act on**, to react to **session
values nothing sets**, and to use **escalation reasons the Escalate tool rejects**. It also contradicts itself on
tone. At best these instructions waste reasoning; at worst they make ARIA promise something nobody delivers (a
callback, a text message, a keypad transfer). v2 removes them, and sends each customer need to what does exist
(mostly Escalate). One attached tool (QueryAssistant) is never used and is dropped. The prompt goes from 87,334 to
68,504 characters, with the same 19 session variables, model and guardrail.

## Tools: are they all needed?

Use in the last 14 days (demo traffic, so low counts mean little; the prompt and flow are the main evidence):
Money Hub collaborator 15 · Complete 9 · get_credit_card_details 2 · StartCardDispute 2 (old version) · others 0.

| Tool | Verdict | Why |
|---|---|---|
| Complete | **keep** | Ends her part, and hands over with `nextStep` (dispute, mortgage) |
| Escalate | **keep** | The only way to transfer to a person |
| Money Hub collaborator | **keep** | Money questions for verified customers |
| Retrieve | **keep** | Knowledge base (overridden to the bank's KB association) |
| search_knowledge_base, get_feature_parity | **keep** (overlap) | The prompt uses both alongside Retrieve. Consider merging into Retrieve later |
| get_account_balance / _details / get_recent_transactions | **keep** | Account questions |
| get_customer_details | **keep** | First step of every pre-authenticated session |
| verify_customer_identity, initiate_customer_auth, validate_customer_auth | **keep** | Unauthenticated sessions (no verified link, no ID&V). Unused lately, but the path exists |
| send_push_challenge, verify_push_challenge | **keep** | Level 3 → 4 payment approval in the app |
| get_/block_ debit card, get_/block_ credit card | **keep** | Card questions and lost or stolen blocks. The blocks now take `customer_id` like the other card tools, so a customer can only block their own card |
| get_mortgage_details | **keep** | Mortgage questions |
| get_product_catalogue | **keep** | Product questions |
| analyse_spending | **keep** (overlap) | Quick spending figures. In-depth money questions go to the Money Hub agent, which v2 now says explicitly |
| **QueryAssistant** | **remove** | No instruction, never mentioned in the prompt, never used. Every other tool is named in the prompt |

v2's tools are v38's minus QueryAssistant, **byte-for-byte** (schemas, `customer_id` scoping on every card tool
including the blocks, Retrieve override, Complete and Escalate instructions). The collaborator, guardrail v3, locale and instance are unchanged.

## Prompt: what's kept, what's removed, what's new

| Live section | In v2 | Notes |
|---|---|---|
| Intro, formatting rules (voice/chat, money, digits, dates) | **word for word** | |
| Agent Identity | **word for word** | |
| PII Handling (4-step pipeline) | **removed → "Personal Data"** | The pii_* tools aren't attached. Kept: use the session's customerId, mask to last four, keep PII in thinking |
| Farewell rule | **word for word** | Was hidden inside the PII section; now its own |
| Session Context, `<customer_context>`, personalisation | **word for word** | Same 19 variables |
| `<known_contact_reasons>` | **word for word** | |
| "Channel rules" (4 lines) | **removed** | Duplicated the formatting rules and Out-of-Scope |
| Greeting protocol | **word for word** | |
| Authentication gate, `<assurance_levels>`, payment step-up | **word for word** | |
| `<money_hub>` | **one fix** | `escalationReason customer_request (or vulnerability…)`: neither is an Escalate value. Now `customer_requested`, with "Vulnerability flag:" in the summary (the live mapping table's own rule) |
| `<card_disputes>`, `<mortgage_applications>` | **word for word** | |
| Pre-authenticated sessions | **word for word** | |
| Vulnerability protocol | **one fix** | refer_to_specialist named `escalate_to_human_agent query_context` → the Escalate tool with "Vulnerability flag: [flag_type]" |
| In-call distress | **fixed** | `escalation_reason: vulnerability / fraud_dispute, priority: …` → Escalate values per the live mapping table: crisis, self-harm and coercion → general_banking with "Vulnerability flag: …"; fraud → fraud_security. Safeguarding needs no confirmation (as live) |
| Unauthenticated sessions | **simplified** | Steps calling pii_* and cross_validate_session_identity removed. verify → initiate → ask DOB and mobile → validate kept word for word |
| Query Handling | **one fix** | Credit card "dispute (provide dispute_team_ref…)" contradicted `<card_disputes>` and the field doesn't exist → "follow `<card_disputes>`". "(Bedrock Knowledge Base)" / "(MCP Gateway)" architecture words dropped |
| `<tool_usage_strategy>` | **rewritten to the real tools** | Listed 7 tools she doesn't have |
| `<voice_latency_bridging>` (fillers, tiers, small talk, silence) | **kept**, 4 small fixes | Tier 3 listed missing tools. Two examples made timing promises the same section bans ("It only takes a moment", "It'll just be a moment") |
| `<knowledge_base_retrieval>` index | **condensed** | 110 lines of rates, fees, limits and branch facts → a 12-line topic list. The rule is "Retrieve for these topics". Facts in the prompt invite answers from memory, and drift. "How to use Retrieve" is word for word, except meridianbank.co.uk → "our website" (see "Not changed" 4) |
| `<proactive_assistance>` | **word for word** | |
| Escalation protocol, tables, fields, mappings | **word for word**, last line fixed | "return intent: TransferToAgent" → call Escalate |
| Channel Transfer Protocol | **removed → "Requests You Can't Action Directly"** | request_channel_transfer isn't attached. See decisions |
| Security Guardrails | **word for word**, 4 fixes | "data tools only after cross_validate_session_identity returns match" would block every data tool if read literally → "after authentication". Block rule covers both card types. Tool failure → `technical_issue`. Repeating PII added |
| Secure Data Collection (DTMF) | **removed → in "Requests You Can't…"** | Returned a Lex intent (CollectCardDetails) the flow has no branch for. See decisions |
| ARIA Processing Status / payment status | **removed** | aria_status, payment_status: nothing sets them. There's no payment tool |
| In-Flight Task Continuity (filler turns) | **word for word** | |
| Callback Handling | **removed → in "Requests You Can't…"** | Returned RequestCallback, which the flow can't act on. See decisions |
| Tone & Voice | **rewritten, warmer** | Live banned "Of course!" and "Absolutely!" while every example used them, and said "not by name" while personalisation says greet by name. v2: warm acknowledgements without exclamation marks, empathy first, preferred name at moments that matter, one sincere apology. Its number and currency formatting paragraph is word for word |
| Out-of-Scope | **word for word**, one fix | `out_of_scope_redirect` → `out_of_scope` |
| Response examples | **word for word**, 3 fixes | "[handoff_ref]", "approximately [N] seconds" (values that don't exist, and a timing promise), "give me just a moment", TransferToAgent → Escalate |
| `<tool_instructions>`, `<instructions>`, `messages:` | **word for word** | Including the pre-filled `<message>` |

## Decisions to check (customer needs whose live path can't run)

These live instructions can't run today: no tool, no flow branch. ARIA would say she's doing something and nothing
would happen. v2 sends each one to what exists. Veto any you'd rather handle differently.

| # | Live instruction | What actually happens live | v2 |
|---|---|---|---|
| D1 | Callback: confirm topic and number, then return `RequestCallback` | The flow has no RequestCallback branch: nothing | "I'm not able to book a call back myself, but I can put you through to a colleague now, and they can arrange one." If yes, **Escalate** (customer_requested) with "Callback requested on [number]:" in the summary. The human handover flow queues for a colleague now; it has no scheduled-callback path, so v2 never promises a later call |
| D2 | Card digits by keypad: return `CollectCardDetails` | No branch: nothing | Never collect full card numbers, PIN or CVV. Identify cards by productContext endings. If full details are needed, offer a colleague (**Escalate**, complex_request) |
| D3 | Voice → chat by SMS link (`request_channel_transfer`) | Tool not attached: nothing | Acknowledge and keep answers short. If they'd rather speak to someone, offer a colleague (as D1) |
| D4 | Chat → voice callback (`request_channel_transfer`) | Tool not attached: nothing | Offer a callback (as D1) |
| D5 | Customer asks for a person: "return intent TransferToAgent" | Only Escalate transfers | Call **Escalate** (this is what works today) |
| D6 | aria_status = error → escalate; payment_status handling | Nothing sets these values | Removed |

## Latency changes (19 Oct, after a live call)

On the call of 19 Oct, the first Money Hub hand-off took 15.7 s from the customer's question to the answer: ARIA 9.5 s,
the bridge and AgentCore runtime about 2.5 s, the Money Hub agent 3.4 s. ARIA v2 changes only how fast she gets there:

| Change | Why | Business logic |
|---|---|---|
| The session context block (all 19 `{{$.Custom.*}}` values) moved from near the top to just before the tool instructions | Bedrock caches a prompt only up to the first thing that changes. With the values near the top, about 1,700 prompt tokens (plus the tools) were cached and about 15,000 re-read on every ARIA turn (`cacheReadInputTokens` 5,162 of about 17,000). Now about 97% of the prompt comes before them | same text, same values |
| "Keep <thinking> short" | Her reasoning restated her own rules for about 200 tokens before the hand-off; at Sonnet's speed that's about 3 s of silence | same decisions; steps that happen in <thinking> still do |
| The Money Hub hand-off message is one sentence | It listed the customer's ID, level and products; the bridge reads who they are from the contact | same hand-off |

## Not changed, but worth knowing

1. **Agent assist stays with its own flow and agent.** Every route to a person goes ARIA human handover → "ARIA
   agent assist", which sets `my-agent-assistant-agent:7` for the adviser. The live conversation bot flow is left as
   it is. The modular flow drops the conversation bot flow's agent-assistance setting (ARIA in that slot was
   overwritten on every route to a person), so it has one plain Connect assistant block for ARIA's session.
2. **Card blocks are now scoped to the customer** (done 18 Oct): `block_debit_card` and `block_credit_card` require
   `customer_id` and only block that customer's own card, in the Lambdas, the gateway schema, the live ARIA's tool
   settings (`tool_scopes.py`) and v2.
3. **Three knowledge tools overlap** (Retrieve, search_knowledge_base, get_feature_parity). The live prompt wants all
   three; consider one.
4. **The knowledge base is Meridian Bank's** (Meridian Points, meridianbank.co.uk, 0161 numbers) inside a Nationwide
   prompt. v2 only removed the website from its own fallback line; the KB content and phone numbers are unchanged
   business data.
5. **Other agents in the assistant:**
   - `my-agent-briefing-agent`: briefs the human agent after a hand-over; seen in traces.
   - `my-agent-assistant-agent`: the agent-assist agent (see 1).
   - `card-disputes-agent`: has its own tools, including QueryAssistant; no flow I read uses it.
   - `ARIA-Banking-Selfservice-Agent`: a legacy self-service type agent, unused.
   - `AVA-BranchInfo-Orchestration-agent`: a separate branch bot.

   Three MCP gateway applications are registered; ARIA's tools come from `aria-banking-mcp-gateway-prod`.
6. **19 custom variables is Connect's limit.** v2 uses the same 19 as live. Adding one means dropping another.
7. **Creating the agent hasn't been exercised.** `create_agent.sh --apply` is the first real test of the create-ai-prompt and create-ai-agent payloads. The configuration is v37's own shape, but run the dry run first and send me any error.
8. **Evidence is thin:** 44 traced sessions is demo traffic. "Remove QueryAssistant" rests on it having no
   instruction, no mention and no use, not on volume.

## How "same business logic" is checked

`../tests/test_agent_v2.py`:
- every word-for-word section is identical to the live prompt;
- 31 customer-facing rules from the live prompt are present exactly;
- no new contradictions ("bearing with"), no promise of a later call, chat number formatting kept;
- the file is valid YAML with the live structure (run with pyyaml installed);
- none of the phantom tools, intents or values remain, and no timing promises;
- every escalation reason is one of the Escalate tool's five values;
- the same 19 variables, inside Connect's limits, and the same tail;
- tools are v38 minus QueryAssistant, byte for byte, every card tool taking `customer_id`, with the same
  collaborator and guardrail;
- every tool the prompt names is attached, and every attached tool is named.
