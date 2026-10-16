# Money Hub — Specification

| | |
|---|---|
| Status | Built and unit-tested (61 tests). Agent checked on real Bedrock turns locally. **Not deployed; nothing has run on a live contact.** |
| Date | 16 October 2026 |
| Depends on | ARIA (`my-conversation-agent`) and `conversation bot flow`; the ARIA MCP gateway (optional, for agent assist) |
| Built with | Strands Agents, `strands-agents-tools` (calculator), Amazon Bedrock AgentCore Runtime, Amazon Connect agent-to-agent (A2A) collaboration |

## 1. What is wanted

> A Strands agent for spending insights, hosted in AgentCore, as a collaborator to ARIA, reachable through
> chat or voice, handling everything around a "money hub": spending analysis, money in and out, a view of
> expected spending in coming months. It must not give advice but must reason and explain: "how do I reach
> my savings goal?" means analysing spends, understanding discretionary payments and habits, and explaining
> what could be reduced or replaced to reach the target. Sample data of at least 100 transactions covering
> money in and out. A small responsive frontend showing the same data in categories, money in and out and
> expected, letting the customer categorise their transactions.

## 2. Design at a glance

```
Customer ─ phone or chat ─► ARIA (Connect AI agent, my-conversation-agent)
                              │  decides from the collaborator instruction; hands off unannounced
                              ▼  Connect A2A, "talk to the customer", text (Connect speaks it in ARIA's voice)
                      Bridge Lambda (Function URL)  ── checks Connect's API key, speaks Connect's A2A extensions,
                              │                        keeps the conversation, finds the verified customer
                              ▼  InvokeAgentRuntime (IAM)
                      Strands agent on AgentCore Runtime ── 12 Money Hub tools + calculator, Claude Haiku 4.5
                              │
                              ▼
                      moneyhub package ── sample data, every calculation, the customer's categories and goals
                              ▲                                   (DynamoDB aria-money-hub)
                      Money Hub page (Lambda + HTTP API) ── same data, same calculations, recategorise, goals
```

When the agent is done it sends FINISH (COMPLETE or ESCALATE, with a reason). ARIA is invoked again with
the reason and carries on, or escalates to a person through its usual path.

## 3. Decisions

**M1. External collaborator in "talk to the customer" mode, text.** Amazon Connect supports agents hosted
on AgentCore as external A2A collaborators. Text mode means Connect does speech-to-text and text-to-speech,
so the caller hears ARIA's voice throughout and the agent needs no voice infrastructure. Chat works the same
way. Audio streaming was not chosen: it needs Nova Sonic, immediate handoff and must be ARIA's only
collaborator.

**M2. A bridge in front of AgentCore Runtime.** Connect authenticates an external agent with a fixed API key
(`Authorization: Bearer`). AgentCore Runtime accepts only IAM (SigV4) or short-lived OAuth JWTs, so Connect
can't call it directly. The bridge is a Lambda behind a Function URL (not API Gateway, whose 30-second limit
could cut a turn short). It checks the key in constant time, speaks Connect's A2A extensions, and calls the
runtime with IAM. It also keeps the Connect protocol out of the agent, so the agent is a plain Strands agent.

**M3. The agent is stateless; the bridge keeps the conversation.** On chat Connect opens a new connection per
message and re-sends the history; over HTTPS there is no persistent connection on voice either. The bridge
stores the transcript per `contextId` (DynamoDB, two hours) and sends it with each turn. Any runtime
instance can answer.

**M4. Identity from Connect, never from the conversation.** `INIT_SESSION` carries the contact ARN, not custom
attributes. The bridge reads the contact's attributes with `GetContactAttributes` and applies the same gate
as the dispute service: `authStatus` authenticated and, if set, LoA 2 or above. The customer ID is bound into
the agent's tools when they are built; no tool takes a customer argument. An unverified customer gets no data
and a COMPLETE hand-back telling ARIA to verify first.

