# ARIA — AgentCore Tools Architecture

## Where tools live in deployment

All 20 banking tools are **bundled inside the AgentCore Runtime container** and run
**in-process** alongside the agent. No separate tool service or Gateway is required.

```
Docker container (AgentCore Runtime)
├── aria/agentcore_app.py        ← BedrockAgentCoreApp (HTTP server)
├── aria/agent.py                ← Strands Agent (Claude Sonnet 4.6)
└── aria/tools/                  ← All 20 tools — same Python process
      account/, auth/, credit_card/, debit_card/,
      customer/, mortgage/, escalation/, pii/, …
```

When ARIA calls `get_account_balance`, it is a direct in-process Python function
call — no network hop, no separate service. The Strands agent framework handles
the tool-calling loop internally. This is correct and intentional.

---

## What is AgentCore Gateway?

Gateway is a separate AWS-managed service that exposes tools as
**MCP (Model Context Protocol) HTTP endpoints** with managed auth, rate limiting,
and traffic control:

```
Agent (Claude) → AgentCore Gateway → /tools/get_account_balance  (HTTP)
                                    → /tools/block_card           (HTTP)
                                    → /tools/get_statements       (HTTP)
```

The agent still calls tools by name; it just reaches them over a network
instead of in-process.

---

## In-process vs Gateway — decision table

| Scenario | In-process (current) | AgentCore Gateway |
|---|---|---|
| Tools are Python functions calling stub / bank APIs | ✅ Correct choice | Overkill |
| Tools need to be shared by multiple agents | ❌ Each agent has its own copy | ✅ One endpoint, many agents |
| Tools need OAuth / secrets to call external bank APIs | Works, secrets live in container | ✅ Gateway manages auth separately |
| Tools are long-running async operations | Blocks the agent | ✅ Gateway supports async task pattern |
| Tool response time < 1 s | ✅ No added latency | Adds ~50–200 ms per tool call |
| Session context (`session_id`, PII vault) needed | ✅ Naturally in-process | Must explicitly pass session context |

---

## Why tools stay in the container for ARIA today

### 1 — Session coupling
The PII vault (`_VAULT`) lives in the same process as the agent. Moving tools to
Gateway would require shipping PII vault state across a network boundary, which
increases attack surface without any corresponding benefit.

### 2 — Voice latency
In a Nova Sonic 2 voice turn ARIA may call 2–3 tools per customer utterance. A
network hop per call adds ~100–200 ms each. On a voice call where sub-second
responsiveness is expected, that accumulates to perceivable delay.

### 3 — No shared-tool requirement
ARIA is currently the only agent. There is no second agent that needs to call the
same tools, so there is nothing to be gained from a shared endpoint.

### 4 — Strands already implements MCP in-process
The Strands `@tool` decorator produces MCP-compatible tool definitions. Tools are
MCP-ready today; they just run inside the process rather than over HTTP. Migrating
to Gateway later requires no changes to the tool logic itself.

---

## When to migrate tools to Gateway

The natural triggers are:

- **Real bank API authentication** — when tools need OAuth 2.0 tokens or rotating
  secrets that are better managed centrally rather than per-container.
- **Multiple agents sharing tools** — if a fraud-detection agent, a branch-staff
  agent, or a mortgage advisor agent also needs `get_account_details` or
  `get_statements`, a single Gateway endpoint avoids duplicating the tool logic.
- **Independent deployability** — update `block_card` logic without rebuilding and
  redeploying the full ARIA container.

At that point the migration path is:
1. Extract tool functions into a standalone MCP server (FastMCP or similar).
2. Register the MCP server in AgentCore Gateway.
3. In `aria/agent.py`, replace `tools=ALL_TOOLS` with the Gateway MCP server URL.
4. Tool logic is unchanged; only the call boundary moves from in-process to HTTP.

---

## Summary

| Question | Answer |
|---|---|
| Are tools hosted on AgentCore Gateway? | No — they run inside the Runtime container |
| Do tools need any AgentCore-specific changes? | No — `@tool`-decorated functions work as-is |
| Are tools MCP-compatible? | Yes — Strands produces MCP tool definitions automatically |
| Should Gateway be added now? | No — adds latency and complexity with no current benefit |
| When should Gateway be considered? | Real bank API OAuth, multi-agent tool sharing, or independent tool deployments |
