#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate SDLC analysis reports against ten production rules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
RULES = {
    "ANL-001": {"severity": "CRITICAL", "message": "Report file exists and is non-empty"},
    "ANL-002": {"severity": "HIGH", "message": "Requirements section present with at least 3 items"},
    "ANL-003": {"severity": "HIGH", "message": "Dependency list present"},
    "ANL-004": {"severity": "HIGH", "message": "No unresolved HIGH/CRITICAL CVEs without mitigation note"},
    "ANL-005": {"severity": "MEDIUM", "message": "Documentation coverage assessment present"},
    "ANL-006": {"severity": "MEDIUM", "message": "Code quality metrics present (test coverage %, linting score)"},
    "ANL-007": {"severity": "MEDIUM", "message": "Technology stack identified"},
    "ANL-008": {"severity": "LOW", "message": "Architecture diagram reference or description present"},
    "ANL-009": {"severity": "LOW", "message": "Risk summary present"},
    "ANL-010": {"severity": "LOW", "message": "Recommended next steps present"},
}


def canonical_heading(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^\d+(?:\.\d+)*[.)-]?\s*", "", value)
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def extract_sections(markdown: str) -> Dict[str, str]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown))
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = canonical_heading(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[heading] = markdown[start:end].strip()
    return sections


def normalize_column(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower().strip().strip("|")).strip()


def extract_tables(section_text: str) -> List[List[List[str]]]:
    tables: List[List[List[str]]] = []
    current: List[str] = []
    for raw in section_text.splitlines():
        line = raw.strip()
        if line.startswith("|") and line.endswith("|"):
            current.append(line)
        elif current:
            if len(current) >= 2:
                tables.append([[cell.strip() for cell in row.strip("|").split("|")] for row in current])
            current = []
    if current and len(current) >= 2:
        tables.append([[cell.strip() for cell in row.strip("|").split("|")] for row in current])
    return tables


def table_has_data(table: List[List[str]], min_rows: int = 1) -> bool:
    if len(table) < 3:
        return False
    data_rows = [row for row in table[2:] if any(cell.strip(" -") for cell in row)]
    return len(data_rows) >= min_rows


def add_issue(issues: List[Tuple[str, str]], rule_id: str) -> None:
    issues.append((rule_id, RULES[rule_id]["message"]))


def validate_json_report(data: Dict[str, Any], issues: List[Tuple[str, str]]) -> None:
    requirements = data.get("requirements") if isinstance(data.get("requirements"), list) else []
    if len(requirements) < 3:
        add_issue(issues, "ANL-002")

    dependencies = data.get("dependencies", {}) if isinstance(data.get("dependencies"), dict) else {}
    dependency_items = dependencies.get("items") if isinstance(dependencies.get("items"), list) else []
    if not dependency_items:
        add_issue(issues, "ANL-003")
    else:
        unresolved = []
        for item in dependency_items:
            if not isinstance(item, dict):
                continue
            cve_status = str(item.get("cve_status", ""))
            mitigation = str(item.get("mitigation_note", "")).strip()
            if cve_status.startswith(("HIGH", "CRITICAL")) and not mitigation:
                unresolved.append(item)
        if unresolved:
            add_issue(issues, "ANL-004")

    documentation = data.get("documentation") if isinstance(data.get("documentation"), dict) else {}
    if not str(documentation.get("assessment", "")).strip():
        add_issue(issues, "ANL-005")

    code_quality = data.get("code_quality") if isinstance(data.get("code_quality"), dict) else {}
    if not str(code_quality.get("test_coverage_percent", "")).strip() or not str(code_quality.get("linting_score", "")).strip():
        add_issue(issues, "ANL-006")

    technology_stack = data.get("technology_stack") if isinstance(data.get("technology_stack"), list) else []
    if not technology_stack:
        add_issue(issues, "ANL-007")

    architecture = data.get("architecture") if isinstance(data.get("architecture"), dict) else {}
    if not str(architecture.get("diagram_reference", "")).strip() and not str(architecture.get("description", "")).strip():
        add_issue(issues, "ANL-008")

    risks = data.get("risks") if isinstance(data.get("risks"), list) else []
    if not risks:
        add_issue(issues, "ANL-009")

    next_steps = data.get("recommended_next_steps") if isinstance(data.get("recommended_next_steps"), list) else []
    if not next_steps:
        add_issue(issues, "ANL-010")


def validate_markdown_report(markdown: str, issues: List[Tuple[str, str]]) -> None:
    sections = extract_sections(markdown)

    requirements = sections.get(canonical_heading("Requirements Extracted"), "")
    requirement_count = len(re.findall(r"(?m)^\s*(?:\d+\.|[-*])\s+", requirements))
    if requirement_count < 3:
        add_issue(issues, "ANL-002")

    dependency_section = sections.get(canonical_heading("Dependency Analysis"), "")
    dep_tables = extract_tables(dependency_section)
    if not dep_tables or not any(table_has_data(table) for table in dep_tables):
        add_issue(issues, "ANL-003")
    else:
        for table in dep_tables:
            if not table_has_data(table):
                continue
            header = [normalize_column(cell) for cell in table[0]]
            cve_index = header.index("cve status") if "cve status" in header else -1
            mitigation_index = None
            for candidate in ["mitigation notes", "mitigation notes ", "mitigation notes / notes", "mitigation notes / notes ", "mitigation notes  notes"]:
                if candidate in header:
                    mitigation_index = header.index(candidate)
                    break
            if mitigation_index is None and "mitigation / notes" in header:
                mitigation_index = header.index("mitigation / notes")
            for row in table[2:]:
                if cve_index < 0 or cve_index >= len(row):
                    continue
                cve_status = row[cve_index].strip().upper()
                mitigation = row[mitigation_index].strip() if mitigation_index is not None and mitigation_index < len(row) else ""
                if (cve_status.startswith("HIGH") or cve_status.startswith("CRITICAL")) and mitigation in {"", "-", "none", "n/a"}:
                    add_issue(issues, "ANL-004")
                    break

    documentation = sections.get(canonical_heading("Documentation Assessment"), "")
    if "coverage" not in documentation.lower() and "assessment" not in documentation.lower():
        add_issue(issues, "ANL-005")

    code_quality = sections.get(canonical_heading("Code Quality Metrics"), "")
    if not re.search(r"test coverage", code_quality, flags=re.IGNORECASE) or not re.search(r"linting score", code_quality, flags=re.IGNORECASE):
        add_issue(issues, "ANL-006")

    if not re.search(r"technology stack|stack", markdown, flags=re.IGNORECASE):
        add_issue(issues, "ANL-007")

    if not re.search(r"architecture", markdown, flags=re.IGNORECASE):
        add_issue(issues, "ANL-008")

    risk_summary = sections.get(canonical_heading("Risk Summary"), "")
    if not extract_tables(risk_summary) and len(risk_summary.split()) < 10:
        add_issue(issues, "ANL-009")

    next_steps = sections.get(canonical_heading("Recommended Next Steps"), "")
    if len(re.findall(r"(?m)^\s*(?:\d+\.|[-*])\s+", next_steps)) == 0:
        add_issue(issues, "ANL-010")


def validate_report(path: Path) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        add_issue(issues, "ANL-001")
        return issues

    text = safe_read_text(path)
    if not text.strip():
        add_issue(issues, "ANL-001")
        return issues

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            add_issue(issues, "ANL-001")
            return issues
        if not isinstance(data, dict):
            add_issue(issues, "ANL-001")
            return issues
        validate_json_report(data, issues)
    else:
        validate_markdown_report(text, issues)

    deduped: List[Tuple[str, str]] = []
    seen = set()
    for item in issues:
        if item[0] not in seen:
            deduped.append(item)
            seen.add(item[0])
    deduped.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an SDLC analysis report against ten rules.")
    parser.add_argument("report_file", help="Path to analysis/source-code-report.json or analysis/analysis-report.md")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.report_file).expanduser().resolve()
    issues = validate_report(path)
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rule_id, message in issues:
        severity = RULES[rule_id]["severity"]
        counts[severity] += 1
        print(f"[{severity}]".ljust(11) + f" {rule_id}: {message}")
    total = len(issues)
    print(f"Found {total} issues ({counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low)")
    return 0 if counts["CRITICAL"] == 0 and counts["HIGH"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
