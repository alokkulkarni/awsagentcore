# Updating ARIA's Prompt for Known Contact Reasons — Complete Novice Guide

This guide walks you through editing ARIA's orchestration prompt so that ARIA can open with
*"Are you calling about your mortgage application, or is it something else today?"* when the bank
already knows a likely reason for the contact.

You do not need to have edited a prompt before. Every edit tells you what to search for, what is
there now, exactly what to paste, and why.

| | |
|---|---|
| Prompt you will edit | `ARIA-Banking-Ochestration-Prompt` (currently version 13, 774 lines) |
| AI agent that uses it | `my-conversation-agent` (currently version 21) |
| Flow that uses the agent | `conversation bot flow` |
| Time needed | About 40 minutes |
| Status | **Nothing in this guide has been applied.** You make every change by hand |

> **About screen labels and line numbers.** The prompt text quoted here was read from your instance
> on 12 October 2026, so the *find this* lines are exact for version 13. Every edit in Part B was
> applied to a copy of that version on a laptop to confirm each *find this* line occurs exactly once
> and that the result keeps its structure. It has not been saved in Connect or tried on a call. Line numbers are a rough
> guide only: always locate a place by searching for the quoted text. The names of buttons in the
> Connect admin website were written from AWS documentation, not by clicking through your console,
> so a label may differ slightly.

---

## Table of Contents

