#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
AWS Lambda Security Auto-Fixer
Automatically fixes auto-fixable security issues in Lambda Python handlers.

Rules fixed:
  PY_SSRF_URLOPEN      — adds HTTPS urlparse validation before urlopen calls
  PY_MISSING_TLS_VERIFY — removes verify=False from requests calls
  PY_SILENT_EXCEPT     — replaces except: pass with debug logging

Usage:
  python3 fix_security.py <file.py> [--dry-run] [--backup]

Flags:
  --dry-run   Print diffs without writing files
  --backup    Save original as <file.py>.bak before modifying
"""

import ast
import difflib
import re
import shutil
import sys
from pathlib import Path
from typing import List, Optional, Tuple


class ImportTracker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.import_lines: List[int] = []
        self.has_logging = False
        self.has_urllib_parse = False

    def visit_Import(self, node: ast.Import) -> None:
        self.import_lines.append(node.lineno)
        for alias in node.names:
            if alias.name == "logging":
                self.has_logging = True
            if alias.name == "urllib.parse":
                self.has_urllib_parse = True

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.import_lines.append(node.lineno)
        if (node.module or "") == "urllib":
            if any(alias.name == "parse" for alias in node.names):
                self.has_urllib_parse = True
        if (node.module or "") == "urllib.parse":
            self.has_urllib_parse = True


class UrlopenCollector(ast.NodeVisitor):
    def __init__(self, source: str) -> None:
        self.source = source
        self.calls: List[Tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        fn_name = _full_name(node.func)
        if fn_name in {"urllib.request.urlopen", "urlopen"} and node.args:
            expr = ast.get_source_segment(self.source, node.args[0]) or "url"
            self.calls.append((node.lineno, expr))
        self.generic_visit(node)


class SilentExceptCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.pass_lines: List[int] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self.pass_lines.append(node.body[0].lineno)
        self.generic_visit(node)


def _full_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _full_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _parse(source: str, path: Path) -> ast.Module:
    return ast.parse(source, filename=str(path))


def find_logger_expr(source: str) -> str:
    if "LOGGER" in source:
        return "LOGGER"
    if "logger" in source:
        return "logger"
    return "logging.getLogger(__name__)"


def _ensure_import(lines: List[str], tracker: ImportTracker, statement: str, changes: List[str]) -> List[str]:
    insert_after = max(tracker.import_lines, default=0)
    lines.insert(insert_after, statement)
    changes.append(f"Added: {statement.strip()}")
    return lines


def _has_recent_urlparse(lines: List[str], lineno: int) -> bool:
    snippet = "\n".join(lines[max(0, lineno - 6):lineno - 1]).lower()
    return "urlparse(" in snippet and ".scheme" in snippet


def fix_source(source: str, path: Path) -> Tuple[str, List[str]]:
    changes: List[str] = []
    try:
        tree = _parse(source, path)
    except SyntaxError as exc:
        return source, [f"ERROR: SyntaxError — cannot parse: {exc}"]

    tracker = ImportTracker()
    tracker.visit(tree)
    lines = source.splitlines(keepends=True)
    logger_expr = find_logger_expr(source)

    original_source = source
    source = re.sub(r",\s*verify=False(?=\s*[,)])", "", source)
    source = re.sub(r"verify=False\s*,\s*", "", source)
    if source != original_source:
        changes.append("Removed verify=False from requests calls")
        lines = source.splitlines(keepends=True)

    tree = _parse(source, path)
    tracker = ImportTracker()
    tracker.visit(tree)
    collector = UrlopenCollector(source)
    collector.visit(tree)
    inserted = 0
    if collector.calls and not tracker.has_urllib_parse:
        lines = _ensure_import(lines, tracker, "import urllib.parse\n", changes)
        source = "".join(lines)
        tree = _parse(source, path)
        tracker = ImportTracker()
        tracker.visit(tree)
        collector = UrlopenCollector(source)
        collector.visit(tree)
        lines = source.splitlines(keepends=True)
    for lineno, expr in collector.calls:
        adjusted_line = lineno + inserted
        if _has_recent_urlparse(lines, adjusted_line):
            continue
        indent = len(lines[adjusted_line - 1]) - len(lines[adjusted_line - 1].lstrip())
        prefix = " " * indent
        block = [
            f"{prefix}_parsed = urllib.parse.urlparse({expr})\n",
            f"{prefix}if _parsed.scheme != \"https\" or not _parsed.netloc:\n",
            f"{prefix}    raise ValueError(f\"URL must be a full HTTPS URL, got: {{{expr}!r}}\")\n",
        ]
        lines[adjusted_line - 1:adjusted_line - 1] = block
        inserted += len(block)
        changes.append(f"Added HTTPS urlparse validation before urlopen() at line {lineno}")

    source = "".join(lines)
    tree = _parse(source, path)
    tracker = ImportTracker()
    tracker.visit(tree)
    lines = source.splitlines(keepends=True)
    silent = SilentExceptCollector()
    silent.visit(tree)
    if silent.pass_lines and "logging.getLogger(__name__)" in logger_expr and not tracker.has_logging:
        lines = _ensure_import(lines, tracker, "import logging\n", changes)
        source = "".join(lines)
        tree = _parse(source, path)
        tracker = ImportTracker()
        tracker.visit(tree)
        lines = source.splitlines(keepends=True)
        silent = SilentExceptCollector()
        silent.visit(tree)

    for lineno in silent.pass_lines:
        indent = len(lines[lineno - 1]) - len(lines[lineno - 1].lstrip())
        lines[lineno - 1] = f"{' ' * indent}{logger_expr}.debug('Suppressed exception', exc_info=True)\n"
        changes.append(f"Replaced bare except: pass at line {lineno} with debug logging")

    return "".join(lines), changes


def fix_file(path: Path) -> Tuple[str, List[str]]:
    source = path.read_text(encoding="utf-8")
    return fix_source(source, path)


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

        original = path.read_text(encoding="utf-8")
        new_source, changes = fix_file(path)
        if not changes:
            print(f"{path}: no auto-fixable issues found")
            continue

        print(f"\n{path}:")
        for change in changes:
            print(f"  ✓ {change}")

        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            new_source.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        ))
        if dry_run:
            print(diff.rstrip() or "  [dry-run: no textual diff]")
            print("  [dry-run: no files written]")
            continue

        if backup:
            backup_path = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup_path)
            print(f"  Backup saved: {backup_path}")

        path.write_text(new_source, encoding="utf-8")
        print(diff.rstrip() or "  [no textual diff]")
        print(f"  File updated: {path}")

    return overall_exit


if __name__ == "__main__":
    sys.exit(main())
