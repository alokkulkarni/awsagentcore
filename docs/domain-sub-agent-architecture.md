# ARIA — Domain-Based Sub-Agent Architecture on AgentCore

## Overview

As ARIA evolves, the 20 banking tools can be grouped into **domain-specific Strands
agents**, each owning the tools for its domain. ARIA then becomes an **orchestrator
agent** that delegates to these sub-agents rather than calling tools directly.

This document explains:

1. Why and when to introduce domain sub-agents
2. How Strands multi-agent delegation works
3. How to host sub-agents on AgentCore (two models)
4. How the main ARIA chat and voice agents use them
5. How tools link to sub-agents rather than directly to ARIA

---

## Current structure vs proposed structure

### Current (monolithic)

```
ARIA (orchestrator + executor)
└── 20 tools (all domains, all in one agent)
      pii, auth, customer, account, debit_card,
      credit_card, mortgage, products, knowledge,
      analytics, escalation
```

ARIA is responsible for both deciding *what* to do and *doing it*. As the number
of tools grows this becomes harder to test, version, and reason about.

### Proposed (orchestrator + domain sub-agents)

```
ARIA Orchestrator (chat + voice)
├── AuthAgent          → verify_customer_identity, initiate_customer_auth,
│                        validate_customer_auth, cross_validate_session_identity
├── CustomerAgent      → get_customer_details, pii_detect_and_redact,
│                        pii_vault_store, pii_vault_retrieve, pii_vault_purge
├── AccountsAgent      → get_account_details, analyse_spending
├── CardsAgent         → get_debit_card_details, block_debit_card,
│                        get_credit_card_details
├── MortgageAgent      → get_mortgage_details
├── ProductsAgent      → get_product_catalogue, get_feature_parity
├── KnowledgeAgent     → search_knowledge_base
└── EscalationAgent    → generate_transcript_summary, escalate_to_human_agent
```

ARIA's job becomes: understand the customer's intent, route to the right domain
agent, synthesise the result into a coherent response. Each domain agent owns its
tools and its domain-specific reasoning.

---

## How Strands multi-agent delegation works

Strands supports wrapping one agent as a callable tool for another using the
`@tool` decorator or the `AgentTool` wrapper. The sub-agent receives a natural
language query and returns a natural language answer.

### Example: CardsAgent as a tool

```python
# aria/sub_agents/cards_agent.py

from strands import Agent, tool
from aria.tools.debit_card.card_details import get_debit_card_details
from aria.tools.debit_card.block_card import block_debit_card
from aria.tools.credit_card.card_details import get_credit_card_details

_cards_agent = Agent(
    model=bedrock_model,
    system_prompt=CARDS_SYSTEM_PROMPT,      # domain-focused, shorter prompt
    tools=[get_debit_card_details, block_debit_card, get_credit_card_details],
)

@tool
def cards_banking_agent(query: str, session_id: str) -> str:
    """Handle all card-related queries: balances, limits, blocking lost/stolen
    debit and credit cards, replacement requests."""
    return str(_cards_agent(f"[session_id={session_id}] {query}"))
```

### ARIA orchestrator uses sub-agents as tools

```python
# aria/agent.py (orchestrator version)

from aria.sub_agents.cards_agent   import cards_banking_agent
from aria.sub_agents.accounts_agent import accounts_banking_agent
from aria.sub_agents.auth_agent    import auth_banking_agent
# … other sub-agents

ORCHESTRATOR_TOOLS = [
    auth_banking_agent,
    accounts_banking_agent,
    cards_banking_agent,
    mortgage_banking_agent,
    products_banking_agent,
    knowledge_banking_agent,
    escalation_banking_agent,
    customer_banking_agent,   # includes PII tools
]

aria = Agent(
    model=bedrock_model,
    system_prompt=ARIA_ORCHESTRATOR_PROMPT,
    tools=ORCHESTRATOR_TOOLS,
)
```

When a customer says *"block my debit card"*, ARIA calls
`cards_banking_agent("Block the debit card for this session", session_id=...)`.
CardsAgent handles the tool calls (`block_debit_card`), returns the result, and
ARIA delivers the final response.

