# SDLC Review Validation Rules

This reference defines the ten `REV-NNN` controls enforced by `validate_review.py`. The rules align to secure code review practice, OWASP, CWE, dependency hygiene, and practical merge-gate governance.

## Severity Model

- **CRITICAL** — merge-blocking governance or exploitability gap
- **HIGH** — serious security or dependency risk; block merge until fixed
- **MEDIUM** — requires a ticket, note, or remediation plan
- **LOW** — advisory hygiene or traceability improvement

## Rule Index

| Rule ID | Severity | Summary | Primary Reference |
| --- | --- | --- | --- |
| REV-001 | CRITICAL | Review report file exists and is non-empty | NIST SP 800-53 AU-3 / AU-12 |
| REV-002 | CRITICAL | No CRITICAL severity findings without resolution | OWASP ASVS v4.0, NIST RA-5 |
| REV-003 | CRITICAL | No HIGH severity security findings without resolution | OWASP Top 10 2021, ASVS v4.0 |
| REV-004 | HIGH | No hardcoded secrets or credentials detected | CWE-798, PCI-DSS v4.0 Req. 6 |
| REV-005 | HIGH | No known CVEs with CVSS ≥ 7.0 in dependencies | CWE-1104, NIST SI-2 |
| REV-006 | HIGH | Test coverage ≥ 80% (if coverage data available) | Google Testing guidance |
| REV-007 | MEDIUM | No MEDIUM severity findings without a ticket/note | ISO/IEC 27001 change evidence |
| REV-008 | MEDIUM | Code follows project style guide (linting clean) | Google secure coding guidelines |
| REV-009 | LOW | Documentation updated for changed public APIs | OWASP ASVS V14 / API change transparency |
| REV-010 | LOW | CHANGELOG or commit message references a ticket | DORA traceability / auditability |

## REV-001 — Review report file exists and is non-empty

**Severity:** CRITICAL  
**Why it matters:** A review without an artefact is not auditable. NIST SP 800-53 audit controls require retained evidence for change approval.

## REV-002 — No CRITICAL severity findings without resolution

**Severity:** CRITICAL  
**Why it matters:** Unresolved critical weaknesses indicate unacceptable exploitability or governance exposure. This rule aligns to OWASP ASVS verification and NIST RA-5 vulnerability remediation practice.

## REV-003 — No HIGH severity security findings without resolution

**Severity:** CRITICAL  
**Why it matters:** High-risk SAST, secret, and dependency findings materially increase production risk and must not be deferred into merge by default.

## REV-004 — No hardcoded secrets or credentials detected

**Severity:** HIGH  
**Security mapping:** **CWE-798** (Use of Hard-coded Credentials), OWASP Top 10 A02:2021, PCI-DSS v4.0 secure coding requirements.  
**Why it matters:** Hardcoded credentials create direct compromise paths and usually violate secret-management policy.

## REV-005 — No known CVEs with CVSS ≥ 7.0 in dependencies

**Severity:** HIGH  
**Security mapping:** **CWE-1104** (Use of Unmaintained Third Party Components), OWASP A06:2021, NIST SI-2.  
**Why it matters:** High-CVSS package issues are patch-management blockers and must be upgraded or exceptioned explicitly.

## REV-006 — Test coverage ≥ 80% (if coverage data available)

**Severity:** HIGH  
**Why it matters:** Review without meaningful test evidence increases regression risk and weakens confidence in the changed control path.

## REV-007 — No MEDIUM severity findings without a ticket/note

**Severity:** MEDIUM  
**Why it matters:** Medium findings may be deferred, but only with traceable ownership and follow-up evidence.

## REV-008 — Code follows project style guide (linting clean)

**Severity:** MEDIUM  
**Why it matters:** Lint drift often correlates with maintainability and security hygiene regressions, especially in shared codebases.

## REV-009 — Documentation updated for changed public APIs

**Severity:** LOW  
**Security mapping:** OWASP API Security and ASVS documentation expectations.  
**Why it matters:** Public API changes without documentation cause integration defects and operational confusion.

## REV-010 — CHANGELOG or commit message references a ticket

**Severity:** LOW  
**Why it matters:** Ticket-linked commits improve traceability, auditability, and DORA-style change governance.
