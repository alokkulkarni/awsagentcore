#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Lambda Dependency CVE Scanner
Scans dependency manifests for known CVEs across all Lambda runtimes.

Supported manifests:
  requirements.txt  — Python (uses pip-audit, queries PyPI Advisory + OSV)
  package.json      — Node.js (uses npm audit, queries npm Advisory + GitHub Advisory DB)
  go.mod            — Go (uses govulncheck, queries Go Vulnerability Database + OSV)
  pom.xml           — Java Maven (OWASP Dependency-Check instructions)
  build.gradle      — Java Gradle (OWASP Dependency-Check instructions)

Usage:
  python3 scan_deps.py requirements.txt
  python3 scan_deps.py package.json
  python3 scan_deps.py go.mod
  python3 scan_deps.py --json requirements.txt

Exit codes:
  0 — no CVEs found
  1 — CVEs found
  2 — scanner not available or file error

CVE Database References:
  MITRE CVE               https://cve.mitre.org/
  NVD                     https://nvd.nist.gov/
  OSV                     https://osv.dev/
  GitHub Advisory DB      https://github.com/advisories
  PyPI Advisory DB        https://pypi.org/security/
  npm Advisory DB         https://docs.npmjs.com/cli/v10/commands/npm-audit
  Go Vuln DB              https://vuln.go.dev/
  Snyk Vulnerability DB   https://security.snyk.io/
  OWASP Dep-Check         https://owasp.org/www-project-dependency-check/

Tool References:
  pip-audit               https://pypi.org/project/pip-audit/
  govulncheck             https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck
  npm audit               https://docs.npmjs.com/cli/v10/commands/npm-audit
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def detect_manifest(path: Path) -> Optional[str]:
    name = path.name
    if name == "requirements.txt":
        return "python"
    if name == "package.json":
        return "nodejs"
    if name == "go.mod":
        return "go"
    if name == "pom.xml":
        return "maven"
    if name == "build.gradle":
        return "gradle"
    return None


def run_command(command: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, check=False)


def parse_pip_audit(path: Path) -> Tuple[List[Dict[str, str]], Optional[str], int]:
    result = run_command([sys.executable, "-m", "pip_audit", "-r", str(path), "--format", "json"])
    combined = (result.stdout or "") + (result.stderr or "")
    if "No module named pip_audit" in combined:
        return [], "pip-audit is not installed. Install it with: pip install pip-audit", 2
    if not result.stdout.strip():
        return [], combined.strip() or "pip-audit produced no output", 2
    data = json.loads(result.stdout)
    findings: List[Dict[str, str]] = []
    for dep in data.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            vuln_id = vuln.get("id") or ", ".join(vuln.get("aliases", [])) or "UNKNOWN"
            fix_versions = vuln.get("fix_versions") or []
            findings.append({
                "package": dep.get("name", "unknown"),
                "version": dep.get("version", "unknown"),
                "id": vuln_id,
                "severity": vuln.get("severity") or "UNKNOWN",
                "fixed_version": fix_versions[0] if fix_versions else "unknown",
            })
    return findings, None, 1 if findings else 0


def parse_npm_audit(path: Path) -> Tuple[List[Dict[str, str]], Optional[str], int]:
    if shutil.which("npm") is None:
        return [], "npm is not installed or not in PATH. Install Node.js 18+ with npm.", 2
    result = run_command(["npm", "audit", "--json"], cwd=path.parent)
    payload = result.stdout.strip() or result.stderr.strip()
    if not payload:
        return [], "npm audit produced no output", 2
    data = json.loads(payload)
    package_json = json.loads(path.read_text(encoding="utf-8"))
    declared = {}
    declared.update(package_json.get("dependencies", {}))
    declared.update(package_json.get("devDependencies", {}))
    findings: List[Dict[str, str]] = []
    for package, details in (data.get("vulnerabilities") or {}).items():
        via_entries = details.get("via") or []
        if not isinstance(via_entries, list):
            via_entries = [via_entries]
        for via in via_entries:
            if isinstance(via, str):
                findings.append({
                    "package": package,
                    "version": str(declared.get(package, "unknown")),
                    "id": via,
                    "severity": str(details.get("severity", "UNKNOWN")).upper(),
                    "fixed_version": _npm_fix_version(details.get("fixAvailable")),
                })
                continue
            advisory_id = via.get("url") or via.get("source") or via.get("name") or "npm-advisory"
            findings.append({
                "package": via.get("name", package),
                "version": str(declared.get(package, "unknown")),
                "id": str(advisory_id),
                "severity": str(via.get("severity") or details.get("severity") or "UNKNOWN").upper(),
                "fixed_version": _npm_fix_version(details.get("fixAvailable")),
            })
    deduped = {(item["package"], item["id"]): item for item in findings}
    items = list(deduped.values())
    return items, None, 1 if items else 0


def _npm_fix_version(fix_available: object) -> str:
    if isinstance(fix_available, dict):
        return str(fix_available.get("version") or "unknown")
    if fix_available is True:
        return "available"
    if fix_available is False or fix_available is None:
        return "unavailable"
    return str(fix_available)


