#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Local SDLC review scanner for SAST, dependency CVEs, lint status, and coverage gates."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".venv", "venv", "target", "vendor", "__pycache__"}
CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"}
CRITICAL_PATH_HINTS = ("auth", "security", "login", "payment", "billing", "transfer", "crypto", "admin", "token")
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
}
VULNERABLE_DEPENDENCIES = {
    "python": {
        "pyyaml": {"lt": "5.4", "cve": "CVE-2020-14343", "cvss": 8.8, "fixed_in": "5.4", "severity": "HIGH", "issue": "PyYAML before 5.4 is vulnerable to unsafe loader RCE paths.", "cwe": "CWE-502"},
        "django": {"lt": "3.2.25", "cve": "CVE-2023-43665", "cvss": 7.5, "fixed_in": "3.2.25", "severity": "HIGH", "issue": "Django before 3.2.25 contains a denial-of-service security issue.", "cwe": "CWE-400"},
        "requests": {"lt": "2.32.2", "cve": "CVE-2024-35195", "cvss": 7.5, "fixed_in": "2.32.2", "severity": "HIGH", "issue": "Requests before 2.32.2 contains a netrc credential leak issue.", "cwe": "CWE-200"}
    },
    "node": {
        "lodash": {"lt": "4.17.21", "cve": "CVE-2021-23337", "cvss": 7.2, "fixed_in": "4.17.21", "severity": "HIGH", "issue": "lodash before 4.17.21 is vulnerable to command injection / template abuse.", "cwe": "CWE-94"},
        "minimist": {"lt": "1.2.6", "cve": "CVE-2021-44906", "cvss": 9.8, "fixed_in": "1.2.6", "severity": "CRITICAL", "issue": "minimist before 1.2.6 is vulnerable to prototype pollution.", "cwe": "CWE-1321"},
        "axios": {"lt": "1.6.0", "cve": "CVE-2023-45857", "cvss": 7.5, "fixed_in": "1.6.0", "severity": "HIGH", "issue": "axios before 1.6.0 is vulnerable to SSRF and credential leakage scenarios.", "cwe": "CWE-918"}
    }
}
GENERIC_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token|private[_-]?key|client[_-]?secret)\b\s*[:=]\s*['\"][^'\"]{6,}['\"]")
TODO_RE = re.compile(r"(?i)\b(?:TODO|FIXME|XXX)\b")


@dataclass
class Finding:
    id: str
    severity: str
    category: str
    file: str
    line: int
    issue: str
    recommendation: str
    cwe: str = ""
    source: str = "local"
    ticket: str = ""
    note: str = ""
    resolved: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def parse_list(values: Sequence[str] | None) -> List[str]:
    items: List[str] = []
    for value in values or []:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


def version_tuple(value: str) -> Tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", value)]
    return tuple(parts or [0])


def version_less_than(found: str, target: str) -> bool:
    left = list(version_tuple(found))
    right = list(version_tuple(target))
    size = max(len(left), len(right))
    left.extend([0] * (size - len(left)))
    right.extend([0] * (size - len(right)))
    return tuple(left) < tuple(right)


def extract_declared_version(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)+)", value)
    return match.group(1) if match else "0"


def detect_language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "unknown")


