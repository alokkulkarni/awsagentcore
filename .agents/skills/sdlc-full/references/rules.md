# SDLC Full Pipeline Validation Rules

This reference defines the ten `PPL-NNN` rules enforced by `validate_pipeline.py`. The rules align the full SDLC pipeline to production-quality delivery controls, DevSecOps gatekeeping, and DORA-oriented flow metrics.

## Severity Model

- **CRITICAL** — the pipeline is incomplete or unsafe to treat as production-ready.
- **HIGH** — a major SDLC deliverable or quality gate is missing.
- **MEDIUM** — governance evidence is incomplete and should be remediated before handoff.
- **LOW** — advisory optimisation issue that does not block delivery on its own.

## Rule Index

| Rule ID | Severity | Summary | DORA alignment |
| --- | --- | --- | --- |
| PPL-001 | CRITICAL | Pipeline report file exists | Lead time visibility |
| PPL-002 | CRITICAL | All six phases completed with GREEN status | Change failure rate reduction |
| PPL-003 | CRITICAL | No unresolved CRITICAL security findings in review report | Change failure rate reduction |
| PPL-004 | HIGH | Analysis report exists with requirements | Lead time and deployment predictability |
| PPL-005 | HIGH | Architecture HLD exists | Change quality and deployment predictability |
| PPL-006 | HIGH | Backlog story summary exists | Lead time and flow efficiency |
| PPL-007 | HIGH | At least one source file generated or modified | Deployment frequency evidence |
| PPL-008 | HIGH | Test coverage is at least 80% | Change failure rate reduction |
| PPL-009 | MEDIUM | Review report exists and is PASSED | Operational readiness and MTTR support |
| PPL-010 | LOW | Pipeline duration is under two hours | Lead time for changes |

## PPL-001 — Pipeline report file exists

**Severity:** CRITICAL  
**Check:** A `pipeline-report-YYYYMMDD.md` file must exist in the project root.  
**Why it matters:** Delivery without a durable execution record weakens auditability, traceability, and pipeline observability.

## PPL-002 — All six phases completed with GREEN status

**Severity:** CRITICAL  
**Check:** Analysis, Architecture, Refinement, Development, Test, and Review must all be present in the summary table with status `GREEN`.  
**Why it matters:** A full SDLC pipeline is only production-grade when every gate has passed.

## PPL-003 — No unresolved CRITICAL security findings in review report

**Severity:** CRITICAL  
**Check:** The latest review report must show zero unresolved `CRITICAL` and zero unresolved `HIGH` findings.  
**Why it matters:** Security review is the final merge gate; unresolved severe issues directly increase change failure risk.

## PPL-004 — Analysis report exists with requirements

**Severity:** HIGH  
**Check:** Analysis artefacts must include extracted requirements.  
**Why it matters:** Architecture, backlog generation, and scope control depend on validated requirements.

## PPL-005 — Architecture HLD exists

**Severity:** HIGH  
**Check:** `architecture/hld.md` must exist and be non-empty.  
**Why it matters:** Delivery without an HLD reduces design clarity, component accountability, and downstream implementation quality.

## PPL-006 — Backlog stories summary exists

**Severity:** HIGH  
**Check:** `backlog/stories-summary.md` must exist and be non-empty.  
**Why it matters:** A validated backlog is required to connect design intent to implementable delivery slices.

## PPL-007 — At least one source file generated or modified

**Severity:** HIGH  
**Check:** The pipeline report or repository state must indicate at least one generated or modified source file.  
**Why it matters:** A development phase that produces no implementation output did not advance the feature.

## PPL-008 — Test coverage is at least 80%

**Severity:** HIGH  
**Check:** Coverage must be `>= 80%`.  
**Why it matters:** This is the explicit test gate for the full pipeline and a baseline quality threshold for production readiness.

## PPL-009 — Review report exists and is PASSED

**Severity:** MEDIUM  
**Check:** A review report must exist and clearly indicate a pass outcome.  
**Why it matters:** Review evidence supports supportability, auditability, and safer recovery practices.

## PPL-010 — Pipeline duration is under two hours

**Severity:** LOW  
**Check:** Total pipeline duration should remain below `7200` seconds.  
**Why it matters:** Shorter validated feedback loops improve lead time and keep the full-cycle workflow operationally useful.
