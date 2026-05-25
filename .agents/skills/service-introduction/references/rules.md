# Service Introduction Document Validation Rules

This reference defines the 20 SID-NNN rules enforced by `validate_sid.py`. The rules align to ITIL v4 service transition, ISO/IEC 20000-1:2018 service management requirements, and common enterprise service onboarding controls.

## Severity Model

- **CRITICAL** — mandatory governance or operational control missing; the SID is not fit for approval.
- **HIGH** — major readiness gap; fix before formal sign-off or go-live.
- **MEDIUM** — important completeness issue; remediate before audit or CAB where possible.
- **LOW** — advisory enablement issue that should still be addressed for a production-quality SID.

## Rule Index

| Rule ID | Severity | Section | Summary |
|---------|----------|---------|---------|
| SID-001 | CRITICAL | Document Control | Document Control block present (## Document Control heading) |
| SID-002 | HIGH | Document Control | SID ID present and matches SID-[A-Z]{3}-NNN |
| SID-003 | HIGH | Document Control | Version present and matches semver X.Y.Z |
| SID-004 | HIGH | Document Control | Status present and one of Draft, In Review, Approved, Active, Retired |
| SID-005 | CRITICAL | Executive Summary | Executive Summary section present and has content (>50 words) |
| SID-006 | CRITICAL | Service Description | Service Description section present |
| SID-007 | HIGH | Service Description | Service Tier defined (1, 2, or 3) |
| SID-008 | CRITICAL | Technical Architecture | Technical Architecture section present |
| SID-009 | CRITICAL | Service Level Objectives | Service Level Objectives section present |
| SID-010 | HIGH | Service Level Objectives | Availability SLO defined (numeric % value) |
| SID-011 | HIGH | Service Level Objectives | RTO and RPO defined |
| SID-012 | CRITICAL | Security & Compliance | Security & Compliance section present |
| SID-013 | HIGH | Service Dependencies | Service Dependencies section present with a table |
| SID-014 | HIGH | Risk Register | Risk Register section present with at least 4 data rows |
| SID-015 | HIGH | Risk Register | Risk Register has required columns (ID, Risk, Category, Probability, Impact, Mitigation, Owner, Status) |
| SID-016 | HIGH | Approvals | Approvals section present with table containing at least 2 rows |
| SID-017 | MEDIUM | Service Scope | Service Scope section with In-Scope and Out-of-Scope |
| SID-018 | MEDIUM | Operational Model | Operational Model section present |
| SID-019 | MEDIUM | Service Transition Plan | Service Transition Plan section present |
| SID-020 | LOW | Training & Knowledge Transfer | Training & Knowledge Transfer section present |

## SID-001 — Document Control block present (## Document Control heading)

**Severity:** CRITICAL

### What is checked
A dedicated `## Document Control` section must exist.

### Why it matters
ITIL and ISO 20000 require controlled documentation, ownership, and revision traceability.

### ✅ Pass example
```md
## 1. Document Control

| Field | Value |
| --- | --- |
| SID ID | SID-GEN-001 |
```

### ❌ Fail example
```md
# My Service

This document starts with overview prose and has no control section.
```

## SID-002 — SID ID present and matches SID-[A-Z]{3}-NNN

**Severity:** HIGH

### What is checked
The Document Control block must contain an SID ID that matches `SID-[A-Z]{3}-\d{3}`.

### Why it matters
A stable identifier supports audit trails, CAB references, and service catalogue linkage.

### ✅ Pass example
```md
| SID ID | SID-API-001 |
```

### ❌ Fail example
```md
| SID ID | SERVICE-01 |
```

## SID-003 — Version present and matches semver X.Y.Z

**Severity:** HIGH

### What is checked
A semantic version such as `1.0.0` must be present.

### Why it matters
Versioning communicates maturity and supports formal review, approval, and retirement.

### ✅ Pass example
```md
| Version | 1.0.0 |
```

### ❌ Fail example
```md
| Version | Final |
```

## SID-004 — Status present and one of Draft, In Review, Approved, Active, Retired

**Severity:** HIGH

### What is checked
The document status must be one of the five allowed lifecycle states.

### Why it matters
Readers need to know whether the SID is a draft artifact, approved record, or retired reference.

### ✅ Pass example
```md
| Status | In Review |
```

### ❌ Fail example
```md
| Status | Live |
```

## SID-005 — Executive Summary section present and has content (>50 words)

**Severity:** CRITICAL

### What is checked
The Executive Summary section must exist and contain more than fifty words.

### Why it matters
Sponsors and approvers need a concise explanation of service value, audience, and benefits before reviewing technical details.

### ✅ Pass example
```md
## 2. Executive Summary

This service enables ... [two paragraphs totalling more than fifty words]
```

### ❌ Fail example
```md
## Executive Summary

TBD.
```

## SID-006 — Service Description section present

**Severity:** CRITICAL

### What is checked
A canonical Service Description section must exist.

### Why it matters
The service description anchors the document by defining what service is being introduced and for whom.

### ✅ Pass example
```md
## 3. Service Description
```

### ❌ Fail example
```md
No service description section is included.
```

## SID-007 — Service Tier defined (1, 2, or 3)

**Severity:** HIGH

### What is checked
The Service Description section must define a tier of `1`, `2`, or `3`.

### Why it matters
Support depth, resilience expectations, and approval rigor depend on the assigned service tier.

### ✅ Pass example
```md
| Service Tier | 1 |
```

### ❌ Fail example
```md
| Service Tier | Critical |
```

## SID-008 — Technical Architecture section present

**Severity:** CRITICAL

### What is checked
The Technical Architecture section must exist.

### Why it matters
Transition and operations teams need a clear architecture view to understand components, hosting, and integrations.

### ✅ Pass example
```md
## 6. Technical Architecture
```

### ❌ Fail example
```md
The document omits any architecture section.
```

## SID-009 — Service Level Objectives section present

**Severity:** CRITICAL

### What is checked
The Service Level Objectives section must exist.

### Why it matters
An SID without operational targets cannot be assessed for readiness, supportability, or supplier accountability.

### ✅ Pass example
```md
## 9. Service Level Objectives
```

### ❌ Fail example
```md
No SLO section is present.
```

## SID-010 — Availability SLO defined (numeric % value)

**Severity:** HIGH

### What is checked
A numeric availability target such as `99.9%` must be defined.

### Why it matters
Availability targets drive error budgets, support expectations, and business acceptance criteria.

### ✅ Pass example
```md
| Availability Target | 99.9% |
```

### ❌ Fail example
```md
| Availability Target | High availability |
```

## SID-011 — RTO and RPO defined

**Severity:** HIGH

### What is checked
Both RTO and RPO values must be present in the SLO or continuity content.

### Why it matters
Recovery objectives align continuity planning with business tolerance for disruption and data loss.

### ✅ Pass example
```md
| RTO | 4h |
| RPO | 1h |
```

### ❌ Fail example
```md
| RTO | 4h |
```

## SID-012 — Security & Compliance section present

**Severity:** CRITICAL

### What is checked
The Security & Compliance section must exist.

### Why it matters
Security controls, data handling, and regulatory obligations must be documented before production introduction.

### ✅ Pass example
```md
## 11. Security & Compliance
```

### ❌ Fail example
```md
No security or compliance controls are documented.
```

## SID-013 — Service Dependencies section present with a table

**Severity:** HIGH

### What is checked
The Service Dependencies section must include at least one populated dependency table.

### Why it matters
Dependency transparency is essential for supplier management, resilience planning, and impact analysis.

### ✅ Pass example
```md
| Dependency | Version | Owner | Criticality |
```

### ❌ Fail example
```md
Dependencies are mentioned in prose only.
```

## SID-014 — Risk Register section present with at least 4 data rows

**Severity:** HIGH

### What is checked
The Risk Register must include a table with at least four populated rows.

### Why it matters
Formal risk review is a core transition control and demonstrates operational and governance readiness.

### ✅ Pass example
```md
| ID | Risk/Issue | Category | Probability | Impact | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-001 | ... |
| R-002 | ... |
| R-003 | ... |
| R-004 | ... |
```

### ❌ Fail example
```md
The register contains one token row or fewer than four entries.
```

## SID-015 — Risk Register has required columns (ID, Risk, Category, Probability, Impact, Mitigation, Owner, Status)

**Severity:** HIGH

### What is checked
The Risk Register header must normalize to the eight required columns.

### Why it matters
A consistent RAID-style schema enables repeatable review, reporting, and auditing.

### ✅ Pass example
```md
| ID | Risk/Issue | Category | Probability | Impact | Mitigation | Owner | Status |
```

### ❌ Fail example
```md
| ID | Risk | Impact | Owner |
```

## SID-016 — Approvals section present with table containing at least 2 rows

**Severity:** HIGH

### What is checked
The Approvals section must contain a `Role / Name / Signature / Date` table with at least two populated rows.

### Why it matters
Service introduction requires accountable evidence from business, technical, and operational approvers.

### ✅ Pass example
```md
| Role | Name | Signature | Date |
| --- | --- | --- | --- |
| Service Owner | Jane Doe | Pending | 2025-01-01 |
| Operations Manager | John Doe | Pending | 2025-01-01 |
```

### ❌ Fail example
```md
The section is missing or contains only header rows.
```

## SID-017 — Service Scope section with In-Scope and Out-of-Scope

**Severity:** MEDIUM

### What is checked
The Service Scope section must include explicit In-Scope and Out-of-Scope content.

### Why it matters
Clear boundaries reduce transition confusion and prevent unsupported assumptions.

### ✅ Pass example
```md
### In-Scope
- API and background workers

### Out-of-Scope
- Legacy batch jobs
```

### ❌ Fail example
```md
Scope is described informally with no in-scope or out-of-scope split.
```

## SID-018 — Operational Model section present

**Severity:** MEDIUM

### What is checked
The Operational Model section must exist.

### Why it matters
Service introduction is incomplete without support tiers, incident flow, and escalation ownership.

### ✅ Pass example
```md
## 10. Operational Model
```

### ❌ Fail example
```md
The document contains no operating model for support or escalation.
```

## SID-019 — Service Transition Plan section present

**Severity:** MEDIUM

### What is checked
The Service Transition Plan section must exist.

### Why it matters
Transition activities, acceptance criteria, and go-live controls must be documented to move safely into operation.

### ✅ Pass example
```md
## 15. Service Transition Plan
```

### ❌ Fail example
```md
No transition plan or go-live controls are present.
```

## SID-020 — Training & Knowledge Transfer section present

**Severity:** LOW

### What is checked
The Training & Knowledge Transfer section must exist.

### Why it matters
Enablement is lower severity than governance blockers, but still required for a production-quality SID.

### ✅ Pass example
```md
## 16. Training & Knowledge Transfer
```

### ❌ Fail example
```md
There is no section covering training, runbooks, or knowledge transfer.
```
