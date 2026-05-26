---
name: sdlc-backlog
description: >
  Run the SDLC Refinement / Backlog Generation phase. Generates JIRA-compatible epics, user stories
  with Gherkin acceptance criteria, and sub-tasks from architecture artefacts. Integrates with
  AgentCore Bridge (sdlc_run MCP) and JIRA MCP Server for ticket creation. Activate when asked to
  create backlog, generate stories, populate JIRA, write user stories, or refine requirements.
license: MIT
compatibility: >
  Python 3.9+. Optional: JIRA MCP Server for direct ticket creation.
  MCP: sdlc_run via AgentCore Bridge; mcp__jira for JIRA integration.
metadata:
  category: sdlc
  tags: [sdlc, backlog, jira, user-stories, agile, scrum, safe, refinement, gherkin, agentcore]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation Triggers

Activate this skill when the user asks to create or refine a delivery backlog, generate epics, write user stories, populate JIRA, decompose architecture into sprint-ready work, or turn requirements into agile tickets.

Typical trigger phrases include `create backlog`, `generate stories`, `populate JIRA`, `write user stories`, `refine requirements`, `turn the HLD into epics`, and `create sprint-ready stories`.

## Industry Standards

This skill aligns to the following delivery standards and patterns:

- **Scrum Guide (Schwaber & Sutherland):** backlog items must be transparent, ordered, and valuable.
- **SAFe (Scaled Agile Framework):** epics should trace to business outcomes, architecture, and implementation enablers.
- **INVEST:** each story should be Independent, Negotiable, Valuable, Estimable, Small, and Testable.
- **Gherkin / Cucumber BDD:** acceptance criteria should be expressed in executable Given / When / Then language.
- **Mike Cohn user story format:** story text should capture persona, capability, and outcome.

Always prefer thin vertical slices, clear business value, and traceability back to architecture artefacts.

## User Story Format

Use the standard sentence structure exactly:

`As a [persona], I want [capability] so that [benefit]`

Guidance:

- **Persona** should identify the real actor: customer, analyst, operator, admin, service consumer, or support engineer.
- **Capability** should describe one observable outcome, not a technical task list.
- **Benefit** should capture the reason the work matters to the user or business.
- If the source input is technical-only, infer the nearest operational or business persona instead of writing implementation-only stories.

## Acceptance Criteria Format

Every story should have acceptance criteria in Gherkin form:

- `Given` the relevant precondition or system state
- `When` the actor performs an action or the event occurs
- `Then` the expected observable result happens

Example:

```gherkin
Given the order service is available
When a customer submits a valid order
Then the platform stores the order and returns a confirmation reference
```

Keep each scenario testable, specific, and tied to one expected outcome.

## Story Sizing

Use Fibonacci points for implementation sizing: `1, 2, 3, 5, 8, 13, 21`.

Reference mapping for coarse estimation:

- `XS` → `1`
- `S` → `2 or 3`
- `M` → `5`
- `L` → `8`
- `XL` → `13`
- `XXL` → `21`

Prefer smaller stories. If a story naturally sizes above `13`, split it into thinner slices before ticket creation.

## Workflow

Follow this five-step workflow.

### 1. Pre-flight
- Confirm the project root and whether `architecture/hld.md`, ADRs, diagrams, or requirements notes are present.
- Confirm whether JIRA integration is available.
- Decide whether the run is **MCP-backed** or **local fallback**.

### 2. Read Architecture Artefacts
- Read `architecture/hld.md` first.
- Also inspect related component diagrams, ADRs, and requirement notes when present.
- Extract domains, components, integrations, actors, constraints, and delivery dependencies.

### 3. Run `sdlc_run` or Generate Locally
Preferred MCP flow:

```text
phase="refinement"
input=<architecture context + scope + ticketing intent>
```

Local fallback:

```bash
python3 .agents/skills/sdlc-backlog/scripts/generate_backlog.py --project-root <repo>
```

### 4. Create JIRA Tickets via MCP if Available
- Create one epic per business capability or architecture component.
- Create user stories beneath the correct epic.
- Create sub-tasks only for concrete implementation work, not for acceptance criteria.
- Preserve story text, points, acceptance criteria, and dependency notes when creating tickets.

### 5. Write Local Summaries
Always persist the local output set:

- `backlog/stories-summary.md`
- `backlog/epics.md`
- `backlog/acceptance-criteria.md`

Then validate locally with:

```bash
python3 .agents/skills/sdlc-backlog/scripts/validate_backlog.py backlog/stories-summary.md
```

## Output Artefacts

The local fallback should produce the following artefacts:

- **`backlog/stories-summary.md`** — consolidated backlog report containing epics, stories, sizing, sprint assignment, and definition of done.
- **`backlog/epics.md`** — epic-level summary with business value, dependencies, and linked stories.
- **`backlog/acceptance-criteria.md`** — acceptance criteria extracted into a QA-friendly review format.

## JIRA Integration

When JIRA MCP tools are available:

- Use `mcp__jira__create_epic` to create the epic container first.
- Use `mcp__jira__create_issue` for stories and technical sub-tasks.
- Map local fields as follows:
  - Epic title → JIRA epic summary
  - Story text → JIRA issue summary/body
  - Acceptance criteria → issue description or structured acceptance field
  - Story points → estimation field
  - Sprint / iteration → planning field or label
  - Dependencies → linked issue relationships or labels

If JIRA is unavailable, generate the markdown backlog locally and surface it as the source of truth.

## MCP Tool Reference

- **`mcp__sdlc_run`**
  - `phase="refinement"`
  - `input=<HLD + business scope + backlog goal>`
  - Output should include epics, stories, sizing, acceptance criteria, and optionally JIRA references.
- **`mcp__jira__create_epic`**
  - Use for each epic generated from a domain, capability, or component.
- **`mcp__jira__create_issue`**
  - Use for stories and sub-tasks after the target epic exists.

## References

- `references/rules.md` — validation rules for production-quality backlog outputs
- `references/industry-standards.md` — Scrum, SAFe, INVEST, Gherkin, Mike Cohn, and agentskills references
- `references/agentcore-mcp-reference.md` — AgentCore Bridge and JIRA MCP usage patterns
- `assets/schema.json` — machine-readable backlog validation schema
- `templates/epic.md` — epic template
- `templates/user-story.md` — user story template
- `templates/stories-summary.md` — consolidated summary template
