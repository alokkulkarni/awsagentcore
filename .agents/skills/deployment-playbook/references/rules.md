# Deployment Playbook Validation Rules

This reference defines all validation rules enforced by `validate_playbook.py`. The rules align to enterprise deployment governance expectations across ITIL v4 change management, SRE operational readiness, and DORA-oriented release controls.

## Severity Model

- **CRITICAL** — mandatory control missing; playbook is not operationally safe or auditable.
- **HIGH** — major governance or execution gap; fix before approval or execution.
- **MEDIUM** — important completeness gap; fix before final sign-off when possible.
- **LOW** — advisory improvement opportunity.

## Rule Index

| Rule ID | Severity | Section | Summary |
|---------|----------|---------|---------|
| PLAY-001 | CRITICAL | Document Control | Document Control block present |
| PLAY-002 | HIGH | Document Control | Playbook ID follows PLY-XXX-NNN format |
| PLAY-003 | HIGH | Document Control | Version field present and semver format |
| PLAY-004 | HIGH | Document Control | Status value is allowed |
| PLAY-005 | HIGH | Document Control | At least one approver listed |
| PLAY-006 | CRITICAL | Purpose & Scope | Purpose section present |
| PLAY-007 | MEDIUM | Purpose & Scope | In-scope and Out-of-scope defined |
| PLAY-008 | CRITICAL | Deployment Strategy | At least one deployment phase defined |
| PLAY-009 | HIGH | Deployment Strategy | Each phase has rollback trigger defined |
| PLAY-010 | HIGH | Risk Register | Risk Register table present with at least one entry |
| PLAY-011 | HIGH | Risk Register | Risk Register has all eight required columns |
| PLAY-012 | CRITICAL | Rollback Strategy | Rollback Strategy section present |
| PLAY-013 | HIGH | Rollback Strategy | Rollback time objective (RTO) defined |
| PLAY-014 | MEDIUM | Communication Plan | Communication Plan table present |
| PLAY-015 | HIGH | Success Criteria | Success Criteria section present |
| PLAY-016 | HIGH | Post-Deployment Validation | Post-Deployment Validation section present |
| PLAY-017 | MEDIUM | Contacts & Escalation | Contacts & Escalation table present |
| PLAY-018 | HIGH | Approvals | Approvals table present |
| PLAY-019 | MEDIUM | Environment Matrix | Environment Matrix table present |
| PLAY-020 | MEDIUM | Change Management | Change Management section with change type defined |

## PLAY-001 — Document Control block present

**Severity:** CRITICAL

**Section:** Document Control

### What this rule checks
The playbook must contain a dedicated Document Control section with core metadata so operators can identify ownership, revision state, and formal governance status.

### Pass example
A `## 1. Document Control` section contains a metadata table with title, playbook ID, version, status, owner, created date, last reviewed date, and approvers.

### Fail example
The document begins directly with deployment steps and has no control metadata, owner, version, or review information.

### Remediation guidance
Add a Document Control section near the top of the document and populate all required metadata fields before routing for review or approval.

## PLAY-002 — Playbook ID follows PLY-XXX-NNN format

**Severity:** HIGH

**Section:** Document Control

### What this rule checks
Each playbook requires a stable identifier in the format `PLY-XXX-NNN` so it can be referenced in ticketing systems, CAB records, audits, and change calendars.

### Pass example
`Playbook ID | PLY-OPS-001`

### Fail example
`Document ID | DEPLOY-1` or no identifier at all.

### Remediation guidance
Assign a compliant identifier using three uppercase letters for the domain or team and a three-digit sequence number.

## PLAY-003 — Version field present and semver format

**Severity:** HIGH

**Section:** Document Control

### What this rule checks
A version field in semantic version format communicates revision maturity and supports controlled updates during review, approval, and retirement.

### Pass example
`Version | 1.2.0`

### Fail example
`Version | Final` or the version field is omitted.

### Remediation guidance
Add a Version field and use semantic versioning such as `0.1.0`, `1.0.0`, or `2.3.1`.

## PLAY-004 — Status value is allowed

**Severity:** HIGH

**Section:** Document Control

