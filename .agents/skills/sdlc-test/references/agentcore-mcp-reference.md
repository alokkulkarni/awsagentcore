# AgentCore MCP Reference — Test Phase

## Preferred MCP call

```json
{
  "tool": "sdlc_run",
  "phase": "test",
  "input": "<source files, framework, expected test types, and coverage policy>",
  "project_key": "my-repo",
  "repo": "owner/my-repo",
  "session_id": "session-123"
}
```

## Coverage gate integration

The test phase should report:
- generated unit, integration, and E2E files
- test runner status
- line coverage
- branch coverage
- uncovered modules or journeys needing more tests

## Example prompts

- `Generate pytest unit tests for these Python modules and report coverage.`
- `Create Vitest integration tests for the changed API handlers.`
- `Run the SDLC test phase and enforce the coverage gate.`

## Fallback behaviour

If `sdlc_run` is unavailable:
1. Run `scripts/generate_tests.py`.
2. Execute the repository's existing test runner.
3. Run `scripts/validate_tests.py`.
4. Fail the gate when critical/high rules remain.
