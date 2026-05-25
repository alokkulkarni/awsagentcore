---
name: deployment-runbook
description: >
  Generate and validate industry-standard operational runbooks for any software project.
  Activate when a user asks to create a runbook, step-by-step deployment guide,
  operational procedure, incident response procedure, troubleshooting guide, or rollback guide.
  Covers: Google SRE runbook format, numbered steps with verify blocks, exact commands,
  expected outputs, troubleshooting tables, quick-reference sections, and rollback procedures.
  Use to create new runbooks from scratch, validate existing ones, or audit completeness.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH). Works with any project — language/framework agnostic.
metadata:
  category: operations
  tags: [runbook, deployment, sre, google-sre, operations, devops, incident-response, troubleshooting, procedures]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation

Activate this skill whenever the user asks for any of the following:

- A runbook, deployment runbook, release guide, or change-management procedure
- A step-by-step operational guide with exact commands
- A rollback guide, undo guide, restoration plan, or recovery procedure
- An incident response guide, pager/on-call playbook, or outage handling checklist
- A troubleshooting guide, failure-mode matrix, diagnostic sequence, or operational commands reference
- Validation or audit of an existing runbook for completeness, clarity, or SRE / ITIL alignment

Common trigger phrases include:

- "create a runbook"
- "how do I deploy this"
- "write rollback steps"
- "document the operational procedure"
- "incident response steps"
- "give me the commands operators should run"
- "create a troubleshooting guide"
- "make this executable by on-call"

## Industry Standard Format

Every generated or validated runbook MUST contain the following sections in this order:

1. **Document Control**
   - title
   - runbook ID in `RNB-XXX-NNN` format
   - version
   - status
   - owner
   - created date
   - last reviewed date
   - last tested date
2. **Overview**
   - component or service name
   - purpose / business context
   - critical dependencies
   - SLA/SLO targets
   - on-call contact / escalation owner
3. **Prerequisites**
   - access requirements
   - required tools
   - permissions
   - environment-variable checklist with exact names
   - pre-checks and guardrails
4. **Procedure Steps**
   - numbered steps only
   - every step MUST include:
     - step number and title
     - purpose / why this step exists
     - exact command(s) to run in fenced code blocks
     - ✓ **Verify** block with expected output, state, or exit code
     - ⚠️ **If this fails** block with recovery or escalation guidance
5. **Troubleshooting Table**
   - `symptom | probable cause | diagnostic command | resolution | escalate if`
6. **Rollback Procedure**
   - numbered rollback steps using the same command + verify + failure structure as the main procedure
7. **Quick Reference**
   - one-line command cheat sheet for time-critical use
8. **Change Log**
   - `version | date | author | change summary`

## Workflow

1. Scan project:
   `python3 .agents/skills/deployment-runbook/scripts/generate_runbook.py --scan <project_dir>`
2. Generate draft:
   `python3 .agents/skills/deployment-runbook/scripts/generate_runbook.py --generate <project_dir> --output <output_path>`
3. Validate completeness:
   `python3 .agents/skills/deployment-runbook/scripts/validate_runbook.py <runbook_file>`
4. Fix any **MISSING** sections or any numbered step that lacks a command block, ✓ Verify block, or ⚠️ failure block
5. Re-validate until the validator exits with code `0`

## Golden Rules

1. Every step MUST have an exact command — never say "run the deploy script" without the actual command.
2. Every step MUST have a ✓ Verify block showing expected output, state, or exit code.
3. Every step MUST have a ⚠️ failure block with the next action or escalation path.
4. Commands MUST be copy-paste ready — no `<your-value>` placeholders unless the variable is documented at the top.
5. Environment variables MUST be declared at the top with exact names.
6. All AWS resource names MUST use the real deployed name when known — avoid generic placeholders in generated output.
7. The troubleshooting table MUST cover the top 5 most common failure modes for the target system.

## Validation Rules

| Rule ID | Severity | Requirement |
|---------|----------|-------------|
| RNB-001 | CRITICAL | Document Control block present |
| RNB-002 | HIGH | Runbook ID follows `RNB-XXX-NNN` format |
| RNB-003 | HIGH | Version field present |
| RNB-004 | HIGH | Last-tested date present |
| RNB-005 | CRITICAL | Overview section present |
| RNB-006 | MEDIUM | SLA/SLO targets defined |
| RNB-007 | HIGH | On-call contact present |
| RNB-008 | CRITICAL | Prerequisites section present |
| RNB-009 | MEDIUM | At least one env var checklist item in Prerequisites |
| RNB-010 | CRITICAL | At least 3 numbered procedure steps |
| RNB-011 | CRITICAL | Each step has a code block (command) |
| RNB-012 | CRITICAL | Each step has a Verify block |
| RNB-013 | HIGH | Each step has a failure/escalation block |
| RNB-014 | HIGH | Troubleshooting table present |
| RNB-015 | MEDIUM | Troubleshooting table has at least 3 rows |
| RNB-016 | HIGH | Troubleshooting table has all 5 required columns |
| RNB-017 | CRITICAL | Rollback Procedure section present |
| RNB-018 | HIGH | Rollback procedure has numbered steps |
| RNB-019 | MEDIUM | Quick Reference section present |
| RNB-020 | LOW | Change Log present |

## References

- `references/rules.md` — complete rule index with pass/fail examples and remediation guidance
- `references/google-sre-reference.md` — Google SRE runbook philosophy, on-call guidance, and SLO alignment
- `references/runbook-patterns.md` — common deployment, canary, rollback, migration, and cloud deployment patterns
- `references/industry-standards.md` — Google SRE, ITIL v4, DevOps, AWS, DORA, PagerDuty, Atlassian, and Azure references
- `assets/schema.json` — machine-readable schema for required sections and rule severity mapping
- `templates/deployment-runbook.md` — full deployment runbook example
- `templates/rollback-runbook.md` — dedicated rollback procedure template
- `templates/incident-response-runbook.md` — incident response template with comms and escalation steps
- `templates/troubleshooting-runbook.md` — troubleshooting guide template with diagnostics and decision support
