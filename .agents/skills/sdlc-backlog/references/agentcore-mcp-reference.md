# AgentCore Bridge and JIRA MCP Reference

## Preferred MCP Flow

Use AgentCore Bridge first when the environment exposes `sdlc_run`.

Example payload:

```json
{
  "phase": "refinement",
  "input": "Generate epics and user stories from architecture/hld.md with Gherkin acceptance criteria.",
  "project_key": "PROJ",
  "repo": "owner/repository",
  "session_id": "<session>"
}
```

Expected response shape:

- epic list
- user story list
- acceptance criteria per story
- optional sprint sizing and dependency hints
- optional JIRA issue keys if ticket creation is delegated downstream

## JIRA MCP Usage

Create epics first:

```json
{
  "summary": "Customer Identity",
  "description": "Epic generated from architecture component Customer Identity"
}
```

Then create stories with the resulting epic link:

```json
{
  "summary": "As a security administrator, I want ... so that ...",
  "description": "Acceptance criteria:
- Given ...
- When ...
- Then ...",
  "epic": "EPIC-KEY"
}
```

## Local Fallback

If MCP tooling is unavailable, run:

```bash
python3 .agents/skills/sdlc-backlog/scripts/generate_backlog.py --project-root <repo>
python3 .agents/skills/sdlc-backlog/scripts/validate_backlog.py backlog/stories-summary.md
```
