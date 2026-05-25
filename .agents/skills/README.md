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
```

### GitHub Copilot in VS Code or Copilot CLI

```bash
mkdir -p .agents/skills
cp -R .agents/skills/lambda-performance-audit .agents/skills/
cp -R .agents/skills/lambda-security-audit .agents/skills/
cp -R .agents/skills/deployment-playbook .agents/skills/
cp -R .agents/skills/deployment-runbook .agents/skills/
cp -R .agents/skills/service-introduction .agents/skills/
```

Global alternative:

```bash
mkdir -p ~/.agents/skills
cp -R .agents/skills/lambda-performance-audit ~/.agents/skills/
cp -R .agents/skills/lambda-security-audit ~/.agents/skills/
cp -R .agents/skills/deployment-playbook ~/.agents/skills/
cp -R .agents/skills/deployment-runbook ~/.agents/skills/
cp -R .agents/skills/service-introduction ~/.agents/skills/
```

### Kiro

```bash
mkdir -p .kiro/skills
cp -R .agents/skills/deployment-playbook .kiro/skills/
cp -R .agents/skills/deployment-runbook .kiro/skills/
cp -R .agents/skills/service-introduction .kiro/skills/
```

### Claude Code

```bash
mkdir -p .claude/skills
cp -R .agents/skills/deployment-playbook .claude/skills/
cp -R .agents/skills/deployment-runbook .claude/skills/
cp -R .agents/skills/service-introduction .claude/skills/
```

### Using install.sh (any skill)

```bash
# Install to current project only
bash .agents/skills/deployment-playbook/scripts/install.sh --project
bash .agents/skills/deployment-runbook/scripts/install.sh --project
bash .agents/skills/service-introduction/scripts/install.sh --project

# Install globally (available in all projects)
bash .agents/skills/deployment-playbook/scripts/install.sh --global
bash .agents/skills/deployment-runbook/scripts/install.sh --global
bash .agents/skills/service-introduction/scripts/install.sh --global
```

## Quick usage

1. Place the skill in a supported skills directory.
2. Reload skills in your agent if needed.
3. Ask the agent to create or validate a playbook/runbook, review a Lambda handler, or generate a Service Introduction Document.
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
5. Re-run validators after making changes — exit 0 means no critical/high issues.

## More

- Standard: https://agentskills.io
- Specification: https://agentskills.io/specification
