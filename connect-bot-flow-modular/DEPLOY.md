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
