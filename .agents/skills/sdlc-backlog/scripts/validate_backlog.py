#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Validate backlog summaries against the backlog rule set."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
RULES = {
    "BKL-001": {"severity": "CRITICAL", "message": "backlog/stories-summary.md exists"},
    "BKL-002": {"severity": "CRITICAL", "message": "At least one epic defined"},
    "BKL-003": {"severity": "HIGH", "message": "At least 3 user stories defined"},
    "BKL-004": {"severity": "HIGH", "message": 'All stories follow "As a... I want... so that..." format'},
    "BKL-005": {"severity": "HIGH", "message": "All stories have acceptance criteria"},
    "BKL-006": {"severity": "MEDIUM", "message": "Acceptance criteria in Given/When/Then format"},
    "BKL-007": {"severity": "MEDIUM", "message": "Story points or size estimates present"},
    "BKL-008": {"severity": "MEDIUM", "message": "Stories linked to epics"},
    "BKL-009": {"severity": "LOW", "message": "Definition of Done defined"},
    "BKL-010": {"severity": "LOW", "message": "Sprint/iteration assignment present"},
}


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def add_issue(issues: List[Tuple[str, str]], rule_id: str) -> None:
    issues.append((rule_id, RULES[rule_id]["message"]))


def extract_story_blocks(markdown: str) -> List[str]:
    matches = list(re.finditer(r"(?m)^###\s+Story\s+[A-Z0-9-]+\s+—\s+.+$", markdown))
    blocks: List[str] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        blocks.append(markdown[start:end].strip())
    return blocks


def field_value(block: str, field_name: str) -> str:
    match = re.search(rf"(?im)^(?:-\s+)?{re.escape(field_name)}:\s*(.+)$", block)
    return match.group(1).strip() if match else ""


def validate(markdown: str) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    epic_count = len(re.findall(r"(?m)^###\s+Epic\s+[A-Z0-9-]+", markdown))
    story_blocks = extract_story_blocks(markdown)
    if epic_count < 1:
        add_issue(issues, "BKL-002")
    if len(story_blocks) < 3:
        add_issue(issues, "BKL-003")

    if story_blocks:
        story_format_ok = True
        acceptance_ok = True
        gherkin_ok = True
        size_ok = True
        epic_link_ok = True
        sprint_ok = True
        for block in story_blocks:
            if not re.fullmatch(r"As a .+?, I want .+? so that .+", field_value(block, "Story")):
                story_format_ok = False
            if not re.search(r"(?im)^####\s+Acceptance Criteria", block):
                acceptance_ok = False
            has_given = bool(re.search(r"(?im)^-\s+Given\b", block))
            has_when = bool(re.search(r"(?im)^-\s+When\b", block))
            has_then = bool(re.search(r"(?im)^-\s+Then\b", block))
            if not (has_given and has_when and has_then):
                gherkin_ok = False
            if not (field_value(block, "Story Points") or field_value(block, "Size")):
                size_ok = False
            if not field_value(block, "Epic"):
                epic_link_ok = False
            if not (field_value(block, "Sprint") or field_value(block, "Iteration")):
                sprint_ok = False
        if not story_format_ok:
            add_issue(issues, "BKL-004")
        if not acceptance_ok:
            add_issue(issues, "BKL-005")
        if not gherkin_ok:
            add_issue(issues, "BKL-006")
        if not size_ok:
            add_issue(issues, "BKL-007")
        if not epic_link_ok:
            add_issue(issues, "BKL-008")
        if not sprint_ok:
            add_issue(issues, "BKL-010")
    else:
        for rule_id in ["BKL-004", "BKL-005", "BKL-006", "BKL-007", "BKL-008", "BKL-010"]:
            add_issue(issues, rule_id)

    if not re.search(r"(?im)^##\s+Definition of Done", markdown):
        add_issue(issues, "BKL-009")

    deduped: List[Tuple[str, str]] = []
    seen = set()
    for issue in issues:
        if issue[0] not in seen:
            deduped.append(issue)
            seen.add(issue[0])
    deduped.sort(key=lambda item: (SEVERITY_ORDER[RULES[item[0]]["severity"]], item[0]))
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate backlog/stories-summary.md against 10 backlog rules.")
    parser.add_argument("backlog_file", nargs="?", default="backlog/stories-summary.md", help="Path to stories-summary.md")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.backlog_file).expanduser().resolve()
    if not path.exists() or not path.is_file():
        print(f"[CRITICAL] BKL-001: {RULES['BKL-001']['message']}")
        print("Found 1 issues (1 critical, 0 high, 0 medium, 0 low)")
        return 1

    issues = validate(safe_read_text(path))
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for rule_id, message in issues:
        severity = RULES[rule_id]["severity"]
        counts[severity] += 1
        print(f"[{severity}]".ljust(11) + f" {rule_id}: {message}")
    print(f"Found {len(issues)} issues ({counts['CRITICAL']} critical, {counts['HIGH']} high, {counts['MEDIUM']} medium, {counts['LOW']} low)")
    return 0 if counts["CRITICAL"] == 0 and counts["HIGH"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
