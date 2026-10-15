# CX designer guide — the "Card dispute" assistant

This guide builds, step by step, the assistant that takes a card dispute over from ARIA. It is
written for someone who has never built anything in agentic CX designer. Every click is listed,
and each part ends with a check, so you know it worked before you move on.

**What the assistant does.** When a customer tells ARIA they want to dispute a card payment, ARIA
passes them to this assistant without saying so. The assistant then:

- finds the payment;
- fills in the dispute form, asking only for what it doesn't already know;
- blocks the card and orders a replacement, if the customer says yes;
- shares the form if the customer wants to see it: **texted** on a phone call, **posted in the
  chat** on chat.

When it's finished, it hands the customer back, and Connect passes them to an adviser, who checks
the form and submits it.

It works the same on a **phone call** and on **chat**.

**Time:** allow about two hours the first time. You can stop between parts; everything you save is
kept.

---

## Before you start

**Have these open:**

1. **This file**, in VS Code. You'll copy text from it. Always copy from the file, not from a chat
   or an email, so nothing gets changed on the way.
2. **The AWS console**, signed in, region **Europe (London)** (top right).
3. **The output of `deploy_card_dispute.sh`** (README step 2). You need one line from it, the
   **Data request address**, which looks like
   `https://abcd1234.execute-api.eu-west-2.amazonaws.com/acxd/ops`.

**Five words you'll meet:**

| Word | What it means |
|---|---|
| **Workspace** | A container for everything you build. Your mortgage assistant lives in `ariaworkspace`; so will this one, and it shares some of the mortgage assistant's pieces |
| **Resource** | Something flows use: a context variable, a Secret, a Data request. Created once, in the workspace |
| **Flow** | A diagram of boxes (**nodes**) joined by lines (**paths**). It's the script of the conversation |
| **Application** | A package of flows that you build and deploy. Connect talks to the application |
| **Chip** | A coloured tag inside a text box that stands for a variable or Secret. You insert it from a menu; you never type it |

**Three habits that avoid almost every problem:**

1. **Never type `{` … `}` by hand.** When a value in this guide contains `{something}`, type only
   `{`. A menu opens; choose the item. It turns into a chip. Text you type with braces is sent as
   plain text, and the assistant breaks without any error message.
2. **Save often.** Nothing saves on its own. If you close the tab without saving, it's gone.
3. **Type names exactly.** `CardDispute` and `carddispute` are different things to the designer.

---

## Part 1 — Open the designer and your workspace

1. In the AWS console, type `Amazon Connect` in the search bar at the top and open it.
2. You see a list of instances. Click your instance's **alias**, the blue link in the first
   column. Don't tick the checkbox.
3. On the instance page, look for **agentic CX designer** (in the left menu or on the page) and
   click it. It opens in a new browser tab.
4. At the **top left** there's a drop-down with a workspace name. Click it and choose
   **`ariaworkspace`**.

✅ **Check:** in the left menu, open **Resources** → **Data requests**. You see your mortgage
assistant's Data requests (for example `attachToScreen`). That proves you're in the right workspace.

---

## Part 2 — Create the resources

Resources come first, because a flow can only use a resource that already exists.

### 2a. Context variables (7 used, only 1 to create)

**What they are.** A context variable is a named box that carries a value between Connect and the
assistant. Connect puts values in when the conversation starts (for example the customer's first
name), and the assistant puts values in when it finishes (for example its note for the adviser).
Connect can only fill a box that has **Allow frontend updates** switched on.

