#!/usr/bin/env python3
"""Check direct dependency versions for safe upgrades."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen
from typing import Any, Dict, List, Sequence

DEPRECATED_PACKAGES = {
    "node-sass": "sass",
    "tslint": "eslint",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check dependency versions for a scaffolded webapp.")
    parser.add_argument("project_dir", help="Path to the generated webapp directory.")
    parser.add_argument("--update", action="store_true", help="Rewrite package.json to the latest compatible versions and run npm install.")
    parser.add_argument("--include-major", action="store_true", help="Allow suggested rewrites to include the latest major version.")
    parser.add_argument("--output-dir", help="Directory for dependency-report.md. Defaults to the project directory.")
    return parser.parse_args(argv)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_json(url: str) -> Dict[str, Any]:
    with urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def now_iso() -> str:
    try:
        result = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        return (-1, -1, -1)
    return tuple(int(part) for part in match.groups())


def sort_versions(versions: List[str]) -> List[str]:
    stable = [version for version in versions if re.match(r"^\d+\.\d+\.\d+$", version)]
    stable.sort(key=parse_version)
    return stable


def latest_matching(versions: List[str], predicate) -> str:
    matches = [version for version in versions if predicate(parse_version(version))]
    return matches[-1] if matches else "—"


def version_prefix(spec: str) -> str:
    match = re.match(r"^[~^]", spec.strip())
    return match.group(0) if match else ""


def analyse_dependencies(section_name: str, deps: Dict[str, str]) -> List[Dict[str, str]]:
    rows = []
    for package, current_spec in sorted(deps.items()):
        metadata = fetch_json(f"https://registry.npmjs.org/{package}")
        versions = sort_versions(list((metadata.get("versions") or {}).keys()))
        current = parse_version(current_spec)
        latest_major = (metadata.get("dist-tags") or {}).get("latest") or (versions[-1] if versions else "—")
        latest_patch = latest_matching(versions, lambda version: version[0] == current[0] and version[1] == current[1])
        latest_minor = latest_matching(versions, lambda version: version[0] == current[0])
        deprecated_replacement = DEPRECATED_PACKAGES.get(package)

        status = "✅ Current"
        if deprecated_replacement:
            status = f"⚠️ Deprecated → use {deprecated_replacement}"
        elif latest_minor not in {"—", re.search(r'(\d+\.\d+\.\d+)', current_spec).group(1) if re.search(r'(\d+\.\d+\.\d+)', current_spec) else current_spec}:
            status = "⬆️ Safe update available"
        elif parse_version(latest_major) > current:
            status = "⚠️ Major update available"

        rows.append(
            {
                "section": section_name,
                "package": package,
                "current": current_spec,
                "latest_patch": latest_patch,
                "latest_minor": latest_minor,
                "latest_major": latest_major,
                "status": status,
                "replacement": deprecated_replacement or "",
            }
        )
    return rows


def recommended_version(row: Dict[str, str], include_major: bool) -> str:
    if row["replacement"]:
        return row["current"]
    target = row["latest_major"] if include_major and row["latest_major"] != "—" else row["latest_minor"]
    if target == "—":
        target = row["latest_patch"]
    if target == "—":
        return row["current"]
    return f"{version_prefix(row['current'])}{target}"


def render_rows(title: str, rows: List[Dict[str, str]]) -> List[str]:
    lines = [f"## {title}", "| Package | Current | Latest Patch | Latest Minor | Latest Major | Status |", "|---------|---------|-------------|-------------|-------------|--------|"]
    for row in rows:
        lines.append(
            f"| {row['package']} | {row['current']} | {row['latest_patch']} | {row['latest_minor']} | {row['latest_major']} | {row['status']} |"
        )
    lines.append("")
    return lines


def render_report(project_dir: Path, dependency_rows: List[Dict[str, str]], dev_rows: List[Dict[str, str]], lockfile_total: int) -> str:
    outdated = sum(1 for row in dependency_rows + dev_rows if "update" in row["status"].lower())
    deprecated = sum(1 for row in dependency_rows + dev_rows if row["replacement"])
    lines = [
        "# Dependency Report",
        f"**Generated:** {now_iso()}",
        "",
        *render_rows("Direct Dependencies", dependency_rows),
        *render_rows("Dev Dependencies", dev_rows),
        "## Transitive Dependencies Summary",
        f"- Total packages in lockfile: {lockfile_total}",
        f"- Outdated: {outdated}",
        f"- Deprecated: {deprecated}",
        "",
        "## Recommended Actions",
    ]
    if deprecated:
        lines.append("- Replace deprecated packages before the next release.")
    if outdated:
        lines.append("- Apply safe patch/minor updates, regenerate the lockfile, and re-run tests.")
    if not outdated and not deprecated:
        lines.append("- Direct dependencies are current within the configured semver ranges.")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_dir = Path(args.project_dir).expanduser().resolve()
    package_path = project_dir / "package.json"
    if not package_path.exists():
        raise SystemExit(f"[ERROR] package.json not found in {project_dir}")

    package_data = load_json(package_path)
    dependency_rows = analyse_dependencies("dependencies", package_data.get("dependencies") or {})
    dev_rows = analyse_dependencies("devDependencies", package_data.get("devDependencies") or {})

    if args.update:
        for row in dependency_rows:
            package_data.setdefault("dependencies", {})[row["package"]] = recommended_version(row, args.include_major)
        for row in dev_rows:
            package_data.setdefault("devDependencies", {})[row["package"]] = recommended_version(row, args.include_major)
        package_path.write_text(json.dumps(package_data, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["npm", "install"], cwd=project_dir, check=True)

    lockfile_total = 0
    if (project_dir / "package-lock.json").exists():
        lock_data = load_json(project_dir / "package-lock.json")
        if isinstance(lock_data.get("packages"), dict):
            lockfile_total = max(len(lock_data["packages"]) - 1, 0)
        elif isinstance(lock_data.get("dependencies"), dict):
            lockfile_total = len(lock_data["dependencies"])

    report_text = render_report(project_dir, dependency_rows, dev_rows, lockfile_total)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else project_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "dependency-report.md"
    report_path.write_text(report_text, encoding="utf-8")
    print(report_text)
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
