#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate SDLC review reports against REV-001 through REV-010."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
RULES = {
    "REV-001": {"severity": "CRITICAL", "message": "Review report file exists and is non-empty"},
    "REV-002": {"severity": "CRITICAL", "message": "No CRITICAL severity findings without resolution"},
    "REV-003": {"severity": "CRITICAL", "message": "No HIGH severity security findings without resolution"},
    "REV-004": {"severity": "HIGH", "message": "No hardcoded secrets or credentials detected"},
    "REV-005": {"severity": "HIGH", "message": "No known CVEs with CVSS ≥ 7.0 in dependencies"},
    "REV-006": {"severity": "HIGH", "message": "Test coverage ≥ 80% (if coverage data available)"},
    "REV-007": {"severity": "MEDIUM", "message": "No MEDIUM severity findings without a ticket/note"},
    "REV-008": {"severity": "MEDIUM", "message": "Code follows project style guide (linting clean)"},
    "REV-009": {"severity": "LOW", "message": "Documentation updated for changed public APIs"},
    "REV-010": {"severity": "LOW", "message": "CHANGELOG or commit message references a ticket"},
}
PUBLIC_API_HINTS = ("api", "route", "controller", "graphql", "openapi", "schema", "public")
DOC_HINTS = ("docs/", "readme", "changelog", ".md")


def add_issue(issues: List[Tuple[str, str]], rule_id: str) -> None:
    issues.append((rule_id, RULES[rule_id]["message"]))


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_payload(report_path: Path) -> Dict[str, Any]:
    json_path = report_path.with_suffix(".json")
    if json_path.exists():
        try:
            return json.loads(safe_read_text(json_path))
        except json.JSONDecodeError:
            return {}
    return {}


def run_command(command: List[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)


def latest_commit_message(project_root: Path) -> str:
    if not shutil.which("git"):
        return ""
    result = run_command(["git", "log", "-1", "--pretty=%s"], project_root)
    return result.stdout.strip()


def is_security_finding(finding: Dict[str, Any]) -> bool:
    return str(finding.get("category", "")).lower() in {"sast", "secret-detection", "dependency-cve"}


def validate(report_path: Path, project_root: Path) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    if not report_path.exists() or not report_path.is_file() or not safe_read_text(report_path).strip():
        add_issue(issues, "REV-001")
        return issues

    payload = load_payload(report_path)
    findings = payload.get("findings") if isinstance(payload.get("findings"), list) else []
    files = payload.get("files_reviewed") if isinstance(payload.get("files_reviewed"), list) else []
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
    lint = payload.get("lint") if isinstance(payload.get("lint"), dict) else {}

    if any(str(f.get("severity")) == "CRITICAL" and not f.get("resolved") for f in findings):
        add_issue(issues, "REV-002")
    if any(str(f.get("severity")) == "HIGH" and is_security_finding(f) and not f.get("resolved") for f in findings):
        add_issue(issues, "REV-003")
    if any(is_security_finding(f) and ("secret" in str(f.get("issue", "")).lower() or str(f.get("cwe")) == "CWE-798") for f in findings):
        add_issue(issues, "REV-004")
    if any(str(f.get("category")) == "dependency-cve" and float(f.get("metadata", {}).get("cvss", 0) or 0) >= 7.0 for f in findings):
        add_issue(issues, "REV-005")
    if coverage.get("line") is not None and float(coverage["line"]) < 80.0:
        add_issue(issues, "REV-006")
    if any(str(f.get("severity")) == "MEDIUM" and not f.get("ticket") and not f.get("note") for f in findings):
        add_issue(issues, "REV-007")
    if lint.get("status") in {"failed", "unavailable"}:
        add_issue(issues, "REV-008")

    lowered_files = [str(item).lower() for item in files]
    public_api_changed = any(any(hint in item for hint in PUBLIC_API_HINTS) for item in lowered_files)
    docs_changed = any(any(hint in item for hint in DOC_HINTS) for item in lowered_files)
    if public_api_changed and not docs_changed:
        add_issue(issues, "REV-009")

    commit_message = latest_commit_message(project_root)
    ticket_pattern = re.compile(r"(?:[A-Z]{2,}-\d+|#\d+)")
    if not any("changelog" in item for item in lowered_files) and not ticket_pattern.search(commit_message):
        add_issue(issues, "REV-010")

    deduped: List[Tuple[str, str]] = []
    seen = set()
    for issue in issues:
        if issue[0] not in seen:
            deduped.append(issue)
            seen.add(issue[0])
    deduped.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an SDLC review report against REV rules.")
    parser.add_argument("report_file", help="Path to the markdown review report.")
    parser.add_argument("--project-root", default=".", help="Project root for commit and docs checks.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report_path = Path(args.report_file).expanduser().resolve()
    project_root = Path(args.project_root).expanduser().resolve()
    issues = validate(report_path, project_root)
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rule_id, message in issues:
        severity = RULES[rule_id]["severity"]
        counts[severity] += 1
        print(f"[{severity}]".ljust(11) + f" {rule_id}: {message}")
    print(f"Found {len(issues)} issues ({counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low)")
    return 1 if counts["CRITICAL"] or counts["HIGH"] else 0


if __name__ == "__main__":
    sys.exit(main())
