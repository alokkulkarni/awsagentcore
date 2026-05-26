#!/usr/bin/env python3
"""Run a dependency security audit for a scaffolded webapp."""

from pathlib import Path
import json
import subprocess
import urllib.request
import sys
import re
from collections import defaultdict

SEVERITY_ORDER = {"critical": 0, "high": 1, "moderate": 2, "low": 3, "info": 4}
SEVERITIES = ["critical", "high", "moderate", "low"]
COLORS = {
    "critical": "\033[1;31m",
    "high": "\033[31m",
    "moderate": "\033[33m",
    "low": "\033[36m",
    "reset": "\033[0m",
    "bold": "\033[1m",
    "green": "\033[32m",
}
CWE_TO_OWASP = {
    "CWE-79": "A03:2021 — Injection / XSS",
    "CWE-89": "A03:2021 — Injection / SQL Injection",
    "CWE-94": "A03:2021 — Injection / Code Injection",
    "CWE-116": "A03:2021 — Injection / Output Encoding",
    "CWE-200": "A01:2021 — Broken Access Control / Information Exposure",
    "CWE-287": "A07:2021 — Identification and Authentication Failures",
    "CWE-352": "A01:2021 — Broken Access Control / CSRF",
    "CWE-400": "A05:2021 — Security Misconfiguration / Resource Exhaustion",
    "CWE-434": "A08:2021 — Software and Data Integrity Failures",
    "CWE-502": "A08:2021 — Software and Data Integrity Failures",
    "CWE-601": "A10:2021 — Server-Side Request Forgery / Open Redirect",
    "CWE-918": "A10:2021 — Server-Side Request Forgery",
}


def parse_args(argv):
    if len(argv) < 2:
        raise SystemExit("Usage: python3 audit_security.py <project_dir> [--fix] [--report-only] [--output-dir DIR]")
    project_dir = None
    output_dir = None
    fix = False
    report_only = False
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--fix":
            fix = True
        elif arg == "--report-only":
            report_only = True
        elif arg == "--output-dir":
            index += 1
            if index >= len(argv):
                raise SystemExit("[ERROR] --output-dir requires a directory path.")
            output_dir = Path(argv[index]).expanduser().resolve()
        elif project_dir is None:
            project_dir = Path(arg).expanduser().resolve()
        else:
            raise SystemExit(f"[ERROR] Unexpected argument: {arg}")
        index += 1
    if project_dir is None:
        raise SystemExit("[ERROR] Project directory is required.")
    return project_dir, fix, report_only, output_dir


def now_iso():
    try:
        result = subprocess.run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except Exception:
        return "unknown"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def request_json(url, payload=None):
    if payload is None:
        request = urllib.request.Request(url)
    else:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def run_npm(project_dir, *args):
    return subprocess.run(["npm", *args], cwd=project_dir, capture_output=True, text=True)


def build_dependency_tree(node):
    dependencies = {}
    for name, child in (node.get("dependencies") or {}).items():
        dependencies[name] = {
            "version": str(child.get("version", "unknown")),
            "requires": child.get("requires") or {},
            "dependencies": build_dependency_tree(child),
        }
    return dependencies


def flatten_from_nested(lock_data):
    flattened = {}

    def walk(name, node, trail, direct):
        version = str(node.get("version", "unknown"))
        key = (name, version)
        entry = flattened.setdefault(
            key,
            {
                "name": name,
                "version": version,
                "direct": direct,
                "paths": [],
                "requires": node.get("requires") or {},
                "status": "clean",
                "cves": set(),
            },
        )
        entry["direct"] = entry["direct"] or direct
        entry["paths"].append(trail + [name])
        for child_name, child in (node.get("dependencies") or {}).items():
            walk(child_name, child, trail + [name], False)

    for name, node in (lock_data.get("dependencies") or {}).items():
        walk(name, node, [lock_data.get("name", "app")], True)
    return flattened


