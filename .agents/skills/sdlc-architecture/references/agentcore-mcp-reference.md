# AgentCore MCP Reference — SDLC Architecture

## Tool Summary

- **Tool name:** `sdlc_run`
- **Primary phase value:** `architecture`
- **Purpose:** generate SDLC architecture outputs through AgentCore Bridge with validation status.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `phase` | string | Yes | Use `architecture` for this skill. |
| `input` | string | Yes | Requirements, constraints, and context from the analysis phase. |
| `project_key` | string | Yes | Compact uppercase project identifier derived from the repository name. |
| `repo` | string | Yes | Repository name, such as `owner/repo`. |
| `session_id` | string | Yes | Session identifier provided by the host runtime. |

## Example Payload

```json
{
  "phase": "architecture",
  "input": "Generate an HLD, component diagram, ADRs, and technology recommendations from the approved analysis output.",
  "project_key": "AWSAGENT",
  "repo": "alokkulkarni/awsagentcore",
  "session_id": "session-12345"
}
```

## Response Structure

```json
{
  "validation_status": "GREEN",
  "output": {
    "hld": "# High-Level Design...",
    "component_diagram": "flowchart LR...",
    "adrs": ["001-initial-architecture-baseline.md"]
  },
  "issues": []
}
```

## Deriving `project_key`

1. Use the repository name.
2. Remove separators and punctuation.
3. Convert to uppercase.
4. Keep it concise and readable.

Examples:
- `awsagentcore` → `AWSAGENT`
- `customer-portal` → `CUSTPORT`
- `payments-api` → `PAYMENTS`

## Error Handling and Fallback

If `sdlc_run` is unavailable:

1. Read `analysis/source-code-report.json` locally if it exists.
2. Run `scripts/generate_architecture.py`.
3. Validate the resulting artefacts with `scripts/validate_architecture.py`.
4. Continue the workflow using the local outputs.

## AgentCore Bridge Endpoint

AgentCore Bridge endpoint configuration is provided through the `AGENTCORE_ENDPOINT` environment variable. If it is unset or unavailable, assume local generation mode.
