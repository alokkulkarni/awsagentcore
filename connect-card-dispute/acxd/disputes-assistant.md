# CX designer guide — the "Card dispute" assistant

This builds the assistant that takes a card dispute over from ARIA and does all of it: it finds the
payment, fills in the dispute, blocks and replaces the card if the customer wants, and shares the
form (texted on a phone call, posted in the chat on chat). Then it hands the customer back, and
Connect passes them to an adviser.

It works the same on a **phone call** and on **chat**. The only difference is how the form link
reaches the customer, and the assistant handles that itself.

You build it in **agentic CX designer**, the same tool you used for the mortgage application. Allow
about two hours the first time. Work top to bottom: a flow can only use things that already exist.

**Keep these open while you work:**
- This file. You'll copy text from it.
- The output of `deploy_card_dispute.sh` (README step 2). You need the **Data request address**,
  which ends in `/acxd/ops`.

**Two habits that avoid most problems:**
- When a value contains `{something}`, don't type the braces. Type `{` and pick the item from the
  menu that opens. Typed braces are sent as plain text.
- **Save** often. The canvas doesn't save on its own.

---

## Part 1 — Open the designer and your workspace

1. Open the AWS console and go to **Amazon Connect**.
2. Select your instance, then **agentic CX designer**.
3. Use the workspace dropdown at the top left to choose `ariaworkspace` (the one your mortgage
   assistant lives in).

---

## Part 2 — Create the resources

Everything the flows use is a **resource**: context variables, a Secret and Data requests.

### 2a. Context variables (7 used, only 1 to create)

