---
name: deployment-playbook
description: >
  Generate and validate industry-standard deployment playbooks for any software project.
  Activate when a user asks to create a playbook, deployment plan, change management document,
  release strategy, or operational plan for deploying software components.
  Covers: ITIL v4 change management, DORA metrics alignment, risk register (RAID log),
  environment matrix, rollback strategy, communication plan, approvals table,
  success criteria, and post-deployment validation.
  Use to create new playbooks from scratch, validate existing ones, or audit completeness.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH). Works with any project — language/framework agnostic.
metadata:
  category: operations
  tags: [playbook, deployment, itil, change-management, release, sre, dora, runbook, operations, devops]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation

Activate this skill when the user asks for any of the following:

- Deployment playbook
- Deployment plan or release plan
- Change plan or change management document
- Operational readiness plan
- Release strategy or go-live checklist
- Rollback plan, go/no-go checklist, or production cutover plan
- Validation of an existing playbook or audit of deployment readiness documentation

Typical trigger phrases include: `create a playbook`, `write a deployment plan`, `draft a change document`, `prepare a release runbook`, `validate this playbook`, `audit deployment readiness`, and `create an operational plan for production rollout`.

## Industry Standard Format (Required Sections)

Every deployment playbook created or validated by this skill must contain all of the sections below.

### 1. Document Control
Required fields:
- Title
- Playbook ID in `PLY-XXX-NNN` format
- Version (semantic version)
- Status (`Draft`, `In Review`, `Approved`, `Active`, `Retired`)
- Owner
- Created date
- Last reviewed date
- Approvers

### 2. Purpose & Scope
Must define:
- Objective
- In-scope services, components, or activities
- Out-of-scope services or exclusions
- Intended audience

### 3. Component Overview
Must include:
- Architecture diagram placeholder or reference
- Technology stack summary
- Deployment model (for example: rolling, canary, blue/green, immutable, in-place)

### 4. Prerequisites
Must include:
- Access requirements
- Required tooling
- Environment readiness checklist

### 5. Deployment Strategy
Structure the rollout into phases. Every phase must include:
- Phase name
- Objective
- Steps list
- Dependencies
- Duration estimate
- Rollback trigger

### 6. Environment Matrix
Provide a table with the following columns:
- Environment
- Region
- Tier
- Purpose
- Deployment Order

### 7. Change Management
Must describe:
- Change type (`Standard`, `Normal`, or `Emergency`)
- Change window
- CAB approval path
- Freeze periods or blackout constraints

### 8. Risk Register
Provide a RAID-style markdown table with the following columns:
- ID
- Risk/Issue
- Category
- Probability
- Impact
- Mitigation
- Owner
- Status

### 9. Rollback Strategy
Must include:
- Trigger conditions
- Step-by-step rollback instructions per component or deployment unit
- Rollback time objective (RTO)

### 10. Communication Plan
Provide a markdown table with:
- Phase
- Audience
- Channel
- Owner
- Timing

### 11. Success Criteria
Must define:
- Functional checks
- Performance thresholds
- SLO or reliability targets

### 12. Post-Deployment Validation
Must cover:
- Smoke tests
- Monitoring and alert review
- Business sign-off or service-owner confirmation

### 13. Contacts & Escalation
Provide a markdown table with:
- Role
- Name
- Contact
- Escalation Level

### 14. Approvals
Provide a markdown table with:
- Role
- Name
- Signature
- Date

## Workflow

Follow this workflow exactly:

1. Scan the target project:
   ```bash
   python3 .agents/skills/deployment-playbook/scripts/generate_playbook.py --scan <project_dir>
   ```
2. Generate the initial draft:
   ```bash
   python3 .agents/skills/deployment-playbook/scripts/generate_playbook.py --generate <project_dir> --output <output_path>
   ```
3. Validate the generated or existing playbook:
   ```bash
   python3 .agents/skills/deployment-playbook/scripts/validate_playbook.py <playbook_file>
   ```
4. Fix every missing or invalid section reported by the validator.
5. Re-run validation until the validator exits with code `0`.

## Validation Rules

Use the rules below to validate completeness and structure.

| Rule ID | Severity | Requirement |
|---------|----------|-------------|
| PLAY-001 | CRITICAL | Document Control block present |
| PLAY-002 | HIGH | Playbook ID follows `PLY-XXX-NNN` format |
| PLAY-003 | HIGH | Version field present and semver format |
| PLAY-004 | HIGH | Status is one of `Draft`, `In Review`, `Approved`, `Active`, `Retired` |
| PLAY-005 | HIGH | At least one Approver listed |
| PLAY-006 | CRITICAL | Purpose section present |
| PLAY-007 | MEDIUM | In-scope and Out-of-scope defined |
| PLAY-008 | CRITICAL | At least one deployment phase defined |
| PLAY-009 | HIGH | Each phase has rollback trigger defined |
| PLAY-010 | HIGH | Risk Register table present with at least one entry |
| PLAY-011 | HIGH | Risk Register has all 8 required columns |
| PLAY-012 | CRITICAL | Rollback Strategy section present |
| PLAY-013 | HIGH | RTO (rollback time) defined |
| PLAY-014 | MEDIUM | Communication Plan table present |
| PLAY-015 | HIGH | Success Criteria section present |
| PLAY-016 | HIGH | Post-Deployment Validation section present |
| PLAY-017 | MEDIUM | Contacts & Escalation table present |
| PLAY-018 | HIGH | Approvals table present |
| PLAY-019 | MEDIUM | Environment Matrix table present |
| PLAY-020 | MEDIUM | Change Management section with change type defined |

## Output Expectations

When creating a playbook:

- Use enterprise change-management language.
- Prefer measurable statements over vague guidance.
- Fill detected values automatically from the project scan.
- Use `<!-- PLACEHOLDER: ... -->` comments where project-specific detail cannot be inferred safely.
- Keep the document audit-ready: dates, owners, approvers, environments, risk entries, rollback triggers, and validation steps must be explicit.

When validating an existing playbook:

- Report rule failures using the validator output format.
- Treat `CRITICAL` and `HIGH` findings as blockers.
- Recommend concrete remediations aligned with ITIL v4, DORA, and SRE operating practices.

## References

- `references/rules.md` — complete validation rule index with pass/fail guidance
- `references/itil-reference.md` — ITIL v4 alignment and CAB guidance
- `references/industry-standards.md` — ITIL, DORA, SRE, ISO 20000, ISO 22301, and NIST references
- `references/iso-change-management.md` — ISO 20000 / ITSM change management reference
- `assets/schema.json` — machine-readable schema for required sections, fields, and rules
- `templates/deployment-playbook.md` — standard deployment playbook template
- `templates/change-management-playbook.md` — ITIL normal change template
- `templates/incident-response-playbook.md` — incident response template
- `templates/release-playbook.md` — release management template
