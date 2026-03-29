# ADR-001: Audit and Transcript Non-Blocking Design

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

ARIA serves banking customers in real time over two channels:

- **Chat** — synchronous HTTP request/response (AgentCore `/invocations`)
- **Voice** — live bidirectional audio stream (Nova Sonic 2 S2S over `/ws`)

Both channels require two cross-cutting concerns to run alongside every customer interaction:

1. **Transcript saving** — conversation turns recorded for training, QA, and complaints handling
2. **Audit event emission** — immutable structured records of every tool invocation for FCA, PCI-DSS, GDPR, and SOX compliance

The key architectural question was: **where in the execution path do these run, and can they block, slow, or break the customer experience?**

---

## Decision

### 1. Transcript and audit run after the LLM response is computed — never during

For **chat**, the sequence is:

```
agent(prompt)          ← LLM runs; response fully formed before next line executes
    │
    ▼  response ready
_emit_audit()          ← post-processing only; customer answer already in memory
transcript.add_turn()  ← in-memory list append; ~0.001 ms
transcript.save()      ← file/S3 write; happens after return in local mode
    │
    ▼
return aria_text       ← customer receives their answer
```

The LLM (`agent(prompt)`) is entirely unaffected. Audit and transcript only run once the response is already computed and ready.

### 2. Voice audit uses `async_record()` — I/O is fully off the event loop

For **voice**, tool calls run inside the asyncio event loop that also manages audio capture, Nova Sonic streaming, and WebSocket I/O. A synchronous boto3 call (EventBridge `PutEvents`, ~50 ms) on the event loop would block all audio I/O during that window.

Decision: `AuditManager.async_record()` offloads all I/O to a thread-pool executor via `asyncio.get_event_loop().run_in_executor()`. It is called with `await` but returns immediately — the executor runs the I/O concurrently with audio processing.

```
asyncio.to_thread(tool_func)    ← tool result computed off event loop
    │
    ▼  result ready
await _audit.async_record()     ← fires executor task; event loop not blocked
return result to Nova Sonic     ← immediate; no wait for audit I/O
```

Chat channels use the synchronous `audit.record()` — they are not on an audio event loop and the sync call (~5 ms locally, ~50–200 ms in cloud) is acceptable post-response overhead.

### 3. All failures are silently caught — never propagate to the customer

Every I/O call (local JSONL write, S3 `PutObject`, EventBridge `PutEvents`) is wrapped in a `try/except Exception`. On failure:

- The error is logged at `ERROR` level to CloudWatch / `aria.log`
- The banking session continues unaffected
- The customer never sees an error message caused by an audit or transcript failure

This is a deliberate trade-off: **observability infrastructure must never degrade the banking interaction**.

---

## Consequences

### Latency impact (measured / estimated)

| Operation | Local mode | Cloud mode (EventBridge + S3) |
|---|---|---|
| `add_turn()` | ~0.001 ms | ~0.001 ms |
| `audit.record()` / JSONL | ~0.5 ms | n/a (sync not used on voice) |
| `await async_record()` (voice) | ~0.5 ms | fires in background — **0 ms added to audio path** |
| `_emit_audit()` (chat, post-LLM) | ~0.5 ms | ~10–50 ms per tool call |
| `transcript.save()` | ~2 ms | ~50–200 ms |
| **Total added per turn** | **< 5 ms** | **~60–250 ms post-LLM** |

For context: an LLM response from Claude Sonnet takes 1–5 seconds. The 60–250 ms post-response overhead in cloud mode is less than 5–10% of total turn latency and is imperceptible to the customer.

For voice: the overhead is **zero** on the audio path because `async_record()` uses the executor.

### Failure modes

| Failure | Impact on customer | Logged? |
|---|---|---|
| Local disk full — JSONL write fails | None | Yes (`ERROR`) |
| S3 unreachable — transcript upload fails | None | Yes (`ERROR`) |
| EventBridge unreachable — audit publish fails | None | Yes (`ERROR`) |
| DynamoDB write fails (downstream EventBridge rule) | None | Via EventBridge DLQ |
| CloudTrail Lake ingestion fails | None | Via EventBridge DLQ |

### Data durability trade-offs

- **Local JSONL**: synchronous append — event is written before the next tool call starts. Durable as long as the process does not crash mid-write.
- **Cloud chat (S3 transcript)**: written every turn for crash-durability. If the AgentCore microVM is recycled mid-session, all turns up to the last completed turn are preserved.
- **Cloud voice (EventBridge)**: fired-and-forgotten asynchronously. If the process crashes between `run_in_executor` scheduling and the executor actually running, the event may be lost. For voice, this is an acceptable trade-off given the audio latency requirement. Tier 1 events (card block, auth) are additionally captured in CloudWatch Logs via the tool's own `logger.info` calls.

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| Write audit synchronously in `_execute_tool()` | Would block the audio event loop on EventBridge calls in cloud voice mode |
| Background `asyncio.create_task()` | Requires an active event loop at schedule time; `run_in_executor` is simpler and works from any async context |
| Dedicated audit microservice / sidecar | Operational overhead disproportionate to current scale; revisit when audit volume exceeds EventBridge's 10,000 events/sec limit |
| Kafka / Kinesis for audit streaming | Same — future consideration at higher scale; EventBridge is sufficient and fully managed |
| Disable audit for Tier 3 (informational) tools | Decided to keep all tiers for completeness; Tier 3 events are cheap and provide full data lineage |

---

## Implementation reference

| File | Role |
|---|---|
| `aria/audit_manager.py` | `AuditManager.record()` (sync, chat), `async_record()` (async, voice), `emit_chat_tool_audits()` (Strands message inspector) |
| `aria/voice_agent.py` | `_execute_tool()` calls `await _audit.async_record()` after tool result |
| `aria/agentcore_voice.py` | Same pattern |
| `aria/agentcore_app.py` | `_emit_audit()` called post-`agent(prompt)`, pre-`return` |
| `main.py` | Same pattern; `len(agent.messages)` snapshot before call |
| `aria/transcript_manager.py` | `add_turn()` in-memory; `save()` sync file/S3 write at session end |

---

## Related documents

- `docs/audit-event-architecture.md` — full audit storage architecture (tiers, EventBridge fan-out, CloudTrail Lake, DynamoDB, S3 WORM)
- `docs/agentcore-deployment-guide.md` — EventBridge bus setup, IAM permissions, CloudTrail Lake channel creation, query examples
- `docs/transcript-storage.md` — transcript S3 key structure, IAM, Athena usage
