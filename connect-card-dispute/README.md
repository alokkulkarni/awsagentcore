# Card Transaction Disputes — Setup Guide

A customer tells ARIA they want to dispute a card payment, or that they don't recognise one. ARIA
checks who they are and hands the call, in the same voice and without announcing it, to the **card
dispute assistant** built in the CX designer. That assistant does the whole dispute: it finds the
payment, fills the form (asking only what it doesn't already know), blocks and replaces the card if
the customer wants, and texts them the form if they want to see it. Then the call goes back through
ARIA's own human hand-over to an adviser, whose screen pop shows the dispute, any card blocked or
ordered, and a link to the form. The adviser checks it with the customer and submits it.

This guide assumes you have not done this before. Follow the steps in order: each one needs the
one before.

> **Nothing here has been tried on a live contact yet.** The code has unit tests only, and the
> CX designer and flow steps are written from your mortgage Live Sync build, which works. The first
> real call is the test of everything else. Each step says what to check.

## Table of Contents

- [1. How a call goes](#1-how-a-call-goes)
- [2. Who does what](#2-who-does-what)
- [3. What is in this folder](#3-what-is-in-this-folder)
- [4. Before you start](#4-before-you-start)
- [Set it up](#set-it-up)
- [Test it](#test-it)
- [Troubleshooting](#troubleshooting)
- [How to undo it](#how-to-undo-it)
- [Earlier designs](#earlier-designs)

---

## 1. How a call goes

```
Caller ─► ARIA (conversation bot flow)
            │  checks: verified, Level 2+, no vulnerability to handle first
            │  calls StartCardDispute with what the caller already said
            ▼
          Card dispute assistant flow ─► Agentic CX block: the CX designer "Card dispute" assistant
            │    finds the payment, fills the dispute, blocks / replaces the card,
            │    texts the form link (the form then updates on the caller's phone as they talk)
            │    reads it back, then hands back
            ▼
          Lambda aria-card-dispute "handover": team + summary, built from what was saved
            ▼
          ARIA human handover (the same flow ARIA's own escalations use) ─► adviser's queue
            ▼
          Adviser: screen pop "Card dispute" ─► opens the form ─► customer confirms ─► Submit
```

**Why the flow, not ARIA, does the transfer at the end.** When ARIA escalates, its Escalate tool
only fills in four attributes; `conversation bot flow` then runs **ARIA human handover**. The
disputes route ends on that same flow with the same four attributes, so to the adviser it *is* an
ARIA hand-over. Sending the call back into ARIA's bot just to say goodbye would leave the caller in
silence: ARIA's bot waits for the caller to speak first.

**The same voice.** ARIA hands over with one sentence such as "Let's sort that out for you", and the
assistant's first words are a question about the payment. Neither says anything about transferring.
The assistant's voice is set in the CX designer application, so it must be set to match ARIA's
(step 6).

---

## 2. Who does what

| | ARIA | Card dispute assistant | Adviser |
|---|---|---|---|
| Checks the caller is verified (Level 2+) | Yes | Checks again; the Lambda also refuses an unverified call | Own checks |
| Asks about the payment, the card, the form | Never | Yes, only what it does not already know | Confirms with the customer |
| Fills in the dispute | Never | Yes | Can change anything |
| Blocks / orders a replacement card | Not for disputes | Yes, with the customer's yes | Yes, in your own systems |
| Texts the form link | No | Yes, if the customer wants to see it | — |
| Confirms or submits the dispute | Never | Never (it has no way to) | Yes, after the customer confirms |

The assistant reaches the dispute service through seven **Data requests**, each an HTTPS call with
a key. None takes a customer ID or a phone number: the service works out the customer and the
number to text from Connect's own record of the call. An unverified call gets nothing done.

---

## 3. What is in this folder

| Path | What it is |
|---|---|
| [SPEC.md](SPEC.md) | The design, the rules the code enforces, the known gaps. Part 4 is this design |
| [acxd/disputes-assistant.md](acxd/disputes-assistant.md) | Everything to create in the CX designer, value by value |
| [flows/build_card_dispute_flow.py](flows/build_card_dispute_flow.py) | Writes the Connect flow `card-dispute-flow.json` |
| [lambda/](lambda/) | The Lambda. `dispute_service.py` holds every rule; `dispute_web.py` the CX designer door |
| [web/](web/) | The customer form page and the adviser page |
| [scripts/deploy_card_dispute.sh](scripts/deploy_card_dispute.sh) | Deploys the Lambda, table, web address, gateway tool and Connect access |
| [scripts/deploy_pages_cloudfront.sh](scripts/deploy_pages_cloudfront.sh) | Optional: CloudFront in front of the pages |
| [scripts/build_aria_prompt.py](scripts/build_aria_prompt.py) | Builds ARIA's new prompt from the one that is live today |
| [prompts/card-disputes-cx-designer-block.txt](prompts/card-disputes-cx-designer-block.txt) | The section added to ARIA's prompt |
| [acxd/connect-ai-agent/StartCardDispute.schema.json](acxd/connect-ai-agent/StartCardDispute.schema.json) | ARIA's hand-over tool |
| [tests/](tests/) | Unit tests |

---

## 4. Before you start

- You are on the branch with this work: `git checkout feature/dispute-agents && git pull`.
- You can run the AWS CLI against account `395402194296`, and you have `python3`, `zip`, `curl`
  and `npm`.
- The agent-assist work in [connect-agent-assist/](../connect-agent-assist/) is deployed and its
  screen pop works.
- Your mortgage Live Sync application works in the CX designer workspace `ariaworkspace`. This
  reuses its workspace, and every CX designer screen will look familiar.
- The routing table `aria-routing-config` has rows for `fraud_security`, `debit_card` and
  `credit_card` (it does today), and an adviser serves those queues.

---

## Set it up

### Step 1 — Run the tests (optional, no AWS)

```bash
python3 -m unittest discover -s connect-card-dispute/tests
python3 -m unittest discover -s connect-agent-assist/tests
```

Both end with `OK`.

### Step 2 — Deploy the dispute service

```bash
./connect-card-dispute/scripts/deploy_card_dispute.sh
```

It updates the Lambda `aria-card-dispute` and its table, keeps the web address for the pages,
lets Connect call the Lambda from a flow (and adds it to your instance), and updates the gateway
tool. It tests itself at the end. Add `--dry-run` first to see what it would do.

Keep two lines it prints:

```
For the CX designer disputes assistant (acxd/disputes-assistant.md):
  Data request address : https://…/acxd/ops
  Its key              : Secrets Manager secret aria-card-dispute/acxd-key
```

### Step 3 — CloudFront in front of the pages (optional)

```bash
./connect-card-dispute/scripts/deploy_pages_cloudfront.sh
```

The pages work without it. With it, the texted link and the adviser's link use one stable
`https://….cloudfront.net` address and the Touchpoint library is cached near the customer. Every
page load and every call still goes to the Lambda uncached. It takes 5 to 15 minutes. Later runs of
step 2 keep using its address; the Data request address stays the API's.

### Step 4 — Let the screen pop read disputes

```bash
./connect-agent-assist/scripts/deploy_agent_assist.sh
```

Look for `Card dispute service: aria-card-dispute`.

### Step 5 — Texting the form link (optional)

Without this the assistant simply says it can't text the form, and carries on by voice. To switch
it on:

1. AWS console → **AWS End User Messaging SMS** (eu-west-2).
2. Get a sender that can text UK mobiles: **Phone numbers** → **Request originator**, or a **Sender
   ID**. Check in the console what the UK needs for the one you choose.
3. A new account is in the SMS **sandbox**: it only texts numbers you have verified. Under
   **Destination phone numbers**, add and verify the mobile you will test from. Request production
   access before real customers use it.
4. Run step 2 again with the sender's ID or ARN:
   ```bash
   ./connect-card-dispute/scripts/deploy_card_dispute.sh --sms-from <phone-number-or-sender-id-ARN> --bank-name "Your bank"
   ```
   The texts go only to numbers starting `+447` (UK mobiles); `--sms-prefixes +447,+353` widens it.
   The setting is kept on later runs.

The text goes to the number the customer is calling from, which `conversation bot flow` already
records as `customerPhone`. The link works for two hours.

### Step 6 — Build the assistant in the CX designer

Follow [acxd/disputes-assistant.md](acxd/disputes-assistant.md) from top to bottom: seven context
variables, one Secret, seven Data requests (use the address and key from step 2), the
`HandBackToARIA` flow, the main flow's opening, prompt, tools and exits, and the voice. Then build
and deploy the application `Card dispute`. Note its **application ID**, its environment's
**alias**, and its **deployment key** and **API key**.

Test each Data request with **Test** as you create it: `401` means the key is wrong; `ok:false`
with `customer_not_identified` means it reached the service (a made-up contact is not a verified
customer).

### Step 7 — Give the form page its Live Sync keys

1. AWS console → **Secrets Manager** → **Store a new secret** → **Other type of secret**.
2. Two key/value rows: `deploymentKey` and `apiKey`, from step 6.
3. Name it exactly `aria-card-dispute/touchpoint`, and create it.
4. Run step 2 again. It should say `Live Sync keys found`.

Without them, the texted form still shows the dispute and updates as the assistant fills it in;
only the assistant seeing what the customer types needs Live Sync.

### Step 8 — Import the Connect flow

```bash
python3 connect-card-dispute/flows/build_card_dispute_flow.py --application-id <id> --alias <alias>
```

1. **Routing** → **Flows** → **Create flow** → arrow next to **Save** → **Import** →
   `connect-card-dispute/flows/card-dispute-flow.json`.
2. Name it `Card dispute assistant`.
3. Check the **Agentic CX** block shows the `Card dispute` application, its environment, and five
   context variables. Check the **AWS Lambda function** block shows `aria-card-dispute` (step 2
   added it to the instance) and three parameters.
4. **Save**, then **Publish**.

If you ran the script without `--application-id`, choose the application in the block before
saving.

### Step 9 — Give ARIA its hand-over tool and prompt

**The tool.**

1. **AI agent designer** → **AI agents** → `my-conversation-agent` → **Edit** → **Add tool** →
   **Create new AI Tool**.
2. Name `StartCardDispute`, exactly. Type **Return to Control**.
3. Input schema: paste
   [acxd/connect-ai-agent/StartCardDispute.schema.json](acxd/connect-ai-agent/StartCardDispute.schema.json).
4. Instructions:
   ```
   Use when a verified customer wants to dispute a card payment or does not recognise one. Put
   everything they have already said about the payment in handoverSummary.
   ```
5. Example:
   ```
   <message>Let's sort that out for you.</message>
   ```
6. **Save**. Don't publish yet.

**The prompt.**

```bash
python3 connect-card-dispute/scripts/build_aria_prompt.py --mode cx
```

It reads ARIA's live prompt (it changes nothing in AWS), adds the dispute section, and writes
`connect-card-dispute/prompts/aria-orchestration-prompt-with-disputes.yaml`. Today that is
83,135 characters, under Connect's limit.

1. **AI prompts** → `ARIA-Banking-Ochestration-Prompt`. Copy the current text somewhere as a backup.
2. Replace the whole text with the file. Check the first line is exactly `system: |`.
3. **Save**, then **Publish**.
4. In `my-conversation-agent`, choose that prompt version. **Save**, then **Publish**. Note the new
   agent version (today's live one is 26, so expect 27).

ARIA does not need the dispute tools from the gateway, and today it has none. Leave them off.

### Step 10 — Add one branch to the bot flow

In `conversation bot flow`, find the **Check contact attributes** block that tests
`$.Lex.SessionAttributes.Tool`. It has branches for `Escalate`, `Complete` and
`StartMortgageApplication`.

1. Add a condition: **Equals** `StartCardDispute`.
2. Add a **Set contact attributes** block and connect the new branch to it:

| Destination key | Value |
|---|---|
| `handoverSummary` | Set dynamically: namespace **Lex**, session attribute `handoverSummary` |
| `entry` | Set manually: `phone` |

3. Add a **Transfer to flow** block choosing `Card dispute assistant`. Connect the Set contact
   attributes block's **Success** and **Error** to it, and its **Error** to the flow's existing
   Disconnect.
4. Point the flow at ARIA's new version, in both places:
   - the first **Connect assistant** block: the new version of `my-conversation-agent`;
   - the **Get customer input** block's session attribute `x-amz-lex:q-in-connect:ai-agent-arn`:
     change the number at the end to the new version.
5. **Save**, then **Publish**.

### Step 11 — The adviser's side

**The screen pop.**

1. **Routing** → **Flows** → `ARIA-Agent-Screen-Pop-Flow` → arrow next to **Save** → **Export
   flow**, to keep as your way back.
2. Arrow next to **Save** → **Import** → `connect-agent-assist/flows/aria-agent-screen-pop-flow.json`.
3. The **Card dispute** view now has six lines: reference, payment, what's still needed, whether the
   customer is viewing the form, cards blocked or ordered, and the assistant's note.
4. **Save**, then **Publish**.

**The adviser's assistant (optional).** It can then answer questions about the dispute.

1. **AI agents** → `my-agent-assistant-agent` → **Edit** → **Add tool** →
   `aria_banking_dispute___get_card_dispute`, only this one. **Save**, **Publish**, note the version.
2. **AI prompts** → `agent-briefing-prompt`: paste
   [agent-briefing-prompt-v1.yaml](../connect-agent-assist/prompts/agent-briefing-prompt-v1.yaml),
   **Save**, **Publish**.
3. **AI agents** → `my-agent-briefing-agent` → **Edit**: add the same tool, choose the new prompt
   version, **Save**, **Publish**, note the version.
4. In the flow `ARIA agent assist`, update the versions in three places: the **Connect assistant**
   block, and the `assistAgentArn` and `briefingAgentArn` parameters on the **AWS Lambda function**
   block. **Save**, then **Publish**.

> **If `get_card_dispute` is not offered:** Connect keeps its own copy of the gateway's tool list.
> Remove the `aria-mcp-agentcore-gateway-server` integration from the agent, add it again, and
> re-select the tools it had. Note them down first.

---

## Test it

You need a phone (the mobile you verified in step 5, if texting is on), and an adviser logged in to
the agent workspace and **Available**.

### Test 1 — A payment the customer did not make, with the form

| # | Who | Do | Expect |
|---|---|---|---|
| 1 | Customer | Ring ARIA as James. "I don't recognise a payment on my debit card" | ARIA checks you; then one short sentence, no transfer words |
| 2 | Customer | (listen) | The same voice asks about the payment, without asking what you already said |
| 3 | Customer | "The Amazon one, about ninety pounds. I still have my card." | It names the payment back and asks whether you made it, or goes straight on |
| 4 | Customer | "No, I didn't make it" | It offers to block the card |
| 5 | Customer | "Yes please", then "yes" to a replacement | It gives the replacement time (3 to 5 working days) |
| 6 | Customer | (listen) | It offers to text you the form |
| 7 | Customer | "Yes" | A text arrives on your mobile; it says "the mobile ending …" only |
| 8 | Customer | Open the link | The form, filled in so far, "Connected to your call" |
| 9 | Customer | Answer its remaining questions; type a sentence into "what happened" yourself | Fields fill as you speak; your typing is kept |
| 10 | Customer | Agree when it reads it back | "A colleague will now check the form with you…", then "Please wait while I connect you…" |
| 11 | Adviser | Accept | Screen pop **Card dispute**: the payment, **Cards:** blocked and replacement ordered, the note, the link |
| 12 | Adviser | Open the link, change a field | The customer's form becomes read-only and shows the change |
| 13 | Customer | Press **These details are correct** | The adviser page shows the confirmation |
| 14 | Adviser | **Submit dispute** | Both pages show "Submitted" and the reference |

### Test 2 — A payment the customer made, by voice only

Ring as James, dispute the Tesco payment, "I was charged twice". Decline the text. The call goes to
the queue the routing table gives `debit_card`, not Fraud. On the adviser page, tick "The customer
confirmed these details to me on this contact", then submit.

### Test 3 — The rules hold

- Call from a number that isn't verified as James: the assistant does nothing on cards or disputes
  and passes you to a colleague.
- Ask the assistant to submit the dispute: it can't, and says a colleague will.
- Ask for the text a fourth time: refused ("sent the most times allowed").
- On the adviser page, press **Submit** before the customer has confirmed: refused.

### Where to look

| Log group | Shows |
|---|---|
| `/aws/lambda/aria-card-dispute` | One line per call: `route=/acxd/ops … outcome=blockCard:ok`, `op=handover … topic=fraud_security`, page requests. Never content, numbers or links |
| `/aws/connect/<your instance>` flow logs | Which blocks `conversation bot flow` and `Card dispute assistant` ran |
| `/aws/lambda/aria-agent-assist-injector` | `briefing_read` each time a screen pop opens |

---

## Troubleshooting

| What you see | Likely cause |
|---|---|
| ARIA tries to help with the dispute itself | ARIA's prompt or version: step 9 (prompt published, agent published) and step 10 (both version places) |
| ARIA says one sentence, then silence | The assistant's opening (acxd/disputes-assistant.md 3a) is missing or not connected to the assistant node |
| The call drops after ARIA's sentence | The bot flow branch (step 10) is missing, so the Tool check takes "no match". Or the Agentic CX block has no application chosen |
| A different voice after ARIA | The CX designer application's voice (acxd 4.1) |
| Every Data request says `customer_not_identified` | `contactId` is not mapped as a **Variable** (acxd 3c), or the caller isn't verified |
| Data requests answer `401` | The CX designer Secret doesn't match `aria-card-dispute/acxd-key` |
| "I can't text the form right now" | `sms_not_configured` (step 5 not done), `no_mobile_number` (not calling from a `+447` mobile), or `sms_failed`: the SMS sandbox, or the sender can't send to that number |
| The form opens but doesn't update | It updates every two seconds from what's saved. If the assistant says it saved something and it doesn't appear, check the log for `updateDispute` outcomes |
| The adviser gets "Card dispute: the hand-over summary could not be built" | The flow couldn't call the Lambda. Step 2 again (it adds the Connect permission), then check the Lambda block in step 8 |
| The screen pop is the ordinary one, with no dispute | The dispute wasn't started (the summary says "Card dispute not drafted"), or step 4 wasn't run |

---

## How to undo it

| To undo | Do |
|---|---|
| ARIA's dispute hand-over | Point `conversation bot flow` back at agent version 26, both places, and publish |
| The screen pop | Import the file you exported in step 11 and publish |
| The adviser's assistant tool | Point `ARIA agent assist` back at the previous agent versions |
| Texting | Lambda console → `aria-card-dispute` → **Configuration** → **Environment variables**: remove `SMS_ORIGINATION_IDENTITY`. Later runs of step 2 leave it off |
| The dispute service | Delete the gateway target `aria-banking-dispute`, the HTTP API `aria-card-dispute-pages`, the Lambda `aria-card-dispute`, its role `aria-lambda-card-dispute-role` and the table `aria-card-disputes`. Then run step 4 again |

---

## Earlier designs

Two earlier designs are still in the code, and neither is used now:

- **ARIA drafts the dispute itself** with five gateway tools (`build_aria_prompt.py --mode direct`).
- **An in-instance disputes agent** attached to ARIA as a collaborator (`--mode agents`,
  `attach_disputes_collaborator.sh`, `prompts/disputes-agent-prompt-v1.yaml`). The AI agent
  `card-disputes-agent` you created for it is not attached to ARIA (checked: ARIA has no
  collaborator); you can leave it or delete it.

Their setup steps are in this README's history, at commit `35a43f2`. SPEC.md Parts 1 to 3 explain
them.
