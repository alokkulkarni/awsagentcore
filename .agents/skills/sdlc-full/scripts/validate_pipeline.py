#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

PHASE_NAMES = ('Analysis', 'Architecture', 'Refinement', 'Development', 'Test', 'Review')
SOURCE_SUFFIXES = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.java', '.rs', '.kt', '.kts', '.cs', '.cpp', '.cc', '.c', '.h'
}
EXCLUDED_PARTS = {
    '.git', '.hg', '.svn', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', 'coverage'
}


@dataclass
class RuleResult:
    rule_id: str
    severity: str
    passed: bool
    message: str
    evidence: str = ''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate a completed SDLC pipeline run.')
    parser.add_argument('--project-root', default='.', help='Project root containing the pipeline artefacts.')
    parser.add_argument('--report', help='Explicit pipeline report path. Defaults to the latest pipeline-report-*.md file.')
    parser.add_argument('--output-json', action='store_true', help='Emit machine-readable JSON instead of text output.')
    return parser.parse_args()


def find_report(project_root: Path, explicit_report: Optional[str]) -> Optional[Path]:
    if explicit_report:
        report_path = Path(explicit_report)
        if not report_path.is_absolute():
            report_path = project_root / report_path
        return report_path
    candidates = sorted(project_root.glob('pipeline-report-*.md'))
    return candidates[-1] if candidates else None


def read_text(path: Optional[Path]) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ''
    return path.read_text(encoding='utf-8')


def parse_phase_table(report_text: str) -> Dict[str, Dict[str, str]]:
    phases: Dict[str, Dict[str, str]] = {}
    pattern = re.compile(
        r'^\|\s*(Analysis|Architecture|Refinement|Development|Test|Review)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]+?)\s*\|\s*$',
        re.MULTILINE,
    )
    for match in pattern.finditer(report_text):
        phases[match.group(1)] = {
            'status': match.group(2).strip(),
            'gate_result': match.group(3).strip(),
            'artifacts': match.group(4).strip(),
            'duration': match.group(5).strip(),
        }
    return phases


def find_latest_review_report(project_root: Path) -> Optional[Path]:
    review_dir = project_root / 'review'
    if not review_dir.exists():
        return None
    candidates = sorted(review_dir.glob('review-report-*.md'))
    return candidates[-1] if candidates else None


def find_analysis_report(project_root: Path) -> Optional[Path]:
    for candidate in (
        project_root / 'analysis/source-code-report.json',
        project_root / 'analysis/analysis-report.json',
        project_root / 'analysis/requirements.md',
    ):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def extract_comment_value(report_text: str, name: str) -> Optional[str]:
    match = re.search(rf'<!--\s*{re.escape(name)}:\s*(.*?)\s*-->', report_text)
    return match.group(1).strip() if match else None