def flatten_from_packages(lock_data):
    flattened = {}
    for package_path, info in (lock_data.get("packages") or {}).items():
        if not package_path:
            continue
        name = info.get("name")
        if not name:
            tail = package_path.split("node_modules/")[-1]
            name = tail
        version = str(info.get("version", "unknown"))
        if not name or version == "unknown":
            continue
        segments = [segment for segment in package_path.split("node_modules/") if segment]
        path_items = [lock_data.get("name", "app")] + [segment.rstrip("/") for segment in segments]
        key = (name, version)
        entry = flattened.setdefault(
            key,
            {
                "name": name,
                "version": version,
                "direct": package_path.count("node_modules/") == 1,
                "paths": [],
                "requires": info.get("dependencies") or {},
                "status": "clean",
                "cves": set(),
            },
        )
        entry["paths"].append(path_items)
    return flattened


def flatten_dependencies(lock_data):
    flattened = flatten_from_nested(lock_data)
    if not flattened and lock_data.get("packages"):
        flattened = flatten_from_packages(lock_data)
    return flattened


def build_quick_payload(lock_data, package_json):
    return {
        "name": package_json.get("name", lock_data.get("name", "webapp")),
        "version": package_json.get("version", lock_data.get("version", "1.0.0")),
        "requires": (package_json.get("dependencies") or {}) | (package_json.get("devDependencies") or {}),
        "dependencies": build_dependency_tree(lock_data),
    }


def build_single_package_payload(name, version, requires=None):
    return {
        "name": name,
        "version": version,
        "requires": requires or {},
        "dependencies": {},
    }


def parse_cwes(value):
    if isinstance(value, list):
        items = []
        for item in value:
            items.extend(parse_cwes(item))
        return items
    if isinstance(value, str):
        return re.findall(r"CWE-\d+", value)
    return []


def parse_cves(value, fallback):
    if isinstance(value, list):
        values = [item for item in value if isinstance(item, str) and item.startswith("CVE-")]
        if values:
            return values
    if isinstance(fallback, str) and fallback.startswith("CVE-"):
        return [fallback]
    return [fallback]


def normalize_dependency_path(path_value):
    if isinstance(path_value, list):
        return [str(item) for item in path_value if str(item)]
    if isinstance(path_value, str):
        if ">" in path_value:
            return [segment.strip() for segment in path_value.split(">") if segment.strip()]
        if "node_modules/" in path_value:
            return [segment for segment in path_value.split("node_modules/") if segment]
        return [segment for segment in re.split(r"[\\/]", path_value) if segment and segment != "node_modules"]
    return []


def record_issue(issues, flattened, name, version, vuln_id, severity, title, cwes, source, dependency_paths=None, recommendation=None):
    key = (name, version, vuln_id)
    issue = issues.setdefault(
        key,
        {
            "package": name,
            "version": version,
            "id": vuln_id,
            "severity": (severity or "moderate").lower(),
            "title": title or vuln_id,
            "cwes": [],
            "paths": [],
            "sources": set(),
            "recommendation": recommendation,
        },
    )
    issue["sources"].add(source)
    issue["cwes"] = sorted(set(issue["cwes"]) | set(cwes))
    if dependency_paths:
        for item in dependency_paths:
            normalized = normalize_dependency_path(item)
            if normalized and normalized not in issue["paths"]:
                issue["paths"].append(normalized)
    elif (name, version) in flattened and not issue["paths"]:
        issue["paths"].extend(flattened[(name, version)]["paths"][:1])
    flattened.setdefault((name, version), {"name": name, "version": version, "direct": False, "paths": [], "requires": {}, "status": "clean", "cves": set()})
    flattened[(name, version)]["status"] = "vulnerable"
    flattened[(name, version)]["cves"].add(vuln_id)


