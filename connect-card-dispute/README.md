# Card Transaction Disputes — Setup Guide

A customer tells ARIA, **on the phone or in a chat**, that they want to dispute a card payment or
don't recognise one. ARIA checks who they are and passes them, without announcing it, to the **card
dispute assistant**. That assistant does the whole dispute:

- finds the payment;
- fills in the dispute form, asking only for what it doesn't already know;
- blocks the card and orders a replacement, if the customer says yes;
- shares the form if the customer wants to see it: **texted** on a phone call, **posted in the
  chat** on chat. The form then fills in in front of them as they talk.

Then the customer goes to an adviser through ARIA's usual hand-over. The adviser's screen shows
the dispute, any card blocked or ordered, and a link to the form. The adviser checks it with the
customer and submits it.

**This guide assumes you've never done this before.** Do the steps in order; each one needs the
one before. Every step says what you should see when it has worked.

> **Nothing here has been tried on a live call or chat yet.** The code has automatic tests only.
> The CX designer and Connect steps follow your mortgage Live Sync build, which works. Your first
> real call and chat are the real test, and "Test it" says exactly what to check.

## Table of Contents

- [1. How it works](#1-how-it-works)
- [2. Words you'll see](#2-words-youll-see)
- [3. Before you start](#3-before-you-start)
- [Set it up (11 steps)](#set-it-up)
- [Test it](#test-it)
- [Troubleshooting](#troubleshooting)
- [How to undo it](#how-to-undo-it)
- [What is in this folder](#what-is-in-this-folder)
- [Earlier designs](#earlier-designs)

---

## 1. How it works

```
Customer (phone or chat) ─► ARIA            checks they're verified, then calls StartCardDispute
                              │
                              ▼
                      "Card dispute assistant" flow (Connect)
                              │ 1. notes the channel: VOICE or CHAT
                              │ 2. the CX designer assistant does the dispute
                              │ 3. Lambda builds the hand-over from what was saved
                              ▼
                      "ARIA human handover" flow ─► adviser's queue
                              │
                              ▼
                      Adviser: screen pop "Card dispute" ─► opens the form ─► customer confirms ─► Submit
```

| | ARIA | Card dispute assistant | Adviser |
|---|---|---|---|
| Checks the customer is verified | Yes | Checks again (and the service refuses an unverified customer) | Own checks |
| Asks about the payment and the card | Never | Yes, only what it doesn't know | Confirms with the customer |
| Fills in the dispute | Never | Yes | Can change anything |
| Blocks / replaces the card | No (for disputes) | Yes, with the customer's yes | In your own systems |
| Shares the form | No | Phone: texts it. Chat: posts it | — |
| Submits | Never | Never (it can't) | Yes, after the customer confirms |

**Why ARIA doesn't speak again at the end.** ARIA's own transfers work by filling in four details
and then running the **ARIA human handover** flow. The dispute route ends on that same flow with
the same four details, so to the adviser it is an ARIA hand-over. Bringing a caller back into ARIA
just to say goodbye would leave them in silence, because ARIA waits for the customer to speak first.

---

## 2. Words you'll see

| Word | What it means here |
|---|---|
| **Terminal** | The command window on your Mac. Every `./…` or `python3 …` line below is typed there, from the repository folder |
| **Connect admin website** | Where you manage Amazon Connect: AWS console → Amazon Connect → your instance → **Log in for emergency access** (or your usual sign-in link) |
| **Flow** | A diagram in Connect (**Routing → Flows**) that decides what happens to a call or chat. Made of **blocks** joined by arrows |
| **Publish** | Makes your saved changes live. **Save** alone does not |
| **AI agent / AI prompt** | ARIA's brain and instructions, under **AI agent designer** in the Connect admin website. Each **Publish** makes a new numbered **version**, and flows name the version they use |
| **Agentic CX designer** | Where the card dispute assistant is built (AWS console → Amazon Connect → your instance → **agentic CX designer**) |
| **Data request** | One of the assistant's tools: a call to the dispute service |
| **Screen pop** | What the adviser sees when the call or chat arrives |

---

## 3. Before you start

Check each of these. If one isn't true, stop and sort it out first.

- [ ] **The code.** In Terminal, go to the repository folder and run:
  ```bash
  git checkout feature/dispute-agents && git pull
  ```
- [ ] **The AWS CLI works** for account `395402194296`. Test it:
  ```bash
  aws sts get-caller-identity --query Account --output text
  ```
  It should print `395402194296`.
- [ ] `python3`, `zip`, `curl` and `npm` are installed (`npm -v` prints a number).
- [ ] The **agent-assist** screen pop already works (from `connect-agent-assist`).
- [ ] The **mortgage Live Sync assistant** works in agentic CX designer, in workspace `ariaworkspace`.
- [ ] An adviser account can take contacts from the fraud and cards queues.

---

## Set it up

### Step 1 — Run the automatic tests (2 minutes, optional)

```bash
python3 -m unittest discover -s connect-card-dispute/tests
python3 -m unittest discover -s connect-agent-assist/tests
```

✅ **Worked if:** both end with `OK`. They don't touch AWS.

### Step 2 — Deploy the dispute service (5 minutes)

```bash
./connect-card-dispute/scripts/deploy_card_dispute.sh
```

This updates the Lambda `aria-card-dispute`, its database table and web address, lets Connect
call it from a flow, and updates the agent-assist tool. Want to see what it would do first? Add
`--dry-run` to the end.

✅ **Worked if:** it ends with `Done` and green ✓ lines for every test, including "The hand-back
call works" and "The CX designer door is up". **Copy these two lines** somewhere; you need them in
step 6:

```
  Data request address : https://…/acxd/ops
  Its key              : Secrets Manager secret aria-card-dispute/acxd-key
```

❌ **If it stops with a red message,** the message says what's wrong (most often: not signed in to
AWS, so redo the check in "Before you start").

### Step 3 — CloudFront in front of the form pages (15 minutes, optional)

```bash
./connect-card-dispute/scripts/deploy_pages_cloudfront.sh
```

Gives the form one tidy `https://….cloudfront.net` address and makes it load faster. Skip it if
you like; the form works without it.

✅ **Worked if:** it prints the CloudFront address and says the page loads there.

### Step 4 — Let the adviser's screen pop read disputes (3 minutes)

```bash
./connect-agent-assist/scripts/deploy_agent_assist.sh
```

✅ **Worked if:** you see the line `Card dispute service: aria-card-dispute`.

### Step 5 — Switch on texting for phone calls (20 minutes, optional)

On chat, the form link is posted in the chat, so nothing is needed here for chat. On a phone call
the link is texted; without this step the assistant says it can't text the form and carries on by
voice.

1. AWS console → search **End User Messaging** → open **AWS End User Messaging SMS**. Check the
   region at the top right is **Europe (London) eu-west-2**.
2. Get a sender that can text UK mobiles: **Phone numbers** → **Request originator** (or a
   **Sender ID**). Follow the screens; check there what the UK requires for the type you choose.
3. A new account is in the **SMS sandbox**: it only texts numbers you've verified. Go to
   **Destination phone numbers** → **Add destination phone number**, enter the mobile you'll test
   from, and enter the code it receives.
4. Open your new sender and copy its **ARN** (it starts `arn:aws:sms-voice:`).
5. Run step 2 again with it:
   ```bash
   ./connect-card-dispute/scripts/deploy_card_dispute.sh --sms-from <the ARN> --bank-name "Your bank"
   ```

✅ **Worked if:** the "Deploying with" section says `Form link texts from: arn:aws:sms-voice:…`.
The setting is remembered on later runs. Texts go only to UK mobiles (`+447…`).

Before real customers use it, request **production access** in the same console, so it can text
any number.

### Step 6 — Build the assistant in agentic CX designer (about 2 hours)

Follow **[acxd/disputes-assistant.md](acxd/disputes-assistant.md)** from top to bottom. It's
click-by-click and gives every value to paste: 1 new context variable (the other six already exist
from your mortgage build), 1 Secret, 7 Data requests, 2 flows and the application.

Three things matter most. That guide explains each one:

- the **opening** before the assistant node, so the assistant speaks first;
- **`contactId` chosen as a Variable** in every tool, never typed;
- the application's **voice set to Amy, English (UK)**, so callers hear one voice.

✅ **Worked if:** the application `Card dispute` shows **Live**, and you've written down its
**application ID**, **alias**, **deployment key** and **API key**.

### Step 7 — Give the form page its Live Sync keys (5 minutes)

This lets the assistant see what the customer types on the form.

1. AWS console → **Secrets Manager** → **Store a new secret**.
2. Choose **Other type of secret**. Add two rows under **Key/value**:
   - key `deploymentKey`, value: the deployment key from step 6;
   - key `apiKey`, value: the API key from step 6.
3. **Next**. Secret name: `aria-card-dispute/touchpoint`, exactly. **Next**, **Next**, **Store**.
4. Run step 2 again: `./connect-card-dispute/scripts/deploy_card_dispute.sh`

✅ **Worked if:** it says `Live Sync keys found: aria-card-dispute/touchpoint`.

### Step 8 — Add the "Card dispute assistant" flow to Connect (10 minutes)

**8a. Make the flow file.** In Terminal, using the ID and alias from step 6:

```bash
python3 connect-card-dispute/flows/build_card_dispute_flow.py --application-id <application ID> --alias <alias>
```

✅ It prints `Wrote …/card-dispute-flow.json (7 blocks)`.

**8b. Import it.**

1. Connect admin website → **Routing** → **Flows** → **Create flow**.
2. At the top right, click the small arrow next to **Save** → **Import flow** → choose
   `connect-card-dispute/flows/card-dispute-flow.json` → **Import**.
3. Click the flow's name at the top left and change it to `Card dispute assistant`.
4. Check three blocks. Click each one to open it:
   - **Set contact attributes** (first): one attribute, `disputeChannel`, set from **System →
     Channel**.
   - **Agentic CX**: shows the `Card dispute` application and its environment, and five context
     variables. If it says "choose an application", pick `Card dispute` and its environment now.
   - **AWS Lambda function**: shows `aria-card-dispute` and three parameters.
5. **Save**, then **Publish**.

✅ **Worked if:** the flow publishes with no error. Yellow warnings before saving are normal.

### Step 9 — Give ARIA its hand-over tool and new instructions (20 minutes)

**9a. The tool.**

1. Connect admin website → **AI agent designer** → **AI agents** → open `my-conversation-agent`.
2. **Edit**. Scroll to **Tools** → **Add tool** → **Create new AI Tool**.
3. **Tool name**: `StartCardDispute`. Type it exactly, with the capital letters; the bot flow
   compares it letter for letter.
4. **Tool type**: **Return to Control**.
5. **Input schema**: open
   [acxd/connect-ai-agent/StartCardDispute.schema.json](acxd/connect-ai-agent/StartCardDispute.schema.json),
   copy all of it, paste.
6. **Instructions**, paste:
   ```
   Use when a verified customer wants to dispute a card payment or does not recognise one. Put
   everything they have already said about the payment in handoverSummary.
   ```
7. **Examples**, paste (keep the tags):
   ```
   <message>Let's sort that out for you.</message>
   ```
8. **Create**. Don't publish yet.

**9b. The instructions (prompt).** In Terminal:

```bash
python3 connect-card-dispute/scripts/build_aria_prompt.py --mode cx
```

✅ It prints `Wrote …/aria-orchestration-prompt-with-disputes.yaml` and a size under 100,000
characters. It only reads from AWS; it changes nothing.

1. **AI agent designer** → **AI prompts** → open `ARIA-Banking-Ochestration-Prompt`.
2. Select all the text and copy it into a file on your desktop. **That's your backup.**
3. **Edit**. Delete all the text and paste the whole of
   `connect-card-dispute/prompts/aria-orchestration-prompt-with-disputes.yaml`.
4. Check the very first line is exactly `system: |`.
5. **Save**, then **Publish**.

**9c. Publish ARIA.**

1. Back in `my-conversation-agent` → **Edit**: under the prompt, choose the version you just
   published.
2. **Save**, then **Publish**.
3. **Write down the new version number**. Today's live one is 26, so expect 27.

### Step 10 — Send ARIA's hand-over to the new flow (15 minutes)

All of this is in the flow **conversation bot flow** (Connect admin website → **Routing** →
**Flows**). It works the same for phone and chat.

**10a. Add the branch.**

1. Find the **Check contact attributes** block that checks **Namespace: Lex**, session attribute
   **`Tool`**. It sits after **Get customer input** and already has branches for `Escalate`,
   `Complete` and `StartMortgageApplication`.
2. Open it → **Add another condition** → **Equals** → type `StartCardDispute` → **Save**. A new
   output called `StartCardDispute` appears on the block.

**10b. Copy what ARIA was told onto the contact.**

1. From the block library on the left, drag a **Set contact attributes** block onto the canvas.
2. Drag an arrow from the new `StartCardDispute` output to it.
3. Open it and add two attributes. Choose **Add another attribute** for the second.

   | Destination key | How | Value |
   |---|---|---|
   | `handoverSummary` | **Set dynamically**, Namespace **Lex**, Key **Session attributes** | `handoverSummary` |
   | `entry` | **Set manually** | `aria` |

4. **Save**.

**10c. Transfer to the dispute flow.**

1. Drag a **Transfer to flow** block onto the canvas. Open it, choose `Card dispute assistant`,
   **Save**.
2. Draw arrows from the Set contact attributes block's **Success** and **Error** to it.
3. Draw an arrow from the Transfer to flow block's **Error** to the nearby **Disconnect** block.

**10d. Use ARIA's new version (from step 9c), everywhere this flow names it.**

1. Every **Connect assistant** block that shows `my-conversation-agent` (today only the first one,
   after **Set language**): open it, choose the new version, **Save**.
2. The **Get customer input** block → **Session attributes** → `x-amz-lex:q-in-connect:ai-agent-arn`.
   Its value ends `…:26`. Change only that last number to the new version, for example `:27`.
   **Save**.
3. If step 6 used a voice other than Amy: the **Set voice** block near the top, choose the same
   voice.

**10e.** **Save**, then **Publish** the flow.

✅ **Worked if:** it publishes without errors. Click **Save** first if Publish is greyed out.

### Step 11 — The adviser's side (15 minutes)

**11a. The new screen pop.**

1. **Routing** → **Flows** → open `ARIA-Agent-Screen-Pop-Flow`.
2. Arrow next to **Save** → **Export flow**. Keep the file. **That's your backup.**
3. Arrow next to **Save** → **Import flow** →
   `connect-agent-assist/flows/aria-agent-screen-pop-flow.json`.
4. **Save**, then **Publish**.

✅ The **Card dispute** view (open it in the flow to look) now lists six lines, `dispute1` to
`dispute6`.

**11b. Let the adviser's assistant read disputes (optional).**

1. **AI agent designer** → **AI agents** → `my-agent-assistant-agent` → **Edit** → **Add tool** →
   choose `aria_banking_dispute___get_card_dispute` (only this one) → **Save** → **Publish**.
   Write down the version.
2. **AI prompts** → `agent-briefing-prompt` → **Edit**: replace the text with
   [agent-briefing-prompt-v1.yaml](../connect-agent-assist/prompts/agent-briefing-prompt-v1.yaml)
   → **Save** → **Publish**.
3. **AI agents** → `my-agent-briefing-agent` → **Edit**: add the same tool, choose the new prompt
   version → **Save** → **Publish**. Write down the version.
4. **Routing** → **Flows** → `ARIA agent assist`. Update the version numbers in three places: the
   **Connect assistant** block, and on the **AWS Lambda function** block the parameters
   `assistAgentArn` and `briefingAgentArn` (change the number at the end). **Save**, **Publish**.

> If `get_card_dispute` isn't in the tool list: Connect keeps its own copy of the gateway's tools.
> Note the tools the agent has, remove the `aria-mcp-agentcore-gateway-server` integration, add it
> back, and re-select them.

🎉 **Set-up is done.** Now test it.

---

## Test it

You need: a phone (the mobile you verified in step 5, if texting is on), a browser for chat, and an
adviser signed in to the agent workspace and set to **Available**.

### Test 1 — Phone: a payment the customer didn't make

| # | Who | Do | You should see / hear |
|---|---|---|---|
| 1 | Customer | Ring ARIA as James: "I don't recognise a payment on my debit card" | ARIA checks you, then one short sentence. No "transferring" |
| 2 | Customer | Listen | The **same voice** asks about the payment, without asking what you've already said |
| 3 | Customer | "The Amazon one, about ninety pounds. I still have my card." | It names the payment back, or asks whether you made it |
| 4 | Customer | "No, I didn't make it" | It offers to block the card |
| 5 | Customer | "Yes please", then yes to a replacement | It says the replacement arrives in 3 to 5 working days |
| 6 | Customer | Listen | It offers to share the form |
| 7 | Customer | "Yes" | A text arrives. It says "the mobile ending …", never the full number |
| 8 | Customer | Open the link in the text | The form, filled in so far, and "Connected to your call" |
| 9 | Customer | Answer its questions; type a sentence into "what happened" yourself | Fields fill as you speak; your typing stays |
| 10 | Customer | Agree when it sums up | "A colleague will now check the form with you…", then "Please wait while I connect you…" |
| 11 | Adviser | Accept the call | Screen pop **Card dispute**: the payment, **Cards:** blocked and replacement ordered, the note, a link |
| 12 | Adviser | Open the link and change a field | The customer's form becomes read-only and shows the change |
| 13 | Customer | Press **These details are correct** | The adviser page shows the confirmation |
| 14 | Adviser | **Submit dispute** | Both pages show "Submitted" and the reference |

### Test 2 — Chat: the same, in writing

1. Start a chat with ARIA the way you normally test ARIA on chat: your chat widget, or **Test
   chat** in the Connect admin website (**Test settings** → choose `conversation bot flow` →
   **Apply**).
2. Type "I want to dispute a card payment", and verify yourself as James when ARIA asks.

| # | You should see |
|---|---|
| 1 | ARIA replies with one short sentence, then the assistant's question about the payment, in the same chat |
| 2 | It blocks and replaces the card only after you type yes |
| 3 | When you say you'd like to see the form, **a link appears in the chat**. Nothing is texted |
| 4 | Opening it shows the form, joined to the chat, filling in as you type in the chat |
| 5 | At the end, the chat goes to an adviser, whose screen pop says the link was "posted in the chat" |

### Test 3 — Phone, without the form

Ring as James, dispute the Tesco payment: "I was charged twice". When it offers the form, say no.
The call goes to the queue the routing table gives `debit_card`, not to Fraud. On the adviser page,
tick "The customer confirmed these details to me on this contact", then submit.

### Test 4 — The safety rules hold

- Ask the assistant to submit the dispute: it can't, and says a colleague will.
- Ask for the form a fourth time: it says it can't share it again.
- On the adviser page, press **Submit** before the customer has confirmed: refused.

### Where to look when something goes wrong

| Where | What it shows |
|---|---|
| CloudWatch → Log groups → `/aws/lambda/aria-card-dispute` | One line per tool call, e.g. `outcome=blockCard:ok` or `op=handover … topic=fraud_security`. Never customer details |
| CloudWatch → `/aws/connect/<your instance alias>`, search the contact ID | Every flow block the call or chat went through |
| Agentic CX designer → the application → **Test** → **Debugger** | What the assistant decided and which tools it called |

---

## Troubleshooting

| What you see | Most likely cause, and the fix |
|---|---|
| ARIA tries to handle the dispute itself | ARIA isn't on the new version. Check step 9 (prompt and agent published) and 10d (both places) |
| ARIA says its sentence, then silence | The assistant's opening is missing or not connected: disputes-assistant.md Part 3b, steps 2 to 5 |
| The call or chat ends after ARIA's sentence | The `StartCardDispute` branch (10a to 10c) is missing or not connected, or the Agentic CX block has no application (8b) |
| A different voice after ARIA | The CX designer application's voice: disputes-assistant.md Part 4, step 3 |
| The assistant says it can't find anything about you | Every Data request answered `customer_not_identified`: `contactId` isn't chosen as a **Variable** (Part 3b, step 7), or ARIA hadn't verified you |
| Data requests answer `401` | The CX designer Secret doesn't match `aria-card-dispute/acxd-key`: Part 2b again |
| Phone: "I can't share the form right now" | Look in the Lambda log for `sendFormLink:`. `sms_not_configured` = step 5 not done; `no_mobile_number` = not calling from a UK mobile; `sms_failed` = sandbox (verify the number) or the sender can't text it |
| Chat: no link appears | The log shows `sendFormLink:ok` but no link was posted: the prompt's "On CHAT" rule (Part 3b, step 6) |
| The form opens but doesn't change | It updates every two seconds from what's saved. Check the log for `updateDispute:ok` |
| Adviser sees "the hand-over summary could not be built" | Connect couldn't call the Lambda. Run step 2 again, then check the Lambda block (8b) |
| The screen pop is the usual one, no dispute | No dispute was started (the summary says "Card dispute not drafted"), or step 4 wasn't run |

---

## How to undo it

| To undo | Do |
|---|---|
| ARIA's dispute hand-over | In `conversation bot flow`, put version 26 back in both places (10d) and publish |
| The screen pop | Import the backup from 11a and publish |
| ARIA's prompt | Paste the backup from 9b, publish, and choose that version in the agent |
| Texting | Lambda console → `aria-card-dispute` → **Configuration** → **Environment variables** → remove `SMS_ORIGINATION_IDENTITY`. Later runs of step 2 leave it off |
| The whole dispute service | Delete the gateway target `aria-banking-dispute`, the HTTP API `aria-card-dispute-pages`, the Lambda `aria-card-dispute`, its role `aria-lambda-card-dispute-role` and the table `aria-card-disputes`. Then run step 4 again |

---

## What is in this folder

| Path | What it is |
|---|---|
| [SPEC.md](SPEC.md) | The design, the rules the code enforces, the known gaps. Part 4 is this design |
| [acxd/disputes-assistant.md](acxd/disputes-assistant.md) | Step 6: everything to build in agentic CX designer |
| [flows/build_card_dispute_flow.py](flows/build_card_dispute_flow.py) | Step 8: writes the Connect flow `card-dispute-flow.json` |
| [lambda/](lambda/) | The Lambda. `dispute_service.py` holds the rules; `dispute_web.py` the assistant's tools |
| [web/](web/) | The customer's form page and the adviser's page |
| [scripts/deploy_card_dispute.sh](scripts/deploy_card_dispute.sh) | Step 2 |
| [scripts/deploy_pages_cloudfront.sh](scripts/deploy_pages_cloudfront.sh) | Step 3 |
| [scripts/build_aria_prompt.py](scripts/build_aria_prompt.py) | Step 9b |
| [prompts/card-disputes-cx-designer-block.txt](prompts/card-disputes-cx-designer-block.txt) | The section added to ARIA's prompt |
| [acxd/connect-ai-agent/StartCardDispute.schema.json](acxd/connect-ai-agent/StartCardDispute.schema.json) | Step 9a |
| [tests/](tests/) | Step 1 |

---

## Earlier designs

Two earlier designs are still in the code, and neither is used:

- **ARIA drafts the dispute itself** with five gateway tools (`build_aria_prompt.py --mode direct`).
- **An in-instance disputes agent** attached to ARIA (`--mode agents`,
  `attach_disputes_collaborator.sh`). The AI agent `card-disputes-agent` made for it isn't attached
  to ARIA (checked: ARIA has no collaborator). You can leave it or delete it.

Their setup steps are in this README's history at commit `35a43f2`; SPEC.md Parts 1 to 3 explain
them.
