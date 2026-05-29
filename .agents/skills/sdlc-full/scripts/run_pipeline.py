#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SOURCE_SUFFIXES = {
    '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.java', '.rs', '.kt', '.kts', '.cs', '.cpp', '.cc', '.c', '.h'
}
EXCLUDED_PARTS = {
    '.git', '.hg', '.svn', 'node_modules', '.venv', 'venv', '__pycache__', 'dist', 'build', 'coverage'
}


@dataclass(frozen=True)
class PhaseDefinition:
    key: str
    label: str
    skill_dir: str
    scripts: Sequence[str]
    validators: Sequence[str]
    artifact_targets: Sequence[str]


@dataclass
class PhaseResult:
    key: str
    label: str
    status: str
    gate_result: str
    duration_seconds: float = 0.0
    artifacts: List[str] = field(default_factory=list)
    summary: str = ''
    warnings: List[str] = field(default_factory=list)
    command: str = ''
    validator_command: str = ''
    output: str = ''
    validation_output: str = ''
    files_changed: int = 0
    coverage_percent: Optional[float] = None


PHASES: Sequence[PhaseDefinition] = (
    PhaseDefinition('analysis', 'Analysis', 'sdlc-analyse', ('scripts/run_analysis.py',), ('scripts/validate_analysis.py',), ('analysis',)),
    PhaseDefinition('architecture', 'Architecture', 'sdlc-architecture', ('scripts/generate_architecture.py',), ('scripts/validate_architecture.py',), ('architecture',)),
    PhaseDefinition('refinement', 'Refinement', 'sdlc-backlog', ('scripts/generate_backlog.py',), ('scripts/validate_backlog.py', 'scripts/validate_refinement.py'), ('backlog',)),
    PhaseDefinition('development', 'Development', 'sdlc-codegen', ('scripts/scaffold_project.py',), ('scripts/validate_codegen.py', 'scripts/validate_development.py'), ()),
    PhaseDefinition('test', 'Test', 'sdlc-test', ('scripts/generate_tests.py',), ('scripts/validate_tests.py', 'scripts/validate_test.py'), ('coverage', 'reports', 'tests', 'test-results')),
    PhaseDefinition('review', 'Review', 'sdlc-review', ('scripts/run_review.py',), ('scripts/validate_review.py',), ('review',)),
)
PHASE_INDEX = {phase.key: index for index, phase in enumerate(PHASES)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the local SDLC fallback pipeline.')
    parser.add_argument('--project-root', default='.', help='Project root to run the pipeline in.')
    parser.add_argument('--feature', default='', help='Feature or scope description for the pipeline run.')
    parser.add_argument(
        '--start-phase',
        default='analysis',
        choices=[phase.key for phase in PHASES],
        help='First phase to execute. Earlier phases will be marked as skipped.',
    )
    parser.add_argument('--dry-run', action='store_true', help='Print the planned commands without executing them.')
    return parser.parse_args()


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}'


def quote_command(command: Sequence[str]) -> str:
    return ' '.join(subprocess.list2cmdline([part]) for part in command)


def discover_script(skill_root: Path, candidates: Sequence[str]) -> Optional[Path]:
    for candidate in candidates:
        path = skill_root / candidate
        if path.exists():
            return path
    return None


def build_commands(script_path: Path, project_root: Path, feature: str, dry_run: bool, *, for_validator: bool = False) -> List[List[str]]:
    feature = feature.strip()
    commands: List[List[str]] = []
    common = [sys.executable, str(script_path), '--project-root', str(project_root)]
    if not for_validator:
        for flag in ('--feature', '--input', '--scope'):
            command = list(common)
            if feature:
                command.extend([flag, feature])
            if dry_run:
                command.append('--dry-run')
            commands.append(command)
        command = [sys.executable, str(script_path)]
        if feature:
            command.append(feature)
        if dry_run:
            command.append('--dry-run')
        commands.append(command)
    else:
        commands.append(list(common))
        commands.append([sys.executable, str(script_path), str(project_root)])
        commands.append([sys.executable, str(script_path)])
    unique: List[List[str]] = []
    seen = set()
    for command in commands:
        marker = tuple(command)
        if marker in seen:
            continue
        unique.append(command)
        seen.add(marker)
    return unique


