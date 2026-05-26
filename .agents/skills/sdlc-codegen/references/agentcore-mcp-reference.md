# AgentCore Bridge Development Reference

## Preferred MCP Flow

Use `sdlc_run` when the environment exposes AgentCore Bridge.

Example payload:

```json
{
  "phase": "development",
  "input": "Implement or scaffold the stories from backlog/stories-summary.md using the architecture in architecture/hld.md.",
  "project_key": "PROJ",
  "repo": "owner/repository",
  "session_id": "<session>"
}
```

Expected output should include generated files, dependency changes, and validation notes.

## Filesystem MCP Usage

If a filesystem MCP server is available, use it to write generated files while preserving the same safety rule as the local fallback:

- write only missing files
- report collisions as merge work
- persist a scaffold summary

## Local Fallback

```bash
python3 .agents/skills/sdlc-codegen/scripts/scaffold_project.py --project-root <repo> --framework auto
python3 .agents/skills/sdlc-codegen/scripts/validate_codegen.py --project-root <repo>
```