def _parse_go_mod_versions(path: Path) -> Dict[str, str]:
    versions: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("require "):
            parts = stripped.split()
            if len(parts) >= 3:
                versions[parts[1]] = parts[2]
        elif stripped and not stripped.startswith(("module ", "go ", "require (", ")", "replace ", "exclude ", "//")):
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].startswith("v"):
                versions[parts[0]] = parts[1]
    return versions


def parse_govulncheck(path: Path) -> Tuple[List[Dict[str, str]], Optional[str], int]:
    govulncheck = shutil.which("govulncheck")
    if govulncheck is None:
        return [], (
            "govulncheck is not installed. Install it with: go install golang.org/x/vuln/cmd/govulncheck@latest\n"
            "Alternative: use osv-scanner against the module directory."
        ), 2
    result = run_command([govulncheck, "-json", "./..."], cwd=path.parent)
    if not result.stdout.strip() and result.returncode != 0:
        return [], result.stderr.strip() or "govulncheck failed", 2
    modules = _parse_go_mod_versions(path)
    osv_entries: Dict[str, Dict[str, object]] = {}
    findings: List[Dict[str, str]] = []
    for raw_line in result.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        message = json.loads(raw_line)
        if "osv" in message:
            osv = message["osv"]
            osv_entries[osv["id"]] = osv
        if "finding" in message:
            finding = message["finding"]
            osv_id = finding.get("osv")
            trace = finding.get("trace") or []
            package = trace[0].get("module", "unknown") if trace else "unknown"
            osv = osv_entries.get(osv_id, {})
            affected = osv.get("affected") or []
            fixed_version = "unknown"
            for item in affected:
                package_name = item.get("package", {}).get("name")
                if package_name and package_name != package:
                    continue
                for range_item in item.get("ranges") or []:
                    for event in range_item.get("events") or []:
                        if event.get("fixed"):
                            fixed_version = event["fixed"]
                            break
                    if fixed_version != "unknown":
                        break
            findings.append({
                "package": package,
                "version": modules.get(package, "unknown"),
                "id": osv_id or "unknown",
                "severity": str((osv.get("database_specific") or {}).get("severity") or "UNKNOWN").upper(),
                "fixed_version": fixed_version,
            })
    deduped = {(item["package"], item["id"]): item for item in findings}
    items = list(deduped.values())
    return items, None, 1 if items else 0


def java_instructions(path: Path) -> Tuple[List[Dict[str, str]], Optional[str], int]:
    tool = "pom.xml" if path.name == "pom.xml" else "build.gradle"
    return [], (
        f"{tool} requires an external Java dependency scanner. Use OWASP Dependency-Check, for example:\n"
        f"  dependency-check --project lambda-security-audit --scan {path.parent}\n"
        "Reference: https://owasp.org/www-project-dependency-check/"
    ), 2


def _cve_url(cve_id: str) -> str:
    """Return a direct URL to the CVE in NVD, OSV, or npm advisory."""
    if cve_id.startswith("CVE-"):
        return f"https://nvd.nist.gov/vuln/detail/{cve_id}"
    if cve_id.startswith("GHSA-"):
        return f"https://github.com/advisories/{cve_id}"
    if cve_id.startswith("GO-"):
        return f"https://pkg.go.dev/vuln/{cve_id}"
    if cve_id.startswith("PYSEC-"):
        return f"https://osv.dev/vulnerability/{cve_id}"
    if cve_id.startswith("npm-"):
        return f"https://www.npmjs.com/advisories/{cve_id.replace('npm-', '')}"
    if cve_id.startswith("https://"):
        return cve_id
    return f"https://osv.dev/vulnerability/{cve_id}"


def format_text(path: Path, findings: List[Dict[str, str]], error: Optional[str], manifest_type: str) -> None:
    print(f"\n{path}  [{manifest_type}]")
    if error:
        print(f"  ERROR: {error}")
        return
    if not findings:
        print("  ✓ No CVEs found")
        return
    for item in findings:
        url = _cve_url(item["id"])
        print(f"  - {item['package']} {item['version']}  {item['id']}  {item['severity']}  fix: {item['fixed_version']}")
        print(f"    Reference: {url}")


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    output_json = "--json" in args
    file_args = [arg for arg in args if not arg.startswith("--")]
    if not file_args:
        print("Error: no input files specified", file=sys.stderr)
        return 2

    exit_code = 0
    results = {}
    for file_arg in file_args:
        path = Path(file_arg)
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            return 2
        manifest_type = detect_manifest(path)
        if manifest_type is None:
            print(f"Error: unsupported manifest: {path.name}", file=sys.stderr)
            return 2

        if manifest_type == "python":
            findings, error, status = parse_pip_audit(path)
        elif manifest_type == "nodejs":
            findings, error, status = parse_npm_audit(path)
        elif manifest_type == "go":
            findings, error, status = parse_govulncheck(path)
        else:
            findings, error, status = java_instructions(path)

        exit_code = max(exit_code, status)
        results[str(path)] = {
            "manifest_type": manifest_type,
            "findings": findings,
            "error": error,
        }
        if not output_json:
            format_text(path, findings, error, manifest_type)

    if output_json:
        print(json.dumps(results, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
