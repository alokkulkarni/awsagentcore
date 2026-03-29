# ADR-004: PII Vault — In-Memory Session-Scoped Token Store

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

Customer PII flows through ARIA's conversation: full names, dates of birth, account numbers, card numbers, sort codes, home addresses, and National Insurance Numbers (NINOs). If stored raw in the conversation history, this data would appear in:

- LLM prompts sent to Bedrock (logged by CloudWatch)
- AgentCore Memory (persisted conversation context)
- Audit transcripts written to S3
- Any future RAG indexing of conversation history

This creates GDPR, PCI-DSS, and FCA regulatory exposure. PCI-DSS DSS v4 explicitly prohibits storing full card numbers in conversation logs; GDPR requires data minimisation. The design must ensure PII is never written to any persistent store in plaintext.

## Decision

**An in-memory module-level dict (`_VAULT`) serves as a session-scoped token vault.** PII is replaced with opaque tokens before entering the conversation history. The four PII tools implement the complete pipeline:

### The four-step PII pipeline

**Step 1 — `pii_detect_and_redact`**  
Scans text for PII patterns using regex. Replaces each detected value with a token in the format `[PII:<TYPE>:<8-hex-chars>]`. Returns the redacted text for inclusion in `agent.messages`.

```
Input:  "My name is Jane Smith and my account is 12345678"
Output: "My name is [PII:NAME:a3f7c2d1] and my account is [PII:ACCOUNT:b9e1f4a2]"
```

Detected PII types: `NAME`, `DOB`, `ACCOUNT`, `CARD`, `SORTCODE`, `ADDRESS`, `NINO`, `EMAIL`, `PHONE`.

**Step 2 — `pii_vault_store`**  
Stores the `token → plaintext_value` mapping in `_VAULT`. Called immediately after `pii_detect_and_redact` so the token is resolvable for the remainder of the session.

```python
# aria/tools/pii/vault_store.py
_VAULT: dict[str, str] = {}

# aria/tools/pii/pii_vault_store.py
from aria.tools.pii.vault_store import _VAULT

@tool
def pii_vault_store(token: str, value: str) -> dict:
    """Store a PII token-value pair in the session vault."""
    _VAULT[token] = value
    return {"stored": token}
```

**Step 3 — `pii_vault_retrieve`**  
Resolves a token back to its plaintext value. Called only by tools that need the real value to perform an action (e.g. `get_account_details` needs the real account number to query the data source).

```python
@tool
def pii_vault_retrieve(token: str) -> dict:
    """Retrieve a plaintext PII value by its token."""
    value = _VAULT.get(token)
    return {"token": token, "value": value, "found": value is not None}
```

**Step 4 — `pii_vault_purge`**  
Clears all tokens from `_VAULT`. Called by ARIA as part of the session goodbye flow — the system prompt instructs ARIA to call `pii_vault_purge` before ending any session.

```python
@tool
def pii_vault_purge() -> dict:
    """Purge all PII tokens from the session vault. Call at session end."""
    count = len(_VAULT)
    _VAULT.clear()
    return {"purged": count}
```

### Why the vault is in-memory

**O(1) lookup latency:** A dict lookup adds zero measurable latency to tool calls. There is no network round-trip, no serialisation, no connection pool.

**No external failure mode:** The vault never introduces a new point of failure. If Bedrock is reachable, the vault is reachable. There is no Redis timeout, no DynamoDB throttle, no Secrets Manager rate limit to account for.

**Natural session scoping:** Each ARIA process handles one customer session (local) or one AgentCore microVM invocation (cloud). The process boundary is the session boundary. The vault is automatically scoped to the session with no TTL configuration required.

**Guaranteed isolation in AgentCore:** AWS AgentCore runs each session in an isolated microVM. Different customer sessions cannot share the same Python process, so they cannot share `_VAULT`. Session isolation is enforced by the platform, not by the application.

**Automatic cleanup via purge:** `pii_vault_purge` is called as part of ARIA's scripted goodbye flow. Even if purge is not called (e.g. abrupt disconnect), the vault is destroyed when the process exits — PII is never persisted.

### Module singleton pattern

All four PII tools import `_VAULT` from the same module:

```python
from aria.tools.pii.vault_store import _VAULT
```

Python's module import system caches modules after first import. All four tools hold a reference to the same dict object. Mutations in `pii_vault_store` are immediately visible in `pii_vault_retrieve` and `pii_vault_purge`.

## Consequences

### What this enables

- PII never appears in `agent.messages`, CloudWatch Logs, AgentCore Memory, or S3 transcripts in plaintext
- GDPR data minimisation and PCI-DSS card data protection requirements are met at the application layer
- Zero-latency token resolution — banking tool calls are not slowed by vault lookups
- No operational overhead — no Redis cluster, no DynamoDB table, no Secrets Manager path to manage

### Trade-offs and limitations

- **Crash before purge:** If the process crashes mid-session, `_VAULT` is lost without explicit purge. This is acceptable because the vault holds session-transient data only — it is not a source of truth for customer data
- **No persistence:** The vault cannot survive process restart. This is by design — vault tokens are session-scoped and meaningless after the session ends
- **Single-process only:** If domain sub-agents run in separate containers (see the domain sub-agent architecture roadmap), each container has its own `_VAULT` instance. Tokens created in the orchestrator container are not resolvable in domain agent containers. Migration to a shared store (Redis/ElastiCache) would be required if that architecture is adopted
- **In-memory capacity:** For a standard banking session (< 100 PII tokens), memory consumption is negligible (< 10 KB). Not a practical concern

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| AWS Secrets Manager | Designed for static credentials/secrets, not session-scoped ephemeral tokens; ~50 ms per API call adds unacceptable latency; per-request cost at scale; rate limits apply |
| Amazon DynamoDB with TTL | External network call per vault operation adds 1–5 ms latency; TTL-based cleanup is eventual (DynamoDB TTL is best-effort, not guaranteed); significant over-engineering for session-transient data |
| AWS KMS envelope encryption | Wrong use case — KMS encrypts data at rest; it does not provide session-scoped token substitution; would require storing encrypted blobs somewhere, which doesn't solve the problem |
| Redis / ElastiCache | External dependency with operational overhead (cluster management, failover, network ACLs); justified only if sub-agents in separate containers need to share vault; not needed for current architecture |
| Encrypt PII in conversation history (keep in messages) | Does not achieve data minimisation; encrypted PII is still PII under GDPR; complexity of key management in a conversational context |

## Implementation reference

| File | Role |
|---|---|
| `aria/tools/pii/vault_store.py` | `_VAULT` dict — the single shared vault instance |
| `aria/tools/pii/pii_detect_and_redact.py` | Regex PII detection + token substitution |
| `aria/tools/pii/pii_vault_store.py` | `pii_vault_store` tool — writes token → value |
| `aria/tools/pii/pii_vault_retrieve.py` | `pii_vault_retrieve` tool — reads value by token |
| `aria/tools/pii/pii_vault_purge.py` | `pii_vault_purge` tool — clears all vault entries |
| `aria/config.py` | `ARIA_SYSTEM_PROMPT` — includes instruction to call `pii_vault_purge` at session end |

## Related documents

- [ADR-003: Modular One-File-Per-Tool Architecture](ADR-003-modular-tool-architecture.md)
- [ADR-001: Audit Transcript Non-Blocking](ADR-001-audit-transcript-non-blocking.md)
- `docs/domain-sub-agent-architecture.md` — future sub-agent design requiring shared vault
