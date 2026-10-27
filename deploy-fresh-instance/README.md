# deploy-fresh-instance

One interactive script that builds the whole ARIA system in a **new AWS account** on a **new Amazon Connect instance**:
the instance and its queues, Q in Connect with the bank's knowledge base, the Lex bot, the MCP gateway and every tool
on it (banking, Money Hub, disputes, branches and appointments, queue status), every Lambda, table and role, every
contact flow and module, Money Hub with its A2A collaborator, card disputes, the mortgage Live Sync backend and
reference page, the agentic CX designer apps, ARIA v2 and the advisers' AI agents, the screen pop, the banking app, and
a final read-back.

Every step says what it makes and why, shows the exact command, and asks `[y]es / [s]kip / [q]uit` before running
it. Its output follows straight away. IDs are saved as they're made, so you can stop and carry on later.

> **Not yet run end to end.** Every piece is tested offline (see *Checks*), and each wraps the repo's own deploy
> scripts or the AWS APIs they use, but the whole sequence hasn't been run against a real new account. Run it in a
> sandbox account first and expect to fix the odd step. Each step can be re-run on its own.

## Before you start (once)

1. **A new, empty AWS account.** The script refuses the account today's system runs in, and any account
   that already has `aria-*` or `mortgage-livesync-*` resources: every script uses fixed names and would
   quietly reuse them.
2. **Sign in to it** with the AWS CLI (`aws sso login --profile …`).
3. **Bedrock model access** in that account and region: open Bedrock → *Model access* once and accept any terms
   Anthropic asks for. The run uses Titan text embeddings v2 (knowledge base), Claude Sonnet 4.5 (ARIA), Claude
   Sonnet 5 (agent assist) and Claude Haiku 4.5 (briefing, Money Hub).
4. **Tools:** bash 4+ (`brew install bash`; macOS ships 3.2), AWS CLI 2.38+, Python 3 with a current boto3
   (`pip install -U boto3`), node 20+ and npm, AWS SAM CLI, docker with buildx, jq, zip, curl, openssl. The first
   step checks them all.
5. **Checkouts of `connect-livesync-mortgage`** (the mortgage backend and reference page are deployed from it) and
   **`branchtransfercalldesign`** (ARIA's branch finder and appointment tools, and agent assist's queue-status tool,
   are deployed from its `backend/`). Set `MORTGAGE_REPO` and `BRANCH_REPO` in your config.
6. **Today's designer apps** (the mortgage and card dispute assistants) are read from today's workspace with its own
   API key and written to `templates/acxd` (secret *names* only, never values). If `templates/acxd` isn't there, the
   `designer-access` step does this first and asks for today's key. To do it beforehand instead:

   ```bash
   $(brew --prefix)/bin/bash /path/to/deploy-fresh-instance/deploy.sh --config today.env capture-acxd
   ```

   Commit `templates/acxd` afterwards, so the next fresh deploy doesn't need today's key.

## Run it

1. Copy the example config:

   ```bash
   cp /Users/alokkulkarni/Documents/Development/awsagentcore/deploy-fresh-instance/config.example.env /Users/alokkulkarni/Documents/Development/awsagentcore/deploy-fresh-instance/my-instance.env
   ```

2. In `/Users/alokkulkarni/Documents/Development/awsagentcore/deploy-fresh-instance/my-instance.env`, set
   `AWS_PROFILE` (the new account), `REGION` and `INSTANCE_ALIAS`. `MORTGAGE_REPO` and `BRANCH_REPO` already default
   to your checkouts.
3. Sign in to the new account, then run:

   ```bash
   $(brew --prefix)/bin/bash /Users/alokkulkarni/Documents/Development/awsagentcore/deploy-fresh-instance/deploy.sh --config /Users/alokkulkarni/Documents/Development/awsagentcore/deploy-fresh-instance/my-instance.env
   ```

4. The last step lists each piece as OK or MISSING, including all 15 gateway targets and each agent's tool count,
   and prints where to start.

