#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate a runbook markdown file against deployment-runbook rules."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = SCRIPT_DIR.parent / "assets" / "schema.json"


def load_rules() -> Dict[str, Dict[str, str]]:
    data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return {item["id"]: item for item in data["validationRules"]}


RULES = load_rules()


def normalize_heading(title: str) -> str:
    title = re.sub(r"^\d+\.\s*", "", title.strip())
    return re.sub(r"\s+", " ", title).strip().lower()


def top_level_sections(text: str) -> Dict[str, str]:
    matches = list(re.finditer(r"(?m)^##\s+(.+)$", text))
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        title = normalize_heading(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def find_section(sections: Dict[str, str], name: str) -> Optional[str]:
    return sections.get(name.lower())


def parse_steps(section_text: str) -> List[Tuple[int, str, str]]:
    matches = list(re.finditer(r"(?m)^###\s+(\d+)\.\s+(.+)$", section_text))
    steps: List[Tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section_text)
        steps.append((int(match.group(1)), match.group(2).strip(), section_text[start:end].strip()))
    return steps


def parse_table(section_text: str) -> Tuple[List[str], List[List[str]]]:
    lines = [line.strip() for line in section_text.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return [], []
    header = [cell.strip().lower() for cell in lines[0].strip("|").split("|")]
    rows: List[List[str]] = []
    for line in lines[2:]:
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return header, rows


def add_issue(issues: List[Tuple[str, str, str]], rule_id: str, message: str) -> None:
    issues.append((RULES[rule_id]["severity"], rule_id, message))


def has_code_block(body: str) -> bool:
    return "```" in body


def has_verify_block(body: str) -> bool:
    return "✓ **Verify**" in body or "**Verify**" in body


def has_failure_block(body: str) -> bool:
    return "⚠️ **If this fails**" in body or "**If this fails**" in body


def validate(path: Path) -> List[Tuple[str, str, str]]:
    text = path.read_text(encoding="utf-8")
    sections = top_level_sections(text)
    issues: List[Tuple[str, str, str]] = []

    document_control = find_section(sections, "document control")
    if document_control is None:
        add_issue(issues, "RNB-001", "Document Control section is missing")
    else:
        if not re.search(r"\bRNB-[A-Z0-9]{3}-\d{3}\b", document_control):
            add_issue(issues, "RNB-002", "Runbook ID does not follow RNB-XXX-NNN format")
        if not re.search(r"(?im)^\|\s*Version\s*\|", document_control):
            add_issue(issues, "RNB-003", "Version field is missing from Document Control")
        if not re.search(r"(?im)^\|\s*Last Tested\s*\|", document_control):
            add_issue(issues, "RNB-004", "Last Tested field is missing from Document Control")

    overview = find_section(sections, "overview")
    if overview is None:
        add_issue(issues, "RNB-005", "Overview section is missing")
    else:
        if not re.search(r"(?i)\bSLA\b|\bSLO\b", overview):
            add_issue(issues, "RNB-006", "Overview does not define SLA/SLO targets")
        if not re.search(r"(?i)on-?call", overview):
            add_issue(issues, "RNB-007", "Overview does not include an on-call contact")

    prerequisites = find_section(sections, "prerequisites")
    if prerequisites is None:
        add_issue(issues, "RNB-008", "Prerequisites section is missing")
    else:
        if not re.search(r"(?m)(\|\s*[A-Z][A-Z0-9_]+\s*\|)|(- \[[ xX]\]\s*[A-Z][A-Z0-9_]+)", prerequisites):
            add_issue(issues, "RNB-009", "Prerequisites do not include an environment variable checklist item")

    procedure = find_section(sections, "procedure steps") or ""
    procedure_steps = parse_steps(procedure)
    if len(procedure_steps) < 3:
        add_issue(issues, "RNB-010", "Procedure Steps must contain at least 3 numbered steps")

    rollback = find_section(sections, "rollback procedure")
    rollback_steps = parse_steps(rollback or "")
    if rollback is None:
        add_issue(issues, "RNB-017", "Rollback Procedure section is missing")
    elif not rollback_steps:
        add_issue(issues, "RNB-018", "Rollback Procedure must contain numbered steps")

    for number, title, body in procedure_steps + rollback_steps:
        if not has_code_block(body):
            add_issue(issues, "RNB-011", f"Step {number} \"{title}\" missing command code block")
        if not has_verify_block(body):
            add_issue(issues, "RNB-012", f"Step {number} \"{title}\" missing Verify block")
        if not has_failure_block(body):
            add_issue(issues, "RNB-013", f"Step {number} \"{title}\" missing failure block")

    troubleshooting = find_section(sections, "troubleshooting table")
    if troubleshooting is None:
        add_issue(issues, "RNB-014", "Troubleshooting Table section is missing")
    else:
        header, rows = parse_table(troubleshooting)
        if not header:
            add_issue(issues, "RNB-014", "Troubleshooting Table section does not contain a markdown table")
        if len(rows) < 3:
            add_issue(issues, "RNB-015", "Troubleshooting table must contain at least 3 data rows")
        expected = ["symptom", "probable cause", "diagnostic command", "resolution", "escalate if"]
        if header[:5] != expected:
            add_issue(issues, "RNB-016", "Troubleshooting table must contain Symptom, Probable Cause, Diagnostic Command, Resolution, and Escalate If columns")

    if find_section(sections, "quick reference") is None:
        add_issue(issues, "RNB-019", "Quick Reference section is missing")
    if find_section(sections, "change log") is None:
        add_issue(issues, "RNB-020", "Change Log section is missing")

    return issues


def summary_counts(issues: Sequence[Tuple[str, str, str]]) -> Dict[str, int]:
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for severity, _, _ in issues:
        counts[severity] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a deployment runbook markdown file.")
    parser.add_argument("runbook_file", help="Path to the markdown runbook file.")
    args = parser.parse_args()
    path = Path(args.runbook_file)

    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return 1

    issues = validate(path)
    for severity, rule_id, message in issues:
        print(f"[{severity}] {rule_id}: {message}")

    counts = summary_counts(issues)
    print(
        f"Found {len(issues)} issues ({counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low)"
    )
    return 0 if counts["CRITICAL"] == 0 and counts["HIGH"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
