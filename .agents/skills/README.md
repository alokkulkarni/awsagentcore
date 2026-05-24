# Agent Skills — Lambda Performance Audit

[agentskills.io](https://agentskills.io) defines an open skill format: a directory with `SKILL.md` plus optional scripts, references, and assets that AI agents can load on demand.

## Compatibility

| Platform | Status | Project path | Personal / global path |
| --- | --- | --- | --- |
| VS Code + GitHub Copilot | ✅ | `.agents/skills/lambda-performance-audit/` (also `.github/skills/` or `.claude/skills/`) | `~/.agents/skills/lambda-performance-audit/` (also `~/.copilot/skills/`) |
| GitHub Copilot CLI | ✅ | `.agents/skills/lambda-performance-audit/` (also `.github/skills/` or `.claude/skills/`) | `~/.agents/skills/lambda-performance-audit/` (also `~/.copilot/skills/`) |
| Kiro | ✅ | `.kiro/skills/lambda-performance-audit/` | `~/.kiro/skills/lambda-performance-audit/` |
| Cursor | ✅ | `.agents/skills/lambda-performance-audit/` or `.cursor/skills/lambda-performance-audit/` | `~/.agents/skills/lambda-performance-audit/` or `~/.cursor/skills/lambda-performance-audit/` |
| Gemini CLI | ✅ | `.agents/skills/lambda-performance-audit/` or `.gemini/skills/lambda-performance-audit/` | `~/.agents/skills/lambda-performance-audit/` or `~/.gemini/skills/lambda-performance-audit/` |
| Claude Code | ✅ | `.claude/skills/lambda-performance-audit/` | `~/.claude/skills/lambda-performance-audit/` |
| OpenHands | ✅ | `.agents/skills/lambda-performance-audit/` | `~/.agents/skills/lambda-performance-audit/` |

## Install

### This repository

Already installed at:

```text
.agents/skills/lambda-performance-audit/
```

### GitHub Copilot in VS Code or Copilot CLI

```bash
mkdir -p .agents/skills
cp -R .agents/skills/lambda-performance-audit .agents/skills/
```

Global alternative:

```bash
mkdir -p ~/.agents/skills
cp -R .agents/skills/lambda-performance-audit ~/.agents/skills/
```

### Kiro

```bash
mkdir -p .kiro/skills
cp -R .agents/skills/lambda-performance-audit .kiro/skills/
```

Global alternative:

```bash
mkdir -p ~/.kiro/skills
cp -R .agents/skills/lambda-performance-audit ~/.kiro/skills/
```

### Cursor

```bash
mkdir -p .cursor/skills
cp -R .agents/skills/lambda-performance-audit .cursor/skills/
```

Global alternative:

```bash
mkdir -p ~/.cursor/skills
cp -R .agents/skills/lambda-performance-audit ~/.cursor/skills/
```

### Gemini CLI

```bash
mkdir -p .gemini/skills
cp -R .agents/skills/lambda-performance-audit .gemini/skills/
```

Global alternative:

```bash
mkdir -p ~/.gemini/skills
cp -R .agents/skills/lambda-performance-audit ~/.gemini/skills/
```

### Claude Code

```bash
mkdir -p .claude/skills
cp -R .agents/skills/lambda-performance-audit .claude/skills/
```

Global alternative:

```bash
mkdir -p ~/.claude/skills
cp -R .agents/skills/lambda-performance-audit ~/.claude/skills/
```

### OpenHands

```bash
mkdir -p .agents/skills
cp -R .agents/skills/lambda-performance-audit .agents/skills/
```

Global alternative:

```bash
mkdir -p ~/.agents/skills
cp -R .agents/skills/lambda-performance-audit ~/.agents/skills/
```

## Quick usage

1. Place the skill in a supported skills directory.
2. Reload skills in your agent if needed.
3. Ask the agent to review or optimize a Python Lambda handler.
4. The skill should run:
   - `python3 .agents/skills/lambda-performance-audit/scripts/audit_lambda.py <file>`
   - `python3 .agents/skills/lambda-performance-audit/scripts/fix_lambda.py <file>`
5. Re-run the audit and `python3 -m py_compile <file>` before deployment.

## More

- Standard: https://agentskills.io
- Specification: https://agentskills.io/specification