| Command | Does |
|---|---|
| `deploy.sh --config F` | every step, asking before each (steps already done are passed over) |
| `deploy.sh --config F --list` | the steps in order, with which are done |
| `deploy.sh --config F --from flows-fill` | carry on from a step |
| `deploy.sh --config F --only aria-agent` | run one step again, even one that's done |
| `deploy.sh --config F --yes` | don't ask before each step (console pauses still ask) |

Allow about 2 hours, most of it waiting (the instance, the Money Hub image, the gateway, two CloudFront builds, the
designer builds).

## The steps

| Phase | Steps | What they make |
|---|---|---|
| 0 Preflight | `preflight` | Checks the account, that nothing is in the way, and the tools |
| 1 Connect instance | `instance`, `queues`, `admin-user` | The instance (flow logs, Contact Lens, multi-party, storage), today's queues by name in the Basic Routing Profile, the first admin user |
| 2 Q in Connect | `assistant`, `knowledge-base`, `guardrail`, `ai-logging` | The assistant (domain), the bank's knowledge base on Bedrock with S3 Vectors, ARIA's guardrail, AI agent event logs |
| 3 Lex | `lex-bot` | The bot with the Q in Connect intent, on the instance |
| 4 Tools and core Lambdas | `gateway`, `mock-data`, `mcp-app`, `injector`, `handback-recovery`, `routing`, `branch-tools` | The MCP gateway and 10 tool Lambdas, the demo data switch, the MCP server integration, the session injector (with the bank data), hand-back recovery, routing lookup (re-pointed at the new queues), the branch-info, branch-appointments and queue-status tools (tables, sample branches, roles, Lambdas, gateway targets) |
| 5 Flows | `flow-shells` | Every flow and module as a placeholder, for their IDs (they refer to each other in a circle) |
| 6 Money Hub, disputes, mortgage | `money-hub` … `web-urls` | Money Hub page, agent, A2A bridge and warmer, its collaborator integration; the card dispute service and pages; the mortgage stack and its reference page (`mortgage-web`); tool permissions for every gateway tool; the agent-assist Lambda |
| 7 Agentic CX designer | `designer-access`, `designer-apps`, `touchpoint-keys` | Access to the new workspace, the mortgage and card dispute assistants rebuilt and deployed, their Touchpoint keys |
| 8 AI agents | `aria-agent`, `assist-agents` | ARIA v2 (23 gateway tools including branches and appointments, knowledge base search pinned to the new assistant, guardrail, Money Hub collaborator) and the advisers' agent-assist and briefing agents |
| 9 Flows | `flows-fill` | Every flow and module's real content, published |
| 10 Front doors | `phone`, `banking-app`, `origins`, `smoke` | An optional phone number, the banking app, approved origins, and a read-back of everything |

## Where you'll be asked to paste something

No API gives these out, so the script stops, says exactly where to click, and checks what you paste. Pasted
values go to the helper's stdin and into Secrets Manager; they're never put on a command line or printed.

| When | What | From |
|---|---|---|
| `admin-user` | a username and password you choose | you |
| `money-hub` (optional) | Tavus API key, face ID, PAL ID (video avatar) | platform.tavus.io |
| `designer-access` | only if `templates/acxd` is missing: today's designer API key and workspace ID | today's agentic CX designer → Settings → Programmatic users |
| `designer-access` | the new workspace's designer API key and workspace ID | the new instance's agentic CX designer → Settings → Programmatic users |
| `touchpoint-keys` | each designer app's Touchpoint deployment key and API key | the designer → Applications → *app* → Deploy |
| `phone` | whether to claim a number (monthly cost) | you |

## The few things it changes that it didn't make

The scripts are create-only: anything that exists is left alone. Three exceptions, all on the new instance's own
defaults: `queues` adds the new queues to the default **Basic Routing Profile**; `tool-grants` lets the default
**Admin** and **Agent** security profiles use the gateway's tools (ARIA's tool calls run with them); `instance`
sets the instance's attributes. Two instance settings have no API and stay as Connect's defaults: *bot management*
and *bot analytics and transcripts* (turn them on in the Connect console → instance → Flows if you want them,
as connect-bot-flow-modular/DEPLOY.md notes).

