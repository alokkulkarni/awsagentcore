# Deployment Runbook Rule Reference

This reference expands every validation rule used by `validate_runbook.py` and the deployment-runbook skill.

## Quick Index

| Rule ID | Severity | Section | Requirement |
|---------|----------|---------|-------------|
| RNB-001 | CRITICAL | Document Control | Document Control block present |
| RNB-002 | HIGH | Document Control | Runbook ID follows `RNB-XXX-NNN` format |
| RNB-003 | HIGH | Document Control | Version field present |
| RNB-004 | HIGH | Document Control | Last-tested date present |
| RNB-005 | CRITICAL | Overview | Overview section present |
| RNB-006 | MEDIUM | Overview | SLA/SLO targets defined |
| RNB-007 | HIGH | Overview | On-call contact present |
| RNB-008 | CRITICAL | Prerequisites | Prerequisites section present |
| RNB-009 | MEDIUM | Prerequisites | At least one env var checklist item in Prerequisites |
| RNB-010 | CRITICAL | Procedure Steps | At least 3 numbered procedure steps |
| RNB-011 | CRITICAL | Procedure Steps | Each step has a code block (command) |
| RNB-012 | CRITICAL | Procedure Steps | Each step has a Verify block |
| RNB-013 | HIGH | Procedure Steps | Each step has a failure/escalation block |
| RNB-014 | HIGH | Troubleshooting Table | Troubleshooting table present |
| RNB-015 | MEDIUM | Troubleshooting Table | Troubleshooting table has at least 3 rows |
| RNB-016 | HIGH | Troubleshooting Table | Troubleshooting table has all 5 columns |
| RNB-017 | CRITICAL | Rollback Procedure | Rollback Procedure section present |
| RNB-018 | HIGH | Rollback Procedure | Rollback procedure has numbered steps |
| RNB-019 | MEDIUM | Quick Reference | Quick Reference section present |
| RNB-020 | LOW | Change Log | Change Log present |

## RNB-001 — Document Control block present [CRITICAL]

**Requirement:** Every runbook starts with a Document Control section that identifies the document and its lifecycle metadata.

**Pass example**
```md
## 1. Document Control
| Field | Value |
|---|---|
| Runbook ID | RNB-WEB-001 |
```

**Fail example**
```md
## 2. Overview
Deployment notes start immediately with no document metadata.
```

**Remediation:** Add a Document Control section before Overview and include title, Runbook ID, version, status, owner, created, last reviewed, and last tested fields.

## RNB-002 — Runbook ID follows `RNB-XXX-NNN` format [HIGH]

**Requirement:** The runbook identifier must match `RNB-XXX-NNN` so documents can be tracked consistently.

**Pass example**
```md
| Runbook ID | RNB-API-014 |
```

**Fail example**
```md
| Runbook ID | deployment-runbook-prod |
```

**Remediation:** Rename the identifier to the required pattern, for example `RNB-WEB-001` or `RNB-ECS-117`.

## RNB-003 — Version field present [HIGH]

**Requirement:** Runbooks must expose a version so responders know which revision they are using.

**Pass example**
```md
| Version | 1.7 |
```

**Fail example**
```md
| Status | Approved |
<!-- no version row -->
```

**Remediation:** Add a Version row in Document Control and increment it every time the procedure changes.

## RNB-004 — Last-tested date present [HIGH]

**Requirement:** Runbooks must record when the procedure was last executed or rehearsed.

**Pass example**
```md
| Last Tested | 2025-05-01 |
```

**Fail example**
```md
| Last Reviewed | 2025-05-01 |
<!-- Last Tested missing -->
```

**Remediation:** Add a Last Tested row and update it whenever the deployment or rollback path is rehearsed.

## RNB-005 — Overview section present [CRITICAL]

**Requirement:** A responder must be able to see the component, purpose, and business context before executing commands.

**Pass example**
```md
## 2. Overview
| Item | Details |
| Component | Payments API |
```

**Fail example**
```md
## 3. Prerequisites
The document jumps straight into commands.
```

**Remediation:** Add an Overview section that describes the component, purpose, dependencies, service levels, and contacts.

## RNB-006 — SLA/SLO targets defined [MEDIUM]

**Requirement:** The Overview must include availability, latency, or error-budget targets so the operator knows the deployment guardrails.

**Pass example**
```md
| SLA/SLO Targets | 99.9% availability, p95 latency < 400 ms, error rate < 1% |
```

**Fail example**
```md
| Purpose | Deploy the service safely |
<!-- no service level objective -->
```

**Remediation:** Document the SLA or SLO targets that must remain true during and after the procedure.

## RNB-007 — On-call contact present [HIGH]

**Requirement:** The runbook must tell the operator who owns the service and where to escalate.

**Pass example**
```md
| On-call Contact | PagerDuty: Web Platform Primary; Slack: #prod-oncall |
```

**Fail example**
```md
| Critical Dependencies | RDS, ECS, Route 53 |
<!-- no contact -->
```

**Remediation:** Add the owning team, on-call rotation, and escalation channel in the Overview.

## RNB-008 — Prerequisites section present [CRITICAL]

**Requirement:** Operators need access checks, tools, permissions, and pre-flight conditions before executing changes.

**Pass example**
```md
## 3. Prerequisites
### Access checklist
- [ ] Production AWS role assumed
```

