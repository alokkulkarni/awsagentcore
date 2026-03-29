# ADR-008: In-Process Tool Execution (Not AgentCore Gateway Endpoints)

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

AgentCore offers two ways to make tools available to a hosted agent:

1. **In-process** — tool functions run inside the same Python process as the agent, imported directly as callables and passed to the Strands `Agent` constructor.
2. **AgentCore Gateway** — tools exposed as HTTP endpoints; the agent calls them via Gateway URLs registered in the AgentCore tool registry. Each tool invocation is an HTTP request from the agent container to the Gateway endpoint.

ARIA has 20 banking tools spanning 8 domains (accounts, cards, payments, PII, knowledge, fraud, escalation, products). A decision is required on which execution model to use and whether it should be applied uniformly or per-tool.

## Decision

All 20 ARIA banking tools are executed **in-process** within the same container as the agent.

Tools are collected into `ALL_TOOLS` in `aria/tools/__init__.py` and passed directly to the Strands `Agent` at construction time:

```python
# aria/agent.py
from aria.tools import ALL_TOOLS

def create_aria_agent() -> Agent:
    return Agent(
        model=bedrock_model,
        tools=ALL_TOOLS,   # all 20 tools, in-process
        system_prompt=SYSTEM_PROMPT,
        memory=memory_client,
    )
```

**Key reasons for this decision:**

1. **Zero network latency per tool call** — an in-process function call takes microseconds; an HTTP round-trip to a Gateway endpoint adds ~5–50 ms each way. A complex banking query may invoke 4–6 tools in a single turn; Gateway hops would add 40–300 ms of avoidable latency per turn.

2. **PII vault is in-process session state** — `_VAULT` (in `aria/tools/pii/`) is a module-level singleton dict that holds ephemeral PII collected during a session (DOB, address fragments). If tools ran as separate Gateway services, the vault would not be accessible across process boundaries without an external store (e.g., Redis/ElastiCache), which would significantly complicate the PII architecture and introduce a new infrastructure dependency.

3. **Simpler deployment** — all tools ship in the same Docker image; no Gateway endpoint registration, no separate service deployments, no service discovery or health-check infrastructure for tools.

4. **Unified error handling** — tool exceptions propagate naturally through Strands' tool execution loop and are formatted into `toolResult` error responses automatically. Gateway tools would require HTTP status code translation and retry logic.

5. **Unified observability** — all tool calls are visible in the same process logs, traces, and audit events. No cross-service correlation IDs are needed to reconstruct a session's tool call sequence.

**When AgentCore Gateway makes sense (not now, documented for future):**

- Domain sub-agents in separate containers need access to shared tools
- A tool becomes an independently scalable service (e.g., a high-volume fraud-check service shared across multiple agents)
- Tools are reused across multiple distinct agents in the same platform
- See [docs/domain-sub-agent-architecture.md](../domain-sub-agent-architecture.md) for the future Gateway pattern

## Consequences

### What this enables

- Sub-millisecond tool dispatch with no network overhead.
- PII vault remains a simple in-process dict with no external dependency.
- Single Docker image ships agent + all tools; one deployment unit.
- Tool failures surface cleanly in the agent's error handling and audit trail.

### Trade-offs and limitations

- **Image size coupling** — if any tool adds a large dependency (e.g., a PDF parser, an ML model), the entire agent image grows. There is no way to isolate heavy tool dependencies from the agent process.
- **In-process failure risk** — a crashing tool (unhandled exception, OOM) could affect the agent process. Mitigated by Strands' exception wrapping around tool calls, which catches and formats errors without crashing the agent.
- **No independent tool scaling** — tools scale with the agent container. This is acceptable because AgentCore auto-scales containers per session; tool-level scaling is not required at current load.
- **Single-language constraint** — all tools must be Python (the agent's language). Gateway would allow tools in any language.

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| AgentCore Gateway for all tools | Network latency per tool call; PII vault incompatible without Redis; higher operational complexity |
| AWS Lambda functions as tools | Cold start latency (100–500 ms); separate deployment pipeline; no PII vault sharing |
| Separate ECS microservices per tool domain | Massive operational overhead for 8 domains; PII vault sharing requires Redis; no benefit at current scale |
| Mixed: some in-process, some Gateway | Operational complexity without benefit at current scale; deferred to future sub-agent architecture |

## Implementation reference

| File | Role |
|---|---|
| `aria/tools/__init__.py` | `ALL_TOOLS` list — collects all 20 tool functions and exports them |
| `aria/agent.py` | `create_aria_agent()` — passes `ALL_TOOLS` to `Agent(tools=ALL_TOOLS)` |
| `aria/agentcore_app.py` | Uses the same `Agent` instance; tool dispatch is in-process |
| `aria/tools/pii/` | `_VAULT` singleton — only viable as in-process state |
| `aria/tools/accounts/`, `cards/`, `payments/`, etc. | Individual tool domain modules, all imported in-process |

## Related documents

- [docs/domain-sub-agent-architecture.md](../domain-sub-agent-architecture.md) — future Gateway pattern when domain sub-agents are introduced
- [ADR-010](ADR-010-audit-eventbridge-three-tier.md) — audit events from in-process tool calls
- [ADR-001](ADR-001-audit-transcript-non-blocking.md) — non-blocking design for tool-adjacent async operations
