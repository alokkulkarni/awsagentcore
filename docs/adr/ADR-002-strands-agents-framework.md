# ADR-002: Strands Agents as the AI Agent Framework

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

ARIA required an AI agent framework to orchestrate LLM calls, tool execution, conversation management, and streaming for a banking use case. The framework needed to:

- Integrate natively with Amazon Bedrock and Claude models without an adapter layer
- Provide a simple, testable tool registration mechanism
- Manage conversation history and Bedrock Converse API message formatting automatically
- Support streaming output while allowing the application to control terminal rendering
- Be maintainable and aligned with AWS's long-term agentic platform direction

Multiple frameworks were evaluated against these requirements.

## Decision

Chose **Strands Agents** (AWS open-source, [github.com/strands-agents/sdk-python](https://github.com/strands-agents/sdk-python)) as ARIA's agent framework.

### Why Strands Agents

**Native Bedrock / Claude integration via `BedrockModel`**  
No adapter layer is required. `BedrockModel` accepts a `model_id`, a `boto3_session`, and optional inference config, and calls the Bedrock Converse API directly. Per-region model ID resolution is handled in `create_aria_agent()` before the model is instantiated.

**`@tool` decorator pattern**  
Any Python function decorated with `@tool` becomes an agent-callable tool. Strands reads the function's type hints and docstring to auto-generate the Bedrock tool JSON specification — no hand-written schema required. This keeps tools simple, self-documenting, and independently testable.

```python
@tool
def get_account_details(account_id: str) -> dict:
    """Retrieve full account details for a given account ID."""
    ...
```

**Built-in conversation management**  
`agent.messages` holds the full conversation history as a list of Bedrock Converse API-compatible message dicts. The framework handles USER / ASSISTANT turn alternation, tool result injection, and token count tracking automatically.

**Controlled streaming output**  
`callback_handler=None` silences Strands' default streaming output, giving `main.py` full control over what is rendered to the terminal. `CompositeCallbackHandler` allows future extension (e.g. streaming tokens to a frontend websocket) without changing tool or agent code.

**Platform alignment**  
Strands is maintained by AWS and is the declared foundation for AgentCore Runtime. `BedrockAgentCoreApp` wraps the same `BedrockModel` — ARIA's agent code requires no changes to run in local mode or under AgentCore.

### Implementation

`aria/agent.py` — `create_aria_agent()`:

1. Resolves the correct `model_id` for the target AWS region (Claude model ARNs differ by region)
2. Builds a `boto3.Session` using the full credential chain (env vars → `~/.aws` → instance profile) with optional IAM role assumption for cross-account deployments
3. Instantiates `BedrockModel(model_id=..., boto3_session=..., ...)`
4. Returns `Agent(model, system_prompt=ARIA_SYSTEM_PROMPT, tools=ALL_TOOLS, callback_handler=None)`

```python
def create_aria_agent() -> Agent:
    boto_session = _build_boto_session()
    model = BedrockModel(
        model_id=_resolve_model_id(boto_session),
        boto3_session=boto_session,
        max_tokens=8192,
    )
    return Agent(
        model,
        system_prompt=ARIA_SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        callback_handler=None,
    )
```

## Consequences

### What this enables

- Zero-boilerplate tool registration: add a `@tool`-decorated function, import it into `ALL_TOOLS`, done
- Automatic Bedrock tool spec generation from Python type hints and docstrings
- Transparent conversation history with `agent.messages` — accessible for transcripts and audit
- Drop-in AgentCore Runtime compatibility — `BedrockAgentCoreApp(create_aria_agent)` runs without modification
- `CompositeCallbackHandler` provides a future streaming extension point at no current cost

### Trade-offs and limitations

- Strands is a relatively young framework — APIs may change between minor versions
- `callback_handler=None` disables all default event hooks; any observability (token counts, latency) must be added explicitly
- Voice channel (Nova Sonic S2S bidirectional stream) cannot use the Strands agent loop — tools are dispatched directly via `_tool_map` in `aria/voice_agent.py` (see ADR-005)

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| LangChain | More abstraction layers, slower iteration for Bedrock-native tooling, heavier dependency tree; Bedrock integration requires additional adapters |
| AutoGen | Designed for multi-agent orchestration; overkill for a single-agent banking session; adds complexity with no benefit |
| LlamaIndex | Primarily a RAG/retrieval framework; not optimised for tool-calling banking agents |
| Custom agent loop | High maintenance burden; would require re-implementing Converse API message formatting, tool spec generation, turn management, and conversation history |

## Implementation reference

| File | Role |
|---|---|
| `aria/agent.py` | `create_aria_agent()` — builds `BedrockModel` and `Agent` with all tools |
| `aria/tools/__init__.py` | `ALL_TOOLS` list — all registered `@tool` functions |
| `aria/config.py` | `ARIA_SYSTEM_PROMPT`, region-to-model-ID mapping |
| `main.py` | Calls `create_aria_agent()`, drives the conversation loop, renders output |
| `aria/agentcore_app.py` | `BedrockAgentCoreApp(create_aria_agent)` — AgentCore Runtime entry point |

## Related documents

- [ADR-001: Audit Transcript Non-Blocking](ADR-001-audit-transcript-non-blocking.md)
- [ADR-003: Modular One-File-Per-Tool Architecture](ADR-003-modular-tool-architecture.md)
- [ADR-005: Nova Sonic 2 S2S — Direct API](ADR-005-nova-sonic-direct-api.md)