def parse_npm_audit(audit_data, flattened):
    issues = {}
    vulnerabilities = audit_data.get("vulnerabilities") or {}
    for name, details in vulnerabilities.items():
        matched_versions = [version for dep_name, version in flattened if dep_name == name] or [str(details.get("range", "unknown"))]
        via_items = details.get("via") or []
        if not isinstance(via_items, list):
            via_items = [via_items]
        for version in matched_versions:
            for via in via_items:
                if isinstance(via, str):
                    continue
                record_issue(
                    issues,
                    flattened,
                    name,
                    version,
                    str(via.get("source") or via.get("url") or via.get("title") or "npm-audit"),
                    via.get("severity") or details.get("severity"),
                    via.get("title") or details.get("title") or "npm advisory",
                    parse_cwes(via.get("cwe") or via.get("cwes") or via.get("overview") or ""),
                    "npm-audit",
                    dependency_paths=[details.get("nodes", [None])[0]] if details.get("nodes") else None,
                    recommendation=(details.get("fixAvailable") or {}).get("name") if isinstance(details.get("fixAvailable"), dict) else None,
                )
    advisories = audit_data.get("advisories") or {}
    for advisory_id, advisory in advisories.items():
        name = advisory.get("module_name")
        if not name:
            continue
        findings = advisory.get("findings") or []
        matched_versions = [finding.get("version") for finding in findings if finding.get("version")] or [version for dep_name, version in flattened if dep_name == name]
        for version in matched_versions:
            paths = []
            for finding in findings:
                for path in finding.get("paths") or []:
                    paths.append([segment.strip() for segment in path.split(">") if segment.strip()])
            record_issue(
                issues,
                flattened,
                name,
                version,
                (advisory.get("cves") or [f"ADV-{advisory_id}"])[0],
                advisory.get("severity"),
                advisory.get("title"),
                parse_cwes(advisory.get("cwe") or advisory.get("overview") or ""),
                "npm-audit",
                dependency_paths=paths,
                recommendation=(advisory.get("recommendation") or "").strip() or None,
            )
    return issues


def parse_quick_response(response, flattened):
    issues = {}
    advisories = response.get("advisories") or {}
    for advisory_id, advisory in advisories.items():
        name = advisory.get("module_name")
        if not name:
            continue
        findings = advisory.get("findings") or []
        versions = [finding.get("version") for finding in findings if finding.get("version")] or [version for dep_name, version in flattened if dep_name == name]
        for version in versions:
            paths = []
            for finding in findings:
                for path in finding.get("paths") or []:
                    paths.append([segment.strip() for segment in path.split(">") if segment.strip()])
            record_issue(
                issues,
                flattened,
                name,
                version,
                parse_cves(advisory.get("cves"), f"ADV-{advisory_id}")[0],
                advisory.get("severity"),
                advisory.get("title"),
                parse_cwes(advisory.get("cwe") or advisory.get("overview") or ""),
                "quick-audit",
                dependency_paths=paths,
                recommendation=(advisory.get("recommendation") or "").strip() or None,
            )
    vulnerabilities = response.get("vulnerabilities") or {}
    for name, details in vulnerabilities.items():
        matched_versions = [version for dep_name, version in flattened if dep_name == name]
        via_items = details.get("via") or []
        if not isinstance(via_items, list):
            via_items = [via_items]
        for version in matched_versions or [str(details.get("range", "unknown"))]:
            for via in via_items:
                if not isinstance(via, dict):
                    continue
                record_issue(
                    issues,
                    flattened,
                    name,
                    version,
                    str(via.get("source") or via.get("url") or via.get("title") or "quick-audit"),
                    via.get("severity") or details.get("severity"),
                    via.get("title") or details.get("title") or "Registry advisory",
                    parse_cwes(via.get("cwe") or via.get("cwes") or via.get("overview") or ""),
                    "quick-audit",
                    dependency_paths=details.get("nodes"),
                    recommendation=(details.get("fixAvailable") or {}).get("name") if isinstance(details.get("fixAvailable"), dict) else None,
                )
    return issues


def combine_issues(*collections):
    merged = {}
    for current in collections:
        for key, item in current.items():
            target = merged.setdefault(
                key,
                {
                    "package": item["package"],
                    "version": item["version"],
                    "id": item["id"],
                    "severity": item["severity"],
                    "title": item["title"],
                    "cwes": [],
                    "paths": [],
                    "sources": set(),
                    "recommendation": item.get("recommendation"),
                },
            )
            target["cwes"] = sorted(set(target["cwes"]) | set(item.get("cwes") or []))
            target["sources"].update(item.get("sources") or set())
            for path in item.get("paths") or []:
                if path and path not in target["paths"]:
                    target["paths"].append(path)
            if not target.get("recommendation") and item.get("recommendation"):
                target["recommendation"] = item["recommendation"]
    return merged


