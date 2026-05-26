#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Generate local SDLC architecture artefacts from repository evidence."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

SKILL_ROOT = Path(__file__).resolve().parent.parent
HLD_TEMPLATE_PATH = SKILL_ROOT / "templates" / "hld.md"
ADR_TEMPLATE_PATH = SKILL_ROOT / "templates" / "adr.md"
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    "target",
}
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
    ".tf": "Terraform",
    ".sql": "SQL",
    ".sh": "Shell",
}
IGNORE_COMPONENTS = {"tests", "test", "docs", "scripts", ".github", ".agents", "analysis", "architecture"}


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def safe_load_json(path: Path) -> Dict[str, Any]:
    text = safe_read_text(path)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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


def slug_to_title(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", value)).strip().title()


def detect_project_name(root: Path, analysis_report: Dict[str, Any]) -> str:
    project = analysis_report.get("project") if isinstance(analysis_report.get("project"), dict) else {}
    if isinstance(project.get("name"), str) and project["name"].strip():
        return project["name"].strip()
    package_json = safe_load_json(root / "package.json")
    if isinstance(package_json.get("name"), str) and package_json["name"].strip():
        return package_json["name"].strip()
    return root.name


def collect_component_candidates(root: Path) -> List[Dict[str, str]]:
    components: List[Dict[str, str]] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name):
        if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS or child.name in IGNORE_COMPONENTS:
            continue
        code_files = list(iter_files(child, ["*.py", "*.js", "*.ts", "*.go", "*.java", "*.rs", "*.tf", "*.sql"]))
        if not code_files:
            continue
        language_counts: Dict[str, int] = {}
        for path in code_files:
            language = LANGUAGE_BY_EXTENSION.get(path.suffix.lower(), "Unknown")
            language_counts[language] = language_counts.get(language, 0) + 1
        dominant_language = max(language_counts.items(), key=lambda item: item[1])[0]
        name = slug_to_title(child.name)
        lowered = child.name.lower()
        if any(token in lowered for token in ["api", "route", "web", "ui"]):
            responsibility = "Expose user or service-facing interfaces and coordinate request handling."
            interfaces = "HTTP / UI / request-response"
        elif any(token in lowered for token in ["service", "domain", "core", "agent"]):
            responsibility = "Implement core business workflows and orchestration logic."
            interfaces = "Internal service APIs and domain events"
        elif any(token in lowered for token in ["data", "model", "db", "repo", "store"]):
            responsibility = "Persist and retrieve application state and reference data."
            interfaces = "Database queries and repository interfaces"
        elif any(token in lowered for token in ["infra", "iac", "terraform", "deploy"]):
            responsibility = "Define deployment, runtime, and infrastructure provisioning concerns."
            interfaces = "Infrastructure APIs and deployment pipelines"
        else:
            responsibility = "Provide a bounded application capability inferred from repository structure."
            interfaces = "Internal module contracts"
        components.append({
            "name": name,
            "responsibility": responsibility,
            "technology": dominant_language,
            "interfaces": interfaces,
        })
    if components:
        return components[:8]
    return [{
        "name": "Application Core",
        "responsibility": "Primary business logic and orchestration inferred from repository entry points.",
        "technology": "Detected source language",
        "interfaces": "Internal service APIs",
    }]


def infer_technology_stack(root: Path, analysis_report: Dict[str, Any], components: List[Dict[str, str]]) -> List[Dict[str, str]]:
    stack = analysis_report.get("technology_stack") if isinstance(analysis_report.get("technology_stack"), list) else []
    normalized: List[Dict[str, str]] = []
    for item in stack:
        if isinstance(item, dict) and item.get("technology"):
            normalized.append({
                "technology": str(item.get("technology")),
                "version": str(item.get("version", "Detected from analysis")),
                "evidence": str(item.get("evidence", "analysis/source-code-report.json")),
                "rationale": "Carried forward from analysis evidence.",
            })
    if normalized:
        return normalized
    deduped = []
    seen = set()
    for component in components:
        technology = component["technology"]
        if technology not in seen:
            deduped.append({
                "technology": technology,
                "version": "Detected from repository structure",
                "evidence": component["name"],
                "rationale": "Dominant implementation language inferred from component scan.",
            })
            seen.add(technology)
    return deduped or [{
        "technology": "Unknown",
        "version": "Manual review required",
        "evidence": "No technology evidence found",
        "rationale": "Add explicit stack decisions in a follow-up ADR.",
    }]


