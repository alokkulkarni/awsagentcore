#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Run a local SDLC analysis fallback for repositories."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_ROOT / "templates" / "analysis-report.md"
SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    "target",
    ".next",
    ".turbo",
}
DOCUMENTATION_FILES = ["README.md", "docs/", "CONTRIBUTING.md", "CHANGELOG.md", "LICENSE"]
LANGUAGE_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".cc": "C++",
    ".c": "C",
    ".h": "C/C++ Header",
    ".hpp": "C/C++ Header",
    ".scala": "Scala",
    ".swift": "Swift",
    ".sh": "Shell",
    ".tf": "Terraform",
    ".sql": "SQL",
}
KNOWN_VULNERABLE_PACKAGES = {
    "axios": {
        "max_version": "0.27.1",
        "severity": "HIGH",
        "cve": "GHSA-wf5p-g6vw-rhxx",
        "summary": "Server-side request forgery risk in older axios releases.",
        "reference": "https://nvd.nist.gov/",
    },
    "django": {
        "max_version": "3.2.24",
        "severity": "HIGH",
        "cve": "CVE-2024-24680",
        "summary": "Review Django patch level for recent security advisories.",
        "reference": "https://nvd.nist.gov/",
    },
    "flask": {
        "max_version": "2.2.4",
        "severity": "HIGH",
        "cve": "CVE-2023-30861",
        "summary": "Older Flask versions should be reviewed for security fixes.",
        "reference": "https://nvd.nist.gov/",
    },
    "jinja2": {
        "max_version": "2.11.2",
        "severity": "HIGH",
        "cve": "CVE-2020-28493",
        "summary": "Sandbox escape and template injection concerns in older releases.",
        "reference": "https://nvd.nist.gov/",
    },
    "jsonwebtoken": {
        "max_version": "8.5.1",
        "severity": "HIGH",
        "cve": "CVE-2022-23529",
        "summary": "Review JWT library release level and patch status.",
        "reference": "https://nvd.nist.gov/",
    },
    "lodash": {
        "max_version": "4.17.20",
        "severity": "HIGH",
        "cve": "CVE-2021-23337",
        "summary": "Prototype pollution risk in older lodash versions.",
        "reference": "https://nvd.nist.gov/",
    },
    "minimist": {
        "max_version": "1.2.5",
        "severity": "HIGH",
        "cve": "CVE-2021-44906",
        "summary": "Prototype pollution risk in older minimist versions.",
        "reference": "https://nvd.nist.gov/",
    },
    "pyyaml": {
        "max_version": "5.3.1",
        "severity": "HIGH",
        "cve": "CVE-2020-14343",
        "summary": "Unsafe loader defaults in older PyYAML versions.",
        "reference": "https://nvd.nist.gov/",
    },
    "requests": {
        "max_version": "2.19.1",
        "severity": "HIGH",
        "cve": "CVE-2018-18074",
        "summary": "Credential leakage risk in older requests versions.",
        "reference": "https://nvd.nist.gov/",
    },
}


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
    except OSError:
        return ""


def iter_files(root: Path, patterns: Iterable[str] | None = None) -> Iterable[Path]:
    pattern_list = list(patterns or ["*"])
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS and not name.startswith(".")]
        base = Path(current_root)
        for name in files:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(relative, pattern) for pattern in pattern_list):
                yield path


def load_json(path: Path) -> Dict[str, Any]:
    text = safe_read_text(path)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def detect_project_name(root: Path) -> str:
    package = load_json(root / "package.json")
    if isinstance(package.get("name"), str) and package["name"].strip():
        return package["name"].strip()

    pyproject = safe_read_text(root / "pyproject.toml")
    match = re.search(r"(?ms)^\[project\].*?^name\s*=\s*['\"]([^'\"]+)['\"]", pyproject)
    if match:
        return match.group(1).strip()

    go_mod = safe_read_text(root / "go.mod")
    match = re.search(r"(?m)^module\s+(.+)$", go_mod)
    if match:
        return match.group(1).strip().split("/")[-1]

    readme = safe_read_text(root / "README.md")
    for line in readme.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()

    return root.name