def is_relevant_file(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.name.startswith(".") and path.name not in {".env.example"}:
        return False
    if path.suffix.lower() in CODE_EXTENSIONS:
        return True
    return path.name in {"requirements.txt", "package.json"}


def discover_files(project_root: Path) -> List[Path]:
    return [path for path in project_root.rglob("*") if path.is_file() and is_relevant_file(path)]


def find_line_numbers(pattern: re.Pattern[str], text: str) -> Iterable[Tuple[int, str]]:
    for index, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            yield index, line.strip()


def make_finding(path: Path, line: int, rule_id: str, severity: str, category: str, issue: str, recommendation: str, cwe: str = "", **metadata: Any) -> Finding:
    return Finding(
        id=rule_id,
        severity=severity,
        category=category,
        file=path.as_posix(),
        line=line,
        issue=issue,
        recommendation=recommendation,
        cwe=cwe,
        metadata=metadata,
    )


def scan_python(path: Path, text: str) -> List[Finding]:
    findings: List[Finding] = []
    patterns = [
        (re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\b\s*=\s*['\"][^'\"]{8,}['\"]"), "REV-PY-001", "CRITICAL", "secret-detection", "Possible hardcoded secret detected in Python source.", "Move secrets to a vault or environment injection path.", "CWE-798"),
        (re.compile(r"(?:cursor|db)\.execute\(\s*(?:f['\"]|['\"].*[%+].*)"), "REV-PY-002", "HIGH", "sast", "Potential SQL injection pattern detected in Python SQL execution.", "Use parameterised queries instead of string interpolation.", "CWE-89"),
        (re.compile(r"\b(?:pickle\.loads?|yaml\.load\()"), "REV-PY-003", "HIGH", "sast", "Unsafe deserialisation pattern detected in Python source.", "Use safe loaders and never deserialize untrusted content.", "CWE-502"),
        (re.compile(r"\b(?:eval|exec)\s*\("), "REV-PY-004", "CRITICAL", "sast", "eval/exec detected in Python source.", "Remove dynamic code execution and use safer parsing patterns.", "CWE-95"),
        (re.compile(r"subprocess\.(?:run|Popen|call|check_output|check_call)\(.*shell\s*=\s*True"), "REV-PY-005", "HIGH", "sast", "subprocess invoked with shell=True.", "Use argument lists with shell=False to avoid command injection.", "CWE-78")
    ]
    for pattern, rule_id, severity, category, issue, recommendation, cwe in patterns:
        for line, _ in find_line_numbers(pattern, text):
            findings.append(make_finding(path, line, rule_id, severity, category, issue, recommendation, cwe))
    return findings


def scan_javascript(path: Path, text: str) -> List[Finding]:
    findings: List[Finding] = []
    patterns = [
        (re.compile(r"(?:__proto__|constructor\.prototype|lodash\.merge\(|Object\.assign\([^\n]+(?:req|body|params|query))"), "REV-JS-001", "HIGH", "sast", "Prototype pollution sink detected in JS/TS source.", "Sanitise attacker-controlled objects and block prototype keys such as __proto__.", "CWE-1321"),
        (re.compile(r"(?:innerHTML\s*=|dangerouslySetInnerHTML|document\.write\()"), "REV-JS-002", "HIGH", "sast", "Potential XSS sink detected in JS/TS source.", "Use safe DOM APIs or trusted sanitisation before rendering untrusted content.", "CWE-79"),
        (re.compile(r"\b(?:eval|new Function)\s*\("), "REV-JS-003", "CRITICAL", "sast", "Dynamic code execution detected in JS/TS source.", "Remove eval/new Function and replace with safe parsing or explicit dispatch.", "CWE-95"),
        (re.compile(r"(?:require\(['\"]child_process['\"]\)|from ['\"]child_process['\"])"), "REV-JS-004", "HIGH", "sast", "child_process import detected in JS/TS source.", "Avoid shell execution in request or build paths; validate all commands and arguments.", "CWE-78"),
        (re.compile(r"(?i)\b(api[_-]?key|secret|token)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"), "REV-JS-005", "CRITICAL", "secret-detection", "Possible hardcoded API key or credential detected in JS/TS source.", "Move API keys to secret storage and inject them at runtime.", "CWE-798")
    ]
    for pattern, rule_id, severity, category, issue, recommendation, cwe in patterns:
        for line, _ in find_line_numbers(pattern, text):
            findings.append(make_finding(path, line, rule_id, severity, category, issue, recommendation, cwe))
    return findings


def scan_generic(path: Path, text: str) -> List[Finding]:
    findings: List[Finding] = []
    for line, _ in find_line_numbers(GENERIC_SECRET_RE, text):
        findings.append(make_finding(path, line, "REV-GEN-001", "HIGH", "secret-detection", "Hardcoded credential pattern detected.", "Replace inline credentials with secret-manager references.", "CWE-798"))
    if any(hint in path.as_posix().lower() for hint in CRITICAL_PATH_HINTS):
        for line, _ in find_line_numbers(TODO_RE, text):
            findings.append(make_finding(path, line, "REV-GEN-002", "MEDIUM", "coding-standards", "TODO/FIXME remains in a critical execution path.", "Resolve or track the item in a ticket before merge."))
    random_patterns = [
        (re.compile(r"\brandom\.(?:random|randrange|randint|choice)\("), "REV-GEN-003", "MEDIUM", "coding-standards", "Non-cryptographic Python random source detected.", "Use secrets.SystemRandom or the secrets module for security-sensitive randomness.", "CWE-338"),
        (re.compile(r"\bMath\.random\s*\("), "REV-GEN-004", "MEDIUM", "coding-standards", "Math.random() detected in JS/TS source.", "Use crypto.getRandomValues() or a reviewed library for security-sensitive randomness.", "CWE-338")
    ]
    for pattern, rule_id, severity, category, issue, recommendation, cwe in random_patterns:
        for line, _ in find_line_numbers(pattern, text):
            findings.append(make_finding(path, line, rule_id, severity, category, issue, recommendation, cwe))
    return findings


def parse_requirements(path: Path) -> List[Tuple[str, str, int]]:
    items: List[Tuple[str, str, int]] = []
    for line_number, raw in enumerate(safe_read_text(path).splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*([<>=!~]+\s*[^;\s]+)?", line)
        if match:
            items.append((match.group(1).lower(), match.group(2) or "", line_number))
    return items


def parse_package_json(path: Path) -> List[Tuple[str, str, int]]:
    text = safe_read_text(path)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    items: List[Tuple[str, str, int]] = []
    for section in ("dependencies", "devDependencies"):
        deps = payload.get(section) or {}
        if not isinstance(deps, dict):
            continue
        for name, version in deps.items():
            line = 1
            needle = f'"{name}"'
            for index, raw in enumerate(text.splitlines(), start=1):
                if needle in raw:
                    line = index
                    break
            items.append((name.lower(), str(version), line))
    return items


def scan_dependency_manifest(path: Path) -> List[Finding]:
    if path.name == "requirements.txt":
        ecosystem = "python"
        packages = parse_requirements(path)
    elif path.name == "package.json":
        ecosystem = "node"
        packages = parse_package_json(path)
    else:
        return []
    findings: List[Finding] = []
    for package, declared, line in packages:
        entry = VULNERABLE_DEPENDENCIES[ecosystem].get(package)
        if not entry:
            continue
        found_version = extract_declared_version(declared)
        if version_less_than(found_version, entry["lt"]):
            findings.append(
                make_finding(
                    path,
                    line,
                    f"REV-DEP-{package.upper().replace('-', '_')}",
                    entry["severity"],
                    "dependency-cve",
                    f"{package} {declared or found_version} matches a vulnerable dependency rule ({entry['cve']}).",
                    f"Upgrade to {entry['fixed_in']} or later.",
                    entry["cwe"],
                    cve=entry["cve"],
                    cvss=entry["cvss"],
                    fixed_in=entry["fixed_in"],
                    package=package,
                    version=declared or found_version,
                )
            )
    return findings


def gather_manifests(project_root: Path, files: List[Path]) -> List[Path]:
    manifests = [path for path in files if path.name in {"requirements.txt", "package.json"}]
    for candidate in (project_root / "requirements.txt", project_root / "package.json"):
        if candidate.exists() and candidate not in manifests:
            manifests.append(candidate)
    return manifests


def run_command(command: List[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)


def lint_status(project_root: Path, files: List[Path]) -> Dict[str, Any]:
    python_files = [str(path.relative_to(project_root)) for path in files if path.suffix.lower() == ".py"]
    js_files = [str(path.relative_to(project_root)) for path in files if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}]
    checks: List[Dict[str, Any]] = []
    status = "clean"
    if python_files and shutil.which("ruff"):
        result = run_command(["ruff", "check", *python_files], project_root)
        checks.append({"tool": "ruff", "returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()})
        if result.returncode != 0:
            status = "failed"
    elif python_files:
        checks.append({"tool": "ruff", "returncode": None, "stdout": "", "stderr": "ruff not installed"})
        status = "unavailable"
    if js_files and shutil.which("eslint"):
        result = run_command(["eslint", *js_files], project_root)
        checks.append({"tool": "eslint", "returncode": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()})
        if result.returncode != 0:
            status = "failed"
    elif js_files:
        checks.append({"tool": "eslint", "returncode": None, "stdout": "", "stderr": "eslint not installed"})
        if status == "clean":
            status = "unavailable"
    if not python_files and not js_files:
        status = "not_applicable"
    return {"status": status, "checks": checks}


def parse_coverage(project_root: Path) -> Dict[str, Any]:
    candidates = [
        project_root / "coverage" / "coverage-summary.json",
        project_root / "coverage-summary.json",
        project_root / "coverage" / "lcov.info",
        project_root / "lcov.info",
        project_root / "coverage.xml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        if path.name.endswith("coverage-summary.json"):
            try:
                payload = json.loads(safe_read_text(path))
                total = payload.get("total", {})
                return {"source": path.as_posix(), "line": total.get("lines", {}).get("pct"), "branch": total.get("branches", {}).get("pct")}
            except json.JSONDecodeError:
                continue
        if path.name == "lcov.info":
            lines_found = lines_hit = branches_found = branches_hit = 0
            for raw in safe_read_text(path).splitlines():
                if raw.startswith("LF:"):
                    lines_found += int(raw.split(":", 1)[1])
                elif raw.startswith("LH:"):
                    lines_hit += int(raw.split(":", 1)[1])
                elif raw.startswith("BRF:"):
                    branches_found += int(raw.split(":", 1)[1])
                elif raw.startswith("BRH:"):
                    branches_hit += int(raw.split(":", 1)[1])
            return {
                "source": path.as_posix(),
                "line": round((lines_hit / lines_found) * 100, 2) if lines_found else None,
                "branch": round((branches_hit / branches_found) * 100, 2) if branches_found else None,
            }
        if path.name == "coverage.xml":
            try:
                root = ET.fromstring(safe_read_text(path))
            except ET.ParseError:
                continue
            line_rate = root.attrib.get("line-rate")
            branch_rate = root.attrib.get("branch-rate")
            return {
                "source": path.as_posix(),
                "line": round(float(line_rate) * 100, 2) if line_rate else None,
                "branch": round(float(branch_rate) * 100, 2) if branch_rate else None,
            }
    return {"source": None, "line": None, "branch": None}


def git_branch(project_root: Path) -> str:
    if not shutil.which("git"):
        return "unknown"
    result = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], project_root)
    return result.stdout.strip() or "unknown"


def collect_files(project_root: Path, requested: List[str]) -> List[Path]:
    if requested:
        results: List[Path] = []
        for value in requested:
            candidate = Path(value)
            candidate = candidate if candidate.is_absolute() else (project_root / candidate)
            candidate = candidate.resolve()
            if candidate.exists() and candidate.is_file():
                results.append(candidate)
        return results
    return discover_files(project_root)


def filter_by_threshold(findings: List[Finding], threshold: str) -> List[Finding]:
    limit = SEVERITY_ORDER[threshold.upper()]
    return [finding for finding in findings if SEVERITY_ORDER[finding.severity] <= limit]


def counts_for(findings: List[Finding]) -> Dict[str, int]:
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def table_rows(findings: List[Finding]) -> str:
    if not findings:
        return "| None | - | - | - | - | - | - |\n"
    rows = []
    for finding in findings:
        rows.append(f"| {finding.id} | {Path(finding.file).as_posix()} | {finding.line} | {finding.issue} | {finding.cwe or '-'} | {finding.severity} | {finding.recommendation} |")
    return "\n".join(rows) + "\n"


def dependency_rows(findings: List[Finding]) -> str:
    dep_findings = [finding for finding in findings if finding.category == "dependency-cve"]
    if not dep_findings:
        return "| None | - | - | - | - |\n"
    rows = []
    for finding in dep_findings:
        rows.append(f"| {finding.metadata.get('package', '-')} | {finding.metadata.get('version', '-')} | {finding.metadata.get('cve', '-')} | {finding.metadata.get('cvss', '-')} | {finding.metadata.get('fixed_in', '-')} |")
    return "\n".join(rows) + "\n"


def build_report(project_root: Path, files: List[Path], findings: List[Finding], coverage: Dict[str, Any], lint: Dict[str, Any], threshold: str) -> str:
    counts = counts_for(findings)
    critical = [finding for finding in findings if finding.severity == "CRITICAL"]
    high = [finding for finding in findings if finding.severity == "HIGH"]
    medium_low = [finding for finding in findings if finding.severity in {"MEDIUM", "LOW"}]
    merge_failed = bool(critical or high or any(f.category == "secret-detection" for f in findings) or any((f.metadata.get("cvss") or 0) >= 7.0 for f in findings if f.category == "dependency-cve") or (coverage.get("line") is not None and coverage["line"] < 80))
    status_badge = "✅ PASSED" if not merge_failed else "⛔ FAILED"
    recommendation = (
        "No blocking CRITICAL/HIGH findings remain and all merge gates are satisfied."
        if not merge_failed
        else "Blocking security or quality gates remain unresolved. Resolve CRITICAL/HIGH issues, secrets, high-CVSS dependencies, or coverage deficits before merging."
    )
    files_list = "\n".join(f"- {path.relative_to(project_root).as_posix()}" for path in files) or "- none"
    generated_now = datetime.now(timezone.utc)
    return f"""# SDLC Review Report

## Report metadata

- Date: {generated_now.strftime('%Y-%m-%d %H:%M UTC')}
- Reviewer: {os.environ.get('USER', 'agent')}
- Branch: {git_branch(project_root)}
- Severity threshold: {threshold.upper()}
- Files reviewed:
{files_list}

## Executive Summary

**Status:** {status_badge}

- Total findings: {len(findings)}
- Critical: {counts['CRITICAL']}
- High: {counts['HIGH']}
- Medium: {counts['MEDIUM']}
- Low: {counts['LOW']}
- Lint status: {lint.get('status', 'unknown')}

## Critical Findings

| ID | File | Line | Issue | CWE | Severity | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
{table_rows(critical)}
## High Findings

| ID | File | Line | Issue | CWE | Severity | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
{table_rows(high)}
## Medium/Low Findings

| ID | File | Line | Issue | CWE | Severity | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
{table_rows(medium_low)}
## Dependency CVE Summary

| Package | Version | CVE | CVSS | Fixed In |
| --- | --- | --- | --- | --- |
{dependency_rows(findings)}
## Coverage Summary

- Source: {coverage.get('source') or 'Not found'}
- Line coverage: {coverage.get('line') if coverage.get('line') is not None else 'Not available'}
- Branch coverage: {coverage.get('branch') if coverage.get('branch') is not None else 'Not available'}

## Merge Recommendation

**{'PASSED' if not merge_failed else 'FAILED'}** — {recommendation}

## Remediation Guidance

1. Remove or externalise any hardcoded credentials immediately.
2. Upgrade vulnerable dependencies to the documented fixed versions.
3. Replace dangerous execution patterns (`eval`, `shell=True`, child_process, unsafe deserialisation) with safe alternatives.
4. Capture tickets or exception notes for medium findings that cannot be fixed in the current change set.
5. Re-run review and validation after remediation.
"""


def dedupe_findings(findings: List[Finding]) -> List[Finding]:
    seen = set()
    deduped: List[Finding] = []
    for finding in findings:
        key = (finding.id, finding.file, finding.line, finding.issue)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    deduped.sort(key=lambda item: (SEVERITY_ORDER[item.severity], item.file, item.line, item.id))
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local SDLC review scan and write markdown/JSON reports.")
    parser.add_argument("--files", nargs="*", help="Comma-separated or repeated list of files to review.")
    parser.add_argument("--project-root", default=".", help="Project root to scan.")
    parser.add_argument("--output", help="Markdown report output path. Defaults to review/review-report-YYYYMMDD-HHMM.md")
    parser.add_argument("--severity-threshold", choices=["critical", "high", "medium", "low"], default="high")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    requested = parse_list(args.files)
    files = [path for path in collect_files(project_root, requested) if path.exists() and path.is_file()]
    findings: List[Finding] = []
    for path in files:
        if path.name in {"requirements.txt", "package.json"}:
            continue
        text = safe_read_text(path)
        language = detect_language(path)
        if language == "python":
            findings.extend(scan_python(path, text))
        elif language in {"javascript", "typescript"}:
            findings.extend(scan_javascript(path, text))
        findings.extend(scan_generic(path, text))
    for manifest in gather_manifests(project_root, files):
        findings.extend(scan_dependency_manifest(manifest))
        if manifest not in files:
            files.append(manifest)
    findings = dedupe_findings(findings)
    coverage = parse_coverage(project_root)
    lint = lint_status(project_root, files)
    generated_now = datetime.now(timezone.utc)
    timestamp = generated_now.strftime("%Y%m%d-%H%M")
    report_path = Path(args.output).expanduser() if args.output else project_root / "review" / f"review-report-{timestamp}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = report_path.with_suffix(".json")
    report = build_report(project_root, files, findings, coverage, lint, args.severity_threshold)
    payload = {
        "generated_at": generated_now.isoformat(),
        "project_root": project_root.as_posix(),
        "branch": git_branch(project_root),
        "files_reviewed": [path.relative_to(project_root).as_posix() if path.is_relative_to(project_root) else path.as_posix() for path in files],
        "severity_threshold": args.severity_threshold,
        "summary": counts_for(findings),
        "coverage": coverage,
        "lint": lint,
        "findings": [asdict(finding) for finding in findings],
        "report_path": report_path.as_posix(),
    }
    report_path.write_text(report, encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(report_path.as_posix())
    print(json_path.as_posix())
    findings_failed = bool(filter_by_threshold(findings, args.severity_threshold))
    validator = Path(__file__).with_name("validate_review.py")
    validation = subprocess.run(
        [sys.executable, str(validator), str(report_path), "--project-root", str(project_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    if validation.stdout:
        print(validation.stdout.rstrip())
    if validation.stderr:
        print(validation.stderr.rstrip(), file=sys.stderr)
    if validation.returncode != 0:
        return validation.returncode
    return 1 if findings_failed else 0


if __name__ == "__main__":
    sys.exit(main())
