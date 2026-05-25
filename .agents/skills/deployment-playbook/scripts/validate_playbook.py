#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate deployment playbooks against enterprise completeness rules."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
ALLOWED_STATUS = {"Draft", "In Review", "Approved", "Active", "Retired"}
REQUIRED_RISK_COLUMNS = ["id", "risk issue", "category", "probability", "impact", "mitigation", "owner", "status"]

RULES = {
    "PLAY-001": {"severity": "CRITICAL", "message": "Document Control block missing"},
    "PLAY-002": {"severity": "HIGH", "message": "Playbook ID missing or not in PLY-XXX-NNN format"},
    "PLAY-003": {"severity": "HIGH", "message": "Version field missing or not in semantic version format"},
    "PLAY-004": {"severity": "HIGH", "message": "Status field missing or not one of Draft | In Review | Approved | Active | Retired"},
    "PLAY-005": {"severity": "HIGH", "message": "No approver listed"},
    "PLAY-006": {"severity": "CRITICAL", "message": "Purpose & Scope section missing"},
    "PLAY-007": {"severity": "MEDIUM", "message": "In-Scope and Out-of-Scope definitions missing"},
    "PLAY-008": {"severity": "CRITICAL", "message": "No deployment phase defined"},
    "PLAY-009": {"severity": "HIGH", "message": "One or more deployment phases are missing rollback triggers"},
    "PLAY-010": {"severity": "HIGH", "message": "Risk Register table missing or empty"},
    "PLAY-011": {"severity": "HIGH", "message": "Risk Register table missing required columns"},
    "PLAY-012": {"severity": "CRITICAL", "message": "Rollback Strategy section missing"},
    "PLAY-013": {"severity": "HIGH", "message": "Rollback Time Objective (RTO) not defined"},
    "PLAY-014": {"severity": "MEDIUM", "message": "Communication Plan table missing"},
    "PLAY-015": {"severity": "HIGH", "message": "Success Criteria section missing"},
    "PLAY-016": {"severity": "HIGH", "message": "Post-Deployment Validation section missing"},
    "PLAY-017": {"severity": "MEDIUM", "message": "Contacts & Escalation table missing"},
    "PLAY-018": {"severity": "HIGH", "message": "Approvals table missing"},
    "PLAY-019": {"severity": "MEDIUM", "message": "Environment Matrix table missing"},
    "PLAY-020": {"severity": "MEDIUM", "message": "Change Management section missing change type"}
}


def canonical_heading(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"^\d+(?:\.\d+)*[.)-]?\s*", "", value)
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()


def extract_main_sections(markdown: str) -> Dict[str, str]:
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", markdown))
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = canonical_heading(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[heading] = markdown[start:end].strip()
    return sections


def get_section(sections: Dict[str, str], name: str) -> str:
    return sections.get(canonical_heading(name), "")


def normalize_column(value: str) -> str:
    value = value.strip().strip("|")
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return value.strip()


def extract_first_table(section_text: str) -> List[List[str]]:
    lines = [line.strip() for line in section_text.splitlines()]
    table_lines: List[str] = []
    collecting = False
    for line in lines:
        if line.startswith("|") and line.endswith("|"):
            table_lines.append(line)
            collecting = True
        elif collecting:
            break
    if len(table_lines) < 2:
        return []
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in table_lines]


def table_has_data(table: List[List[str]]) -> bool:
    return len(table) >= 3 and any(cell.strip(" -") for row in table[2:] for cell in row)


