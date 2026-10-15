# CX designer configuration — "Card dispute" assistant

Everything to create in the agentic CX designer for the disputes assistant (SPEC Part 4). ARIA
checks the caller and hands the call over; this assistant then does the whole dispute: it finds the
payment, fills the dispute, blocks and replaces the card if needed, and texts the customer the form
if they want to see it. Then it hands the call back, and the Connect flow passes it to an adviser
through ARIA's own human hand-over.

Create the resources in section 1 first; a flow can only pick what already exists. The
click-by-click mechanics are the same as for your mortgage application
(`connect-livesync-mortgage/docs/GUIDE.md` Parts 3 to 5). This file gives the values.

Use the workspace you already have (`ariaworkspace`). Typing `{` in a text field opens the menu of
variables and Secrets; always insert them from that menu, never type the braces by hand.

## 1. Resources

### 1a. Context variables

| Name | Type | Allow frontend updates | Set by | Used for |
|------|------|------------------------|--------|----------|
| `entry` | String | On | Connect | `phone` |
| `contactId` | String | On | Connect (namespace **System**, **Contact id**) | every Data request |
| `firstName` | String | On | Connect | the customer's name |
| `verification` | String | On | Connect | `authenticated`, or not |
| `handoverSummary` | String | On | Connect | what the customer already told ARIA |
| `summary` | String | Off | the assistant | its note for the adviser |
| `escalationReason` | String | Off | the assistant | why the call goes to a person |

### 1b. Secret

Create a Secret named `card_dispute_api_key`. Its value is the key the deploy script made: in the
AWS console open **Secrets Manager**, the secret `aria-card-dispute/acxd-key`, **Retrieve secret
value**, and copy it across.

### 1c. Data requests

Create the seven Data requests below. Every one has the same settings:

| Setting | Value |
|---------|-------|
| Implementation | **External**, `POST` (never Static: Static returns canned data and never calls the service) |
| Endpoint URL (both environments) | the "CX designer tool address" the deploy script printed, ending `/acxd/ops` |
| Header | `Content-Type` = `application/json` |
| Header | `x-api-key` = the Secret `card_dispute_api_key` (insert with `{`) |

Keep every request field at the top level. Use each request and response sample exactly as given:
the CX designer builds the fields from them, and the service always answers with every field shown.

Every response has `ok`, `reason` and `message`. `ok` false is an answer, not a failure: `message`
says what went wrong and what to do, and the assistant should follow it.

No Data request takes a customer ID or a phone number. The service works out the customer, and the
number to text, from the call itself. There is no Data request that confirms or submits a dispute.

#### `listCardsAndPayments`

Description: "The customer's cards (with whether each is blocked) and their recent card payments. Call it first, before asking which payment."

| Request sample | `{"operation":"listCardsAndPayments","contactId":"0a1b2c3d-1111-2222-3333-444455556666"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","cards":[{"cardType":"debit","cardLastFour":"4821","status":"active"}],"payments":[{"transactionId":"TXN-4821-20261011-8999","date":"2026-10-11","merchant":"AMAZON.CO.UK","amount":"89.99","cardType":"debit","cardLastFour":"4821"}]}` |

#### `startDispute`

Description: "Starts the dispute for one payment, or returns the one already started for it. transactionId must come from listCardsAndPayments. disputeType is unauthorised (the customer did not make the payment or does not recognise it) or merchant (they made it, but something went wrong)."

| Request sample | `{"operation":"startDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","transactionId":"TXN-4821-20261011-8999","disputeType":"unauthorised"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","disputeId":"DSP-ABCD2345","status":"draft","payment":"AMAZON.CO.UK, £89.99 on 2026-10-11, debit card ending 4821","disputeType":"unauthorised","reasonCode":"","reasonsAllowed":"card_lost_or_stolen, card_details_used_without_card, not_recognised","cardInPossession":"","cardBlocked":"","contactedMerchant":"","narrative":"","missing":"Reason, Customer still has the card, In the customer's words","complete":false,"customerWatching":false,"linkSent":false}` |

#### `updateDispute`

Description: "Saves the customer's answers on the dispute. Send only the fields you have answers for. reasonCode must be one of reasonsAllowed. cardInPossession, cardBlocked and contactedMerchant are yes or no. narrative is what happened, in the customer's own words. The reply's missing field says what is still needed."

| Request sample | `{"operation":"updateDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345","disputeType":"unauthorised","reasonCode":"card_details_used_without_card","cardInPossession":"yes","cardBlocked":"yes","contactedMerchant":"no","narrative":"I have never ordered from Amazon."}` |
|---|---|
| Response sample | the same as `startDispute` |

#### `getDispute`

Description: "The dispute as it stands, including anything the customer typed on the form themselves. Leave disputeId empty for the customer's latest open dispute."

