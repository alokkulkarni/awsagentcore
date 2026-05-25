#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate Service Introduction Documents (SID) against 20 rules."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
ALLOWED_STATUS = {"Draft", "In Review", "Approved", "Active", "Retired"}
REQUIRED_RISK_COLUMNS = ["id", "risk issue", "category", "probability", "impact", "mitigation", "owner", "status"]
REQUIRED_APPROVAL_COLUMNS = ["role", "name", "signature", "date"]
TOKEN_DEFAULTS = {
    "SID_ID": "SID-GEN-001",
    "SERVICE_TIER": "2",
    "AVAILABILITY_SLO": "99.9%",
    "RTO": "4h",
    "RPO": "1h",
}
RULES = {
    "SID-001": {"severity": "CRITICAL", "message": "Document Control block present (## Document Control heading)"},
    "SID-002": {"severity": "HIGH", "message": "SID ID present and matches SID-[A-Z]{3}-NNN"},
    "SID-003": {"severity": "HIGH", "message": "Version present and matches semver X.Y.Z"},
    "SID-004": {"severity": "HIGH", "message": "Status present and one of Draft, In Review, Approved, Active, Retired"},
    "SID-005": {"severity": "CRITICAL", "message": "Executive Summary section present and has content (>50 words)"},
    "SID-006": {"severity": "CRITICAL", "message": "Service Description section present"},
    "SID-007": {"severity": "HIGH", "message": "Service Tier defined (1, 2, or 3)"},
    "SID-008": {"severity": "CRITICAL", "message": "Technical Architecture section present"},
    "SID-009": {"severity": "CRITICAL", "message": "Service Level Objectives section present"},
    "SID-010": {"severity": "HIGH", "message": "Availability SLO defined (numeric % value)"},
    "SID-011": {"severity": "HIGH", "message": "RTO and RPO defined"},
    "SID-012": {"severity": "CRITICAL", "message": "Security & Compliance section present"},
    "SID-013": {"severity": "HIGH", "message": "Service Dependencies section present with a table"},
    "SID-014": {"severity": "HIGH", "message": "Risk Register section present with at least 4 data rows"},
    "SID-015": {"severity": "HIGH", "message": "Risk Register has required columns (ID, Risk, Category, Probability, Impact, Mitigation, Owner, Status)"},
    "SID-016": {"severity": "HIGH", "message": "Approvals section present with table containing at least 2 rows"},
    "SID-017": {"severity": "MEDIUM", "message": "Service Scope section with In-Scope and Out-of-Scope"},
    "SID-018": {"severity": "MEDIUM", "message": "Operational Model section present"},
    "SID-019": {"severity": "MEDIUM", "message": "Service Transition Plan section present"},
    "SID-020": {"severity": "LOW", "message": "Training & Knowledge Transfer section present"},
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
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"SID file not found: {path}") from exc
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


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


def normalize_placeholder(value: str) -> str:
    value = value.strip()
    match = re.fullmatch(r"\{\{([A-Z0-9_]+)\}\}", value)
    if match:
        return TOKEN_DEFAULTS.get(match.group(1), value)
    return value


def normalize_column(value: str) -> str:
    value = value.strip().strip("|")
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return value.strip()


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
    if len(table) < 2:
        return False
    data_rows = [row for row in table[2:] if any(cell.strip(" -") for cell in row)]
    return len(data_rows) >= min_rows


def find_field_value(text: str, field_name: str) -> str:
    normalized_field = normalize_column(field_name)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 2 and normalize_column(cells[0]) == normalized_field:
                return normalize_placeholder(cells[1].strip())

    patterns = [
        rf"(?im)^\|\s*{re.escape(field_name)}\s*\|\s*([^|]+?)\s*\|$",
        rf"(?im)^(?:[-*]\s+)?\*\*{re.escape(field_name)}:\*\*\s*(.+)$",
        rf"(?im)^(?:[-*]\s+)?{re.escape(field_name)}\s*:\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_placeholder(match.group(1).strip())
    return ""


def word_count(text: str) -> int:
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"\{\{[A-Z0-9_]+\}\}", "placeholder", cleaned)
    cleaned = re.sub(r"[`*_>#|\-]", " ", cleaned)
    return len(re.findall(r"\b\w+\b", cleaned))


