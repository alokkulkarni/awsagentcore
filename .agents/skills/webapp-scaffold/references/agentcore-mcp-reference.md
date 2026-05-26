# AgentCore MCP Reference

The `webapp_scaffold_run` MCP tool wraps the skill scripts so an agent can collect inputs, scaffold a project, or validate an existing output without manually orchestrating every step.

## Parameters

| Parameter | Type | Required | Description |
| --- | --- | --- | --- |
| `action` | string | yes | One of `scaffold`, `validate`, or `collect_info`. |
| `config_path` | string | no | Path to `webapp-config.json`. Used by `scaffold` and optionally by `collect_info`. |
| `output_dir` | string | no | Target project directory for generated files. Defaults to `./<project-name>/`. |
| `dry_run` | boolean | no | When `true`, print planned file operations without writing files. |

## Example payloads

```json
{
  "action": "collect_info",
  "config_path": "./webapp-config.json"
}
```

```json
{
  "action": "scaffold",
  "config_path": "./webapp-config.json",
  "output_dir": "./my-webapp",
  "dry_run": false
}
```

```json
{
  "action": "validate",
  "output_dir": "./my-webapp"
}
```