def get_registry_metadata(name, cache):
    if name not in cache:
        cache[name] = request_json(f"https://registry.npmjs.org/{name}")
    return cache[name]


def suggest_safe_version(issue, cache):
    if issue.get("recommendation") and isinstance(issue["recommendation"], str) and "@" in issue["recommendation"]:
        return issue["recommendation"].split("@")[-1]
    metadata = get_registry_metadata(issue["package"], cache)
    latest = (metadata.get("dist-tags") or {}).get("latest")
    if latest:
        return latest
    versions = list((metadata.get("versions") or {}).keys())
    versions.sort(key=version_key, reverse=True)
    return versions[0] if versions else "unknown"


def version_key(value):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value))
    if not match:
        return (-1, -1, -1)
    return tuple(int(part) for part in match.groups())


def count_by_severity(issues):
    counts = {severity: 0 for severity in SEVERITIES}
    for issue in issues.values():
        severity = issue["severity"].lower()
        if severity in counts:
            counts[severity] += 1
    return counts


def render_summary_table(before_counts, after_counts):
    lines = [
        "| Severity | Count | Fixed | Remaining |",
        "|----------|-------|-------|-----------|",
    ]
    for severity in SEVERITIES:
        total = before_counts.get(severity, 0)
        remaining = after_counts.get(severity, total)
        fixed = max(total - remaining, 0)
        lines.append(f"| {severity.title()} | {total} | {fixed} | {remaining} |")
    return "\n".join(lines)


