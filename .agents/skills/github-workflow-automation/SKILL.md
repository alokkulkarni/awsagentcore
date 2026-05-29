---
name: github-workflow-automation
description: >
  Build, optimize, debug, and manage GitHub Actions CI/CD workflows — with or without AI swarm coordination via ruv-swarm and claude-flow. Use this skill whenever the user mentions GitHub Actions, CI/CD pipelines, workflow YAML files, pull request automation, release pipelines, self-healing workflows, security scanning in CI, or anything involving .github/workflows/. Also trigger when the user asks about automating repository management, multi-repo coordination, PR validation bots, or deployment strategies. Even if the user just says "set up CI for my project" or "my GitHub workflow keeps failing" — use this skill.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH), Node.js 18+ optional for Node repos. Compatible with Copilot CLI, VS Code GitHub Copilot, Kiro, Claude Code, Cursor, and Gemini CLI.
metadata:
  category: devops
  tags: [github-actions, ci, cd, workflow, docker, security, coverage, testing, deployment, automation]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Purpose

Generate, validate, harden, and troubleshoot production-ready GitHub Actions workflows for CI, CD, integration testing, regression testing, image scanning, deployment rollback, security reporting, and auditable report retention.

---

## MANDATORY: Ask ALL questions BEFORE creating any files

**You MUST ask every question below before writing a single workflow file.** Do NOT infer, assume, or skip any question. Do NOT use placeholder values. Ask questions one at a time in order, waiting for the user's answer before proceeding to the next.

---

### PHASE 1 — Repository & Detection

Ask these first:

> **Q1.** "What is the path (or GitHub URL) of the repository where the workflows should be created? [default: current directory]"

> **Q2.** "Where should workflow files be placed? [default: .github/workflows]"

After getting Q1, scan the repo with `scripts/scan_repo.py` to auto-detect: language, framework, package manager, test runner, Dockerfile presence. Tell the user what was detected, for example:
> "I detected: Node.js 20 / React / npm / Vitest / Dockerfile present. Does this look correct? [y/n]"
If they say no, ask them to confirm the correct values.

---

### PHASE 2 — What Workflows to Create

Ask each separately:

> **Q3.** "Create a CI workflow (build, test, coverage, security scan, Docker build/push)? [y/n, default: y]"

> **Q4.** "Create CD deployment workflows? [y/n, default: y]"

> **Q5.** "Create an integration tests workflow? [y/n, default: y]"

> **Q6.** "Create a regression tests workflow? [y/n, default: y]"

> **Q7.** "Create an image scanning workflow (Trivy + Grype + Docker Scout, email report)? [y/n, default: y]"

---

### PHASE 3 — CI Configuration (only if Q3 = y)

> **Q8.** "Which Docker registry should built images be pushed to? [dockerhub | ghcr | ecr | acr | custom, default: ghcr]"

> **Q9.** "What should the Docker image name be? [I suggest: `<org>/<repo-name>` derived from git remote — confirm or override]"
  Tell the user what you derived from `git config remote.origin.url`. Show the suggestion explicitly, e.g.:
  > "Based on the git remote I suggest the image name: `myorg/my-app`. Is this correct, or would you like a different name?"

> **Q10.** "What is the minimum code coverage threshold? [default: 80]%"

> **Q11.** "Should CI fail immediately on CRITICAL CVEs? [y/n, default: y]"

> **Q12.** "Should CI also fail on HIGH CVEs? [y/n, default: y]"

> **Q13.** "Which branches should trigger CI? [default: main, develop, feature/**, fix/**]"

---

### PHASE 4 — CD Configuration (only if Q4 = y)

> **Q14.** "How many deployment environments do you have? [default: 3]"

For EACH environment (e.g. env 1 of 3), ask:

> **Q15-A.** "Name for environment N? [default: dev / staging / prod]"

> **Q15-B.** "Deployment target for `<env-name>`? [ecs | eks | lambda | aca | cloudrun | kubernetes, default: ecs]"

> **Q15-C.** "Should `<env-name>` auto-deploy on push? [y/n, default: y for dev/staging, n for prod]"