---

## Hosting on AgentCore — two models

### Model A: All sub-agents in one container (in-process)

All sub-agent Python objects live in the same Runtime container as ARIA.
Delegation is a Python function call — zero network overhead.

```
AgentCore Runtime Container
├── aria/agentcore_app.py          ← HTTP server (/invocations, /ws, /ping)
├── aria/agent.py                  ← ARIA orchestrator agent
└── aria/sub_agents/
      auth_agent.py                ← AuthAgent + auth tools
      cards_agent.py               ← CardsAgent + card tools
      accounts_agent.py            ← AccountsAgent + account tools
      …
```

**When to use Model A:**
- All domains belong to the same product (Meridian Bank retail banking)
- Sub-agents share the same secrets / bank API credentials
- You want a single deployable artefact

### Model B: Each sub-agent in its own AgentCore Runtime (separate containers)

Each domain agent is deployed as an independent AgentCore Runtime instance with
its own container, its own ECR image, and its own `/invocations` endpoint.
ARIA calls sub-agents over HTTP via AgentCore Gateway.

```
┌─────────────────────────────────────────────────────────┐
│  AgentCore Runtime  —  ARIA Orchestrator Container      │
│  POST /invocations  →  ARIA routes intent               │
│  WS   /ws           →  ARIA voice session               │
└─────────────┬──────────────────────────────┬────────────┘
              │ HTTP (via Gateway)            │ HTTP (via Gateway)
              ▼                              ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│  AgentCore Runtime       │    │  AgentCore Runtime       │
│  CardsAgent Container    │    │  AccountsAgent Container │
│  POST /invocations       │    │  POST /invocations       │
│  block_debit_card        │    │  get_account_details     │
│  get_credit_card_details │    │  analyse_spending        │
└─────────────────────────┘    └─────────────────────────┘
              ▲
              │ HTTP (via Gateway)
┌─────────────────────────┐
│  AgentCore Runtime       │
│  MortgageAgent Container │
│  POST /invocations       │
│  get_mortgage_details    │
└─────────────────────────┘
```

ARIA's sub-agent tools become HTTP client wrappers:

```python
@tool
def cards_banking_agent(query: str, session_id: str) -> str:
    """Handle all card-related queries."""
    response = requests.post(
        CARDS_AGENT_ENDPOINT,      # AgentCore Gateway URL for CardsAgent
        headers={"Authorization": f"Bearer {gateway_token}"},
        json={"message": query, "session_id": session_id},
    )
    return response.json()["response"]
```

The tool signature is **identical** to Model A from ARIA's perspective. Only the
implementation changes from a Python call to an HTTP call.

**When to use Model B:**
- Sub-agents need different IAM roles / API credentials (e.g., mortgage agent
  calls a different core banking system than the cards agent)
- Sub-agents must be independently scaled (cards queries peak at different times
  than mortgage queries)
- Sub-agents need independent deployment cycles (update CardsAgent without
  touching ARIA or MortgageAgent)
- Multiple front-end agents (ARIA retail + a branch-staff agent) both need the
  same CardsAgent endpoint

---

## How ARIA chat and voice agents use sub-agents

Neither `aria/agentcore_app.py` nor `aria/agentcore_voice.py` needs to change.
The only change is in the tool list the agent is constructed with:

### Chat channel

```python
# aria/agentcore_app.py  — chat handler (unchanged structure)
@app.entrypoint
def chat_handler(payload, context):
    agent = _CHAT_AGENTS.get(session_id) or create_aria_agent()
    return str(agent(prompt))
```

`create_aria_agent()` builds the Strands agent with whatever tool list is
configured — whether those tools delegate to in-process sub-agents (Model A)
or remote containers (Model B), the chat handler is identical.

### Voice channel

The voice channel dispatches tool calls from Nova Sonic via `_dispatch_tool()`
in `ARIAWebSocketVoiceSession`. Sub-agent tools are registered in `_tool_map`
exactly like any other tool. From Nova Sonic's perspective, calling
`cards_banking_agent` is no different from calling `get_debit_card_details`.