def infer_requirements(analysis_report: Dict[str, Any]) -> List[str]:
    requirements = analysis_report.get("requirements") if isinstance(analysis_report.get("requirements"), list) else []
    statements = []
    for item in requirements[:5]:
        if isinstance(item, dict) and item.get("statement"):
            statements.append(str(item["statement"]))
        elif isinstance(item, str):
            statements.append(item)
    return statements or ["No prior analysis report was available; this architecture was inferred from repository structure."]


def sanitize_node(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return cleaned or "node"


def build_component_diagram(project_name: str, components: List[Dict[str, str]]) -> str:
    lines = [
        "flowchart LR",
        f"    user([User / Caller]) --> {sanitize_node(project_name)}",
        f"    {sanitize_node(project_name)}[{project_name}]",
    ]
    previous = sanitize_node(project_name)
    for component in components:
        node = sanitize_node(component["name"])
        lines.append(f"    {previous} --> {node}[{component['name']}]")
        previous = node
    lines.append(f"    {previous} --> external[(External Services / Data Stores)]")
    return "\n".join(lines) + "\n"


def render_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def load_template(path: Path) -> str:
    return safe_read_text(path)


def build_hld(project_name: str, analysis_report: Dict[str, Any], components: List[Dict[str, str]], tech_stack: List[Dict[str, str]], component_diagram_path: str) -> str:
    template = load_template(HLD_TEMPLATE_PATH)
    requirements = infer_requirements(analysis_report)
    system_context = f"""```mermaid
C4Context
title {project_name} - System Context
Person(user, \"Primary User\", \"Business or operational user\")
System(system, \"{project_name}\", \"Core platform under design\")
System_Ext(ext, \"External Services\", \"Third-party dependencies, cloud services, and data providers\")
Rel(user, system, \"Uses\")
Rel(system, ext, \"Integrates with\")
```"""
    container_diagram = "\n".join([
        "```mermaid",
        "C4Container",
        f"title {project_name} - Container Architecture",
        f"System_Boundary(sys, \"{project_name}\") {{",
        *[f"  Container({sanitize_node(component['name'])}, \"{component['name']}\", \"{component['technology']}\", \"{component['responsibility']}\")" for component in components],
        "}",
        "Person(user, \"Primary User\", \"Consumes platform capabilities\")",
        f"Rel(user, {sanitize_node(components[0]['name'])}, \"Uses\")",
        "```",
    ])
    component_rows = render_table(
        ["Component", "Responsibility", "Technology", "Interfaces"],
        [[item["name"], item["responsibility"], item["technology"], item["interfaces"]] for item in components],
    )
    stack_rows = render_table(
        ["Technology", "Version", "Evidence", "Rationale"],
        [[item["technology"], item["version"], item["evidence"], item["rationale"]] for item in tech_stack],
    )
    integration_rows = render_table(
        ["Integration Point", "Direction", "Protocol / Interface", "Notes"],
        [
            [components[0]["name"], "Inbound", "HTTP / CLI / SDK", "Primary entry point inferred from repository structure."],
            [components[-1]["name"], "Outbound", "Service API / data store", "Depends on external systems and third-party integrations."],
        ],
    )
    risk_rows = render_table(
        ["Risk", "Impact", "Trade-off / Mitigation"],
        [
            ["Repository-inferred boundaries may omit hidden runtime components.", "Architecture may need refinement after stakeholder review.", "Validate the component map with engineering and operations."],
            ["Technology choices inherit current codebase constraints.", "Modernisation options may be limited by compatibility.", "Record deviations and upgrades in ADR follow-ups."],
        ],
    )
    adr_links = "- [ADR 001 — Initial architecture baseline](adrs/001-initial-architecture-baseline.md)"
    tokens = {
        "{{PROJECT_NAME}}": project_name,
        "{{VERSION}}": "0.1.0",
        "{{STATUS}}": "Draft",
        "{{AUTHORS}}": "agentskills",
        "{{GENERATED_AT}}": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "{{EXECUTIVE_SUMMARY}}": f"This High-Level Design translates the analysis phase into a baseline architecture for {project_name}. The design emphasizes component clarity, technology traceability, and readiness for downstream backlog, implementation, and review workflows.",
        "{{BUSINESS_CONTEXT}}": "\n".join(f"- {item}" for item in requirements),
        "{{SYSTEM_CONTEXT_DIAGRAM}}": system_context,
        "{{CONTAINER_DIAGRAM}}": container_diagram,
        "{{COMPONENT_TABLE}}": component_rows,
        "{{TECH_STACK_TABLE}}": stack_rows,
        "{{NFR_LIST}}": "- Performance: design for observable request latency and predictable throughput.\n- Scalability: keep component boundaries explicit so horizontal scaling and decomposition remain possible.\n- Security: preserve least privilege, dependency hygiene, and auditable control points.",
        "{{INTEGRATION_POINTS}}": integration_rows,
        "{{SECURITY_ARCHITECTURE}}": "Authentication, authorization, secret handling, and dependency-risk remediation should follow the controls identified during analysis. Security boundaries should be enforced at entry points and external integrations.",
        "{{DEPLOYMENT_ARCHITECTURE}}": f"Deploy the solution as a set of bounded components with environment-specific configuration, CI-driven promotion, and explicit observability hooks. The standalone Mermaid component view is stored in `{component_diagram_path}`.",
        "{{RISK_TABLE}}": risk_rows,
        "{{ADR_LINKS}}": adr_links,
    }
    rendered = template
    for key, value in tokens.items():
        rendered = rendered.replace(key, value)
    return rendered


def build_adr(project_name: str, components: List[Dict[str, str]], tech_stack: List[Dict[str, str]]) -> str:
    template = load_template(ADR_TEMPLATE_PATH)
    primary_component = components[0]["name"]
    primary_stack = ", ".join(item["technology"] for item in tech_stack[:3])
    tokens = {
        "{{TITLE}}": "ADR 001: Establish the initial component baseline",
        "{{STATUS}}": "Accepted",
        "{{CONTEXT}}": f"The project requires a documented baseline architecture so later implementation and review phases inherit a clear HLD, component boundaries, and a traceable technology rationale. Repository evidence indicates {primary_component} as a primary capability area with the stack centered on {primary_stack or 'the detected implementation technologies'}.",
        "{{DECISION}}": "Adopt a component-oriented baseline architecture, capture it in the HLD, and maintain architecture rationale through MADR-formatted ADRs stored alongside the design artefacts.",
        "{{POSITIVE}}": "Creates a consistent handoff from analysis into design, backlog, and implementation.",
        "{{NEGATIVE}}": "Repository-inferred boundaries may need refinement once runtime and stakeholder information is confirmed.",
        "{{NEUTRAL}}": "Additional ADRs can supersede this baseline without invalidating the overall documentation pattern.",
        "{{LINKS}}": "- ../hld.md\n- ../../analysis/source-code-report.json",
    }
    rendered = template
    for key, value in tokens.items():
        rendered = rendered.replace(key, value)
    return rendered


def build_tech_stack(project_name: str, tech_stack: List[Dict[str, str]]) -> str:
    rows = render_table(["Technology", "Version", "Evidence", "Rationale"], [[item["technology"], item["version"], item["evidence"], item["rationale"]] for item in tech_stack])
    return f"# Technology Stack Recommendation — {project_name}\n\n{rows}\n"


def write_outputs(output_dir: Path, project_name: str, hld: str, diagram: str, adr: str, tech_stack_doc: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    adrs_dir = output_dir / "adrs"
    adrs_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "hld.md").write_text(hld, encoding="utf-8")
    (output_dir / "component-diagram.mmd").write_text(diagram, encoding="utf-8")
    (output_dir / "tech-stack.md").write_text(tech_stack_doc, encoding="utf-8")
    (adrs_dir / "001-initial-architecture-baseline.md").write_text(adr, encoding="utf-8")
    summary = {
        "project": project_name,
        "output_dir": str(output_dir),
        "artifacts": [
            str(output_dir / "hld.md"),
            str(output_dir / "component-diagram.mmd"),
            str(adrs_dir / "001-initial-architecture-baseline.md"),
            str(output_dir / "tech-stack.md"),
        ],
    }
    (output_dir / "architecture-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate local SDLC architecture artefacts from repository evidence.")
    parser.add_argument("--project-root", default=".", help="Repository root to scan.")
    parser.add_argument("--output-dir", default="architecture", help="Directory to write architecture artefacts into.")
    parser.add_argument("--analysis-report", default="analysis/source-code-report.json", help="Path to the analysis JSON report.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    analysis_report = safe_load_json(Path(args.analysis_report).expanduser().resolve())
    project_name = detect_project_name(project_root, analysis_report)
    components = collect_component_candidates(project_root)
    tech_stack = infer_technology_stack(project_root, analysis_report, components)
    component_diagram = build_component_diagram(project_name, components)
    hld = build_hld(project_name, analysis_report, components, tech_stack, "component-diagram.mmd")
    adr = build_adr(project_name, components, tech_stack)
    tech_stack_doc = build_tech_stack(project_name, tech_stack)
    write_outputs(output_dir, project_name, hld, component_diagram, adr, tech_stack_doc)
    print(json.dumps({"project": project_name, "components": len(components), "output_dir": str(output_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
