---
name: sdlc-test
description: >
  Run the SDLC Test phase. Generates unit tests, integration tests, and E2E test suites from
  the implementation, then runs them and reports coverage. Supports pytest, Jest/Vitest, Go test,
  JUnit/Maven, and Playwright. Integrates with AgentCore Bridge via sdlc_run MCP. Activate when
  asked to generate tests, write test cases, run tests, check coverage, or validate test quality.
license: MIT
compatibility: >
  Python 3.9+. Test runners: pytest, jest, vitest, go test, mvn test, playwright.
  MCP: sdlc_run via AgentCore Bridge.
metadata:
  category: sdlc
  tags: [sdlc, testing, unit-tests, integration-tests, e2e, pytest, jest, playwright, coverage, agentcore, tdd, bdd]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation Triggers

Activate this skill when explicitly asked to generate tests, create test cases, run test suites, check coverage,
validate test quality, or extend unit, integration, or E2E automation for an implementation.

Typical trigger phrases include:
- `generate tests for this feature`
- `write unit tests`
- `create integration tests`
- `run the test suite`
- `check coverage`
- `validate test quality`

## Industry Standards

The test phase aligns to the following references and target levels:

- **IEEE 829** — formal test documentation and planning structure
- **ISTQB Foundation Level** — equivalence partitioning, boundary analysis, state, and decision-table techniques
- **TDD (Test-Driven Development)** — incremental red/green/refactor discipline
- **BDD (Behaviour-Driven Development)** — user-journey and behaviour-focused test language
- **Google Testing Blog guidelines** — maintainable, layered, trustworthy automation patterns
- **Coverage targets** — **line coverage ≥ 80%**, **branch coverage ≥ 70%**

## Test Framework Matrix

| Language / Stack | Unit / Integration Framework | Coverage Tool | E2E Tool |
| --- | --- | --- | --- |
| Python | pytest | coverage.py / pytest-cov | Playwright or browser/API journey tests |
| JavaScript / TypeScript | Jest or Vitest | Istanbul / V8 coverage / lcov | Playwright |
| Go | `go test` | `go test -coverprofile` | Playwright or API journey tests |
| Java | JUnit 5 / Maven Surefire | JaCoCo | Playwright / Selenium-compatible flows |

## Test Generation Strategy

- **Unit tests:** generate at least one test file per source file
- **Integration tests:** add coverage for each API endpoint, route handler, or service boundary
- **E2E tests:** cover critical user journeys such as login, payment, transfer, onboarding, or checkout flows

## Coverage Gate

Minimum acceptable coverage when reports are available:

- **Line coverage:** 80% or higher
- **Branch coverage:** 70% or higher

## Workflow

Follow this five-step workflow.

### 1. Pre-flight
- Detect changed or target source files
- Count existing test files and coverage artefacts
- Identify package manager or build tool (`pytest`, `package.json`, `go.mod`, `pom.xml`)

### 2. Detect the active framework
- Prefer the framework already configured in the repository
- Fallback to the language default when auto-detection is required
- Use `pytest`, `jest`, `vitest`, `go test`, or `JUnit 5` as appropriate

### 3. Call `sdlc_run` or generate locally
- Preferred: `mcp__sdlc_run` with `phase="test"`
- Fallback: run `scripts/generate_tests.py` for local test-stub generation and framework-aware placement
- Use filesystem write access to persist generated test files when MCP is available

### 4. Run the test suite
- Execute the existing project test command or framework-native runner
- Capture pass/fail state, coverage output, and generated artefact locations

### 5. Report results
- Summarise generated unit/integration/E2E tests
- Surface line and branch coverage
- Highlight FIRST violations or weak tests
- Block when coverage gates fail or no discoverable tests exist

## Test Quality Checks

All generated or reviewed tests should satisfy **FIRST** properties:

- **Fast** — short feedback cycle
- **Independent** — no hidden ordering or shared mutable state
- **Repeatable** — deterministic across environments
- **Self-validating** — clear assertions and automated pass/fail outcome
- **Timely** — created alongside or before implementation changes

## Output Artefacts

Expected artefacts include:

- Test files alongside source or under conventional test directories such as `tests/`, `src/test/java/`, or package-local Go tests
- `coverage/lcov.info`, `coverage-summary.json`, `coverage.xml`, or `jacoco.xml`
- `test-results/` or framework-native result directories

## MCP Tool Reference

Preferred MCP invocation:

```json
{
  "tool": "sdlc_run",
  "phase": "test",
  "input": "<source files, framework, and quality expectations>",
  "project_key": "<repo-name>",
  "repo": "<owner/repo>",
  "session_id": "<session-id>"
}
```

Use `mcp__filesystem__write_file` for generated test artefacts when test content is produced remotely by the MCP path.

## References

- `references/rules.md` — TST rule catalogue with severity and testing-standard mappings
- `references/industry-standards.md` — testing standards, frameworks, and quality references
- `references/agentcore-mcp-reference.md` — `sdlc_run` test examples and coverage-gate guidance
- `assets/schema.json` — machine-readable TST rule metadata
- `templates/test-plan.md` — IEEE 829-style test plan template
- `templates/test-case.md` — reusable single test case template
- IEEE 829
- ISTQB Foundation Level
- Kent Beck — Test-Driven Development
- Cucumber / BDD references
- Google Testing Blog