| Request sample | `{"operation":"getDispute","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345"}` |
|---|---|
| Response sample | the same as `startDispute` |

#### `blockCard`

Description: "Blocks the customer's debit or credit card straight away. cardType is debit or credit. Asking twice is safe: it gives the same reference. Only after the customer agrees."

| Request sample | `{"operation":"blockCard","contactId":"0a1b2c3d-1111-2222-3333-444455556666","cardType":"debit"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","cardType":"debit","cardLastFour":"4821","reference":"BLOCK-4821-ABC234"}` |

#### `orderReplacementCard`

Description: "Orders a replacement for a card that has been blocked. cardType is debit or credit. Only after the customer agrees."

| Request sample | `{"operation":"orderReplacementCard","contactId":"0a1b2c3d-1111-2222-3333-444455556666","cardType":"debit"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","cardType":"debit","cardLastFour":"4821","reference":"REPL-4821-ABC234","arrivesInWorkingDays":"3 to 5"}` |

#### `sendFormLink`

Description: "Texts the customer a link to this dispute's form, joined to this call, to the mobile they are calling from. Only when they want to see the form. sent=true means the text has gone; say only sentTo, never a full number."

| Request sample | `{"operation":"sendFormLink","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","sent":true,"sentTo":"the mobile ending 123"}` |

Test each Data request with **Test** before going on. `401` means the Secret or the header is
wrong. `ok:false` with `customer_not_identified` is correct for a made-up contact ID: it shows the
request reached the service.

## 2. Flow `HandBackToARIA`

Build this first; the main flow points to it. After **Start**, add two **Generative text** nodes
in a row. Connect Success, Failure and Timeout of each to the next, so an empty answer never
blocks the hand-off.

| # | Output variable | Prompt |
|---|-----------------|--------|
| 1 | `handoffNote` | "In one sentence for a bank adviser, say anything they should know that is not on the dispute form: how the customer is feeling, anything they asked for that was not done, anything else they want help with. Write 'Nothing further.' if there is nothing. No card numbers. Conversation: {System.transcript}" |
| 2 | `handoffReason` | "Why is this going to a person? Output exactly one of: dispute_ready_for_review, dispute_incomplete, customer_request, vulnerability, tool_failure, other. No markdown, no explanation. Conversation: {System.transcript}" |

Then an **Escalate** node:

- **Message**: "That's everything I need. A colleague will now check the form with you before it's
  submitted. You won't need to repeat anything."
- **State modifications**, one **Set** per row:

| Context variable | Value |
|------------------|-------|
| `summary` | `{handoffNote}` |
| `escalationReason` | `{handoffReason}` |

Only context variables set this way reach Connect. Leave the Escalate node's Continuation
unconnected. The team the call goes to, and the adviser's summary of the dispute, are not made
here: the Connect flow builds them from what was saved, so they are always right.

## 3. Flow `CardDispute` (the main flow)

### 3a. The opening

The assistant node replies to what the caller says; it does not speak first. Coming from ARIA, the
caller has just heard one sentence and is waiting, so the flow must speak first and end with a
question. Build this between **Start** and the assistant node:

```
Start → Generative text "openingQuestion" ── Success ──► Basic "{openingQuestion}" ──► CardDispute
                                          └─ Failure / Timeout ──► Basic (fixed question) ──► CardDispute
```

1. A **Generative text** node, output variable `openingQuestion`, prompt:
   "The customer wants to dispute a card payment. They already told our phone assistant: {handoverSummary}. Write one short, warm question, in plain UK English, that moves the dispute on without asking for anything they already said. If they named the payment, ask them to confirm it in a few words, naming it. If they said nobody else should be using the card or that it is being used now, ask if they would like it blocked straight away. Otherwise ask which payment it is: the shop and roughly how much is enough. Do not greet them, do not say who you are, and do not mention transferring. Output only the question."
2. A **Basic** node, message `{openingQuestion}`, from **Success**.
3. A **Basic** node from **Failure** and **Timeout**, message: "Which card payment would you like to
   dispute? The shop and roughly how much is enough."
4. Connect both Basic nodes to the assistant node `CardDispute`.

### 3b. The assistant node

Add a **Live Sync** node named `CardDispute`. Live Sync lets the assistant see the form when the
customer opens the texted link, including anything they type. It works without a page too: then it
is a voice conversation. Its **Prompt**:

```
You are the card dispute assistant for the bank, on a phone call. The customer was just speaking to
our phone assistant, ARIA, and has been passed to you without being told: to them it is the same
conversation. Never introduce yourself, never greet them again, and never ask for anything they
already said. You handle the whole dispute. A colleague then checks it with the customer and
submits it.

Call details (empty when not known):
first name: {firstName} | verified: {verification} | how they arrived: {entry}
already said to ARIA: {handoverSummary}

Before anything else
- If "verified" is not "authenticated", do nothing on their cards or disputes. Say a colleague will
  help, and use Escalation requested.
- Call listCardsAndPayments once, and use it to find the payment. Never read out a full card number;
  "your debit card ending 4821" is fine.

If someone else is using their card, or they have lost it
- Offer to block it straight away. With their yes, call blockCard. Then offer a replacement and,
  with their yes, call orderReplacementCard. Tell them the replacement arrives in
  arrivesInWorkingDays working days. Do this before the rest of the dispute.

The dispute
1. Find the payment from what they say: retailer, amount or date. If two match, ask one question to
   tell them apart. If none match, say you cannot see it and use Escalation requested.
2. Ask whether they made the payment, unless they have said. Then call startDispute with that
   payment's transactionId and disputeType: unauthorised if they did not make it or do not
   recognise it, merchant if they made it but something went wrong.
3. Fill in everything you already know without asking: what they told ARIA and you so far. Save it
   with updateDispute. Then ask only for what the reply's missing field lists, one question at a
   time, and save each answer as soon as you have it. For the reason, choose from reasonsAllowed
   using their words; do not read the codes out. Write narrative in their own words; do not
   improve it.
4. Never say you have saved something unless updateDispute replied ok=true.

Seeing the form
- Once the dispute is started, offer once: "Would you like me to text you the form so you can see it
  as we go?" With their yes, call sendFormLink and tell them which mobile it went to using sentTo.
  If ok is false, say you can't text it right now and carry on by voice.
- When they open it, they see your changes within a couple of seconds, and they can type in it too.
  Call getDispute to see what they typed. You do not need to fill in the page yourself: saving with
  updateDispute is enough.

Finishing
- When complete is true, read the dispute back in one or two sentences, including any card you
  blocked or replaced, and ask if it is right. Correct anything with updateDispute.
- Then use Escalation requested. A colleague checks it with them and submits it.

What you never do
- Never submit, confirm or accept a dispute, and never say it has been submitted or accepted.
- Never state or guess a refund, a timescale for the dispute or its outcome. Say: "My colleague will
  explain what happens next."
- Never block or replace a card without the customer's yes.
- Never read out a link, a reference you were not asked for, or a full card or phone number.
- Never say you are transferring or connecting them unless you use Escalation requested in the
  same turn. Asking for a person is always Escalation requested.
- If they ask about something other than this dispute, say your colleague can help with that too,
  and carry on; it goes in the hand-over.

Vulnerability
- If the customer is distressed, confused, or mentions bereavement, illness or money worries,
  acknowledge it kindly and use Escalation requested.

Tone
- Warm, plain English, UK spelling. Two short sentences per turn at most.
```

Re-insert every `{name}` in the prompt with the `{` menu so it becomes a real variable.

### 3c. Tools

Add the seven Data requests from 1c, each with its Description as the tool prompt. Map their inputs:

| Input | Source |
|-------|--------|
| `operation` | **Explicit text**: the Data request's own name, for example `blockCard` |
| `contactId` | **Variable**: pick the context variable `contactId` |
| every other input | **LLM prompt** (the assistant fills it from the conversation) |

Do **not** put a `{contactId}` chip inside an Explicit text value: the CX designer then sends the
chip's placeholder text instead of the call's ID, and every request answers
`customer_not_identified`. The mortgage build hit exactly this.

**Data capture: don't add it.** The dispute is saved by the Data requests; slots would stay empty
and required ones make the node fail.

### 3d. Live Sync actions

None. Paste `acxd/live-sync-actions.json` (an empty list). There is no action that confirms or
submits.

### 3e. Exit conditions

| Name | Description for the agent | Connect to |
|------|---------------------------|------------|
| Escalation requested | Use when the dispute is complete and read back, when the customer asks for a person, when the payment cannot be found, when the customer is not verified, or at any sign of vulnerability. Always use this exit for any transfer. | Redirect to `HandBackToARIA` |
| Unable to help | A Data request failed twice. | Redirect to `HandBackToARIA` |

Also connect **Timeout** and **Failure** to `HandBackToARIA`. There is no "Task complete" exit:
this assistant never finishes a dispute; an adviser does.

## 4. Voice, build, deploy

1. **Voice.** ARIA speaks with **Amy**, English (UK), on the generative engine (`conversation bot
   flow` → Set voice). Connect's Set voice block does not change this assistant's voice: the
   application's own voice setting does. In the application's settings, choose Amy, English (UK).
   If Amy is not offered, choose the closest British voice, and set `conversation bot flow`'s Set
   voice block to the same one, so the caller hears one voice throughout.
2. Create the application (name it `Card dispute`), add the `CardDispute` flow as its entry, build
   and deploy it to an environment, as in the mortgage guide Part 5.
3. Note, for later:
   - the application's ID and the environment's alias, for the Connect flow (README step 8);
   - its **deployment key** and **API key**, for the form page (README step 7).
