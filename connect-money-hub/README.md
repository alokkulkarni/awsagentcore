# Money Hub — Setup Guide

A customer asks ARIA, **on the phone or in a chat**, something like "where does my money go?" or "how do I
reach £3,000 by July?". ARIA quietly hands the conversation to the **Money Hub agent**: a Strands agent
running on Amazon Bedrock AgentCore. It looks at the customer's real transactions and explains:

- money in and money out, by category, month by month;
- regular payments and subscriptions;
- what the next few months are expected to look like, including the balance;
- spending habits ("coffee 12 times a month at about £4");
- what reaching a savings goal would take, and which changes to discretionary spending would get them there.

It **reasons and explains but never gives financial advice**. When it's done, it hands back to ARIA. The
customer hears ARIA's voice throughout. There's also a responsive **Money Hub page** showing the same figures,
where the customer can move transactions to other categories and save goals, and **chat or call** from the
page itself. That conversation goes through ARIA to the same agent, which knows which tab they were on.

This guide is for someone doing this for the first time. Do the steps in order. Each says what you should
see when it worked.

> **Nothing here has run on a live call or chat yet.** There are 78 automatic tests, and the agent was checked
> on real Bedrock turns on a laptop. The first live contact is the real test. SPEC.md section 9 lists the two
> protocol details that contact will confirm.

## Table of Contents

