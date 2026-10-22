# Deploying the modular conversation bot flow and ARIA v2

Step by step, from nothing to tested, then switching over. **Phases 1 to 6 only create new resources and never
overwrite anything.**
- The scripts check before they write, stop if a name is already taken, and tag what they create
  `project=connect-bot-flow-modular`.
- In the admin website you always use **Create**, never Import into something that exists.

The live conversation bot flow, the live ARIA (`my-conversation-agent`) and everything that uses them keep working
until Phase 7, which is the only phase that changes existing settings. Phase 8 undoes it.

Checked on 18 Oct 2026, so you don't need to redo these:
- the live flow uses ARIA v38;
- both Lambdas the new flow calls (`aria-session-injector-qconnect`, `aria-handback-recovery`) and the Lex bot
  alias `production` are associated with the instance;
- the card Lambdas and gateway schemas require `customer_id`;
- no ARIA v2, flow modules or AI agent logging exist yet.

| Phase | What | Where | Time |
|---|---|---|---|
| 0 | Check your terminal and the files | terminal | 5 min |
| 1 | Switch on logging (AI agent events) and find the bot analytics | terminal + admin website | 10 min |
| 2 | Create ARIA v2 | terminal | 5 min |
| 3 | Import and publish the three modules | Connect admin website | 15 min |
| 4 | Fill in the ARNs and rebuild the main flow | terminal | 5 min |
| 5 | Import and publish the main flow | Connect admin website | 5 min |
| 6 | Test without touching anything live | your laptop | 30 min |
| 7 | Switch over (when you're happy) | terminal + admin website | 15 min |
| 8 | Roll back (only if needed) | terminal + admin website | 5 min |

---

## Phase 0: Check your terminal and the files

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
export AWS_REGION=eu-west-2
aws sts get-caller-identity --query Account --output text        # must print 395402194296
aws --version                                                     # AWS CLI v2
python3 -m unittest discover -s connect-bot-flow-modular/tests    # OK (skipped=1)
```

- The skipped test is the full YAML parse, which needs pyyaml. To run it too:
  `~/.venvs/aria-deploy/bin/python3 -m unittest discover -s connect-bot-flow-modular/tests`.
- In the Connect admin website you need a security profile that can create and publish flows and **flow modules**.
  Admin can.
- **Optional:** the live flow changed at 10:25 on 18 Oct (only the ARIA version). The equivalence test doesn't
  compare agent versions, so the reference snapshot is still valid. To refresh it anyway, run the command at the end
  of `README.md`.

---

## Phase 1: Switch on logging

So your first test is fully recorded. Both of these add logging only, and apply to the live ARIA too.

### 1a. AI agent event logs (ARIA's turns, tool calls, model responses)

```bash
./connect-bot-flow-modular/ai-agent/enable_ai_agent_logging.sh            # dry run: read what it would do
./connect-bot-flow-modular/ai-agent/enable_ai_agent_logging.sh --apply
```

It creates only what's missing: the log group `/aws/vendedlogs/connect/ai-agents/e6991ed4-e11c-4194-8d20-13889a36bd15`
(30-day retention), a delivery source for the assistant (`EVENT_LOGS`), a destination and the delivery, all tagged.
It never replaces or changes anything that exists:
- An existing log group keeps its retention.
- A source or destination already using one of its names for something else makes it stop.
- If the assistant already has event logging under another name, it stops and says so.

Running it twice changes nothing.

**On this account today (read on 19 Oct):** the log group, the source and the destination already exist and are
right, but there's **no delivery**, so no event logs arrive yet. An earlier run stopped before its last step. The
dry run should therefore show:
- "exists, … will reuse" for the source and the destination;
- "exists: used as it is" for the log group;
- one write only: `[would run] aws logs create-delivery …`.

Check it:

```bash
aws logs describe-deliveries --query "deliveries[?deliverySourceName=='aria-assistant-event-logs']"
```

You should see one delivery. If `create-delivery` (or `put-delivery-source`) fails with access denied, your role
needs:
- `logs:PutDeliverySource`, `logs:PutDeliveryDestination`, `logs:CreateDelivery`;
- `wisdom:AllowVendedLogDeliveryForResource` on the assistant ARN.

### 1b. The Lex bot: use Connect's bot analytics (not Lex conversation logs)

`coversatonalaibot` was created in the Connect admin website. Connect manages it: it carries the tag
`AmazonConnectEnabled=True` and runs as Connect's service-linked role. So the Lex console greys out its alias's
conversation logs. Don't force them on through the API; Connect owns that bot.

Nothing is lost:
- **Lex errors** are already in the flow log on the Get customer input block (`ErrorDetails`, as with the chat
  `NullPointerException`).
- **ARIA's turns** are in the AI agent event logs (1a).

The bot's conversations are in Connect itself:
1. **Bot analytics:** **Routing → Flows → Bots → coversatonalaibot → Analytics**. This shows recognition and
   conversation performance, success, failure and drop rates. It needs the Bots View/Edit and Historical metrics
   Access permissions (Admin has them).
2. **Dashboard:** **Analytics → Dashboards → Flows and conversational bot performance**, for bot conversations,
   success rate, average turns and duration, including Q in Connect.
3. **Per contact:** **Contact search →** the contact **→ Automated interaction → Show flow & trace details**.

If **Bots** has no Analytics tab: in the AWS console, go to Amazon Connect → the instance → **Flows**, turn on
**Enable Bot Analytics and Transcripts in Connect**, and **Save**.

### 1c. Flow logs

Already on for the instance (log group `/aws/connect/conversationalbot`). The new flow and every module switch
logging on as their first block, so nothing to do.

---

## Phase 2: Create ARIA v2

`create_agent.sh` **only creates**:
- a new AI prompt **ARIA-Banking-Orchestration-Prompt-v2**;
- a new AI agent **aria-conversation-agent-v2**;
- their first versions, both tagged `project=connect-bot-flow-modular`.

**Before writing anything it checks, and stops if** either name already exists, or if any ID it would touch is the
live ARIA (`68179bd0-…`) or the live ARIA prompt (`37cae8d9-…`). It only *reads* the live ARIA's security-profile
list, and adds the new agent to the same profiles. That doesn't change what those profiles allow.

It sends the agent itself with the boto3 in `~/.venvs/aria-deploy`, because the AWS CLI (2.35) doesn't know the
Money Hub collaborator setting (`multiAgentConfigurations`) and rejects it before sending. Check the venv's boto3
knows it:

```bash
~/.venvs/aria-deploy/bin/pip install -U boto3        # only if the check line below says it doesn't
python3 connect-bot-flow-modular/ai-agent/build_agent.py
./connect-bot-flow-modular/ai-agent/create_agent.sh            # dry run
```

If an earlier run created the prompt and stopped before the agent, it reuses that prompt (it carries our tag) and
creates only the agent. **On this account today**, the 19 Oct run created
`ARIA-Banking-Orchestration-Prompt-v2` (`f6369a3e-…`, version 1, same text as the build) and stopped at the agent,
so the dry run says `… is ours (tagged) from a run that stopped before the agent: reusing it` and
`reusing f6369a3e-… version 1`.

The build prints the prompt size and "21 tools". The dry run must also show:
- `agent request: valid CreateAIAgent request: 21 tools, 1 collaborator(s)`;
- `MODE: create ARIA v2 as new resources`;
- `no prompt named ARIA-Banking-Orchestration-Prompt-v2, no agent named aria-conversation-agent-v2: both will be created new`;
- `[would] create a new prompt … tagged`, then `[would] create a new orchestration agent …`;
- six `[would] link …` lines, for the 3 profiles on the agent and on its version.

If it says `STOPPED: … already exists`, nothing was changed: a resource with that name is already there. If it's
ARIA v2 from an earlier run, use `--update` (see "Afterwards"); otherwise rename it before going on. Then:

```bash
./connect-bot-flow-modular/ai-agent/create_agent.sh --apply
```

It prints, in order:
- `created <prompt id>` and `published version 1`: **ARIA-Banking-Orchestration-Prompt-v2**, on the same model as the live prompt;
- `created <agent id>` and `published version 1`: **aria-conversation-agent-v2**, with 21 tools, the Money Hub collaborator and guardrail v3;
- `linked 3 profiles to the agent and version 1`.

It finishes with **`ARIA v2: arn:aws:wisdom:eu-west-2:395402194296:ai-agent/e6991ed4-…/<agent id>:1`**. Copy that
whole line: you need it in Phase 4.

Check it in the Connect admin website: **AI agent designer → AI agents → aria-conversation-agent-v2**. You should
see the v2 prompt and 21 tools. **Look, but don't Save there:** the designer's Save can replace its security
profiles. To change v2 later, edit `build_agent.py` and run `create_agent.sh --update --apply` (see "Afterwards").

**If it fails part-way:**
- **On `create-ai-prompt`:** nothing was created. Send me the message: this is the first time the payload has been
  sent.
- **On creating the agent:** the new prompt exists (tagged), but there's no agent. Run `--apply` again: it reuses
  that prompt and creates only the agent.
- **On linking profiles:** the agent exists. Link the profiles to it and its version in **AI agent designer → the
  agent → Security profiles**, or with the `associate-security-profiles` commands. Don't re-run without `--update`:
  it would stop because the names now exist.

---

## Phase 3: Import and publish the three modules

First make sure nothing already uses these names (you're creating new modules, never importing over one). This
must print nothing:

```bash
aws connect list-contact-flow-modules --instance-id f969d4b4-f716-4974-a325-bb7899f2f293 \
    --query "ContactFlowModulesSummaryList[?starts_with(Name, 'ARIA - ')].Name" --output text
```

Then in the Connect admin website, **for each module in this order**:

| # | File | Name (exactly) |
|---|---|---|
| 1 | `connect-bot-flow-modular/modules/aria-contact-setup.json` | ARIA - Contact setup |
| 2 | `connect-bot-flow-modular/modules/aria-customer-context.json` | ARIA - Customer context |
| 3 | `connect-bot-flow-modular/modules/aria-decide-handback.json` | ARIA - Decide hand-back |

1. Go to **Routing → Flows**, open the **Modules** tab, and choose **Create flow module**. Always a new module:
   never open an existing one and import over it.
2. In the designer, open the menu (top right) and choose **Import**. Choose the file.
3. Check the blocks appear laid out left to right. A yellow warning before saving is normal: the designer resolves
   the Lambda ARNs on save.
4. Set the module **name** as in the table, choose **Save**, then **Publish**.

Then get the three ARNs:

```bash
aws connect list-contact-flow-modules --instance-id f969d4b4-f716-4974-a325-bb7899f2f293 \
    --query "ContactFlowModulesSummaryList[?starts_with(Name, 'ARIA - ')].[Name, Arn]" --output table
```

**If the import rejects a block,** send me the error. The most likely candidates are the Disconnect block inside
Contact setup and Customer context (assumption 3 in `assumptions.md`).

---

## Phase 4: Fill in the ARNs and rebuild the main flow

Edit `connect-bot-flow-modular/config.json` and replace the four placeholders:

```json
{
  "modules": {
    "contact_setup":    "arn:aws:connect:eu-west-2:395402194296:instance/f969d4b4-f716-4974-a325-bb7899f2f293/flow-module/<id 1>",
    "customer_context": "arn:aws:connect:eu-west-2:395402194296:instance/f969d4b4-f716-4974-a325-bb7899f2f293/flow-module/<id 2>",
    "decide_handback":  "arn:aws:connect:eu-west-2:395402194296:instance/f969d4b4-f716-4974-a325-bb7899f2f293/flow-module/<id 3>"
  },
  "aria": "arn:aws:wisdom:eu-west-2:395402194296:ai-agent/e6991ed4-e11c-4194-8d20-13889a36bd15/<agent id>:1"
}
```

Then:

```bash
python3 connect-bot-flow-modular/build_flows.py --config connect-bot-flow-modular/config.json
python3 -m unittest discover -s connect-bot-flow-modular/tests
python3 /Users/alokkulkarni/.claude/skills/amazon-connect-flow-builder/scripts/validate_flow.py \
    connect-bot-flow-modular/flows/aria-conversation-bot-flow.json --strict
```

- The build must **not** print a "Still to fill in" line.
- The tests must still pass: rebuilding with real ARNs changes nothing they check.
- `--strict` must say PASS with no placeholders left.

---

## Phase 5: Import and publish the main flow

This must print nothing (no flow has the name yet):

```bash
aws connect list-contact-flows --instance-id f969d4b4-f716-4974-a325-bb7899f2f293 \
    --query "ContactFlowSummaryList[?Name=='ARIA conversation bot flow (modular)'].Id" --output text
```

1. Go to **Routing → Flows → Create flow**, and choose **Inbound flow**. Always **Create flow**: never open the
   live conversation bot flow and import into it.
2. Open the menu (top right), choose **Import**, and choose `connect-bot-flow-modular/flows/aria-conversation-bot-flow.json`.
3. Name it **ARIA conversation bot flow (modular)**.
4. Spot-check four blocks:
   - **contactSetup**, **customerContext** and **decideHandback** each name their module;
   - **talkToAria** shows the Lex bot `coversatonalaibot` / `production`, with the session attribute
     `x-amz-lex:q-in-connect:ai-agent-arn` set to the ARIA v2 ARN.
5. **Save**, then **Publish**.

**If Publish failed and left a saved draft** (the check above now prints its ID): open that draft, **ARIA
conversation bot flow (modular)**, choose **Import** again with the rebuilt file, then **Save** and **Publish**. It's
the new flow you made in this phase, never the live one.

The **Connect assistant** block is two actions underneath (`connectAssistant` and its hidden `saveAssistantSession`).
If the designer shows a separate empty **Set contact attributes** block after it, the file is older than this fix:
run `build_flows.py --config config.json` again.

Get its flow ID for testing:

```bash
aws connect list-contact-flows --instance-id f969d4b4-f716-4974-a325-bb7899f2f293 --contact-flow-types CONTACT_FLOW \
    --query "ContactFlowSummaryList[?Name=='ARIA conversation bot flow (modular)'].Id" --output text
```

---

## Phase 6: Test without touching anything live

Run the banking app on your laptop against the **modular** flow. These are real chats and calls, using your AWS
credentials:

```bash
python3 connect-banking-app/scripts/local_preview.py --talk f969d4b4-f716-4974-a325-bb7899f2f293 <modular flow id>
```

Open the link it prints. Then:

| # | Where | Do | Expect |
|---|---|---|---|
| 1 | Home, chat | Say hello | ARIA greets James by name, mentions his products |
| 2 | Cards, chat | "I don't recognise a payment on my credit card" | "Let's sort that out for you", then the **card dispute assistant** a few seconds later |
| 3 | Cards, "Dispute" on a payment | Start a chat | Straight to the card dispute assistant with that payment |
| 4 | Money Hub, call | Ask about your spending | The Money Hub agent answers |
| 5 | Money Hub, call | "Help me fill in my mortgage application", give the code | The **mortgage assistant** joins (not a hang-up) |
| 6 | Cards, chat | "I've lost my debit card, please block it" (confirm) | Blocked, with a reference starting `BLOCK-4821-` |
| 7 | Accounts, chat | "Can I speak to someone?" | Transferred to the queue. In the adviser's CCP, the assist panel is the agent-assist agent |
| 8 | Any, chat | "That's all, thanks" | A short goodbye, and the chat ends |
| 9 | Help, chat | Say nothing for 5 minutes | Retried twice, then the chat ends |

Check each one in three places. Find the contact ID in **Analytics → Contact search** (last 15 minutes).

1. **Flow log:** CloudWatch → **Logs Insights**, log group `/aws/connect/conversationalbot`:
   ```
   fields @timestamp, ContactFlowName, Identifier, ContactFlowModuleType, Results, ExternalResults.route, ErrorDetails.ErrorCode
   | filter ContactId = '<contact id>' | sort @timestamp asc
   ```
   You'll see the readable block names, the modules' blocks under their module names, and `routeHandback` with the
   route taken. A Get customer input **Error** with `NullPointerException` on a chat hand-back is the known Connect
   bug; the next lines show the recovery working.
2. **ARIA's tool calls:** Logs Insights on `/aws/vendedlogs/connect/ai-agents/e6991ed4-e11c-4194-8d20-13889a36bd15`:
   ```
   fields @timestamp, @message | filter @message like /<contact id>/ | sort @timestamp asc
   ```
3. **The conversation and analytics:** open the contact in **Contact search**:
   - the transcript, sentiment and summary (Contact Lens);
   - **Automated interaction → Show flow & trace details**, for ARIA's trace (this can take up to 30 minutes after
     the contact ends);
   - the contact attributes `handbackRoute` and `handbackOutcome`.

**If something's wrong,** send me the contact ID. I'll read the flow log, ARIA's events and her trace.
- **ARIA doesn't use James's name (test 1):** that's assumption 4, the single Connect assistant block.
- **Test 5 hangs up:** check `ExternalResults.route` on `recoverAfterComplete` in the flow log.

---

## Phase 7: Switch over (when you're happy)

Four things send contacts to the live conversation bot flow today. Move each one to the modular flow:

1. **The banking app:**
   ```bash
   ./connect-banking-app/scripts/deploy_banking_app.sh --contact-flow-id <modular flow id>
   ```
   This also moves its permission to start chats onto the new flow.
2. **The Money Hub page:**
   ```bash
   ./connect-money-hub/scripts/deploy_money_hub.sh --contact-flow-id <modular flow id>
   ```
3. **The phone number:**
   1. In the admin website, go to **Channels → Phone numbers**.
   2. Find the number whose contact flow is **conversation bot flow**. (Of the instance's three numbers, the other two
      use ARIA IDV Test Harness and Branch expert transfer flow.)
   3. Set its flow to **ARIA conversation bot flow (modular)**, then **Save**.
4. **The "ARIA IDV Test Harness" flow** transfers to the conversation bot flow. In that flow:
   1. Open its **Transfer to flow** block and choose **ARIA conversation bot flow (modular)**.
   2. **Save** and **Publish**.

**Also check (outside this repo):** the mortgage Live Sync web widget (`connect-livesync-mortgage`). If it starts
contacts in the conversation bot flow (`entry=web_widget`), point its flow setting at the modular flow too.

Then repeat tests 1, 2, 5 and 7 through the deployed banking app and the phone number.

Keep the live conversation bot flow and `my-conversation-agent` **unchanged** for at least a week.

---

## Phase 8: Roll back (only if needed)

Undo Phase 7 in the same way, with the old flow ID `f6d6545f-c9ae-4ca4-a4d8-6fdc8ba0494f`:

```bash
./connect-banking-app/scripts/deploy_banking_app.sh --contact-flow-id f6d6545f-c9ae-4ca4-a4d8-6fdc8ba0494f
./connect-money-hub/scripts/deploy_money_hub.sh --contact-flow-id f6d6545f-c9ae-4ca4-a4d8-6fdc8ba0494f
```

Then set the phone number and the IDV Test Harness transfer back to **conversation bot flow**. ARIA v2, the
modules, the modular flow and the logging can stay: nothing live uses them once switched back.

---

## Back to ARIA, and every app page through ARIA (20 Oct 2026)

What changes:
- **The card dispute assistant hands back to ARIA** when the customer has finished with the dispute and asks about
  anything else (or says they need nothing else), instead of passing them to a colleague. ARIA answers straight
  away, without greeting them again. Asking for a person still goes to a colleague.
- **The banking app's mortgage form and Cards → Dispute start with ARIA.** She greets in one sentence and hands
  over in the same turn; the mortgage form still gets the mortgage assistant joined to it (on chat too, where
  ARIA's mortgage hand-over used to go to a colleague).

Do these in this order. **The banking app goes last**: until ARIA, her flow and the injector know the new
pages, a mortgage-form chat would reach ARIA without the new rule.

1. **Session injector** (code only, so its settings stay as they are). From the repository root:
   ```bash
   (cd scripts/lambdas && zip -q /tmp/injector.zip session_injector_qconnect.py)
   aws lambda update-function-code --function-name aria-session-injector-qconnect --region eu-west-2 \
       --zip-file fileb:///tmp/injector.zip --query LastModified --output text
   ```
2. **ARIA v2's prompt** (adds `<from_internet_banking>`): `./connect-bot-flow-modular/ai-agent/create_agent.sh
   --update` (dry run), then `--update --apply`. It publishes a new version; put its ARN in `config.json` as `aria`.
3. **Rebuild the flows**: `python3 connect-bot-flow-modular/build_flows.py --config connect-bot-flow-modular/config.json`.
4. **Re-import the module `ARIA - Decide hand-back`** (Routing → Flow modules → open it → Import →
   `modules/aria-decide-handback.json` → Save → **Publish**). New: `appPage=mortgage` → `mortgage_form`.
5. **Re-import the main flow `ARIA conversation bot flow (modular)`** (`flows/aria-conversation-bot-flow.json`),
   Save, **Publish**. New: `entry=returned` comes back to ARIA, skipping Contact setup (already done) and,
   when she already has a session (`ariaStarted`), a second Connect assistant block; and `mortgage_form` → Mortgage
   Live Sync handover.
6. **The card dispute assistant** (Agentic CX designer, application "Card dispute"), following
   `connect-card-dispute/acxd/disputes-assistant.md`:
   - Part 3a: change the `HandBackToARIA` Escalate message to the new neutral one.
   - Part 3a-2: build the new flow `BackToARIA`.
   - Part 3b: paste the updated prompt into `CardDisputeAssistant`, add the exit condition **Back to ARIA**, and
     draw its line to a Redirect → `BackToARIA`.
   - Build and deploy the application (Part 4), to the same environment.
7. **The card dispute Connect flow**: `python3 connect-card-dispute/flows/build_card_dispute_flow.py
   --application-id 0695e7ea-b8a9-4514-a3f0-eb65fabe9afe --alias 1jVQrqDoXSeGFTnPa7HKw --output
   connect-card-dispute/flows/card-dispute-flow.live.json` (ignored by git: the committed file keeps placeholders), then import
   `connect-card-dispute/flows/card-dispute-flow.live.json` into **Card dispute assistant**, Save, **Publish**. New:
   an escalation with `back_to_aria` goes back to ARIA's flow (`entry=returned`, `returnSummary`).
8. **The banking app**: `./connect-banking-app/scripts/deploy_banking_app.sh --contact-flow-id
   2b4f7b5c-1351-42c8-acac-add07d0cbd00`.

### The mortgage assistant goes back to ARIA too (FR-39, `connect-livesync-mortgage` v1.23)

When the customer is done with their application (or has submitted it, or wants something else), the mortgage
assistant hands them back to ARIA with a note of where the application stands, and ARIA says goodbye or helps.
A contact ARIA handed over isn't greeted twice. Do these after steps 1 to 7 above, before the banking app:

1. **Session injector, again** (it now knows "Back from mortgage application"): repeat step 1.
2. **ARIA, again** (her rule now covers both assistants): repeat step 2 (it publishes the next version), put its
   ARN in `config.json`, repeat step 3, and re-import and publish the **main flow** (step 5). The decision module
   hasn't changed.
3. **The mortgage assistant** (Agentic CX designer, application "Mortgage application"), following
   `connect-livesync-mortgage/docs/GUIDE.md` and `acxd/live-sync-node.md`:
   - Part 4a-2: build the new flow `BackToARIA` (note, then Escalate "Of course." with `summary` and
     `escalationReason` = `back_to_aria`).
   - Part 4b step 2: paste the updated prompt (section 1 of `acxd/live-sync-node.md`), re-inserting each `{name}`.
   - Part 4b step 3: on the web branch of the opening, add the second Split on `{handoverSummary}` is not empty →
     Basic "I can see your application. Where would you like to carry on?"
   - Part 4b step 5: rename the exit **Goodbye** to **Back to ARIA** with its new description, and connect it and
     **Task complete** to a new Redirect → `BackToARIA`. Step 6: **Timeout** to its own "progress saved" Exit
     application.
   - Build and deploy to the same environment.
4. **The Connect flow "Mortgage Live Sync handover"** (GUIDE 6.8c and 6.8d-0):
   - Escalation branch: a new **Check contact attributes** on Agentic CX `escalationReason` **Equals**
     `back_to_aria` → **Set contact attributes** (`entry`=`returned`, `returnedFrom`=`mortgage`,
     `handbackRoute`=`returned`, `returnSummary` = Agentic CX `summary`) → **Transfer to flow** "ARIA conversation
     bot flow (modular)". No match / errors → the existing hand-off notes block.
   - Default branch's check: add **Equals** `back_to_aria` as the **first** condition, to the same Set contact
     attributes block (it has an underscore, so it must come before **Contains** `_`).
   - Save, **Publish**.

Check:
| Try | You should see |
|---|---|
| Mortgages → Chat → fill a field → "thanks, that's all for now" | "Of course." then ARIA: a short goodbye saying where the application stands |
| Mortgages → Chat → "how do I open a joint account?" | "Of course." then ARIA answers, no greeting |
| Mortgages → Chat | ARIA's one sentence, then the mortgage assistant without a second "Hello, I'm…" |
| Money Hub → chat → "I want to dispute a payment" → finish and submit → "how do I open a joint account?" | "Of course." then ARIA answers about joint accounts, no greeting, no colleague |
| Cards → Dispute on a payment → Chat | ARIA: "Hi James, let's sort out that payment." then the dispute assistant asks about that payment |
| Mortgages → Chat | ARIA: one sentence, then the mortgage assistant; the form fills as you answer |
| In the dispute, "can I speak to someone?" | A colleague, as before |

## Dispute updates go to the disputes assistant (21 Oct 2026)

Asked "what's the status of my dispute?", ARIA offered a colleague (she has no tool that sees disputes). Now she
hands it to the card disputes assistant like a new dispute (`<dispute_updates>`), and the assistant looks it up with
`getDispute` (by reference, or from the payment's "already disputed" label) and tells them where it is. No Lambda or
flow change.

1. **ARIA**: `create_agent.sh --update`, then `--update --apply`; put the new version ARN in `config.json`, rebuild
   (`build_flows.py --config config.json`), and re-import and publish the main flow. If you haven't yet done the
   mortgage section's "ARIA, again", this one update covers both.
2. **The card disputes assistant** (Agentic CX designer, "Card dispute"): paste the updated prompt into
   `CardDisputeAssistant` (Part 3b, step 6; re-insert `{channel}`, `{firstName}`, `{handoverSummary}`) and the
   updated **opening** prompt into the `openingQuestion` Generative text node (Part 3b, step 2; re-insert
   `{handoverSummary}`). Build and deploy to the same environment.

Check: Cards → Chat → "what's the status of my dispute DSP-…?" → "Let's find that for you." → the disputes
assistant says where it is (and what happens next if it's submitted), then asks if there's anything else.

## Back to ARIA on a chat: she answers straight away (21 Oct 2026)

On a chat, ARIA only gets a turn when a message arrives. The customer's question had gone to the assistant that
handed back, so ARIA sat silent until they typed it again (46 s on 21 Oct), and then answered twice. Now a returning
chat starts her Lex block with the chat's initial message (`talkToAriaWithNote`, Connect's "Initialize bot with
message", `$.Media.InitialMessage`: the only value an imported flow keeps). The internet banking app starts every chat
with the note "Chat started from internet banking." (its widget hides it); the flow checks for it, and chats without it
and calls use the usual block. ARIA answers from her known contact reason (the note), once.

1. **ARIA**: `create_agent.sh --update`, then `--update --apply`; the new version ARN in `config.json`.
2. **Main flow**: `build_flows.py --config config.json`, then re-import and publish "ARIA conversation bot flow
   (modular)". It can go in before the app: until the app sends the note, the check falls through to the usual block.
3. **The banking app**: `deploy_banking_app.sh --contact-flow-id 2b4f7b5c-1351-42c8-acac-add07d0cbd00`.

Check: in a dispute, submit it, then "how do I open a joint account?" → "Of course." → ARIA answers within a few
seconds, once, without you typing again.

## Every hand-over shows, and a page move tells ARIA (21 Oct 2026)

- **The Money Hub hand-over is recorded.** The Money Hub bridge marks the contact (`specialist#<contactId>` in the
  Money Hub table) when a stint starts and when it hands back to ARIA. The banking app's "How it works" view reads it,
  so "Money Hub specialist brought in" and "back to ARIA" show from any page, not only a chat started on the Money Hub
  page. Disputes and mortgage already show from Connect's record; now every hand-over and hand-back shows as it
  happens, a second one too.
