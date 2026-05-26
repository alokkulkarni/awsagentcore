# Agent Skills

[agentskills.io](https://agentskills.io) defines an open skill format: a directory with `SKILL.md` plus optional scripts, references, and assets that AI agents can load on demand.

## Available skills

| Skill | Purpose | Activate when | Path |
| --- | --- | --- | --- |
| `lambda-performance-audit` | Validates AWS Lambda handlers against runtime performance best practices. | Writing, reviewing, creating, or optimizing Lambda handlers in Python, Node.js/TypeScript, Go, or Java. | `.agents/skills/lambda-performance-audit/` |
| `lambda-security-audit` | Validates Lambda handlers and dependency manifests for SAST issues, CVEs, secrets, PII exposure, and OWASP/CWE risks. | Writing, reviewing, creating, scanning, or security-auditing Lambda handlers or manifests such as `requirements.txt`, `package.json`, `go.mod`, `pom.xml`, or `build.gradle`. | `.agents/skills/lambda-security-audit/` |
| `deployment-playbook` | Generates and validates industry-standard deployment playbooks (ITIL v4 / DORA / SRE format) with risk register, rollback strategy, communication plan, and approvals. | Creating a playbook, deployment plan, change management document, release strategy, or operational plan for any software component. | `.agents/skills/deployment-playbook/` |
| `deployment-runbook` | Generates and validates industry-standard operational runbooks (Google SRE format) with numbered steps, verify blocks, troubleshooting tables, and rollback procedures. | Creating a runbook, step-by-step deployment guide, troubleshooting guide, incident response procedure, or rollback guide. | `.agents/skills/deployment-runbook/` |
| `service-introduction` | Generates and validates industry-standard Service Introduction Documents (ITIL v4 / ISO 20000-1 format) with document control, architecture, dependencies, SLOs, risk register, and approvals. | Creating a SID, service introduction document, service design package, service onboarding record, or validating service transition readiness documentation. | `.agents/skills/service-introduction/` |
| `webapp-scaffold` | Scaffolds production-ready React + Vite webapps with Amazon Connect chat integration, brand-aware CSS theming, and CloudFront-ready deployment defaults. | Creating a branded React frontend, scaffolding a Vite webapp, integrating Amazon Connect hosted chat, or generating a secure marketing/site shell for banking, insurance, e-commerce, corporate, or generic SaaS. | `.agents/skills/webapp-scaffold/` |
| `github-workflow-automation` | Generates production-ready GitHub Actions CI/CD, integration-test, and image-scanning workflows with security gating and rollback-ready deployment automation. | Creating, debugging, hardening, or automating `.github/workflows/` pipelines, pull request validation, release delivery, image scanning, or multi-environment deployment workflows. | `.agents/skills/github-workflow-automation/` |
| `testcontainers` | Adds Testcontainers-based integration and E2E test scaffolding with dependency detection, credential wiring, and CI pipeline patching for Docker access. | Adding integration tests with real containerised dependencies (PostgreSQL, Redis, Kafka, LocalStack, etc.), replacing mocks, or enabling Testcontainers in existing CI pipelines. | `.agents/skills/testcontainers/` |
| `sdlc-analyse` | SDLC Analysis phase: repo scanning, requirements extraction, dependency audit, and code quality assessment via AgentCore. | Running analysis, extracting requirements, auditing dependencies, or starting an AgentCore SDLC pipeline. | `.agents/skills/sdlc-analyse/` |
| `sdlc-architecture` | SDLC Architecture phase: HLD generation, Mermaid component diagrams, ADRs, and tech stack recommendations via AgentCore. | Designing the solution, generating an HLD, creating ADRs, or producing architecture artefacts after analysis. | `.agents/skills/sdlc-architecture/` |
| `sdlc-backlog` | SDLC Refinement phase: epic and user story generation with Gherkin acceptance criteria and JIRA ticket creation via AgentCore. | Creating a backlog, refining architecture into epics/stories, or populating delivery tickets. | `.agents/skills/sdlc-backlog/` |
| `sdlc-codegen` | SDLC Development phase: code scaffolding and stub generation for Python, TypeScript, Go, Java, and Rust via AgentCore. | Scaffolding a project, generating implementation stubs, or converting approved stories into code. | `.agents/skills/sdlc-codegen/` |
| `sdlc-test` | SDLC Test phase: unit, integration, and E2E test generation with ≥80% coverage gating via AgentCore. | Generating tests, running validation suites, checking coverage, or enforcing the test gate. | `.agents/skills/sdlc-test/` |
| `sdlc-review` | SDLC Review phase: SAST, dependency CVE scan, coding standards review, and merge gating via AgentCore. | Running pre-merge review, security audit, standards validation, or a release gate check. | `.agents/skills/sdlc-review/` |
| `sdlc-full` | Full SDLC pipeline end-to-end (analysis → architecture → refinement → dev → test → review) with GREEN/RED phase gates via AgentCore. | Running the entire AgentCore delivery pipeline, greenfield feature delivery, or full project setup. | `.agents/skills/sdlc-full/` |

## Compatibility

| Platform | Status | Project path | Personal / global path |
| --- | --- | --- | --- |
| VS Code + GitHub Copilot | ✅ | `.agents/skills/<skill-name>/` (also `.github/skills/` or `.claude/skills/`) | `~/.agents/skills/<skill-name>/` (also `~/.copilot/skills/`) |
| GitHub Copilot CLI | ✅ | `.agents/skills/<skill-name>/` (also `.github/skills/` or `.claude/skills/`) | `~/.agents/skills/<skill-name>/` (also `~/.copilot/skills/`) |
| Kiro | ✅ | `.kiro/skills/<skill-name>/` | `~/.kiro/skills/<skill-name>/` |
| Cursor | ✅ | `.agents/skills/<skill-name>/` or `.cursor/skills/<skill-name>/` | `~/.agents/skills/<skill-name>/` or `~/.cursor/skills/<skill-name>/` |
| Gemini CLI | ✅ | `.agents/skills/<skill-name>/` or `.gemini/skills/<skill-name>/` | `~/.agents/skills/<skill-name>/` or `~/.gemini/skills/<skill-name>/` |
| Claude Code | ✅ | `.claude/skills/<skill-name>/` | `~/.claude/skills/<skill-name>/` |
| OpenHands | ✅ | `.agents/skills/<skill-name>/` | `~/.agents/skills/<skill-name>/` |

## Install

### This repository

Installed skills:

```text
.agents/skills/lambda-performance-audit/
.agents/skills/lambda-security-audit/
.agents/skills/deployment-playbook/
.agents/skills/deployment-runbook/
.agents/skills/service-introduction/
.agents/skills/webapp-scaffold/
.agents/skills/github-workflow-automation/
.agents/skills/testcontainers/
.agents/skills/sdlc-analyse/
.agents/skills/sdlc-architecture/
.agents/skills/sdlc-backlog/
.agents/skills/sdlc-codegen/
.agents/skills/sdlc-test/
.agents/skills/sdlc-review/
.agents/skills/sdlc-full/
```

### GitHub Copilot in VS Code or Copilot CLI

```bash
mkdir -p .agents/skills
cp -R .agents/skills/lambda-performance-audit .agents/skills/
cp -R .agents/skills/lambda-security-audit .agents/skills/
cp -R .agents/skills/deployment-playbook .agents/skills/
cp -R .agents/skills/deployment-runbook .agents/skills/
cp -R .agents/skills/service-introduction .agents/skills/
cp -R .agents/skills/webapp-scaffold .agents/skills/
cp -R .agents/skills/github-workflow-automation .agents/skills/
cp -R .agents/skills/testcontainers .agents/skills/
cp -R .agents/skills/sdlc-analyse .agents/skills/
cp -R .agents/skills/sdlc-architecture .agents/skills/
cp -R .agents/skills/sdlc-backlog .agents/skills/
cp -R .agents/skills/sdlc-codegen .agents/skills/
cp -R .agents/skills/sdlc-test .agents/skills/
cp -R .agents/skills/sdlc-review .agents/skills/
cp -R .agents/skills/sdlc-full .agents/skills/
```

Global alternative:

```bash
mkdir -p ~/.agents/skills
cp -R .agents/skills/lambda-performance-audit ~/.agents/skills/
cp -R .agents/skills/lambda-security-audit ~/.agents/skills/
cp -R .agents/skills/deployment-playbook ~/.agents/skills/
cp -R .agents/skills/deployment-runbook ~/.agents/skills/
cp -R .agents/skills/service-introduction ~/.agents/skills/
cp -R .agents/skills/webapp-scaffold ~/.agents/skills/
cp -R .agents/skills/github-workflow-automation ~/.agents/skills/
cp -R .agents/skills/testcontainers ~/.agents/skills/
cp -R .agents/skills/sdlc-analyse ~/.agents/skills/
cp -R .agents/skills/sdlc-architecture ~/.agents/skills/
cp -R .agents/skills/sdlc-backlog ~/.agents/skills/
cp -R .agents/skills/sdlc-codegen ~/.agents/skills/
cp -R .agents/skills/sdlc-test ~/.agents/skills/
cp -R .agents/skills/sdlc-review ~/.agents/skills/
cp -R .agents/skills/sdlc-full ~/.agents/skills/
```

### Kiro

```bash
mkdir -p .kiro/skills
cp -R .agents/skills/deployment-playbook .kiro/skills/
cp -R .agents/skills/deployment-runbook .kiro/skills/
cp -R .agents/skills/service-introduction .kiro/skills/
cp -R .agents/skills/webapp-scaffold .kiro/skills/
cp -R .agents/skills/github-workflow-automation .kiro/skills/
cp -R .agents/skills/testcontainers .kiro/skills/
cp -R .agents/skills/sdlc-analyse .kiro/skills/
cp -R .agents/skills/sdlc-architecture .kiro/skills/
cp -R .agents/skills/sdlc-backlog .kiro/skills/
cp -R .agents/skills/sdlc-codegen .kiro/skills/
cp -R .agents/skills/sdlc-test .kiro/skills/
cp -R .agents/skills/sdlc-review .kiro/skills/
cp -R .agents/skills/sdlc-full .kiro/skills/
```

### Claude Code

```bash
mkdir -p .claude/skills
cp -R .agents/skills/deployment-playbook .claude/skills/
cp -R .agents/skills/deployment-runbook .claude/skills/
cp -R .agents/skills/service-introduction .claude/skills/
cp -R .agents/skills/webapp-scaffold .claude/skills/
cp -R .agents/skills/github-workflow-automation .claude/skills/
cp -R .agents/skills/testcontainers .claude/skills/
cp -R .agents/skills/sdlc-analyse .claude/skills/
cp -R .agents/skills/sdlc-architecture .claude/skills/
cp -R .agents/skills/sdlc-backlog .claude/skills/
cp -R .agents/skills/sdlc-codegen .claude/skills/
cp -R .agents/skills/sdlc-test .claude/skills/
cp -R .agents/skills/sdlc-review .claude/skills/
cp -R .agents/skills/sdlc-full .claude/skills/
```

### Using install.sh (any skill)

```bash
# Install to current project only
bash .agents/skills/deployment-playbook/scripts/install.sh --project
bash .agents/skills/deployment-runbook/scripts/install.sh --project
bash .agents/skills/service-introduction/scripts/install.sh --project
bash .agents/skills/webapp-scaffold/scripts/install.sh --project
bash .agents/skills/github-workflow-automation/scripts/install.sh --project
bash .agents/skills/testcontainers/scripts/install.sh --project
bash .agents/skills/sdlc-analyse/scripts/install.sh --project
bash .agents/skills/sdlc-architecture/scripts/install.sh --project
bash .agents/skills/sdlc-backlog/scripts/install.sh --project
bash .agents/skills/sdlc-codegen/scripts/install.sh --project
bash .agents/skills/sdlc-test/scripts/install.sh --project
bash .agents/skills/sdlc-review/scripts/install.sh --project
bash .agents/skills/sdlc-full/scripts/install.sh --project

# Install globally (available in all projects)
bash .agents/skills/deployment-playbook/scripts/install.sh --global
bash .agents/skills/deployment-runbook/scripts/install.sh --global
bash .agents/skills/service-introduction/scripts/install.sh --global
bash .agents/skills/webapp-scaffold/scripts/install.sh --global
bash .agents/skills/github-workflow-automation/scripts/install.sh --global
bash .agents/skills/testcontainers/scripts/install.sh --global
bash .agents/skills/sdlc-analyse/scripts/install.sh --global
bash .agents/skills/sdlc-architecture/scripts/install.sh --global
bash .agents/skills/sdlc-backlog/scripts/install.sh --global
bash .agents/skills/sdlc-codegen/scripts/install.sh --global
bash .agents/skills/sdlc-test/scripts/install.sh --global
bash .agents/skills/sdlc-review/scripts/install.sh --global
bash .agents/skills/sdlc-full/scripts/install.sh --global
```

## Quick usage

1. Place the skill in a supported skills directory.
2. Reload skills in your agent if needed.
3. Ask the agent to create or validate a playbook/runbook, review a Lambda handler, generate a Service Introduction Document, scaffold a branded webapp, or run any SDLC phase or the full SDLC pipeline.
4. Available commands:
   - `python3 .agents/skills/lambda-performance-audit/scripts/audit_lambda.py <file>`
   - `python3 .agents/skills/lambda-performance-audit/scripts/fix_lambda.py <file>`
   - `python3 .agents/skills/lambda-security-audit/scripts/audit_security.py <file>`
   - `python3 .agents/skills/lambda-security-audit/scripts/fix_security.py <file>`
   - `python3 .agents/skills/lambda-security-audit/scripts/scan_deps.py <manifest>`
   - `python3 .agents/skills/deployment-playbook/scripts/generate_playbook.py --scan <dir>`
   - `python3 .agents/skills/deployment-playbook/scripts/generate_playbook.py --generate <dir> --output <file>`
   - `python3 .agents/skills/deployment-playbook/scripts/validate_playbook.py <playbook.md>`
   - `python3 .agents/skills/deployment-runbook/scripts/generate_runbook.py --scan <dir>`
   - `python3 .agents/skills/deployment-runbook/scripts/generate_runbook.py --generate <dir> --output <file>`
   - `python3 .agents/skills/deployment-runbook/scripts/validate_runbook.py <runbook.md>`
   - `python3 .agents/skills/service-introduction/scripts/generate_sid.py --project-root <dir> --scan-only --output-json`
   - `python3 .agents/skills/service-introduction/scripts/collect_info.py --output-json .sid-context.json`
   - `python3 .agents/skills/service-introduction/scripts/generate_sid.py --project-root <dir> --context-json .sid-context.json --output <sid.md>`
   - `python3 .agents/skills/service-introduction/scripts/validate_sid.py <sid.md>`
   - `python3 .agents/skills/webapp-scaffold/scripts/collect_info.py`
   - `python3 .agents/skills/webapp-scaffold/scripts/scaffold_webapp.py --config webapp-config.json --output <dir>`
   - `python3 .agents/skills/webapp-scaffold/scripts/validate_webapp.py <dir>`
   - `python3 .agents/skills/github-workflow-automation/scripts/collect_info.py`
   - `python3 .agents/skills/github-workflow-automation/scripts/scaffold_workflows.py --config github-workflow-config.json --output <repo>`
   - `python3 .agents/skills/github-workflow-automation/scripts/validate_workflows.py <repo>/.github/workflows`
   - `python3 .agents/skills/testcontainers/scripts/scan_project.py <project-dir>`
   - `python3 .agents/skills/testcontainers/scripts/collect_info.py --project <project-dir> --output-json testcontainers-config.json`
   - `python3 .agents/skills/testcontainers/scripts/scaffold_testcontainers.py --project <project-dir> --config testcontainers-config.json`
   - `python3 .agents/skills/testcontainers/scripts/patch_pipeline.py --project <project-dir> --provider <github-actions|gitlab-ci|jenkins|circleci|bitbucket|azure-devops>`
   - `python3 .agents/skills/testcontainers/scripts/validate_setup.py <project-dir>`
   - `python3 .agents/skills/sdlc-full/scripts/run_pipeline.py --project-root <dir> --feature "<feature>"`
   - `python3 .agents/skills/sdlc-full/scripts/validate_pipeline.py --project-root <dir>`
5. Re-run validators after making changes — exit 0 means no critical/high issues.

## More

- Standard: https://agentskills.io
- Specification: https://agentskills.io/specification