def detect_description(root: Path) -> str:
    readme = safe_read_text(root / "README.md")
    if readme:
        for chunk in [part.strip() for part in re.split(r"\n\s*\n", readme) if part.strip()]:
            if not chunk.startswith("#"):
                return re.sub(r"\s+", " ", chunk)
    package = load_json(root / "package.json")
    if isinstance(package.get("description"), str) and package["description"].strip():
        return package["description"].strip()
    return "Repository analysis generated from local project evidence."


def git_context(root: Path) -> Dict[str, str]:
    def run(*args: str) -> str:
        try:
            result = subprocess.run(["git", *args], cwd=root, check=False, capture_output=True, text=True)
        except OSError:
            return "unknown"
        value = result.stdout.strip()
        return value or "unknown"

    return {
        "repository": root.name,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": run("log", "-1", "--format=%h %s"),
        "status": run("status", "--short") or "clean",
    }


def parse_version_fragment(value: str) -> str:
    cleaned = value.strip().strip('"\'')
    cleaned = re.split(r"[;\s]", cleaned, maxsplit=1)[0]
    cleaned = re.sub(r"^[<>=~^!]+", "", cleaned)
    cleaned = cleaned.strip()
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[0].strip()
    return cleaned or "unspecified"


def compare_versions(left: str, right: str) -> int | None:
    if left in {"", "*", "latest", "unspecified", "unknown"} or right in {"", "*", "latest", "unspecified", "unknown"}:
        return None
    left_parts = [int(part) for part in re.findall(r"\d+", left)]
    right_parts = [int(part) for part in re.findall(r"\d+", right)]
    if not left_parts or not right_parts:
        return None
    length = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (length - len(left_parts)))
    right_parts.extend([0] * (length - len(right_parts)))
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


def parse_dependency_entry(raw: str, ecosystem: str, source: str) -> Dict[str, str] | None:
    raw = raw.strip().strip(",")
    if not raw or raw.startswith("#"):
        return None
    if ecosystem == "npm":
        name, version = raw.split(" ", 1)
        return {"name": name.lower(), "version": version or "unspecified", "ecosystem": ecosystem, "source": source}
    if ecosystem in {"pip", "poetry"}:
        match = re.match(r"([A-Za-z0-9_.\-\[\]]+)\s*(.*)", raw)
        if not match:
            return None
        return {
            "name": match.group(1).split("[")[0].lower(),
            "version": parse_version_fragment(match.group(2) or "unspecified"),
            "ecosystem": ecosystem,
            "source": source,
        }
    if ecosystem == "gomod":
        parts = raw.split()
        if len(parts) >= 2:
            return {"name": parts[0].lower(), "version": parts[1], "ecosystem": ecosystem, "source": source}
    if ecosystem == "cargo":
        name, version = raw.split(" ", 1)
        return {"name": name.lower(), "version": parse_version_fragment(version), "ecosystem": ecosystem, "source": source}
    return None