**M5. Numbers are computed, never generated.** `moneyhub/analysis.py` works out every figure: monthly
summaries, categories, recurring payments, the forecast, discretionary habits, and savings-goal arithmetic.
The page and the agent call the same functions, so they always agree. The prompt forbids the model from
inventing or calculating figures (calculator only to combine figures a tool returned).

**M6. Guidance, not advice.** The agent explains and reasons with the customer's own figures and shows what
changes would mean ("if you…, then…"). It never recommends a financial product or provider, never says what
the customer should do, declines advice requests with a choice (see the numbers, or a colleague), and hands
back to escalate only if the customer picks the colleague. A fixed disclosure sentence ends any answer about
goals or changes (`GUIDANCE_DISCLOSURE`, placeholder wording). Signs of vulnerability or financial difficulty
hand back to escalate.

**M7. Savings goals reason over discretionary habits.** `goal_plan` returns the monthly amount needed, what is
left over now, the gap, and an illustrative mix of changes (25% then 50% less on each discretionary habit,
biggest first; individual subscriptions) with what each frees up and months to the goal with and without them.
One-off spending (holidays) is not treated as a monthly habit. When even every change falls short, it says so.

**M8. Channel-aware.** The bridge records VOICE or CHAT. On calls the prompt sets hard limits (45 words, three
figures, no lists) and the output cap is 300 tokens; money with £, dates as "11 October", card digits one by
one. On chat, short lists and a page link (secret after `#`, 24 hours).

**M9. Model.** Claude Haiku 4.5 (`eu.anthropic.claude-haiku-4-5-20251001-v1:0`), for speed on calls and EU
data residency. Haiku 5.5's inference profile is listed in eu-west-2 but returned "not available for this
account" when tried. Configurable with `--model`.

**M10. Sample data.** Seeded, so identical every run: James (CUST-001) 333 transactions, Sarah (CUST-002) 188,
16 April to 15 October 2026. Money in: salary, side income, refunds, a transfer from savings. Money out across
20 categories, fixed (mortgage, council tax, energy, insurance, subscriptions) and variable (groceries, coffee,
takeaways, eating out, transport, shopping, a summer holiday). "Today" for every analysis is 15 October 2026,
the end of the data, so forecasts always look forward from it.

## 4. Components

| Path | What | Talks to |
|---|---|---|
| `moneyhub/` | Data, categories, analysis, store, service | DynamoDB `aria-money-hub` |
| `agent/` | Strands agent: `main.py` (AgentCore entrypoint), `money_tools.py` (12 tools), `prompt.py`, `history.py`, Dockerfile | Bedrock, DynamoDB |
| `bridge/` | `a2a_bridge.py` (Lambda), `protocol.py` (A2A frames, OTLP trace) | Connect, Secrets Manager, AgentCore Runtime, DynamoDB |
| `api/` + `web/` | Page Lambda and the responsive page; two read-only gateway tools | DynamoDB |
| `scripts/` | Deploy and configure; `collaborator.py`, `build_aria_prompt.py`, `local_preview.py` | AWS (only when you run them) |

## 5. The Connect contract, as implemented

From "A2A protocol contract for external AI agents" and "A2A sample events" (A2A v1.0, JSON-RPC over HTTPS).

| Connect sends | Bridge answers |
|---|---|
| `INIT_SESSION` (contactArn, history, supportedFinishTypes, subscribeToTracingEvents) | `INIT_SESSION_RESPONSE` statusCode 200, extension echoed |
| `CHANNEL_STATE` READY, `INTERRUPTION`, `DTMF_INPUT_COMPLETE`, informational `ERROR` | An acknowledging message |
| A text turn | A task: the reply (`TEXT_RESPONSE_CHUNK` artifact), one `TRACING_SPAN` artifact, status COMPLETED; with FINISH on the status when handing back |
| `<EMPTY_USER_INPUT>` | A gentle re-prompt, without calling the agent |
| `GetTask` (poll mode) | The stored task |
| Anything it can't dispatch | JSON-RPC error with `google.rpc.ErrorInfo` |
| A turn the agent can't complete | `TASK_STATE_FAILED` with a structured error (424, DEPENDENCY_FAILURE) |