- **Moving page mid-conversation tells ARIA.** The banking app updates the contact's page attributes (`appPage`, the
  Money Hub tab, the mortgage application and stage: what the flows route on) and ARIA's known contact reason
  ("Moved to …:"), so her next turn uses that page's specialist (`<page_changes>`). Never `entry` or who the
  customer is.

1. **Money Hub bridge**: `./connect-money-hub/scripts/deploy_bridge.sh` with no options. It rewrites the bridge's
   settings; on 21 Oct the live bridge used the defaults (`BRIDGE_MODE` sync, no `SILENCE_REPLY` or `WAIT_REPLY`), so
   no options keeps them. If you've since set any, pass them again (`--mode`, `--silence-reply`, `--wait-reply`).
2. **ARIA**: `create_agent.sh --update`, then `--update --apply`; the new version ARN in `config.json`; rebuild
   (`build_flows.py --config config.json`) and re-import and publish the main flow (the flow itself is unchanged
   apart from ARIA's version). One update covers this and the chat note above.
3. **The banking app** (last): `deploy_banking_app.sh --contact-flow-id 2b4f7b5c-1351-42c8-acac-add07d0cbd00`. Its
   role gains `connect:UpdateContactAttributes` and `qconnect`/`wisdom:UpdateSessionData` on ARIA's assistant.

Check: start a chat on Accounts, ask about the transfer, move to Money Hub, ask "where can I cut my spending?" →
"How it works" shows the Money Hub specialist brought in; then "thanks, that's all" → back to ARIA.

## Only ARIA escalates to a person (21 Oct 2026)

Principle: the specialists (Money Hub, disputes, mortgage) never hand a customer to a colleague. They go back to ARIA
with what's needed, "colleague needed" included, and ARIA decides and escalates. The adviser's screen pop gets the
specialist's full notes (ARIA's own summary is capped at 500 characters), the dispute reference, and for a mortgage
the application view.