def collect_dependencies(root: Path) -> List[Dict[str, str]]:
    dependencies: List[Dict[str, str]] = []

    package = load_json(root / "package.json")
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        block = package.get(key)
        if isinstance(block, dict):
            for name, version in sorted(block.items()):
                item = parse_dependency_entry(f"{name} {version}", "npm", f"package.json:{key}")
                if item:
                    dependencies.append(item)

    for req_path in [root / "requirements.txt", root / "requirements-dev.txt", root / "requirements-prod.txt"]:
        text = safe_read_text(req_path)
        if not text:
            continue
        for line in text.splitlines():
            item = parse_dependency_entry(line, "pip", str(req_path.relative_to(root)))
            if item:
                dependencies.append(item)

    pyproject = safe_read_text(root / "pyproject.toml")
    project_match = re.search(r"(?ms)^\[project\](.*?)(^\[|\Z)", pyproject)
    if project_match:
        dep_match = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)\]", project_match.group(1))
        if dep_match:
            for entry in re.findall(r"['\"]([^'\"]+)['\"]", dep_match.group(1)):
                item = parse_dependency_entry(entry, "pip", "pyproject.toml:project.dependencies")
                if item:
                    dependencies.append(item)

    poetry_match = re.search(r"(?ms)^\[tool\.poetry\.dependencies\](.*?)(^\[|\Z)", pyproject)
    if poetry_match:
        for line in poetry_match.group(1).splitlines():
            line = line.strip()
            if not line or line.startswith("python") or line.startswith("#") or "=" not in line:
                continue
            name, version = [part.strip() for part in line.split("=", 1)]
            item = parse_dependency_entry(f"{name} {version}", "poetry", "pyproject.toml:tool.poetry.dependencies")
            if item:
                dependencies.append(item)

    go_mod = safe_read_text(root / "go.mod")
    for line in go_mod.splitlines():
        stripped = line.strip()
        if not stripped or stripped in {"require (", ")"} or stripped.startswith("module ") or stripped.startswith("go ") or stripped.startswith("//"):
            continue
        if stripped.startswith("require "):
            stripped = stripped[len("require "):].strip()
        item = parse_dependency_entry(stripped, "gomod", "go.mod")
        if item:
            dependencies.append(item)

    cargo = safe_read_text(root / "Cargo.toml")
    cargo_match = re.search(r"(?ms)^\[dependencies\](.*?)(^\[|\Z)", cargo)
    if cargo_match:
        for line in cargo_match.group(1).splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, version = [part.strip() for part in stripped.split("=", 1)]
            item = parse_dependency_entry(f"{name} {version}", "cargo", "Cargo.toml")
            if item:
                dependencies.append(item)

    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in dependencies:
        key = (item["name"], item["version"], item["source"])
        if key in seen:
            continue
        record = dict(item)
        record["license"] = "Unknown"
        record["cve_status"] = "None detected"
        record["mitigation_note"] = ""
        record["risk_reference"] = ""
        rule = KNOWN_VULNERABLE_PACKAGES.get(record["name"])
        if rule:
            comparison = compare_versions(record["version"], rule["max_version"])
            if comparison is None:
                record["cve_status"] = f"{rule['severity']} - manual review required"
                record["mitigation_note"] = "Version range could not be normalized automatically."
                record["risk_reference"] = rule["reference"]
            elif comparison <= 0:
                record["cve_status"] = f"{rule['severity']} - {rule['cve']}"
                record["mitigation_note"] = f"Upgrade above {rule['max_version']} and document remediation."
                record["risk_reference"] = rule["reference"]
        deduped.append(record)
        seen.add(key)
    return deduped


def is_test_file(path: Path) -> bool:
    relative = path.as_posix().lower()
    name = path.name.lower()
    return (
        "/tests/" in relative
        or "/test/" in relative
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".spec.js")
        or name.endswith(".spec.ts")
        or name.endswith(".test.js")
        or name.endswith(".test.ts")
        or name.endswith("_test.go")
    )


def collect_source_metrics(root: Path) -> Dict[str, Any]:
    loc_by_language: Counter[str] = Counter()
    source_count = 0
    test_count = 0
    docs_count = 0
    for path in iter_files(root):
        if path.name.startswith("."):
            continue
        ext = path.suffix.lower()
        text = safe_read_text(path)
        if path.name.lower().endswith(".md") or path.parent.name.lower() == "docs":
            docs_count += 1
        language = LANGUAGE_BY_EXTENSION.get(ext)
        if language:
            line_count = sum(1 for line in text.splitlines() if line.strip())
            loc_by_language[language] += line_count
            if is_test_file(path):
                test_count += 1
            else:
                source_count += 1
    return {
        "lines_of_code": dict(sorted(loc_by_language.items())),
        "source_files": source_count,
        "test_files": test_count,
        "documentation_files": docs_count,
    }


