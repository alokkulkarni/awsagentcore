# Agent Skills — AWS Lambda Audits

[agentskills.io](https://agentskills.io) defines an open skill format: a directory with `SKILL.md` plus optional scripts, references, and assets that AI agents can load on demand.

## Available skills

| Skill | Purpose | Activate when | Path |
| --- | --- | --- | --- |
| `lambda-performance-audit` | Validates AWS Lambda handlers against runtime performance best practices. | Writing, reviewing, creating, or optimizing Lambda handlers in Python, Node.js/TypeScript, Go, or Java. | `.agents/skills/lambda-performance-audit/` |
| `lambda-security-audit` | Validates Lambda handlers and dependency manifests for SAST issues, CVEs, secrets, PII exposure, and OWASP/CWE risks. | Writing, reviewing, creating, scanning, or security-auditing Lambda handlers or manifests such as `requirements.txt`, `package.json`, `go.mod`, `pom.xml`, or `build.gradle`. | `.agents/skills/lambda-security-audit/` |

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
```

### GitHub Copilot in VS Code or Copilot CLI

```bash
mkdir -p .agents/skills
cp -R .agents/skills/lambda-performance-audit .agents/skills/
cp -R .agents/skills/lambda-security-audit .agents/skills/
```

Global alternative:

```bash
mkdir -p ~/.agents/skills
cp -R .agents/skills/lambda-performance-audit ~/.agents/skills/
cp -R .agents/skills/lambda-security-audit ~/.agents/skills/
```

## Quick usage

1. Place the skill in a supported skills directory.
2. Reload skills in your agent if needed.
3. Ask the agent to review, optimize, or security-audit a Lambda handler.
4. Available commands:
   - `python3 .agents/skills/lambda-performance-audit/scripts/audit_lambda.py <file>`
   - `python3 .agents/skills/lambda-performance-audit/scripts/fix_lambda.py <file>`
   - `python3 .agents/skills/lambda-security-audit/scripts/audit_security.py <file>`
   - `python3 .agents/skills/lambda-security-audit/scripts/fix_security.py <file>`
   - `python3 .agents/skills/lambda-security-audit/scripts/scan_deps.py <manifest>`
5. Re-run the audit plus language-native validation before deployment.

## More

- Standard: https://agentskills.io
- Specification: https://agentskills.io/specification
