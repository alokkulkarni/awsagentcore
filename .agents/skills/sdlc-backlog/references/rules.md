# Backlog Validation Rules

This reference defines the ten BKL rules enforced by `validate_backlog.py`.

## Severity Model

- **CRITICAL** — hard blocker for production use.
- **HIGH** — significant issue that should be fixed before handoff.
- **MEDIUM** — important quality gap; remediate during refinement.
- **LOW** — advisory improvement expected in a production-quality deliverable.

## Rule Index

| Rule ID | Severity | Section | Summary |
|---------|----------|---------|---------|
| BKL-001 | CRITICAL | Output | backlog/stories-summary.md exists |
| BKL-002 | CRITICAL | Epics | At least one epic defined |
| BKL-003 | HIGH | Stories | At least 3 user stories defined |
| BKL-004 | HIGH | Stories | All stories follow "As a... I want... so that..." format |
| BKL-005 | HIGH | Acceptance Criteria | All stories have acceptance criteria |
| BKL-006 | MEDIUM | Acceptance Criteria | Acceptance criteria in Given/When/Then format |
| BKL-007 | MEDIUM | Sizing | Story points or size estimates present |
| BKL-008 | MEDIUM | Traceability | Stories linked to epics |
| BKL-009 | LOW | Delivery Readiness | Definition of Done defined |
| BKL-010 | LOW | Planning | Sprint/iteration assignment present |

## BKL-001 — backlog/stories-summary.md exists

**Severity:** CRITICAL

### What is checked
backlog/stories-summary.md exists

### Why it matters
This rule protects output quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
`backlog/stories-summary.md` is generated and checked in or attached to the delivery run.

### ❌ Fail example
No summary file exists, so the backlog cannot be reviewed.

## BKL-002 — At least one epic defined

**Severity:** CRITICAL

### What is checked
At least one epic defined

### Why it matters
This rule protects epics quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
The summary contains at least one `### Epic EPIC-001 — ...` block.

### ❌ Fail example
Stories are listed with no epic container or capability grouping.

## BKL-003 — At least 3 user stories defined

**Severity:** HIGH

### What is checked
At least 3 user stories defined

### Why it matters
This rule protects stories quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Three or more `### Story STORY-00N — ...` entries are present.

### ❌ Fail example
Only one or two stories are produced from a non-trivial architecture.

## BKL-004 — All stories follow "As a... I want... so that..." format

**Severity:** HIGH

### What is checked
All stories follow "As a... I want... so that..." format

### Why it matters
This rule protects stories quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
`Story: As a service consumer, I want ... so that ...`

### ❌ Fail example
`Story: Build the API endpoint`

## BKL-005 — All stories have acceptance criteria

**Severity:** HIGH

### What is checked
All stories have acceptance criteria

### Why it matters
This rule protects acceptance criteria quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Each story has an `#### Acceptance Criteria` block.

### ❌ Fail example
One or more stories stop after the description and points.

## BKL-006 — Acceptance criteria in Given/When/Then format

**Severity:** MEDIUM

### What is checked
Acceptance criteria in Given/When/Then format

### Why it matters
This rule protects acceptance criteria quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Criteria include explicit `Given`, `When`, and `Then` lines.

### ❌ Fail example
Criteria are written as vague bullets like `- Works correctly`.

## BKL-007 — Story points or size estimates present

**Severity:** MEDIUM

### What is checked
Story points or size estimates present

### Why it matters
This rule protects sizing quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
`Story Points: 5` or `Size: 5` is present for every story.

### ❌ Fail example
Sizing is missing, making sprint planning difficult.

## BKL-008 — Stories linked to epics

**Severity:** MEDIUM

### What is checked
Stories linked to epics

### Why it matters
This rule protects traceability quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Each story has `Epic: EPIC-001`.

### ❌ Fail example
Stories exist but do not reference a parent epic.

## BKL-009 — Definition of Done defined

**Severity:** LOW

### What is checked
Definition of Done defined

### Why it matters
This rule protects delivery readiness quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
A `## Definition of Done` section captures shared completion expectations.

### ❌ Fail example
No shared completion criteria are defined.

## BKL-010 — Sprint/iteration assignment present

**Severity:** LOW

### What is checked
Sprint/iteration assignment present

### Why it matters
This rule protects planning quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Each story records `Sprint: Sprint 1` or `Iteration: PI-1 Iteration-2`.

### ❌ Fail example
Stories are not assigned to any sprint or iteration.