def parse_coverage(root: Path) -> Tuple[str, str]:
    coverage_xml = root / "coverage.xml"
    if coverage_xml.exists():
        text = safe_read_text(coverage_xml)
        match = re.search(r'line-rate="([0-9.]+)"', text)
        if match:
            value = round(float(match.group(1)) * 100, 2)
            return (f"{value}%", "coverage.xml")
    for path in [root / "lcov.info", root / "coverage/lcov.info"]:
        if path.exists():
            lines_found = 0
            lines_hit = 0
            for line in safe_read_text(path).splitlines():
                if line.startswith("LF:"):
                    lines_found += int(line.split(":", 1)[1])
                elif line.startswith("LH:"):
                    lines_hit += int(line.split(":", 1)[1])
            if lines_found:
                value = round((lines_hit / lines_found) * 100, 2)
                return (f"{value}%", str(path.relative_to(root)))
    return ("Not available", "No coverage.xml or lcov.info found")


def detect_linting_score(root: Path) -> Tuple[str, str]:
    report_candidates = [
        root / "pylint-report.txt",
        root / "eslint-report.json",
        root / "ruff-report.txt",
        root / "golangci-lint-report.txt",
    ]
    for path in report_candidates:
        text = safe_read_text(path)
        if not text:
            continue
        score_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*100", text)
        if score_match:
            return (f"{score_match.group(1)}/100", str(path.relative_to(root)))
    configs = [
        root / "pyproject.toml",
        root / ".ruff.toml",
        root / ".eslintrc",
        root / ".eslintrc.json",
        root / ".pylintrc",
        root / ".golangci.yml",
        root / ".golangci.yaml",
    ]
    for path in configs:
        if path.exists():
            return ("Configured - report not generated", str(path.relative_to(root)))
    return ("Not configured", "No lint configuration or report found")


def detect_documentation(root: Path) -> Dict[str, Any]:
    present = []
    missing = []
    for name in DOCUMENTATION_FILES:
        path = root / name.rstrip("/")
        exists = path.exists() if not name.endswith("/") else path.is_dir()
        (present if exists else missing).append(name)
    ratio = len(present) / len(DOCUMENTATION_FILES)
    if ratio >= 0.8:
        coverage = "good"
    elif ratio >= 0.5:
        coverage = "partial"
    else:
        coverage = "minimal"
    assessment = (
        f"Documentation coverage is {coverage}. Present: {', '.join(present) or 'none'}. "
        f"Missing: {', '.join(missing) or 'none'}."
    )
    return {"coverage": coverage, "present": present, "missing": missing, "assessment": assessment}