- [How it works](#how-it-works)
- [Before you start](#before-you-start)
- [Set it up](#set-it-up)
- [Test it](#test-it)
- [Troubleshooting](#troubleshooting)
- [How to undo it](#how-to-undo-it)
- [What is in this folder](#what-is-in-this-folder)

---

## How it works

```
Customer (phone or chat) ─► ARIA ─► (Connect hands over, unannounced) ─► Bridge ─► Money Hub agent (AgentCore)
                             ▲                                                          │
                             └──────── hands back with a reason ◄───────────────────────┘
```

| Piece | What it does |
|---|---|
| **ARIA** | Notices a money question, makes sure the customer is verified, lets Connect hand over. Carries on when the agent hands back |
| **Bridge** (Lambda) | Connect's front door to the agent. Checks Connect's key, works out who the customer is from Connect's own record, keeps the conversation |
| **Money Hub agent** (Strands on AgentCore Runtime) | Talks to the customer, using 13 Money Hub tools. Every figure comes from a tool; it never invents numbers |
| **Money Hub page** | The same figures in a web page; change categories, save goals |

The sample data is fictional: James (`CUST-001`) has 333 transactions and Sarah (`CUST-002`) 188, from
16 April to 15 October 2026. "Today", for every figure, is 15 October 2026.

---

## Before you start

Tick each one:

- [ ] **The code.** In Terminal:
  ```bash
  cd ~/Documents/Development/awsagentcore
  git fetch && git checkout feature/money-hub && git pull
  ```
- [ ] **AWS CLI signed in** to account `<account-id>`:
  ```bash
  aws sts get-caller-identity --query Account --output text
  ```
  ✅ prints `<account-id>`.
- [ ] **AWS CLI new enough.** Step 5 needs a newer CLI than 2.35.11. Check with `aws --version`, and update
  if needed: on a Mac, `brew upgrade awscli` (or the installer from the AWS website).
- [ ] **Docker Desktop is running.** Step 3 builds the agent's container. Check with `docker buildx version`.
- [ ] `python3`, `zip` and `curl` are installed.
- [ ] **Node.js 18 or later** with `npm`, for the page's Call button (step 9). Check with `node --version`.
  On a Mac: `brew install node`.
- [ ] Your Connect instance is on the **Connect Customer** tier. Agent-to-agent collaboration doesn't work on
  Customer Basic.

---

## Set it up

### Step 1 — Run the tests and preview the page (5 minutes, no AWS)

```bash
python3 -m unittest discover -s connect-money-hub/tests
```
✅ Ends with `OK`.

```bash
python3 connect-money-hub/scripts/local_preview.py
```
It prints a link like `http://127.0.0.1:8765/#k=…`. Open it in your browser: James's Money Hub, with
the tabs Money out, Money in, Expected, Transactions and Goals. Try moving a payment to another category on
the Transactions tab. Press **Ctrl+C** in Terminal to stop.

### Step 2 — Deploy the Money Hub data service and page (5 minutes)

```bash
./connect-money-hub/scripts/deploy_money_hub.sh
```

This creates the DynamoDB table `aria-money-hub`, the page Lambda `aria-money-hub-api` and its web address,
and two read-only tools on ARIA's gateway (for the adviser's assistant).

✅ It ends with `Done` and prints:
- **Money Hub page:** `https://….execute-api.eu-west-2.amazonaws.com/`
- **Demo link:** open it to see James's Money Hub. It works for 24 hours; run the script again for a new one.

### Step 3 — Build and deploy the agent to AgentCore (10 to 15 minutes)

Make sure Docker Desktop is running, then:

```bash
./connect-money-hub/scripts/deploy_agent.sh
```

This creates an ECR repository, a role only AgentCore can use, builds the agent's ARM64 container (this takes
a few minutes the first time), and creates the AgentCore Runtime `aria_money_hub_agent`. Then it waits for
**READY** and asks the agent a test question.

✅ It ends with an answer from the agent, for example *"Agent: Your regular payments are…"*, and the line
`The agent answers.`

❌ "The image did not build": open Docker Desktop and try again.
❌ "not available for this account": the model isn't enabled; run with `--model` and another model ID.

### Step 4 — Deploy the bridge (5 minutes)

```bash
./connect-money-hub/scripts/deploy_bridge.sh
```

This creates:
- a KMS key that Connect may use only through Secrets Manager;
- a secret holding the API key Connect will present, which only your Connect instance can read;
- the bridge Lambda with its public HTTPS address.

✅ It ends with three ✓ tests: the agent card loads; a request without the key is refused; a session start
with the key is accepted. It prints the **Bridge address**.

**Optional, for quicker hand-offs:** keep the bridge warm, so the first hand-off in a call doesn't wait for the
Lambda to start. It adds a schedule that pings the bridge every 5 minutes (dry run first):

```bash
./connect-money-hub/scripts/keep_bridge_warm.sh            # then again with --apply; --remove --apply undoes it
```

The key is made once, used for that one test, and never shown or read back. If you run the script again,
the keyed test is skipped; that's expected.

### Step 5 — Give ARIA its new instructions (10 minutes)

1. In Terminal:
   ```bash
   python3 connect-money-hub/scripts/build_aria_prompt.py
   ```
   ✅ `Wrote …/aria-prompt-with-money-hub.yaml` and a size under 100,000 characters. It only reads from AWS.
2. Connect admin website → **AI agent designer** → **AI prompts** → `ARIA-Banking-Ochestration-Prompt`.
3. **Back it up:** select all the text, copy it, and save it in a file on your desktop.
4. **Edit**, select all, delete, and paste the whole of
   `connect-money-hub/prompts/aria-prompt-with-money-hub.yaml`. Check the first line is `system: |`.
5. **Save**, then **Publish** (this publishes the *prompt*).
6. **Don't change ARIA in the AI agent designer.** Step 6's script points ARIA at the newest published prompt
   (and guardrail) version and publishes one ARIA version with them and the collaborator. The console's agent
   **Save** doesn't reach the configuration the script works from, and it can drop ARIA's security profiles.

### Step 6 — Make the Money Hub agent ARIA's collaborator (5 minutes)

There's no console screen for this; the script does it. [docs/collaborator-setup.md](docs/collaborator-setup.md)
explains each thing it sets up, where it lives in Connect, and how to check it.

**6a. Dry run first** (changes nothing):
```bash
./connect-money-hub/scripts/connect_collaborator.sh
```
✅ It lists what it would do, and shows ARIA's collaborators going from N to N+1.
❌ "Your AWS CLI … is too old": update it (see Before you start), then run again.

**6b. Do it:**
```bash
./connect-money-hub/scripts/connect_collaborator.sh --apply
```
It:
1. registers the bridge as an A2A application;
2. associates it with your instance;
3. backs up ARIA's configuration (in `scripts/backups/`), then adds the Money Hub collaborator, keeping everything else;
4. sets up the security profile;
5. publishes a new ARIA version.

Step 3 of its output shows `Prompt version: X -> Y` (and the guardrail): check Y is the version you just
published. To choose another, add `--prompt-version N` or `--guardrail-version N`; `--keep-versions` leaves them.

✅ It ends with **ARIA version to use: N** and `Linked:` lines for ARIA and version N. Write N down.

> **Don't save ARIA in the AI agent designer after this step.** Saving it there can replace its security profiles and silently stop the hand-over. For a new prompt or guardrail version, publish it, then run this step again and use the new ARIA version it prints. `connect_collaborator.sh --check --version N` confirms the links at any time.
❌ A message about the tier means your instance isn't on Connect Customer.

### Step 7 — Point the bot flow at ARIA's new version (10 minutes)

Connect admin website → **Routing** → **Flows** → `conversation bot flow`:

1. The **Connect assistant** block that names `my-conversation-agent` (near the top, after Set language):
   click it, choose version **N**, then **Save**.
2. The **Get customer input** block → **Session attributes** → `x-amz-lex:q-in-connect:ai-agent-arn`: change
   only the number at the end to **N**, then **Save**.
3. **Save** the flow, then **Publish**.

✅ It publishes without errors. Nothing else in the flow changes: Connect hands over and back inside ARIA's
own Lex conversation.

### Step 8 — Let the adviser's assistant see the Money Hub (optional, 10 minutes)

In **AI agents** → `my-agent-assistant-agent` → **Edit** → **Add tool**, add
`aria_money_hub___get_money_hub_summary` and `aria_money_hub___get_money_hub_forecast`. Then **Save** and
**Publish**, and update the version in the flow `ARIA agent assist`.

If the tools aren't offered, Connect is using its own copy of the gateway's tool list. Note the agent's
tools, remove the `aria-mcp-agentcore-gateway-server` integration, add it back, and re-select them.

### Step 9 — Chat and call from the Money Hub page (10 minutes)

A tag fixed at the bottom of the page, **Ask about your money**, opens the assistant over the page. It shows
the tab you're on. On a phone it's a sheet from the bottom whose height you drag with its handle; on a tablet
or computer it's a panel at the bottom right that you resize by dragging its top-left corner. The page keeps
scrolling behind it. **–** minimises it back to the tag (a conversation carries on); **×** closes it and ends
any conversation. Inside are two buttons, **Chat** and **Call**. Each one starts a conversation with ARIA, in
`conversation bot flow`, from the browser. A call uses your computer's microphone and speaker; no phone is
needed. When the customer asks about their money, ARIA hands over to the Money Hub agent as usual. The agent
knows which tab of the page they were looking at.

**Who ARIA thinks it is.** The page tells Connect who the customer is only if the page link came from a
conversation where they were verified at Level 2 (for example, the agent sent it in a chat). Then ARIA lets the
agent take over straight away. The demo link from step 2 has no verified conversation behind it, so ARIA
asks the customer to verify first, just like a normal chat.

1. **Build the call component and redeploy the page.** Step 2 already did this if Node.js was installed. To be
   sure, or to get a demo link that counts as verified James (for testing only), run:
   ```bash
   ./connect-money-hub/scripts/build_chime.sh
   ./connect-money-hub/scripts/deploy_money_hub.sh --verified-demo
   ```
   ✅ The build prints `Built web/vendor/chime.js`. The deploy ends with `Chat and call from the page: on`
   and `Demo link verified (Level 2): yes`.

   > Anyone with a `--verified-demo` link is treated as James for 24 hours. Use it only in this test account.
   > Run the deploy again without the option to go back to an ordinary demo link.

2. **Redeploy the agent and the bridge** so they know about the page's tab:
   ```bash
   ./connect-money-hub/scripts/deploy_agent.sh
   ./connect-money-hub/scripts/deploy_bridge.sh
   ```
   ✅ Each ends with `Done`.

3. **Update ARIA's prompt.** The Money Hub section gained two sentences about conversations started from the
   page. Repeat **step 5** (build the prompt, paste, publish), then **step 7** (put ARIA's new version in
   both places in `conversation bot flow`).

4. **Try it** (see *From the Money Hub page* under [Test it](#test-it)).

> **Web calling on the instance.** Calls use the same Connect feature as the Live Sync widget, which already
> starts web calls on this instance, so there's nothing to switch on. If **Call** says it couldn't connect,
> see Troubleshooting.

You can also try the buttons from your laptop before deploying. This starts real contacts with your AWS
sign-in:
```bash
python3 connect-money-hub/scripts/local_preview.py --talk <instance-id> f6d6545f-c9ae-4ca4-a4d8-6fdc8ba0494f --verified
```

---

## Test it

### On chat
**Test chat** → **Test settings** → `conversation bot flow` → **Apply**. Verify yourself as James when ARIA asks.

| You type | You should see |
|---|---|
| `Where does my money go?` | The essential and discretionary split and your biggest habits, then an offer to go into detail. No "transferring" |
| `How can I reach £3,000 by next July?` | What you'd need a month (£333), what you have left over (£210), the gap, then which changes would close it, ending with *"This is guidance based on your past spending, not financial advice."* |
| `Show me my coffee payments` | A short list |
| `That Pret one was lunch, not coffee` | It offers to move it, and does so when you say yes |
| `Can I see all this?` | A link to your Money Hub page |
| `Should I put money in an ISA?` | It says it can't give financial advice and offers the numbers or a colleague |
| `No thanks, that's all` | It hands back. ARIA asks if there's anything else |

### On a phone call
Ring ARIA as James and ask "where does my money go?". Answers are short, a few figures at a time, in
ARIA's voice, with an offer of more detail.

### From the Money Hub page
Open the demo link from step 9 (the verified one) in **Chrome, Edge or Safari**.

| You do | You should see |
|---|---|
| Open the page | A tag at the bottom, **Ask about your money**, naming the tab you're on |
| Click **Expected**, then the tag | The assistant opens over the page, *About Expected*. On a phone, drag its handle up and down; on a computer, drag its top-left corner. Scroll the page above or beside it |
| Click **Chat** | `Connecting you…`, ARIA's greeting, then a message the page sends for you (*"I'm on my Money Hub page, on the Expected tab…"*). Then an answer about the coming months, with no "transferring" |
| Type `What's my biggest regular payment?` | A short answer with the figure |
| Move a payment to another category in the chat, then click **End chat** | The chat ends. The page refreshes and shows the new category |
| Click **Call** | Your browser asks to use the microphone: **Allow**. `Connected. Speak when you're ready.` ARIA greets you; say *"Where does my money go?"* and the answer is short, in ARIA's voice |
| Talk for a minute on the call | What you and the assistant say appears in the panel as text, a few seconds behind, labelled **You** and **Assistant** (read from ARIA's Amazon Q in Connect session; there's no Contact Lens real-time transcript before a person joins) |
| Click **Mute**, then **Unmute** | The button changes and your voice stops, then starts, reaching the call |
| Click **–** during a call | The assistant shrinks to the tag, which says **Call in progress**; the call carries on. Click the tag to return |
| Click **End call** | `You ended the call.` The contact ends in Connect (not after a timeout) |
| Open an ordinary (not verified) demo link and click **Chat** | ARIA asks you to verify first, then hands over |

### Check it in the logs
- **CloudWatch** → `/aws/lambda/aria-money-hub-bridge`: one line per event, for example
  `event=TEXT outcome=ok tools=2 finish=- ms=4100`. Never what was said.
- **CloudWatch** → GenAI Observability, or `/aws/bedrock-agentcore/runtimes/…`: the agent's own traces.
- In Connect, the contact's AI agent trace shows the collaboration and the agent's spans.

---

## Troubleshooting

| What you see | Likely cause, and the fix |
|---|---|
| ARIA answers money questions itself | ARIA isn't on version N in both places (step 7), or step 6 wasn't applied |
| The conversation goes to the flow's error path at the hand-over | Connect couldn't use the bridge. In `/aws/lambda/aria-money-hub-bridge`: no lines means Connect never called it (check the A2A application's address, step 6); `event=AUTH outcome=refused` means the key doesn't match (the secret was changed) |
| `deploy_bridge.sh` stops with "A request without the key got HTTP 503" | The bridge couldn't read its key. Just after the role is created this is AWS taking a minute or two to apply the new permissions; the script now waits up to two minutes. If it still fails, `/aws/lambda/aria-money-hub-bridge` names the error. Running the script again is safe |
| The chat ends by itself just after ARIA says it can help (flow log: the Get customer input block returns `Error`; the bridge log is empty) | Connect refused the hand-over: ARIA isn't linked to the **ARIA AI agent collaborators** security profile. Saving ARIA in the AI agent designer can replace its profiles. Run `connect_collaborator.sh --check --version N` (N = the version in the flow); it prints the fix. Or run `connect_collaborator.sh --apply` again **after** your last change to ARIA in the console, and use the version it prints |
| "I can't open your Money Hub on this conversation yet" | The customer isn't verified at Level 2 on the contact. ARIA verifies them, then hands over again |
| Every turn fails with "The Money Hub agent is unavailable" | The runtime failed. Check its CloudWatch logs; often a model the account can't use (`--model`) |
| Connect handled a turn but the reply never arrived | The HTTPS reply format (SPEC section 9). Redeploy the bridge with `--mode poll` and try again, then tell me what the bridge log shows |
| `connect_collaborator.sh` fails creating the security profile, naming the permission | The script asks for `BasicAgentAccess`, the usual name for **Access Contact Control Panel**. In the Connect admin website, open **Users → Security profiles → ARIA AI agent collaborators** and tick **Contact Control Panel (CCP) → Access CCP** by hand, then run the script again |
| The test turn in `deploy_agent.sh` fails with "endpoint" or "not found" | The script calls the runtime's DEFAULT endpoint, which normally exists. If not: `aws bedrock-agentcore-control create-agent-runtime-endpoint --agent-runtime-id <id> --name DEFAULT`, wait for READY, run again |
| The page says "This link has expired" | Links last 24 hours. Run `deploy_money_hub.sh` for a new demo link, or ask the agent in chat |
| A call ends abruptly mid-conversation (flow log: Get customer input → `Error` → Disconnect) | Often the assistant's voice from the speakers reached the microphone and Connect heard it as the customer interrupting during a hand-over. Use headphones. In `conversation bot flow`, send the Get customer input block's **Error** branch to a **Loop** block (2 loops) that goes back to the same Get customer input block, and only the loop's **Complete** to Disconnect: ARIA's session carries on where it was |
| On a call the assistant talks over its own answer, or the call ends after a pause | Connect sends an empty turn after a few seconds of quiet and whenever the bot block restarts, needs text in every reply (a reply without text errors the bot block), and plays only the reply to its newest turn. The bridge returns the answer still being prepared if there is one (log `outcome=waited`), otherwise "Take your time." (`outcome=pause`), and the re-prompt on a second pause in a row (`outcome=reprompt`) |
| On a call the assistant replies before you've finished, answers half a sentence, or asks "Are you still there?" as you start to speak | Lex's voice timings are short by default. In `conversation bot flow`, open the **Get customer input** block, **Session attributes**, and set `x-amz-lex:audio:end-timeout-ms:*:*` = `2000` (pause before your turn ends; default 0.6 s), `x-amz-lex:audio:max-length-ms:*:*` = `30000` (longest turn; default 12 s, longer is cut in two) and `x-amz-lex:audio:start-timeout-ms:*:*` = `8000` (wait for you to start; default 3 s). The bridge joins a sentence that still arrives in pieces, and re-prompts only after a second silence in a row |
| A call connects but no transcript appears | In `/aws/lambda/aria-money-hub-api`: `transcript unavailable` means the Lambda's built-in AWS SDK is too old for Q in Connect messages; an `AccessDenied` error means `deploy_money_hub.sh` hasn't been run since the transcript permissions were added |
| No **Chat** or **Call** buttons on the page | The page Lambda has no Connect settings. Run `deploy_money_hub.sh` without `--no-talk` |
| "We couldn't connect you just now" when you click Chat or Call | Connect refused to start the contact. In `/aws/lambda/aria-money-hub-api`, look for `start call failed:` or `start chat failed:` with the error type. `AccessDeniedException`: run `deploy_money_hub.sh` again (it sets the permission). `InvalidRequestException` on a call: check that in-app and web calling is available for the instance, as the Live Sync widget uses it |
| "We couldn't connect the conversation (403)" | The browser reached Connect but the contact had already ended or the token was refused. Click Chat again |
| "To call, allow this page to use your microphone" | The browser blocked the microphone. Click the padlock in the address bar, allow the microphone, reload |
| Call connects but you hear nothing | Check the computer's output device, and in the browser console (**View → Developer → JavaScript Console**) look for an error naming `Content-Security-Policy`; send me the host it names |
| Chat says Connected but no messages arrive | In the browser console, look for a `Content-Security-Policy` error naming a `wss://` host; it needs adding to `_TALK_HOSTS` in `api/money_api.py` |
| ARIA asks a verified link to verify again | The link wasn't minted at Level 2 (an ordinary demo link, or one from a conversation without a level). Use `--verified-demo` for testing, or ask the agent for a link inside a verified chat |

---

## How to undo it

| To undo | Do |
|---|---|
| ARIA's hand-over | In `conversation bot flow`, put back ARIA's previous version in both places and publish. Or run `connect_collaborator.sh --remove --apply` |
| ARIA's prompt | Paste the backup from step 5, publish, choose it in the agent |
| Chat and call from the page | Run `deploy_money_hub.sh --no-talk`: the buttons disappear and the page Lambda loses permission to start contacts |
| Everything | Delete the Lambdas `aria-money-hub-api` and `aria-money-hub-bridge`, the HTTP API `aria-money-hub-pages`, the AgentCore Runtime `aria_money_hub_agent`, the ECR repository `aria-money-hub-agent`, the table `aria-money-hub`, the secret `aria-money-hub/a2a-api-key`, the AppIntegrations application `aria-money-hub` and the gateway target `aria-money-hub`. Schedule the KMS key for deletion last |

---

## What is in this folder

| Path | What it is |
|---|---|
| [SPEC.md](SPEC.md) | Design, decisions, the Connect contract, rules, open questions |
| [docs/collaborator-setup.md](docs/collaborator-setup.md) | What `connect_collaborator.sh` does, step by step, and where each collaborator setting lives in Connect |
| [docs/diagrams/](docs/diagrams/) | Architecture, sequence and AWS infrastructure diagrams (PNG and PDF, editable in draw.io); `build_diagrams.py --export` rebuilds them |
| [moneyhub/](moneyhub/) | The data and every calculation (`analysis.py`), categories, store, service |
| [agent/](agent/) | The Strands agent: `main.py`, `money_tools.py` (its tools), `prompt.py`, Dockerfile. `strands-agents-tools` is there for its `calculator` |
| [bridge/](bridge/) | The Connect A2A bridge: `a2a_bridge.py`, `protocol.py` |
| [api/](api/), [web/](web/) | The Money Hub page and its Lambda. `web/talk.js` is the chat and call client; `web/dock.js` the bottom tag and the overlay |
| [moneyhub/contact.py](moneyhub/contact.py) | What a chat or call from the page tells Connect, from the link's record |
| [web/vendor-src/](web/vendor-src/) | Pinned Amazon Chime SDK version; `scripts/build_chime.sh` builds `web/vendor/chime.js` (not in git) |
| [prompts/money-hub-aria-block.txt](prompts/money-hub-aria-block.txt) | The section added to ARIA's prompt |
| [scripts/](scripts/) | Deploy (steps 2 to 4), collaborator (step 6), prompt builder (step 5), local preview, Chime build (step 9) |
| [tests/](tests/) | 78 automatic tests |