The key constraint for voice: **sub-agent tool calls must be fast** (< 2 s
end-to-end ideally). In Model B, each remote sub-agent call adds network latency
plus a second LLM inference call. For voice specifically, Model A (in-process)
is strongly preferred unless sub-agent isolation is a hard requirement.

---

## Tool ownership — who owns what

Under the sub-agent pattern, tools belong to sub-agents, not to ARIA.
ARIA's tool list becomes a list of sub-agent entry points.

| Domain sub-agent | Owns these tools |
|---|---|
| `AuthAgent` | `verify_customer_identity`, `initiate_customer_auth`, `validate_customer_auth`, `cross_validate_session_identity` |
| `CustomerAgent` | `get_customer_details`, `pii_detect_and_redact`, `pii_vault_store`, `pii_vault_retrieve`, `pii_vault_purge` |
| `AccountsAgent` | `get_account_details`, `analyse_spending` |
| `CardsAgent` | `get_debit_card_details`, `block_debit_card`, `get_credit_card_details` |
| `MortgageAgent` | `get_mortgage_details` |
| `ProductsAgent` | `get_product_catalogue`, `get_feature_parity` |
| `KnowledgeAgent` | `search_knowledge_base` |
| `EscalationAgent` | `generate_transcript_summary`, `escalate_to_human_agent` |

ARIA sees only **8 tools** (one per domain). Each sub-agent manages its own
tool set internally, with its own domain-specific system prompt.

### PII vault — a special case

The PII vault (`pii_vault_store`, `pii_vault_retrieve`) uses an in-memory
`_VAULT` dict keyed by `session_id`. If sub-agents move to separate containers
(Model B), the in-memory vault must be replaced with a shared session store
(e.g., ElastiCache Redis or AgentCore Memory) so all sub-agents can read/write
PII tokens for the same session. In Model A (same container), the vault
continues to work as-is.

---

## AgentCore Gateway role in Model B

In Model B, AgentCore Gateway acts as the routing layer between ARIA and the
domain sub-agent containers:

```
ARIA container → Gateway (mTLS + auth) → CardsAgent container /invocations
                                        → AccountsAgent container /invocations
                                        → MortgageAgent container /invocations
```

Gateway provides:
- **Auth** — signs requests between containers so sub-agent endpoints are not
  publicly callable without ARIA's credentials
- **Routing** — single base URL; path-based routing to the correct container
- **Rate limiting** — protects downstream sub-agents from runaway orchestrator calls
- **Observability** — centralised tracing across the call chain

In Model A, Gateway is not needed because all calls are in-process.

---

## Recommendation for ARIA today

| Consideration | Recommendation |
|---|---|
| Current tool count (20) | Still manageable in one agent; sub-agents not urgent |
| Voice latency sensitivity | Strongly favours Model A if sub-agents are introduced |
| Single product / single team | Model A — one container, one deployment |
| PII vault | Model A — keeps vault in-process, avoids shared store complexity |
| Future: multiple agents or independent domains | Introduce Model B domain-by-domain starting with non-PII domains (Mortgage, Products, Knowledge) |

**Recommended migration order when the time comes:**

1. **Phase 1** — Introduce sub-agents in-process (Model A). Restructure
   `aria/tools/__init__.py` into `aria/sub_agents/`. ARIA orchestrates 8
   sub-agent tools instead of 20 raw tools. Single container, no infra change.

2. **Phase 2** — Extract non-sensitive, stateless sub-agents to separate
   containers (MortgageAgent, ProductsAgent, KnowledgeAgent). These have no
   PII vault dependency and low call frequency — ideal first candidates for
   Model B.

3. **Phase 3** — Extract CardsAgent and AccountsAgent once shared session state
   (Redis or AgentCore Memory) is in place to support PII vault across
   containers.

4. **Phase 4** — AuthAgent and CustomerAgent remain in ARIA's container or
   become a sidecar — these are called on every session and carry PII, so
   they benefit least from remote isolation.
