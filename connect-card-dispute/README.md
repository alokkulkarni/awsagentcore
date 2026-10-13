# Card Transaction Disputes — Setup Guide

A customer tells ARIA they want to dispute a card payment. ARIA fills in the dispute form as far as
it can and passes the contact to an adviser. The adviser checks the form with the customer and
submits it. The customer can watch the form on their own screen the whole time.

This guide assumes you have not done this before. Follow the parts in order.

> **Read [SPEC.md](SPEC.md) section 0 first** if you expected this to work like the mortgage Live
> Sync page. It looks similar to the customer, but it is built differently, and the spec says why.

> **Nothing here has been tried on a live contact yet.** The code has unit tests only. The first real
> call is the test of everything else. Each part says what to check.

## Table of Contents

- [1. How it works](#1-how-it-works)
- [2. What is in this folder](#2-what-is-in-this-folder)
- [3. Before you start](#3-before-you-start)
- [Part A — Run the tests on your laptop](#part-a--run-the-tests-on-your-laptop)
- [Part B — Deploy](#part-b--deploy)
- [Part C — Give ARIA the dispute tools](#part-c--give-aria-the-dispute-tools)
- [Part D — Update ARIA's prompt](#part-d--update-arias-prompt)
- [Part E — Give the agent-assist agents the read-only tool](#part-e--give-the-agent-assist-agents-the-read-only-tool)
- [Part F — Import the new screen pop](#part-f--import-the-new-screen-pop)
- [Part G — Test it](#part-g--test-it)
- [Part H — Route 1: a disputes agent that takes over from ARIA](#part-h--route-1-a-disputes-agent-that-takes-over-from-aria)
- [Part J — Route 3: the form fills in on the customer's screen (Live Sync)](#part-j--route-3-the-form-fills-in-on-the-customers-screen-live-sync)
- [Troubleshooting](#troubleshooting)
- [How to undo it](#how-to-undo-it)

---

## 1. How it works

There is **one record** for each dispute, kept in a database table. Three things read and write it:

| Who | How | What they can do |
|---|---|---|
| **ARIA** | Five tools | Find the transaction, start a draft, fill in fields. Never confirm, never submit |
| **The adviser** | A web page opened from the screen pop | Change any field, record the customer's confirmation, submit |
| **The customer** | A web page | Watch the form, and press one button: "These details are correct" |

**The first question decides the route.** ARIA asks: "Did you make or authorise this payment
yourself?"

- **No** → an *unauthorised* dispute → the **Fraud Team**. ARIA also offers to block the card.
- **Yes, but something went wrong** → a *merchant* dispute → the **Cards Team**.

**How the customer's page gets the right dispute.** The customer opens the page and it shows a
six-digit code. They read the code to ARIA. ARIA passes it to a tool, and the dispute appears on
that page. The code goes from the page to the call, never the other way, so a code on its own shows
nothing to anyone. This step is optional: a customer with no screen gets the same service.

**How the adviser gets the form.** When the contact arrives, the screen pop shows a "Card dispute"
view with a summary and a link, **Open the dispute form**. The link works for 60 minutes.

---

## 2. What is in this folder

| Path | What it is |
|---|---|
| [SPEC.md](SPEC.md) | The design, the rules the code enforces, and the known gaps. Part 3 covers the two routes in Parts H and J |
| [acxd/](acxd/) | Everything to paste into the CX designer for the Live Sync route (Part J) |
| [flows/](flows/) | The hand-over flow for the Live Sync route |
| [lambda/](lambda/) | The Lambda. `dispute_service.py` holds every rule |
| [web/](web/) | The customer page and the adviser page |
| [scripts/deploy_card_dispute.sh](scripts/deploy_card_dispute.sh) | Deploys everything in AWS that this feature needs |
| [scripts/tool_schemas.json](scripts/tool_schemas.json) | The five tools, as ARIA sees them |
| [scripts/build_aria_prompt.py](scripts/build_aria_prompt.py) | Builds ARIA's new prompt from the one that is live today |
| [prompts/card-disputes-block.txt](prompts/card-disputes-block.txt) | The instructions added to ARIA's prompt |
| [tests/](tests/) | Unit tests |

---

## 3. Before you start

- The agent-assist work in [connect-agent-assist/](../connect-agent-assist/) is deployed and working
  (its screen pop shows the arrival briefing).
- You can run the AWS CLI against account `395402194296`.
- The routing table `aria-routing-config` has rows for `fraud_security`, `debit_card` and
  `credit_card`. It does today.
- An adviser is in a routing profile that serves the **Fraud Security Queue** (for unauthorised
  disputes) and the Cards queues (for the other kind).

---

## Part A — Run the tests on your laptop

```bash
python3 -m unittest discover -s connect-card-dispute/tests
python3 -m unittest discover -s connect-agent-assist/tests
```

Both should end with `OK`. They need no AWS access.

---

## Part B — Deploy

Two scripts, in this order.

**1. The dispute service.**

```bash
./connect-card-dispute/scripts/deploy_card_dispute.sh
```

It creates the table, the Lambda `aria-card-dispute`, a web address for the two pages, and the
gateway target `aria-banking-dispute` with the five tools. Then it tests a tool call and the
customer page. Add `--dry-run` first if you want to see what it would do.

At the end it prints the **customer page** address. Keep it: you open it in Part G.

**2. The agent-assist Lambda, again.**

```bash
./connect-agent-assist/scripts/deploy_agent_assist.sh
```

It notices the dispute service now exists and lets the screen pop ask it about a customer's
dispute. You should see the line `Card dispute service: aria-card-dispute`.

> **To send every dispute to the Fraud Team**, including payments the customer did make, run the
> first script with `--merchant-topic fraud_security`.

---

## Part C — Give ARIA the dispute tools

1. Connect admin website → **AI agent designer** → **AI agents** → `my-conversation-agent` → **Edit**.
2. Under **Tools**, choose **Add tool** and add all five from the `aria-mcp-agentcore-gateway-server`
   integration:

| Tool | ARIA uses it to |
|---|---|
| `aria_banking_dispute___list_card_transactions` | Find the transaction |
| `aria_banking_dispute___start_card_dispute` | Start the draft |
| `aria_banking_dispute___update_card_dispute` | Fill in answers |
| `aria_banking_dispute___get_card_dispute` | Read it back |
| `aria_banking_dispute___attach_dispute_screen` | Show it on the customer's screen |

3. Leave each tool's instruction field empty.
4. **Do not publish yet.** Part D changes the prompt, and you publish once after that.

> **If the five tools are not offered:** Connect keeps its own copy of a gateway's tool list. Remove
> the `aria-mcp-agentcore-gateway-server` integration from the agent, add it again, and re-select
> the tools the agent had before. Note them down first.

---

## Part D — Update ARIA's prompt

**1. Build the new prompt.** This reads the prompt that is live in your instance and adds the
dispute section to it. It changes nothing in AWS.

```bash
python3 connect-card-dispute/scripts/build_aria_prompt.py
```

It writes `connect-card-dispute/prompts/aria-orchestration-prompt-with-disputes.yaml` and tells you
the size. It refuses to write a prompt Connect would reject (over 100,000 characters, or more than
19 custom variables).

**2. Paste it.**

1. **AI agent designer** → **AI prompts** → `ARIA-Banking-Ochestration-Prompt`.
2. Select all the existing text and save a copy somewhere as a backup.
3. **Edit** (or **Create new version**), and replace the whole text with the file from step 1.
4. Check the first line is exactly `system: |`.
5. **Save**, then **Publish**. Note the new prompt version.

**3. Publish the agent.**

1. Back in `my-conversation-agent` → **Edit**, set the prompt to the version you just published.
2. **Save**, then **Publish**. Note the new **agent version**.

**4. Point the bot flow at the new agent version.** ARIA's agent version is named in two places in
`conversation bot flow`:

1. **Routing** → **Flows** → `conversation bot flow`.
2. The **first Connect assistant block**: choose the new version of `my-conversation-agent`.
3. The **Get customer input** (Lex) block: in its session attributes, find
   `x-amz-lex:q-in-connect:ai-agent-arn` and change the number at the end of its value to the new
   version.
4. **Save**, then **Publish**.

---

## Part E — Give the agent-assist agents the read-only tool

The adviser's assistant can then tell them what a dispute still needs.

1. **AI agents** → `my-agent-assistant-agent` → **Edit** → **Add tool** →
   `aria_banking_dispute___get_card_dispute`. Add only this one. **Save**, **Publish**, note the
   version. Its prompt is not changed: the tool's own description tells the assistant when to use it.
2. **AI prompts** → `agent-briefing-prompt`: paste the updated
   [agent-briefing-prompt-v1.yaml](../connect-agent-assist/prompts/agent-briefing-prompt-v1.yaml),
   **Save**, **Publish**. It now reads the dispute itself when the handover is a card dispute.
3. **AI agents** → `my-agent-briefing-agent` → **Edit**: add the same tool, choose the new prompt
   version, **Save**, **Publish**, note the version.
4. In the flow `ARIA agent assist`, update the version number in three places: the **Connect
   assistant** block, and the `assistAgentArn` and `briefingAgentArn` parameters on the **AWS Lambda
   function** block. **Save**, then **Publish**.

This part is optional. Without it the screen pop still shows the dispute; only the assistant's own
answers about it are missing.

---

## Part F — Import the new screen pop

1. **Routing** → **Flows** → `ARIA-Agent-Screen-Pop-Flow`.
2. Arrow next to **Save** → **Export flow**, and keep the file as your way back.
3. Arrow next to **Save** → **Import**, and select
   `connect-agent-assist/flows/aria-agent-screen-pop-flow.json`.
4. Check no block shows a warning. There are now eight blocks, including a second **Check contact
   attributes** block (it tests whether the customer has a dispute) and a **Card dispute** view.
5. **Save**, then **Publish**.

---

## Part G — Test it

You need a phone, an adviser logged in to the agent workspace and **Available**, and a browser tab
for the customer page.

### Test 1 — A payment the customer did not make, with the screen

| Step | Who | Do | Expect |
|---|---|---|---|
| 1 | Customer | Open the customer page from Part B in a browser | A six-digit code |
| 2 | Customer | Ring ARIA as James. Say "I want to dispute a card payment" | ARIA asks which payment |
| 3 | Customer | "The Amazon one, eighty-nine ninety-nine" | "Did you make or authorise this payment yourself?" |
| 4 | Customer | "No" | ARIA asks whether you still have the card, then offers to block it |
| 5 | Customer | Answer, and say what happened in a sentence | ARIA offers the screen |
| 6 | Customer | Read out the code on the page | The page changes to the form, already filled in |
| 7 | Customer | Confirm when ARIA reads it back | "I'm passing you to a colleague…" |
| 8 | Adviser | Accept the contact | Screen pop headed **Card dispute**, with a summary and a link |
| 9 | Adviser | Open the link. Change the wording of what happened | The customer's page shows the new wording within a few seconds, tagged "Adviser" |
| 10 | Customer | Press **These details are correct** | The adviser page says the customer has confirmed, and **Submit** becomes available |
| 11 | Adviser | **Submit dispute** | Both pages show "Submitted" and the reference |

### Test 2 — A payment the customer made, without the screen

Ring as James, dispute the Tesco payment, answer "Yes, but I was charged twice." Decline the screen.
Tesco is on James's debit card, so the contact goes to whichever queue the routing table gives
`debit_card` (today that row points at the current-account queue), not to Fraud. On the adviser page, tick "The customer
confirmed these details to me on this contact", then submit.

### Test 3 — The rules hold

- On the adviser page, press **Submit** before the customer has confirmed: it is refused.
- After the adviser has opened the form, ring ARIA again and ask to change the dispute: ARIA cannot,
  and hands over.
- Read ARIA a wrong code: nothing attaches. Five wrong codes and the page can no longer be attached
  to that dispute.

### Where to look when something is wrong

| Log group | Shows |
|---|---|
| `/aws/lambda/aria-card-dispute` | One line per tool call or page request: the operation, the outcome and the dispute reference. Never the content |
| `/aws/lambda/aria-agent-assist-injector` | `briefing_read` each time a screen pop opens |
| `/aws/connect/conversationalbot` | Which blocks each flow ran |

---

## Part H — Route 1: a disputes agent that takes over from ARIA

Parts C and D put the whole dispute procedure inside ARIA. This part moves it into a second AI
agent, which makes ARIA's prompt shorter and its tool list smaller. Do Parts A to G first and get
one dispute through on a live call; then switch to this.

**What the customer hears:** no difference. The disputes agent speaks as ARIA, in the same voice,
and neither agent announces the hand-off. Confirming that on a real call is step H.6.

**Before you start:** your Connect instance must be on the **Connect Customer** tier. If it is not,
step H.4 fails with a message saying so, and nothing changes.

### H.1 Create the disputes agent's prompt

1. **AI agent designer** → **AI prompts** → **Create AI prompt**. Type **Orchestration**. Name
   `card-disputes-agent-prompt`. Model: the same as ARIA's (Claude Sonnet 4.5).
2. Paste the whole of [prompts/disputes-agent-prompt-v1.yaml](prompts/disputes-agent-prompt-v1.yaml).
3. **Save**, then **Publish**.

### H.2 Create the disputes agent

1. **AI agents** → **Create AI agent**. Type **Orchestration**. Name `card-disputes-agent`.
   Locale English (UK). Prompt: the version from H.1.
2. Add these tools, and no others:

| Tool | Why |
|---|---|
| The five `aria_banking_dispute___…` tools | To draft the dispute |
| `aria_banking_debit_card___block_debit_card`, `aria_banking_credit_card___block_credit_card` | To block the card when asked |
| `Escalate` | To give the conversation back to ARIA when the dispute is drafted |
| `Complete` | To give it back when the customer changes the subject |

   `Escalate` and `Complete` are required: without them the agent cannot hand the conversation back,
   and the script in H.4 refuses to attach it.
3. **Save**, then **Publish**. Copy the agent's **ID**: the last part of its ARN, shown on its page.

### H.3 Give ARIA its shorter dispute section

```bash
python3 connect-card-dispute/scripts/build_aria_prompt.py --mode agents
```

Paste the file it writes into `ARIA-Banking-Ochestration-Prompt`, **Save** and **Publish**, as in
Part D step 2. Then in `my-conversation-agent`:

1. Choose the new prompt version.
2. **Remove** the five `aria_banking_dispute___…` tools. The disputes agent has them now.
3. **Save**. Do not publish from the console: the script in H.4 publishes.

### H.4 Attach the disputes agent to ARIA

There is no console screen for this, so it is a script:

```bash
./connect-card-dispute/scripts/attach_disputes_collaborator.sh --collaborator-agent-id <ID from H.2>
```

Add `--dry-run` first to see the change. The script reads ARIA as it is, saves a copy in
`connect-card-dispute/backups/`, adds the disputes agent as a collaborator, and publishes a new
version of ARIA. It prints the version number.

### H.5 Point the bot flow at the new ARIA version

The script prints these steps with the right number. They are the same three places as Part D
step 4: both **Connect assistant** blocks and the Lex block's `x-amz-lex:q-in-connect:ai-agent-arn`.

### H.6 Test

Ring ARIA and ask to dispute a card payment. Say you have no screen to hand.

| Check | What you should find |
|---|---|
| The voice | The same throughout. No "I'm passing you to…" until the dispute is drafted |
| The questions | ARIA does not ask twice for something you already said |
| The end | One line about a colleague, then the transfer. No goodbye, no second greeting |
| The screen pop | The same **Card dispute** view as before |

If the customer's ID or verification level did not reach the disputes agent, it hands straight back
without drafting anything and the adviser's summary begins "Card dispute not drafted". Say so if
that happens: it means the collaborator does not receive ARIA's session values, and the fix is in
the prompts.

**To undo:** point the bot flow back at the previous ARIA version. To remove the collaborator
altogether, run the script with `--remove`.

---

## Part J — Route 3: the form fills in on the customer's screen (Live Sync)

When the customer has the card dispute page open and reads its code to ARIA, the call is handed to
a CX designer assistant that fills the form on their screen as they talk. This is the same
technology as your mortgage application. It is optional, and it is the largest piece to set up.

**What you need already working:** Parts A to G, and the mortgage Live Sync application, because
this reuses its workspace and you will recognise every screen.

### J.1 Deploy

```bash
./connect-card-dispute/scripts/deploy_card_dispute.sh
```

Run it again even if you ran it before. It now also needs `npm` (it fetches Amazon's Touchpoint
library for the page), creates a key for the CX designer in Secrets Manager, and prints a new
section:

```
For the Live Sync route (README Part J):
  CX designer tool address : https://…/acxd/ops
  Its key                  : Secrets Manager secret aria-card-dispute/acxd-key
```

### J.2 Build the assistant in the CX designer

Follow [acxd/live-sync-node.md](acxd/live-sync-node.md) from top to bottom. It lists every value:
nine context variables, one Secret, one Data request, a hand-off flow, the main flow's prompt and
exits. Build, test and deploy the application, and note its **deployment key** and **API key**.

### J.3 Give the page its Live Sync keys

1. AWS console → **Secrets Manager** → **Store a new secret** → **Other type of secret**.
2. Two key/value rows: `deploymentKey` and `apiKey`, with the values from J.2.
3. Name it exactly `aria-card-dispute/touchpoint`. Create it.
4. Run the deploy script once more. It should now say `Live Sync keys found`.

### J.4 Import the hand-over flow

```bash
python3 connect-card-dispute/flows/build_livesync_handover_flow.py --application-id <id> --alias <alias>
```

Leave the two options off if you do not know them; you then choose the application in the block.

1. **Routing** → **Flows** → **Create flow** (inbound) → **Import** →
   `connect-card-dispute/flows/card-dispute-livesync-handover-flow.json`.
2. Name it `Card dispute Live Sync handover`.
3. Open the **Agentic CX** block and check it shows your workspace, the `Card dispute` application
   and its environment, and six context variables.
4. **Save**, then **Publish**.

### J.5 Give ARIA the hand-over tool

1. `my-conversation-agent` → **Edit** → **Add tool** → **Create new AI Tool**.
2. Name `StartCardDispute`, exactly. Type **Return to Control**.
3. Input schema: paste
   [acxd/connect-ai-agent/StartCardDispute.schema.json](acxd/connect-ai-agent/StartCardDispute.schema.json).
4. Instructions:
   ```
   Use only when the customer wants to dispute a card payment AND has read out the 6-digit code
   shown on the card dispute page. Pass that code as screenCode, digits only.
   ```
5. Example:
   ```
   <message>Thank you. I'll fill the form in with you on your screen now.</message>
   ```
6. **Save**. ARIA's prompt from Part H step 3 (`--mode agents`) already tells it when to use this.
7. Publish ARIA. If you use route 1 as well, publish by running the attach script again instead,
   so the collaborator is kept.

### J.6 Add one branch to the bot flow

In `conversation bot flow`, find the **Check contact attributes** block that tests
`$.Lex.SessionAttributes.Tool`. It already has a branch for `StartMortgageApplication`.

1. Add a condition: **Equals** `StartCardDispute`.
2. Add a **Set contact attributes** block, and connect the new branch to it. Three attributes:

| Destination key | Value |
|---|---|
| `handoverSummary` | Set dynamically: namespace **Lex**, session attribute `handoverSummary` |
| `screenCode` | Set dynamically: namespace **Lex**, session attribute `screenCode` |
| `entry` | Set manually: `phone` |

3. Add a **Transfer to flow** block choosing `Card dispute Live Sync handover`. Connect the Set
   contact attributes block's Success **and** Error to it, and its own Error to the flow's existing
   Disconnect.
4. Point the flow at ARIA's new version (the same three places as before), **Save**, **Publish**.

The mortgage branch next to it is built the same way; copy its shape.

### J.7 Test

| Step | Who | Do | Expect |
|---|---|---|---|
| 1 | Customer | Open the customer page | A six-digit code |
| 2 | Customer | Ring ARIA: "I want to dispute a card payment" | ARIA asks whether the dispute page is open |
| 3 | Customer | Read the code | "I'll fill the form in with you on your screen now" |
| 4 | Customer | Watch the page | It changes to a form. "Connected to your call." |
| 5 | Customer | Say which payment, and that you did not make it | The dropdowns fill in on screen as you speak |
| 6 | Customer | Type something into "what happened" yourself | It is kept; the assistant carries on |
| 7 | Customer | Agree when it reads the dispute back | Hand-off to a colleague |
| 8 | Adviser | Accept | The **Card dispute** screen pop, with the link to the adviser form |
| 9 | Adviser | Change a field | The customer's page becomes read-only and shows the change |

### If route 3 misbehaves

| What you see | Likely cause |
|---|---|
| The page stays on the code | `attachToScreen` did not succeed. In `/aws/lambda/aria-card-dispute`, look for `route=/acxd/ops`: `unauthorised` is a wrong key in the CX designer Secret; `customer_not_identified` means the contact has no `customerId` attribute |
| The form appears but nothing fills in | Live Sync did not start. The page says so under the form. Check J.3, and that the deploy script said the Touchpoint library was added |
| It fills the wrong payment | The assistant chose by retailer name. Ask it for the amount or date |
| The contact drops at the hand-off | The assistant's topic was not one the routing table has. The flow falls back to `fraud_security`; check that row exists |

This route copies the pattern of the mortgage page, which needed many fixes on live calls. Expect
to find some here too, and tell me what the page and the Lambda log show.

---

## Troubleshooting

### ARIA says it cannot help with disputes
The tools are not on the agent version the bot flow uses. Check Part C, then both places in Part D
step 4. A published agent is not live until the flow names its version.

### ARIA drafts the dispute but the contact is disconnected instead of transferred
The routing table has no row for the topic ARIA used. The dispute Lambda's log shows the dispute
type; an unauthorised dispute needs a `fraud_security` row, the other kind needs `debit_card` or
`credit_card`.

### The screen pop is the ordinary handoff summary, with no dispute
- The agent-assist Lambda was not redeployed after the dispute service (Part B, step 2). Its
  settings should include `DISPUTE_FUNCTION_NAME`.
- Or the dispute is not open any more: only a draft or a dispute with an adviser is shown.

### The screen pop shows the dispute but the link does nothing
The view has two links: one in the bar at the top and one in the text. If neither opens the page,
say so. The address is correct in the dispute Lambda's reply; it is the view that is not opening it.

### The customer page stays on the code
ARIA did not attach it. Check the dispute Lambda's log for `tool=attach_dispute_screen` and its
outcome: `code_not_recognised` means the digits did not match a waiting page, or the code was more
than ten minutes old.

### The adviser page says the link cannot be used
Links last 60 minutes. Press **Refresh briefing** on the screen pop for a new one.

---

## How to undo it

Each step is separate; do only what you need.

| To undo | Do |
|---|---|
| The screen pop | Import the file you exported in Part F and publish |
| ARIA's dispute behaviour | Point `conversation bot flow` back at the previous agent version, both places, and publish |
| The assistant's tool | Point `ARIA agent assist` back at the previous agent versions |
| The dispute service | Delete the gateway target `aria-banking-dispute`, the HTTP API `aria-card-dispute-pages`, the Lambda `aria-card-dispute`, its role `aria-lambda-card-dispute-role`, and the table `aria-card-disputes`. Then run the agent-assist deploy script again |
