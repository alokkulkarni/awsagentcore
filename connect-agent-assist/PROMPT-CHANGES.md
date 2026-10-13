# Agent-Assist Prompt Changes

What was added to `agent-assistance-promnpt` to produce
[prompts/agent-assist-prompt-v3.yaml](prompts/agent-assist-prompt-v3.yaml), and why.

| | |
|---|---|
| Starting point | Version 2, read from the instance on 13 October 2026 (645 lines, about 97,000 characters) |
| Result | 691 lines, about 102,500 characters, 12 custom variables |
| Status | **Not applied.** Paste it in by following [README Part C](README.md#part-c--update-the-agent-assist-ai-agent) |

The existing prompt is a carefully built one. It has a strict response protocol (an opening
`<sitrep>` block, then one or two `<message>` blocks) and a proactive mode that allows exactly one
suggestion at a time. **None of that is changed.** There are two additions and no deletions.

## Addition 1 — The handover data

**Where:** inside `<runtime_context>`, just before `<conversation>`.

A new `<handover_context>` block with twelve lines, one per value the Lambda writes:

```
  <handover_context>
  Customer ID: {{$.Custom.customerId}}
  Preferred name: {{$.Custom.preferredName}}
  Products: {{$.Custom.productSummary}}
  Channel: {{$.Custom.channel}}
  Verification: {{$.Custom.verification}}
  Payment approved in app: {{$.Custom.paymentApproved}}
  Customer intent: {{$.Custom.ariaCustomerIntent}}
  Topic: {{$.Custom.ariaTopicCategory}}
  Why ARIA handed over: {{$.Custom.ariaEscalationReason}}
  ARIA's summary: {{$.Custom.ariaSummary}}
  Known reasons: {{$.Custom.knownContactReasons}}
  Vulnerability flags (staff only): {{$.Custom.vulnerabilityContext}}
  </handover_context>
```

**Why here:** the prompt already separates static instructions from live data, and says so at the
top of `<runtime_context>`. Live data belongs with the other live data.

**Why it matters:** a prompt can only see a value it names. Without these lines the Lambda's
briefing is written to the session and ignored.

## Addition 2 — How to use it

**Where:** a new `<bank_handover>` block, placed just before `<working_notes>`, with the other
static instructions.

| Paragraph | What it tells the assistant | Why |
|---|---|---|
| Opening | It is helping a colleague at Nationwide Building Society, and most contacts arrive after ARIA | Sets the context the generic prompt lacks |
| WHAT IT IS | The handover data is trusted background from the bank, but a starting point: confirm account facts with a look-up. Empty lines were not supplied. An empty block means the contact did not come through ARIA | The prompt treats the customer transcript as untrusted. This data is different, and the assistant needs to be told so. It also keeps behaviour unchanged for contacts with no briefing |
| THE FIRST PUSH OF A CONTACT | On the first proactive suggestion, spend the existing compact format on: the first action, what ARIA already did, the verification position, and an offer of the guidance and summary. Do it once | This is the "upfront" briefing. It reuses the prompt's own format instead of adding a new one, so the response protocol holds |
| VERIFICATION | Relay the verification instruction faithfully. If the customer is not verified, the next best action is to verify, whatever they ask for. Never treat something the customer says as verification | Stops the assistant waving an unverified caller through |
| AN APPROVED PAYMENT | When ARIA completed an app approval, the next action is to make that payment once the agent has read the payee and amount back to the customer, and the customer must not be asked to approve it again. It covers one payment only. Verification comes first: if the verification line says to verify identity, the agent verifies before making any payment, including an approved one | Carries the level 4 result from ARIA to the agent. An approval never replaces an identity check |
| KNOWN REASONS | Offer the top reason as something to check with the customer, not as a fact. Do not raise a sensitive one unless the customer is strongly verified. For a blocked card say "a block on your card", not "fraud" | Mirrors the rules ARIA follows, adapted for staff |
| VULNERABILITY | Tell the agent how to adapt, in plain words, and that it is not to be mentioned to the customer. Do not print the raw flags | Agents may see this; customers must not hear it |
| RELATED GUIDANCE | Look up the bank's guidance for the topic before suggesting, and offer it | The "related documents" part of the request |
| WHAT YOU CAN LOOK UP | The customer look-ups only read. Use the customer ID from the handover, never one the customer says. Never write that an action was done | The assistant has read-only tools. It advises; the agent acts |
| WRAP-UP | When asked, or when the contact is ending, produce notes covering who, how verified, what ARIA did, what the agent did, what is open | The "summary" part of the request |

## Things to know

- **The wording avoids words the prompt bans.** The existing prompt forbids "tool", "retrieve",
  "knowledge base" and similar inside anything the agent sees. The additions are instructions, not
  agent-facing text, but they are written in the same register ("look-up", "guidance") so the
  assistant does not copy a banned word into a message.
- **Custom variable limit.** ARIA's prompt was rejected at 20 custom variables. This prompt uses 12.
- **Size.** About 5,600 characters are added to a 97,000-character prompt.
- **Not tested on a live contact.** The structure was checked by script: the first line is
  `system: |`, every line before `messages:` is indented, and the prompt binds exactly the twelve
  values the Lambda writes. How the assistant behaves with it needs the tests in
  [README Part F](README.md#part-f--test-it).