Context variables carry values between Connect and the assistant. They belong to the whole
workspace, so the mortgage assistant's are shared with this one. Six of the seven this assistant
uses already exist from the mortgage build
([connect-livesync-mortgage](https://github.com/alokkulkarni/connect-livesync-mortgage), GUIDE
Part 3a). Don't create those again; only check them.

1. Go to **Resources** → **Context variables**.
2. **Check** the six marked "Yes" are in the list, with **Allow frontend updates** as shown. If one
   is missing (for example, in a different workspace), create it the same way as step 3.
3. **Create** `channel`: **Add context variable** → Name `channel` → Type **String** → **Allow
   frontend updates** On → **Save**.

| Name | Type | Allow frontend updates | Already there? | What it holds here |
|------|------|------------------------|----------------|--------------------|
| `entry` | String | On | Yes (mortgage) | where the customer came from: `aria` |
| `contactId` | String | On | Yes (mortgage) | the call's or chat's ID; every Data request sends it |
| `firstName` | String | On | Yes (mortgage) | the customer's first name |
| `handoverSummary` | String | On | Yes (mortgage) | what the customer already told ARIA |
| `channel` | String | On | **No: create it** | `VOICE` or `CHAT` |
| `summary` | String | Off | Yes (mortgage) | the assistant's note for the adviser |
| `escalationReason` | String | Off | Yes (mortgage) | why the customer goes to a person |

Sharing them with the mortgage assistant is safe: each conversation has its own values. The
mortgage flows keep setting `entry` to `phone` or `web_widget`; only this assistant sees `aria`.

There's no `verification` variable: the dispute service checks every request itself and answers
`customer_not_identified` for anyone ARIA didn't verify, and the assistant then passes them to a
colleague.

### 2b. The Secret (1)

The Data requests prove who they are with a key. The deploy script created it in AWS; you copy it
into the designer once.

1. In another browser tab: AWS console → **Secrets Manager** → open `aria-card-dispute/acxd-key` →
   **Retrieve secret value** → copy the value.
2. Back in the designer: **Resources** → **Secrets** → **Add secret**. Name `card_dispute_api_key`,
   paste the value, **Save**.

Don't paste the key anywhere else.

### 2c. Data requests (7)

These are the assistant's tools. All seven call the same address; only `operation` and the fields
differ.

**Do these steps for each of the seven below:**

1. **Resources** → **Data requests** → **New data request**.
2. **Name**: the name in the heading, exactly (for example `listCardsAndPayments`).
3. **Description**: the "Description" text. The assistant reads it to decide when to use the tool,
   so paste it as written.
4. **Implementation** tab → choose **External** (never **Static**: Static returns made-up data and
   never calls the service). Then:
   - **Method**: `POST`.
   - **Production** and **Development** endpoint URL: both the **Data request address** from the
     deploy script, ending `/acxd/ops`.
   - **Headers**, add two:
     - `Content-Type` with value `application/json`;
     - `x-api-key`: in the value box type `{`, choose **Secrets**, then `card_dispute_api_key`.
5. **Request model**: choose **Auto-generate** (the star icon), paste the "Request sample", confirm.
6. **Response model**: **Auto-generate** again, paste the "Response sample", confirm. Where it says
   "the same as `startDispute`", paste `startDispute`'s response sample.
7. **Save**.
8. **Test**: open **Test**, choose **Development**, enter the request sample's values, and run.
   - `ok: false` with reason `customer_not_identified` is **correct** here: the sample's contact
     isn't a real verified call, and it proves the request reached the service.
   - `401` means the `x-api-key` header isn't using the Secret. Check step 4.

Every reply has `ok`, `reason` and `message`. When `ok` is false, `message` says what to do, and the
assistant follows it.

None of these takes a customer ID or a phone number. The service finds both from the call or chat
itself, and does nothing for a customer ARIA didn't verify. None can confirm or submit a dispute.

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

Description: "Shares this dispute's form with the customer, joined to this conversation, only when they want to see it. On a phone call it is texted to the mobile they are calling from: say only sentTo, never a number, and link is empty. On chat it comes back in link: post it in your message exactly as given."

| Request sample | `{"operation":"sendFormLink","contactId":"0a1b2c3d-1111-2222-3333-444455556666","disputeId":"DSP-ABCD2345"}` |
|---|---|
| Response sample | `{"ok":true,"reason":"","message":"","sent":true,"sentTo":"the mobile ending 123","link":""}` |

---

## Part 3 — Build the flows

You build two flows. Build `HandBackToARIA` first, because the main flow points to it.

**How the canvas works**
- **Add a node**: **Add** on the toolbar, or right-click the canvas → **New node**.
- **Connect two nodes**: drag from a node's small exit dot to the next node.
- **Edit a node**: click it; its settings open on the side.
- **Validation** on the toolbar lists anything not connected.

### 3a. Flow `HandBackToARIA`

```
Start → Generative text "handoffNote" → Generative text "handoffReason" → Escalate
```

1. **Resources** → **Flows** → **New flow**. Name `HandBackToARIA` (flow names can't have
   spaces), then **Create flow**.
2. Add a **Generative text** node and connect **Start** to it.
   - **Output variable**: `handoffNote`.
   - **Prompt**: paste, then re-insert `{System.transcript}` with the `{` menu:
     "In one sentence for a bank adviser, say anything they should know that is not on the dispute form: how the customer is feeling, anything they asked for that was not done, anything else they want help with. Write 'Nothing further.' if there is nothing. No card numbers. Conversation: {System.transcript}"
3. Add a second **Generative text** node. Connect the first node's **Success**, **Failure** *and*
   **Timeout** to it, so an empty answer never stops the hand-off.
   - **Output variable**: `handoffReason`.
   - **Prompt**: "Why is this going to a person? Output exactly one of: dispute_ready_for_review, dispute_incomplete, customer_request, vulnerability, tool_failure, other. No markdown, no explanation. Conversation: {System.transcript}"
4. Add an **Escalate** node. Connect the second node's **Success**, **Failure** and **Timeout** to it.
   - **Message**: "That's everything I need. A colleague will now check the form with you before
     it's submitted. You won't need to repeat anything."
   - **Add functionality** → **State modifications**. Add two **Set** rows; for each value type `{`
     and pick the variable:

     | Context variable | Value |
     |------------------|-------|
     | `summary` | `{handoffNote}` |
     | `escalationReason` | `{handoffReason}` |

   - Leave the Escalate node's **Continuation** path unconnected. **Validation** may mention it;
     that's expected.
5. **Save**.

You don't choose the team or write the dispute summary here. Connect builds both from what the
assistant saved, so they're always right.

### 3b. Flow `CardDispute` (the main flow)

```
Start → Generative text "openingQuestion" ─ Success ─────────► Basic "{openingQuestion}" ─┐
                                          └ Failure / Timeout ► Basic (fixed question) ───┤
                                                                                           ▼
                                        Live Sync node "CardDisputeAssistant" ─ exits ─► Redirect → HandBackToARIA
```

1. **Resources** → **Flows** → **New flow**. Name `CardDispute`, then **Create flow**.

**The opening.** The assistant node only replies to what the customer says; it never speaks first.
Coming from ARIA, the customer has just heard (or read) one sentence and is waiting. So the flow
must speak first and end with a question, or the conversation goes silent. Your mortgage build
showed this.

2. Add a **Generative text** node and connect **Start** to it.
   - **Output variable**: `openingQuestion`.
   - **Prompt** (re-insert `{handoverSummary}` with the `{` menu):
     "The customer wants to dispute a card payment. They already told our assistant: {handoverSummary}. Write one short, warm question, in plain UK English, that moves the dispute on without asking for anything they already said. If they named the payment, ask them to confirm it in a few words, naming it. If they said someone else is using the card or it is lost, ask if they would like it blocked straight away. Otherwise ask which payment it is: the shop and roughly how much is enough. Do not greet them, do not say who you are, and do not mention transferring. Output only the question."
3. Add a **Basic** node from the Generative text node's **Success**. **Message**: type `{` and pick
   `openingQuestion`.
4. Add another **Basic** node, and connect the Generative text node's **Failure** and **Timeout** to
   it. **Message**: "Which card payment would you like to dispute? The shop and roughly how much is
   enough."

**The assistant.**

5. Add a **Live Sync** node, name it `CardDisputeAssistant`, and connect both Basic nodes to it.
   Live Sync lets the assistant see the form when the customer opens the link, including anything
   they type. With no form open, it's an ordinary phone or chat conversation.
6. **Prompt**: paste the whole block below, then re-insert each `{name}` with the `{` menu
   (`{channel}`, `{firstName}`, `{handoverSummary}`).

```
You are the card dispute assistant for the bank. The customer was just talking to our assistant,
ARIA, and has been passed to you without being told: to them it is the same conversation. Never
introduce yourself, never greet them again, and never ask for anything they already said. You
handle the whole dispute. A colleague then checks it with the customer and submits it.

Conversation details (empty when not known):
channel: {channel} | first name: {firstName}
already said to ARIA: {handoverSummary}

Channel
- channel VOICE is a phone call: you are speaking. Keep turns short and never spell things out.
- channel CHAT is a chat: you are writing. Keep messages short; you may use a short list.

Before anything else
- If any tool replies with reason customer_not_identified, the customer is not verified: do
  nothing on their cards or disputes, say a colleague will help, and use Escalation requested.
- Call listCardsAndPayments once, and use it to find the payment. Never give a full card number;
  "your debit card ending 4821" is fine.

If someone else is using their card, or they have lost it
- Offer to block it straight away. With their yes, call blockCard. Then offer a replacement and,
  with their yes, call orderReplacementCard. Tell them it arrives in arrivesInWorkingDays working
  days. Do this before the rest of the dispute.

The dispute
1. Find the payment from what they say: retailer, amount or date. If two match, ask one question to
   tell them apart. If none match, say you cannot see it and use Escalation requested.
2. Ask whether they made the payment, unless they have said. Then call startDispute with that
   payment's transactionId and disputeType: unauthorised if they did not make it or do not
   recognise it, merchant if they made it but something went wrong.
3. Fill in everything you already know without asking: what they told ARIA and you so far. Save it
   with updateDispute. Then ask only for what the reply's missing field lists, one question at a
   time, and save each answer as soon as you have it. For the reason, choose from reasonsAllowed
   using their words; never show or say the codes. Write narrative in their own words; do not
   improve it.
4. Never say you have saved something unless updateDispute replied ok=true.

Seeing the form
- Once the dispute is started, offer once to share the form so they can see it as you go. With
  their yes, call sendFormLink.
  - On VOICE: tell them it has been texted to sentTo. Never read out a link or a number.
  - On CHAT: post the link from the reply exactly as given, on its own line, with one short line
    saying it opens their dispute form.
  - If ok is false, say you can't share it right now and carry on.
- When they open it, they see your changes within a couple of seconds and can type in it too. Call
  getDispute to see what they typed. Saving with updateDispute is enough; you do not need to fill
  in the page yourself.

Finishing
- When complete is true, sum up the dispute in one or two sentences, including any card you blocked
  or replaced, and ask if it is right. Correct anything with updateDispute.
- Then use Escalation requested. A colleague checks it with them and submits it.

What you never do
- Never submit, confirm or accept a dispute, and never say it has been submitted or accepted.
- Never state or guess a refund, a timescale for the dispute or its outcome. Say: "My colleague will
  explain what happens next."
- Never block or replace a card without the customer's yes.
- Never give a full card number or phone number, or a reference you were not asked for.
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

7. **Tools**: in the node's tools section, add each of the seven Data requests. For each one, paste
   its Description as the tool prompt, then map its inputs:

   | Input | Choose |
   |-------|--------|
   | `operation` | **Explicit text**, and type the Data request's own name, for example `blockCard` |
   | `contactId` | **Variable**, then pick the context variable `contactId` |
   | every other input | **LLM prompt** (the assistant fills it from the conversation) |

   Don't choose Explicit text and put a `{contactId}` chip inside it. The designer then sends the
   chip's placeholder instead of the real ID, and every request answers `customer_not_identified`.
   The mortgage build hit exactly this.

8. **Data capture**: don't add it, and remove it if the node has one. The Data requests save the
   dispute; slots would stay empty and make the node fail.
9. **Live Sync actions**: paste the contents of `acxd/live-sync-actions.json` (an empty list).
   There's no action that confirms or submits.
10. **Exit conditions**: add these two.

    | Name | Description for the agent |
    |------|---------------------------|
    | `Escalation requested` | Use when the dispute is complete and summed up, when the customer asks for a person, when the payment cannot be found, when the customer is not verified, or at any sign of vulnerability. Always use this exit for any transfer. |
    | `Unable to help` | A Data request failed twice. |

11. From each exit, and from the node's **Timeout** and **Failure** paths, add a **Redirect** node
    pointing to the flow `HandBackToARIA` (one Redirect node can take all four). Don't add a "Task
    complete" exit: this assistant never finishes a dispute; an adviser does.
12. **Save**, then **Validation**. Fix anything it lists, except the Escalate node's Continuation
    in `HandBackToARIA`.

---

## Part 4 — Create, build and deploy the application

1. **Applications** → **New application**. Name `Card dispute`, then **Create**.
2. **Design** tab:
   1. Attach both flows, `CardDispute` and `HandBackToARIA`, and **Save**. A Redirect only works if
      its target flow is attached.
   2. Set all four **default behaviours** (the **Default behavior** icon under the **Flows** list),
      then **Save**:

      | Default | Flow |
      |---------|------|
      | **Welcome** | `CardDispute` |
      | **Unknown** | `CardDispute` |
      | **Fallback** | `HandBackToARIA` |
      | **Escalation** | `HandBackToARIA` |

      If Unknown or Fallback is empty, the build warns about "Default quick replies" and the
      assistant uses generic built-in replies. Set both.
3. **Voice**: in the application's settings, find its voice and choose **Amy, English (UK)**, the
   voice ARIA uses. Connect's own Set voice block doesn't change this assistant's voice. If Amy
   isn't offered, choose the closest British voice, write it down, and set ARIA's Set voice block to
   the same one (README step 10). On chat, voice doesn't matter.
4. **Deploy** tab:
   1. Choose **Development** → **Build & deploy**.
   2. Read the checks: red must be fixed, yellow are warnings.
   3. Description `v1 card dispute`, then **Build**.
   4. When the build finishes, hover over its status → **Deploy**. It shows **Live** when done.
5. **Test** tab: type "I want to dispute a payment" and check it replies. It can't do real work
   here (there's no verified call, so the Data requests say `customer_not_identified`), and that's
   expected. The real test is README "Test it".
6. When you're happy, repeat step 4 with **Production**.
7. **Write down**, for the README:
   - the **application ID** (in the application's settings, or the address bar);
   - the **alias** of the environment you deployed (for example `Production`'s alias);
   - the build's **deployment key** (click the deployed build);
   - the application's **API key** (application settings → **Access**).