def detect_technology_stack(root: Path, metrics: Dict[str, Any]) -> List[Dict[str, str]]:
    stack: List[Dict[str, str]] = []
    package = load_json(root / "package.json")
    if package:
        stack.append({"technology": "Node.js", "version": str(package.get("engines", {}).get("node", "Detected from package.json")), "evidence": "package.json"})
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        stack.append({"technology": "Python", "version": "Detected from project manifests", "evidence": "pyproject.toml / requirements.txt"})
    if (root / "go.mod").exists():
        stack.append({"technology": "Go", "version": "Detected from go.mod", "evidence": "go.mod"})
    if (root / "Cargo.toml").exists():
        stack.append({"technology": "Rust", "version": "Detected from Cargo.toml", "evidence": "Cargo.toml"})
    if (root / "pom.xml").exists() or (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        stack.append({"technology": "Java", "version": "Detected from build manifest", "evidence": "pom.xml / build.gradle"})
    if any(iter_files(root, ["Dockerfile", "Dockerfile.*", "docker-compose.yml", "docker-compose.yaml"])):
        stack.append({"technology": "Containers", "version": "Docker / OCI", "evidence": "container manifests"})
    if any(iter_files(root, ["*.tf", "**/*.tf"])):
        stack.append({"technology": "Terraform", "version": "Infrastructure as Code", "evidence": "Terraform files"})
    for language, loc in metrics["lines_of_code"].items():
        if loc > 0 and language not in {item["technology"] for item in stack}:
            stack.append({"technology": language, "version": "Detected from source files", "evidence": f"{loc} LOC"})
    return stack or [{"technology": "Unknown", "version": "Manual review required", "evidence": "No common manifests detected"}]


def extract_requirements(root: Path, project_name: str, stack: List[Dict[str, str]], documentation: Dict[str, Any], metrics: Dict[str, Any], dependencies: List[Dict[str, str]]) -> List[Dict[str, str]]:
    candidates: List[str] = []
    doc_paths = [root / "README.md"]
    if (root / "docs").exists():
        doc_paths.extend(sorted((root / "docs").glob("*.md")))
    for doc_path in doc_paths:
        text = safe_read_text(doc_path)
        if not text:
            continue
        for line in text.splitlines():
            stripped = re.sub(r"^[-*]\s+", "", line.strip())
            if not stripped:
                continue
            if re.search(r"\b(must|should|supports?|provides?|enables?|requires?)\b", stripped, flags=re.IGNORECASE):
                candidates.append(stripped)
            elif line.strip().startswith(("-", "*")) and 25 <= len(stripped) <= 180:
                candidates.append(stripped)
    tech_names = ", ".join(item["technology"] for item in stack[:4]) or "detected technologies"
    heuristics = [
        f"{project_name} must support the detected technology stack ({tech_names}) with maintainable dependency manifests.",
        f"{project_name} should maintain documentation coverage for onboarding, change tracking, and operational handover.",
        (
            f"{project_name} must preserve automated verification through the detected test suite."
            if metrics["test_files"]
            else f"{project_name} requires automated test coverage to reduce delivery and regression risk."
        ),
        (
            f"{project_name} must monitor and remediate third-party dependency vulnerabilities with documented mitigations."
            if dependencies
            else f"{project_name} should establish a dependency inventory before release planning."
        ),
        (
            f"{project_name} should improve missing documentation artefacts: {', '.join(documentation['missing'])}."
            if documentation["missing"]
            else f"{project_name} should keep core documentation artefacts current as the codebase evolves."
        ),
    ]
    candidates.extend(heuristics)
    requirements: List[Dict[str, str]] = []
    seen = set()
    for statement in candidates:
        cleaned = re.sub(r"\s+", " ", statement).strip(" .")
        if len(cleaned) < 20:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        requirements.append({"id": f"REQ-{len(requirements)+1:03d}", "statement": cleaned + "." if not cleaned.endswith(".") else cleaned})
        seen.add(key)
        if len(requirements) == 8:
            break
    return requirements[:8]


def detect_architecture_reference(root: Path) -> Dict[str, str]:
    readme = safe_read_text(root / "README.md")
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", readme):
        candidate = match.group(1)
        if any(token in candidate.lower() for token in ["arch", "diagram", "design", "c4"]):
            return {"diagram_reference": candidate, "description": f"Architecture evidence found in README image reference: {candidate}."}
    for path in iter_files(root, ["*.mmd", "*.drawio", "*.puml", "docs/diagrams/*", "**/*architecture*.*"]):
        return {"diagram_reference": str(path.relative_to(root)), "description": f"Architecture asset detected at {path.relative_to(root)}."}
    top_dirs = [child.name for child in root.iterdir() if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith(".")][:5]
    description = f"No formal architecture diagram was detected. A repository-structure view suggests major modules in: {', '.join(top_dirs) or 'application root'}."
    return {"diagram_reference": "Inferred repository structure", "description": description}


def summarize_risks(documentation: Dict[str, Any], dependencies: List[Dict[str, str]], metrics: Dict[str, Any], coverage: str) -> List[Dict[str, str]]:
    risks: List[Dict[str, str]] = []
    unresolved = [dep for dep in dependencies if dep["cve_status"].startswith(("HIGH", "CRITICAL"))]
    if unresolved:
        risks.append({
            "severity": "HIGH",
            "risk": f"{len(unresolved)} dependency entries matched known vulnerable version patterns.",
            "impact": "Potential security exposure and release delay until upgrades or mitigations are documented.",
            "mitigation": "Upgrade flagged packages and record compensating controls where immediate patching is not possible.",
        })
    if documentation["missing"]:
        risks.append({
            "severity": "MEDIUM",
            "risk": f"Missing documentation artefacts: {', '.join(documentation['missing'])}.",
            "impact": "Increased onboarding, audit, and operational handover risk.",
            "mitigation": "Create or refresh the missing documents before later SDLC phases rely on them.",
        })
    if coverage == "Not available":
        risks.append({
            "severity": "MEDIUM",
            "risk": "No machine-readable test coverage report was detected.",
            "impact": "Confidence in regression safety is reduced.",
            "mitigation": "Generate coverage.xml or lcov.info as part of CI evidence collection.",
        })
    if metrics["test_files"] == 0:
        risks.append({
            "severity": "HIGH",
            "risk": "No test files were detected in the repository scan.",
            "impact": "High chance of regressions and weak release readiness evidence.",
            "mitigation": "Add automated tests and connect them to CI before production delivery.",
        })
    return risks or [{
        "severity": "LOW",
        "risk": "No blocking risks detected from the local heuristic scan.",
        "impact": "Proceed to the next SDLC phase with normal review.",
        "mitigation": "Keep dependency and documentation checks current.",
    }]


def recommended_next_steps(risks: List[Dict[str, str]], documentation: Dict[str, Any], coverage: str) -> List[str]:
    steps: List[str] = []
    if any(risk["severity"] in {"HIGH", "CRITICAL"} for risk in risks):
        steps.append("Resolve HIGH and CRITICAL dependency or test-readiness issues before architecture sign-off.")
    if documentation["missing"]:
        steps.append(f"Create or refresh missing documentation: {', '.join(documentation['missing'])}.")
    if coverage == "Not available":
        steps.append("Enable coverage.xml or lcov.info generation in CI so later phases can validate test evidence.")
    steps.append("Review extracted requirements with stakeholders and confirm scope before generating architecture artefacts.")
    steps.append("Carry forward the dependency inventory and risk register into backlog and remediation planning.")
    deduped = []
    seen = set()
    for item in steps:
        key = item.lower()
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def render_markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    def esc(value: Any) -> str:
        return str(value).replace("|", "\\|")
    lines = ["| " + " | ".join(esc(header) for header in headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(esc(cell) for cell in row) + " |")
    return "\n".join(lines)


def build_validation_status(report: Dict[str, Any]) -> str:
    unresolved = [dep for dep in report["dependencies"]["items"] if dep["cve_status"].startswith(("HIGH", "CRITICAL")) and not dep["mitigation_note"]]
    if unresolved or len(report["requirements"]) < 3:
        return "RED"
    return "GREEN"


def render_markdown(report: Dict[str, Any]) -> str:
    template = safe_read_text(TEMPLATE_PATH)
    requirement_lines = "\n".join(f"{index}. {item['statement']}" for index, item in enumerate(report["requirements"], start=1))
    doc_rows = [[name, "Present" if name in report["documentation"]["present"] else "Missing", report["documentation"]["coverage"] if index == 0 else ""] for index, name in enumerate(DOCUMENTATION_FILES)]
    dep_rows = [
        [item["name"], item["version"], item["license"], item["cve_status"], item["mitigation_note"] or "-"]
        for item in report["dependencies"]["items"][:20]
    ] or [["No dependencies detected", "-", "-", "-", "-"]]
    quality_rows = [
        ["Source files", str(report["code_quality"]["source_files"])],
        ["Test files", str(report["code_quality"]["test_files"])],
        ["Lines of code by language", ", ".join(f"{lang}: {loc}" for lang, loc in report["code_quality"]["lines_of_code"].items()) or "None detected"],
        ["Test coverage", report["code_quality"]["test_coverage_percent"]],
        ["Coverage evidence", report["code_quality"]["coverage_source"]],
        ["Linting score", report["code_quality"]["linting_score"]],
        ["Linting evidence", report["code_quality"]["linting_evidence"]],
    ]
    risk_rows = [[risk["severity"], risk["risk"], risk["impact"], risk["mitigation"]] for risk in report["risks"]]
    next_steps = "\n".join(f"- {item}" for item in report["recommended_next_steps"])
    validation = report["validation_status"]
    tokens = {
        "{{PROJECT_NAME}}": report["project"]["name"],
        "{{PROJECT_DESCRIPTION}}": report["project"]["description"],
        "{{GENERATED_AT}}": report["generated_at"],
        "{{REPO_CONTEXT}}": f"Branch: {report['git_context']['branch']}  |  Commit: {report['git_context']['commit']}",
        "{{ARCHITECTURE_REFERENCE}}": report["architecture"]["description"],
        "{{REQUIREMENTS_BLOCK}}": requirement_lines,
        "{{DOCUMENTATION_TABLE}}": render_markdown_table(["Artefact", "Status", "Coverage Profile"], doc_rows),
        "{{DOCUMENTATION_ASSESSMENT}}": report["documentation"]["assessment"],
        "{{DEPENDENCY_TABLE}}": render_markdown_table(["Name", "Version", "License", "CVE Status", "Mitigation / Notes"], dep_rows),
        "{{QUALITY_TABLE}}": render_markdown_table(["Metric", "Value"], quality_rows),
        "{{TECH_STACK}}": ", ".join(f"{item['technology']} ({item['evidence']})" for item in report["technology_stack"]),
        "{{RISK_TABLE}}": render_markdown_table(["Severity", "Risk", "Impact", "Mitigation"], risk_rows),
        "{{NEXT_STEPS}}": next_steps,
        "{{VALIDATION_STATUS}}": validation,
        "{{VALIDATION_BADGE}}": f"![Validation Status](https://img.shields.io/badge/Validation-{validation}-{'brightgreen' if validation == 'GREEN' else 'red'})",
    }
    rendered = template
    for key, value in tokens.items():
        rendered = rendered.replace(key, value)
    return rendered


def build_report(project_root: Path) -> Dict[str, Any]:
    metrics = collect_source_metrics(project_root)
    coverage_value, coverage_source = parse_coverage(project_root)
    linting_score, linting_evidence = detect_linting_score(project_root)
    documentation = detect_documentation(project_root)
    dependencies = collect_dependencies(project_root)
    stack = detect_technology_stack(project_root, metrics)
    requirements = extract_requirements(project_root, detect_project_name(project_root), stack, documentation, metrics, dependencies)
    architecture = detect_architecture_reference(project_root)
    risks = summarize_risks(documentation, dependencies, metrics, coverage_value)
    report = {
        "project": {
            "name": detect_project_name(project_root),
            "description": detect_description(project_root),
            "root": str(project_root),
        },
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "git_context": git_context(project_root),
        "requirements": requirements,
        "documentation": documentation,
        "dependencies": {
            "count": len(dependencies),
            "items": dependencies,
        },
        "code_quality": {
            **metrics,
            "test_coverage_percent": coverage_value,
            "coverage_source": coverage_source,
            "linting_score": linting_score,
            "linting_evidence": linting_evidence,
        },
        "technology_stack": stack,
        "architecture": architecture,
        "risks": risks,
        "recommended_next_steps": recommended_next_steps(risks, documentation, coverage_value),
    }
    report["validation_status"] = build_validation_status(report)
    return report


def write_outputs(report: Dict[str, Any], output_dir: Path, output_format: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_format in {"json", "both"}:
        (output_dir / "source-code-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if output_format in {"markdown", "both"}:
        (output_dir / "analysis-report.md").write_text(render_markdown(report), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local SDLC analysis fallback for a repository.")
    parser.add_argument("--project-root", default=".", help="Repository root to scan.")
    parser.add_argument("--output-dir", default="analysis", help="Directory to write report artefacts into.")
    parser.add_argument("--format", choices=["json", "markdown", "both"], default="both", help="Which output formats to write.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    report = build_report(project_root)
    write_outputs(report, output_dir, args.format)
    print(json.dumps({
        "validation_status": report["validation_status"],
        "output_dir": str(output_dir),
        "requirements": len(report["requirements"]),
        "dependencies": report["dependencies"]["count"],
    }, indent=2))
    validator = Path(__file__).with_name("validate_analysis.py")
    report_file = output_dir / ("analysis-report.md" if args.format == "markdown" else "source-code-report.json")
    validation = subprocess.run([sys.executable, str(validator), str(report_file)], check=False, capture_output=True, text=True)
    if validation.stdout:
        print(validation.stdout.rstrip())
    if validation.stderr:
        print(validation.stderr.rstrip(), file=sys.stderr)
    return validation.returncode


if __name__ == "__main__":
    raise SystemExit(main())
