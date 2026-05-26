---
name: sdlc-review
description: >
  Run the SDLC Review phase. Performs SAST (static analysis), DAST hints, dependency CVE scanning,
  coding standards validation, and test coverage gating on staged or changed files. Blocks merge if
  CRITICAL or HIGH findings remain unresolved. Integrates with AgentCore Bridge via sdlc_run MCP.
  Activate when asked to review code, run security audit, check coding standards, validate before
  merge, or run pre-commit checks.
license: MIT
compatibility: >
  Python 3.9+. Optional: bandit (Python SAST), eslint (JS/TS), semgrep (multi-language).
  MCP: sdlc_run via AgentCore Bridge.
metadata:
  category: sdlc
  tags: [sdlc, review, security, sast, cve, owasp, coding-standards, pre-commit, agentcore, audit]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation Triggers

Activate this skill only when explicitly requested to review code, run a security audit, check coding standards,
validate a change before merge, or execute pre-commit quality gates.

**Important:** `disable-model-invocation: true` applies to this skill. It must be called explicitly by name so
review scans do not run unexpectedly inside normal authoring flows, CI dry-runs, or commit hooks.

Typical trigger phrases include:
- `review these changes`
- `run a security audit`
- `validate before merge`
- `check coding standards`
- `run pre-commit checks`
- `scan staged files for vulnerabilities`

## Industry Standards

This skill aligns review output and merge-gate decisions to the following standards and control sets:

- **OWASP Top 10 (2021)** — application risk categories for injection, auth, secrets, software integrity, and logging
- **OWASP ASVS v4.0** — verification requirements for secure coding, dependency hygiene, and review evidence
- **CWE/SANS Top 25** — prioritised weakness catalogue for hardcoded credentials, injection, unsafe deserialisation, and XSS
- **NIST SP 800-53** — engineering and assessment controls including SA, RA, SI, AU, and CM families
- **ISO/IEC 27001:2022** — secure development, change control, vulnerability handling, and auditability expectations
- **DORA (Digital Operational Resilience Act)** — resilience, secure change, dependency oversight, and evidence retention
- **PCI-DSS v4.0 secure coding requirements** — secure development and vulnerability remediation expectations
- **Google secure coding guidelines** — pragmatic secure-by-default implementation patterns and review discipline

## Security Check Categories

The local scanner and MCP-backed review path must classify findings into these categories:

1. **SAST** — insecure code constructs, injection risks, unsafe deserialisation, shell execution, XSS, and eval
2. **Dependency CVE** — vulnerable package versions in `requirements.txt` and `package.json`
3. **Secret Detection** — hardcoded credentials, API keys, tokens, passwords, and high-risk literals
4. **Coding Standards** — TODO/FIXME in critical paths, lint hygiene, project style conformance, and unsafe randomness
5. **Test Coverage Gate** — minimum coverage threshold enforcement where coverage data is available

## Severity Classification

| Severity | Meaning | Merge Impact |
| --- | --- | --- |
| **CRITICAL** | Confirmed high-risk exploitable weakness or governance blocker | **Block merge** |
| **HIGH** | Serious security, dependency, or quality issue with meaningful production risk | **Block merge** |
| **MEDIUM** | Needs remediation plan, ticket, or documented exception | Advisory unless policy escalates |
| **LOW** | Informational hygiene improvement | Informational |

## Workflow

Follow this five-step workflow for every invocation.

### 1. Pre-flight using git diff
- Prefer staged files from `git diff --cached --name-only`
- Otherwise review the branch diff against `origin/main` or `origin/master`
- If file arguments are supplied explicitly, use that narrowed list

### 2. Collect files and manifests
- Build the changed-file set
- Include dependency manifests (`requirements.txt`, `package.json`) when present
- Capture branch name, commit reference, and coverage/lint artefacts if available

### 3. Call `sdlc_run` or run local review
- Preferred: `mcp__sdlc_run` with `phase="review"`
- Fallback: run `scripts/run_review.py` locally for SAST, secret detection, dependency checks, lint status, and coverage parsing
- Use GitHub code search when remote code context is required

### 4. Parse results by severity
- Group findings into CRITICAL, HIGH, MEDIUM, LOW
- Identify unresolved CRITICAL/HIGH items immediately
- Record dependency CVEs with CVSS and fixed-version guidance
- Capture coverage percentage and lint status for merge policy evaluation

### 5. Write the review report
- Write `review/review-report-YYYYMMDD-HHMM.md`
- Persist machine-readable JSON next to the markdown report
- Summarise merge status as `PASSED` or `FAILED`
- Include remediation guidance for all blocking issues

## Merge Gate Policy

A review is **PASSED** only when all of the following are true:
- No unresolved **CRITICAL** findings remain
- No unresolved **HIGH** findings remain
- No hardcoded secrets are detected
- No known dependency CVEs with **CVSS ≥ 7.0** remain
- Test coverage is **≥ 80%** when coverage data exists

A review is **FAILED** when any of the above conditions are not met. Medium and low findings remain advisory unless
project policy explicitly requires a ticket, note, or exception record.

## Output Artefacts

The primary artefact is:

- `review/review-report-YYYYMMDD-HHMM.md`

Companion artefacts created by the local scanner:
- `review/review-report-YYYYMMDD-HHMM.json`
- Optional coverage summaries already present in the repo, such as `coverage/lcov.info` or `coverage/coverage-summary.json`

## CI/CD Integration

### Git pre-commit hook

```bash
python3 .agents/skills/sdlc-review/scripts/run_review.py \
  --project-root . \
  --files "$(git diff --cached --name-only | tr '\n' ',')" \
  --severity-threshold high
latest_report=$(ls -1t review/review-report-*.md | head -n 1)
python3 .agents/skills/sdlc-review/scripts/validate_review.py "$latest_report" --project-root .
```

### GitHub Actions step

```yaml
- name: Run SDLC review
  run: |
    python3 .agents/skills/sdlc-review/scripts/run_review.py --project-root . --severity-threshold high
    latest_report=$(ls -1t review/review-report-*.md | head -n 1)
    python3 .agents/skills/sdlc-review/scripts/validate_review.py "$latest_report" --project-root .
```

## MCP Tool Reference

Preferred MCP invocation:

```json
{
  "tool": "sdlc_run",
  "phase": "review",
  "input": "<changed files, manifests, and review context>",
  "project_key": "<repo-name>",
  "repo": "<owner/repo>",
  "session_id": "<session-id>"
}
```

Use `mcp__github-mcp-server__search_code` to enrich remote repository review context when changed files,
API surfaces, or dependency usage must be inspected beyond the local workspace.

## References

- `references/rules.md` — complete REV rule catalogue with severity, rationale, and security mappings
- `references/industry-standards.md` — primary standards, registries, and external references
- `references/agentcore-mcp-reference.md` — `sdlc_run` review examples and explicit invocation guidance
- `assets/schema.json` — machine-readable rule metadata for REV-001 through REV-010
- `templates/review-report.md` — canonical markdown review report template
- OWASP Top 10 (2021)
- OWASP ASVS v4.0
- CWE/SANS Top 25
- NIST SP 800-53
- ISO/IEC 27001:2022
- PCI-DSS v4.0
- agentskills.io
