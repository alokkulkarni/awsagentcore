#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate test assets against TST-001 through TST-010."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
RULES = {
    "TST-001": {"severity": "CRITICAL", "message": "At least one test file exists"},
    "TST-002": {"severity": "CRITICAL", "message": "Tests can be discovered by the test runner (syntax valid)"},
    "TST-003": {"severity": "HIGH", "message": "Line coverage ≥ 80% (if coverage report available)"},
    "TST-004": {"severity": "HIGH", "message": "Branch coverage ≥ 70% (if coverage report available)"},
    "TST-005": {"severity": "HIGH", "message": "No test that always passes (empty assertions, pass-only tests)"},
    "TST-006": {"severity": "MEDIUM", "message": "Each public function/method has at least one test"},
    "TST-007": {"severity": "MEDIUM", "message": "Integration tests present for API endpoints"},
    "TST-008": {"severity": "MEDIUM", "message": "Tests are independent (no shared mutable state between tests)"},
    "TST-009": {"severity": "LOW", "message": "Test names are descriptive (not test1, testA, etc.)"},
    "TST-010": {"severity": "LOW", "message": "E2E tests present for critical user journeys"},
}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".venv", "venv", "target", "vendor", "__pycache__", "test-results"}
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"}
TEST_PATTERNS = ("test_", "_test.", ".test.", ".spec.", "e2e", "integration", "Test.java")
API_PATTERNS = [
    re.compile(r"app\.(?:get|post|put|delete|patch)\(\s*['\"]([^'\"]+)"),
    re.compile(r"router\.(?:get|post|put|delete|patch)\(\s*['\"]([^'\"]+)"),
    re.compile(r"@(?:Get|Post|Put|Delete|Patch)Mapping\(\s*['\"]?([^'\")]+)"),
    re.compile(r"http\.(?:Handle|HandleFunc)\(\s*['\"]([^'\"]+)"),
]
CRITICAL_JOURNEY_HINTS = ("login", "payment", "transfer", "checkout", "signup", "account", "onboarding")


