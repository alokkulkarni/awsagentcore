---
name: sdlc-codegen
description: >
  Run the SDLC Development / Code Generation phase. Generates code stubs, scaffolding,
  boilerplate, and implementation from user stories and architecture artefacts. Detects
  the project language and framework and generates idiomatic code. Integrates with
  AgentCore Bridge via sdlc_run MCP. Activate when asked to generate code, scaffold,
  create boilerplate, implement stories, or build out components.
license: MIT
compatibility: >
  Python 3.9+. Generates code for: Python, TypeScript/JavaScript, Go, Java/Spring, Rust.
  MCP: sdlc_run via AgentCore Bridge.
metadata:
  category: sdlc
  tags: [sdlc, codegen, scaffolding, boilerplate, python, typescript, go, java, agentcore, development]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation Triggers

Activate this skill when the user asks to scaffold a project, generate code, create boilerplate, implement backlog items, build out components, or turn architecture and stories into source files.

Common trigger phrases include `generate code`, `scaffold this project`, `build the boilerplate`, `implement the stories`, `create service stubs`, and `generate framework structure`.

## Supported Languages and Frameworks

The skill is designed to detect or work with the following ecosystems:

- **Python:** FastAPI, Flask, Django
- **TypeScript / JavaScript:** Express, Next.js, React
- **Go:** stdlib, Gin, Echo
- **Java:** Spring Boot, Quarkus
- **Rust:** Actix, Axum

If auto-detection finds a supported language but not a listed framework, fall back to a safe language-level scaffold and document the assumption in the summary.

## Scaffolding Patterns

Use idiomatic project structure conventions for the detected stack:

- **Python web apps:** `app/` or `src/` packages, route modules, service modules, and `tests/`.
- **TypeScript services:** `src/` with component folders, request handlers, service logic, and colocated or sibling tests.
- **Next.js apps:** `app/` routes or API handlers, `components/` for UI modules, and test files under `tests/`.
- **Go services:** `internal/` packages or package-per-component folders, handlers/services, and `_test.go` files.
- **Java services:** `src/main/java` and `src/test/java` with package-appropriate class names.
- **Rust services:** `src/` modules plus `tests/` integration coverage.

## Code Generation Principles

Generated code should follow these principles:

- **DRY:** avoid duplicated boilerplate when one shared pattern is enough.
- **SOLID:** keep responsibilities separated and interfaces intentional.
- **Idiomatic patterns:** prefer framework-native structure and naming.
- **Test-first mindset:** create or suggest test files alongside the scaffold.
- **Operational readiness:** include basic validation, error handling, and documentation hints.

## Workflow

Follow this five-step workflow.

### 1. Pre-flight with Language Detection
- Inspect `package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`, `pom.xml`, and `Cargo.toml`.
- Confirm whether the user wants a new scaffold, story implementation, or safe stub generation.
- Decide whether MCP-backed generation or the local scaffold script should be used.

### 2. Read Architecture and Backlog
- Read `architecture/hld.md` first.
- Read `backlog/stories-summary.md` when available to preserve story scope and naming.
- Extract components, routes, dependencies, and non-functional expectations.

### 3. Call `sdlc_run` or Local Scaffold
Preferred MCP flow:

```text
phase="development"
input=<architecture + backlog + requested implementation scope>
```

Local fallback:

```bash
python3 .agents/skills/sdlc-codegen/scripts/scaffold_project.py --project-root <repo> --framework auto
```

### 4. Apply Generated Files Safely
- Never overwrite existing source files silently.
- Create only missing files.
- If a generated file conflicts with an existing implementation, report the merge suggestion instead of replacing the file.

### 5. Run Validation
- Run language-appropriate validation for generated code.
- Validate scaffold quality with:

```bash
python3 .agents/skills/sdlc-codegen/scripts/validate_codegen.py --project-root <repo>
```

## Language Detection

Auto-detection uses common repository manifests:

- `package.json` → Next.js, Express, React, Node/TypeScript indicators
- `requirements.txt` / `pyproject.toml` → FastAPI, Flask, Django, Python package metadata
- `go.mod` → Gin, Echo, or generic Go projects
- `pom.xml` / Gradle files → Spring Boot, Quarkus, or generic Java services
- `Cargo.toml` → Actix, Axum, or generic Rust crates

If multiple stacks are present, prefer the stack closest to the target scope or the repository root.

## Safe File Writing

- Never overwrite an existing file with generated content.
- Create new files only when the path is missing.
- Record skipped files in the scaffold summary so the operator can merge manually.
- Keep dependency suggestions explicit when a manifest update is needed but not safe to apply automatically.

## Output Artefacts

The local fallback should produce:

- generated source and test files for each discovered component
- `codegen/scaffold-summary.md`
- `codegen/scaffold-summary.json`

## MCP Tool Reference

- **`mcp__sdlc_run`**
  - `phase="development"`
  - `input=<stories + architecture + requested scope>`
- **`mcp__filesystem__write_file`**
  - Use to persist generated files when the environment exposes a filesystem MCP server.
  - Preserve the same no-overwrite rule used by the local scaffold script.

## References

- `references/rules.md` — validation rules for generated scaffolds
- `references/industry-standards.md` — SOLID, Clean Code, 12-Factor, style guides, and agentskills references
- `references/agentcore-mcp-reference.md` — AgentCore development-phase MCP usage
- `assets/schema.json` — machine-readable code generation rule metadata
- `templates/component-scaffold.md` — component scaffold report template
- `templates/codegen-summary.md` — code generation summary template
