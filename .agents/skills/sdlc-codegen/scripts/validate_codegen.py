#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate generated scaffold outputs against the codegen rule set."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
RULES = {
    "CDG-001": {"severity": "CRITICAL", "message": "Generated files exist (at least one new file created)"},
    "CDG-002": {"severity": "HIGH", "message": "Generated code compiles/parses (language-appropriate check)"},
    "CDG-003": {"severity": "HIGH", "message": "No hardcoded credentials or secrets in generated code"},
    "CDG-004": {"severity": "HIGH", "message": "Error handling present in generated code"},
    "CDG-005": {"severity": "MEDIUM", "message": "Generated code follows project naming conventions"},
    "CDG-006": {"severity": "MEDIUM", "message": "Tests generated alongside source files"},
    "CDG-007": {"severity": "MEDIUM", "message": "Generated code has at least minimal comments/docstrings"},
    "CDG-008": {"severity": "LOW", "message": "README or CHANGELOG updated"},
    "CDG-009": {"severity": "LOW", "message": "No TODO/FIXME left unresolved in critical paths"},
    "CDG-010": {"severity": "LOW", "message": "Dependency manifest updated if new deps added"},
}
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
]
ERROR_PATTERNS = [r"\btry\b", r"\bcatch\b", r"\bexcept\b", r"if err != nil", r"internalServerError", r"Result<", r"RuntimeError", r"HTTPException"]
COMMENT_PATTERNS = [r'"""', r"/\*\*", r"//", r"# "]
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".go", ".java", ".rs"}
TEST_HINTS = ("test", "tests", "spec")

def add_issue(issues: List[Tuple[str, str]], rule_id: str) -> None:
    issues.append((rule_id, RULES[rule_id]["message"]))

def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")

def load_summary(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

def is_test_file(path: Path) -> bool:
    lowered = path.as_posix().lower()
    return any(token in lowered for token in TEST_HINTS) or path.name.endswith("_test.go")

def naming_ok(path: Path) -> bool:
    name = path.name
    if path.suffix == ".py":
        return bool(re.fullmatch(r"(?:test_)?[a-z0-9_]+\.py", name))
    if path.suffix in {".ts", ".js"}:
        return bool(re.fullmatch(r"[a-z0-9._-]+\.(ts|js)", name))
    if path.suffix == ".tsx":
        return bool(re.fullmatch(r"(?:[A-Z][A-Za-z0-9]+|[a-z0-9._-]+)\.tsx", name))
    if path.suffix == ".go":
        return bool(re.fullmatch(r"[a-z0-9_]+\.go", name))
    if path.suffix == ".java":
        return bool(re.fullmatch(r"[A-Z][A-Za-z0-9]+\.java", name))
    if path.suffix == ".rs":
        return bool(re.fullmatch(r"[a-z0-9_]+\.rs", name))
    return True

def run_command(command: List[str], cwd: Path) -> bool:
    try:
        subprocess.run(command, cwd=str(cwd), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def parse_check(project_root: Path, files: List[Path]) -> bool:
    py_files = [str(path) for path in files if path.suffix == ".py"]
    if py_files and not run_command([sys.executable, "-m", "py_compile", *py_files], project_root):
        return False
    js_files = [path for path in files if path.suffix == ".js"]
    if js_files and shutil.which("node"):
        for path in js_files:
            if not run_command(["node", "--check", str(path)], project_root):
                return False
    ts_files = [path for path in files if path.suffix in {".ts", ".tsx"}]
    if ts_files and shutil.which("tsc") and not run_command(["tsc", "--noEmit", *[str(path) for path in ts_files]], project_root):
        return False
    go_files = [path for path in files if path.suffix == ".go"]
    if go_files and (project_root / "go.mod").exists() and shutil.which("go") and not run_command(["go", "test", "./..."], project_root):
        return False
    java_files = [path for path in files if path.suffix == ".java"]
    if java_files:
        if (project_root / "pom.xml").exists() and shutil.which("mvn") and not run_command(["mvn", "-q", "-DskipTests", "compile"], project_root):
            return False
        if not (project_root / "pom.xml").exists() and shutil.which("javac") and not run_command(["javac", *[str(path) for path in java_files]], project_root):
            return False
    rust_files = [path for path in files if path.suffix == ".rs"]
    if rust_files and (project_root / "Cargo.toml").exists() and shutil.which("cargo") and not run_command(["cargo", "check"], project_root):
        return False
    return True

def validate(project_root: Path, summary: Dict[str, object]) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    created_rel = [Path(item) for item in summary.get("created_files", []) if isinstance(item, str)]
    created_files = [project_root / item for item in created_rel if (project_root / item).exists()]
    source_files = [path for path in created_files if path.suffix in SOURCE_SUFFIXES]
    non_test_source = [path for path in source_files if not is_test_file(path)]
    if not created_files:
        add_issue(issues, "CDG-001")
        return issues
    if source_files and not parse_check(project_root, source_files):
        add_issue(issues, "CDG-002")
    combined_source = "\n".join(safe_read_text(path) for path in source_files)
    if any(pattern.search(combined_source) for pattern in SECRET_PATTERNS):
        add_issue(issues, "CDG-003")
    if non_test_source and not any(re.search(pattern, safe_read_text(path)) for path in non_test_source for pattern in ERROR_PATTERNS):
        add_issue(issues, "CDG-004")
    if not all(naming_ok(path) for path in source_files):
        add_issue(issues, "CDG-005")
    if not any(is_test_file(path) for path in created_files):
        add_issue(issues, "CDG-006")
    if non_test_source and not any(re.search(pattern, safe_read_text(path)) for path in non_test_source for pattern in COMMENT_PATTERNS):
        add_issue(issues, "CDG-007")
    touched_docs = {Path(item).name.lower() for item in summary.get("created_files", []) if isinstance(item, str)} | {Path(item).name.lower() for item in summary.get("modified_files", []) if isinstance(item, str)}
    if not ({"readme.md", "changelog.md"} & touched_docs):
        add_issue(issues, "CDG-008")
    if any(re.search(r"\b(?:TODO|FIXME)\b", safe_read_text(path)) for path in non_test_source):
        add_issue(issues, "CDG-009")
    if summary.get("dependencies_added") and not summary.get("manifest_updates"):
        add_issue(issues, "CDG-010")
    deduped: List[Tuple[str, str]] = []
    seen = set()
    for issue in issues:
        if issue[0] not in seen:
            deduped.append(issue)
            seen.add(issue[0])
    deduped.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return deduped

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate generated scaffold outputs.")
    parser.add_argument("--project-root", default=".", help="Project root containing codegen/scaffold-summary.json")
    parser.add_argument("--summary", default="codegen/scaffold-summary.json", help="Relative or absolute path to scaffold summary JSON")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    summary_path = Path(args.summary).expanduser()
    if not summary_path.is_absolute():
        summary_path = project_root / summary_path
    summary = load_summary(summary_path.resolve())
    if not summary:
        print(f"[CRITICAL] CDG-001: {RULES['CDG-001']['message']}")
        print("Found 1 issues (1 critical, 0 high, 0 medium, 0 low)")
        return 1
    issues = validate(project_root, summary)
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rule_id, message in issues:
        severity = RULES[rule_id]["severity"]
        counts[severity] += 1
        print(f"[{severity}]".ljust(11) + f" {rule_id}: {message}")
    print(f"Found {len(issues)} issues ({counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low)")
    return 0 if counts["CRITICAL"] == 0 and counts["HIGH"] == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
