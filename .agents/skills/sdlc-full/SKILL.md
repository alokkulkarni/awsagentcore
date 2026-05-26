---
name: sdlc-full
description: >
  Run the complete SDLC pipeline end-to-end via AgentCore: analysis → architecture → refinement
  → development → test → review. Each phase is gated — the pipeline stops if a RED validation
  gate is returned. Invoke explicitly with a feature description. Not appropriate for targeted
  single-phase work — use the individual sdlc-* skills for that. Activate when asked to run
  the full pipeline, end-to-end SDLC, greenfield feature delivery, or full project setup.
license: MIT
compatibility: >
  Python 3.9+. Depends on: sdlc-analyse, sdlc-architecture, sdlc-backlog, sdlc-codegen,
  sdlc-test, sdlc-review skills being installed. MCP: sdlc_run via AgentCore Bridge.
metadata:
  category: sdlc
  tags: [sdlc, pipeline, end-to-end, agentcore, full-cycle, greenfield, analysis, architecture, codegen, testing, review]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation

This skill is **explicit invocation only** because `disable-model-invocation: true` is enabled.

Use either of these forms:

- `/sdlc-full [feature description]`
- `run full pipeline for [feature]`
- `run end-to-end SDLC for [feature]`
- `set up the full SDLC pipeline for [feature]`

Do **not** use this skill for isolated analysis, architecture, backlog, code generation, test, or review tasks. Use the corresponding `sdlc-*` phase skill instead.

## ⚠️ Important Note

This skill orchestrates **all six SDLC phases** in sequence:

1. Analysis
2. Architecture
3. Refinement
4. Development
5. Test
6. Review

Every phase must return a **GREEN** validation outcome before the pipeline can advance. Any **RED** gate halts execution immediately and must be reported clearly with the blocking phase, reason, and remediation path.

## Pipeline Overview

| Phase | Gate Condition | Halt Criteria |
|-------|---------------|---------------|
| Analysis | `validation_status = GREEN` | Any CRITICAL/HIGH finding unresolved |
| Architecture | `validation_status = GREEN` | No components defined |
| Refinement | `validation_status = GREEN` | Zero stories generated |
| Development | `validation_status = GREEN` | Code generation failed |
| Test | `coverage ≥ 80%` | Coverage < 80% |
| Review | `No CRITICAL/HIGH security findings` | Any unresolved CRITICAL/HIGH |

## Industry Standards

This pipeline should align to the following delivery and governance standards:

- **DORA metrics** — deployment frequency, lead time for changes, mean time to restore, and change failure rate.
- **SAFe PI Planning** — structured refinement, dependency visibility, and delivery sequencing across increments.
- **DevOps Research / Accelerate** — elite delivery performance correlates with fast, safe, measurable software delivery.
- **Google DORA State of DevOps Report** — use the same metrics language for pipeline health, flow, and release confidence.

## Workflow

Begin every run with repository context collection:

```bash
echo "Repository: $(basename $(git rev-parse --show-toplevel 2>/dev/null || echo 'unknown'))"
echo "Branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo 'unknown')"
echo "Last commit: $(git log -1 --format='%h %s' 2>/dev/null || echo 'none')"
echo "Feature scope: $ARGUMENTS"
echo "Session ID: ${CLAUDE_SESSION_ID:-unknown}"
```

### Phase 1 — Analysis

- Call `mcp__sdlc_run` with `phase="analysis"`.
- Input should include the feature description plus detected repository context.
- Persist outputs to `analysis/`.
- Stop immediately if requirements are incomplete or validation returns RED.

### Phase 2 — Architecture

- Call `mcp__sdlc_run` with `phase="architecture"`.
- Feed the validated analysis outputs into the architecture phase.
- Require a GREEN architecture gate with components, interfaces, and HLD artefacts present.
- Persist outputs to `architecture/`.

### Phase 3 — Refinement

- Call `mcp__sdlc_run` with `phase="refinement"`.
- Convert the architecture into epics, stories, acceptance criteria, and implementation slices.
- Require a GREEN refinement gate with non-zero story generation.
- Persist outputs to `backlog/`.

### Phase 4 — Development

- Call `mcp__sdlc_run` with `phase="development"`.
- Use approved stories and architecture as input.
- Require generated or modified source files plus a GREEN validation result.
- Record development artefacts in the pipeline report.

### Phase 5 — Test

- Call `mcp__sdlc_run` with `phase="test"`.
- Generate and/or run unit, integration, and end-to-end tests.
- Enforce the coverage gate: **minimum 80%**.
- Stop if the test gate is RED or if coverage falls below threshold.

### Phase 6 — Review

- Call `mcp__sdlc_run` with `phase="review"`.
- Review the final diff, generated artefacts, dependency posture, and security findings.
- The pipeline passes only when unresolved **CRITICAL/HIGH** findings are zero.
- Persist outputs to `review/`.

## Pipeline Report

The final report must include:

- Pipeline ID, project name, date, feature description
- Per-phase status, gate result, artefacts, and duration
- Phase summaries for analysis, architecture, backlog, development, test, and review
- Overall pipeline outcome: complete, halted, or complete with skips
- DORA baseline metrics captured for the run
- Recommended next steps

Use `templates/pipeline-report.md` as the canonical structure for markdown output.

## Local Fallback

If the AgentCore Bridge or `mcp__sdlc_run` tool is unavailable, run the local orchestrator:

```bash
python3 .agents/skills/sdlc-full/scripts/run_pipeline.py \
  --project-root <project_dir> \
  --feature "<feature description>"
```

The fallback orchestrator calls sibling `sdlc-*` scripts in sequence and validates each gate before advancing.

## MCP Tool Reference

- MCP tool: `mcp__sdlc_run`
- Phases: `analysis`, `architecture`, `refinement`, `development`, `test`, `review`
- Required coordination fields: `session_id`, `pipeline_id`, `project_key`, `repo`, `input`
- Expected output contract: phase artefacts, `validation_status`, findings, and phase metadata
- Error handling: any RED validation gate or non-zero execution status blocks continuation

See `references/agentcore-mcp-reference.md` for the full phase contract, pipeline tracking guidance, and error codes.

## References

- `references/rules.md` — pipeline gate rule index with severity and DORA alignment
- `references/industry-standards.md` — DORA, Accelerate, SAFe, DevOps Handbook, Google SRE, and agentskills.io references
- `references/agentcore-mcp-reference.md` — AgentCore `sdlc_run` reference for all six phases
- `assets/schema.json` — machine-readable pipeline validation rules
- `templates/pipeline-report.md` — canonical pipeline execution report template
- `templates/phase-gate-checklist.md` — manual phase gate checklist for operator review
