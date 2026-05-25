# Brainstorming Agent Operational Runbook

| Field | Value |
|---|---|
| **Document ID** | RNB-BRAIN-001 |
| **Companion Playbook** | PLY-BRAIN-001 |
| **Version** | 1.0 |
| **Status** | Active |
| **Owner** | Platform Engineering |
| **Date** | 2026-05-25 |
| **Classification** | Internal |

> Use this runbook for operator execution. The currently validated deployment path in the repository is local Docker Compose.

---

## Table of Contents

1. [Pre-deployment Checklist](#1-pre-deployment-checklist)
2. [Local Docker Deployment](#2-local-docker-deployment)
3. [Verify Health](#3-verify-health)
4. [Test Brainstorming Session](#4-test-brainstorming-session)
5. [Test Memory](#5-test-memory)
6. [Rebuild After Code Change](#6-rebuild-after-code-change)
7. [Stop Local Environment](#7-stop-local-environment)
8. [Cloud Deployment](#8-cloud-deployment)
9. [Cloud Teardown](#9-cloud-teardown)
10. [SQLite Backup](#10-sqlite-backup)
11. [View Logs](#11-view-logs)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Pre-deployment Checklist

Complete each item before starting the service:

- [ ] Docker Desktop / Docker Engine is running
- [ ] AWS credentials are available to Docker and/or mounted from `~/.aws`
- [ ] `BEDROCK_MODEL_ID` is set to `eu.anthropic.claude-sonnet-4-6` unless an approved override exists
- [ ] `AWS_DEFAULT_REGION` and `AWS_REGION` are set to the intended Bedrock region
- [ ] Bedrock model access is enabled for the target account/region

Recommended checks:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/brainstorming-agent

docker --version
python3 --version
node --version
aws sts get-caller-identity
aws configure get region
```

---

## 2. Local Docker Deployment

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/brainstorming-agent

cp docker/.env.example docker/.env
```

Edit `docker/.env` and set at minimum:

```env
AWS_ACCESS_KEY_ID=<your-key>
AWS_SECRET_ACCESS_KEY=<your-secret>
AWS_SESSION_TOKEN=<optional>
AWS_REGION=eu-west-2
AWS_DEFAULT_REGION=eu-west-2
BEDROCK_MODEL_ID=eu.anthropic.claude-sonnet-4-6
```

Start the stack:

```bash
docker compose -f docker/docker-compose.yml up --build
```

Expected access points:

- Frontend: `http://localhost:3000`
- API / health: `http://localhost:8000`

Notes:
- The backend listens on container port `8200` and is published to host port `8000`.
- The frontend container serves nginx on host port `3000` and proxies `/api/` and `/ws/` to the backend.

---

## 3. Verify Health

Backend health:

```bash
curl -s http://localhost:8000/health
```

Expected result: JSON containing `"status": "ok"` plus model and database status.

Frontend reachability:

```bash
curl -I http://localhost:3000
```

Expected result: HTTP `200 OK`.

---

## 4. Test Brainstorming Session

### 4.1 Create a Session

The current implementation exposes `POST /sessions` rather than `POST /sessions/new`.

```bash
SESSION_ID=$(curl -s -X POST http://localhost:8000/sessions \
  -H 'Content-Type: application/json' \
  -d '{"title":"Runbook Smoke Test","topics":["ops","brainstorming"]}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

echo "$SESSION_ID"
```

### 4.2 Verify Session Creation

```bash
curl -s http://localhost:8000/sessions | python3 -m json.tool
```

Confirm the new session appears in the list.

### 4.3 Test Live Chat Streaming

The current service uses WebSocket streaming at `/ws/{session_id}` rather than `POST /sessions/{id}/chat`.

Operationally, use the browser UI for the smoke test:

1. Open `http://localhost:3000`
2. Select the newly created session
3. Send a prompt such as: `Give me three strategic risks of launching an AI copilot in financial services.`
4. Confirm the UI shows:
   - WebSocket status `Live`
   - token-by-token streaming
   - final assistant response
   - audit events updating in the Audit tab

If you use a separate WebSocket client, connect to either:
- `ws://localhost:3000/ws/<session-id>` via frontend proxy, or
- `ws://localhost:8000/ws/<session-id>` direct to backend

---

## 5. Test Memory

The current implementation does **not** expose a standalone `POST /memories/save` endpoint. Memory saves occur through agent tool calls during a brainstorming session.

### 5.1 Trigger a Memory Save

From the browser UI, send a prompt that encourages persistence, for example:

> Summarise the strongest go-to-market risk and save it as a memory.

### 5.2 Search Saved Memories

```bash
curl -s "http://localhost:8000/memories/search?q=risk" | python3 -m json.tool
```

### 5.3 Check Session Memories

```bash
curl -s "http://localhost:8000/sessions/$SESSION_ID/memories" | python3 -m json.tool
```

Success criteria:
- at least one memory is returned
- memory includes title/content/topics
- linked count is present even if zero

---

## 6. Rebuild After Code Change

Rebuild the stack after backend or frontend changes:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/brainstorming-agent

docker compose -f docker/docker-compose.yml up --build
```

If the prior stack is still running, interrupt it first or run the command in the same shell so Compose recreates changed services.

---

## 7. Stop Local Environment

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/brainstorming-agent

docker compose -f docker/docker-compose.yml down
```

This stops the containers but preserves the named Docker volume unless it is explicitly removed.

---

## 8. Cloud Deployment

The requested `./deploy.sh deploy` workflow is not present in the current `brainstorming-agent/` tree. As of this runbook version, no component-local cloud deployment script was found.

If a future `deploy.sh` is introduced, the intended operator entrypoint is:

```bash
./deploy.sh deploy
```

Before using it in production, document:
- resources created
- region(s) used
- public/private endpoints
- state files or parameters written
- rollback and teardown commands

Until then, treat Docker Compose as the only validated deployment path.

---

## 9. Cloud Teardown

No validated `./deploy.sh teardown` script exists in the current component tree.

If cloud automation is later added, the teardown entrypoint should be:

```bash
./deploy.sh teardown
```

Do not run teardown in shared environments until the script is reviewed and its deletion scope is understood.

---

## 10. SQLite Backup

Create backups from inside the running backend container and save them in a repository-local backup folder.

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/brainstorming-agent
mkdir -p backups
```

### 10.1 Preferred: `sqlite3` CLI Dump (if available in container)

```bash
docker exec brainstorm-agent sh -lc 'sqlite3 /app/data/brainstorm.db ".dump"' \
  > backups/brainstorm-$(date +%Y%m%d%H%M%S).sql
```

### 10.2 Fallback: Python `sqlite3` Dump

Use this if the `sqlite3` binary is unavailable:

```bash
docker exec brainstorm-agent python - <<'PY' \
  > backups/brainstorm-$(date +%Y%m%d%H%M%S).sql
import sqlite3
conn = sqlite3.connect('/app/data/brainstorm.db')
for line in conn.iterdump():
    print(line)
conn.close()
PY
```

Restore should only be performed during a maintenance window after taking a fresh copy of the current DB file.

---

## 11. View Logs

Backend logs:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/brainstorming-agent
docker compose -f docker/docker-compose.yml logs -f brainstorm-agent
```

Frontend logs:

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore/brainstorming-agent
docker compose -f docker/docker-compose.yml logs -f brainstorm-frontend
```

Focus on:
- Bedrock authentication or throttling errors
- FastAPI startup failures
- WebSocket disconnects
- nginx proxy errors
- SQLite write or lock errors

---

## 12. Troubleshooting

| Symptom | Likely Cause | Action |
|---|---|---|
| Bedrock returns 403 | Invalid credentials, wrong profile, or model access missing | Re-check `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, mounted `~/.aws`, account access to the model, and region alignment |
| Health endpoint fails | Backend did not start or DB init failed | Review `brainstorm-agent` logs and confirm `DB_PATH` is writable |
| WebSocket not connecting | Proxy issue, wrong origin, or backend unavailable | Confirm frontend is on `3000`, backend on `8000`, nginx `/ws/` proxy is active, and browser devtools show a successful WebSocket upgrade |
| Voice not working | Browser support or permissions issue | Use Chrome or Edge, allow microphone access, and remember production voice features generally require HTTPS |
| Memory search empty | Agent did not save memory yet | Trigger a save-worthy prompt, then re-run `/memories/search` and `/sessions/{id}/memories` |
| SQLite locked error | Concurrent writes or long-running DB handle | Retry once, inspect audit errors, and consider reducing concurrent sessions or tuning the SQLite access model |
| Frontend loads but API calls fail | nginx proxy or backend routing issue | Test `curl http://localhost:8000/health` directly, then validate `/api/` proxy behaviour from the frontend |

For unresolved issues, escalate per the companion playbook.
