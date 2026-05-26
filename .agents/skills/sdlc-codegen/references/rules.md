# Code Generation Validation Rules

This reference defines the ten CDG rules enforced by `validate_codegen.py`.

## Severity Model

- **CRITICAL** — hard blocker for production use.
- **HIGH** — significant issue that should be fixed before handoff.
- **MEDIUM** — important quality gap; remediate during refinement.
- **LOW** — advisory improvement expected in a production-quality deliverable.

## Rule Index

| Rule ID | Severity | Section | Summary |
|---------|----------|---------|---------|
| CDG-001 | CRITICAL | Output | Generated files exist (at least one new file created) |
| CDG-002 | HIGH | Quality Gates | Generated code compiles/parses (language-appropriate check) |
| CDG-003 | HIGH | Security | No hardcoded credentials or secrets in generated code |
| CDG-004 | HIGH | Reliability | Error handling present in generated code |
| CDG-005 | MEDIUM | Conventions | Generated code follows project naming conventions |
| CDG-006 | MEDIUM | Testing | Tests generated alongside source files |
| CDG-007 | MEDIUM | Maintainability | Generated code has at least minimal comments/docstrings |
| CDG-008 | LOW | Docs | README or CHANGELOG updated |
| CDG-009 | LOW | Hygiene | No TODO/FIXME left unresolved in critical paths |
| CDG-010 | LOW | Dependencies | Dependency manifest updated if new deps added |

## CDG-001 — Generated files exist (at least one new file created)

**Severity:** CRITICAL

### What is checked
Generated files exist (at least one new file created)

### Why it matters
This rule protects output quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
The scaffold summary lists one or more created source or test files.

### ❌ Fail example
The summary is empty or no generated files can be found.

## CDG-002 — Generated code compiles/parses (language-appropriate check)

**Severity:** HIGH

### What is checked
Generated code compiles/parses (language-appropriate check)

### Why it matters
This rule protects quality gates quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Python files pass `py_compile`; other languages pass an available parser or compiler check.

### ❌ Fail example
Generated files contain syntax errors or fail the configured parser.

## CDG-003 — No hardcoded credentials or secrets in generated code

**Severity:** HIGH

### What is checked
No hardcoded credentials or secrets in generated code

### Why it matters
This rule protects security quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
No `password=`, `api_key`, `secret`, or AWS key patterns are present.

### ❌ Fail example
The scaffold contains embedded tokens, passwords, or secret placeholders that look real.

## CDG-004 — Error handling present in generated code

**Severity:** HIGH

### What is checked
Error handling present in generated code

### Why it matters
This rule protects reliability quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Generated handlers or services include try/catch, except, `if err != nil`, or equivalent.

### ❌ Fail example
Happy path only; failures are ignored.

## CDG-005 — Generated code follows project naming conventions

**Severity:** MEDIUM

### What is checked
Generated code follows project naming conventions

### Why it matters
This rule protects conventions quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
File names use language-appropriate casing such as `service.py`, `route.ts`, or `OrderController.java`.

### ❌ Fail example
Names violate common conventions, e.g. `Bad File Name.py`.

## CDG-006 — Tests generated alongside source files

**Severity:** MEDIUM

### What is checked
Tests generated alongside source files

### Why it matters
This rule protects testing quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
At least one generated test file accompanies the scaffolded source.

### ❌ Fail example
Only source files are created.

## CDG-007 — Generated code has at least minimal comments/docstrings

**Severity:** MEDIUM

### What is checked
Generated code has at least minimal comments/docstrings

### Why it matters
This rule protects maintainability quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Source files contain comments, docstrings, or API docs describing intent.

### ❌ Fail example
Generated files are uncommented stubs with no context.

## CDG-008 — README or CHANGELOG updated

**Severity:** LOW

### What is checked
README or CHANGELOG updated

### Why it matters
This rule protects docs quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
A README or CHANGELOG entry is created or updated for the scaffold run.

### ❌ Fail example
No operator-facing documentation is updated.

## CDG-009 — No TODO/FIXME left unresolved in critical paths

**Severity:** LOW

### What is checked
No TODO/FIXME left unresolved in critical paths

### Why it matters
This rule protects hygiene quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
Critical source files avoid `TODO` and `FIXME` markers.

### ❌ Fail example
Generated handlers or services are left with unresolved TODO markers.

## CDG-010 — Dependency manifest updated if new deps added

**Severity:** LOW

### What is checked
Dependency manifest updated if new deps added

### Why it matters
This rule protects dependencies quality and keeps the output aligned with agentskills.io production expectations.

### ✅ Pass example
If the scaffold suggests new dependencies, the manifest update is captured in the summary.

### ❌ Fail example
New dependencies are implied but the manifest was not updated or recorded.
