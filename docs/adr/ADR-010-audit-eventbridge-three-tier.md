# ADR-010: Audit Event Compliance Storage — EventBridge Fan-Out to Three-Tier Architecture

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

UK banking regulatory requirements mandate a durable, immutable audit trail for customer-impacting actions:

| Regulation | Relevant requirement |
|---|---|
| FCA SYSC 9 | Retain records of customer interactions; demonstrate controls |
| PCI-DSS v4 (Req. 10.5.2) | Protect audit logs from modification and destruction (WORM) |
| GDPR Article 5(2) | Accountability — demonstrate lawful, transparent data processing |
| SOX Section 802 | Preserve financial records; prohibit alteration or destruction |
| FCA retention period | 7+ years for most categories; 10+ years for certain financial records |

ARIA makes tool calls that mutate customer state or initiate banking actions (card blocks, escalations, statement requests, instrument orders). These must be audited with:

- **Immutability** — records cannot be altered or deleted after creation
- **WORM storage** — required specifically for payment and card events (PCI-DSS 10.5.2)
- **Real-time queryability** — complaint handling and fraud investigations require sub-second lookups
- **Long-term retention** — 7–10 years at low cost

Additionally, the audit mechanism must not block or slow ARIA's response path (see ADR-001).

## Decision

Audit events are published to an EventBridge custom bus (`meridian-aria-audit`) and fanned out to three independent storage tiers:

```
ARIA Tool Call
    ↓
AuditManager.record() / async_record()
    ↓
EventBridge Custom Bus (meridian-aria-audit)
    ├─→ CloudTrail Lake        (immutable, cryptographically signed, 7yr retention, SQL queryable)
    ├─→ DynamoDB               (hot queries, 90-day TTL, GSI on customer_id + timestamp)
    └─→ S3 Object Lock (WORM)  via Kinesis Data Firehose (WORM archive; Glacier after 90 days)
```

**Tool tier classification** (defined in `aria/audit_manager.py` `_TOOL_META`):

| Tier | Examples | Storage targets |
|---|---|---|
| Tier 1 — Critical | `block_debit_card`, `block_credit_card` | All three tiers; immediate PCI-DSS audit |
| Tier 2 — Significant | `verify_customer_identity`, `get_account_details`, `escalate_to_human_agent` | All three tiers |
| Tier 3 — Informational | `get_product_catalogue`, `search_knowledge_base` | CloudTrail Lake only |

**Audit event schema** (fields emitted by `AuditManager`):

| Field | Description |
|---|---|
| `event_id` | UUID4 — globally unique per event |
| `customer_id` | Pseudonymised customer reference |
| `session_id` | AgentCore or local session identifier |
| `timestamp` | ISO-8601 with timezone |
| `tool_name` | Name of the ARIA tool invoked |
| `tool_tier` | 1 / 2 / 3 — classification from `_TOOL_META` |
| `tool_category` | Domain: accounts / cards / payments / pii / etc. |
| `event_type` | `tool_invocation` / `tool_result` / `session_start` / etc. |
| `severity` | `INFO` / `WARN` / `CRITICAL` |
| `params` | Sanitised input — PIN, CVV, and full card numbers redacted |
| `result_summary` | Non-PII summary of tool outcome |
| `execution_channel` | `local_chat` / `local_voice` / `agentcore_chat` / `agentcore_voice` |
| `agent_version` | Deployed ARIA version string |
| `aws_account_id` | AWS account ID for the running container |
| `aws_region` | Runtime region (eu-west-2) |

**Non-blocking guarantee:**

`EventBridge.put_events()` is dispatched via `ThreadPoolExecutor` through `asyncio.get_event_loop().run_in_executor()` — the event loop is never blocked by audit I/O. See ADR-001 for the full non-blocking design rationale.

```python
# aria/audit_manager.py (simplified)
async def async_record(self, tool_name: str, params: dict, result: dict) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(self._executor, self._put_event, tool_name, params, result)
```

**Local development mode:**

When running without AWS credentials, `AuditManager` writes JSONL to `audit/{customer_id}/{date}/audit.jsonl`. The schema is identical to the cloud event schema, enabling local output to be compared against cloud audit records. The `audit/` directory is excluded from git via `.gitignore`.

**Why EventBridge fan-out over direct multi-target writes:**

- ARIA makes a single `put_events()` call — it has no knowledge of or dependency on the storage topology.
- Storage tiers can be reconfigured (targets added, removed, or changed) by updating EventBridge rules; no code change required.
- CloudTrail Lake is the authoritative immutable record; DynamoDB and S3 are projections that can be reconstructed from CloudTrail Lake via event replay if lost.

