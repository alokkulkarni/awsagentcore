#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
AWS Lambda Performance Auditor
Validates Lambda Python handlers against AWS best practices.

Usage:
  python3 audit_lambda.py <file.py> [<file2.py> ...]
  python3 audit_lambda.py --json <file.py>       # JSON output
  python3 audit_lambda.py --summary <file.py>    # Summary only

Exit codes:
  0 — no CRITICAL or HIGH issues
  1 — one or more CRITICAL/HIGH issues found
  2 — file not found or parse error
"""

import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RULES: Dict[str, Dict[str, object]] = {
    "CLIENT_IN_HANDLER": {
        "severity": "CRITICAL",
        "message": "boto3.client()/resource() called inside lambda_handler — recreated on every cold AND warm invocation",
        "suggestion": "Move to module level or use a lazy-init pattern (_X = None; def _get_x(): global _X; if _X is None: _X = boto3.client(...))",
        "auto_fixable": False,
    },
    "MISSING_BOTO_CONFIG": {
        "severity": "HIGH",
        "message": "boto3 client/resource created without botocore.config.Config",
        "suggestion": "Add: config=Config(tcp_keepalive=True, max_pool_connections=10, retries={'mode':'standard','max_attempts':3}, connect_timeout=5, read_timeout=15)",
        "auto_fixable": True,
    },
    "MISSING_CONFIG_IMPORT": {
        "severity": "HIGH",
        "message": "boto3 is used but 'from botocore.config import Config' is not imported",
        "suggestion": "Add at top: from botocore.config import Config",
        "auto_fixable": True,
    },
    "HARDCODED_LOG_LEVEL": {
        "severity": "MEDIUM",
        "message": "Logger level is hardcoded — cannot be changed at runtime via LOG_LEVEL env var",
        "suggestion": "Replace with: logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))",
        "auto_fixable": True,
    },
    "MISSING_INVOCATION_LOG": {
        "severity": "LOW",
        "message": "No structured JSON log at the start of lambda_handler",
        "suggestion": "Add as first statement: logger.info(json.dumps({'event': 'lambda_invoked', 'function': context.function_name}))",
        "auto_fixable": True,
    },
    "UNCACHED_PAGINATOR": {
        "severity": "HIGH",
        "message": "Paginator called without TTL cache — list_* API call repeated on every invocation",
        "suggestion": "Cache results at module level with a TTL dict: _CACHE = {}; use time.time() for expiry (300s recommended)",
        "auto_fixable": False,
    },
    "API_CALL_IN_LOOP": {
        "severity": "HIGH",
        "message": "AWS API call inside a loop — N+1 pattern increases latency and costs",
        "suggestion": "Batch with list comprehension first, then use batch APIs (batch_get_item, etc.) or cache results",
        "auto_fixable": False,
    },
    "HARDCODED_REGION": {
        "severity": "MEDIUM",
        "message": "Hardcoded AWS region in boto3 call",
        "suggestion": "Remove region_name= (Lambda sets AWS_REGION automatically) or use os.environ.get('AWS_REGION')",
        "auto_fixable": False,
    },
    "BROAD_EXCEPT": {
        "severity": "LOW",
        "message": "Broad except Exception catches all exceptions without specific boto3 error handling",
        "suggestion": "Catch (ClientError, BotoCoreError) specifically before the broad except. Use logger.exception() to auto-include stack trace.",
        "auto_fixable": False,
    },
}

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
API_PREFIXES = (
    "describe_",
    "get_",
    "list_",
    "put_",
    "update_",
    "delete_",
    "create_",
    "send_",
    "invoke_",
    "query",
    "scan",
)
SAFE_CALLERS = {"self", "cls", "re", "os", "sys", "json", "time", "datetime"}
BOTO_SPECIFIC_EXCEPTIONS = {"ClientError", "BotoCoreError", "EndpointConnectionError", "NoCredentialsError", "ParamValidationError"}


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
        return fn.value.id == "boto3" and fn.attr in ("client", "resource")
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
    return [(node, node.lineno) for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "setLevel"]


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


def _is_descendant_of_nested_function(node: ast.AST, loop_node: ast.AST, parents: Dict[int, ast.AST]) -> bool:
    current = parents.get(id(node))
    while current is not None and current is not loop_node:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return True
        current = parents.get(id(current))
    return False


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


def audit_file(path: Path) -> Tuple[List[Issue], Optional[str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], f"File not found: {path}"
    except OSError as exc:
        return [], f"Cannot read file: {exc}"

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
    print(f"\n{BOLD}{path}{RESET}")
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
