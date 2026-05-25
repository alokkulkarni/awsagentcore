# Brainstorming Agent Deployment Playbook

| Field | Value |
|---|---|
| **Document ID** | PLY-BRAIN-001 |
| **Version** | 1.0 |
| **Status** | Active |
| **Owner** | Platform Engineering |
| **Date** | 2026-05-25 |
| **Classification** | Internal |
| **Companion Runbook** | `docs/runbooks/brainstorming-agent-runbook.md` |

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Deployment Strategy](#4-deployment-strategy)
5. [Environment Matrix](#5-environment-matrix)
6. [Change Management](#6-change-management)
7. [Risk Register](#7-risk-register)
8. [Rollback Strategy](#8-rollback-strategy)
9. [Communication Plan](#9-communication-plan)
10. [Success Criteria](#10-success-criteria)
11. [Post-Deployment Validation](#11-post-deployment-validation)
12. [Contacts and Escalation](#12-contacts-and-escalation)
13. [Approvals](#13-approvals)

---

## 1. Purpose

The Brainstorming Agent is an internal AI brainstorming workspace used to capture, expand, and revisit strategic ideas through a conversational interface. The component combines a FastAPI backend, Strands-based agent tooling, SQLite-backed memory, WebSocket streaming, and a React + Vite + Tailwind frontend with browser-native voice support.

### 1.1 Service Summary

| Capability | Implementation |
|---|---|
| Conversational runtime | FastAPI app with Strands agent orchestration |
| Model provider | Amazon Bedrock |
| Default model | `eu.anthropic.claude-sonnet-4-6` |
| Memory store | SQLite (`sessions`, `memories`, `memory_links`, `audit_log`) |
| Search | SQLite FTS5 over memories |
| Streaming | WebSocket token streaming |
| Frontend | React + Vite + Tailwind via nginx |
| Voice mode | Browser Web Speech API (speech-to-text and text-to-speech) |

### 1.2 Operational Scope

This playbook governs deployment, change control, rollback, validation, and communication for the Brainstorming Agent component under `brainstorming-agent/`.

---

## 2. Architecture

### 2.1 Logical Architecture

```text
User Browser
   |
   v
Frontend (React + Vite + Tailwind + nginx) :3000
   |-- /api/* --> FastAPI backend :8000 host / :8200 container
   |-- /ws/*  --> WebSocket stream to FastAPI backend
   |
   v
Strands agent runtime
   |
   +--> Amazon Bedrock (`eu.anthropic.claude-sonnet-4-6`)
   |
   +--> SQLite memory store (sessions, memories, memory_links, audit_log, FTS5)
```

### 2.2 Container and Port Model

| Component | Runtime | Internal Port | Host Port | Notes |
|---|---|---:|---:|---|
| Backend | FastAPI / Uvicorn | 8200 | 8000 | Direct health/API access |
| Frontend | nginx serving Vite build | 5175 | 3000 | Proxies `/api/` and `/ws/` to backend |
| Database | SQLite file | n/a | n/a | Persisted at `/app/data/brainstorm.db` via Docker volume |

### 2.3 Key Architectural Controls

- FastAPI initializes the SQLite schema at startup.
- The agent binds each session to Strands tools for save/search/link memory operations.
- WebSocket sessions stream tool activity, tokens, completion, and safety metadata in real time.
- The frontend reconnects WebSocket sessions with exponential backoff on unexpected disconnects.
- Voice is browser-native only; no server-side speech stack is deployed.

---

## 3. Prerequisites

### 3.1 Tooling

- Docker Desktop or compatible Docker engine
- Python 3.12+
- Node.js 20+
- AWS credentials with Amazon Bedrock access

### 3.2 Required Configuration

| Variable | Required | Purpose |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Yes | AWS authentication |
| `AWS_SECRET_ACCESS_KEY` | Yes | AWS authentication |
| `AWS_SESSION_TOKEN` | Optional | Temporary credentials / SSO |
| `AWS_DEFAULT_REGION` | Yes | SDK region for Bedrock |
| `AWS_REGION` | Recommended | Explicit Bedrock runtime region |
| `BEDROCK_MODEL_ID` | Yes | Bedrock model selection |
| `DB_PATH` | Optional | SQLite path override |

### 3.3 Access Validation

- Confirm Bedrock model access before deployment.
- Confirm the selected region supports the target model.
- Confirm Docker can mount a persistent local volume.

---

## 4. Deployment Strategy

### 4.1 Primary Mode — Local Docker Compose

The supported deployment path in the current component is Docker Compose:

```bash
cd brainstorming-agent
cp docker/.env.example docker/.env
# edit docker/.env

docker compose -f docker/docker-compose.yml up --build
```

This path builds both containers, starts the backend and frontend, mounts a persistent Docker volume for SQLite, and exposes the UI on `http://localhost:3000` plus the backend health/API endpoint on `http://localhost:8000`.

### 4.2 Cloud Path

The repository review for this document found no component-local `brainstorming-agent/deploy.sh`. Treat cloud deployment as a controlled extension path, not a currently validated repo workflow. If a future deployment script is introduced, the standard invocation should be:

```bash
./deploy.sh deploy
```

Any cloud rollout must document created resources, endpoint URLs, state storage, and teardown steps before production use.

### 4.3 Deployment Principles

- Prefer immutable rebuilds over in-place edits.
- Preserve the SQLite volume across container restarts.
- Apply model changes and protocol changes only with a validation window.
- Use the runbook for execution details and operator commands.

---

## 5. Environment Matrix

| Environment | Runtime Mode | AWS Infrastructure | Bedrock Dependency | Data Persistence | Primary Use |
|---|---|---|---|---|---|
| Local Docker | Docker Compose | None beyond operator credentials | Yes | Docker volume (`brainstorm_data`) | Development, demos, smoke tests |
| Cloud | Future scripted deployment | To be defined by deploy automation | Yes | Must be explicitly designed | Shared/internal hosted usage |

---

## 6. Change Management

All changes to the Brainstorming Agent must be assessed for operational impact before release.

### 6.1 Standard Change Types

| Change Type | Impact Area | Required Control |
|---|---|---|
| SQLite schema migration | Persistence, compatibility, backup/restore | Backup before release; test migration and rollback |
| Bedrock model update | Cost, latency, output quality | Validate permissions, response quality, and throttling behaviour |
| WebSocket protocol change | Frontend/backend compatibility | Version both ends together and smoke-test streaming |
| Voice UI change | Browser compatibility | Validate Chrome/Edge support and graceful text fallback |
| Docker image update | Startup behaviour and dependency resolution | Rebuild images and re-run health checks |

### 6.2 Approval Expectations

- Minor operational config changes: Platform Engineering approval
- Schema or protocol changes: Platform Engineering plus application owner review
- Model or region changes: Platform Engineering plus security/compliance awareness where required

---

## 7. Risk Register

| ID | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R1 | Bedrock throttling or transient Bedrock failures | Response delays or failed sessions | Medium | Implement retry/backoff, monitor error rates, document service limits |
| R2 | SQLite file loss on container recreation | Loss of sessions and memories | Medium | Mount persistent volume and take routine backups |
| R3 | WebSocket connection drops | Broken live responses or stale UI state | Medium | Use browser reconnect logic and validate nginx `/ws/` proxy path |
| R4 | Browser voice API unsupported | Voice mode unavailable | High | Fall back to text chat and document browser requirements |
| R5 | SQLite locking under concurrent access | Write failures or degraded UX | Medium | Keep access patterns simple, monitor audit errors, consider WAL/tuning if concurrency grows |
| R6 | Credential misconfiguration | Backend starts but Bedrock calls fail | Medium | Validate AWS identity and region before go-live |

---

## 8. Rollback Strategy

### 8.1 Docker Rollback

- Revert to the last known-good image/build context.
- Restart the stack with the prior application version.
- Preserve the existing SQLite volume unless data corruption is suspected.

### 8.2 Data Rollback

- Take a SQLite dump before any schema-affecting change.
- Restore from the latest valid backup if data corruption or migration failure occurs.
- Revalidate session listing, memory search, and linked-memory retrieval after restore.

### 8.3 Change-Specific Rollback

| Change | Rollback Action |
|---|---|
| Model update | Restore previous `BEDROCK_MODEL_ID` and restart backend |
| WebSocket/frontend change | Roll back frontend and backend together |
| Schema migration | Restore backup, redeploy previous build, verify FTS search |

---

## 9. Communication Plan

| Phase | Audience | Message |
|---|---|---|
| Pre-change | Platform Engineering, stakeholders | Scope, planned window, risk summary, rollback path |
| Start of deployment | Operators, impacted users | Deployment in progress, expected duration |
| Validation complete | Stakeholders | Deployment successful, health checks passed |
| Incident or rollback | Stakeholders, incident lead | Symptoms, impact, rollback status, next update time |

### 9.1 Minimum Communications

- Announce schema, model, or protocol changes before execution.
- Record validation results after deployment.
- Record any rollback decision and data restore action.

---

## 10. Success Criteria

The deployment is successful only when all of the following are true:

- FastAPI health endpoint returns HTTP 200.
- Frontend is reachable on `http://localhost:3000`.
- WebSocket streaming returns token events and a final completion event.
- Memories can be saved and later retrieved through session or search views.
- Voice mode works in Chrome and degrades safely to text where unsupported.
- Audit entries appear for user messages, assistant responses, tool calls, and safety analysis.

---

## 11. Post-Deployment Validation

Run the companion runbook and confirm:

1. `curl http://localhost:8000/health` returns `status: ok`.
2. Frontend loads successfully at `http://localhost:3000`.
3. A new session can be created.
4. A brainstorming prompt produces streamed output.
5. At least one memory can be retrieved through `/memories/search` or the memory browser.
6. Logs show no persistent Bedrock authentication, WebSocket, or SQLite errors.

---

## 12. Contacts and Escalation

| Priority | Contact Group | Trigger |
|---|---|---|
| P1 | Platform Engineering | Service unavailable, data loss, unrecoverable startup failure |
| P2 | Application owner / maintainers | Functional defect, degraded memory or streaming behaviour |
| P3 | Frontend owner | Voice/browser UI issues, rendering or proxy issues |
| Vendor/Cloud | AWS Support | Bedrock regional outage, account-level throttling, IAM anomalies |

### 12.1 Escalation Guidance

- Escalate immediately for data loss indicators, repeated health check failures, or sustained Bedrock 4xx/5xx errors.
- Escalate after first failed retry cycle for WebSocket-wide disconnect issues.

---

## 13. Approvals

| Role | Approval Required | Status |
|---|---|---|
| Platform Engineering | Yes | Pending operational use |
| Application Owner | Yes | Pending operational use |
| Security / Compliance | As required for cloud hosting changes | Conditional |

Approved versions of this playbook become the operating baseline for future Brainstorming Agent releases.