**Why CloudTrail Lake as the primary tier:**

- Purpose-built for audit workloads: cryptographic hash-chaining makes records tamper-evident.
- Cannot be deleted without root account action — satisfies FCA immutability requirement without custom enforcement logic.
- SQL-queryable via CloudTrail Lake Insights — compliance teams can run self-serve queries without engineering involvement.
- 7-year default retention aligns with FCA SYSC 9 record-keeping rules.

**Why DynamoDB as the second tier:**

- P99 read latency < 5 ms — complaint handling and fraud investigation teams get real-time results.
- GSI on `(customer_id, timestamp)` supports queries such as "show all actions on this account in the last 30 days".
- 90-day TTL keeps the DynamoDB table small and cost-efficient; records older than 90 days are covered by CloudTrail Lake and S3 WORM.

**Why S3 Object Lock (WORM) via Kinesis Firehose as the third tier:**

- Object Lock in **COMPLIANCE mode** — records are immutable even to the AWS account owner, satisfying PCI-DSS 10.5.2 without additional controls.
- Lifecycle policy moves objects to Glacier Deep Archive after 90 days (~$0.00099/GB/month), making 7–10 year retention economically viable.
- Firehose handles batching and delivery; no custom code is required for S3 writes.

## Consequences

### What this enables

- A single `put_events()` call satisfies immutability (CloudTrail Lake), real-time query (DynamoDB), and WORM archival (S3) requirements simultaneously.
- Compliance team can query CloudTrail Lake directly with SQL — no engineering ticket required for routine audit queries.
- WORM guarantee for PCI-DSS 10.5.2 satisfied by S3 Object Lock COMPLIANCE mode.
- Storage topology is decoupled from agent code — new storage targets can be added via EventBridge rules.
- ARIA's response path is never blocked by audit I/O.

### Trade-offs and limitations

- **EventBridge delivery is asynchronous and at-least-once** — in the event of a transient EventBridge failure, events may be delayed but not lost (EventBridge retries). In an extreme failure scenario, events could be missed; mitigated by CloudTrail's own event capture and DLQ on EventBridge targets.
- **Three storage tiers = three sets of IAM policies, monitoring, and cost lines** — higher operational surface than a single-tier solution.
- **DynamoDB TTL is best-effort** — records may persist slightly beyond 90 days before AWS deletes them. This is acceptable; the TTL is for cost management, not compliance.
- **S3 Object Lock COMPLIANCE mode cannot be overridden** — if an audit record is written incorrectly (e.g., contains PII that should not have been stored), it cannot be deleted for the lock duration. `_sanitise_params()` in `AuditManager` mitigates this by redacting sensitive fields before the event is emitted.

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| CloudWatch Logs only | Not immutable; cannot satisfy FCA or PCI-DSS immutability requirement |
| DynamoDB only | Not WORM; expensive for 7+ year retention at scale; no cryptographic tamper detection |
| Amazon QLDB | Being deprecated by AWS; not a viable new investment |
| Self-managed Postgres audit tables | Operational overhead; no WORM guarantee without additional tooling; managed backup strategy required for compliance |
| Kinesis Data Streams → S3 only | Single tier; no real-time query capability for complaint handling; no CloudTrail Lake tamper detection |
| CloudTrail Lake only (no DynamoDB) | CloudTrail Lake query latency (~seconds) is too slow for real-time complaint handling workflows |

## Implementation reference

| File | Role |
|---|---|
| `aria/audit_manager.py` | `AuditManager` class; `_TOOL_META` tier definitions; `record()`, `async_record()`, `emit_chat_tool_audits()`, `_sanitise_params()` |
| `aria/voice_agent.py` | Calls `await _audit.async_record()` inside `_execute_tool()` for voice sessions |
| `aria/agentcore_voice.py` | Same `async_record()` pattern for AgentCore-hosted voice sessions |
| `aria/agentcore_app.py` | `_msg_idx` snapshot + `emit_chat_tool_audits()` called after each `agent()` invocation |
| `main.py` | Same message snapshot pattern for local chat sessions |

## Related documents

- [docs/audit-event-architecture.md](../audit-event-architecture.md) — detailed storage architecture with IAM policies, DynamoDB schema, CloudTrail Lake query examples, and Firehose configuration
- [docs/agentcore-deployment-guide.md](../agentcore-deployment-guide.md) — EventBridge bus setup section
- [ADR-001](ADR-001-audit-transcript-non-blocking.md) — non-blocking async design for audit and transcript I/O
