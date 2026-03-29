# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records for the ARIA banking agent.

ADRs document significant design decisions — what was decided, why, what alternatives
were considered, and what the consequences are.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-audit-transcript-non-blocking.md) | Audit and Transcript Non-Blocking Design | Accepted | 2026-03-29 |
| [ADR-002](ADR-002-strands-agents-framework.md) | Strands Agents as the AI Agent Framework | Accepted | 2026-03-29 |
| [ADR-003](ADR-003-modular-tool-architecture.md) | Modular One-File-Per-Tool Architecture | Accepted | 2026-03-29 |
| [ADR-004](ADR-004-pii-vault-in-memory.md) | PII Vault — In-Memory Session-Scoped Token Store | Accepted | 2026-03-29 |
| [ADR-005](ADR-005-nova-sonic-direct-api.md) | Nova Sonic 2 S2S — Direct API over Strands Bidi SDK | Accepted | 2026-03-29 |
| [ADR-006](ADR-006-echo-gate-barge-in.md) | PyAudio Echo Gate + NOVA_BARGE_IN Opt-In for Local Voice | Accepted | 2026-03-29 |
| [ADR-007](ADR-007-agentcore-docker-ecr.md) | AgentCore Runtime — Docker Container in ECR (Not ZIP) | Accepted | 2026-03-29 |
| [ADR-008](ADR-008-in-process-tools-not-gateway.md) | In-Process Tool Execution (Not AgentCore Gateway) | Accepted | 2026-03-29 |
| [ADR-009](ADR-009-cross-region-model-access.md) | Cross-Region Model Access — Claude eu-west-2 / Nova Sonic eu-north-1 | Accepted | 2026-03-29 |
| [ADR-010](ADR-010-audit-eventbridge-three-tier.md) | Audit Event Compliance Storage — EventBridge Fan-Out Three-Tier | Accepted | 2026-03-29 |

## Format

Each ADR follows this structure:

- **Context** — the problem or question that needed a decision
- **Decision** — what was decided and how it works
- **Consequences** — latency impact, failure modes, trade-offs, alternatives rejected
- **Implementation reference** — which files implement the decision
- **Related documents** — links to supporting architecture docs
