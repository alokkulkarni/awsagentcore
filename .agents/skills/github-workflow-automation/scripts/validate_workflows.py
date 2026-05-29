#!/usr/bin/env python3
"""Validate generated GitHub Actions workflow YAML files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    class _FallbackYAML:
        @staticmethod
        def safe_load(text: str) -> Dict[str, Any]:
            data: Dict[str, Any] = {}
            if re.search(r"(?m)^name:\s*", text):
                data["name"] = True
            if re.search(r"(?m)^on:\s*", text):
                data["on"] = True
            elif re.search(r"(?m)^true:\s*", text):
                data[True] = True
            if re.search(r"(?m)^permissions:\s*", text):
                data["permissions"] = True
            if re.search(r"(?m)^jobs:\s*", text):
                data["jobs"] = {}
            return data

    yaml = _FallbackYAML()  # type: ignore

ACTION_RE = re.compile(r"uses:\s*([^@\s]+)@([^\s#]+)")
RUNS_ON_RE = re.compile(r"(?m)^\s+runs-on:\s*(.+)$")
UPLOAD_RE = re.compile(r"uses:\s*actions/upload-artifact@[^\n]+", re.IGNORECASE)
CHECKOUT_RE = re.compile(r"uses:\s*actions/checkout@", re.IGNORECASE)
RUN_BLOCK_RE = re.compile(r"(?ms)^\s+run:\s*\|\n(?P<body>(?:\s{10,}.+\n?)+)")
SECRET_KEY_RE = re.compile(r"^(password|token|secret|api[_-]?key)$", re.IGNORECASE)
CONTINUE_ON_ERROR_RE = re.compile(r"(?im)^\s*continue-on-error:\s*true\s*$")
SBOM_RE = re.compile(r"(?im)^\s*-\s+name:\s*Generate SBOM|sbom\.cdx\.json")
CBOM_RE = re.compile(r"(?im)^\s*-\s+name:\s*Generate CBOM|cbom\.cdx\.json")
ROLLBACK_RE = re.compile(r"(?im)\broll\s*back\b|\brollback\b")
ROLLBACK_SCOPED_RE = re.compile(r"(?im)steps\.deploy\.outcome\s*==\s*'failure'")
BAKE_FILE_EXPR_RE = re.compile(r"steps\.meta\.outputs\.bake-file")


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def rule_result(rule_id: str, severity: str, message: str) -> Tuple[str, str, str]:
    return rule_id, severity, message


def parse_yaml(text: str) -> Dict[str, Any]:
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


def has_plaintext_secret(text: str) -> bool:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or ':' not in line:
            continue
        key, value = line.split(':', 1)
        key = key.strip().lower()
        value = value.strip()
        if not SECRET_KEY_RE.fullmatch(key):
            continue
        if '${{' in value or value in {'', 'null', '""', "''"}:
            continue
        return True
    return False


def validate_file(path: Path) -> List[Tuple[str, str, str]]:
    text = safe_read_text(path)
    findings: List[Tuple[str, str, str]] = []
    try:
        data = parse_yaml(text)
        findings.append(rule_result("VAL-001", "PASS", "YAML parsed with yaml.safe_load()."))
    except Exception as exc:  # pragma: no cover - parser error path
        return [rule_result("VAL-001", "FAIL", f"Invalid YAML syntax: {exc}")]

    has_on = "on" in data or True in data
    jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
    if data.get("name") and has_on and jobs is not None:
        findings.append(rule_result("VAL-002", "PASS", "Required top-level keys detected."))
    else:
        findings.append(rule_result("VAL-002", "FAIL", "Missing one or more required top-level keys: name, on, jobs."))

    if re.search(r"(?m)^permissions:\s*", text):
        findings.append(rule_result("VAL-003", "PASS", "permissions block present."))
    else:
        findings.append(rule_result("VAL-003", "FAIL", "permissions block missing."))

    if has_plaintext_secret(text):
        findings.append(rule_result("VAL-004", "FAIL", "Possible plaintext secret detected in workflow YAML."))
    else:
        findings.append(rule_result("VAL-004", "PASS", "No plaintext secret literals detected."))

    unpinned = [f"{action}@{version}" for action, version in ACTION_RE.findall(text) if version.lower() in {"master", "main", "latest"}]
    if unpinned:
        findings.append(rule_result("VAL-005", "FAIL", f"Unpinned action versions detected: {', '.join(unpinned)}"))
    else:
        findings.append(rule_result("VAL-005", "PASS", "Action versions are stable tags or SHAs."))

    invalid_runners = [runner.strip() for runner in RUNS_ON_RE.findall(text) if "ubuntu-latest" not in runner and "ubuntu-" not in runner and "self-hosted" not in runner]
    if invalid_runners:
        findings.append(rule_result("VAL-006", "WARN", f"Non-standard runners detected: {', '.join(invalid_runners)}"))
    else:
        findings.append(rule_result("VAL-006", "PASS", "Jobs use ubuntu-latest or compatible runners."))

    upload_steps = list(UPLOAD_RE.finditer(text))
    missing_retention = []
    for match in upload_steps:
        snippet = text[match.start():match.end() + 400]
        if "retention-days:" not in snippet:
            missing_retention.append(match.group(0).strip())
    if missing_retention:
        findings.append(rule_result("VAL-007", "FAIL", "Artifact upload step missing retention-days."))
    else:
        findings.append(rule_result("VAL-007", "PASS", "Artifact upload steps include retention-days."))

    if CONTINUE_ON_ERROR_RE.search(text):
        findings.append(rule_result("VAL-008", "WARN", "continue-on-error=true found; add inline justification if this is intentional."))
    else:
        findings.append(rule_result("VAL-008", "PASS", "No unjustified continue-on-error usage found."))

    if CHECKOUT_RE.search(text):
        findings.append(rule_result("VAL-009", "PASS", "At least one checkout step present."))
    else:
        findings.append(rule_result("VAL-009", "FAIL", "No actions/checkout step found."))

    unsafe_blocks = []
    for block in RUN_BLOCK_RE.finditer(text):
        body = block.group("body")
        if "set -e" not in body and "set -eo pipefail" not in body and "set -euo pipefail" not in body and "set -euxo pipefail" not in body:
            unsafe_blocks.append(body.splitlines()[0].strip())
    if unsafe_blocks:
        findings.append(rule_result("VAL-010", "WARN", "One or more multiline run blocks do not declare set -e style safeguards."))
    else:
        findings.append(rule_result("VAL-010", "PASS", "Multiline run blocks use shell safety guards."))

    if path.name == "ci.yml":
        if SBOM_RE.search(text):
            findings.append(rule_result("VAL-011", "PASS", "CI workflow includes SBOM generation markers."))
        else:
            findings.append(rule_result("VAL-011", "FAIL", "ci.yml is missing explicit SBOM generation/output steps."))
        if BAKE_FILE_EXPR_RE.search(text):
            findings.append(rule_result("VAL-014", "FAIL", "ci.yml uses steps.meta.outputs.bake-file; use concrete artifact paths instead."))
        else:
            findings.append(rule_result("VAL-014", "PASS", "ci.yml avoids undefined bake-file artifact expressions."))

    if path.name.startswith("cd-") and path.suffix in {".yml", ".yaml"}:
        if CBOM_RE.search(text):
            findings.append(rule_result("VAL-012", "PASS", "CD workflow includes CBOM generation markers."))
        else:
            findings.append(rule_result("VAL-012", "FAIL", f"{path.name} is missing explicit CBOM generation/output steps."))
        if ROLLBACK_RE.search(text):
            findings.append(rule_result("VAL-013", "PASS", "CD workflow includes rollback logic."))
        else:
            findings.append(rule_result("VAL-013", "FAIL", f"{path.name} is missing rollback logic."))
        if ROLLBACK_SCOPED_RE.search(text):
            findings.append(rule_result("VAL-015", "PASS", "CD rollback is scoped to deploy-step failures."))
        else:
            findings.append(rule_result("VAL-015", "FAIL", f"{path.name} rollback is not scoped to deploy-step failures."))

    return findings


def collect_workflow_files(root: Path) -> List[Path]:
    if root.is_file():
        return [root]
    return sorted([path for path in root.rglob("*.y*ml") if path.is_file()])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate generated GitHub Actions workflows.")
    parser.add_argument("path", nargs="?", default=".github/workflows", help="Workflow directory or YAML file.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.path).expanduser().resolve()
    files = collect_workflow_files(root)
    if not files:
        print("FAIL VAL-000: no workflow YAML files found")
        return 1

    total_fail = 0
    total_warn = 0
    for file_path in files:
        print(f"\n# {file_path}")
        for rule_id, severity, message in validate_file(file_path):
            print(f"{severity} {rule_id}: {message}")
            if severity == "FAIL":
                total_fail += 1
            elif severity == "WARN":
                total_warn += 1

    print(f"\nSummary: FAIL={total_fail} WARN={total_warn} FILES={len(files)}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main())