def find_field_value(text: str, field_name: str) -> str:
    patterns = [
        rf"(?im)^\|\s*{re.escape(field_name)}\s*\|\s*([^|]+?)\s*\|$",
        rf"(?im)^(?:[-*]\s+)?\*\*{re.escape(field_name)}:\*\*\s*(.+)$",
        rf"(?im)^(?:[-*]\s+)?{re.escape(field_name)}\s*:\s*(.+)$"
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def add_issue(issues: List[Tuple[str, str]], rule_id: str) -> None:
    issues.append((rule_id, RULES[rule_id]["message"]))


def validate(markdown: str) -> List[Tuple[str, str]]:
    sections = extract_main_sections(markdown)
    issues: List[Tuple[str, str]] = []

    document_control = get_section(sections, "Document Control")
    if not document_control:
        add_issue(issues, "PLAY-001")
    else:
        playbook_id = find_field_value(document_control, "Playbook ID")
        if not re.fullmatch(r"PLY-[A-Z]{3}-\d{3}", playbook_id):
            add_issue(issues, "PLAY-002")
        version = find_field_value(document_control, "Version")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            add_issue(issues, "PLAY-003")
        status = find_field_value(document_control, "Status")
        if status not in ALLOWED_STATUS:
            add_issue(issues, "PLAY-004")
        approvers = find_field_value(document_control, "Approvers")
        if not approvers or approvers.lower() in {"tbd", "n/a", "none"}:
            add_issue(issues, "PLAY-005")

    purpose_scope = get_section(sections, "Purpose & Scope")
    if not purpose_scope:
        add_issue(issues, "PLAY-006")
    elif "in-scope" not in purpose_scope.lower() or "out-of-scope" not in purpose_scope.lower():
        add_issue(issues, "PLAY-007")

    deployment_strategy = get_section(sections, "Deployment Strategy")
    phase_matches = list(re.finditer(r"(?m)^###\s+Phase\b.+$", deployment_strategy))
    if not phase_matches:
        add_issue(issues, "PLAY-008")
    else:
        for index, match in enumerate(phase_matches):
            start = match.end()
            end = phase_matches[index + 1].start() if index + 1 < len(phase_matches) else len(deployment_strategy)
            if "rollback trigger" not in deployment_strategy[start:end].lower():
                add_issue(issues, "PLAY-009")
                break

    risk_register = get_section(sections, "Risk Register")
    risk_table = extract_first_table(risk_register)
    if not table_has_data(risk_table):
        add_issue(issues, "PLAY-010")
    else:
        header = [normalize_column(cell) for cell in risk_table[0]]
        if header != REQUIRED_RISK_COLUMNS:
            add_issue(issues, "PLAY-011")

    rollback = get_section(sections, "Rollback Strategy")
    if not rollback:
        add_issue(issues, "PLAY-012")
    elif not re.search(r"\b(?:rto|rollback time objective)\b", rollback, flags=re.IGNORECASE):
        add_issue(issues, "PLAY-013")

    if not table_has_data(extract_first_table(get_section(sections, "Communication Plan"))):
        add_issue(issues, "PLAY-014")

    if not get_section(sections, "Success Criteria"):
        add_issue(issues, "PLAY-015")

    if not get_section(sections, "Post-Deployment Validation"):
        add_issue(issues, "PLAY-016")

    if not table_has_data(extract_first_table(get_section(sections, "Contacts & Escalation"))):
        add_issue(issues, "PLAY-017")

    if not table_has_data(extract_first_table(get_section(sections, "Approvals"))):
        add_issue(issues, "PLAY-018")

    if not table_has_data(extract_first_table(get_section(sections, "Environment Matrix"))):
        add_issue(issues, "PLAY-019")

    change_management = get_section(sections, "Change Management")
    change_type = find_field_value(change_management, "Change Type")
    if not change_management or change_type not in {"Standard", "Normal", "Emergency"}:
        add_issue(issues, "PLAY-020")

    issues.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return issues


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2:
        print("Usage: validate_playbook.py <playbook_file>", file=sys.stderr)
        return 1

    path = Path(argv[1]).expanduser().resolve()
    if not path.exists() or not path.is_file():
        print(f"[ERROR] Playbook file not found: {path}", file=sys.stderr)
        return 1

    try:
        markdown = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        markdown = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    issues = validate(markdown)
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rule_id, message in issues:
        severity = RULES[rule_id]["severity"]
        counts[severity] += 1
        print(f"[{severity}] {rule_id}: {message}")

    total = len(issues)
    print(f"Found {total} issues ({counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low)")
    return 0 if counts["CRITICAL"] == 0 and counts["HIGH"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
