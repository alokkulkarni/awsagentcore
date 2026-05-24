#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
AWS Lambda Performance Auditor
Validates Lambda handlers against AWS best practices for all supported runtimes.

Supported runtimes (detected by file extension):
  .py              — Python
  .js .mjs .cjs .ts — Node.js / TypeScript
  .go              — Go
  .java            — Java / Spring

Usage:
  python3 audit_lambda.py <file> [<file2> ...]
  python3 audit_lambda.py --json <file>      # JSON output
  python3 audit_lambda.py --summary <file>   # Counts only

Exit codes:
  0 — no CRITICAL or HIGH issues
  1 — one or more CRITICAL/HIGH issues found
  2 — file not found or parse error
"""

import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Severity ordering ───────────────────────────────────────────────────────

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# ─── Rule registry (all languages) ───────────────────────────────────────────

RULES: Dict[str, Dict[str, Any]] = {
    # ── Python ────────────────────────────────────────────────────────────────
    "CLIENT_IN_HANDLER": {
        "severity": "CRITICAL",
        "language": "python",
        "message": "boto3.client()/resource() called inside lambda_handler — recreated on every invocation",
        "suggestion": "Move to module level or use a lazy-init pattern (_X = None; def _get_x(): global _X; if _X is None: _X = boto3.client(...))",
        "auto_fixable": False,
    },
    "MISSING_BOTO_CONFIG": {
        "severity": "HIGH",
        "language": "python",
        "message": "boto3 client/resource created without botocore.config.Config",
        "suggestion": "Add: config=Config(tcp_keepalive=True, max_pool_connections=10, retries={'mode':'standard','max_attempts':3}, connect_timeout=5, read_timeout=15)",
        "auto_fixable": True,
    },
    "MISSING_CONFIG_IMPORT": {
        "severity": "HIGH",
        "language": "python",
        "message": "boto3 used but 'from botocore.config import Config' is not imported",
        "suggestion": "Add at top: from botocore.config import Config",
        "auto_fixable": True,
    },
    "HARDCODED_LOG_LEVEL": {
        "severity": "MEDIUM",
        "language": "python",
        "message": "Logger level is hardcoded — cannot be changed at runtime via LOG_LEVEL env var",
        "suggestion": "Replace with: logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))",
        "auto_fixable": True,
    },
    "MISSING_INVOCATION_LOG": {
        "severity": "LOW",
        "language": "python",
        "message": "No structured JSON log at the start of lambda_handler",
        "suggestion": "Add: logger.info(json.dumps({'event': 'lambda_invoked', 'function': context.function_name}))",
        "auto_fixable": True,
    },
    "UNCACHED_PAGINATOR": {
        "severity": "HIGH",
        "language": "python",
        "message": "Paginator called without TTL cache — list_* API call repeated every invocation",
        "suggestion": "Cache results at module level with a TTL dict: _CACHE = {}; use time.time() for expiry (300s recommended)",
        "auto_fixable": False,
    },
    "API_CALL_IN_LOOP": {
        "severity": "HIGH",
        "language": "python",
        "message": "AWS API call inside a loop — N+1 pattern increases latency and cost",
        "suggestion": "Collect IDs first, use batch APIs, or cache per-item lookups",
        "auto_fixable": False,
    },
    "HARDCODED_REGION": {
        "severity": "MEDIUM",
        "language": "python",
        "message": "Hardcoded AWS region in boto3 call",
        "suggestion": "Remove region_name= (Lambda sets AWS_REGION) or use os.environ.get('AWS_REGION')",
        "auto_fixable": False,
    },
    "BROAD_EXCEPT": {
        "severity": "LOW",
        "language": "python",
        "message": "Broad except Exception catches all exceptions without boto3-specific handling first",
        "suggestion": "Catch (ClientError, BotoCoreError) before broad except. Use logger.exception() for stack traces.",
        "auto_fixable": False,
    },

    # ── Node.js / TypeScript ──────────────────────────────────────────────────
    "JS_CLIENT_IN_HANDLER": {
        "severity": "CRITICAL",
        "language": "nodejs",
        "message": "AWS SDK client instantiated inside the handler function — recreated on every invocation",
        "suggestion": "Move 'new XxxClient(...)' to module scope (outside the handler function)",
        "auto_fixable": False,
    },
    "JS_SDK_V2_USAGE": {
        "severity": "HIGH",
        "language": "nodejs",
        "message": "AWS SDK v2 detected (require('aws-sdk') or import AWS from 'aws-sdk') — v2 is deprecated",
        "suggestion": "Migrate to AWS SDK v3: use per-service imports like '@aws-sdk/client-s3'. SDK v2 has larger cold-start bundle size.",
        "auto_fixable": False,
    },
    "JS_MISSING_HTTP_KEEPALIVE": {
        "severity": "HIGH",
        "language": "nodejs",
        "message": "No HTTP keepAlive agent configured — connections are not reused across SDK calls",
        "suggestion": "Add NodeHttpHandler with an https.Agent({ keepAlive: true }) from '@smithy/node-http-handler'",
        "auto_fixable": False,
    },
    "JS_MISSING_RETRY_CONFIG": {
        "severity": "HIGH",
        "language": "nodejs",
        "message": "AWS SDK client created without explicit maxAttempts — uses SDK default (3) with no visibility",
        "suggestion": "Set maxAttempts: 3 in the client config object",
        "auto_fixable": False,
    },
    "JS_FULL_SDK_IMPORT": {
        "severity": "MEDIUM",
        "language": "nodejs",
        "message": "Full SDK v2 import detected — increases deployment package size and cold-start time",
        "suggestion": "Use per-service SDK v3 imports: import { S3Client } from '@aws-sdk/client-s3'",
        "auto_fixable": False,
    },
    "JS_HARDCODED_REGION": {
        "severity": "MEDIUM",
        "language": "nodejs",
        "message": "Hardcoded AWS region string in client config",
        "suggestion": "Remove region (Lambda sets AWS_REGION) or use process.env.AWS_REGION",
        "auto_fixable": False,
    },
    "JS_MISSING_INVOCATION_LOG": {
        "severity": "LOW",
        "language": "nodejs",
        "message": "No structured JSON log at the start of the handler",
        "suggestion": "Add: console.log(JSON.stringify({ event: 'lambda_invoked', function: context.functionName }))",
        "auto_fixable": False,
    },
    "JS_UNHANDLED_ASYNC": {
        "severity": "HIGH",
        "language": "nodejs",
        "message": "Async handler with no try/catch — unhandled rejections silently fail",
        "suggestion": "Wrap handler body in try { ... } catch (err) { console.error(err); throw err; }",
        "auto_fixable": False,
    },

    # ── Go ────────────────────────────────────────────────────────────────────
    "GO_CLIENT_IN_HANDLER": {
        "severity": "CRITICAL",
        "language": "go",
        "message": "AWS SDK client created inside the handler function — not reused across warm invocations",
        "suggestion": "Move client creation to package-level var block and initialise in init()",
        "auto_fixable": False,
    },
    "GO_SDK_V1_USAGE": {
        "severity": "HIGH",
        "language": "go",
        "message": "AWS SDK for Go v1 detected (github.com/aws/aws-sdk-go) — v1 is in maintenance mode",
        "suggestion": "Migrate to AWS SDK for Go v2: github.com/aws/aws-sdk-go-v2",
        "auto_fixable": False,
    },
    "GO_MISSING_HTTP_TRANSPORT": {
        "severity": "HIGH",
        "language": "go",
        "message": "No custom http.Transport configured — uses Go default with no keepalive or connection pool tuning",
        "suggestion": "Create an http.Client with http.Transport{DialContext with KeepAlive, MaxIdleConns, IdleConnTimeout} and pass to config.WithHTTPClient()",
        "auto_fixable": False,
    },
    "GO_CLIENT_NOT_IN_VAR_BLOCK": {
        "severity": "HIGH",
        "language": "go",
        "message": "AWS SDK client variable not found in package-level var() block",
        "suggestion": "Declare client as package-level var and initialise in init() so it is reused across invocations",
        "auto_fixable": False,
    },
    "GO_MISSING_LOG_LEVEL": {
        "severity": "MEDIUM",
        "language": "go",
        "message": "Log level not sourced from LOG_LEVEL environment variable",
        "suggestion": "Read os.Getenv(\"LOG_LEVEL\") at startup and configure slog/zerolog/zap accordingly",
        "auto_fixable": False,
    },
    "GO_MISSING_INVOCATION_LOG": {
        "severity": "LOW",
        "language": "go",
        "message": "No structured JSON log at start of handler",
        "suggestion": "Add: log.Printf(`{\"event\":\"lambda_invoked\",\"function\":\"%s\"}`, os.Getenv(\"AWS_LAMBDA_FUNCTION_NAME\"))",
        "auto_fixable": False,
    },

    # ── Java / Spring ─────────────────────────────────────────────────────────
    "JAVA_CLIENT_IN_HANDLER": {
        "severity": "CRITICAL",
        "language": "java",
        "message": "AWS SDK client instantiated inside handleRequest() — recreated on every invocation",
        "suggestion": "Declare client as private static final at class level, initialised in a static block or field initializer",
        "auto_fixable": False,
    },
    "JAVA_SDK_V1_USAGE": {
        "severity": "HIGH",
        "language": "java",
        "message": "AWS SDK for Java v1 detected (com.amazonaws.*) — v1 is in maintenance mode",
        "suggestion": "Migrate to AWS SDK for Java v2: software.amazon.awssdk.*",
        "auto_fixable": False,
    },
    "JAVA_MISSING_HTTP_CLIENT_CONFIG": {
        "severity": "HIGH",
        "language": "java",
        "message": "AWS SDK client built without explicit HTTP client configuration (connection pool, timeouts)",
        "suggestion": "Use .httpClientBuilder(ApacheHttpClient.builder().maxConnections(50).connectionTimeout(...).socketTimeout(...))",
        "auto_fixable": False,
    },
    "JAVA_NO_STATIC_CLIENT": {
        "severity": "HIGH",
        "language": "java",
        "message": "No private static final SDK client field found — client likely recreated per invocation",
        "suggestion": "Add: private static final XxxClient CLIENT = XxxClient.builder()...build();",
        "auto_fixable": False,
    },
    "JAVA_MISSING_RETRY_CONFIG": {
        "severity": "HIGH",
        "language": "java",
        "message": "SDK client built without explicit retry policy",
        "suggestion": "Add .overrideConfiguration(c -> c.retryPolicy(RetryPolicy.builder().numRetries(3).build()))",
        "auto_fixable": False,
    },
    "JAVA_SNAPSTART_NOT_CONSIDERED": {
        "severity": "MEDIUM",
        "language": "java",
        "message": "Java handler does not implement CRaC Checkpointable interface for SnapStart",
        "suggestion": "For Java 21 on Lambda, consider implementing org.crac.Resource and annotating with @RegisterReflectionForBinding for Spring or using spring-cloud-function-adapter-aws",
        "auto_fixable": False,
    },
    "JAVA_MISSING_INVOCATION_LOG": {
        "severity": "LOW",
        "language": "java",
        "message": "No structured log at the start of handleRequest()",
        "suggestion": "Add: context.getLogger().log(\"{\\\"event\\\":\\\"lambda_invoked\\\"}\");",
        "auto_fixable": False,
    },
}

API_PREFIXES = ("describe_", "get_", "list_", "put_", "update_", "delete_", "create_", "send_", "invoke_", "query", "scan")
SAFE_CALLERS = {"self", "cls", "re", "os", "sys", "json", "time", "datetime"}
BOTO_SPECIFIC_EXCEPTIONS = {"ClientError", "BotoCoreError", "EndpointConnectionError", "NoCredentialsError", "ParamValidationError"}


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Issue:
    rule_id: str
    severity: str
    line: int
    col: int
    message: str
    suggestion: str
    auto_fixable: bool

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


# ─── Python AST helpers (kept from original) ─────────────────────────────────

class ParentMapBuilder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.parents: Dict[int, ast.AST] = {}

    def generic_visit(self, node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            self.parents[id(child)] = node
            self.visit(child)


class HandlerClientCollector(ast.NodeVisitor):
    def __init__(self, handler: ast.FunctionDef) -> None:
        self.handler = handler
        self.calls: List[ast.Call] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.handler:
            for stmt in node.body:
                self.visit(stmt)
            return
        if _is_lazy_init_function(node):
            return
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        if _is_boto3_client_call(node):
            self.calls.append(node)
        self.generic_visit(node)



def _is_boto3_client_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
        return fn.value.id == "boto3" and fn.attr in ("client", "resource", "Session")
    return False



def _has_config_kwarg(call: ast.Call) -> bool:
    return any(kw.arg == "config" for kw in call.keywords)



def _has_region_literal(call: ast.Call) -> Optional[int]:
    for kw in call.keywords:
        if kw.arg == "region_name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return call.lineno
    return None



def _is_environ_get(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute):
        if fn.attr == "getenv" and isinstance(fn.value, ast.Name) and fn.value.id == "os":
            return True
        if fn.attr == "get" and isinstance(fn.value, ast.Attribute):
            return isinstance(fn.value.value, ast.Name) and fn.value.value.id == "os" and fn.value.attr == "environ"
    return False



def _collect_boto3_calls(tree: ast.Module) -> List[ast.Call]:
    return [node for node in ast.walk(tree) if _is_boto3_client_call(node)]



def _find_function(tree: ast.Module, name: str) -> Optional[ast.FunctionDef]:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None



def _is_none_check_expr(test: ast.AST) -> bool:
    if isinstance(test, ast.Compare):
        return any(isinstance(op, (ast.Is, ast.IsNot)) for op in test.ops)
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return True
    if isinstance(test, ast.BoolOp):
        return any(_is_none_check_expr(value) for value in test.values)
    return False



def _is_none_check(node: ast.If) -> bool:
    return _is_none_check_expr(node.test)



def _is_lazy_init_function(node: ast.AST) -> bool:
    if not isinstance(node, ast.FunctionDef):
        return False
    has_none_check = any(isinstance(stmt, ast.If) and _is_none_check(stmt) for stmt in ast.walk(node))
    has_boto3_call = any(_is_boto3_client_call(child) for child in ast.walk(node))
    return has_none_check and has_boto3_call



def _boto3_calls_in_scope(func: ast.FunctionDef) -> List[ast.Call]:
    collector = HandlerClientCollector(func)
    collector.visit(func)
    return collector.calls



def _has_config_import(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "botocore.config" and any(alias.name == "Config" for alias in node.names):
                return True
            if module == "botocore" and any(alias.name == "config" for alias in node.names):
                return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "botocore.config":
                    return True
    return False



def _find_setlevel_calls(tree: ast.Module) -> List[Tuple[ast.Call, int]]:
    return [
        (node, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setLevel"
    ]



def _is_json_dumps_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dumps"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
    )



def _starting_statements(handler: ast.FunctionDef, limit: int = 3) -> List[ast.stmt]:
    stmts = handler.body
    start = 0
    if stmts and isinstance(stmts[0], ast.Expr) and isinstance(stmts[0].value, ast.Constant) and isinstance(stmts[0].value.value, str):
        start = 1
    queue: List[ast.stmt] = list(stmts[start:])
    collected: List[ast.stmt] = []
    while queue and len(collected) < limit:
        stmt = queue.pop(0)
        if isinstance(stmt, ast.Try):
            queue = list(stmt.body) + queue
            continue
        collected.append(stmt)
    return collected



def _has_invocation_log(handler: ast.FunctionDef) -> bool:
    for stmt in _starting_statements(handler):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if isinstance(call.func, ast.Attribute) and call.func.attr in ("info", "debug"):
                if call.args and _is_json_dumps_call(call.args[0]):
                    return True
    return False



def _find_paginator_calls(tree: ast.Module) -> List[Tuple[ast.Call, ast.FunctionDef]]:
    results: List[Tuple[ast.Call, ast.FunctionDef]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "get_paginator":
                    results.append((child, node))
    return results



def _function_has_cache_check(func: ast.FunctionDef) -> bool:
    for node in ast.walk(func):
        if isinstance(node, ast.If):
            if _is_none_check(node):
                return True
            test = node.test
            if isinstance(test, ast.Compare) and any(isinstance(op, ast.In) for op in test.ops):
                return True
    return False



def _receiver_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None



def _is_pagination_loop(node: ast.AST) -> bool:
    if not isinstance(node, ast.While):
        return False
    is_true_loop = isinstance(node.test, ast.Constant) and node.test.value is True
    if not is_true_loop:
        return False
    has_next_token_marker = any(
        (isinstance(child, ast.Name) and child.id.lower() == "next_token")
        or (isinstance(child, ast.Constant) and child.value == "NextToken")
        for child in ast.walk(node)
    )
    return has_next_token_marker



def _is_descendant_of_nested_function(node: ast.AST, loop_node: ast.AST, parents: Dict[int, ast.AST]) -> bool:
    current = parents.get(id(node))
    while current is not None and current is not loop_node:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return True
        current = parents.get(id(current))
    return False



def _find_api_calls_in_loops(tree: ast.Module, parents: Dict[int, ast.AST]) -> List[int]:
    results: List[int] = []
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            if _is_pagination_loop(node):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    method = child.func.attr
                    if any(method.startswith(prefix) for prefix in API_PREFIXES):
                        if not _is_descendant_of_nested_function(child, node, parents):
                            receiver = _receiver_name(child.func.value)
                            if receiver not in SAFE_CALLERS and child.lineno not in seen:
                                results.append(child.lineno)
                                seen.add(child.lineno)
    return sorted(results)



def _is_specific_boto_exception(node: ast.ExceptHandler) -> bool:
    exc_type = node.type
    if exc_type is None:
        return False
    if isinstance(exc_type, ast.Name):
        return exc_type.id in BOTO_SPECIFIC_EXCEPTIONS
    if isinstance(exc_type, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id in BOTO_SPECIFIC_EXCEPTIONS for elt in exc_type.elts)
    return False



def _find_broad_except(tree: ast.Module) -> List[int]:
    results: List[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            saw_specific = False
            for handler in node.handlers:
                if _is_specific_boto_exception(handler):
                    saw_specific = True
                    continue
                if handler.type is None:
                    if not saw_specific:
                        results.append(handler.lineno)
                    continue
                if isinstance(handler.type, ast.Name) and handler.type.id == "Exception" and not saw_specific:
                    results.append(handler.lineno)
    return results


# ─── Python audit ────────────────────────────────────────────────────────────

def audit_python(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [], f"SyntaxError in {path}: {exc}"

    parent_builder = ParentMapBuilder()
    parent_builder.visit(tree)
    parents = parent_builder.parents
    issues: List[Issue] = []

    def add(rule_id: str, line: int, col: int = 0) -> None:
        rule = RULES[rule_id]
        issues.append(
            Issue(
                rule_id=rule_id,
                severity=str(rule["severity"]),
                line=line,
                col=col,
                message=str(rule["message"]),
                suggestion=str(rule["suggestion"]),
                auto_fixable=bool(rule["auto_fixable"]),
            )
        )

    handler = _find_function(tree, "lambda_handler")
    boto3_calls = _collect_boto3_calls(tree)

    if handler:
        for call in _boto3_calls_in_scope(handler):
            add("CLIENT_IN_HANDLER", call.lineno, getattr(call, "col_offset", 0))
        if not _has_invocation_log(handler):
            add("MISSING_INVOCATION_LOG", handler.lineno, 0)

    for call in boto3_calls:
        if not _has_config_kwarg(call):
            add("MISSING_BOTO_CONFIG", call.lineno, getattr(call, "col_offset", 0))
        region_line = _has_region_literal(call)
        if region_line:
            add("HARDCODED_REGION", region_line, 0)

    if boto3_calls and not _has_config_import(tree):
        add("MISSING_CONFIG_IMPORT", 1, 0)

    for call, lineno in _find_setlevel_calls(tree):
        if call.args and not _is_environ_get(call.args[0]):
            add("HARDCODED_LOG_LEVEL", lineno, 0)

    for call, func in _find_paginator_calls(tree):
        if not _function_has_cache_check(func):
            add("UNCACHED_PAGINATOR", call.lineno, 0)

    for lineno in _find_api_calls_in_loops(tree, parents):
        add("API_CALL_IN_LOOP", lineno, 0)

    for lineno in _find_broad_except(tree):
        add("BROAD_EXCEPT", lineno, 0)

    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return issues, None


# ─── Node.js / TypeScript audit (regex-based) ────────────────────────────────

JS_HANDLER_RE = re.compile(
    r"""(?:exports\s*\.\s*handler\s*=\s*(async\s*)?|module\.exports(?:\.handler)?\s*=\s*(async\s*)?|export\s+const\s+handler\s*=\s*(async\s*)?|export\s+async\s+function\s+handler\s*\()"""
)
JS_NEW_CLIENT_RE = re.compile(r"""\bnew\s+(?:AWS\.\w+|[A-Z][A-Za-z0-9_]*Client)\s*\(""")


def _find_js_handlers(lines: List[str]) -> List[Tuple[int, int, bool]]:
    handlers: List[Tuple[int, int, bool]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = JS_HANDLER_RE.search(line)
        if not match:
            i += 1
            continue

        is_async = "async" in match.group(0)
        start = i
        end = i
        brace_depth = line.count("{") - line.count("}")
        saw_brace = "{" in line

        if saw_brace and brace_depth <= 0:
            handlers.append((start + 1, end + 1, is_async))
            i += 1
            continue

        j = i + 1
        while j < len(lines):
            current = lines[j]
            if "{" in current:
                saw_brace = True
            brace_depth += current.count("{") - current.count("}")
            end = j
            if saw_brace and brace_depth <= 0:
                break
            j += 1

        handlers.append((start + 1, end + 1, is_async))
        i = end + 1
    return handlers



def audit_nodejs(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    issues: List[Issue] = []
    lines = source.splitlines()
    handlers = _find_js_handlers(lines)

    def add(rule_id: str, line: int) -> None:
        rule = RULES[rule_id]
        issues.append(Issue(
            rule_id=rule_id,
            severity=str(rule["severity"]),
            line=line,
            col=0,
            message=str(rule["message"]),
            suggestion=str(rule["suggestion"]),
            auto_fixable=bool(rule["auto_fixable"]),
        ))

    sdk_v2_re = re.compile(r"""(?:require\s*\(\s*['"]aws-sdk['"]\s*\)|from\s+['"]aws-sdk['"]|import\s+AWS\s+from\s+['"]aws-sdk['"])""")
    first_client_line: Optional[int] = None
    seen_rule_lines = set()

    for i, line in enumerate(lines, 1):
        if sdk_v2_re.search(line):
            add("JS_SDK_V2_USAGE", i)
            add("JS_FULL_SDK_IMPORT", i)
        if first_client_line is None and JS_NEW_CLIENT_RE.search(line):
            first_client_line = i

    for start, end, is_async in handlers:
        handler_lines = lines[start - 1:end]
        handler_text = "\n".join(handler_lines)
        for line_no, line in enumerate(handler_lines, start):
            if JS_NEW_CLIENT_RE.search(line) and ("JS_CLIENT_IN_HANDLER", line_no) not in seen_rule_lines:
                add("JS_CLIENT_IN_HANDLER", line_no)
                seen_rule_lines.add(("JS_CLIENT_IN_HANDLER", line_no))

        intro = "\n".join(handler_lines[:5])
        if not re.search(r"""lambda_invoked|lambdaInvoked|JSON\.stringify\s*\(\s*\{[^\n]*event\s*:\s*['\"]lambda_invoked['\"]|getLogger\(""", intro):
            add("JS_MISSING_INVOCATION_LOG", start)

        if is_async and not re.search(r"""\btry\s*\{""", handler_text):
            add("JS_UNHANDLED_ASYNC", start)

    if first_client_line is None and re.search(r"""@aws-sdk/client-|aws-sdk""", source):
        first_client_line = 1

    if first_client_line is not None and not re.search(r"""keepAlive\s*:\s*true|NodeHttpHandler|httpsAgent|AWS_NODEJS_CONNECTION_REUSE_ENABLED\s*=\s*['\"]?1['\"]?""", source):
        add("JS_MISSING_HTTP_KEEPALIVE", first_client_line)

    if first_client_line is not None and not re.search(r"""maxAttempts\s*:|maxRetries\s*:""", source):
        add("JS_MISSING_RETRY_CONFIG", first_client_line)

    region_re = re.compile(r"""region\s*:\s*['"][a-z]{2}-[a-z]+-\d['"]""")
    for i, line in enumerate(lines, 1):
        if region_re.search(line):
            add("JS_HARDCODED_REGION", i)

    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return issues, None


# ─── Go audit (regex-based) ──────────────────────────────────────────────────

def audit_go(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    issues: List[Issue] = []
    lines = source.splitlines()

    def add(rule_id: str, line: int) -> None:
        rule = RULES[rule_id]
        issues.append(Issue(
            rule_id=rule_id,
            severity=str(rule["severity"]),
            line=line,
            col=0,
            message=str(rule["message"]),
            suggestion=str(rule["suggestion"]),
            auto_fixable=bool(rule["auto_fixable"]),
        ))

    if re.search(r'"github\.com/aws/aws-sdk-go(?:"|/)', source) and "aws-sdk-go-v2" not in source:
        add("GO_SDK_V1_USAGE", 1)

    handler_func_re = re.compile(r"""^func\s+(?!init\s*\()(\w+)\s*\(""", re.MULTILINE)
    for match in handler_func_re.finditer(source):
        func_name = match.group(1)
        if func_name == "main":
            continue
        start_line = source[:match.start()].count("\n") + 1
        for idx in range(start_line - 1, min(start_line + 100, len(lines))):
            # SDK v2: config.LoadDefaultConfig / NewXxxFromConfig
            # SDK v1: svc := s3.New(sess) / dynamodb.New(sess) etc.
            if re.search(
                r"""\bconfig\.LoadDefaultConfig\b|\bNew\w+FromConfig\b"""
                r"""|\b\w+\.New\s*\(\s*sess""",
                lines[idx],
            ):
                add("GO_CLIENT_IN_HANDLER", idx + 1)
                break

    has_any_client = "aws-sdk-go-v2" in source
    has_custom_transport = bool(re.search(r"""http\.Transport|http\.Client\s*\{""", source))
    if has_any_client and not has_custom_transport:
        add("GO_MISSING_HTTP_TRANSPORT", 1)

    has_var_block_client = bool(re.search(r"""^var\s*\([\s\S]*?\*\w+\.Client|^var\s+\w+\s+\*\w+\.Client""", source, re.MULTILINE))
    has_init_func = bool(re.search(r"""^func\s+init\s*\(\s*\)""", source, re.MULTILINE))
    if has_any_client and not has_var_block_client and not has_init_func:
        add("GO_CLIENT_NOT_IN_VAR_BLOCK", 1)

    has_log_level = bool(re.search(r"""Getenv\s*\(\s*"LOG_LEVEL"\s*\)""", source))
    has_logging = bool(re.search(r"""\blog\.|\bslog\.|zerolog\.|zap\.""", source))
    if has_logging and not has_log_level:
        add("GO_MISSING_LOG_LEVEL", 1)

    has_invocation_log = bool(re.search(r"""lambda_invoked|lambdaInvoked""", source))
    has_lambda_start = bool(re.search(r"""lambda\.Start""", source))
    if has_lambda_start and not has_invocation_log:
        add("GO_MISSING_INVOCATION_LOG", 1)

    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return issues, None


# ─── Java audit (regex-based) ────────────────────────────────────────────────

def audit_java(path: Path, source: str) -> Tuple[List[Issue], Optional[str]]:
    issues: List[Issue] = []
    lines = source.splitlines()

    def add(rule_id: str, line: int) -> None:
        rule = RULES[rule_id]
        issues.append(Issue(
            rule_id=rule_id,
            severity=str(rule["severity"]),
            line=line,
            col=0,
            message=str(rule["message"]),
            suggestion=str(rule["suggestion"]),
            auto_fixable=bool(rule["auto_fixable"]),
        ))

    if re.search(r"""com\.amazonaws(?:\.services|\.)""", source):
        add("JAVA_SDK_V1_USAGE", 1)

    handle_re = re.compile(r"""public\s+[\w<>,\s\[\]]+\s+handleRequest\s*\(""")
    new_client_re = re.compile(r"""\w+Client\.builder\(\)""")
    in_handle = False
    brace_depth = 0
    for i, line in enumerate(lines, 1):
        if not in_handle and handle_re.search(line):
            in_handle = True
            brace_depth = line.count("{") - line.count("}")
            continue
        if in_handle:
            brace_depth += line.count("{") - line.count("}")
            if new_client_re.search(line):
                add("JAVA_CLIENT_IN_HANDLER", i)
            if brace_depth <= 0:
                in_handle = False

    has_static_client = bool(re.search(r"""private\s+static\s+(?:final\s+)?\w+Client\s+\w+""", source))
    has_any_client_usage = bool(re.search(r"""\w+Client\.builder\(\)""", source))
    if has_any_client_usage and not has_static_client:
        add("JAVA_NO_STATIC_CLIENT", 1)

    has_http_client_config = bool(re.search(r"""ApacheHttpClient|UrlConnectionHttpClient|NettyNioAsync|httpClientBuilder""", source))
    if has_any_client_usage and not has_http_client_config:
        add("JAVA_MISSING_HTTP_CLIENT_CONFIG", 1)

    has_retry = bool(re.search(r"""RetryPolicy|retryPolicy|numRetries|maxAttempts""", source))
    if has_any_client_usage and not has_retry:
        add("JAVA_MISSING_RETRY_CONFIG", 1)

    implements_handler = bool(re.search(r"""implements\s+RequestHandler""", source))
    implements_crac = bool(re.search(r"""org\.crac|implements[^\n]*Resource""", source))
    if implements_handler and not implements_crac:
        add("JAVA_SNAPSTART_NOT_CONSIDERED", 1)

    has_invocation_log = bool(re.search(r"""lambda_invoked|lambdaInvoked|getLogger\(\)\.log""", source))
    if implements_handler and not has_invocation_log:
        add("JAVA_MISSING_INVOCATION_LOG", 1)

    issues.sort(key=lambda issue: (SEVERITY_ORDER.get(issue.severity, 9), issue.line, issue.col))
    return issues, None


# ─── Language dispatch ────────────────────────────────────────────────────────

def detect_language(path: Path) -> Optional[str]:
    ext = path.suffix.lower()
    if ext == ".py":
        return "python"
    if ext in (".js", ".mjs", ".cjs", ".ts"):
        return "nodejs"
    if ext == ".go":
        return "go"
    if ext == ".java":
        return "java"
    return None



def audit_file(path: Path) -> Tuple[List[Issue], Optional[str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], f"File not found: {path}"
    except OSError as exc:
        return [], f"Cannot read file: {exc}"

    language = detect_language(path)
    if language is None:
        return [], f"Unsupported file type '{path.suffix}' — supported: .py .js .mjs .cjs .ts .go .java"

    if language == "python":
        return audit_python(path, source)
    if language == "nodejs":
        return audit_nodejs(path, source)
    if language == "go":
        return audit_go(path, source)
    if language == "java":
        return audit_java(path, source)
    return [], f"No auditor for language: {language}"


# ─── Output formatters ────────────────────────────────────────────────────────

SEVERITY_COLORS = {
    "CRITICAL": "\033[91m",
    "HIGH": "\033[93m",
    "MEDIUM": "\033[94m",
    "LOW": "\033[96m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
SUCCESS = "\033[92m"



def _color(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{RESET}"



def print_report(path: Path, issues: List[Issue], error: Optional[str], summary_only: bool = False) -> None:
    lang = detect_language(path) or "unknown"
    print(f"\n{BOLD}{path}{RESET}  [{lang}]")
    if error:
        print(f"  ✗ {_color('ERROR', SEVERITY_COLORS['CRITICAL'])}: {error}")
        return
    if not issues:
        print(f"  {_color('✓ No issues found', SUCCESS)}")
        return
    if summary_only:
        by_severity: Dict[str, int] = {}
        for issue in issues:
            by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        parts = [
            f"{_color(severity, SEVERITY_COLORS.get(severity, ''))}: {count}"
            for severity, count in sorted(by_severity.items(), key=lambda item: SEVERITY_ORDER.get(item[0], 9))
        ]
        print(f"  {', '.join(parts)}  ({len(issues)} total)")
        return
    for issue in issues:
        fix_str = " [auto-fixable]" if issue.auto_fixable else ""
        print(f"  Line {issue.line:4d}  {_color(f'[{issue.severity}]', SEVERITY_COLORS.get(issue.severity, ''))} {issue.rule_id}{fix_str}")
        print(f"           {issue.message}")
        print(f"           → {issue.suggestion}")



def print_json_report(results: Dict[str, object]) -> None:
    print(json.dumps(results, indent=2))



def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    output_json = "--json" in args
    summary_only = "--summary" in args
    file_args = [arg for arg in args if not arg.startswith("--")]
    if not file_args:
        print("Error: no input files specified", file=sys.stderr)
        return 2

    all_results: Dict[str, Dict[str, object]] = {}
    exit_code = 0

    for file_arg in file_args:
        path = Path(file_arg)
        issues, error = audit_file(path)
        all_results[str(path)] = {
            "language": detect_language(path),
            "issues": [issue.as_dict() for issue in issues],
            "error": error,
            "counts": {
                "CRITICAL": sum(1 for issue in issues if issue.severity == "CRITICAL"),
                "HIGH": sum(1 for issue in issues if issue.severity == "HIGH"),
                "MEDIUM": sum(1 for issue in issues if issue.severity == "MEDIUM"),
                "LOW": sum(1 for issue in issues if issue.severity == "LOW"),
            },
        }
        if error:
            exit_code = 2
        elif any(issue.severity in ("CRITICAL", "HIGH") for issue in issues):
            exit_code = max(exit_code, 1)
        if not output_json:
            print_report(path, issues, error, summary_only)

    if output_json:
        print_json_report(all_results)
    else:
        total_critical = sum(result["counts"]["CRITICAL"] for result in all_results.values())
        total_high = sum(result["counts"]["HIGH"] for result in all_results.values())
        total_medium = sum(result["counts"]["MEDIUM"] for result in all_results.values())
        total_low = sum(result["counts"]["LOW"] for result in all_results.values())
        print(f"\n{'─' * 60}")
        print(
            f"Total: {_color(str(total_critical) + ' CRITICAL', SEVERITY_COLORS['CRITICAL'])}  "
            f"{_color(str(total_high) + ' HIGH', SEVERITY_COLORS['HIGH'])}  "
            f"{_color(str(total_medium) + ' MEDIUM', SEVERITY_COLORS['MEDIUM'])}  "
            f"{_color(str(total_low) + ' LOW', SEVERITY_COLORS['LOW'])}"
        )
        if exit_code == 0:
            print(_color("✓ All files pass CRITICAL/HIGH checks", SUCCESS))
        else:
            print(_color("✗ Fix CRITICAL/HIGH issues before deployment", SEVERITY_COLORS["CRITICAL"]))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