### What this rule checks
The status must be one of `Draft`, `In Review`, `Approved`, `Active`, or `Retired` so readers know whether the playbook is ready for operational use.

### Pass example
`Status | In Review`

### Fail example
`Status | Done` or `Status | Live`.

### Remediation guidance
Replace non-standard values with one of the approved lifecycle states.

## PLAY-005 — At least one approver listed

**Severity:** HIGH

**Section:** Document Control

### What this rule checks
Deployment playbooks require accountable approval. At least one named approver must be captured in Document Control or the Approvals section.

### Pass example
`Approvers | Head of Platform Engineering; Change Manager`

### Fail example
`Approvers | TBD` or no approver names are listed anywhere.

### Remediation guidance
List at least one approver role or named approver and ensure the final Approvals table is ready for signature.

## PLAY-006 — Purpose section present

**Severity:** CRITICAL

**Section:** Purpose & Scope

### What this rule checks
Every playbook must explain why the deployment exists and what business or technical objective it serves.

### Pass example
A `## 2. Purpose & Scope` section states the deployment objective and expected outcome.

### Fail example
The document jumps from metadata directly into operational steps without describing the purpose.

### Remediation guidance
Add a Purpose & Scope section that states the deployment objective, affected service, and intended audience.

## PLAY-007 — In-scope and Out-of-scope defined

**Severity:** MEDIUM

**Section:** Purpose & Scope

### What this rule checks
Clear scope boundaries prevent accidental expansion of the change, reduce coordination failures, and set expectations for stakeholders.

### Pass example
The section includes explicit `In-Scope` and `Out-of-Scope` subsections or bullet lists.

### Fail example
Purpose is described but there is no boundary between included and excluded systems or activities.

### Remediation guidance
Add concise in-scope and out-of-scope statements naming covered services, excluded systems, and unsupported activities.

## PLAY-008 — At least one deployment phase defined

**Severity:** CRITICAL

**Section:** Deployment Strategy

### What this rule checks
A production playbook must break execution into explicit phases so teams can coordinate checkpoints, pauses, and approvals.

### Pass example
The Deployment Strategy section contains one or more phase subsections such as `### Phase 1 — Pre-Deployment Readiness`.

### Fail example
A single unstructured list of commands is provided with no phases, ownership, or checkpoints.

### Remediation guidance
Define at least one named deployment phase with an objective, steps, dependencies, duration estimate, and rollback trigger.

## PLAY-009 — Each phase has rollback trigger defined

**Severity:** HIGH

**Section:** Deployment Strategy

### What this rule checks
Rollback conditions must be explicit for every deployment phase so teams know when to stop, reverse, or escalate.

### Pass example
Each phase subsection contains a `Rollback Trigger` line, for example `Rollback Trigger: Error rate > 2% for 5 minutes`.

### Fail example
Phases describe steps and timing but never state when rollback should be initiated.

### Remediation guidance
Add a rollback trigger statement to every phase using measurable technical or business conditions.

## PLAY-010 — Risk Register table present with at least one entry

**Severity:** HIGH

**Section:** Risk Register

### What this rule checks
A RAID-style risk register is mandatory so deployment risks, owners, and mitigations are reviewed before implementation.

### Pass example
The Risk Register section contains a markdown table with one or more populated data rows.

### Fail example
The section is missing or contains only prose with no structured risks.

### Remediation guidance
Add a risk register table and capture at least one meaningful risk or issue with an owner and mitigation.

## PLAY-011 — Risk Register has all eight required columns

**Severity:** HIGH

**Section:** Risk Register

### What this rule checks
The risk register must include the standard eight RAID columns so probability, impact, ownership, and status are auditable.

### Pass example
`| ID | Risk/Issue | Category | Probability | Impact | Mitigation | Owner | Status |`

### Fail example
A simplified table omits `Probability`, `Owner`, or `Status`.

### Remediation guidance
Restore the full eight-column structure and populate every row consistently.

## PLAY-012 — Rollback Strategy section present

**Severity:** CRITICAL

**Section:** Rollback Strategy

### What this rule checks
Production changes require a dedicated rollback strategy that describes how to recover safely if the deployment fails or degrades service.

