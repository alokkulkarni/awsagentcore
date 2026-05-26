---
name: sdlc-architecture
description: >
  Run the SDLC Architecture phase. Generates High-Level Design (HLD), component diagrams
  (Mermaid), Architecture Decision Records (ADRs), and technology stack recommendations.
  Integrates with AgentCore Bridge via sdlc_run MCP tool. Activate when asked to design
  architecture, generate HLD, write ADRs, create component diagrams, or recommend tech stack.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH). Mermaid CLI optional for diagram rendering.
  MCP: sdlc_run tool via AgentCore Bridge.
metadata:
  category: sdlc
  tags: [sdlc, architecture, hld, adr, togaf, c4, component-diagram, design, agentcore]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation

Activate this skill when the user asks to:

- design the system architecture
- generate a high-level design (HLD)
- create component or container diagrams
- write or update Architecture Decision Records (ADRs)
- recommend or rationalise a technology stack
- convert analysis outputs into architecture artefacts

Typical trigger phrases include: `design the architecture`, `generate the HLD`, `create ADRs`, `make a component diagram`, `recommend the tech stack`, `draft architecture docs`, and `continue from the analysis phase`.

## Industry Standards

This skill aligns to the following architecture references:

- **TOGAF ADM** — architecture development phases, viewpoints, and stakeholder traceability.
- **C4 Model (Simon Brown)** — system context, container, and component thinking for software architecture communication.
- **ISO/IEC/IEEE 42010** — architecture descriptions, concerns, viewpoints, and rationale.
- **arc42** — pragmatic architecture documentation template and quality attribute coverage.

## Architecture Decision Record (ADR) Format

Use the **MADR (Markdown Any Decision Records)** format for ADRs created by this skill. Every ADR should contain:

- **Title**
- **Status** (`Proposed`, `Accepted`, `Deprecated`, `Superseded`)
- **Context**
- **Decision**
- **Consequences** split into positive, negative, and neutral effects
- **Links** to related ADRs, analysis artefacts, or upstream constraints

Store ADRs in `architecture/adrs/` using a numeric prefix such as `001-initial-architecture-baseline.md`.

## Workflow

Follow this workflow exactly.

### Step 1: Pre-flight repository context
Collect repository context and confirm whether analysis artefacts are available.

```bash
printf 'Repository: %s\n' "$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")"
printf 'Branch: %s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
printf 'Analysis report: %s\n' "$(test -f analysis/source-code-report.json && echo available || echo missing)"
```

### Step 2: Read the analysis report
Prefer `analysis/source-code-report.json` as the canonical input. Extract:
- requirements
- dependency and risk findings
- technology stack
- documentation / operational constraints

If the analysis report is missing, note the gap and either run `sdlc-analyse` first or use the local generator to infer a baseline architecture from the repository.

### Step 3: Call `sdlc_run` or generate locally
When AgentCore Bridge is available, call `sdlc_run` with `phase: "architecture"` and pass the analysis summary as input.

Fallback-safe local generation command:

```bash
python3 .agents/skills/sdlc-architecture/scripts/generate_architecture.py \
  --project-root <project_dir> \
  --output-dir <project_dir>/architecture \
  --analysis-report <project_dir>/analysis/source-code-report.json
```

The local generator must produce an HLD, a Mermaid component diagram, at least one ADR, and a technology stack recommendation document.

### Step 4: Validate generated artefacts
Validate all architecture outputs immediately after generation.

```bash
python3 .agents/skills/sdlc-architecture/scripts/validate_architecture.py architecture
```

Validation is gating:
- **GREEN** when there are no CRITICAL or HIGH issues
- **RED** when any CRITICAL or HIGH rule fails

### Step 5: Write and summarize artefacts
Persist architecture artefacts and summarize:
- components and responsibilities
- integration points
- non-functional requirements and deployment model
- ADR decisions and trade-offs
- validation outcome

## Output Artefacts

Write artefacts to the project `architecture/` directory unless overridden.

- `architecture/hld.md` — High-Level Design document
- `architecture/component-diagram.mmd` — Mermaid component diagram
- `architecture/adrs/NNN-title.md` — ADR files in MADR format
- `architecture/tech-stack.md` — recommended technology stack and rationale

## Validation Gates

### GREEN
All of the following are true:
- `architecture/hld.md` exists and defines at least one component
- component diagram, ADRs, and tech stack artefacts exist
- responsibilities, interfaces, and non-functional requirements are documented
- deployment model and risk assessment are present

### RED
Any of the following applies:
- HLD, diagram, ADRs, or tech stack artefacts are missing
- components are undefined or lack responsibilities
- integration points are undocumented
- non-functional requirements, deployment model, or risk assessment are absent

## MCP Tool Reference

Call the AgentCore Bridge tool like this:

```json
{
  "phase": "architecture",
  "input": "Generate an HLD, component diagram, ADRs, and technology recommendations from the approved analysis report.",
  "project_key": "REPONAME",
  "repo": "owner/repo",
  "session_id": "current-session-id"
}
```

Expected response shape:

```json
{
  "validation_status": "GREEN",
  "output": {
    "hld": "...",
    "adr_files": [],
    "component_diagram": "..."
  },
  "issues": []
}
```

If MCP is unavailable, continue with `scripts/generate_architecture.py` and validate the local outputs.

## References

- TOGAF ADM — https://www.opengroup.org/togaf
- C4 Model — https://c4model.com/
- ISO/IEC/IEEE 42010 — https://www.iso.org/standard/50508.html
- arc42 — https://arc42.org/
- `references/rules.md` — complete ARC rule index with pass/fail examples
- `references/industry-standards.md` — standards summary and URLs
- `references/agentcore-mcp-reference.md` — `sdlc_run` usage reference for architecture generation
- `assets/schema.json` — machine-readable architecture rule metadata
- `templates/hld.md` — default high-level design template
- `templates/adr.md` — MADR ADR template
