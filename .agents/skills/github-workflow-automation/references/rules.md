### GHA-001: Always pin action versions

Use SHA-pinned actions where possible or stable version tags; never `@master` or `@latest`.

### GHA-002: Never store secrets in workflow files

All credentials must come from `secrets.*`, OIDC, or environment variables sourced outside the repo.

### GHA-003: Use `permissions:` minimal scope

Workflows and jobs must declare only the scopes needed for the steps they execute.

### GHA-004: Fail fast on CRITICAL CVEs

Security jobs must break the pipeline when CRITICAL issues are detected.

### GHA-005: Cache dependencies for speed

Use `setup-*` cache features or `actions/cache` for package managers and build tooling.

### GHA-006: Upload dated artifacts for auditability

Coverage, scan, deployment, and integration reports must be retained with date-based names.

### GHA-007: Use GitHub Environments for prod approval gates

Production deployments must target protected environments with reviewers or manual approvals.

### GHA-008: Always run CodeQL on every CI push

Initialize, autobuild, and analyze CodeQL in the security stage for supported languages.

### GHA-009: Generate SBOM for every Docker image

OCI image builds should publish SBOM or provenance metadata.

### GHA-010: Coverage threshold enforced in CI

The pipeline must parse coverage output and fail below the configured threshold.

### GHA-011: Use immutable build inputs

Prefer lockfiles, fixed language versions, and reproducible commands.

### GHA-012: Separate CI and CD concerns

Build/test and deploy workflows should be split to reduce blast radius and simplify approvals.

### GHA-013: Treat report regressions as first-class signals

Compare n-1 reports for security and coverage drift before promoting releases.

### GHA-014: Run smoke tests after every deployment

Every CD workflow must verify health or key paths before declaring success.

### GHA-015: Rollback must be scripted

Deployment jobs should have an automated rollback path when smoke tests or stabilization fail.

### GHA-016: Use artifact retention policies

All uploaded artifacts need explicit `retention-days` values.

### GHA-017: Prefer OIDC over long-lived cloud keys

Use workload identity or temporary credentials where the target platform supports it.

### GHA-018: Avoid implicit shell success

Use `set -euo pipefail` in multiline shell steps.

### GHA-019: Do not ignore failures without justification

If `continue-on-error` is needed, document the reason inline and gate the result elsewhere.

### GHA-020: Keep job names stable and descriptive

Use predictable job IDs so workflow_run triggers, status checks, and dashboards remain stable.

### GHA-021: Use Docker metadata labels and tags

Image builds should publish SHA tags and semantic or branch-aware tags when available.

### GHA-022: Publish reports back to the repo carefully

Bot commits must be scoped to generated reports and use `[skip ci]` to prevent loops.

### GHA-023: Security scan generated images, not just source

Run Trivy, Grype, and policy checks against pushed images after build.

### GHA-024: Validate YAML before merge

Workflow syntax and policy validation should run before repository-wide adoption.

### GHA-025: Prefer reusable workflows for repeated logic

Shared setup and notification logic should be modeled as workflow_call templates.

### GHA-026: Record deployment evidence

Deployment jobs should publish image, environment, rollback, and smoke-test evidence.

### GHA-027: Respect branch strategy

CI triggers should cover mainline, development, and feature work without over-triggering protected deploys.

### GHA-028: Surface integration test outcomes in summaries

Integration workflows should emit JUnit artifacts and markdown summaries for reviewers.

### GHA-029: Keep package publishing permissions narrow

Only jobs that push images or packages should receive package write access.

### GHA-030: Document external references and versions

Keep action versions, GitHub docs, OWASP guidance, and standards references alongside the skill.