### Pass example
A `## 9. Rollback Strategy` section outlines conditions, owners, and step-by-step rollback actions.

### Fail example
The playbook says `rollback if needed` without any formal rollback section.

### Remediation guidance
Create a Rollback Strategy section and document trigger conditions, sequence, owners, and recovery checkpoints.

## PLAY-013 — Rollback time objective (RTO) defined

**Severity:** HIGH

**Section:** Rollback Strategy

### What this rule checks
Rollback planning must include an RTO or rollback time target so leadership can evaluate exposure and escalation urgency.

### Pass example
`Rollback Time Objective (RTO): 30 minutes to restore the last known good version.`

### Fail example
Rollback steps are listed but there is no target recovery time.

### Remediation guidance
Add a rollback time objective or explicit recovery target in minutes or hours.

## PLAY-014 — Communication Plan table present

**Severity:** MEDIUM

**Section:** Communication Plan

### What this rule checks
Stakeholder communication must be planned with audience, channel, owner, and timing so updates are predictable during the change.

### Pass example
A table lists deployment phases, target audiences, channels, owners, and timings.

### Fail example
The playbook says `notify stakeholders` but does not specify who, how, or when.

### Remediation guidance
Add a Communication Plan table covering pre-change, in-flight, rollback, and completion communications.

## PLAY-015 — Success Criteria section present

**Severity:** HIGH

**Section:** Success Criteria

### What this rule checks
A deployment is not complete until measurable success criteria are defined for functionality, performance, and reliability.

### Pass example
The section defines target error rates, latency thresholds, smoke test expectations, or SLO outcomes.

### Fail example
The document states `deployment successful if no issues reported`.

### Remediation guidance
Add specific functional, performance, and reliability checks with thresholds or acceptance targets.

## PLAY-016 — Post-Deployment Validation section present

**Severity:** HIGH

**Section:** Post-Deployment Validation

### What this rule checks
The playbook must describe how the team verifies the service after rollout and before the change is formally closed.

### Pass example
A section lists smoke tests, monitoring checks, business validation, and sign-off steps.

### Fail example
The playbook ends after the final deployment command and has no validation activities.

### Remediation guidance
Add a Post-Deployment Validation section with smoke tests, observability checks, and business sign-off actions.

## PLAY-017 — Contacts & Escalation table present

**Severity:** MEDIUM

**Section:** Contacts & Escalation

### What this rule checks
Operational contacts must be documented so the incident commander or release manager can escalate quickly during execution.

### Pass example
A table lists engineering, product, service desk, incident commander, and executive escalation contacts.

### Fail example
Only team aliases are mentioned casually in prose with no escalation levels.

### Remediation guidance
Add a structured Contacts & Escalation table with roles, contact methods, and escalation levels.

## PLAY-018 — Approvals table present

**Severity:** HIGH

**Section:** Approvals

### What this rule checks
Formal approval evidence is required for auditability and change governance, especially for normal and emergency changes.

### Pass example
An Approvals section contains a markdown table with role, name, signature, and date columns.

### Fail example
The playbook mentions `approved by CAB` but provides no approval table.

### Remediation guidance
Add the Approvals section and include one row per approving role with signature and date fields.

## PLAY-019 — Environment Matrix table present

**Severity:** MEDIUM

**Section:** Environment Matrix

### What this rule checks
A deployment playbook must show the environments, regions, tiers, purposes, and deployment order affected by the rollout.

### Pass example
`| Environment | Region | Tier | Purpose | Deployment Order |` with populated rows.

### Fail example
The playbook refers to `all environments` but includes no matrix.

### Remediation guidance
Add an Environment Matrix table describing each target environment and its rollout sequence.

## PLAY-020 — Change Management section with change type defined

**Severity:** MEDIUM

**Section:** Change Management

### What this rule checks
The playbook must identify the change type and governance path so change scheduling, CAB involvement, and freeze controls are clear.

### Pass example
`Change Type: Normal` inside the Change Management section, with window and approval details.

### Fail example
A Change Management section exists but never specifies whether the change is Standard, Normal, or Emergency.

### Remediation guidance
Add a clear change type, approved window, CAB or ECAB path, and any relevant freeze period references.
