# ARIA conversation bot flow, modular, with ARIA v2

Everything needed to stand up ARIA's conversation flow **fresh**, alongside the live one:
- a modular main flow and three flow modules (`flows/`, `modules/`);
- ARIA v2, the orchestration agent and its prompt (`ai-agent/`);
- the scripts that create them and switch on logging.

The business logic is the live flow's and the live ARIA's. The tests prove it against snapshots of both. Nothing
existing is changed.

```
MAIN FLOW  aria-conversation-bot-flow.json                    (every flow and module logs from its first block)
  Logging on
  [ARIA - Contact setup]          recording + Contact Lens analytics by channel, voice Amy, en-GB
  Check entry ─ web_widget   → Transfer: Mortgage Live Sync handover   (if it fails → ARIA)
              ├ card_dispute → entry=aria → Transfer: Card dispute assistant
              └ otherwise    ▼
  Connect assistant → save session                             (ARIA's Q in Connect session)
  [ARIA - Customer context]       session injector → customer context on the contact and in ARIA's session
  ARIA v2 (Lex) ─ timeout   → retry ARIA (×2, then end)
                ├ hand-back → copy ARIA's fields (lex*) ─┐
                └ error     → handbackOutcome=error ─────┤
                                                         ▼
  [ARIA - Decide hand-back]       sets handbackRoute + what the destination reads
  Route on handbackRoute ─ card_dispute      → Transfer: Card dispute assistant
                         ├ mortgage_livesync → Transfer: Mortgage Live Sync handover
                         ├ human             → Transfer: ARIA human handover → ARIA agent assist
                         ├ retry             → retry ARIA
                         └ end               → End
```