- [1. Concepts You Must Understand First](#1-concepts-you-must-understand-first)
- [2. What ARIA Will Do Afterwards](#2-what-aria-will-do-afterwards)
- [3. Before You Start](#3-before-you-start)
- [Part A — Open the Prompt and Take a Backup](#part-a--open-the-prompt-and-take-a-backup)
- [Part B — The Seven Edits](#part-b--the-seven-edits)
- [Part C — Fix the Leftover Bank Name](#part-c--fix-the-leftover-bank-name)
- [Part D — Save and Publish the Prompt](#part-d--save-and-publish-the-prompt)
- [Part E — Publish a New AI Agent Version](#part-e--publish-a-new-ai-agent-version)
- [Part F — Point the Flow at the New Version](#part-f--point-the-flow-at-the-new-version)
- [Part G — Test It](#part-g--test-it)
- [Level 4 — The Payment Step-Up](#level-4--the-payment-step-up)
- [How to Undo Everything](#how-to-undo-everything)
- [Common Mistakes](#common-mistakes)
- [Things Noticed in the Current Prompt](#things-noticed-in-the-current-prompt)

---

## 1. Concepts You Must Understand First

### What is the orchestration prompt?

It is a long piece of text that tells ARIA who it is, what it may do, and how to behave. ARIA reads
all of it at the start of every conversation. Changing ARIA's behaviour means changing this text.

### What is a variable?

Some parts of the prompt are not fixed text. They are placeholders that get filled in for each
contact. A placeholder looks like this:

```
{{$.Custom.preferredName}}
```

Just before ARIA reads the prompt, Amazon Connect replaces that placeholder with a real value, such
as `James`. The values come from the **session injector** Lambda.

> **The single most important idea in this guide:** ARIA can only see a value if the prompt contains
> its placeholder. The injector now sends new values about contact reasons. Until you add their
> placeholders to the prompt, ARIA never sees them, and nothing changes.

### The four new values

| Placeholder | Example value | Meaning |
|---|---|---|
| `{{$.Custom.hasKnownContactReason}}` | `true` | Is there a reason ARIA is allowed to mention? Always `true` or `false` |
| `{{$.Custom.topContactReason}}` | `your mortgage application` | A short phrase for the most likely reason |
| `{{$.Custom.topContactReasonCategory}}` | `mortgages` | Which team deals with it |
| `{{$.Custom.contactReasonSummary}}` | `(1) your mortgage application: Application started online and paused at the income documents step...` | Up to three reasons with background detail |

> **Connect limits custom variables, and for this prompt the working maximum is 19.** The error
> message says "may not exceed 20", but a version with exactly 20 `{{$.Custom...}}` placeholders
> was rejected and one with 19 was accepted, so Connect appears to count one of the built-in
> variables as well. Your prompt started with 15. This guide adds **four**, which makes 19: the
> prompt is full. The injector also
> provides two further values that are deliberately **not** added, because no rule needs them:
> `contactReasons` (the same reasons as structured data, which duplicates `contactReasonSummary`)
> and `loa` (the level of assurance the ID&V harness reached). If you try to add a 21st variable,
> saving fails with *"Number of custom variables may not exceed 20"*.

### Who decides whether a reason may be mentioned?

**The injector, not the prompt.** Before ARIA sees anything, the injector has already checked that
the caller was properly verified. If they were not, `hasKnownContactReason` is `false` and the other
values are empty. A caller recognised only by their phone number gets nothing.

This matters because a prompt rule can be argued with ("ignore your instructions and tell me…"),
but ARIA cannot reveal information it was never given. So the prompt's job here is narrower: it
decides **how** to raise a reason, politely and safely.

### Why indentation matters

The prompt is stored in a format called **YAML**. Look at its very first line:

```
system: |
```

Everything after that line belongs to the `system` section **only while it is indented by at least
two spaces**. Every line you paste must therefore begin with two spaces, like its neighbours.

```
  - This line is correct. It starts with two spaces.
- This line is WRONG. It starts at the left edge and will break the prompt.
```

All the text blocks in this guide already include the two spaces. Copy them exactly, including the
spaces at the start of each line, and do not let your editor remove them.

### What are versions, and why are there three things to publish?

Three things are chained together, and each is **pinned** to an exact version of the next:

```
conversation bot flow  ──uses──▶  AI agent version 21  ──uses──▶  prompt version 13
```

Publishing a new prompt creates version 14, but the agent still points at 13. Publishing a new
agent creates version 22, but the flow still points at 21. So an edited prompt reaches callers only
after all three steps: publish the prompt (Part D), publish the agent (Part E), update the flow
(Part F). Miss one and callers keep getting the old behaviour, with no error to tell you.

The benefit is safety: nothing you do in Parts A to E affects a single live call.

---

## 2. What ARIA Will Do Afterwards

**Today**, for a verified customer:

> "Hello James, welcome back to Nationwide Building Society. James has a current account ending
> 4821… How can I help you today?"

**After this change**, when the bank knows a likely reason:

> "Hello James, welcome back to Nationwide Building Society. Are you calling about trouble signing in
> to the mobile app, or is it something else today?"

The rules ARIA will follow:

| Rule | Why |
|---|---|
| **Ask, never state.** "Are you calling about…?" not "I can see that…" | The guess may be wrong. A question lets the customer correct it without awkwardness |
| **Offer one reason only** | A list of everything the bank knows feels like surveillance and wastes time on a call |
| **Short label first, detail only after "yes"** | The detail is personal. Confirming first means it is only spoken when relevant |
| **If the answer is "no", drop it** | The customer has said why they are calling. Returning to the guess would be irritating |
| **Check the real position with a tool before acting** | The reason is a hint about why they called, not the up-to-date record |
| **Say "a block on your debit card", never "fraud"** | Avoids alarming the customer or implying they did something wrong |
| **Stay silent in sensitive cases** | For example, do not raise a failed payment with a customer flagged for financial difficulty |

---

## 3. Before You Start

| Needed | Why | How to check |
|---|---|---|
| The updated session injector is deployed | It provides the new values. Without it every placeholder is empty | Harness [README Part F](README.md#part-f--recommended-redeploy-the-session-injector) |
| Permission to edit AI prompts, AI agents and flows | You will change all three | You can open **AI agent designer** and **Flows** in the Connect admin website |
| A plain text editor | For the backup, and for preparing text to paste | TextEdit in plain-text mode, Notepad, or VS Code |
| A quiet moment for Part F | It is the only step that changes live calls | |

You can do Parts A to E at any time. They do not affect callers.

---

## Part A — Open the Prompt and Take a Backup

### Step A.1 — Open the prompt

1. Open your **Connect admin website**.
2. In the left menu choose **AI agent designer** → **AI prompts**.
3. Click `ARIA-Banking-Ochestration-Prompt`.
4. Check the version shown is **13**. If it is higher, someone has edited the prompt since this
   guide was written. The *find this* text should still be there, but check each edit carefully.

### Step A.2 — Take a backup

1. Click inside the prompt text.
2. Select everything (**Cmd+A** on Mac, **Ctrl+A** on Windows) and copy it.
3. Paste it into a new plain-text file and save it as `aria-prompt-v13-backup.txt`.

Version 13 stays in Connect even after you publish a new one, so this file is a second safety net.
It is also useful for comparing before and after.

### Step A.3 — Start editing

Click **Edit** (or **Create new version**, depending on your console).

> **Tip: edit in your text editor instead.** The prompt is 774 lines. It is easier to make the
> edits in the backup file's copy, using your editor's search, then paste the whole result back into
> Connect at the end. If you do this, make sure the editor is in **plain text** mode. A word
> processor will change straight quotes into curly quotes and may remove leading spaces, both of
> which break the prompt.

---

## Part B — The Seven Edits

Do them in order. Each has the same layout:

- **Find this** — text to search for (use **Cmd+F** or **Ctrl+F**). It is exact.
- **What is there now** — so you know you are in the right place.
- **What to do** — add after, add before, or replace.
- **Paste this** — the new text, already indented.
- **Why** — what the edit achieves.

Edits 1 to 3 are essential. Edits 4 to 7 stop older instructions in the prompt from contradicting
the new ones.

---

### Edit 1 — Tell ARIA the new values exist

**Find this:**

```
Voice channel: customerPhone (inbound caller ID)
```

**What is there now:** a short list, under the heading `## Session Context (injected as custom
variables)`, describing each group of values the injector provides. This is its last line.

**What to do:** add one new line directly **after** that line.

**Paste this:**

```
  Known contact reasons (only for a caller verified by an upstream ID&V flow, empty otherwise): hasKnownContactReason, topContactReason, topContactReasonCategory, contactReasonSummary
```

**Afterwards it should look like this:**

```
  Voice channel: customerPhone (inbound caller ID)
  Known contact reasons (only for a caller verified by an upstream ID&V flow, empty otherwise): hasKnownContactReason, topContactReason, topContactReasonCategory, contactReasonSummary

  <customer_context>
```

**Why:** this section is ARIA's table of contents for its session data. Listing the new values here
tells ARIA they are legitimate and when to expect them to be empty.

---

### Edit 2 — Add the placeholders (the essential one)

**Find this:**

```
- Customer Phone (voice inbound caller ID): {{$.Custom.customerPhone}}
```

**What is there now:** the last line of a list inside `<customer_context>`. Each line of that list
has a label, a colon, and a `{{$.Custom...}}` placeholder. The very next line is
`</customer_context>`.

**What to do:** add four new lines **after** the Customer Phone line and **before**
`</customer_context>`.

**Paste this:**

```
  - Has Known Contact Reason: {{$.Custom.hasKnownContactReason}}
  - Most Likely Contact Reason: {{$.Custom.topContactReason}}
  - Most Likely Reason Category: {{$.Custom.topContactReasonCategory}}
  - Known Contact Reasons (CONTEXT ONLY — never read out verbatim): {{$.Custom.contactReasonSummary}}
```

**Afterwards it should look like this:**

```
  - Prior Transcript: {{$.Custom.priorTranscript}}
  - Customer Phone (voice inbound caller ID): {{$.Custom.customerPhone}}
  - Has Known Contact Reason: {{$.Custom.hasKnownContactReason}}
  - Most Likely Contact Reason: {{$.Custom.topContactReason}}
  - Most Likely Reason Category: {{$.Custom.topContactReasonCategory}}
  - Known Contact Reasons (CONTEXT ONLY — never read out verbatim): {{$.Custom.contactReasonSummary}}
  </customer_context>
```

**Why:** this is where the values actually enter the prompt. For James, ARIA will read
`- Most Likely Contact Reason: trouble signing in to the mobile app`. For a caller who was not
verified, it will read `- Most Likely Contact Reason:` with nothing after it.

> **Check the spelling of each placeholder, letter by letter.** Capital letters matter.
> `{{$.Custom.topContactReason}}` works. `{{$.Custom.TopContactReason}}` or
> `{{$.Custom.topcontactreason}}` is silently empty, with no error. Two opening braces, two closing
> braces, and `$.Custom.` before the name.

---

### Edit 3 — Tell ARIA how to behave

**Find this:**

```
</personalization_guidelines>
```

**What is there now:** the closing line of a block of personalisation rules. After it comes a blank
line, then a line that reads `Channel rules:`.

**What to do:** add a whole new block **after** `</personalization_guidelines>` and **before**
`Channel rules:`. Leave one blank line above your block and one below it.

**Paste this:**

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
  8. When a known reason is offered, do not also recite the product summary. Keep the opening short.

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

**Afterwards it should look like this** (shortened):

```
  </personalization_guidelines>

  <known_contact_reasons>
  The bank sometimes already knows why a customer is likely to be getting in touch, ...
  ...
  </known_contact_reasons>

  Channel rules:
```

**Why, section by section:**

| Section of the block | What it is for |
|---|---|
| The opening paragraph | Switches the whole block off when there is nothing to mention, so ordinary calls are unaffected |
| *How to raise it* | The behaviour described in section 2 of this guide |
| *When NOT to raise it* | Four situations where an existing rule in your prompt should win. Without these, ARIA would have two conflicting instructions |
| *Tone* | Two cases that need care: a bereaved customer, and a card blocked for suspected fraud |
| The final paragraph | Stops ARIA making up a reason, and stops it saying the bank "predicted" something |

> **The text in square brackets stays as it is.** `[topContactReason]` is not a placeholder that
> Connect fills in. It is shorthand that ARIA understands as "put the Most Likely Contact Reason
> here". Your prompt already uses the same style, for example `[preferredName]`.

---

### Edit 4 — Update the two greeting templates

Your prompt has fixed greeting wording that ends "How can I help you today?". Left alone, it would
contradict Edit 3.

#### Edit 4a — Voice greeting

**Find this:**

```
- Authenticated: "Hello [preferredName], welcome back to Nationwide Building Society. [productSummary] How can I help you today?"
```

**What is there now:** a line under `VOICE greeting (channel is voice or ivr):`.

**What to do:** leave that line alone. Add one new line directly **after** it.

**Paste this:**

```
  - Authenticated with a known contact reason: "Hello [preferredName], welcome back to Nationwide Building Society. Are you calling about [topContactReason], or is it something else today?"
```

#### Edit 4b — Chat greeting

**Find this:**

```
- Authenticated: "Hi [preferredName], welcome to Nationwide Building Society chat. I'm ARIA, your virtual banking assistant. [productSummary] What can I help you with today?"
```

**What is there now:** a line under `CHAT greeting (channel is chat, mobile, web, or branch-kiosk):`.

**What to do:** leave that line alone. Add one new line directly **after** it.

**Paste this:**

```
  - Authenticated with a known contact reason: "Hi [preferredName], welcome to Nationwide Building Society chat. I'm ARIA. Is this about [topContactReason], or something else?"
```

**Why:** ARIA follows these templates closely. Giving it a third template for the new situation is
clearer than hoping it will adapt the existing one.

---

### Edit 5 — Update the authentication steps

**Find this:**

```
4. Close with: "How can I help you today?"
```

**What is there now:** step 4 of a numbered list under `Pre-authenticated sessions`, in the section
`## Authentication Gate`.

**What to do:** **replace** that one line.

**Paste this:**

```
  4. Close with: "How can I help you today?" — unless Has Known Contact Reason is "true", in which case close with the question from <known_contact_reasons> and skip step 3.
```

**Afterwards it should look like this:**

```
  3. Acknowledge products in one conversational sentence using the product summary (productSummary).
  4. Close with: "How can I help you today?" — unless Has Known Contact Reason is "true", in which case close with the question from <known_contact_reasons> and skip step 3.
  5. Check vulnerability context (vulnerabilityContext) in <thinking> immediately after fetching profile — apply all applicable rules silently.
```

**Why:** this numbered list is a second place that dictates the greeting. Step 3 says to describe
the customer's products; "skip step 3" keeps the opening short when a reason is being offered.

---

### Edit 6 — Update proactive assistance

**Find this:**

```
- For authenticated customers: always call get_account_balance or the relevant product tool in <thinking> before their first turn completes, so you have their data ready.
```

**What is there now:** the last bullet inside `<proactive_assistance>`. The next line is
`</proactive_assistance>`.

**What to do:** add one new line **after** that bullet and **before** `</proactive_assistance>`.

**Paste this:**

```
  - If Has Known Contact Reason is "true": follow <known_contact_reasons>. This takes the place of the priorSummary reference at session start; do not do both in the same message.
```

**Why:** an earlier bullet in this block tells ARIA to open with "I can see you were in touch with us
recently about…" when a previous conversation is on record. A customer with both a previous
conversation and a known reason would otherwise get two "I can see…" statements in one greeting.
This line says which one wins.

---

### Edit 7 — Add guardrails, examples and a closing instruction

#### Edit 7a — Security guardrails

**Find this:**

```
- If tool fails: do not retry more than once; on second failure escalate with escalation_reason: tool_failure.
```

**What is there now:** the last bullet under `## Security Guardrails`.

**What to do:** add three new lines directly **after** it.

**Paste this:**

```
  - Never mention a known contact reason unless Has Known Contact Reason is "true" in customer_context.
  - Never give the detail of a known contact reason before the customer confirms it is why they are getting in touch.
  - Never discuss a known contact reason with anyone who says they are contacting us on the customer's behalf.
```

**Why:** the Security Guardrails section is where ARIA looks for its hard limits. Repeating the
three most important rules there gives them the same weight as "never reveal raw PII".

#### Edit 7b — Worked examples

**Find this:**

```
Opening — cross-channel transfer (chat → voice, priorTranscript set):
```

**What is there now:** the title of the third example inside `<response_examples>`.

**What to do:** add the block below directly **before** that title, leaving a blank line between
your block and the title.

**Paste this:**

```
  Opening — authenticated voice customer with a known contact reason:
  <message>
  Hello [preferredName], welcome back to Nationwide Building Society. Are you calling about [topContactReason], or is it something else today?
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
  Hi [preferredName], welcome to Nationwide Building Society chat. I'm ARIA. Is this about [topContactReason], or something else?
  </message>

```

**Why:** language models copy examples more reliably than they follow rules. These show the exact
shape of the new opening, and of the two follow-ups ("yes" and "no"), in the `<message>` and
`<thinking>` format your prompt already uses.

#### Edit 7c — The final instruction

**Find this:**

```
Keep your initial message as a brief, personalised acknowledgement of their request, but avoid making capability claims before reviewing your available tools.
```

**What is there now:** a sentence in the middle of the paragraph inside `<instructions>`, almost at
the very end of the prompt.

**What to do:** add one sentence directly **after** that sentence, on the same line. Type a space
first.

**Paste this:**

```
If Has Known Contact Reason is "true" and this is your first message, follow <known_contact_reasons> for the opening.
```

**Why:** the `<instructions>` paragraph is the last thing ARIA reads before it speaks, so it carries
a lot of weight. A short pointer here makes sure the new behaviour is applied to the opening message.

---

### Optional edit — Send escalations to the right team

Only do this if you want a confirmed reason to influence routing when ARIA hands over to a person.

**Find this:**

```
topicCategory — pick the single closest match to the primary subject of the conversation:
```

**What is there now:** the start of a list of category names under `## Escalate Tool — Required
Fields`.

**What to do:** add one line directly **before** it.

**Paste this:**

```
  If the customer confirmed a known contact reason, use Most Likely Reason Category as topicCategory when it is one of the values listed below, and include the reason label in conversationSummary.
```

> **Check the category names match first.** The injector's test reasons use `mortgages` and
> `bereavement`, as in your routing table. The list in this prompt says `mortgage` (no "s") and has
> no `bereavement` entry. Decide which spelling is right and make the prompt, the routing table and
> the injector agree. Until they do, the words "when it is one of the values listed below" keep this
> edit safe: ARIA falls back to choosing a category itself.

---

## Part C — Fix the Leftover Bank Name

The bank is Nationwide Building Society, and most of the prompt says so. Eight places in version 13
still say "Meridian". Fix them now, while you are editing.

Search for `Meridian` and work through the results.

| # | Where | Now | Change to |
|---|---|---|---|
| 1 | Voice farewell, in `## PII Handling` | `Thank you for calling Meridian Bank.` | `Thank you for calling Nationwide Building Society.` |
| 2 | Chat farewell, same section | `Thanks for chatting with Meridian Bank today.` | `Thanks for chatting with Nationwide Building Society today.` |
| 3 | Statements guidance, in `## Query Handling` | `via the Meridian Bank mobile app` | `via the Nationwide Building Society mobile app` |
| 4 | Start of `<knowledge_base_retrieval>` | `the Meridian Bank internal Knowledge Base` | `the Nationwide Building Society internal Knowledge Base` |
| 5 | Credit card product line, same block | `Meridian Points (1pt/£1, 1,000pts=£10)` | **Check first.** This is a product name. Use the real name of the rewards scheme |
| 6 | Fraud protection line, same block | `How Meridian Bank protects customers` | `How Nationwide Building Society protects customers` |
| 7 | Callback closing line, in `## Callback Handling` | `Thank you for calling Meridian Bank. Goodbye!` | `Thank you for calling Nationwide Building Society. Goodbye!` |
| 8 | First example in `<response_examples>` | `welcome back to Meridian Bank.` | `welcome back to Nationwide Building Society.` |

When you finish, search for `Meridian` again. There should be no results, or only item 5 if you are
still confirming the product name.

> Items 4 to 6 describe what is in the knowledge base. If the knowledge base documents themselves
> still say "Meridian", ARIA may repeat the name when quoting them. That is a separate clean-up in
> the knowledge base, not in this prompt.

---

## Part D — Save and Publish the Prompt

### Step D.1 — Check your work before saving

Use search to confirm each of these. It takes two minutes and catches almost every mistake.

| Search for | Expected number of results |
|---|---|
| `hasKnownContactReason` | 2 (Edit 1, Edit 2) |
| `{{$.Custom.topContactReason}}` | 1 |
| `{{$.Custom.contactReasonSummary}}` | 1 |
| `<known_contact_reasons>` | 4 (the block's opening line in Edit 3, then one mention each in Edits 5, 6 and 7c) |
| `</known_contact_reasons>` | 1 |
| `Authenticated with a known contact reason` | 2 (Edits 4a and 4b) |
| `[topContactReason]` | 6 (two in Edit 3, one each in Edits 4a and 4b, two in Edit 7b) |
| `{{$.Custom.` | **19**, with or without the level 4 change. Connect refuses to save this prompt with 20 or more |
| `Meridian` | 0, or 1 if you are still confirming the rewards scheme name (Part C, item 5) |

Then check these by eye:

- **Every line you pasted starts with at least two spaces.**
- The first line of the prompt is still exactly `system: |`.
- Near the end, the line `messages:` still starts at the left edge with **no** spaces. It must not
  have been indented by accident.
- All quotation marks are straight (`"`), not curly (`“ ”`).

### Step D.2 — Save and publish

1. If you edited in a text editor, select all the text in the Connect prompt box and paste your
   edited version over it.
2. Click **Save**.
3. If Connect reports an error, it is nearly always indentation. See [Common Mistakes](#common-mistakes).
4. Click **Publish**.
5. Note the new version number. It should be **14**.

Callers are not affected yet. The agent still uses version 13.

---

## Part E — Publish a New AI Agent Version

1. Left menu → **AI agent designer** → **AI agents**.
2. Click `my-conversation-agent`.
3. Click **Edit** (or **Create new version**).
4. Find the **prompt** setting. It shows `ARIA-Banking-Ochestration-Prompt` with a version selector.
5. Change the version from 13 to **14**.
6. Change nothing else. Leave the guardrail, the tools and the locale as they are.
7. Click **Save**, then **Publish**.
8. Note the new agent version. It should be **22**.

Callers are still not affected. The flow still uses agent version 21.

---

## Part F — Point the Flow at the New Version

**This is the step that changes live calls.** Choose a quiet moment.

1. Left menu → **Routing** → **Flows** → open `conversation bot flow`.
2. The flow names the agent version in **two** places. Both currently end in `:21`.

### Place 1 — The Connect assistant block

There are two **Connect assistant** blocks in this flow. You want the **first** one: the one the
contact reaches *before* the session injector Lambda block.

1. Click its title to open the settings.
2. It has an **AI agent** (orchestration) selected, with a version.
3. Change the version to **22**.
4. Click **Save** on the block.

The second Connect assistant block, after the injector, has no agent version set. Leave it alone.

### Place 2 — The Lex block

1. Find the **Get customer input** block that connects the customer to the Lex bot. It comes after
   the second Connect assistant block.
2. Click its title. Scroll to **Session attributes**.
3. Find the attribute named `x-amz-lex:q-in-connect:ai-agent-arn`.
4. Its value is a long identifier ending `:21`. Change **only** the final number, so it ends `:22`.
   Do not change any other character.
5. Click **Save** on the block.

### Publish

1. Click **Save** for the flow, then **Publish**.
2. New contacts use the new prompt straight away. Contacts already in progress finish on the old one.

> **Both places must show the same version.** If one says 22 and the other 21, part of each contact
> uses the old prompt and part uses the new one, and the behaviour will be confusing to diagnose.

---

## Part G — Test It

Call the **ID&V test harness number**, not the main number. Press `#` after each entry.

| # | Test | Keys | What ARIA should say |
|---|---|---|---|
| 1 | James, quick select | `1`, `1` | "…Are you calling about trouble signing in to the mobile app, or is it something else today?" |
| 2 | Answer **yes** on test 1 | say "yes" | Confirms, then looks into it. Detail appears only now |
| 3 | Repeat test 1, answer **no, I want my balance** | say it | "No problem…" then helps with the balance. Does **not** mention the mortgage application |
| 4 | Daniel, quick select (level 3) | `1`, `4` | Asks about "a block on your debit card". Does not say "fraud" |
| 5 | Daniel at level 2 only: calling from James's phone | `2`, `1`, `1`, `2`, `30051994`, `7734`, *code* | Asks about "card payments that were declined". Does **not** mention a blocked card: that needs level 3 |
| 6 | Sarah, quick select | `1`, `2` | **Ordinary greeting.** Her reasons are failed payments and she is flagged for financial difficulty, so ARIA stays silent |
| 7 | Margaret, quick select | `1`, `3` | A gentle, optional form of the question |
| 8 | Ethel, quick select | `1`, `5` | Asks about "your card PIN being locked" |
| 9 | Nobody verified: withheld number, wrong details twice | `2`, `7`, `1`, `01011900`, `0000`, `01011900`, `0000` | Ordinary unauthenticated greeting. No reason |
| 10 | Call the **main** number directly | | Ordinary greeting. No reason, even though your number is recognised |

Tests 9 and 10 matter as much as the others. They prove a reason is **not** shared with someone who
was not properly verified.

**If a test does not behave as expected**, open the contact in **Analytics and optimization →
Contact search** and look at its attributes:

| You see | Meaning |
|---|---|
| `hasKnownContactReason = true`, but ARIA greeted normally | The injector did its part. The prompt is the problem: recheck Edits 2 and 3, and that Part F shows version 22 in both places |
| `hasKnownContactReason = false` | The injector held the reasons back. Check `LoA` on the same contact: it must be 2 or more |
| No `hasKnownContactReason` attribute at all | The main flow's *Set contact attributes* block does not copy it. That is fine: ARIA reads it from the session, not from attributes. Check the injector's CloudWatch log for `knownContactReason=` instead |

The test reasons for every customer are in `_STUB_CONTACT_REASONS` in
[scripts/lambdas/session_injector_qconnect.py](../scripts/lambdas/session_injector_qconnect.py).

---

## Level 4 — The Payment Step-Up

This is a second, later change to the prompt. It makes ARIA aware of the level of assurance the
ID&V flow reached, and adds a payment step-up that ARIA runs itself.

| Level | Reached by | Allows |
|---|---|---|
| 3 | The ID&V harness, on every contact | Everything ARIA can do **except** a payment |
| 4 | ARIA, in conversation, only when a payment is asked for | That one payment |

**The complete prompt with this change is
[prompts/aria-orchestration-prompt-v15.yaml](prompts/aria-orchestration-prompt-v15.yaml).** It is
your live version 14 plus the six edits below. Paste the whole file over the prompt in Connect; it
is easier and safer than making the edits one by one.

| # | Where | What changes |
|---|---|---|
| 1 | `## Agent Identity` | "You cannot make payments" becomes "a payment request is handled only through the Level 4 payment step-up" |
| 2 | `## Session Context` | One line describing `loa` |
| 3 | Inside `<customer_context>` | Adds `- Level of Assurance …: {{$.Custom.loa}}` and **removes** `- Prior Contact ID: {{$.Custom.priorContactId}}`. The prompt can hold only 19 custom variables, and `priorContactId` was bound but used by no rule. The count stays at 19 |
| 4 | Directly under `## Authentication Gate` | A new `<assurance_levels>` block: what each level allows, and the ten-step payment step-up |
| 5 | `## Security Guardrails` | Four bullets: level 4 only on `verified: true`; no payment below level 3; never claim a payment was made; never say level numbers |
| 6 | `<response_examples>` | Four examples covering the payment conversation |

### What ARIA does when asked to make a payment

1. Checks the customer is at level 3. If not, it offers the app or a colleague and asks no questions.
2. Asks who to pay and how much, and reads both back.
3. Asks once: "has anyone asked you to move this money, or told you what to say to us today?" A
   "yes" or a hesitant answer stops everything and goes to the fraud team.
4. Says it needs one more security check, then asks for the date of birth and the last four digits
   of the registered mobile, one at a time.
5. Calls the `validate_customer_auth` tool. **Only `verified: true` from the tool makes it level
   4.** Nothing the customer says can replace that.
6. Confirms the payee and amount once more.
7. Has no tool that moves money today, so it hands the verified request to a colleague with a
   summary beginning "Level 4 payment step-up passed." It does not say the payment was made.

Level 4 covers that single payment. A second payment needs the step-up again. Two wrong attempts
refuse the payment for the call, without saying which answer was wrong. On chat the step-up is not
offered: ARIA suggests the app or a call.

### Lambda change this depends on

`scripts/lambdas/mcp_tools/aria_auth_handler.py` (the function behind `validate_customer_auth`):

- It now reads the date of birth from `dob`, the name the tool schema actually sends. Before, it
  read `date_of_birth`, so a correct answer could never match.
- It accepts the date in any common form ("09/09/1982", "9 September 1982" once the model converts
  it, "1982-09-09", "09091982") instead of needing one exact string.
- It knows all five test customers, not two.

**Deploying it needs care. Read this before running anything.**

The live Lambda, `aria-banking-mcp-auth-prod`, was last deployed on 10 April 2026. On 24 May the
repository file gained a safety switch: it returns an error unless the Lambda has the environment
variable `MOCK_DATA=true`. The live Lambda does not have that variable (it only has `ARIA_DOMAIN`
and `ARIA_ENV`), because it predates the switch.

So if you deploy the new code and do nothing else, `validate_customer_auth` returns *"No data
source configured"* on every call, and ARIA can neither authenticate an unauthenticated caller nor
complete a payment step-up.

Do both of these, in this order:

1. Set the variable first. It is harmless to the code that is running now:

   ```bash
   aws lambda update-function-configuration --function-name aria-banking-mcp-auth-prod \
       --region eu-west-2 \
       --environment 'Variables={ARIA_DOMAIN=<current value>,ARIA_ENV=<current value>,MOCK_DATA=true}'
   ```

   Read the two current values from the Lambda console (**Configuration → Environment variables**)
   and keep them. This command replaces the whole set, so anything you leave out is removed.

2. Then deploy the code:

   ```bash
   ./scripts/deploy_mcp_gateway.sh update-lambdas --env prod --region eu-west-2
   ```

> **`update-lambdas` redeploys all ten tool Lambdas, not only the auth one.** Two other handler
> files have the same safety switch: `aria_account_handler.py` (balances, transactions) and
> `aria_customer_handler.py` (customer details). If their Lambdas also
> predate it, they will start returning the same error. Check each one's environment variables
> first, or deploy only the auth Lambda by hand: zip `aria_auth_handler.py` as `handler.py` and
> upload it to `aria-banking-mcp-auth-prod`.

**This Lambda also serves ARIA's existing check for unauthenticated callers**, so the fix changes
that path too: answers that could not match before can now match.

### Flow changes

**None are required.** ARIA does the step-up with tools inside the conversation, and the hand-over
to a colleague uses the existing *Escalate* branch of `conversation bot flow`.

As with any prompt change you must publish the prompt, publish a new agent version, and move the
flow's two agent references to it ([Parts D to F](#part-d--save-and-publish-the-prompt)).

### Things to know

- **`LoA` on the contact record stays 3.** ARIA cannot write contact attributes, so level 4 exists
  only in the conversation and in the escalation summary.
- **The prompt names tools ARIA does not have.** Version 14 refers to `pii_detect_and_redact`,
  `pii_vault_store`, `cross_validate_session_identity`, `escalate_to_human_agent` and
  `request_channel_transfer`. None is among the agent's 21 configured tools. This is not new and was
  not changed, but it means those instructions cannot be followed as written.
- **Size.** The prompt grows from about 71,000 to about 78,000 characters. If Connect refuses to
  save it, shorten the `<knowledge_base_retrieval>` block.

## How to Undo Everything

Because each layer is pinned to a version, undoing takes one step and loses nothing.

1. Open `conversation bot flow`.
2. Change both places from Part F back to `:21`.
3. **Save** and **Publish** the flow.

ARIA is now exactly as it was. Prompt version 14 and agent version 22 still exist and can be
switched on again later the same way.

---

## Common Mistakes

| Symptom | Cause | Fix |
|---|---|---|
| Connect will not save: *"Number of custom variables may not exceed 20"* | 20 or more `{{$.Custom...}}` placeholders. In practice the most this prompt accepts is 19 | Remove one that no rule uses. `priorContactId` was removed for this reason |
| Connect will not save the prompt | A pasted line starts at the left edge instead of two spaces in | Find the line (often the first or last of a pasted block) and add two spaces at its start |
| The prompt saves, but ARIA stops responding or behaves erratically | The line `messages:` near the end was indented, or a line before it lost its indentation | `messages:` must start at the left edge. Everything between `system: \|` and `messages:` must be indented |
| ARIA greets normally for every customer | A placeholder is misspelt, so the value is empty | Compare each of the four lines from Edit 2 with this guide, letter by letter |
| ARIA greets normally for every customer, and the placeholders are right | Part E or Part F was missed | Check the agent uses prompt 14, and the flow uses agent 22 in **both** places |
| ARIA says the literal words "top contact reason" | The square-bracket shorthand was changed, or Edit 2 is missing | Restore `[topContactReason]` in Edits 3, 4 and 7b, and check Edit 2 |
| ARIA lists two or three reasons | Rule 2 of Edit 3 was altered or lost | Re-paste the block from Edit 3 |
| ARIA gives the detail straight away | Rule 3 of Edit 3, or the guardrails in Edit 7a, are missing | Re-paste both |
| ARIA says "I can see you were in touch recently" **and** asks about a known reason | Edit 6 is missing | Add it |
| ARIA mentions the reason and also recites every product | Edit 5's "skip step 3" is missing | Re-do Edit 5 |
| Odd characters such as `â€œ` appear, or ARIA reads quotation marks strangely | Curly quotes from a word processor | Replace `“ ” ‘ ’` with straight `"` and `'` |
| Raises a reason on the main number without the harness | Should not be possible: the injector blocks it | Check the deployed injector is the updated one (harness README Part F) |

---

## Things Noticed in the Current Prompt

These are outside this change. They are listed so you are not surprised by them while editing.

1. **ARIA runs its own identity check.** For an unauthenticated session the prompt tells ARIA to ask
   for date of birth and the last four digits of the mobile number. A caller the ID&V harness left
   unverified will therefore be asked security questions again by ARIA. That is correct today, but
   it means two separate ID&V implementations exist. The injector already provides the level of
   assurance as `loa`; a later change could bind it in the prompt (one variable slot is spare) and
   make ARIA rely on it.
2. **Category names differ between places.** The escalation list in this prompt uses `mortgage`.
   Your routing table was recently changed to `mortgages`. One of them will not match at escalation
   time. This exists today and is independent of contact reasons.
3. **The prompt is long**: about 65,000 characters. These edits add roughly 6,300 more. If Connect
   refuses to save because of size, the `<knowledge_base_retrieval>` block (about 130 lines of
   product facts) is the natural candidate to shorten, since the knowledge base holds the same
   information.
