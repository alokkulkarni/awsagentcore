# Orchestrator Prompt Changes — Known Contact Reasons

What to add to ARIA's orchestration prompt so it uses the contact reasons the session injector now
provides, and exactly where each piece goes.

| | |
|---|---|
| Prompt | `ARIA-Banking-Ochestration-Prompt` (currently version 13, 774 lines) |
| AI agent | `my-conversation-agent` (currently version 21) |
| Status | **Nothing below has been applied.** These are manual edits in the Connect AI agent designer |

Section names and line numbers refer to version 13 as read from the instance on 12 Oct 2026. If the
prompt has changed since, find the section by its heading.

---

## Why the prompt must change

The injector can put the reasons into the session, but a prompt only sees a variable it names.
Until `{{$.Custom.contactReasonSummary}}` appears in the prompt text, the data is injected and
ignored. There are six edits. Edits 1 to 3 are required. Edits 4 to 6 make the behaviour safe and
consistent.

## What the injector provides

| Variable | Example | When it has a value |
|---|---|---|
| `hasKnownContactReason` | `true` | Always `true` or `false` |
| `topContactReason` | `a block on your debit card` | Only when `true` |
| `topContactReasonCategory` | `fraud_security` | Only when `true` |
| `contactReasonSummary` | `(1) a block on your debit card: Debit card ending 7734 was blocked yesterday after...; (2) card payments that were declined: ...` | Only when `true` |
| `contactReasons` | JSON list with `type`, `label`, `detail`, `occurredAt`, `topicCategory` | Only when `true` |
| `loa` | `3` | When an ID&V flow ran before the main flow |

The injector has already applied the disclosure rule before the prompt sees anything: reasons are
present only for a caller an ID&V flow verified at level 2 or above, and a fraud-related reason only
at level 3. A caller recognised by phone number alone gets `hasKnownContactReason = false`. The
prompt therefore does not decide *whether* a reason may be shared. It decides *how* to raise it.

---

## Edit 1 — Describe the new variables

**Where:** section `## Session Context (injected as custom variables)`, around line 77. After the
line that begins `Voice channel: customerPhone`.

**Add:**

```
  Known contact reasons (only for a caller verified by an upstream ID&V flow, empty otherwise): hasKnownContactReason, topContactReason, topContactReasonCategory, contactReasonSummary, contactReasons
  ID&V result (only when an upstream ID&V flow ran): loa
```

## Edit 2 — Bind the variables (required)

**Where:** inside `<customer_context>`, around line 85. After the line
`- Customer Phone (voice inbound caller ID): {{$.Custom.customerPhone}}` and before
`</customer_context>`.

**Add:**

```
  - Has Known Contact Reason: {{$.Custom.hasKnownContactReason}}
  - Most Likely Contact Reason: {{$.Custom.topContactReason}}
  - Most Likely Reason Category: {{$.Custom.topContactReasonCategory}}
  - Known Contact Reasons (CONTEXT ONLY — never read out verbatim): {{$.Custom.contactReasonSummary}}
  - Known Contact Reasons (structured JSON): {{$.Custom.contactReasons}}
  - Level of Assurance (0–3, empty if no ID&V flow ran): {{$.Custom.loa}}
```

This is the edit that makes the data visible. Without it, nothing else works.

## Edit 3 — Add the behaviour rules (required)

**Where:** a new block immediately after `</personalization_guidelines>`, around line 113, and
before the `Channel rules:` paragraph.

**Add:**