**Inside "ARIA - Decide hand-back"** (all of the live flow's decision blocks, in one place):

| ARIA's hand-back | What the module sets | handbackRoute |
|---|---|---|
| Escalate | topicCategory, escalationReason, customerIntent, conversationSummary | human |
| Complete + `card_dispute`, or StartCardDispute | handoverSummary, entry=aria | card_dispute |
| Complete + `mortgage_application`, or StartMortgageApplication, on a **chat** | topicCategory=mortgage_application, escalationReason=mortgage_application_chat, customerIntent, conversationSummary | human |
| the same, on a **call**, signed in | handoverSummary, buyerType, screenCode, entry=phone, cliMatched=true | mortgage_livesync |
| the same, on a call, not signed in | handoverSummary, buyerType, screenCode, entry=phone | end |
| Complete without a nextStep (Connect drops Complete's fields on calls) | asks `aria-handback-recovery` (whenNothing=end) | from its answer |
| a Lex error (Connect's chat crash with a collaborator) | asks `aria-handback-recovery` | from its answer, else retry |
| any other tool | — | end |

## What changed from the live flow, and why

| Change | Why | Business logic |
|---|---|---|
| **ARIA v2** for chats and calls (`${ARIA_AGENT_V2_ARN}`) | You're creating everything fresh. v2 = live ARIA v38's tools minus the unused QueryAssistant, and a prompt cleaned of instructions that can't run (`ai-agent/COMPARISON.md`) | same |
| **No agent-assist setting** in the Connect assistant block | Every route to a person goes ARIA human handover → **ARIA agent assist**, and that flow sets `my-agent-assistant-agent` for the adviser. The conversation bot flow's setting was overwritten there anyway | none for advisers |
| **One Connect assistant block** (live has two) | With no agent-assist setting the two were identical. One, before the injector, is the pattern AWS documents; retries go straight back to ARIA | same routes |
| **Logging switched on in every module** | Logging carries into later flows, but a module reused elsewhere would otherwise go unlogged | — |
| Working attributes **`lex*`, `handbackOutcome`, `handbackRoute`** | Never collide with the `aria*` attributes the human handover flow sets | — |

The equivalence test still runs the live flow and this one through 24,640 scenarios. Every one ends the same way:
the same transfer or disconnect, the same attributes for the destination, the same number of ARIA turns.

## Impact of the card-block scoping on this folder

The card Lambdas now refuse a block without `customer_id`.
- **ARIA v2** is built from **live v38**, so both block tools require `customer_id`, exactly as live. Its prompt says
  card tools use the session's customerId.
- **The modular flow** uses ARIA v2, so its card blocks work. (Don't point it at live v37, which doesn't send the ID.)
- **Nothing else** in the folder names an agent version. The recovery Lambda and the session injector are
  agent-neutral, and v2 gets the same security profiles as the live ARIA, including the one that lets it bring in
  the Money Hub agent.

## What's logged, and where

| What | Where | Set by |
|---|---|---|
| Every block a contact passes through, in the flow and every module, with Lambda results and errors (`ErrorDetails`) | CloudWatch `/aws/connect/conversationalbot` (the instance's flow logs) | Set logging behavior, first block of each flow and module |
| Call recording; Contact Lens on calls (real-time, ARIA conversation, sentiment, summaries) and chats (Contact Lens, sentiment, summaries) | Contact Lens, contact records | ARIA - Contact setup |
| ARIA's turns: model input and output, **tool calls and results**, Money Hub hand-offs | CloudWatch `/aws/vendedlogs/connect/ai-agents/<assistant>` | **`ai-agent/enable_ai_agent_logging.sh --apply`** (off today) |
| ARIA's traces, per contact | `qconnect ListSpans`, and Contact details → Automated interaction | always on |
| ARIA's tool Lambdas, session injector, hand-back recovery | Each Lambda's CloudWatch log group | always on |
| The Lex bot's own errors | The flow log, Get customer input block (`ErrorDetails`) | always on (the bot is Connect-managed, so Lex conversation logs are locked) |
| Bot conversations: success, failure, drops, turns | Connect: Routing → Flows → Bots → coversatonalaibot → **Analytics**; Analytics → Dashboards → **Flows and conversational bot performance** | Bot Analytics and Transcripts (instance setting) |
| Which way each hand-back went | Contact attributes `handbackOutcome`, `handbackRoute`, `lex*` on the contact record | the main flow and decision module |

## Files

| File | What |
|---|---|
| `flows/aria-conversation-bot-flow.json` | Main flow (Inbound flow) |
| `modules/aria-contact-setup.json` | Flow module: ARIA - Contact setup |
| `modules/aria-customer-context.json` | Flow module: ARIA - Customer context |
| `modules/aria-decide-handback.json` | Flow module: ARIA - Decide hand-back |
| `build_flows.py` | Writes the four files. Edit this, not the JSON |
| `config.json` | The three module ARNs and ARIA v2's version ARN, once they exist |
| `ai-agent/` | ARIA v2: prompt, agent, `create_agent.sh`, `enable_ai_agent_logging.sh`, the review |
| `reference/conversation-bot-flow-live.json` | The live flow, read 18 Oct 2026 |
| `tests/` | Equivalence with the live flow and live ARIA; importability; logging and analytics |
| `manifest.md`, `placeholders.md`, `assumptions.md` | What's what, what to fill in, what was assumed |

## Create everything

From the repo root. The scripts use the AWS CLI, plus the boto3 in `~/.venvs/aria-deploy` for the AI agent calls (the CLI's model doesn't know the collaborator setting yet):

1. **Logging first**, so the first test is recorded:
   ```bash
   ./connect-bot-flow-modular/ai-agent/enable_ai_agent_logging.sh            # dry run
   ./connect-bot-flow-modular/ai-agent/enable_ai_agent_logging.sh --apply
   ```
   The Lex bot is Connect-managed, so its logging is in Connect's bot analytics, not Lex (DEPLOY.md 1b).
2. **ARIA v2:**
   ```bash
   ./connect-bot-flow-modular/ai-agent/create_agent.sh                       # dry run
   ./connect-bot-flow-modular/ai-agent/create_agent.sh --apply
   ```
   Copy the `ARIA v2: arn:…:<version>` it prints.
3. **The three modules.** For each, in the Connect admin website:
   1. Go to **Routing → Flows → Modules → Create flow module**.
   2. Use **Import** and choose the file.
   3. Name it as in the table below, **Save**, then **Publish**.
   4. Copy its ARN (it ends `/flow-module/<id>`).

   | File | Name |
   |---|---|
   | `modules/aria-contact-setup.json` | ARIA - Contact setup |
   | `modules/aria-customer-context.json` | ARIA - Customer context |
   | `modules/aria-decide-handback.json` | ARIA - Decide hand-back |

4. **Fill in the ARNs:** paste the three module ARNs and ARIA v2's ARN into `config.json`, then:
   ```bash
   python3 connect-bot-flow-modular/build_flows.py --config connect-bot-flow-modular/config.json
   python3 -m unittest discover -s connect-bot-flow-modular/tests
   ```
   The build prints anything still to fill in. Don't import until it prints nothing.
5. **The main flow:**
   1. Go to **Routing → Flows → Create flow** and choose **Inbound flow**.
   2. Use **Import** and choose `flows/aria-conversation-bot-flow.json`.
   3. Name it **ARIA conversation bot flow (modular)**, then **Save** and **Publish**.
   4. Note its flow ID.

## Test it without touching the live flow

```bash
python3 connect-banking-app/scripts/local_preview.py --talk <instance-id> <modular flow id>
```

Then run through these:
- a dispute from Cards;
- a mortgage application on a call from the Money Hub (with the code);
- blocking a card;
- a Level 3 payment request;
- asking for a person (check the adviser's assist panel is the agent-assist agent);
- a goodbye.

For each, the flow log shows readable block names (`decideHandback`, `routeHandback`…), ARIA's event logs show her
tool calls, and Contact Lens has the conversation.

## Switching over (when you're ready)

Point the banking app (`deploy_banking_app.sh --contact-flow-id <modular flow id>`), the Money Hub page, the
mortgage widget and any phone numbers or flows that transfer in at the modular flow. Keep the old flow and the live
ARIA unchanged for rollback.

## When something changes

- **ARIA v2's prompt or tools:** edit `ai-agent/build_agent.py`, run the tests, then `create_agent.sh --update
  --apply`. It changes only ARIA v2 (tagged `project=connect-bot-flow-modular`) and publishes a new version. Put the new version ARN in `config.json`, rebuild, and re-import the main
  flow. (`connect-money-hub/scripts/connect_collaborator.sh` only changes the live ARIA.)
- **A routing change:** edit `build_flows.py`. If the live flow changed too, refresh the reference first:
  ```bash
  aws connect describe-contact-flow --instance-id <instance-id> \
      --contact-flow-id f6d6545f-c9ae-4ca4-a4d8-6fdc8ba0494f --query ContactFlow.Content --output text \
      | python3 -m json.tool > connect-bot-flow-modular/reference/conversation-bot-flow-live.json
  ```
