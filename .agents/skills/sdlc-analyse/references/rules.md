# SDLC Analysis Validation Rules

This reference defines the ten `ANL-NNN` validation rules enforced by `validate_analysis.py`. The rules align to BABOK v3 analysis discipline, ISO/IEC 29148 requirements quality, IEEE 830 structure expectations, and OWASP dependency review practices.

## Severity Model

- **CRITICAL** — blocking analysis control missing; the report is not usable as a phase gate.
- **HIGH** — major completeness or security gap; fix before architecture or backlog generation.
- **MEDIUM** — important quality issue; remediate before formal review where practical.
- **LOW** — advisory improvement; address for production-quality analysis artefacts.

## Rule Index

| Rule ID | Severity | Section | Summary |
|---------|----------|---------|---------|
| ANL-001 | CRITICAL | Report Integrity | Report file exists and is non-empty |
| ANL-002 | HIGH | Requirements Extracted | Requirements section present with at least 3 items |
| ANL-003 | HIGH | Dependency Analysis | Dependency list present |
| ANL-004 | HIGH | Dependency Analysis | No unresolved HIGH/CRITICAL CVEs without mitigation note |
| ANL-005 | MEDIUM | Documentation Assessment | Documentation coverage assessment present |
| ANL-006 | MEDIUM | Code Quality Metrics | Test coverage and linting score present |
| ANL-007 | MEDIUM | Project Overview | Technology stack identified |
| ANL-008 | LOW | Project Overview | Architecture diagram reference or description present |
| ANL-009 | LOW | Risk Summary | Risk summary present |
| ANL-010 | LOW | Recommended Next Steps | Recommended next steps present |

## ANL-001 — Report file exists and is non-empty

**Severity:** CRITICAL

### What this rule checks
The referenced analysis artefact must exist on disk and contain usable content.

### ✅ Pass example
```text
analysis/source-code-report.json exists and contains structured JSON.
```

### ❌ Fail example
```text
analysis/analysis-report.md is missing or zero bytes.
```

## ANL-002 — Requirements section present with at least 3 items

**Severity:** HIGH

### What this rule checks
The report must identify at least three concrete requirements, needs, or delivery expectations.

### ✅ Pass example
```md
## Requirements Extracted
1. The service must ...
2. The repository should ...
3. The platform requires ...
```

### ❌ Fail example
```md
## Requirements Extracted
- TBD
```

## ANL-003 — Dependency list present

**Severity:** HIGH

### What this rule checks
A dependency inventory must be present in JSON or Markdown table form.

### ✅ Pass example
```md
## Dependency Analysis
| Name | Version | License | CVE Status |
| --- | --- | --- | --- |
| requests | 2.31.0 | Apache-2.0 | None detected |
```

### ❌ Fail example
```md
Dependencies were reviewed manually.
```

## ANL-004 — No unresolved HIGH/CRITICAL CVEs without mitigation note

**Severity:** HIGH

### What this rule checks
Any HIGH or CRITICAL vulnerability finding must include a mitigation note, compensating control, or remediation plan.

### ✅ Pass example
```md
| lodash | 4.17.19 | MIT | HIGH - CVE-2021-23337 | Upgrade scheduled in sprint 12; WAF rule enabled |
```

### ❌ Fail example
```md
| lodash | 4.17.19 | MIT | HIGH - CVE-2021-23337 | - |
```

## ANL-005 — Documentation coverage assessment present

**Severity:** MEDIUM

### What this rule checks
The analysis must evaluate documentation coverage and identify gaps.

### ✅ Pass example
```md
## Documentation Assessment
Documentation coverage is partial. Present: README.md, docs/. Missing: CONTRIBUTING.md.
```

### ❌ Fail example
```md
## Documentation Assessment
Documentation exists.
```

## ANL-006 — Code quality metrics present (test coverage %, linting score)

**Severity:** MEDIUM

### What this rule checks
The report must show test coverage evidence and linting status or score.

### ✅ Pass example
```md
| Test coverage | 81.2% |
| Linting score | Configured - report not generated |
```

### ❌ Fail example
```md
Code quality looks fine.
```

## ANL-007 — Technology stack identified

**Severity:** MEDIUM

### What this rule checks
The project overview must identify key technologies, languages, or runtime platforms.

### ✅ Pass example
```md
Technology stack: Python, FastAPI, PostgreSQL, Docker.
```

### ❌ Fail example
```md
Technology stack: unknown.
```

## ANL-008 — Architecture diagram reference or description present

**Severity:** LOW

### What this rule checks
The report should reference an architecture asset or document an inferred architecture view.

### ✅ Pass example
```md
Architecture reference: docs/diagrams/system-architecture.png
```

### ❌ Fail example
```md
No architecture information captured.
```

## ANL-009 — Risk summary present

**Severity:** LOW

### What this rule checks
The report should contain a structured risk summary for handoff into later phases.

### ✅ Pass example
```md
## Risk Summary
| Severity | Risk | Impact | Mitigation |
| --- | --- | --- | --- |
| HIGH | No tests detected | Release risk | Add smoke tests |
```

### ❌ Fail example
```md
No risks.
```

## ANL-010 — Recommended next steps present

**Severity:** LOW

### What this rule checks
The report must conclude with actionable next steps.

### ✅ Pass example
```md
## Recommended Next Steps
- Confirm requirements with stakeholders.
- Fix dependency findings.
- Proceed to architecture generation.
```

### ❌ Fail example
```md
## Recommended Next Steps
TBD
```