They belong to the whole workspace, so the mortgage assistant's boxes are shared with this one.
Six of the seven this assistant uses already exist from the mortgage build
([connect-livesync-mortgage](https://github.com/alokkulkarni/connect-livesync-mortgage), GUIDE
Part 3a). **Don't create those again; only check them.**

**Check the six that exist:**

1. Left menu → **Resources** → **Context variables**. A list appears.
2. Find each row marked "Yes" in the table below. Click it, check **Type** is **String** and **Allow
   frontend updates** is as shown, and close it without changing anything.
3. If one is missing (it shouldn't be), create it as below.

**Create the new one:**

4. Click **Add context variable**.
5. **Name**: `channel`. **Type**: **String**. **Allow frontend updates**: switch it **On**.
6. **Save**.

| Name | Type | Allow frontend updates | Already there? | What it holds here |
|------|------|------------------------|----------------|--------------------|
| `entry` | String | On | Yes (mortgage) | where the customer came from: `aria` |
| `contactId` | String | On | Yes (mortgage) | the call's or chat's ID; every Data request sends it |
| `firstName` | String | On | Yes (mortgage) | the customer's first name |
| `handoverSummary` | String | On | Yes (mortgage) | what the customer already told ARIA |
| `channel` | String | On | **No: create it** | `VOICE` or `CHAT` |
| `summary` | String | Off | Yes (mortgage) | the assistant's note for the adviser |
| `escalationReason` | String | Off | Yes (mortgage) | why the customer goes to a person |

Sharing them with the mortgage assistant is safe: every conversation has its own values. The
mortgage flows keep setting `entry` to `phone` or `web_widget`; only this assistant sees `aria`.

There's no "verified" variable. The dispute service checks every request itself, and answers
`customer_not_identified` for anyone ARIA didn't verify; the assistant then passes them to a
colleague.

✅ **Check:** the list shows `channel`, and the six others are as in the table.

### 2b. The Secret (1)

**What it is.** The assistant's tools call the dispute service over the internet. The service only
answers callers who present the right key, like a password. The deploy script created that key in
AWS Secrets Manager; you copy it into the designer once, as a **Secret**, so the tools can present
it without anyone seeing it.

This is a new Secret. The mortgage assistant's `mortgage_api_key` unlocks a different service and
won't work here.

1. **AWS console tab**: search `Secrets Manager` and open it.
2. Click the secret named **`aria-card-dispute/acxd-key`**.
3. Scroll to **Secret value** → click **Retrieve secret value** → click the copy icon next to the
   value.
4. **Designer tab**: left menu → **Resources** → **Secrets** → **Add secret**.
5. **Name**: `card_dispute_api_key`. **Value**: paste (Cmd+V). **Save**.
6. Don't paste the key anywhere else (not in notes, chats or emails).

✅ **Check:** `card_dispute_api_key` appears in the Secrets list. The designer won't show its value
again; that's normal.

### 2c. Data requests (7)

**What they are.** A Data request is one tool the assistant can use: a call to the dispute service.
Each has a **name**, a **description** the assistant reads to decide when to use it, and a
**request** and **response** shape. All seven call the same address; only the `operation` field and
the other fields differ.

You create seven, all the same way. Below the steps, each one has its own heading with exactly
what to paste.

**For each of the seven, in this order** (`listCardsAndPayments`, `startDispute`, `updateDispute`,
`getDispute`, `blockCard`, `orderReplacementCard`, `sendFormLink`):

1. Left menu → **Resources** → **Data requests** → **New data request**.
2. **Name**: the name in the heading, exactly. Example: `listCardsAndPayments`.
3. **Description**: copy the text inside the quotation marks after "Description:" in that heading.
   Don't include the quotation marks themselves. The assistant reads this to decide when to use
   the tool, so don't reword it.
4. Open the **Implementation** tab and choose **External**.
   - Never choose **Static**: Static returns made-up data and never calls the service.
   - **Method**: `POST`.
   - **Production** endpoint URL: paste the **Data request address** (ends `/acxd/ops`).
   - **Development** endpoint URL: paste the same address.
   - **Headers**: add the first header: key `Content-Type`, value `application/json`.
   - Add a second header: key `x-api-key`. For its value, click in the value box, type `{`, choose
     **Secrets**, then click `card_dispute_api_key`. A chip appears. Don't type anything else.
5. **Request model**: click **Auto-generate** (the star icon). A box opens. Paste the **Request
   sample**: everything between the backticks in that heading, starting with `{` and ending with
   `}`. Confirm. The designer turns it into a list of fields.
6. **Response model**: click **Auto-generate** again and paste the **Response sample** the same
   way. For `updateDispute` and `getDispute`, the heading says "the same as `startDispute`": paste
   `startDispute`'s response sample.
7. **Save**.
8. **Test** it:
   1. Open the **Test** tab and choose the **Development** environment.
   2. Fill in the fields with the values from the request sample.
   3. Click **Run**.
   - ✅ **The right result is** `"ok": false` with `"reason": "customer_not_identified"`. That's
     good news: the sample's contact isn't a real verified customer, and the reply proves the tool
     reached the dispute service and the key worked.
   - ❌ **`401`**: the `x-api-key` header isn't using the Secret. Go back to step 4.
   - ❌ **The response sample comes back unchanged**: you chose Static. Switch to External.
   - ❌ **Timeout or "could not connect"**: the address is wrong. Copy it again from the deploy
     output.

Every reply has `ok`, `reason` and `message`. When `ok` is false, `message` tells the assistant what
to do, and it follows it.

None of these tools takes a customer ID or a phone number. The service finds both from the call or
chat itself, and does nothing for a customer ARIA didn't verify. None can confirm or submit a
dispute.

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

✅ **Check before Part 3:** the Data requests list shows all seven new names, and each one tested as
described in step 8.

---

## Part 3 — Build the flows

### How flows and the canvas work (read this once)

A **flow** is drawn on a **canvas**, a big empty page you can scroll and zoom.

- A **node** is a box that does one thing: say a message, ask the AI to write something, let the
  assistant talk, hand over. Every flow starts with a **Start** node that's already there.
- A **path** is a line from one node to the next. Most nodes have several exits, shown as small
  dots or labels on their edge: for example **Success**, **Failure** and **Timeout**. Each exit
  needs a line to wherever that outcome should go.
- An **output variable** is a name you give a node's result, so later nodes can use it as a chip.

**The moves you need:**

| To | Do |
|---|---|
| Add a node | Click **Add** on the toolbar, or right-click empty canvas → **New node**, then choose the node type |
| Connect two nodes | Press and hold on an exit dot of the first node, drag to the second node, let go. A line appears |
| Change a node | Click it. Its settings open in a panel on the right. Close the panel when done |
| Remove a line | Click the line and press Delete (or use its menu) |
| Move around | Drag empty canvas to scroll; use the zoom buttons or your trackpad to zoom |
| Find problems | Click **Validation** on the toolbar. It lists anything not connected |

**Node types used here:**

| Node | What it does |
|---|---|
| **Generative text** | Asks the AI to write some text from a prompt you give it, and stores it in an output variable. The customer doesn't see it |
| **Basic** | Says (or, on chat, writes) a message to the customer |
| **Live Sync** | The assistant itself: talks with the customer, uses tools, and can see the form on the customer's screen |
| **Escalate** | Ends the assistant's part and hands the customer back to Connect |
| **Redirect** | Jumps to another flow |

You build two flows. **Build `HandBackToARIA` first**, because the main flow jumps to it, and a
Redirect can only choose a flow that exists.

### 3a. Flow `HandBackToARIA`

**What it does.** It runs at the very end. It asks the AI for a one-line note for the adviser and a
reason, then hands the customer back to Connect. The finished flow looks like this:

```
Start → Generative text "handoffNote" → Generative text "handoffReason" → Escalate
```

1. **Create the flow.** Left menu → **Resources** → **Flows** → **New flow**. **Name**:
   `HandBackToARIA` (flow names can't contain spaces). Click **Create flow**. The canvas opens with
   a **Start** node.
2. **The note for the adviser.**
   1. Add a **Generative text** node. Place it to the right of **Start**.
   2. Drag a line from **Start**'s exit to it.
   3. Click it to open its settings.
   4. **Output variable**: `handoffNote`.
   5. **Prompt**: copy this text and paste it in:
      "In one sentence for a bank adviser, say anything they should know that is not on the dispute form: how the customer is feeling, anything they asked for that was not done, anything else they want help with. Write 'Nothing further.' if there is nothing. No card numbers. Conversation: {System.transcript}"
   6. At the end of the prompt, delete the pasted `{System.transcript}`. In its place type `{`,
      choose **System**, then **transcript**. A chip appears. This chip gives the AI the whole
      conversation so far.
3. **The reason.**
   1. Add a second **Generative text** node to the right of the first.
   2. From the **first** node, drag **three** lines to it: from **Success**, from **Failure** and
      from **Timeout**. That way the hand-over carries on even if the AI fails to answer.
   3. Click it. **Output variable**: `handoffReason`.
   4. **Prompt**: paste, then replace `{System.transcript}` with the chip as before:
      "Why is this going to a person? Output exactly one of: dispute_ready_for_review, dispute_incomplete, customer_request, vulnerability, tool_failure, other. No markdown, no explanation. Conversation: {System.transcript}"
4. **The hand-back.**
   1. Add an **Escalate** node to the right.
   2. From the second Generative text node, drag lines from **Success**, **Failure** and **Timeout**
      to it.
   3. Click it. **Message** (what the customer hears or reads):
      "That's everything I need. A colleague will now check the form with you before it's
      submitted. You won't need to repeat anything."
   4. Click **Add functionality** → **State modifications**. This is how values reach Connect.
      Add two rows with **Set**:

      | Context variable | Value |
      |------------------|-------|
      | `summary` | `{handoffNote}` |
      | `escalationReason` | `{handoffReason}` |

      For each row, choose the context variable from the list. For the value, type `{` and choose
      the output variable (`handoffNote` or `handoffReason`) so it becomes a chip.
   5. The Escalate node has an exit called **Continuation**. **Leave it unconnected.**
5. Click **Save**.

You don't choose the adviser's team or write the dispute summary here. Connect builds both from
what the assistant saved, so they're always right.

✅ **Check:** four nodes in a row, every exit connected except the Escalate node's **Continuation**.
**Validation** may mention that Continuation; that's expected.

### 3b. Flow `CardDispute` (the main flow)

**What it does.** It's the whole conversation. It has two parts: an **opening** that asks the first
question, and the **assistant** that does the dispute. When the assistant finishes, it jumps to
`HandBackToARIA`. The finished flow looks like this:

```
Start → Generative text "openingQuestion" ─ Success ─────────► Basic "{openingQuestion}" ─┐
                                          └ Failure / Timeout ► Basic (fixed question) ───┤
                                                                                           ▼
                                        Live Sync node "CardDisputeAssistant" ─ exits ─► Redirect → HandBackToARIA
```

1. **Create the flow.** Left menu → **Resources** → **Flows** → **New flow**. **Name**:
   `CardDispute`. Click **Create flow**.

**The opening.** The assistant node only ever *replies*; it never speaks first. Coming from ARIA,
the customer has just heard (or read) one short sentence and is waiting. So the flow must speak
first and end with a question, or the conversation goes silent. Your mortgage build found this the
hard way. The opening writes a question that fits what the customer already told ARIA, and has a
fixed question as a back-up.

2. **Write the first question.**
   1. Add a **Generative text** node and drag a line from **Start** to it.
   2. Click it. **Output variable**: `openingQuestion`.
   3. **Prompt**: paste this, then delete the pasted `{handoverSummary}` and insert the chip (type
      `{`, choose the context variable `handoverSummary`):
      "The customer wants to dispute a card payment. They already told our assistant: {handoverSummary}. Write one short, warm question, in plain UK English, that moves the dispute on without asking for anything they already said. If they named the payment, ask them to confirm it in a few words, naming it. If they said someone else is using the card or it is lost, ask if they would like it blocked straight away. Otherwise ask which payment it is: the shop and roughly how much is enough. Do not greet them, do not say who you are, and do not mention transferring. Output only the question."
3. **Say that question.**
   1. Add a **Basic** node. Drag a line from the Generative text node's **Success** to it.
   2. Click it. **Message**: type `{` and choose `openingQuestion`. The message is just that chip.
4. **The back-up question.**
   1. Add another **Basic** node. Drag lines from the Generative text node's **Failure** and
      **Timeout** to it.
   2. Click it. **Message**: "Which card payment would you like to dispute? The shop and roughly
      how much is enough."

**The assistant.**

5. **Add the assistant node.**
   1. Add a **Live Sync** node.
   2. Name it `CardDisputeAssistant`.
   3. Drag a line from **each** Basic node to it (two lines in total).

   Live Sync means the assistant can also see the dispute form if the customer opens the link, and
   see anything they type. When no form is open, it's an ordinary phone or chat conversation.
6. **Prompt** (the assistant's instructions). Click the node and find its **Prompt** box. Copy the
   whole block below (everything between the two lines of three backticks, but not the backticks)
   and paste it in. Then find these three, delete each, and insert it as a chip with `{`:
   `{channel}`, `{firstName}`, `{handoverSummary}`.

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

7. **Tools.** Still in the `CardDisputeAssistant` node, find its **Tools** section. Add the seven
   Data requests from Part 2c, one at a time:
   1. **Add tool** → type **Data request** → pick the Data request (for example
      `listCardsAndPayments`).
   2. **Tool prompt** (or description): paste that Data request's Description again.
   3. The tool shows its **inputs**, one per field of its request sample. For each input, choose
      where its value comes from:

      | Input | Choose |
      |-------|--------|
      | `operation` | **Explicit text**, and type the Data request's own name, for example `blockCard` |
      | `contactId` | **Variable**, then pick the context variable `contactId` from the list |
      | every other input | **LLM prompt** (the assistant fills it in from the conversation) |

   4. Repeat for all seven.

   ⚠️ **The most common mistake:** choosing **Explicit text** for `contactId` and inserting a
   `{contactId}` chip inside it. The designer then sends the chip's placeholder text instead of the
   real ID, and every tool answers `customer_not_identified`. Always use **Variable** for
   `contactId`. The mortgage build hit exactly this.

8. **Data capture.** If the node has a **Data capture** section, remove it (or leave it empty). The
   tools save the dispute; data capture slots would stay empty and make the node fail.
9. **Live Sync actions.** Find the node's **Live Sync actions** box. In VS Code, open
   `acxd/live-sync-actions.json`, copy all of it (`{"actions": []}`), and paste it in. It's empty on
   purpose: nothing on the page can confirm or submit.
10. **Exit conditions.** These are the ways the assistant can finish. In the node, find **Exit
    conditions** and add two. Paste the descriptions exactly; the assistant reads them to decide
    when to leave.

    | Name | Description for the agent |
    |------|---------------------------|
    | `Escalation requested` | Use when the dispute is complete and summed up, when the customer asks for a person, when the payment cannot be found, when the customer is not verified, or at any sign of vulnerability. Always use this exit for any transfer. |
    | `Unable to help` | A Data request failed twice. |

    Each exit you add appears as a new exit dot on the node, next to its built-in **Timeout** and
    **Failure** exits. Don't add a "Task complete" exit: this assistant never finishes a dispute;
    an adviser does.

11. **Send every way out to the hand-back.**
    1. Add a **Redirect** node to the right of the assistant. Click it and choose the flow
       **`HandBackToARIA`**.
    2. Drag four lines from `CardDisputeAssistant` to the Redirect: from **Escalation requested**,
       **Unable to help**, **Timeout** and **Failure**.
12. **Save**, then click **Validation** on the toolbar. It lists anything not connected. Fix each
    one by drawing the missing line. The only thing it may still mention is the Escalate node's
    Continuation in `HandBackToARIA`, which is fine.

✅ **Check:** the flow matches the picture at the top of 3b. The assistant node has a prompt, seven
tools, no data capture, two exit conditions, and four lines to the Redirect.

---

## Part 4 — Create, build and deploy the application

**What this is.** The flows exist, but nothing can use them until they're in an **application**
that's been built and deployed. Make a **new** application for this assistant. Don't add these flows
to the Mortgage application: an application has one starting flow, and the mortgage one starts the
mortgage conversation.

1. **Create it.** Left menu → **Applications** → **New application**. **Name**: `Card dispute`.
   **Create**.
2. **Design tab: attach the flows and set the defaults.**
   1. Attach the two flows `CardDispute` and `HandBackToARIA` (not the mortgage flows). **Save**.
      A Redirect only works if its target flow is attached.
   2. Click the **Default behavior** icon under the **Flows** list (or the three-dot menu next to a
      flow). Set all four, then **Save**:

      | Default | Flow | When it's used |
      |---------|------|----------------|
      | **Welcome** | `CardDispute` | a conversation starts |
      | **Unknown** | `CardDispute` | the assistant didn't understand; it asks again |
      | **Fallback** | `HandBackToARIA` | something keeps going wrong; send to a person |
      | **Escalation** | `HandBackToARIA` | the customer needs a person |

      If Unknown or Fallback is left empty, the build warns about "Default quick replies" and the
      assistant uses generic built-in replies. Set both.
3. **Voice.** Open the application's settings and find its voice. Choose **Amy, English (UK)**,
   the voice ARIA uses, so a caller hears one voice throughout. Connect's own Set voice block
   doesn't change this assistant's voice; only this setting does. If Amy isn't offered, choose the
   closest British voice, write its name down, and set ARIA's Set voice block to the same one
   (README step 10). On chat, the voice doesn't matter.
4. **Deploy tab: build and deploy.**
   1. Choose the **Development** environment → **Build & deploy**.
   2. Read the checks it shows. **Red** items must be fixed (it says which flow or node). **Yellow**
      items are warnings; read them, but you can go on.
   3. **Description**: `v1 card dispute`. Click **Build**. Wait; it takes a few minutes.
   4. When it finishes, hover over the build's status and choose **Deploy**. Wait until it shows
      **Live**.
5. **Test tab: quick check.** Type "I want to dispute a payment". It should reply with a question.
   It can't look anything up here, because there's no verified customer in this test, so its tools
   answer `customer_not_identified` and it offers a colleague. That's expected. The real test is in
   the README, "Test it".
6. **Production.** Repeat step 4, choosing **Production** instead of Development.
7. **Write down four things.** You need them in the README, steps 7 and 8:
   - the **application ID**: in the application's settings, or in the browser's address bar;
   - the **alias** of the **Production** environment you deployed to;
   - the build's **deployment key**: click the deployed build;
   - the application's **API key**: application settings → **Access**.

✅ **Check:** the application `Card dispute` shows **Live** in Production, and you have the four
values written down.

---

## If something goes wrong here

| What you see | What it means | Fix |
|---|---|---|
| A Data request test gives `401` | The key isn't being sent | Part 2c step 4: the `x-api-key` value must be the Secret chip |
| A test returns exactly the sample | The Data request is Static | Part 2c step 4: choose External |
| A flow can't find `HandBackToARIA` in the Redirect | That flow wasn't saved, or isn't attached to the application | Save it (3a step 5); attach it (Part 4 step 2) |
| The build shows red items | Something is unconnected or missing | Click the item; it opens the node. Usually a missing line |
| In a real call, the assistant says nothing after ARIA | The opening isn't connected to the assistant | 3b steps 2 to 5 |
| In a real call, every tool says `customer_not_identified` | `contactId` isn't set as a Variable, or ARIA hadn't verified the customer | 3b step 7 |
| Prompt text shows `{channel}` as typed words, not a chip | The braces were typed | Delete it and insert with `{` |