## How the repo's IDs get onto the new instance

The committed flows, modules and ARIA v2's agent JSON all carry today's IDs. Rather than change every builder,
`py/rebase.py` swaps each old ID (`templates/live-map.json`) for the new instance's ID of the resource with the
**same name** (from the state file), then refuses anything that still contains an old ID before it goes to AWS.
What was sent is kept in `state/<alias>-flows/`. Two flows existed only in today's instance ("ARIA human handover"
and "Mortgage Live Sync entry"); they were captured into `templates/flows/` on 23 Oct 2026.

## Files

| Path | What |
|---|---|
| `deploy.sh` | the orchestrator: steps, order, prompts |
| `lib/ui.sh` | how steps talk to you |
| `py/*.py` | the AWS work no repo script does (one helper per area; each `python3 py/<x>.py <command> --state …`) |
| `acxd/` | designer SDK scripts: `capture.mjs` (today's workspace, read only), `create.mjs` (new workspace), `verify.mjs` |
| `templates/` | `live-map.json` (today's IDs), `connect.json` (queues, flows, modules), `flows/` (captured flows), `acxd/` (captured designer apps) |
| `state/` | git-ignored: `<alias>.env` (every ID), `<alias>.log` (the whole run, including the banking app's demo link), sent flows |
| `tests/` | offline tests |

Small changes to existing scripts so they can run in another account (each defaults to today's value, so
nothing changes for the current deployment): `scripts/deploy_mcp_gateway.sh` (`AWS_ACCOUNT_ID`),
`scripts/deploy_handback_recovery.sh` (`AWS_ACCOUNT_ID`, `INSTANCE_ID`, `ASSISTANT_ID`),
`scripts/deploy_routing_lambda.sh` (`ROUTING_STATE_FILE`), `connect-money-hub/scripts/keep_bridge_warm.sh`
(`AWS_ACCOUNT_ID`), `connect-banking-app/scripts/deploy_banking_app.sh` (`--assistant-id` / `ASSISTANT_ID`).

## Known gaps and risks

- **The designer phase is the least proven.** The SDK (`amazon-connect-acxd-sdk` 0.2.0) can create everything, but
  its flow format is only known from its types, and nothing has yet rebuilt an app from a capture. `create.mjs` is
  create-only and resumable, so a failure there can be fixed and re-run without starting again.
- **Touchpoint keys:** the directions say where they were in the designer when this was written; the console may
  have moved them.
- **External agents (A2A):** if Connect refuses the Money Hub collaborator with a plan or tier message, the instance
  needs the AI agents plan that allows external agents (Connect console → instance → AI agents), then re-run
  `money-hub-a2a`.
- **Legacy Lambdas:** `scripts/deploy_mcp_gateway.sh` always also makes three older support Lambdas nothing uses
  now. They're harmless; delete them if you like.
- **Not included** (not used by the current system; no flow or agent calls them): DTMF secure capture and its
  tables (`aria-card-bins`, `aria-customer-cards`), meeting ID, the WebRTC API, the two old chat widgets, the
  analytics agent, the IDV test harness, and the branch project's Teams expert transfer (lease bridge, its API and
  tables, the Azure side) and its AVA agent and branch transfer flow.
- **Branch tools** come from `branchtransfercalldesign` as it is checked out (`BRANCH_REPO`). Its sample branches
  (eight, Nationwide and Virgin Money) are seeded into the new `branches` table once.
- **No teardown script.** To remove a test build, delete the Connect instance, then the CloudFormation stack
  `mortgage-livesync-api`, then the resources tagged `project=deploy-fresh-instance` and the `aria-*` ones.

## Checks

```bash
python3 -m unittest discover -s deploy-fresh-instance/tests    # offline tests, no AWS
```

They prove every committed flow, module and ARIA v2 moves onto a new instance with no old ID left (also in another
region), that a missing new ID is named, that the captured flows are whole, the step order, that every step asks
first and checks its inputs, that errors stop the run, that secrets never go on a command line, and that each
helper's command line takes its values the way deploy.sh passes them.