```
  <known_contact_reasons>
  The bank sometimes already knows why a customer is likely to be getting in touch, for example a
  stalled mortgage application, payments that failed, trouble with mobile banking, or a blocked card.
  When "Has Known Contact Reason" in customer_context is "true", use it to save the customer from
  explaining. When it is "false" or empty, this whole block does not apply: greet normally.

  How to raise it:
  1. ASK, never state. Offer the Most Likely Contact Reason as a question straight after the
     greeting, in place of "How can I help you today?":
     - VOICE: "Are you calling about [topContactReason], or is it something else today?"
     - CHAT:  "Is this about [topContactReason], or something else?"
  2. Offer ONE reason only: the most likely. Do not list the others.
  3. Use only the short label. Do NOT give any detail (dates, amounts, card digits, what was
     declined, why something was blocked) until the customer has said yes.
  4. If the customer says yes: confirm you can help, then use the detail from Known Contact Reasons
     as context. Before acting, call the relevant tool to get the current position. The injected
     reason is a hint about why they are calling, not the record of truth.
  5. If the customer says no or names something else: drop it completely and help with what they
     asked. Do not offer the second reason. Do not return to the first.
  6. If the customer raises one of the other known reasons themselves, use its detail as context in
     the same way.
  7. Raise a known reason once, at the start. Never repeat it later in the conversation.

  When NOT to raise it (greet normally instead):
  - Prior Transcript is present. The customer has just transferred from another channel: continue
    that conversation first.
  - vulnerabilityContext has refer_to_specialist. Follow the vulnerability protocol and transfer;
    pass the reason in the handoff instead of asking the customer.
  - vulnerabilityContext has suppress_collections, and the reason is about a payment that failed or
    a direct debit that was returned. Let the customer bring it up.
  - The customer opens by stating why they are getting in touch. Answer that.

  Tone:
  - vulnerabilityContext flag bereavement: ask gently and make it optional, for example "I can see
    you may have been trying to send us something. Would you like help with that, or is there
    something else I can do for you today?"
  - A blocked card: stay calm and factual. Say "a block on your debit card". Never say "fraud",
    never describe the transactions, and never suggest the customer did something wrong, before
    they confirm.

  Never invent a reason. Never mention that the bank "predicted" or "flagged" anything. Never
  reference a reason that is not in customer_context.
  </known_contact_reasons>
```

## Edit 4 — Update the greeting wording

The current greetings end with a fixed "How can I help you today?", which would contradict Edit 3.

**Where (a):** section `## Channel-Aware Greeting Protocol`, around line 120. There are two
`Authenticated:` lines, one for voice and one for chat.

**Add** one line after each `Authenticated:` line:

```
  - Authenticated with a known contact reason: replace the closing question with the question from <known_contact_reasons>.
```

**Where (b):** section `## Authentication Gate`, `Pre-authenticated sessions`, step 4, around line
140. It currently reads `4. Close with: "How can I help you today?"`.

**Replace with:**

```
  4. Close with: "How can I help you today?" — unless Has Known Contact Reason is "true", in which case close with the question from <known_contact_reasons>.
```

## Edit 5 — Add to proactive assistance

**Where:** inside `<proactive_assistance>`, around line 382, as a new bullet before
`</proactive_assistance>`.

**Add:**

```
  - If Has Known Contact Reason is "true": follow <known_contact_reasons>. This takes the place of the priorSummary reference at session start; do not do both in the same message.
```

That last clause matters. The prompt already tells ARIA to open with "I can see you were in touch
with us recently about…" when `priorSummary` is set. Without a precedence rule, a customer with both
would get two "I can see…" statements in one greeting.

## Edit 6 — Add security guardrails and examples

**Where (a):** section `## Security Guardrails`, around line 510, as new bullets.

**Add:**

```
  - Never mention a known contact reason unless Has Known Contact Reason is "true" in customer_context.
  - Never give the detail of a known contact reason before the customer confirms it is why they are getting in touch.
  - Never discuss a known contact reason with anyone who says they are contacting us on the customer's behalf.
```

**Where (b):** inside `<response_examples>`, around line 700, after the existing
`Opening — authenticated voice customer (priorSummary set)` example.

**Add:**

```
  Opening — authenticated voice customer with a known contact reason:
  <message>
  Hello [preferredName], welcome back to Meridian Bank. Are you calling about [topContactReason], or is it something else today?
  </message>
  <thinking>
  Has Known Contact Reason is true. Offering the most likely reason as a question. Giving no detail until the customer confirms. Checking vulnerabilityContext silently.
  </thinking>

  Customer confirms the known reason:
  <message>
  Thanks for confirming. Let me take a look at that for you now.
  </message>
  <thinking>
  Customer confirmed. Using the detail from Known Contact Reasons as context. Calling the relevant tool to get the current position before saying anything specific.
  </thinking>

  Customer says it is something else:
  <message>
  No problem at all. What can I help you with?
  </message>
  <thinking>
  Customer declined the known reason. Dropping it. Not offering any other known reason.
  </thinking>

  Opening — authenticated chat customer with a known contact reason:
  <message>
  Hi [preferredName], welcome to Meridian Bank chat. I'm ARIA. Is this about [topContactReason], or something else?
  </message>
```

