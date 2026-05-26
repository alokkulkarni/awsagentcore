#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate SDLC architecture artefacts against ten production rules."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
RULES = {
    "ARC-001": {"severity": "CRITICAL", "message": "HLD document exists at architecture/hld.md"},
    "ARC-002": {"severity": "CRITICAL", "message": "At least one component defined in HLD"},
    "ARC-003": {"severity": "HIGH", "message": "Component diagram (.mmd) exists"},
    "ARC-004": {"severity": "HIGH", "message": "At least one ADR exists in architecture/adrs/"},
    "ARC-005": {"severity": "HIGH", "message": "Technology stack document exists"},
    "ARC-006": {"severity": "MEDIUM", "message": "Each component has a defined responsibility"},
    "ARC-007": {"severity": "MEDIUM", "message": "Integration points/interfaces documented"},
    "ARC-008": {"severity": "MEDIUM", "message": "Non-functional requirements addressed (performance, scalability, security)"},
    "ARC-009": {"severity": "LOW", "message": "Deployment model described"},
    "ARC-010": {"severity": "LOW", "message": "Architecture risk assessment present"},
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


def validate_architecture(architecture_dir: Path) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    hld_path = architecture_dir / "hld.md"
    diagram_path = architecture_dir / "component-diagram.mmd"
    adrs_dir = architecture_dir / "adrs"
    tech_stack_path = architecture_dir / "tech-stack.md"

    if not hld_path.exists() or not hld_path.is_file() or hld_path.stat().st_size == 0:
        add_issue(issues, "ARC-001")
        return issues

    markdown = safe_read_text(hld_path)
    sections = extract_sections(markdown)

    component_breakdown = sections.get(canonical_heading("Component Breakdown"), "")
    component_tables = extract_tables(component_breakdown)
    component_table = component_tables[0] if component_tables else []
    if not component_table or not table_has_data(component_table):
        add_issue(issues, "ARC-002")
    else:
        for row in component_table[2:]:
            if len(row) < 4 or not row[0].strip() or not row[1].strip():
                add_issue(issues, "ARC-006")
                break

    if not diagram_path.exists() or not diagram_path.is_file() or diagram_path.stat().st_size == 0:
        add_issue(issues, "ARC-003")

    adr_files = sorted(adrs_dir.glob("*.md")) if adrs_dir.exists() else []
    if not adr_files:
        add_issue(issues, "ARC-004")

    if not tech_stack_path.exists() or not tech_stack_path.is_file() or tech_stack_path.stat().st_size == 0:
        add_issue(issues, "ARC-005")

    integration_points = sections.get(canonical_heading("Integration Points"), "")
    if not integration_points or not (extract_tables(integration_points) or re.search(r"interface|integration|protocol|api", integration_points, flags=re.IGNORECASE)):
        add_issue(issues, "ARC-007")

    nfr = sections.get(canonical_heading("Non-Functional Requirements"), "")
    if not all(keyword in nfr.lower() for keyword in ["performance", "scalability", "security"]):
        add_issue(issues, "ARC-008")

    deployment = sections.get(canonical_heading("Deployment Architecture"), "")
    if len(deployment.split()) < 12:
        add_issue(issues, "ARC-009")

    risks = sections.get(canonical_heading("Known Risks & Trade-offs"), "")
    if not risks or not (extract_tables(risks) or len(risks.split()) >= 12):
        add_issue(issues, "ARC-010")

    deduped: List[Tuple[str, str]] = []
    seen = set()
    for item in issues:
        if item[0] not in seen:
            deduped.append(item)
            seen.add(item[0])
    deduped.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate architecture artefacts in an architecture directory.")
    parser.add_argument("architecture_dir", nargs="?", default="architecture", help="Path to the architecture output directory.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    architecture_dir = Path(args.architecture_dir).expanduser().resolve()
    issues = validate_architecture(architecture_dir)
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
