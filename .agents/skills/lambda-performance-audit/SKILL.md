---
name: lambda-performance-audit
description: Validates AWS Lambda Python handlers against official AWS performance best practices. Activate when writing, reviewing, creating, or optimising Lambda functions or Lambda handlers. Covers: boto3 client placement, botocore Config with tcp_keepalive and retry settings, LOG_LEVEL environment variable, TTL caching for repeated AWS API calls, structured JSON invocation logging, N+1 loop patterns, and hardcoded region names. Use to audit existing Lambda files, auto-fix common issues, or validate changes before deployment.
license: MIT
compatibility: Python 3.9+ required, python3 in PATH; uv optional
metadata:
  category: aws
  tags: [lambda, aws, boto3, performance, serverless, python]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep]
---

## Activation

Activate this skill whenever a Lambda handler file is written, modified, reviewed, or created. A Lambda handler is a Python file containing a `lambda_handler(event, context)` function.

## What This Skill Does

Checks Lambda files for these rules:

- **CLIENT_IN_HANDLER** [CRITICAL]: `boto3.client()` or `boto3.resource()` called inside `lambda_handler`
- **MISSING_BOTO_CONFIG** [HIGH]: boto3 client/resource created without `botocore.config.Config(tcp_keepalive=True, ...)`
- **MISSING_CONFIG_IMPORT** [HIGH]: boto3 used but `from botocore.config import Config` not imported
- **HARDCODED_LOG_LEVEL** [MEDIUM]: `logger.setLevel()` hardcoded instead of `os.environ.get("LOG_LEVEL", "INFO")`
- **MISSING_INVOCATION_LOG** [LOW]: no structured JSON log at the start of `lambda_handler`
- **UNCACHED_PAGINATOR** [HIGH]: paginator used without TTL caching for repeated list APIs
- **API_CALL_IN_LOOP** [HIGH]: AWS API call inside a `for`/`while` loop (N+1 pattern)
- **HARDCODED_REGION** [MEDIUM]: hardcoded `region_name=` in a boto3 client/resource call
- **BROAD_EXCEPT** [LOW]: broad `except Exception` without specific boto3 exceptions first

## Workflow

When a Lambda file is written or modified:

1. Run: `python3 .agents/skills/lambda-performance-audit/scripts/audit_lambda.py <file_path>`
2. For each CRITICAL/HIGH issue, fix it manually or use `fix_lambda.py` for auto-fixable ones
3. For MEDIUM/LOW issues, use best judgment or align with the user’s preference
4. Re-run the audit until zero CRITICAL/HIGH issues remain
5. Run: `python3 -m py_compile <file_path>` to validate syntax

## Auto-fix

Run: `python3 .agents/skills/lambda-performance-audit/scripts/fix_lambda.py <file_path>`

This auto-fixes:

- `MISSING_BOTO_CONFIG`
- `MISSING_CONFIG_IMPORT`
- `HARDCODED_LOG_LEVEL`
- `MISSING_INVOCATION_LOG`

`CLIENT_IN_HANDLER` and `API_CALL_IN_LOOP` require manual restructuring.

## The Standard Pattern

Every performant Lambda MUST have:

```python
import os, json, logging
import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)

# Module-level client (warm reuse across invocations)
_CLIENT = boto3.client("connect", config=_BOTO_CONFIG)

def lambda_handler(event, context):
    logger.info(json.dumps({"event": "lambda_invoked", "function": context.function_name}))
    # ... handler logic
```

## References

- For complete rules: read `references/rules.md`
- For code patterns and before/after examples: read `references/fix-patterns.md`
- For auto-fixable rule machine-readable definitions: read `assets/rules.json`
