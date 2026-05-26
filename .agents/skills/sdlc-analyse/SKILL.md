---
name: sdlc-analyse
description: >
  Run the SDLC Analysis phase. Scans the repository, extracts requirements from code and
  documentation, performs dependency auditing, security scanning, and produces a
  validation-gated analysis report. Integrates with AgentCore Bridge via the sdlc_run MCP tool.
  Activate when asked to analyse, run requirements analysis, check dependencies, audit code quality,
  or start the SDLC pipeline.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH). Requires git in PATH for pre-flight context.
  MCP: sdlc_run tool via AgentCore Bridge (optional — falls back to local scan).
metadata:
  category: sdlc
  tags: [sdlc, analysis, requirements, dependencies, agentcore, mcp, pipeline, quality]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation

Activate this skill when the user asks to:

- analyse a repository or codebase
- run requirements analysis
- check dependencies or package risk
- audit code quality, documentation coverage, or delivery readiness
- extract requirements before architecture, backlog, or implementation phases
- start or resume the SDLC pipeline from discovery / analysis

Typical trigger phrases include: `analyse this repo`, `run requirements analysis`, `check dependencies`, `audit code quality`, `extract requirements`, `find documentation gaps`, `start the SDLC pipeline`, and `prepare the analysis phase`.

## Industry Standard

This skill aligns to the following references and should produce outputs consistent with them:

- **BABOK v3** — use structured requirement discovery, stakeholder needs capture, and traceable analysis outputs.
- **ISO/IEC 29148:2018** — ensure requirements are complete, verifiable, and implementation-aware.
- **IEEE 830-1998** — structure software requirements findings clearly enough to seed a formal specification.
- **OWASP Dependency-Check** — treat dependency inventory, vulnerable package detection, and remediation evidence as first-class analysis outputs.

## Workflow

Follow this workflow exactly.

### Step 1: Pre-flight git context
Run lightweight repository context collection before any scan so the report is tied to a concrete state.

```bash
printf 'Repository: %s\n' "$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")"
printf 'Branch: %s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
printf 'Commit: %s\n' "$(git log -1 --format='%h %s' 2>/dev/null || echo none)"
printf 'Dirty files: %s\n' "$(git status --short 2>/dev/null | wc -l | tr -d ' ')"
```

Capture the repository name, current branch, latest commit, and whether there are uncommitted changes. Include this context in all downstream artefacts.

### Step 2: Local repository scan (fallback-safe)
Always be prepared to run the local fallback scanner. Use it when MCP is unavailable, when the bridge is degraded, or when a fast local baseline is useful before remote orchestration.

```bash
python3 .agents/skills/sdlc-analyse/scripts/run_analysis.py \
  --project-root <project_dir> \
  --output-dir <project_dir>/analysis \
  --format both
```

The fallback scanner must:
- inspect README, docs, source, test, and manifest files
- extract at least a baseline set of requirements from repository evidence
- inventory dependencies and flag heuristic CVE risk patterns
- calculate code metrics such as lines of code, dependency totals, and available test coverage
- produce both JSON and Markdown outputs for validation

### Step 3: Call `sdlc_run` MCP when available
If AgentCore Bridge is available, call `sdlc_run` with `phase: "analysis"` and provide either the user request or a concise repository summary as the `input`.

Required parameters:
- `phase`: `analysis`
- `input`: user request plus discovered repository context
- `project_key`: uppercase repository key derived from the repo name
- `repo`: repository name, e.g. `owner/repo` or local directory name
- `session_id`: current session identifier if available

If the MCP call fails, times out, or is not configured, continue with the local artefacts from Step 2 and record that the run used local fallback mode.

### Step 4: Validate output
Validate the generated report immediately.

```bash
python3 .agents/skills/sdlc-analyse/scripts/validate_analysis.py analysis/source-code-report.json
python3 .agents/skills/sdlc-analyse/scripts/validate_analysis.py analysis/analysis-report.md
```

Validation is gating:
- **GREEN** when there are no CRITICAL or HIGH findings
- **RED** when any CRITICAL or HIGH findings remain

### Step 5: Write output artefacts
Persist the final analysis artefacts and surface a concise summary to the user. The report should clearly show:
- extracted requirements
- documentation coverage and gaps
- dependency inventory and risk posture
- code quality metrics and test evidence
- risk summary and recommended next steps

## Output Artefacts

Write artefacts to the project `analysis/` directory unless the caller overrides the output location.

- `analysis/source-code-report.json` — machine-readable analysis result
- `analysis/analysis-report.md` — analyst-friendly report suitable for review
- optional supporting logs or MCP payload snapshots if your execution environment supports them

## Validation Gates

### GREEN
All of the following are true:
- report files exist and are non-empty
- at least three requirements are extracted
- dependency inventory is present
- no unresolved HIGH or CRITICAL dependency risks remain without mitigation
- documentation, code quality, and technology stack sections are present
- risk summary and next steps are present

### RED
Any of the following applies:
- report artefacts are missing or empty
- fewer than three requirements are captured
- dependency inventory is absent
- unresolved HIGH / CRITICAL CVE findings lack mitigation notes
- key sections for documentation, code quality, or next steps are missing

## MCP Tool Reference

Call the AgentCore Bridge tool like this:

```json
{
  "phase": "analysis",
  "input": "Analyse this repository for requirements, dependencies, documentation, and code quality.",
  "project_key": "REPONAME",
  "repo": "owner/repo",
  "session_id": "current-session-id"
}
```

Response shape:

```json
{
  "validation_status": "GREEN",
  "output": {"report": "..."},
  "issues": []
}
```

Project key derivation rules:
- start from the repository name, not the full path
- uppercase letters only where possible
- replace non-alphanumeric characters with nothing
- keep it concise (typically 3-10 characters)
- examples: `aria-banking-agent` → `ARIABANK`, `payments-api` → `PAYMENTS`

If `sdlc_run` is unavailable, log the failure reason and fall back to `scripts/run_analysis.py` without blocking the workflow.

## References

- BABOK v3 — https://www.iiba.org/career-resources/a-business-analysis-body-of-knowledge/babok/
- ISO/IEC 29148:2018 — https://www.iso.org/standard/72089.html
- IEEE 830-1998 — https://standards.ieee.org/ieee/830/1222/
- OWASP Dependency-Check — https://owasp.org/www-project-dependency-check/
- NIST National Vulnerability Database — https://nvd.nist.gov/
- `references/rules.md` — complete ANL rule index with pass/fail examples
- `references/industry-standards.md` — standards summary and URLs
- `references/agentcore-mcp-reference.md` — `sdlc_run` usage reference for this phase
- `assets/schema.json` — machine-readable analysis rule metadata
- `templates/analysis-report.md` — default output template for local or MCP-backed analysis runs