| Part | Change |
|---|---|
| Card dispute flow | Every escalation and error builds the hand-over from the dispute record, then goes back to ARIA (`returnIntent=escalate`, `returnReason`, `returnSummary`); ARIA human handover only if that transfer fails (SPEC R16) |
| Dispute assistant | Complete is not the end: sum up, offer "submit it yourself, or a colleague", wait; escalate only on "a colleague". `HandBackToARIA` says "Of course." |
| Mortgage (`connect-livesync-mortgage` v1.24, FR-40) | The same through "Mortgage Live Sync handover" (GUIDE 6.8d-1); `HandToAdviser` says "Of course." |
| Money Hub agent | Out-of-scope questions: "Let's sort that out.", never "a colleague will help" (it already hands back to ARIA) |
| Session injector | "Back from …: Colleague needed (reason): notes" for ARIA, with the notes' topic |
| ARIA | `<from_internet_banking>`: on "Colleague needed", escalate in the same turn with the notes; no second consent; never back to the same assistant (except to verify) |
| Decision module | After ARIA escalates a colleague-needed return: the adviser gets the specialist's full notes; a mortgage keeps `topicCategory=mortgage_application` (the screen pop's application view) |
| Hand-back recovery | The app's mortgage form on chat goes to the form's mortgage assistant, not a colleague (a bug: on chat ARIA's hand-over always goes through recovery) |
| Overlay | "Specialist asked ARIA for a colleague" |

In this order (ARIA and the injector before any assistant can send "colleague needed"; the banking app last):

1. **Hand-back recovery**: `./scripts/deploy_handback_recovery.sh` (dry run), then `--apply`.
2. **Session injector**: code only, as in "Back to ARIA" step 1.
3. **Money Hub**: `./connect-money-hub/scripts/deploy_agent.sh` (the agent's prompt), and `deploy_bridge.sh` if not
   done for the hand-over marks.
4. **ARIA**: `create_agent.sh --update`, then `--update --apply`; the new version ARN in `config.json`; rebuild
   (`build_flows.py --config config.json`); re-import and publish **the module "ARIA - Decide hand-back"** (it
   changed), then the main flow.
5. **The dispute assistant** (Agentic CX designer, "Card dispute"): the `HandBackToARIA` Escalate message to "Of
   course."; paste the updated `CardDisputeAssistant` prompt (step 7, "say you'll get that sorted"); replace the
   `Escalation requested` exit description; build and deploy to the same environment. Then the Connect flow:
   `build_card_dispute_flow.py --application-id 0695e7ea-b8a9-4514-a3f0-eb65fabe9afe --alias 1jVQrqDoXSeGFTnPa7HKw
   --output connect-card-dispute/flows/card-dispute-flow.live.json`, import into "Card dispute assistant", publish.
6. **The mortgage assistant**: `HandToAdviser`'s Escalate message to "Of course." (GUIDE 4a), build and deploy. Then
   the Connect flow, generated (the same as GUIDE 6.8, v1.24, with the live assistant block unchanged):
   `python3 connect-bot-flow-modular/build_mortgage_handover_flow.py`, then import
   `connect-bot-flow-modular/flows/mortgage-live-sync-handover.json` into "Mortgage Live Sync handover", check the
   Agentic CX block still shows the application and environment, Save, **Publish**.
7. **The banking app**: `deploy_banking_app.sh --contact-flow-id 2b4f7b5c-1351-42c8-acac-add07d0cbd00`.

Check:
| Try | You should see |
|---|---|
| A dispute to complete | A summary, then "submit it yourself, or I can pass it to a colleague"; no colleague until you choose one |
| Choose a colleague | "Of course." then ARIA: passing you to a colleague; the adviser's screen pop has the dispute notes and reference |
| Mortgages → Chat → "can I speak to an adviser?" | "Of course." then ARIA escalates; the screen pop opens the mortgage application view |
| Money Hub → "I want to dispute a payment" | "Let's sort that out." (no colleague), then the disputes specialist |

## Afterwards

- **Changing ARIA v2** (prompt or tools):
  1. Edit `ai-agent/build_agent.py`, then run `python3 -m unittest discover -s connect-bot-flow-modular/tests`.
  2. Run `create_agent.sh --update` (dry run), then `--update --apply`. This changes only the prompt and agent
     tagged `project=connect-bot-flow-modular`, and publishes version 2, 3… Earlier versions stay as they are.
  3. Put the new version ARN in `config.json`, rebuild, and re-import and publish the main flow.

  `connect_collaborator.sh` changes only the live ARIA, never v2.
- **Changing routing:** edit `build_flows.py`, run the tests, rebuild, and re-import the flow or module that changed.
- **Card tools:** every card tool, including blocks, needs the customer's ID. Keep it in any new card tool.
- **The known Connect bug:** a chat hand-back with a collaborator on board crashes in Get customer input, and
  `aria-handback-recovery` covers it. When AWS fixes it (Support case), the recovery stops being called, and nothing
  needs changing.