**Fail example**
```md
## 4. Procedure Steps
### 1. Deploy release
```

**Remediation:** Add a Prerequisites section with access, tools, permissions, and environment checks.

## RNB-009 — At least one env var checklist item in Prerequisites [MEDIUM]

**Requirement:** The Prerequisites section must document concrete variable names so commands are repeatable.

**Pass example**
```md
| AWS_REGION | Deployment region | us-east-1 |
```

**Fail example**
```md
Variables are omitted and the operator must guess values.
```

**Remediation:** Add an environment-variable checklist table with exact variable names, purposes, and example values.

## RNB-010 — At least 3 numbered procedure steps [CRITICAL]

**Requirement:** A deployment runbook needs enough sequential detail to be executable and auditable.

**Pass example**
```md
### 1. Verify context
### 2. Run validation
### 3. Execute deployment
```

**Fail example**
```md
### Deploy service
A single unnumbered paragraph describes the whole process.
```

**Remediation:** Break the procedure into at least three numbered steps with explicit execution order.

## RNB-011 — Each step has a code block (command) [CRITICAL]

**Requirement:** Every numbered step must contain an exact command block that can be copied and pasted.

**Pass example**
```md
### 4. Build image
~~~bash
docker build -t app:release .
~~~
```

**Fail example**
```md
### 4. Build image
Run the normal build script and continue when it works.
```

**Remediation:** Replace narrative instructions with fenced code blocks that contain the exact commands.

## RNB-012 — Each step has a Verify block [CRITICAL]

**Requirement:** Each step must define what success looks like so the operator can stop early when outcomes drift.

**Pass example**
```md
✓ **Verify**
- Exit code is 0
- Stack status is UPDATE_COMPLETE
```

**Fail example**
```md
### 5. Execute deployment
~~~bash
make deploy
~~~
<!-- Verify missing -->
```

**Remediation:** Add a ✓ Verify block after every step with expected output, metrics, or exit codes.

## RNB-013 — Each step has a failure/escalation block [HIGH]

**Requirement:** Every step needs a defined failure path so responders do not improvise under pressure.

**Pass example**
```md
⚠️ **If this fails**
- Stop the change
- Escalate to the platform owner
```

**Fail example**
```md
The step ends after the verify bullets with no failure guidance.
```

**Remediation:** Add a ⚠️ **If this fails** block after every step and specify rollback or escalation actions.

## RNB-014 — Troubleshooting table present [HIGH]

**Requirement:** A reusable runbook needs a symptom-driven troubleshooting table for the most likely failure modes.

**Pass example**
```md
## 5. Troubleshooting Table
| Symptom | Probable Cause | Diagnostic Command | Resolution | Escalate If |
```

**Fail example**
```md
The document ends after the main procedure.
```

**Remediation:** Add a Troubleshooting Table section with concise entries for common deployment failures.

## RNB-015 — Troubleshooting table has at least 3 rows [MEDIUM]

**Requirement:** The table should cover multiple common failure modes instead of a single example.

**Pass example**
```md
Rows cover image pull failures, failed health checks, and permission errors.
```

**Fail example**
```md
Only one troubleshooting row is documented.
```

**Remediation:** Expand the troubleshooting table until it covers at least three high-frequency failure scenarios.

## RNB-016 — Troubleshooting table has all 5 columns [HIGH]

**Requirement:** The table must include symptom, cause, diagnostic command, resolution, and escalation guidance.

**Pass example**
```md
| Symptom | Probable Cause | Diagnostic Command | Resolution | Escalate If |
```

**Fail example**
```md
| Symptom | Fix |
| Service unhealthy | Restart it |
```

**Remediation:** Use the full five-column table so the operator has diagnosis, resolution, and escalation paths.

## RNB-017 — Rollback Procedure section present [CRITICAL]

**Requirement:** Every deployment runbook needs an explicit rollback path, not just forward-only instructions.

**Pass example**
```md
## 6. Rollback Procedure
### 1. Select rollback target
```

**Fail example**
```md
If anything goes wrong, ask the primary engineer for help.
```

**Remediation:** Add a Rollback Procedure section with executable steps, verification, and escalation guidance.

## RNB-018 — Rollback procedure has numbered steps [HIGH]

**Requirement:** Rollback must be as explicit and sequential as the primary deployment path.

**Pass example**
```md
### 1. Select version
### 2. Restore service
### 3. Verify recovery
```

**Fail example**
```md
Rollback: redeploy the old version if needed.
```

**Remediation:** Break rollback into numbered steps with commands, verify blocks, and failure actions.

## RNB-019 — Quick Reference section present [MEDIUM]

**Requirement:** Operators need a condensed command summary for time-critical situations.

**Pass example**
```md
## 7. Quick Reference
~~~bash
aws ecs wait services-stable ...
~~~
```

**Fail example**
```md
No cheat sheet or summary commands are included.
```

**Remediation:** Add a Quick Reference section with the primary deploy, verify, and rollback commands.

## RNB-020 — Change Log present [LOW]

**Requirement:** A runbook should retain a revision history so changes are auditable.

**Pass example**
```md
## 8. Change Log
| Version | Date | Author | Change Summary |
```

**Fail example**
```md
The runbook has no revision history.
```

**Remediation:** Add a Change Log table and update it whenever the procedure changes.
