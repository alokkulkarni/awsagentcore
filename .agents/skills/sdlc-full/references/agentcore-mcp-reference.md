# AgentCore MCP Reference — `sdlc_run`

This reference summarises the expected AgentCore Bridge contract for the `sdlc_run` MCP tool when `sdlc-full` orchestrates the complete software delivery lifecycle.

## Supported phases

- `analysis`
- `architecture`
- `refinement`
- `development`
- `test`
- `review`

## Recommended request envelope

```json
{
  "phase": "analysis",
  "pipeline_id": "PIPELINE-20250115-104500",
  "session_id": "claude-session-id",
  "project_key": "PROJECT",
  "repo": "owner/repository",
  "input": "Feature description and relevant upstream artefacts"
}
```

## Expected response fields

- `phase` — current phase name
- `pipeline_id` — stable ID reused across all six phases
- `session_id` — stable MCP or agent session identifier
- `validation_status` — `GREEN` or `RED`
- `summary` — concise human-readable phase outcome
- `artifacts` — generated files, report paths, or structured artefact descriptors
- `findings` — structured issues, ideally with severity and remediation
- `metrics` — optional counts such as components, stories, files generated, tests generated, coverage, security findings

## Phase-specific expectations

### Analysis
Inputs: repository context and feature scope.  
Outputs: requirements, dependency audit, documentation gaps, quality findings.

### Architecture
Inputs: validated analysis outputs.  
Outputs: HLD, component model, interfaces, ADRs, tech stack recommendations.

### Refinement
Inputs: architecture artefacts.  
Outputs: epics, stories, acceptance criteria, backlog summary, ticket references.

### Development
Inputs: validated backlog plus architecture context.  
Outputs: source file changes, scaffolding manifests, implementation notes.

### Test
Inputs: generated or modified source files.  
Outputs: test files, execution results, coverage, failing modules if below threshold.

### Review
Inputs: full diff, generated artefacts, dependency manifests, test outcomes.  
Outputs: security findings, standards findings, final merge gate result.

## Error handling

Suggested pipeline-level error codes:

- `AGC-001` — invalid phase value
- `AGC-002` — missing required request field
- `AGC-003` — session expired or unknown session
- `AGC-004` — upstream skill dependency unavailable
- `AGC-005` — validation gate returned `RED`
- `AGC-006` — MCP transport or bridge failure

The `sdlc-full` pipeline must halt on `AGC-005` or any response whose `validation_status` is `RED`.

## Session and pipeline tracking

- Reuse a single `pipeline_id` for the whole run.
- Reuse a single `session_id` for correlated MCP telemetry where possible.
- Persist both IDs into the final pipeline report for traceability.
- If a rerun starts from `--start-phase`, keep the previous `pipeline_id` only when explicitly resuming the same delivery attempt.