def extract_coverage(report_text: str) -> Optional[float]:
    comment_value = extract_comment_value(report_text, 'test_coverage_percent')
    if comment_value:
        try:
            return float(comment_value)
        except ValueError:
            pass
    for pattern in (r'coverage[^\d]{0,10}(\d+(?:\.\d+)?)\s*%', r'(\d+(?:\.\d+)?)\s*%\s*coverage'):
        match = re.search(pattern, report_text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def count_changed_source_files(project_root: Path) -> int:
    try:
        result = subprocess.run(
            ['git', '--no-pager', 'status', '--porcelain'],
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode != 0:
        return 0
    count = 0
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        rel_path = line[3:].strip()
        if not rel_path:
            continue
        path = project_root / rel_path
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in SOURCE_SUFFIXES:
            count += 1
    return count


def analysis_has_requirements(path: Optional[Path]) -> bool:
    if path is None or not path.exists():
        return False
    if path.suffix == '.json':
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return False
        for key in ('requirements', 'functional_requirements', 'extracted_requirements'):
            value = data.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, dict) and value:
                return True
            if isinstance(value, str) and value.strip():
                return True
        return 'requirements' in json.dumps(data).lower()
    return 'requirement' in path.read_text(encoding='utf-8', errors='ignore').lower()


def review_is_clean(review_text: str) -> bool:
    lowered = review_text.lower()
    if not lowered:
        return False
    if re.search(r'\b([1-9]\d*)\s+critical\b', lowered):
        return False
    if re.search(r'\b([1-9]\d*)\s+high\b', lowered):
        return False
    return 'critical' not in lowered or '0 critical' in lowered


def review_is_passed(review_text: str) -> bool:
    lowered = review_text.lower()
    return 'passed' in lowered or ('0 critical' in lowered and '0 high' in lowered)


def evaluate_rules(project_root: Path, report_path: Optional[Path]) -> List[RuleResult]:
    report_exists = report_path is not None and report_path.exists() and report_path.is_file()
    report_text = read_text(report_path)
    phase_table = parse_phase_table(report_text)
    review_report_path = find_latest_review_report(project_root)
    review_text = read_text(review_report_path)
    analysis_report_path = find_analysis_report(project_root)
    architecture_hld = project_root / 'architecture/hld.md'
    backlog_summary = project_root / 'backlog/stories-summary.md'
    duration_value = extract_comment_value(report_text, 'total_duration_seconds') if report_text else None
    coverage_percent = extract_coverage(report_text)
    development_files = extract_comment_value(report_text, 'development_files_changed') if report_text else None

    if development_files is not None:
        try:
            generated_or_modified = int(float(development_files))
        except ValueError:
            generated_or_modified = 0
    else:
        generated_or_modified = count_changed_source_files(project_root)

    all_green = all(phase_table.get(phase, {}).get('status') == 'GREEN' for phase in PHASE_NAMES)
    duration_seconds = None
    if duration_value:
        try:
            duration_seconds = int(float(duration_value))
        except ValueError:
            duration_seconds = None

    return [
        RuleResult('PPL-001', 'CRITICAL', report_exists, 'pipeline-report file exists', str(report_path) if report_exists else 'No pipeline-report-*.md file found.'),
        RuleResult('PPL-002', 'CRITICAL', len(phase_table) == 6 and all_green, 'All 6 phases completed (GREEN status)', json.dumps(phase_table, indent=2) if phase_table else 'No complete phase table found.'),
        RuleResult('PPL-003', 'CRITICAL', bool(review_report_path) and review_is_clean(review_text), 'No CRITICAL security findings in review report', str(review_report_path) if review_report_path else 'No review report found.'),
        RuleResult('PPL-004', 'HIGH', analysis_has_requirements(analysis_report_path), 'Analysis report exists with requirements', str(analysis_report_path) if analysis_report_path else 'No analysis report found.'),
        RuleResult('PPL-005', 'HIGH', architecture_hld.exists() and architecture_hld.stat().st_size > 0, 'Architecture HLD exists', str(architecture_hld)),
        RuleResult('PPL-006', 'HIGH', backlog_summary.exists() and backlog_summary.stat().st_size > 0, 'Backlog stories summary exists', str(backlog_summary)),
        RuleResult('PPL-007', 'HIGH', generated_or_modified >= 1, 'At least one source file generated or modified', f'count={generated_or_modified}'),
        RuleResult('PPL-008', 'HIGH', coverage_percent is not None and coverage_percent >= 80.0, 'Test coverage ≥ 80%', f'coverage={coverage_percent if coverage_percent is not None else "unknown"}'),
        RuleResult('PPL-009', 'MEDIUM', bool(review_report_path) and review_is_passed(review_text), 'Review report exists and is PASSED', str(review_report_path) if review_report_path else 'No review report found.'),
        RuleResult('PPL-010', 'LOW', duration_seconds is not None and duration_seconds < 7200, 'Pipeline duration within expected bounds (< 2 hours)', f'duration_seconds={duration_seconds if duration_seconds is not None else "unknown"}'),
    ]


def print_text_report(results: Sequence[RuleResult]) -> None:
    for result in results:
        status = 'PASS' if result.passed else 'FAIL'
        print(f'{result.rule_id} {result.severity:<8} {status} - {result.message}')
        if result.evidence:
            print(f'  Evidence: {result.evidence}')
    passed = sum(1 for result in results if result.passed)
    failed = len(results) - passed
    print(f'\nSummary: {passed} passed, {failed} failed, {len(results)} total')


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    report_path = find_report(project_root, args.report)
    results = evaluate_rules(project_root, report_path)
    if args.output_json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        print_text_report(results)
    blocking_failure = any((not result.passed) and result.severity in {'CRITICAL', 'HIGH'} for result in results)
    return 1 if blocking_failure else 0


if __name__ == '__main__':
    raise SystemExit(main())
