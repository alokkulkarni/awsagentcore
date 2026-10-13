# Card Transaction Disputes — Setup Guide

A customer tells ARIA they want to dispute a card payment. ARIA fills in the dispute form as far as
it can and passes the contact to an adviser. The adviser checks the form with the customer and
submits it. The customer can watch the form on their own screen the whole time.

This guide assumes you have not done this before. Follow the parts in order.

> **Read [SPEC.md](SPEC.md) section 0 first** if you expected this to work like the mortgage Live
> Sync page. It looks similar to the customer, but it is built differently, and the spec says why.

> **Nothing here has been tried on a live contact yet.** The code has 40 unit tests. The first real
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
| [SPEC.md](SPEC.md) | The design, the rules the code enforces, and the known gaps |
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
   version.
2. Do the same for `my-agent-briefing-agent`.
3. In the flow `ARIA agent assist`, update the version number in three places: the **Connect
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
The contact should reach the **Cards** queue, not Fraud. On the adviser page, tick "The customer
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