def format_table(rows):
    widths = [max(len(str(value)) for value in column) for column in zip(*rows)]
    rendered = []
    for row in rows:
        rendered.append(" | ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))
    return "\n".join(rendered)


def render_console_report(project_name, before_counts, after_counts, issues):
    rows = [("Severity", "Count", "Fixed", "Remaining")]
    for severity in SEVERITIES:
        total = before_counts.get(severity, 0)
        remaining = after_counts.get(severity, total)
        fixed = max(total - remaining, 0)
        label = severity.title()
        color = COLORS.get(severity, "")
        rows.append((f"{color}{label}{COLORS['reset']}", str(total), str(fixed), str(remaining)))
    print(f"{COLORS['bold']}Security audit summary — {project_name}{COLORS['reset']}")
    print(format_table(rows))
    if issues:
        print()
        for issue in sorted(issues.values(), key=lambda item: (SEVERITY_ORDER.get(item['severity'], 9), item['package'], item['id'])):
            path_text = " → ".join(issue["paths"][0]) if issue.get("paths") else issue["package"]
            color = COLORS.get(issue["severity"], "")
            print(f"{color}{issue['severity'].upper():<8}{COLORS['reset']} {issue['package']}@{issue['version']} {issue['id']} :: {path_text}")
    else:
        print(f"{COLORS['green']}No vulnerabilities found.{COLORS['reset']}")


def render_markdown(project_dir, generated, before_counts, after_counts, issues, flattened):
    status = "✅ CLEAN"
    if any(after_counts.get(level, 0) for level in ("critical", "high")):
        status = "🚨 ACTION REQUIRED"
    elif any(after_counts.get(level, 0) for level in SEVERITIES):
        status = "⚠️ WARNINGS"

    lines = [
        "# Security Audit Report",
        f"**Generated:** {generated}",
        f"**Project:** {project_dir.name}",
        f"**Status:** {status}",
        "",
        "## Summary",
        render_summary_table(before_counts, after_counts),
        "",
        "## Vulnerabilities Found",
    ]

    if issues:
        for issue in sorted(issues.values(), key=lambda item: (SEVERITY_ORDER.get(item['severity'], 9), item['package'], item['id'])):
            cwe = issue["cwes"][0] if issue.get("cwes") else "CWE-unknown"
            owasp = CWE_TO_OWASP.get(cwe, "A06:2021 — Vulnerable and Outdated Components")
            dependency_path = " → ".join(issue["paths"][0]) if issue.get("paths") else issue["package"]
            fix_version = issue.get("safe_version", "unknown")
            lines.extend(
                [
                    f"### {issue['package']}@{issue['version']} — {issue['id']}",
                    f"- **Severity:** {issue['severity'].upper()}",
                    f"- **CWE:** {cwe}",
                    f"- **OWASP Category:** {owasp}",
                    f"- **Dependency path:** {dependency_path}",
                    f"- **Fix:** Upgrade to {issue['package']}@{fix_version}",
                    "",
                ]
            )
    else:
        lines.extend(["No vulnerabilities detected.", ""])

    lines.extend([
        "## Transitive Dependencies Analysed",
        "| Package | Version | Direct/Transitive | Status |",
        "|---------|---------|-------------------|--------|",
    ])
    for item in sorted(flattened.values(), key=lambda entry: (entry["name"], entry["version"])):
        relation = "Direct" if item.get("direct") else "Transitive"
        status = "Vulnerable" if item.get("status") == "vulnerable" else "Clean"
        lines.append(f"| {item['name']} | {item['version']} | {relation} | {status} |")

    lines.extend(["", "## Recommendations"])
    if issues:
        lines.append("- Prioritise critical and high findings before production deployment.")
        lines.append("- Commit the updated package-lock.json after applying safe upgrades.")
        lines.append("- Re-run `python3 audit_security.py . --fix` and `npm audit --audit-level=high` after remediation.")
    else:
        lines.append("- Continue auditing dependencies before each production build.")
    lines.append("")
    return "\n".join(lines)


def audit_project(project_dir):
    package_json = load_json(project_dir / "package.json")
    lock_data = load_json(project_dir / "package-lock.json")
    flattened = flatten_dependencies(lock_data)

    audit_run = run_npm(project_dir, "audit", "--json")
    audit_payload = {}
    if audit_run.stdout.strip():
        audit_payload = json.loads(audit_run.stdout)
    elif audit_run.stderr.strip().startswith("{"):
        audit_payload = json.loads(audit_run.stderr)

    npm_issues = parse_npm_audit(audit_payload, flattened)

    quick_issues = {}
    try:
        quick_root = request_json("https://registry.npmjs.org/-/npm/v1/security/audits/quick", build_quick_payload(lock_data, package_json))
        quick_issues = combine_issues(quick_issues, parse_quick_response(quick_root, flattened))
    except Exception:
        pass

    for entry in list(flattened.values()):
        try:
            response = request_json(
                "https://registry.npmjs.org/-/npm/v1/security/audits/quick",
                build_single_package_payload(entry["name"], entry["version"], entry.get("requires")),
            )
            quick_issues = combine_issues(quick_issues, parse_quick_response(response, flattened))
        except Exception:
            continue

    issues = combine_issues(npm_issues, quick_issues)
    registry_cache = {}
    for issue in issues.values():
        issue["safe_version"] = suggest_safe_version(issue, registry_cache)
    return flattened, issues


def main():
    project_dir, fix, report_only, output_dir = parse_args(sys.argv)
    if not project_dir.exists():
        raise SystemExit(f"[ERROR] Project directory not found: {project_dir}")
    if not (project_dir / "package-lock.json").exists():
        raise SystemExit(f"[ERROR] package-lock.json not found in {project_dir}")

    before_flattened, before_issues = audit_project(project_dir)
    before_counts = count_by_severity(before_issues)
    after_flattened = before_flattened
    after_issues = before_issues

    if fix and not report_only:
        run_npm(project_dir, "audit", "fix")
        run_npm(project_dir, "update")
        after_flattened, after_issues = audit_project(project_dir)

    after_counts = count_by_severity(after_issues)
    render_console_report(project_dir.name, before_counts, after_counts, after_issues)

    generated = now_iso()
    report_dir = output_dir or project_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "security-audit-report.md"
    report_path.write_text(render_markdown(project_dir, generated, before_counts, after_counts, after_issues, after_flattened), encoding="utf-8")
    print(f"\nReport written to {report_path}")

    remaining = after_counts.get("critical", 0) + after_counts.get("high", 0)
    return 1 if remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