def run_first_success(commands: Sequence[Sequence[str]], cwd: Path) -> Tuple[subprocess.CompletedProcess[str], str]:
    last_result: Optional[subprocess.CompletedProcess[str]] = None
    last_command_text = ''
    for command in commands:
        result = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=3600,
            check=False,
        )
        command_text = quote_command(command)
        last_result = result
        last_command_text = command_text
        if result.returncode == 0:
            return result, command_text
        combined = f'{result.stdout}\n{result.stderr}'.lower()
        if 'unrecognized arguments' in combined or 'usage:' in combined or 'the following arguments are required' in combined:
            continue
        return result, command_text
    if last_result is None:
        raise RuntimeError('No commands were generated for execution.')
    return last_result, last_command_text


def ensure_phase_directories(project_root: Path) -> None:
    for directory_name in ('analysis', 'architecture', 'backlog', 'review'):
        (project_root / directory_name).mkdir(parents=True, exist_ok=True)


def snapshot_sources(project_root: Path) -> Dict[str, Tuple[int, int]]:
    snapshot: Dict[str, Tuple[int, int]] = {}
    for path in project_root.rglob('*'):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        stat = path.stat()
        snapshot[str(path.relative_to(project_root))] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def diff_source_paths(before: Dict[str, Tuple[int, int]], after: Dict[str, Tuple[int, int]]) -> List[str]:
    changed: List[str] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) != after.get(path):
            changed.append(path)
    return changed


def count_source_changes(before: Dict[str, Tuple[int, int]], after: Dict[str, Tuple[int, int]]) -> int:
    return len(diff_source_paths(before, after))


def gather_artifacts(project_root: Path, targets: Sequence[str]) -> List[str]:
    artifacts: List[str] = []
    seen = set()
    for target in targets:
        path = project_root / target
        if not path.exists():
            continue
        if path.is_file():
            rel = str(path.relative_to(project_root))
            if rel not in seen:
                artifacts.append(rel)
                seen.add(rel)
            continue
        for child in sorted(path.rglob('*')):
            if not child.is_file():
                continue
            rel = str(child.relative_to(project_root))
            if rel not in seen:
                artifacts.append(rel)
                seen.add(rel)
    return artifacts


