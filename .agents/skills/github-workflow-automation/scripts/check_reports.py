#!/usr/bin/env python3
"""Compare current security, image-scan, or coverage findings with the most recent n-1 report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)
SEVERITY_PATTERN = re.compile(r"\b(CRITICAL|HIGH|MEDIUM|LOW)\b", re.IGNORECASE)


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_json(path: Path) -> Any:
    text = safe_read_text(path)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def dated_directories(reports_dir: Path) -> List[Path]:
    candidates = [path for path in reports_dir.rglob("*") if path.is_dir() and DATE_PATTERN.fullmatch(path.name)]
    today = date.today().isoformat()
    return sorted((path for path in candidates if path.name != today), key=lambda item: item.name, reverse=True)


def extract_issue_records(payload: Any) -> List[Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}

    def add(cve_id: str, severity: str = "UNKNOWN") -> None:
        token = cve_id.strip()
        if not token:
            return
        normalized = token.upper() if CVE_PATTERN.fullmatch(token) else token
        records[normalized] = {"id": normalized, "severity": severity.upper() if severity else "UNKNOWN"}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            vuln_id = value.get("id") or value.get("cve") or value.get("vulnerabilityID") or value.get("ruleId")
            severity = str(value.get("severity") or value.get("level") or value.get("priority") or "UNKNOWN")
            if isinstance(vuln_id, str):
                match = CVE_PATTERN.search(vuln_id)
                if match:
                    add(match.group(0), severity)
                else:
                    add(vuln_id, severity)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for match in CVE_PATTERN.findall(value):
                severity_match = SEVERITY_PATTERN.search(value)
                add(match, severity_match.group(1) if severity_match else "UNKNOWN")

    walk(payload)
    return sorted(records.values(), key=lambda item: item["id"])


def parse_lcov_text(text: str) -> float | None:
    total = 0
    hit = 0
    for line in text.splitlines():
        if not line.startswith("DA:"):
            continue
        try:
            _, payload = line.split(":", 1)
            _, hits = payload.split(",", 1)
            total += 1
            if int(hits) > 0:
                hit += 1
        except ValueError:
            continue
    if not total:
        return None
    return round((hit / total) * 100, 2)


def extract_coverage_value(payload: Any) -> float | None:
    if isinstance(payload, (int, float)):
        return float(payload)
    if isinstance(payload, dict):
        for key in ("coverage", "line_coverage", "coverage_pct"):
            if key in payload:
                return extract_coverage_value(payload[key])
    if isinstance(payload, str):
        lcov = parse_lcov_text(payload)
        if lcov is not None:
            return lcov
        percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", payload)
        if percent_match:
            return float(percent_match.group(1))
        line_rate = re.search(r'line-rate="([0-9.]+)"', payload)
        if line_rate:
            return round(float(line_rate.group(1)) * 100, 2)
    return None


def select_previous_report(reports_dir: Path, report_type: str) -> Path | None:
    report_tokens = {
        "security": ("security", "audit", "vuln"),
        "image-scan": ("image", "scan", "trivy", "grype", "scout"),
        "coverage": ("coverage",),
    }[report_type]
    for dated_dir in dated_directories(reports_dir):
        for file_path in sorted(dated_dir.rglob("*")):
            if not file_path.is_file():
                continue
            name = file_path.name.lower()
            if any(token in name for token in report_tokens):
                return file_path
    return None


def parse_previous_report(report_path: Path, report_type: str) -> Any:
    payload = load_json(report_path)
    if payload is not None:
        if report_type == "coverage":
            return extract_coverage_value(payload)
        return extract_issue_records(payload)
    text = safe_read_text(report_path)
    if report_type == "coverage":
        return extract_coverage_value(text)
    return extract_issue_records(text)


def normalize_current_findings(report_type: str, current_findings: Any) -> Any:
    if report_type == "coverage":
        value = extract_coverage_value(current_findings)
        return round(value, 2) if value is not None else None
    if isinstance(current_findings, list):
        return extract_issue_records(current_findings)
    return extract_issue_records(current_findings)


def collect_sarif_findings(sarif_dir: Path) -> List[Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}
    for sarif_file in sorted(sarif_dir.rglob("*.sarif")):
        payload = load_json(sarif_file)
        if payload is None:
            continue
        for item in extract_issue_records(payload):
            records[item["id"]] = item
    return sorted(records.values(), key=lambda item: item["id"])


def render_summary_markdown(result: Dict[str, Any]) -> str:
    report_type = result.get("report_type", "unknown")
    previous = result.get("previous_report") or "none"
    lines = [
        f"# {report_type.title()} Comparison Report",
        "",
        f"- Previous report: {previous}",
        "",
    ]
    if report_type == "coverage":
        lines.extend(
            [
                f"- Previous coverage: {result.get('previous_value')}",
                f"- Current coverage: {result.get('current_value')}",
                f"- Regression detected: {result.get('regression_detected')}",
            ]
        )
        return "\n".join(lines) + "\n"

    new_issues = result.get("new_issues") or []
    fixed_issues = result.get("fixed_issues") or []
    unchanged = result.get("unchanged") or []
    lines.extend(
        [
            f"- New issues: {len(new_issues)}",
            f"- Fixed issues: {len(fixed_issues)}",
            f"- Unchanged issues: {len(unchanged)}",
            "",
            "## Current findings",
            "",
        ]
    )
    if unchanged or new_issues:
        current = {}
        for bucket in (unchanged, new_issues):
            for item in bucket:
                if isinstance(item, dict) and item.get("id"):
                    current[item["id"]] = item
        for key in sorted(current):
            item = current[key]
            lines.append(f"- {item.get('id')} ({item.get('severity', 'UNKNOWN')})")
    else:
        lines.append("- No findings detected")
    return "\n".join(lines) + "\n"


def check_previous_report(reports_dir: str | Path, report_type: str, current_findings: Any) -> Dict[str, Any]:
    """
    Compare current findings against the most recent previous report (n-1).
    - reports_dir: path like .github/reports/
    - report_type: 'security' | 'image-scan' | 'coverage'
    - current_findings: list of CVE IDs or coverage pct
    Returns: dict with new_issues, fixed_issues, regression_detected
    """
    base_dir = Path(reports_dir).expanduser().resolve()
    previous_report = select_previous_report(base_dir, report_type) if base_dir.exists() else None
    previous_findings = parse_previous_report(previous_report, report_type) if previous_report else None
    current = normalize_current_findings(report_type, current_findings)

    if report_type == "coverage":
        current_value = float(current) if current is not None else None
        previous_value = float(previous_findings) if previous_findings is not None else None
        regression = previous_value is not None and current_value is not None and current_value < previous_value
        return {
            "report_type": report_type,
            "previous_report": str(previous_report) if previous_report else None,
            "previous_value": previous_value,
            "current_value": current_value,
            "new_issues": [f"coverage decreased from {previous_value}% to {current_value}%"] if regression else [],
            "fixed_issues": [f"coverage increased from {previous_value}% to {current_value}%"] if previous_value is not None and current_value is not None and current_value > previous_value else [],
            "regression_detected": regression,
        }

    previous_map = {item["id"]: item for item in previous_findings or []}
    current_map = {item["id"]: item for item in current or []}
    new_ids = sorted(set(current_map) - set(previous_map))
    fixed_ids = sorted(set(previous_map) - set(current_map))
    unchanged_ids = sorted(set(previous_map) & set(current_map))
    regression = any(current_map[cve_id].get("severity", "UNKNOWN") in {"CRITICAL", "UNKNOWN"} for cve_id in new_ids)

    return {
        "report_type": report_type,
        "previous_report": str(previous_report) if previous_report else None,
        "new_issues": [current_map[cve_id] for cve_id in new_ids],
        "fixed_issues": [previous_map[cve_id] for cve_id in fixed_ids],
        "unchanged": [current_map[cve_id] for cve_id in unchanged_ids],
        "regression_detected": regression,
    }


def parse_current_input(args: argparse.Namespace) -> Any:
    if args.current_sarif_dir:
        return collect_sarif_findings(Path(args.current_sarif_dir).expanduser().resolve())
    if args.current_json:
        return json.loads(args.current_json)
    if args.current_file:
        payload = load_json(Path(args.current_file))
        return payload if payload is not None else safe_read_text(Path(args.current_file))
    if args.coverage is not None:
        return args.coverage
    raise ValueError("Provide --current-json, --current-file, or --coverage.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare workflow reports with the previous dated report.")
    parser.add_argument("--reports-dir", required=True, help="Report root such as .github/reports.")
    parser.add_argument("--report-type", required=True, choices=["security", "image-scan", "coverage"])
    parser.add_argument("--current-json", help="Current findings as JSON text.")
    parser.add_argument("--current-file", help="Current findings file to parse.")
    parser.add_argument("--current-sarif-dir", help="Directory containing SARIF files for image-scan mode.")
    parser.add_argument("--coverage", type=float, help="Coverage percentage for coverage mode.")
    parser.add_argument("--output-json", help="Optional output path for the structured comparison result.")
    parser.add_argument("--normalized-output", help="Optional output path for normalized current findings JSON.")
    parser.add_argument("--summary-markdown", help="Optional path to write a markdown summary.")
    parser.add_argument("--no-fail-on-regression", action="store_true", help="Always return 0 even when regression is detected.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        current = parse_current_input(args)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    normalized_current = normalize_current_findings(args.report_type, current)
    result = check_previous_report(args.reports_dir, args.report_type, current)
    if args.output_json:
        output_path = Path(args.output_json).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.normalized_output:
        normalized_path = Path(args.normalized_output).expanduser()
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text(json.dumps(normalized_current, indent=2), encoding="utf-8")
    if args.summary_markdown:
        summary_path = Path(args.summary_markdown).expanduser()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(render_summary_markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2))

    if result.get("regression_detected") and not args.no_fail_on_regression:
        new_items = result.get("new_issues") or []
        if args.report_type == "coverage":
            print(f"[ERROR] Coverage regression detected: {new_items[0]}", file=sys.stderr)
        else:
            detail = ", ".join(item["id"] for item in new_items if isinstance(item, dict)) or "new critical findings"
            print(f"[ERROR] Regression detected in {args.report_type}: {detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