> **Q15-D.** "Require manual approval gate for `<env-name>`? [y/n, default: n for dev/staging, y for prod]"

> **Q15-E.** "Health-check / smoke test URL for `<env-name>`? [optional, press Enter to skip]"

After all environments collected:

> **Q16.** "What Docker image/registry should CD pull images from? [default: same as CI push registry]"

---

### PHASE 5 — Regression Tests (only if Q6 = y)

> **Q17.** "What base URL should regression tests run against? [e.g. https://staging.myapp.com]"

> **Q18.** "Which environment triggers regression tests automatically? [default: staging]"

> **Q19.** "What test command runs regression tests? [e.g. npm run test:regression | pytest tests/regression/]"

---

### PHASE 6 — Image Scanning (only if Q7 = y)

> **Q20.** "When should image scanning run? [push | schedule | both, default: both]"

> **Q21.** "What cron schedule for image scanning? [default: 0 6 * * * — daily at 6am UTC]"

> **Q22.** "Email scan reports to? [optional, press Enter to skip]"

> **Q23.** "Email provider for scan reports? [sendgrid | ses | smtp, default: ses]"

> **Q24.** "Fail the scan workflow on new CRITICAL CVEs? [y/n, default: y]"

> **Q25.** "Compare scan results against the previous run (n-1) and block if regressions found? [y/n, default: y]"

---

### PHASE 7 — Reports & Retention

> **Q26.** "Where should dated reports be committed in the repo? [default: .github/reports]"

> **Q27.** "How many days should workflow artifacts be retained? [default: 90]"

> **Q28.** "Generate a live coverage badge in README? [y/n, default: y]"

---

## After collecting ALL answers — tell the user what you will create

Before writing any files, print a clear summary like this:

```
I will now create the following workflow files:
  ✅ .github/workflows/ci.yml          — CI: build, test, coverage, CodeQL, Docker build → ghcr.io/myorg/my-app
  ✅ .github/workflows/cd-dev.yml      — CD to dev (ECS, auto-deploy on push to develop)
  ✅ .github/workflows/cd-staging.yml  — CD to staging (ECS, auto-deploy on push to main)
  ✅ .github/workflows/cd-prod.yml     — CD to prod (ECS, manual approval required)
  ✅ .github/workflows/integration-tests.yml  — Integration tests triggered after staging CD
  ✅ .github/workflows/regression-tests.yml   — Regression tests against https://staging.myapp.com
  ✅ .github/workflows/image-scan.yml  — Trivy+Grype scan, daily at 06:00 UTC, report to ops@myorg.com

Shall I proceed? [y/n]
```

Wait for confirmation before writing any files.

---

## Workflow Specifications

### ci.yml — What it creates and why

Tell the user: **"Creating CI workflow — this runs on every push and pull request."**

Include these jobs (in dependency order):

1. **`lint-and-format`** — run linter for detected language (eslint / ruff / checkstyle / golangci-lint)
2. **`unit-tests`** — run test suite, generate coverage report, enforce threshold, upload dated artifact
3. **`security-scan`** — CodeQL analysis + dependency audit (npm audit / pip-audit / govulncheck / trivy fs), fail on CRITICAL (or HIGH if configured), compare against n-1 report
4. **`docker-build-push`** — build Docker image (only after security-scan passes), tag with git SHA + semver, push to configured registry, generate SBOM (`sbom.cdx.json`)
5. **`commit-reports`** — download all artifacts, commit dated reports to `.github/reports/YYYY-MM-DD/`, update coverage badge

For Docker build step, explicitly use the image name the user confirmed in Q9. Print it in a workflow comment.

### cd-<env>.yml — One file per environment

Tell the user: **"Creating CD workflow for `<env>` — deploys to `<target>`."**

