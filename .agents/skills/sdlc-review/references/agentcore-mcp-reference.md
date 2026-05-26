# AgentCore MCP Reference — Review Phase

## Preferred MCP call

Use the AgentCore Bridge tool when available:

```json
{
  "tool": "sdlc_run",
  "phase": "review",
  "input": "<changed files, file contents, manifests, and review context>",
  "project_key": "my-repo",
  "repo": "owner/my-repo",
  "session_id": "session-123"
}
```

## Example prompts

- `Run the SDLC review phase on the staged files and block merge on critical or high issues.`
- `Review these changed API handlers and include dependency CVE results.`
- `Run review on this PR diff and write a markdown report.`

## `disable-model-invocation: true`

This skill is intentionally explicit-only. Review scans can modify CI behaviour, generate merge-blocking artefacts, or create pre-commit friction, so the skill should only run when named directly by the caller or automation.

## Fallback behaviour

If `sdlc_run` is unavailable:
1. Detect changed or staged files locally.
2. Run `scripts/run_review.py`.
3. Validate the report with `scripts/validate_review.py`.
4. Surface blocking findings and remediation guidance.
