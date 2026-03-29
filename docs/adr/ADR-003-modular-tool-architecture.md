# ADR-003: Modular One-File-Per-Tool Architecture

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

ARIA requires approximately 20 banking tools spanning 8 business domains: authentication, account management, debit cards, credit cards, mortgages, PII handling, analytics, knowledge base, customer escalation, and product catalogue. As the tool count grows, tool organisation becomes a significant maintainability concern:

- Tools need to be independently testable
- Domain experts (e.g. the mortgage team) need to find, add, and modify tools without understanding the full codebase
- The Strands `@tool` decorator requires all tools to be registered with the agent — the registration mechanism must be explicit and easy to audit
- Shared data models (Pydantic v2) and shared state (PII vault dict) must be accessible across tools in the same domain without circular imports

## Decision

**One Python file per tool, organised into domain subdirectories under `aria/tools/`.** All tools are registered in `aria/tools/__init__.py` via a single `ALL_TOOLS` list.

### Directory structure

```
aria/tools/
├── __init__.py              ← ALL_TOOLS = [tool1, tool2, ...]
├── auth/
│   ├── verify_customer_identity.py
│   ├── initiate_customer_auth.py
│   ├── validate_customer_auth.py
│   └── cross_validate_session_identity.py
├── account/
│   └── get_account_details.py
├── debit_card/
│   ├── get_debit_card_details.py
│   └── block_debit_card.py
├── credit_card/
│   └── get_credit_card_details.py
├── mortgage/
│   └── get_mortgage_details.py
├── customer/
│   └── get_customer_details.py
├── pii/
│   ├── pii_detect_and_redact.py
│   ├── vault_store.py       ← _VAULT dict lives here
│   ├── pii_vault_store.py
│   ├── pii_vault_retrieve.py
│   └── pii_vault_purge.py
├── analytics/
│   └── analyse_spending.py
├── knowledge/
│   ├── search_knowledge_base.py
│   └── get_feature_parity.py
├── escalation/
│   ├── escalate_to_human_agent.py
│   └── generate_transcript_summary.py
└── products/
    └── get_product_catalogue.py
```

### Key design choices

**Each tool is a standalone `@tool`-decorated function:**

```python
# aria/tools/account/get_account_details.py
from strands import tool
from aria.models.account import AccountDetails

@tool
def get_account_details(account_id: str) -> AccountDetails:
    """Retrieve full account details including balance, transactions, and status."""
    ...
```

Strands reads the type hints and docstring to auto-generate the Bedrock tool JSON spec. No separate schema file is needed.

**Centralised registration in `__init__.py`:**

```python
# aria/tools/__init__.py
from aria.tools.auth.verify_customer_identity import verify_customer_identity
from aria.tools.auth.initiate_customer_auth import initiate_customer_auth
# ... all other tools ...

ALL_TOOLS = [
    verify_customer_identity,
    initiate_customer_auth,
    validate_customer_auth,
    cross_validate_session_identity,
    get_account_details,
    get_debit_card_details,
    block_debit_card,
    # ...
]
```

The ordering in `ALL_TOOLS` is the order Bedrock receives the tool specs — authentication tools first, escalation tools last.

**Shared Pydantic models in `aria/models/`:**  
All tools import response models from `aria/models/` (e.g. `AccountDetails`, `DebitCard`, `Mortgage`). This ensures consistent response structure across tools without coupling tool files to each other.

**PII vault shared via module singleton:**  
The four PII tools (`pii_detect_and_redact`, `pii_vault_store`, `pii_vault_retrieve`, `pii_vault_purge`) all import `_VAULT` from `aria/tools/pii/vault_store.py`. Python module imports are singletons within a process, so all four tools share the same dict instance. See ADR-004 for the vault design rationale.

**Domain directories mirror Meridian Bank business domains:**  
The directory names (`auth/`, `mortgage/`, `debit_card/`) map directly to bank business units. Domain experts can navigate to their directory without reading the full codebase.

## Consequences

### What this enables

- Each tool file is independently testable with no test setup beyond importing the function
- Domain experts can add or modify tools in their domain directory without touching unrelated code
- `ALL_TOOLS` in `__init__.py` is a single, auditable list of every capability ARIA exposes to the LLM
- New domains require only a new subdirectory and imports in `__init__.py` — no framework changes
- Tool spec generation is fully automatic via Strands `@tool` + Python type hints

### Trade-offs and limitations

- `aria/tools/__init__.py` must be updated manually when adding a new tool — there is no auto-discovery
- 20+ files means more `import` lines; mitigated by the clear domain grouping
- Shared `_VAULT` dict works only within a single process — multi-process or multi-container deployments require a shared store (see ADR-004)

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| Single monolithic `tools.py` | Unmaintainable at 20+ tools; merge conflicts when multiple domain teams work simultaneously; hard to test individual tools in isolation |
| Auto-discovery via `importlib` scanning | Complex and fragile; import order in `ALL_TOOLS` cannot be controlled; scanning failures are hard to debug |
| Class-based tools (`ToolRegistry` with methods) | More boilerplate; Strands `@tool` decorator is designed for module-level functions, not class methods |
| Domain-level `__init__.py` with wildcard imports | Hides exactly which tools are registered; `ALL_TOOLS` construction becomes non-obvious |

## Implementation reference

| File | Role |
|---|---|
| `aria/tools/__init__.py` | `ALL_TOOLS` list — single source of truth for registered tools |
| `aria/tools/*/` | One file per tool, grouped by domain |
| `aria/tools/pii/vault_store.py` | `_VAULT` dict shared by all four PII tools |
| `aria/models/` | Pydantic v2 response models shared across tools |
| `aria/agent.py` | Passes `ALL_TOOLS` to `Agent(tools=ALL_TOOLS, ...)` |

## Related documents

- [ADR-002: Strands Agents as the AI Agent Framework](ADR-002-strands-agents-framework.md)
- [ADR-004: PII Vault — In-Memory Session-Scoped Token Store](ADR-004-pii-vault-in-memory.md)