Each CD workflow:
- Triggers: auto-deploy branches for non-prod envs; `workflow_dispatch` with `image_tag` input for all
- Uses GitHub Environment (`environment: <env-name>`) for secrets scoping and approval gates
- Pulls the exact image tag from registry (never rebuilds)
- Generates CBOM (`cbom.cdx.json`) for the deployment image before rollout
- Deploys to the chosen target (ECS / EKS / Lambda / ACA / Cloud Run / Kubernetes)
- Runs smoke test against the health-check URL if provided
- On failure: rolls back to previous stable deployment and exits non-zero
- Commits dated deployment report to `.github/reports/<env>/YYYY-MM-DD/`

### regression-tests.yml — Separate from integration tests

Tell the user: **"Creating regression tests workflow — runs after staging deployment and on schedule."**

- Triggers: `workflow_run` on `CD - staging` completion + `workflow_dispatch` + weekly schedule
- Runs the user-specified regression test command against the configured base URL
- Generates JUnit XML + markdown report
- Compares against n-1 regression report to detect new failures
- Commits dated regression report to `.github/reports/regression/YYYY-MM-DD/`
- Fails workflow if any regression test newly fails vs n-1

### integration-tests.yml — API/service integration layer

- Triggers: `workflow_run` on `CD - staging` completion + `workflow_dispatch`
- Sets up environment (spin up test containers if needed)
- Runs integration suite
- Uploads JUnit report artifact + commits to `.github/reports/integration/YYYY-MM-DD/`

### image-scan.yml — CVE scanning with comparison

- Trivy scan → SARIF to Security tab
- Grype scan → SARIF to Security tab
- Docker Scout policy evaluation
- Consolidate reports, compare with n-1 using `scripts/check_reports.py`
- Commit consolidated report to `.github/reports/image-scans/YYYY-MM-DD/`
- If email configured: send report via SES / SendGrid / SMTP
- Fail if new CRITICAL CVEs found vs n-1

---

## Security requirements — apply to ALL generated workflows

Every generated workflow MUST:

- Use pinned action versions from `assets/action-versions.json` (never `@latest` or `@master`)
- Declare minimal `permissions:` block (least privilege per job)
- Never contain plaintext secrets — all via `${{ secrets.NAME }}` or `${{ vars.NAME }}`
- Have `timeout-minutes:` on every job
- Use `continue-on-error: false` (default) unless explicitly justified in a comment
- Set `GITHUB_TOKEN` permissions to read-only globally, write only where needed
- Use `actions/cache` for dependencies to reduce attack surface from repeated downloads
- Run on `ubuntu-latest` (or pinned `ubuntu-24.04` for reproducibility)
- Have `retention-days:` on every `upload-artifact` step

---

## Scripts reference

| Script | Purpose |
|--------|---------|
| `scripts/collect_info.py` | CLI interactive questionnaire (saves `github-workflow-config.json`) |
| `scripts/scan_repo.py` | Auto-detect language/framework/package manager from a repo path |
| `scripts/scaffold_workflows.py` | Generate all workflow YAML files from config JSON |
| `scripts/validate_workflows.py` | Lint/validate generated workflows (30 GHA rules) |
| `scripts/check_reports.py` | Compare current findings against n-1 dated report |

### CLI usage
```bash
# Interactive collection
python3 .agents/skills/github-workflow-automation/scripts/collect_info.py

# Generate from saved config
python3 .agents/skills/github-workflow-automation/scripts/scaffold_workflows.py \
  --config github-workflow-config.json \
  --output /path/to/repo

# Validate existing workflows
python3 .agents/skills/github-workflow-automation/scripts/validate_workflows.py .github/workflows
```

### Mandatory generation guardrails

- Do **not** hand-write workflow YAML when this skill is available; always generate via `scripts/scaffold_workflows.py`.
- Validation runs automatically at the end of workflow generation and must pass.
- Treat missing SBOM/CBOM as a generation failure:
  - `VAL-011` must pass for `ci.yml` (SBOM).
  - `VAL-012` must pass for every `cd-*.yml` (CBOM).

---

## Rules enforcement

All generated workflows and the validator enforce GHA-001 through GHA-030 in `references/rules.md`:
pinned actions, scoped permissions, secret hygiene, coverage gating, CVE fail-fast, GitHub Environment approvals, dated report retention, rollback readiness, SBOM/CBOM generation, and supply-chain security.
