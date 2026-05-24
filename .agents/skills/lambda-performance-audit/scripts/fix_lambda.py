#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
AWS Lambda Performance Auto-Fixer
Automatically fixes auto-fixable performance issues in Lambda Python handlers.

Rules fixed:
  MISSING_CONFIG_IMPORT  — adds: from botocore.config import Config
  MISSING_BOTO_CONFIG    — adds _BOTO_CONFIG and config= to boto3 calls
  HARDCODED_LOG_LEVEL    — replaces hardcoded setLevel with env var pattern
  MISSING_INVOCATION_LOG — adds structured JSON log at handler start

Usage:
  python3 fix_lambda.py <file.py> [--dry-run] [--backup]

Flags:
  --dry-run   Print planned changes without writing files
  --backup    Save original as <file.py>.bak before modifying
"""

import ast
import re
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple

BOTO_CONFIG_BLOCK = """
_BOTO_CONFIG = Config(
    tcp_keepalive=True,
    max_pool_connections=10,
    retries={"mode": "standard", "max_attempts": 3},
    connect_timeout=5,
    read_timeout=15,
)
"""


class ImportTracker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.modules = set()
        self.import_lines: List[int] = []
        self.boto3_lines: List[int] = []
        self.has_config_import = False

    def visit_Import(self, node: ast.Import) -> None:
        self.import_lines.append(node.lineno)
        for alias in node.names:
            top_level = alias.name.split(".", 1)[0]
            self.modules.add(top_level)
            if alias.name == "boto3":
                self.boto3_lines.append(node.lineno)
            if alias.name == "botocore.config":
                self.has_config_import = True

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.import_lines.append(node.lineno)
        module = node.module or ""
        if module:
            self.modules.add(module.split(".", 1)[0])
        if module.startswith("boto"):
            self.boto3_lines.append(node.lineno)
        if module == "botocore.config" and any(alias.name == "Config" for alias in node.names):
            self.has_config_import = True
        if module == "botocore" and any(alias.name == "config" for alias in node.names):
            self.has_config_import = True


class HandlerFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.handler: Optional[ast.FunctionDef] = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self.handler is None and node.name == "lambda_handler":
            self.handler = node


def find_logger_name(source: str) -> str:
    if "LOGGER" in source:
        return "LOGGER"
    return "logger"


def _ensure_import(lines: List[str], tree: ast.Module, module_name: str, changes: List[str]) -> List[str]:
    tracker = ImportTracker()
    tracker.visit(tree)
    if module_name in tracker.modules:
        return lines
    insert_after = max(tracker.import_lines, default=0)
    lines.insert(insert_after, f"import {module_name}\n")
    changes.append(f"Added: import {module_name}")
    return lines


def _parse(source: str, path: Path) -> ast.Module:
    return ast.parse(source, filename=str(path))


def fix_source(source: str, path: Path) -> Tuple[str, List[str]]:
    changes: List[str] = []
    lines = source.splitlines(keepends=True)

    try:
        tree = _parse(source, path)
    except SyntaxError as exc:
        return source, [f"ERROR: SyntaxError — cannot parse: {exc}"]

    logger_name = find_logger_name(source)
    tracker = ImportTracker()
    tracker.visit(tree)

    if not tracker.has_config_import and tracker.boto3_lines:
        insert_after = max(tracker.boto3_lines)
        lines.insert(insert_after, "from botocore.config import Config\n")
        changes.append(f"Added: from botocore.config import Config (after line {insert_after})")
        source = "".join(lines)
        tree = _parse(source, path)
        tracker = ImportTracker()
        tracker.visit(tree)
        lines = source.splitlines(keepends=True)

    has_any_boto3_call = bool(re.search(r"boto3\.(client|resource)\s*\(", source))
    has_boto_config_var = "_BOTO_CONFIG" in source or "BOTO_CONFIG" in source
    if has_any_boto3_call and not has_boto_config_var:
        last_import_line = max(tracker.import_lines, default=0)
        if last_import_line:
            lines.insert(last_import_line, BOTO_CONFIG_BLOCK + "\n")
            changes.append(f"Added _BOTO_CONFIG = Config(...) block after imports (line {last_import_line})")
            source = "".join(lines)
            tree = _parse(source, path)
            tracker = ImportTracker()
            tracker.visit(tree)
            lines = source.splitlines(keepends=True)

    def add_config_to_call(match: re.Match) -> str:
        full_match = match.group(0)
        if "config=" in full_match or "_BOTO_CONFIG" in full_match:
            return full_match
        idx = full_match.rfind(")")
        return full_match[:idx] + ", config=_BOTO_CONFIG" + full_match[idx:]

    pattern = r"boto3\.(client|resource)\s*\([^)]*\)"
    new_source = re.sub(pattern, add_config_to_call, source)
    if new_source != source:
        changes.append("Added config=_BOTO_CONFIG to boto3.client/resource() calls")
        source = new_source
        tree = _parse(source, path)
        tracker = ImportTracker()
        tracker.visit(tree)
        lines = source.splitlines(keepends=True)

    setlevel_pattern = re.compile(
        r'((?:logger|LOGGER|logging)\s*\.?\s*(?:getLogger\([^)]*\)\s*\.)?setLevel\s*\()'
        r'(logging\.(?:INFO|DEBUG|WARNING|ERROR|CRITICAL)|["\'](?:INFO|DEBUG|WARNING|ERROR|CRITICAL)["\'])'
        r'(\s*\))'
    )
    new_source = setlevel_pattern.sub(r'\1os.environ.get("LOG_LEVEL", "INFO")\3', source)
    if new_source != source:
        source = new_source
        tree = _parse(source, path)
        lines = source.splitlines(keepends=True)
        lines = _ensure_import(lines, tree, "os", changes)
        source = "".join(lines)
        tree = _parse(source, path)
        changes.append("Fixed: hardcoded log level → os.environ.get('LOG_LEVEL', 'INFO')")
        lines = source.splitlines(keepends=True)

    if "lambda_invoked" not in source:
        finder = HandlerFinder()
        finder.visit(tree)
        handler = finder.handler
        if handler and handler.body:
            lines = source.splitlines(keepends=True)
            first_stmt = handler.body[0]
            if isinstance(first_stmt, ast.Expr) and isinstance(first_stmt.value, ast.Constant) and isinstance(first_stmt.value.value, str):
                insert_at = first_stmt.end_lineno or first_stmt.lineno
                if insert_at is None:
                    insert_at = first_stmt.lineno
                anchor_stmt = handler.body[1] if len(handler.body) > 1 else first_stmt
            else:
                insert_at = first_stmt.lineno - 1
                anchor_stmt = first_stmt
            indent_text = lines[anchor_stmt.lineno - 1]
            indent = len(indent_text) - len(indent_text.lstrip())
            log_line = f"{' ' * indent}{logger_name}.info(json.dumps({{'event': 'lambda_invoked', 'function': context.function_name}}))\n"
            lines.insert(insert_at, log_line)
            source = "".join(lines)
            tree = _parse(source, path)
            lines = source.splitlines(keepends=True)
            lines = _ensure_import(lines, tree, "json", changes)
            source = "".join(lines)
            changes.append("Added structured invocation log at start of lambda_handler")

    return source, changes


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    dry_run = "--dry-run" in args
    backup = "--backup" in args
    file_args = [arg for arg in args if not arg.startswith("--")]
    if not file_args:
        print("Error: no input files specified", file=sys.stderr)
        return 1

    overall_exit = 0
    for file_arg in file_args:
        path = Path(file_arg)
        if not path.exists():
            print(f"Error: {path} not found", file=sys.stderr)
            overall_exit = 1
            continue

        source = path.read_text(encoding="utf-8")
        new_source, changes = fix_source(source, path)
        if not changes:
            print(f"{path}: no auto-fixable issues found")
            continue

        print(f"\n{path}:")
        for change in changes:
            print(f"  ✓ {change}")

        if dry_run:
            print("  [dry-run: no files written]")
            continue

        if backup:
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
            print(f"  Backup saved: {backup_path}")

        path.write_text(new_source, encoding="utf-8")
        print(f"  File updated: {path}")

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