---

## Optional — Use the reason when escalating

**Where:** section `## Escalate Tool — Required Fields`, around line 420.

If the customer confirmed the known reason and the conversation is then escalated, ARIA can use
`topContactReasonCategory` as the `topicCategory`. It already matches the names in your proficiency
routing table (`mortgages`, `fraud_security`, `debit_card`, and so on), so the contact reaches the
right team. One line is enough:

```
  - If the customer confirmed a known contact reason, use Most Likely Reason Category as topicCategory and include the reason label in the conversation summary.
```

---

## How to apply it

1. Connect admin website → **AI agent designer** → **AI prompts** → open
   `ARIA-Banking-Ochestration-Prompt`.
2. Click **Edit**. Make edits 1 to 6. **Save**, then **Publish**. This creates version 14.
3. **AI agents** → open `my-conversation-agent` → **Edit**. Change its orchestration prompt to
   version 14. **Save**, then **Publish**. This creates agent version 22.
4. **Routing → Flows** → open `conversation bot flow`. The flow names the agent version in **two**
   places, both currently ending `:21`:
   - the first **Connect assistant** block (the one with an orchestration AI agent selected)
   - the **Get customer input** (Lex) block, session attribute
     `x-amz-lex:q-in-connect:ai-agent-arn`

   Change both to version 22. **Save** and **Publish** the flow.

> If you update only one of the two, the flow keeps using the old prompt for part of the contact.
> If you skip step 4 altogether, nothing changes at all: the flow is pinned to version 21.

To roll back, point both places back at `:21` and publish the flow. Versions 13 and 21 are not
deleted by publishing new ones.

## How to test it

Redeploy the injector first (harness README Part F), then call the harness number.

| Test | Keys | Expected opening from ARIA |
|---|---|---|
| Quick-select James | `1`, `1` | "…Are you calling about trouble signing in to the mobile app, or is it something else today?" |
| Quick-select Daniel (level 2) | `1`, `4` | Asks about "card payments that were declined". The card block is **not** mentioned: it needs level 3 |
| Daniel, verified in the app (level 3) | `2`, `4`, `1`, `6`, `1`, *code*, `2` | Asks about "a block on your debit card" |
| Sarah (has `suppress_collections`) | `1`, `2` | Normal greeting. Her reasons are about failed payments, so ARIA waits for her to raise them |
| Margaret (bereavement) | `1`, `3` | A gentle, optional version of the question |
| General information only, level 1 | `2`, `1`, `1`, `1`, `2` | Normal unauthenticated greeting. No reason |
| Call the **main** number directly | | Normal greeting. No reason, even though the phone number is recognised |

Then answer "no, something else" on one call and "yes" on another, and check ARIA drops the reason
in the first case and gives detail only after the "yes" in the second.

All test reasons are listed in `_STUB_CONTACT_REASONS` in
[scripts/lambdas/session_injector_qconnect.py](../scripts/lambdas/session_injector_qconnect.py).

## Two things noticed in the current prompt

These are outside this change, but you will see them while editing.

1. **Two bank names.** The identity section and the greetings say "Nationwide Building Society",
   while the farewells and some examples say "Meridian Bank". The examples above use "Meridian
   Bank". Use whichever you intend, consistently.
2. **ARIA runs its own identity check.** For an unauthenticated session the prompt asks for date of
   birth and the last four digits of the mobile number. A caller the harness left unverified will
   therefore be asked security questions again by ARIA. That is correct behaviour today, but it
   means there are two ID&V implementations. `loa` is now bound in the prompt (Edit 2) so a later
   change can make ARIA rely on the level instead.