Every response echoes `A2A-Extensions`. Every turn's trace adopts Connect's `traceparent` / `tracestate`
(root `parentSpanId` from `connect=parentSpanId:…`), with a root `invoke_agent money-hub-agent` span carrying
the customer's input and the agent's output, a `chat <model>` span and an `execute_tool <name>` span per tool.
Connect disables external endpoints that don't send traces.

## 6. Rules the code enforces

| # | Rule | Where |
|---|---|---|
| H1 | Every bridge request carries Connect's key; compared in constant time | `a2a_bridge.lambda_handler` |
| H2 | The customer comes from Connect's record of a verified contact (Level 2+) | `a2a_bridge.verified_customer` |
| H3 | No tool takes a customer; the customer is bound when tools are built | `money_tools.build_tools` |
| H4 | Money in stays money in, money out stays money out, when recategorising | `categories.allowed_move` |
| H5 | The page sees only the customer its link names; the link's secret is after `#`, 24 hours | `MoneyHub.customer_of_link` |
| H6 | A tool call can never mint a page link | `money_api.lambda_handler` |
| H7 | Logs carry event types and outcomes, never the customer's words, replies, amounts, IDs or keys | all Lambdas |

## 7. Setup summary (detail in the README)

1. `deploy_money_hub.sh`, 2. `deploy_agent.sh`, 3. `deploy_bridge.sh`, 4. update the AWS CLI if needed and
run `connect_collaborator.sh` (dry run, then `--apply`), 5. ARIA's prompt (`build_aria_prompt.py`) and
publish, 6. point `conversation bot flow` at ARIA's new version. Requires the **Connect Customer** tier.

## 8. Out of scope

Real bank data and a real card or payments system; any regulated advice; audio streaming; the agent
changing anything except categories and goals; adviser-facing views beyond the two read-only gateway tools.

## 9. Open questions to settle on the first live contact

- **The HTTPS turn response.** The samples show streamed frames (WebSocket). Over HTTPS the docs say "the
  response or a task"; the bridge returns one task holding the text artifact, the trace artifact and the
  terminal status. If Connect expects otherwise, switch `BRIDGE_MODE=poll` (answer "working", Connect polls
  `GetTask`) or adjust `protocol.turn_task`.
- **The answer to `CHANNEL_STATE` over HTTPS** isn't defined; the bridge acknowledges with a message.
- **Latency on calls.** A turn took 3 to 5.5 seconds locally (Haiku 4.5, one or two tools). There's no audio
  filler in this mode; check it feels natural, and consider a smaller history or fewer tools if not.
- **What ARIA's history looks like in `INIT_SESSION`** on voice (it is passed through to the agent as context).
- **Contact context** (channel) needs Access Contact Control Panel on ARIA's security profile; the bridge falls
  back to the contact's `channel` attribute, which the bot flow already sets.

## 10. Known gaps

- Nothing here has run on a live contact. The bridge is tested against the AWS sample events, not Connect.
- The disclosure sentence is placeholder wording for the bank's approved text.
- Forecasts are pattern-based estimates; they ignore one-offs by design.
- `connect_collaborator.sh` needs a newer AWS CLI than 2.35.11.
- The runtime uses PUBLIC network mode with IAM-only access; AWS recommends VPC mode for production.
- The bridge keeps each conversation (the customer's words and the agent's replies) in DynamoDB for about two
  hours, with the table's default encryption. Use a customer managed key and shorter retention for real data.
- The bridge's Function URL has no built-in throttling (the page's HTTP API does). Every request still needs the
  key; add reserved concurrency or a WAF if exposure matters.
- `--permissions BasicAgentAccess` (Access Contact Control Panel) and the runtime's DEFAULT endpoint are assumed
  rather than checked; the README troubleshooting table says what to do if either is wrong.