def add_issue(issues: List[Tuple[str, str]], rule_id: str) -> None:
    issues.append((rule_id, RULES[rule_id]["message"]))


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def discover_files(project_root: Path) -> Tuple[List[Path], List[Path]]:
    source_files: List[Path] = []
    test_files: List[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        lowered = path.as_posix().lower()
        if path.suffix.lower() in SOURCE_EXTENSIONS:
            if any(pattern in lowered for pattern in TEST_PATTERNS):
                test_files.append(path)
            else:
                source_files.append(path)
        elif path.suffix.lower() in {".feature", ".spec"}:
            test_files.append(path)
    return source_files, test_files


def parse_python_symbols(path: Path) -> List[str]:
    try:
        tree = ast.parse(safe_read_text(path))
    except SyntaxError:
        return []
    symbols: List[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            symbols.append(node.name)
    return symbols


def parse_generic_symbols(text: str, suffix: str) -> List[str]:
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        patterns = [
            re.compile(r"export\s+(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)"),
            re.compile(r"export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ]
        names: List[str] = []
        for pattern in patterns:
            names.extend(match.group(1) for match in pattern.finditer(text))
        return names
    if suffix == ".go":
        return re.findall(r"(?m)^func\s+([A-Z][A-Za-z0-9_]*)\s*\(", text)
    if suffix == ".java":
        return re.findall(r"(?m)^\s*public\s+(?!class|interface|enum|record)(?:static\s+)?[A-Za-z0-9_<>\[\], ?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    return []


def parse_coverage(project_root: Path) -> Dict[str, Optional[float]]:
    candidates = [
        project_root / "coverage" / "coverage-summary.json",
        project_root / "coverage-summary.json",
        project_root / "coverage" / "lcov.info",
        project_root / "lcov.info",
        project_root / "coverage.xml",
        project_root / "target" / "site" / "jacoco" / "jacoco.xml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        if path.name.endswith("coverage-summary.json"):
            try:
                payload = json.loads(safe_read_text(path))
            except json.JSONDecodeError:
                continue
            total = payload.get("total", {})
            return {"line": total.get("lines", {}).get("pct"), "branch": total.get("branches", {}).get("pct")}
        if path.name == "lcov.info":
            lf = lh = brf = brh = 0
            for raw in safe_read_text(path).splitlines():
                if raw.startswith("LF:"):
                    lf += int(raw.split(":", 1)[1])
                elif raw.startswith("LH:"):
                    lh += int(raw.split(":", 1)[1])
                elif raw.startswith("BRF:"):
                    brf += int(raw.split(":", 1)[1])
                elif raw.startswith("BRH:"):
                    brh += int(raw.split(":", 1)[1])
            return {"line": round((lh / lf) * 100, 2) if lf else None, "branch": round((brh / brf) * 100, 2) if brf else None}
        if path.name == "coverage.xml":
            try:
                root = ET.fromstring(safe_read_text(path))
            except ET.ParseError:
                continue
            line_rate = root.attrib.get("line-rate")
            branch_rate = root.attrib.get("branch-rate")
            return {"line": round(float(line_rate) * 100, 2) if line_rate else None, "branch": round(float(branch_rate) * 100, 2) if branch_rate else None}
        if path.name == "jacoco.xml":
            try:
                root = ET.fromstring(safe_read_text(path))
            except ET.ParseError:
                continue
            line = branch = None
            for counter in root.findall(".//counter"):
                ctype = counter.attrib.get("type")
                missed = int(counter.attrib.get("missed", "0"))
                covered = int(counter.attrib.get("covered", "0"))
                total = missed + covered
                if total == 0:
                    continue
                pct = round((covered / total) * 100, 2)
                if ctype == "LINE":
                    line = pct
                elif ctype == "BRANCH":
                    branch = pct
            return {"line": line, "branch": branch}
    return {"line": None, "branch": None}


def syntax_valid(test_files: List[Path]) -> bool:
    for path in test_files:
        text = safe_read_text(path)
        if path.suffix.lower() == ".py":
            try:
                compile(text, str(path), "exec")
            except SyntaxError:
                return False
        elif path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
            if text.count("{") != text.count("}") or not re.search(r"\b(?:describe|it|test)\s*\(", text):
                return False
        elif path.suffix.lower() == ".go":
            if "func Test" not in text:
                return False
        elif path.suffix.lower() == ".java":
            if "@Test" not in text:
                return False
    return True


def always_passing_test(test_files: List[Path]) -> bool:
    tautologies = [
        re.compile(r"assert\s+True"),
        re.compile(r"expect\(true\)\.toBe\(true\)"),
        re.compile(r"assertEquals\(1,\s*1\)"),
        re.compile(r"\bpass\b"),
        re.compile(r"\bit\.todo\("),
        re.compile(r"\bt\.Skip\("),
    ]
    for path in test_files:
        text = safe_read_text(path)
        if any(pattern.search(text) for pattern in tautologies):
            return True
        if re.search(r"\b(?:def test_[A-Za-z0-9_]+\([^)]*\):\s*(?:#.*\n)*\s*$)", text, re.MULTILINE):
            return True
    return False


def all_test_text(test_files: List[Path]) -> str:
    return "\n".join(safe_read_text(path) for path in test_files)


def public_symbols_covered(source_files: List[Path], test_files: List[Path]) -> bool:
    test_text = all_test_text(test_files)
    symbols: List[str] = []
    for path in source_files:
        if path.suffix.lower() == ".py":
            symbols.extend(parse_python_symbols(path))
        else:
            symbols.extend(parse_generic_symbols(safe_read_text(path), path.suffix.lower()))
    symbols = [symbol for symbol in symbols if symbol and len(symbol) > 1]
    if not symbols:
        return True
    return all(symbol in test_text for symbol in symbols)


def has_api_endpoints(source_files: List[Path]) -> bool:
    for path in source_files:
        text = safe_read_text(path)
        if any(pattern.search(text) for pattern in API_PATTERNS):
            return True
    return False


def has_integration_tests(test_files: List[Path]) -> bool:
    return any("integration" in path.as_posix().lower() or ".int." in path.name.lower() or "api" in path.name.lower() for path in test_files)


def has_shared_mutable_state(test_files: List[Path]) -> bool:
    patterns = [
        re.compile(r"\bbeforeAll\s*\("),
        re.compile(r"\bsetUpClass\s*\("),
        re.compile(r"\bglobal\s+[A-Za-z_]"),
        re.compile(r"\bshared_[A-Za-z0-9_]+\s*="),
        re.compile(r"\blet\s+shared[A-Za-z0-9_]*\s*="),
    ]
    return any(any(pattern.search(safe_read_text(path)) for pattern in patterns) for path in test_files)


def has_generic_names(test_files: List[Path]) -> bool:
    generic_patterns = [
        re.compile(r"\btest1\b", re.IGNORECASE),
        re.compile(r"\btestA\b", re.IGNORECASE),
        re.compile(r"['\"]should work['\"]", re.IGNORECASE),
        re.compile(r"['\"]works['\"]", re.IGNORECASE),
    ]
    return any(any(pattern.search(safe_read_text(path)) for pattern in generic_patterns) for path in test_files)


def has_critical_journeys(project_root: Path, source_files: List[Path]) -> bool:
    sample = safe_read_text(project_root / "README.md") + "\n" + "\n".join(safe_read_text(path) for path in source_files[:50])
    lowered = sample.lower()
    return any(hint in lowered for hint in CRITICAL_JOURNEY_HINTS)


def has_e2e_tests(test_files: List[Path]) -> bool:
    return any(any(token in path.as_posix().lower() for token in ("e2e", "playwright", "journey")) for path in test_files)


def validate(project_root: Path) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    source_files, test_files = discover_files(project_root)
    coverage = parse_coverage(project_root)

    if not test_files:
        add_issue(issues, "TST-001")
        return issues
    if not syntax_valid(test_files):
        add_issue(issues, "TST-002")
    if coverage["line"] is not None and coverage["line"] < 80.0:
        add_issue(issues, "TST-003")
    if coverage["branch"] is not None and coverage["branch"] < 70.0:
        add_issue(issues, "TST-004")
    if always_passing_test(test_files):
        add_issue(issues, "TST-005")
    if not public_symbols_covered(source_files, test_files):
        add_issue(issues, "TST-006")
    if has_api_endpoints(source_files) and not has_integration_tests(test_files):
        add_issue(issues, "TST-007")
    if has_shared_mutable_state(test_files):
        add_issue(issues, "TST-008")
    if has_generic_names(test_files):
        add_issue(issues, "TST-009")
    if has_critical_journeys(project_root, source_files) and not has_e2e_tests(test_files):
        add_issue(issues, "TST-010")

    deduped: List[Tuple[str, str]] = []
    seen = set()
    for issue in issues:
        if issue[0] not in seen:
            deduped.append(issue)
            seen.add(issue[0])
    deduped.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate generated or existing test assets.")
    parser.add_argument("--project-root", default=".", help="Project root to scan.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    issues = validate(project_root)
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rule_id, message in issues:
        severity = RULES[rule_id]["severity"]
        counts[severity] += 1
        print(f"[{severity}]".ljust(11) + f" {rule_id}: {message}")
    print(f"Found {len(issues)} issues ({counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low)")
    return 1 if counts["CRITICAL"] or counts["HIGH"] else 0


if __name__ == "__main__":
    sys.exit(main())
