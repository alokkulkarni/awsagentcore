# AgentCore MCP Reference — SDLC Analysis

## Tool Summary

- **Tool name:** `sdlc_run`
- **Primary phase value:** `analysis`
- **Purpose:** execute the SDLC Analysis phase via AgentCore Bridge and return a validation-gated payload.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `phase` | string | Yes | Phase name. Use `analysis` for this skill. |
| `input` | string | Yes | The user request plus any repository summary or requirements context. |
| `project_key` | string | Yes | Compact uppercase project identifier derived from the repo name. |
| `repo` | string | Yes | Repository name, for example `owner/repo` or a local folder name. |
| `session_id` | string | Yes | Session identifier supplied by the host agent runtime. |

## Example Payload

```json
{
  "phase": "analysis",
  "input": "Analyse this repository for requirements, documentation gaps, dependencies, and code quality.",
  "project_key": "ARIABANK",
  "repo": "alokkulkarni/awsagentcore",
  "session_id": "session-12345"
}
```

## Response Structure

```json
{
  "validation_status": "GREEN",
  "output": {
    "requirements": [],
    "dependencies": [],
    "report_path": "analysis/analysis-report.md"
  },
  "issues": []
}
```

- `validation_status` is either `GREEN` or `RED`.
- `output` contains phase-specific structured results.
- `issues` contains validation or execution findings.

## Deriving `project_key`

1. Start with the repository name.
2. Remove punctuation and separators.
3. Uppercase the result.
4. Keep it concise (usually 3-10 characters).

Examples:
- `awsagentcore` → `AWSAGENT`
- `payments-api` → `PAYMENTS`
- `customer-portal` → `CUSTPORT`

## Error Handling and Fallback

If `sdlc_run` is unavailable, unreachable, or returns a transport error:

1. Record that MCP execution was not available.
2. Run `scripts/run_analysis.py` locally.
3. Validate the local outputs with `scripts/validate_analysis.py`.
4. Continue the SDLC workflow using the local artefacts.

## AgentCore Bridge Endpoint

The AgentCore Bridge endpoint is configured through the `AGENTCORE_ENDPOINT` environment variable. The skill should not hard-code the endpoint. If the variable is absent, assume local fallback mode.
