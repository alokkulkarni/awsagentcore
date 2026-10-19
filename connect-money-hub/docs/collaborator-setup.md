# Making the Money Hub agent ARIA's collaborator

This page explains what `scripts/connect_collaborator.sh` does, and where each of its settings lives in
Amazon Connect Customer. Read it before you run the script for the first time, or when a hand-over to the Money
Hub agent stops working.

## Contents

- [The short version](#the-short-version)
- [What a collaborator is](#what-a-collaborator-is)
- [Where the settings live](#where-the-settings-live)
- [Before you run the script](#before-you-run-the-script)
- [How to run it](#how-to-run-it)
- [What the script does, step by step](#what-the-script-does-step-by-step)
- [After the script: the flow](#after-the-script-the-flow)
- [Hand-overs while ARIA has collaborators](#hand-overs-while-aria-has-collaborators)
- [When Connect loses a chat hand-back](#when-connect-loses-a-chat-hand-back)
- [How to look at each setting](#how-to-look-at-each-setting)
- [What is set up today](#what-is-set-up-today)
- [Things that stop the hand-over](#things-that-stop-the-hand-over)
- [How to undo it](#how-to-undo-it)

---

## The short version

- **There is no console screen for adding a collaborator.** AWS documents it as an API-only feature
  ([Set up an external AI agent integration](https://docs.aws.amazon.com/connect/latest/adminguide/a2a-setup-external.html)).
  That is why there is a script.
- The script makes **five settings in four AWS services**, in the order AWS's guide gives. It shows what it
  would do first, and changes nothing until you add `--apply`.
- At the end it prints **an ARIA version number**. You then choose that version in `conversation bot flow`,
  which *is* done in the console.
- **Don't save ARIA in the AI agent designer afterwards.** The designer's Save can replace ARIA's security
  profiles, and that silently stops the hand-over.

---

## What a collaborator is

ARIA is the bank's Connect AI agent (its name in Connect is `my-conversation-agent`). It talks to every
customer. A **collaborator** is another agent that ARIA can bring into the conversation.

The Money Hub agent is an **external** collaborator: it runs outside Connect, on Amazon Bedrock AgentCore.
Connect reaches it over the A2A (agent-to-agent) protocol through our **bridge** Lambda.

It is set up to **talk to the customer**. When a customer asks about their money, ARIA hands the conversation
over. The Money Hub agent answers until it is done, then hands back with a reason. On a call, Connect turns its
text into speech in ARIA's voice, so the customer never notices the change.

For a hand-over to work, five things must line up:

```
 ARIA's configuration           "Money Hub is a collaborator; hand over when…"      (qconnect AI agent)
        │
        ▼
 ARIA's security profiles       "ARIA is allowed to use the aria-money-hub app"     (Connect security profile)
        │
        ▼
 The A2A application            "aria-money-hub lives at this https address,         (AppIntegrations)
        │                         and its key is in this secret"
        ▼
 The instance association       "this Connect instance may use that application"    (Connect integration)
        │
        ▼
 The bridge Lambda  ──►  Money Hub agent on AgentCore
```

If any link is missing, Connect refuses the hand-over before it reaches the bridge, and the bridge log is
empty.

---

## Where the settings live

| # | Setting | Lives in | Can you see it in the console? |
|---|---|---|---|
| 0 | The bridge's API key (made by `deploy_bridge.sh`, not this script) | **Secrets Manager**: `aria-money-hub/a2a-api-key`, encrypted with its own KMS key | Yes: AWS console → Secrets Manager. Don't open the value |
| 1 | **The A2A application**: the bridge's address, and which secret holds its key | **AppIntegrations** application `aria-money-hub`, type `A2A_SERVER` | No. Use the [commands below](#how-to-look-at-each-setting) |
| 2 | **The instance association**: lets your Connect instance use that application | **Connect** integration association (type `APPLICATION`) | No. Use the commands below |
| 3 | **The collaborator itself**: which application, when to hand over, text rather than audio | **ARIA's configuration** in Connect AI agents (the qconnect API), in the list `multiAgentConfigurations` | No. The AI agent designer has no section for external collaborators |
| 4 | **The security profile** `ARIA AI agent collaborators`: allows the application as a `THIRD_PARTY` AI agent, and gives the *Access Contact Control Panel* permission | **Connect** security profile, linked to ARIA and to each ARIA version | Partly. Connect admin website → **Users** → **Security profiles** shows the profile and its CCP permission. The allowed application is set and read only through the API. ARIA's edit page in the AI agent designer shows which profiles ARIA has |
| 5 | **A published ARIA version** that carries all of the above | **Connect AI agents**: `my-conversation-agent`, version N | Yes: Connect admin website → **AI agent designer** → **AI agents** → `my-conversation-agent` lists its versions |
| 6 | **The flow uses version N** (done by you, not the script) | **Connect flow** `conversation bot flow` | Yes: Connect admin website → **Routing** → **Flows**. See [After the script](#after-the-script-the-flow) |

> **Why "Access Contact Control Panel"?** Without it, Connect doesn't send the bridge the contact's details
> (the customer's phone number or chat, and the channel). The bridge uses them to look up who the customer is
> and whether they are verified.

---

## Before you run the script

Check each of these:

| Need | How to check |
|---|---|
| The bridge is deployed | `deploy_bridge.sh` has run and printed a **Bridge address**. The script stops if it finds no Function URL or no secret |
| AWS CLI **2.27 or newer** | `aws --version`. Older CLIs lack `--auth-config` and `--allowed-ai-agents`. If an older CLI comes first on your PATH and a newer one is installed (often `~/.local/bin/aws`), the script finds and uses the newer one |
| Signed in to account `395402194296` | `aws sts get-caller-identity`. The script stops if you are signed in elsewhere |
| ARIA's new prompt (and any guardrail change) is **published** | README step 5. The script points ARIA at the newest published version of each |
| The instance is on the **Connect Customer** tier | Agent-to-agent collaboration isn't available on Customer Basic. The script tells you if this is the problem |
| A Lex bot with `AMAZON.QInConnectIntent` | Already in place: it is the bot in `conversation bot flow` |

---

## How to run it

Run these from the repository's top folder.

**1. Dry run** (changes nothing; shows what it would do):

```bash
./connect-money-hub/scripts/connect_collaborator.sh
```

**2. Do it:**

```bash
./connect-money-hub/scripts/connect_collaborator.sh --apply
```

It ends with **ARIA version to use: N** and `Linked:` lines. Write N down.

**3. Check at any time** (only reads):

```bash
./connect-money-hub/scripts/connect_collaborator.sh --check --version N
```

**Options**

| Option | What it does |
|---|---|
| *(none)* | Dry run: prints each change as `[would run] …` |
| `--apply` | Makes the changes |
| `--check` | Only reads. Confirms ARIA is linked to all its profiles and the profile allows the application. Add `--version N` to check that version too. If anything is missing, it prints the exact command to fix it |
| `--prompt-version N` | Points ARIA at prompt version N instead of the newest |
| `--guardrail-version N` | Points ARIA at guardrail version N instead of the newest |
| `--keep-versions` | Leaves ARIA's prompt and guardrail versions as they are |
| `--remove` | Takes the Money Hub collaborator off ARIA (with `--apply`). See [How to undo it](#how-to-undo-it) |
| `--region`, `--account-id`, `--instance-id`, `--assistant-id`, `--aria-agent-id` | Target a different setup. The defaults are this account's eu-west-2 instance and ARIA |

**It is safe to run again.** Each step first looks for what it would create, and reuses it if it exists.
Running `--apply` again adds the collaborator once, never twice, and publishes a fresh ARIA version.

---

## What the script does, step by step

The script's numbers match its output, and AWS's guide.

### Before step 1: checks

- `aws` and `python3` are installed, and the CLI is new enough (see above).
- You are signed in to the right account.
- The bridge exists: it reads the bridge Lambda's **Function URL** and the **secret's ARN** (never the secret's
  value).

### Step 1: register the bridge as an A2A application

**What:** creates an AppIntegrations application named `aria-money-hub`:

| Field | Value |
|---|---|
| Type | `A2A_SERVER` (this can't be changed later) |
| Address | the bridge's Function URL (`https://…lambda-url.eu-west-2.on.aws/`) |
| Authentication | `API_KEY`, pointing at the secret `aria-money-hub/a2a-api-key` |

**Why:** this is how Connect knows where the agent is and how to prove it is Connect. On every request,
Connect reads the key from the secret and sends it as `Authorization: Bearer …`. The bridge refuses anything
without it.

**If it already exists:** the script uses it and changes nothing.

> If the bridge's address ever changes, this application must change too. The script doesn't update an
> existing application.

### Step 2: associate the application with the Connect instance

**What:** `connect create-integration-association`, type `APPLICATION`.

**Why:** an application only becomes usable by an instance once it is associated with it.

**If it is already associated:** nothing changes.

### Step 3: add the collaborator to ARIA

This is the step that makes the Money Hub agent a collaborator.

1. **Reads ARIA's whole configuration** and saves a copy in
   `connect-money-hub/scripts/backups/aria-before-money-hub-<date-time>.json`. A dry run saves one too.
2. **Chooses the prompt and guardrail versions.** By default, the newest published version of each. The
   output shows the change, for example `Prompt version: 22 -> 25`.
3. **Adds one entry** to ARIA's list of collaborators (`collaborator.py` builds it):

   ```json
   {
     "handoffAgentConfiguration": {
       "agentTarget": { "applicationId": "<the aria-money-hub application's ID>" },
       "instruction": { "instruction": "Hand the conversation to this agent when a verified customer (Level 2 or above) wants to understand their own money … Do not use it for payments, disputes, cards or products." },
       "audioStreamingEnabled": false,
       "immediateHandoff": false
     }
   }
   ```

   | Field | Meaning |
   |---|---|
   | `handoffAgentConfiguration` | The collaborator **talks to the customer** (rather than doing a job behind the scenes and reporting back, which would be `delegateAgentConfiguration`) |
   | `instruction` | What ARIA reads to decide **when** to hand over. It also tells ARIA what a hand-back means |
   | `audioStreamingEnabled: false` | Text only. On a call, Connect does the speech-to-text and text-to-speech, in ARIA's voice |
   | `immediateHandoff: false` | ARIA decides when to hand over, from the instruction. It doesn't hand over on the first turn |

4. **Sends the whole configuration back** with `qconnect update-ai-agent`. That call replaces everything, so
   the script sends ARIA's existing tools, prompt, guardrail and any other collaborators back unchanged, with
   the one entry added. The output shows `Collaborators before: N  after: N+1`.

**Why the script sets the prompt and guardrail versions itself:** the AI agent designer's **Save** doesn't
reach the configuration this API reads. A version published by the script would otherwise keep old prompt
and guardrail versions.

**If the collaborator is already there:** the old entry is replaced by the new one, never duplicated.

### Step 4: the security profile

**What:**

1. Creates the security profile **`ARIA AI agent collaborators`** if it doesn't exist.
2. Sets its permissions to **Access Contact Control Panel** (`BasicAgentAccess`) and its allowed AI agents to
   the `aria-money-hub` application, type `THIRD_PARTY`.
3. Links the profile to ARIA (the unversioned ARIA).

**Why:** Connect checks, at the moment of hand-over, that one of ARIA's security profiles allows the
application. Without it Connect refuses the hand-over, and on chat the conversation ends.

> **This step sets the profile's lists rather than adding to them.** If you later allow other external agents
> or give other permissions on this same profile, running the script again removes them. Keep this profile
> for the Money Hub only.

### Step 5: publish a new ARIA version

**What:**

1. `qconnect create-ai-agent-version` publishes ARIA as a new numbered version.
2. **Links every one of ARIA's security profiles to that version**, plus `ARIA AI agent collaborators`. Today
   that is `Admin`, `Agent` and `ARIA AI agent collaborators`.
3. Checks the links (the same check as `--check`) and prints `Linked:` lines.

**Why step 2 matters:** a version published through the API starts with **no security profiles**. `Admin`
and `Agent` carry the permissions for ARIA's banking tools. Without them every tool call fails and the flow
hangs up. Without the collaborators profile the hand-over fails.

**Why publish at all:** changes to ARIA take effect only in a published version, and the flow names a version.

---

## After the script: the flow

This part is in the console. Connect admin website → **Routing** → **Flows** → `conversation bot flow`:

0. First, if it isn't there yet, add the `nextStep` check in
   [Hand-overs while ARIA has collaborators](#hand-overs-while-aria-has-collaborators). Without it, a card
   dispute or mortgage application ends the conversation instead of reaching its assistant.
1. The **Connect assistant** block that names `my-conversation-agent`: choose version **N**. Save.
2. The **Get customer input** block → **Session attributes** → `x-amz-lex:q-in-connect:ai-agent-arn`: change
   only the number at the end to **N**. Save.
3. **Save** the flow, then **Publish**.

The Money Hub hand-over and hand-back happen inside ARIA's own conversation in that Get customer input block.

---

## Hand-overs while ARIA has collaborators

**What changes.** Once ARIA has a collaborator, Connect gives the contact back to the flow only through her
reserved **Complete** and **Escalate** tools
([How agent-to-agent collaboration works](https://docs.aws.amazon.com/connect/latest/adminguide/a2a-how-it-works.html)).
Her own hand-over tools, `StartCardDispute` and `StartMortgageApplication`, still run, but nothing hands the
contact back: Get customer input ends in **Error** and ARIA carries on. On 16-17 October every card dispute
started after the Money Hub collaborator was added failed this way. ARIA's traces show it: `Complete` ends with a
`return_to_agent` step, and `StartCardDispute` ends with nothing.

**The fix.** ARIA hands over with **Complete**, and its `nextStep` says where the customer goes:

| `nextStep` | Also sends | Where the flow sends them |
|---|---|---|
| `none` | `reason` | Disconnect, as before |
| `card_dispute` | `handoverSummary` | Card dispute assistant |
| `mortgage_application` | `handoverSummary`, `buyerType`, `screenCode` | Mortgage assistant |

The fields have the same names the old tools used, so the flow's existing blocks read them unchanged.
`scripts/handovers.py` holds the new Complete tool and the prompt changes. The script and the prompt builder
both use it.

**Do these in this order:**

1. **ARIA's prompt.** Run `python3 connect-money-hub/scripts/build_aria_prompt.py`. Paste the whole of
   `prompts/aria-prompt-with-money-hub.yaml` into ARIA's AI prompt (`ARIA-Banking-Ochestration-Prompt`), then
   save and publish it. It changes three things: the dispute step calls Complete with `card_dispute`, a short
   `<mortgage_applications>` section is added, and the "no Complete when handing over" rules say these two
   hand-overs are the exception.
2. **The flow.** In `conversation bot flow`, find the **Check contact attributes** block that checks
   `$.Lex.SessionAttributes.Tool` (it has branches for Escalate, Complete, StartMortgageApplication and
   StartCardDispute):
   1. Disconnect the **Complete** branch from its **Disconnect** block.
   2. Add a new **Check contact attributes** block: **Namespace** Lex, **Key** Session attributes,
      `nextStep`. Add the conditions **Equals** `card_dispute` and **Equals** `mortgage_application`.
   3. Connect **Complete** to the new block.
   4. `card_dispute` goes to the existing **Set contact attributes** block on the StartCardDispute branch
      (the one that sets `handoverSummary` from Lex and `entry` = `aria`).
   5. `mortgage_application` goes to the existing **Check contact attributes** block on the
      StartMortgageApplication branch (the one that checks the channel).
   6. **No match** goes to the Disconnect block that Complete used to go to.
   7. Leave the StartCardDispute and StartMortgageApplication branches where they are. They're harmless, and
      older ARIA versions still use them.
   8. **Save** and **Publish**. This is safe before step 3: today's ARIA never sends `nextStep`, so Complete
      still disconnects.
3. **ARIA's tools.** Run `connect_collaborator.sh --apply`. It keeps the Money Hub collaborator, swaps the two
   old tools for the new Complete, picks up the prompt you published in step 1, and prints a new version.
4. **Point the flow at that version**, in both places ([After the script](#after-the-script-the-flow)).

**How to tell it worked.** Start a chat from any page, say you don't recognise a card payment, and you should
be with the card dispute assistant. In the flow log for that contact, the new block shows `nextStep` as
`card_dispute`. If it's empty, the flow isn't receiving Complete's fields: tell whoever maintains this, and
put the previous ARIA version back in the flow.

---

## When Connect loses a chat hand-back

**The defect.** While ARIA has a collaborator, every time she hands a **chat** back to the flow (Complete,
Escalate, or a hand-over tool), Amazon Connect's Get customer input block fails with:

```
java.lang.NullPointerException: Cannot invoke "java.util.Map.size()" because "m" is null
```

The flow takes the block's **Error** branch, loops back to ARIA, and never sees what she decided. ARIA herself
works correctly: her trace shows the tool call and the hand-back. Calls aren't affected. Every chat hand-back since
the collaborator was added (16 October, about 13:09 UTC) has failed this way, including **chat escalations to a
person**. Seen on contacts 4b92f201, 490cdc10, 2ee92d10, 43d38809 and 77a28b4d. Raise it with AWS Support with
those contact IDs and the error text; the recovery below is a detour until it's fixed.

**The recovery.** `aria-handback-recovery` (`scripts/lambdas/handback_recovery.py`) runs on that Error branch:
1. It reads ARIA's trace for the chat, through the contact's `sessionId` attribute.
2. It finds a hand-back from the last 90 seconds that hasn't been handled yet.
3. It sets the contact attributes the next blocks need: `handoverSummary` and `entry` for a dispute;
   `topicCategory`, `escalationReason`, `customerIntent` and `conversationSummary` for an escalation.
4. It returns `route`:

| `route` | When | Goes to |
|---|---|---|
| `card_dispute` | Complete `card_dispute`, or StartCardDispute | Transfer to flow "Card dispute assistant" |
| `escalate` | Escalate; or a mortgage application (escalated in chat, as the flow already does) | the escalation Transfer to flow |
| `end` | Complete `none` | Disconnect |
| `none` | nothing to recover, or anything went wrong | the Loop block, exactly as today |

It never invents a decision. It ignores a hand-back it has already handled (`handledHandback` attribute), and one
older than 90 seconds.

**Deploy it:** run `./scripts/deploy_handback_recovery.sh` (dry run), then add `--apply`.

**Then, in `conversation bot flow`:**
1. Find ARIA's **Get customer input** block, the one with the `x-amz-lex:q-in-connect:ai-agent-arn` session
   attribute. Its **Error** output goes to a **Loop** block today. Note that Loop block; you reconnect to it in
   step 4.
2. Delete the line from **Error** to the Loop block. Leave its **Timeout** output alone.
3. Add an **Invoke AWS Lambda function** block:
   - Function: `aria-handback-recovery`
   - Timeout: **8** seconds
   - Response validation: **STRING_MAP**
   - Connect the Get customer input block's **Error** output to it.
4. Add a **Check contact attributes** block: **Namespace** External, **Key** `route`, with the conditions
   **Equals** `card_dispute`, **Equals** `escalate` and **Equals** `end`. Connect the Lambda block's **Success** to
   it. Then connect:
   - `card_dispute` → the existing **Transfer to flow** "Card dispute assistant" (the one after the Set contact
     attributes block that sets `entry` = `aria`)
   - `escalate` → the existing **Transfer to flow** that the Escalate branch reaches (after its Set contact
     attributes block)
   - `end` → a **Disconnect** block (the one Complete's **No match** goes to)
   - **No match** → the Loop block from step 1
5. Connect the Lambda block's **Error** to the Loop block from step 1 as well.
6. **Save** and **Publish**.

**How to tell it worked.** In a chat, say you don't recognise a card payment. ARIA says "Let's sort that out for
you." and, a few seconds later, the card dispute assistant takes over. In the flow log for that contact, Get
customer input still shows **Error**; the recovery block's `route` shows `card_dispute`. If it shows `none`, ARIA's
trace wasn't there in time: look at the Lambda's log in CloudWatch (`/aws/lambda/aria-handback-recovery`).

---

## How to look at each setting

These commands only read. Run them from Terminal (region `eu-west-2`).

```bash
# 1. The A2A application: its type and the bridge's address
aws appintegrations list-applications --region eu-west-2 \
  --query "Applications[?Name=='aria-money-hub']"

# 2. The instance association
aws connect list-integration-associations --region eu-west-2 \
  --instance-id f969d4b4-f716-4974-a325-bb7899f2f293 --integration-type APPLICATION

# 3. ARIA's collaborators, prompt and guardrail
aws qconnect get-ai-agent --region eu-west-2 \
  --assistant-id e6991ed4-e11c-4194-8d20-13889a36bd15 --ai-agent-id 68179bd0-78d7-4298-8696-b3817a93b6c2 \
  --query "aiAgent.configuration.orchestrationAIAgentConfiguration.[orchestrationAIPromptId, orchestrationAIGuardrailId, multiAgentConfigurations]"

# 4 and 5. Everything about the profile and ARIA's links, in one go
./connect-money-hub/scripts/connect_collaborator.sh --check --version N
```

In the console:

| To see | Go to |
|---|---|
| ARIA's versions | Connect admin website → **AI agent designer** → **AI agents** → `my-conversation-agent` |
| The collaborators profile and its CCP permission | Connect admin website → **Users** → **Security profiles** → `ARIA AI agent collaborators` |
| Which version the flow uses | Connect admin website → **Routing** → **Flows** → `conversation bot flow` → the Connect assistant block |
| Whether hand-overs reach the bridge | CloudWatch → Log groups → `/aws/lambda/aria-money-hub-bridge` |

---

## What is set up today

Read from AWS on 17 October 2026:

| Setting | Value |
|---|---|
| A2A application | `aria-money-hub` (ID `e72fd4c4-ab42-4906-8874-45943c301013`), type `A2A_SERVER` |
| Its address | the bridge's Function URL, `https://bcndcza6wuib2ua433zvuwmh640rvrxu.lambda-url.eu-west-2.on.aws/` |
| Instance association | present |
| ARIA's collaborators | one: the Money Hub, talks to the customer, text, ARIA decides when |
| ARIA's prompt and guardrail | prompt version 25, guardrail version 3 |
| ARIA's security profiles | `Admin`, `Agent`, `ARIA AI agent collaborators` |
| Collaborators profile | permission: Access Contact Control Panel |
| Newest ARIA version | 35 |

---

## Things that stop the hand-over

| What happens | Why | What to do |
|---|---|---|
| Hand-overs stop after someone edits ARIA in the AI agent designer | The designer's Save can replace ARIA's security profiles | Run `--check --version N`. It prints the fix. Or publish your prompt change, then run the script with `--apply` again and use the version it prints |
| ARIA's tools all fail on a new version | The version was published without `Admin` and `Agent` (for example, from the console or by hand) | Run `--check --version N` and run the commands it prints |
| ARIA uses an old prompt or guardrail | A version was published without the script setting the versions | Run the script again. Check the `Prompt version: X -> Y` line |
| The chat ends just after ARIA says it can help, and the bridge log is empty | Connect refused the hand-over: a missing profile link, or a profile that doesn't allow the application | `--check --version N` |
| Hand-overs stop for new contacts, with no error | Connect disables an external agent that doesn't send trace data on every turn. The bridge sends it, but a bridge change that broke tracing would cause this | Check the bridge log for `TRACING_SPAN` errors; redeploy a working bridge |
| A message about the tier | The instance isn't on Connect Customer | Collaboration needs that tier |
| ARIA says "Let's sort that out for you." but the dispute assistant never joins, and the flow log shows Get customer input **Error** | ARIA is using `StartCardDispute` while she has a collaborator | [Hand-overs while ARIA has collaborators](#hand-overs-while-aria-has-collaborators) |

---

## How to undo it

**Quickest, and safest:** in `conversation bot flow`, put back the ARIA version you used before, in both
places (see [After the script](#after-the-script-the-flow)), then publish. Nothing else needs to change; the
newer versions just aren't used.

**To take the collaborator off ARIA:**

```bash
./connect-money-hub/scripts/connect_collaborator.sh --remove --apply
```

This removes the Money Hub entry from ARIA's configuration and publishes a new version. It leaves the A2A
application, the association and the profile in place, so adding it back later is quick.

> **Before you use that version,** link ARIA's profiles to it: in `--remove` mode the script doesn't copy them,
> so ARIA's banking tools would fail. Run `--check --version N` and then the commands it prints. Or use the
> flow method above instead.

To delete everything, see the README's **How to undo it**.