def extract_coverage(text: str) -> Optional[float]:
    import re

    for pattern in (r'coverage[^\d]{0,10}(\d+(?:\.\d+)?)\s*%', r'(\d+(?:\.\d+)?)\s*%\s*coverage'):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def summarize_output(output: str, fallback: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return fallback
    return lines[0][:240]


def write_report(
    project_root: Path,
    pipeline_id: str,
    feature: str,
    start_phase: str,
    started_at: datetime,
    total_duration_seconds: float,
    results: Sequence[PhaseResult],
    halted_phase: Optional[PhaseResult],
) -> Path:
    report_path = project_root / f'pipeline-report-{started_at:%Y%m%d}.md'
    green_phases = sum(1 for result in results if result.status == 'GREEN')
    development_changes = next((result.files_changed for result in results if result.key == 'development'), 0)
    coverage_percent = next((result.coverage_percent for result in results if result.key == 'test' and result.coverage_percent is not None), None)
    review_summary = next((result.summary for result in results if result.key == 'review'), 'Review phase not executed.')
    if halted_phase is not None:
        overall_status = f'⛔ HALTED AT PHASE {PHASE_INDEX[halted_phase.key] + 1} ({halted_phase.label})'
    elif green_phases == len(PHASES):
        overall_status = '✅ COMPLETE'
    else:
        overall_status = '⚠️ COMPLETE WITH SKIPPED PHASES'

    phase_rows = []
    for result in results:
        artifact_text = ', '.join(f'`{artifact}`' for artifact in result.artifacts[:6]) or '—'
        if len(result.artifacts) > 6:
            artifact_text += f' (+{len(result.artifacts) - 6} more)'
        phase_rows.append(
            f'| {result.label} | {result.status} | {result.gate_result} | {artifact_text} | {format_duration(result.duration_seconds)} |'
        )
    phase_rows_text = '\n'.join(phase_rows)

    sections = []
    for index, result in enumerate(results, start=1):
        warning_block = ''
        if result.warnings:
            warning_lines = '\n'.join(f'- {warning}' for warning in result.warnings)
            warning_block = f'\nWarnings:\n{warning_lines}\n'
        command_block = ''
        if result.command:
            command_block += f'\nCommand: `{result.command}`'
        if result.validator_command:
            command_block += f'\nValidator: `{result.validator_command}`'
        sections.append(
            textwrap.dedent(
                f'''
                ## Phase {index}: {result.label} Summary

                - Status: **{result.status}**
                - Gate Result: **{result.gate_result}**
                - Duration: **{format_duration(result.duration_seconds)}**
                - Artefacts: {', '.join(f'`{artifact}`' for artifact in result.artifacts) or 'None detected'}
                - Summary: {result.summary or 'No summary available.'}{command_block}{warning_block}
                '''
            ).strip()
        )
    sections_text = '\n\n'.join(sections)

    report_text = textwrap.dedent(
        f'''
        # SDLC Pipeline Execution Report

        - Pipeline ID: `{pipeline_id}`
        - Project: `{project_root.name}`
        - Date: `{started_at:%Y-%m-%d %H:%M:%S}`
        - Feature: {feature or 'Not provided'}
        - Start Phase: `{start_phase}`
        - Total Duration: `{format_duration(total_duration_seconds)}`
        <!-- pipeline_id: {pipeline_id} -->
        <!-- total_duration_seconds: {int(round(total_duration_seconds))} -->
        <!-- development_files_changed: {development_changes} -->
        <!-- test_coverage_percent: {'' if coverage_percent is None else coverage_percent} -->

        ## Phase Summary Table

        | Phase | Status | Gate Result | Artefacts | Duration |
        | --- | --- | --- | --- | --- |
        {phase_rows_text}

        {sections_text}

        ## Overall Pipeline Status

        {overall_status}

        ## DORA Metrics Baseline

        - Lead time for changes: `{format_duration(total_duration_seconds)}` for this local pipeline run
        - Deployment frequency: `Not measured in fallback mode`
        - Mean time to restore (MTTR): `Not measured in fallback mode`
        - Change failure rate: `Use review + test failure data to establish baseline`

        ## Next Steps

        - If any phase is not GREEN, remediate the blocking phase before rerunning from that phase.
        - If the review phase is GREEN, prepare merge or deployment approvals.
        - Re-run `python3 .agents/skills/sdlc-full/scripts/validate_pipeline.py --project-root {project_root}` to confirm the completed pipeline meets gate requirements.
        - Review summary snapshot: {review_summary}
        '''
    ).strip() + '\n'
    report_path.write_text(report_text, encoding='utf-8')
    return report_path


def execute_phase(project_root: Path, feature: str, phase: PhaseDefinition, dry_run: bool) -> Tuple[PhaseResult, bool]:
    sibling_root = Path(__file__).resolve().parents[2]
    skill_root = sibling_root / phase.skill_dir
    result = PhaseResult(key=phase.key, label=phase.label, status='PENDING', gate_result='PENDING')
    if not skill_root.exists():
        result.status = 'SKIPPED'
        result.gate_result = 'SKIPPED'
        result.summary = f'Sibling skill directory not found: {phase.skill_dir}'
        result.warnings.append(result.summary)
        return result, False

    script_path = discover_script(skill_root, phase.scripts)
    if script_path is None:
        result.status = 'SKIPPED'
        result.gate_result = 'SKIPPED'
        result.summary = f'No phase script found in {phase.skill_dir}'
        result.warnings.append(result.summary)
        return result, False

    before_snapshot = snapshot_sources(project_root) if phase.key == 'development' else {}
    start = time.time()
    if dry_run:
        commands = build_commands(script_path, project_root, feature, dry_run=True)
        result.status = 'DRY-RUN'
        result.gate_result = 'NOT-RUN'
        result.command = quote_command(commands[0])
        result.summary = 'Dry run only — phase not executed.'
        result.artifacts = gather_artifacts(project_root, phase.artifact_targets)
        return result, False

    commands = build_commands(script_path, project_root, feature, dry_run=False)
    execution, command_text = run_first_success(commands, project_root)
    result.command = command_text
    result.output = '\n'.join(part for part in (execution.stdout.strip(), execution.stderr.strip()) if part).strip()
    result.duration_seconds = time.time() - start
    result.artifacts = gather_artifacts(project_root, phase.artifact_targets)
    result.summary = summarize_output(result.output, f'{phase.label} phase executed.')
    if phase.key == 'development':
        after_snapshot = snapshot_sources(project_root)
        result.files_changed = count_source_changes(before_snapshot, after_snapshot)
        result.artifacts = diff_source_paths(before_snapshot, after_snapshot)
    if phase.key == 'test':
        result.coverage_percent = extract_coverage(result.output)

    if execution.returncode != 0:
        result.status = 'RED'
        result.gate_result = 'FAILED'
        if not result.summary:
            result.summary = f'{phase.label} script failed with exit code {execution.returncode}.'
        return result, True

    validator_path = discover_script(skill_root, phase.validators)
    if validator_path is None:
        result.status = 'RED'
        result.gate_result = 'ERROR'
        result.summary = f'Mandatory validator missing in {phase.skill_dir}.'
        result.warnings.append(f'No validator found in {phase.skill_dir}; pipeline gate cannot be enforced.')
        return result, True

    validator_commands = build_commands(validator_path, project_root, feature, dry_run=False, for_validator=True)
    validation, validator_command = run_first_success(validator_commands, project_root)
    result.validator_command = validator_command
    result.validation_output = '\n'.join(part for part in (validation.stdout.strip(), validation.stderr.strip()) if part).strip()
    if phase.key == 'test' and result.coverage_percent is None:
        result.coverage_percent = extract_coverage(result.validation_output)
    if validation.returncode == 0:
        result.status = 'GREEN'
        result.gate_result = 'PASSED' if phase.key == 'review' else 'GREEN'
        return result, False
    if validation.returncode == 1:
        result.status = 'RED'
        result.gate_result = 'RED'
        if result.validation_output:
            result.summary = summarize_output(result.validation_output, result.summary or f'{phase.label} validation failed.')
        return result, True
    result.status = 'RED'
    result.gate_result = f'ERROR ({validation.returncode})'
    result.summary = summarize_output(result.validation_output, f'{phase.label} validator failed unexpectedly.')
    return result, True


def print_summary(results: Sequence[PhaseResult], report_path: Path, halted_phase: Optional[PhaseResult]) -> None:
    print('SDLC pipeline summary')
    print('---------------------')
    for result in results:
        print(f'{result.label:13} {result.status:10} gate={result.gate_result:8} duration={format_duration(result.duration_seconds)}')
    print(f'Report: {report_path}')
    if halted_phase is not None:
        print(f'Gate failure: {halted_phase.label} — {halted_phase.summary}')


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    ensure_phase_directories(project_root)

    pipeline_started_at = datetime.now()
    pipeline_id = f'PIPELINE-{pipeline_started_at:%Y%m%d-%H%M%S}'
    pipeline_start = time.time()
    start_index = PHASE_INDEX[args.start_phase]
    results: List[PhaseResult] = []
    halted_phase: Optional[PhaseResult] = None

    for index, phase in enumerate(PHASES):
        if index < start_index:
            results.append(
                PhaseResult(
                    key=phase.key,
                    label=phase.label,
                    status='SKIPPED',
                    gate_result='SKIPPED',
                    summary=f'Skipped because --start-phase={args.start_phase}.',
                )
            )
            continue

        phase_result, should_halt = execute_phase(project_root, args.feature, phase, args.dry_run)
        results.append(phase_result)
        if should_halt:
            halted_phase = phase_result
            break

    if halted_phase is not None and len(results) < len(PHASES):
        for phase in PHASES[len(results):]:
            results.append(
                PhaseResult(
                    key=phase.key,
                    label=phase.label,
                    status='NOT-RUN',
                    gate_result='NOT-RUN',
                    summary=f'Blocked because pipeline halted at {halted_phase.label}.',
                )
            )

    total_duration = time.time() - pipeline_start
    report_path = write_report(
        project_root=project_root,
        pipeline_id=pipeline_id,
        feature=args.feature,
        start_phase=args.start_phase,
        started_at=pipeline_started_at,
        total_duration_seconds=total_duration,
        results=results,
        halted_phase=halted_phase,
    )
    print_summary(results, report_path, halted_phase)
    return 1 if halted_phase is not None else 0


if __name__ == '__main__':
    raise SystemExit(main())