def add_issue(issues: List[Tuple[str, str]], rule_id: str) -> None:
    issues.append((rule_id, RULES[rule_id]["message"]))


def validate(markdown: str) -> List[Tuple[str, str]]:
    sections = extract_main_sections(markdown)
    issues: List[Tuple[str, str]] = []

    document_control = get_section(sections, "Document Control")
    if not document_control:
        add_issue(issues, "SID-001")
    else:
        if not re.fullmatch(r"SID-[A-Z]{3}-\d{3}", find_field_value(document_control, "SID ID")):
            add_issue(issues, "SID-002")
        if not re.fullmatch(r"\d+\.\d+\.\d+", find_field_value(document_control, "Version")):
            add_issue(issues, "SID-003")
        if find_field_value(document_control, "Status") not in ALLOWED_STATUS:
            add_issue(issues, "SID-004")

    executive_summary = get_section(sections, "Executive Summary")
    if not executive_summary or word_count(executive_summary) <= 50:
        add_issue(issues, "SID-005")

    service_description = get_section(sections, "Service Description")
    if not service_description:
        add_issue(issues, "SID-006")
    elif find_field_value(service_description, "Service Tier") not in {"1", "2", "3"}:
        add_issue(issues, "SID-007")

    if not get_section(sections, "Technical Architecture"):
        add_issue(issues, "SID-008")

    slo_section = get_section(sections, "Service Level Objectives")
    if not slo_section:
        add_issue(issues, "SID-009")
    else:
        availability = find_field_value(slo_section, "Availability Target") or find_field_value(slo_section, "Availability SLO")
        if not re.fullmatch(r"\d+(?:\.\d+)?%", availability):
            add_issue(issues, "SID-010")
        if not find_field_value(slo_section, "RTO") or not find_field_value(slo_section, "RPO"):
            add_issue(issues, "SID-011")

    if not get_section(sections, "Security & Compliance"):
        add_issue(issues, "SID-012")

    dependencies = get_section(sections, "Service Dependencies")
    if not dependencies or not any(table_has_data(table) for table in extract_tables(dependencies)):
        add_issue(issues, "SID-013")

    risk_register = get_section(sections, "Risk Register")
    risk_tables = extract_tables(risk_register)
    risk_table = risk_tables[0] if risk_tables else []
    if not risk_table or not table_has_data(risk_table, min_rows=4):
        add_issue(issues, "SID-014")
    if not risk_table or [normalize_column(cell) for cell in risk_table[0]] != REQUIRED_RISK_COLUMNS:
        add_issue(issues, "SID-015")

    approvals = get_section(sections, "Approvals")
    approvals_tables = extract_tables(approvals)
    approvals_table = approvals_tables[0] if approvals_tables else []
    if not approvals_table or [normalize_column(cell) for cell in approvals_table[0]] != REQUIRED_APPROVAL_COLUMNS or not table_has_data(approvals_table, min_rows=2):
        add_issue(issues, "SID-016")

    scope = get_section(sections, "Service Scope")
    if not scope or "in-scope" not in scope.lower() or "out-of-scope" not in scope.lower():
        add_issue(issues, "SID-017")

    if not get_section(sections, "Operational Model"):
        add_issue(issues, "SID-018")
    if not get_section(sections, "Service Transition Plan"):
        add_issue(issues, "SID-019")
    if not get_section(sections, "Training & Knowledge Transfer"):
        add_issue(issues, "SID-020")

    deduped: List[Tuple[str, str]] = []
    seen = set()
    for issue in issues:
        if issue[0] not in seen:
            deduped.append(issue)
            seen.add(issue[0])
    deduped.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a Service Introduction Document (SID) against 20 rules.")
    parser.add_argument("sid_file", help="Path to the SID markdown file.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.sid_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        print(f"[ERROR] SID file not found: {path}", file=sys.stderr)
        return 1
    try:
        markdown = safe_read_text(path)
    except OSError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    issues = validate(markdown)
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
