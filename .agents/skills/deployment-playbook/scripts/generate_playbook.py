#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Generate enterprise deployment playbooks from project scans."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_ROOT / "templates"
DEFAULT_TEMPLATE = TEMPLATE_DIR / "deployment-playbook.md"
ENV_ORDER = ["dev", "qa", "test", "staging", "uat", "preprod", "prod"]
REGION_RE = re.compile(r"\b(?:us|eu|ap|sa|ca|af|me)-(?:gov-)?[a-z]+-\d\b")


def log(level: str, message: str) -> None:
    print(f"[{level}] {message}", file=sys.stderr)


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def iter_files(root: Path, patterns: Iterable[str]) -> Iterable[Path]:
    seen: Set[Path] = set()
    for pattern in patterns:
        for path in root.rglob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def detect_project_name(root: Path) -> str:
    package_json = root / "package.json"
    if package_json.exists():
        try:
            data = json.loads(safe_read_text(package_json))
            name = data.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        except json.JSONDecodeError:
            log("WARN", f"Could not parse {package_json}")

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        match = re.search(r"(?ms)^\[project\].*?^name\s*=\s*['\"]([^'\"]+)['\"]", safe_read_text(pyproject))
        if match:
            return match.group(1).strip()

    readme = root / "README.md"
    if readme.exists():
        for line in safe_read_text(readme).splitlines():
            if line.startswith("# "):
                return line[2:].strip()

    return root.name


def detect_tech_stack(root: Path) -> List[str]:
    stack: List[str] = []
    if any(iter_files(root, ["package.json"])):
        stack.append("Node.js")
    if any(iter_files(root, ["requirements.txt", "pyproject.toml"])):
        stack.append("Python")
    if any(iter_files(root, ["go.mod"])):
        stack.append("Go")
    if any(iter_files(root, ["pom.xml", "build.gradle", "build.gradle.kts"])):
        stack.append("Java")
    if any(iter_files(root, ["Dockerfile", "Dockerfile.*", "docker-compose.yml", "docker-compose.yaml"])):
        stack.append("Containers")
    return stack or ["Unknown"]


def detect_regions(root: Path) -> List[str]:
    candidates = list(iter_files(root, ["*.tf", "*.tfvars", "*.yaml", "*.yml", "*.json", ".env*", "README.md"]))
    regions: Set[str] = set()
    for path in candidates:
        content = safe_read_text(path)
        for match in REGION_RE.findall(content):
            regions.add(match)
    return sorted(regions)


def detect_environments(root: Path) -> List[str]:
    content_sources = list(iter_files(root, ["*.tf", "*.tfvars", "*.yaml", "*.yml", "*.json", ".env*", "README.md", "package.json"]))
    found: Set[str] = set()
    aliases = {
        "dev": ["dev", "development"],
        "qa": ["qa"],
        "test": ["test"],
        "staging": ["staging", "stage"],
        "uat": ["uat"],
        "preprod": ["preprod", "pre-prod"],
        "prod": ["prod", "production"],
    }
    for path in content_sources:
        text = safe_read_text(path).lower()
        for env, patterns in aliases.items():
            if any(re.search(rf"\b{re.escape(pattern)}\b", text) for pattern in patterns):
                found.add(env)
    ordered = [env for env in ENV_ORDER if env in found]
    return ordered or ["dev", "staging", "prod"]


def detect_deployment_model(root: Path) -> str:
    if any(iter_files(root, ["Dockerfile", "Dockerfile.*", "docker-compose.yml", "docker-compose.yaml"])):
        return "Containerized application release using controlled progressive rollout"
    if any(iter_files(root, ["*.tf", "*.tfvars"])):
        return "Infrastructure-as-code driven deployment using staged environment promotion"
    if any(iter_files(root, ["serverless.yml", "serverless.yaml", "template.yaml", "template.yml"])):
        return "Automated cloud deployment using an infrastructure template and controlled promotion"
    return "Controlled application deployment via approved automation"


def discover_components(root: Path) -> List[Dict[str, Any]]:
    indicators = {
        "package.json": "application manifest",
        "pyproject.toml": "python project file",
        "requirements.txt": "python requirements",
        "go.mod": "go module",
        "pom.xml": "java build manifest",
        "build.gradle": "java build manifest",
        "build.gradle.kts": "java build manifest",
        "Dockerfile": "container image definition",
        "docker-compose.yml": "compose deployment file",
        "docker-compose.yaml": "compose deployment file",
        "serverless.yml": "serverless deployment file",
        "serverless.yaml": "serverless deployment file",
        "template.yaml": "cloud formation template",
        "template.yml": "cloud formation template",
    }
    components: Dict[str, Dict[str, Any]] = {}

    for path in iter_files(
        root,
        [
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "go.mod",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "serverless.yml",
            "serverless.yaml",
            "template.yaml",
            "template.yml",
            "*.tf",
            "deploy*.sh",
            "deploy*.py",
        ],
    ):
        rel = path.relative_to(root)
        parts = rel.parts
        anchor = Path(parts[0]) if len(parts) > 1 else Path(".")
        if parts and parts[0] == ".github":
            anchor = Path(".")
        if path.name.startswith("deploy") and "scripts" in parts:
            index = parts.index("scripts")
            anchor = Path(*parts[:index]) if index > 0 else Path(".")
        component_key = str(anchor)
        component = components.setdefault(
            component_key,
            {
                "name": root.name if component_key == "." else anchor.name,
                "path": component_key,
                "signals": [],
            },
        )
        if path.suffix in {".tf", ".tfvars"}:
            signal = "terraform configuration"
        elif "deploy" in path.name.lower() and path.suffix in {".sh", ".py"}:
            signal = "deployment script"
        else:
            signal = indicators.get(path.name, path.name)
        if signal not in component["signals"]:
            component["signals"].append(signal)

    if not components:
        components["."] = {"name": root.name, "path": ".", "signals": ["project root"]}

    return sorted(components.values(), key=lambda item: (item["path"] != ".", item["name"]))


def scan_project(root: Path) -> Dict[str, Any]:
    return {
        "project_name": detect_project_name(root),
        "project_root": str(root.resolve()),
        "tech_stack": detect_tech_stack(root),
        "environments": detect_environments(root),
        "regions": detect_regions(root),
        "deployment_model": detect_deployment_model(root),
        "components": discover_components(root),
    }


def make_playbook_id(project_name: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", project_name).upper()
    prefix = (letters[:3] or "OPS").ljust(3, "X")
    return f"PLY-{prefix}-001"


def format_component_summary(components: Sequence[Dict[str, Any]]) -> str:
    lines = []
    for component in components:
        signals = ", ".join(component.get("signals", [])) or "deployment artifact"
        scope = "project root" if component["path"] == "." else component["path"]
        lines.append(f"- **{component['name']}** (`{scope}`): detected via {signals}.")
    return "\n".join(lines)


def format_environment_rows(environments: Sequence[str], regions: Sequence[str]) -> str:
    region = regions[0] if regions else "<!-- PLACEHOLDER: primary region -->"
    purpose_map = {
        "dev": "Developer integration and rapid verification",
        "qa": "Quality assurance and regression testing",
        "test": "Automated validation and system testing",
        "staging": "Pre-production dress rehearsal",
        "uat": "User acceptance validation",
        "preprod": "Production-like final validation",
        "prod": "Customer-facing production service",
    }
    rows = []
    for order, env in enumerate(environments, start=1):
        tier = "Production" if env == "prod" else "Non-Production"
        rows.append(f"| {env} | {region} | {tier} | {purpose_map.get(env, 'Environment purpose to be confirmed')} | {order} |")
    return "\n".join(rows)


def format_risk_rows(environments: Sequence[str], components: Sequence[Dict[str, Any]]) -> str:
    envs = ", ".join(environments)
    first_component = components[0]["name"] if components else "primary service"
    return "\n".join(
        [
            f"| R-001 | Deployment to {envs} introduces an undetected configuration mismatch in {first_component} | Technical | Medium | High | Validate configuration drift before release and hold rollout at each checkpoint | Platform Engineering | Open |",
            "| R-002 | Dependent downstream services may experience elevated latency during rollout | Dependency | Medium | Medium | Monitor dependency dashboards and pause rollout if latency crosses thresholds | Service Owner | Open |",
            "| R-003 | Stakeholders may miss implementation updates during the change window | Operational | Low | Medium | Use the communication plan with named owners and pre-scheduled updates | Release Manager | Open |",
        ]
    )


def format_communication_rows(owner: str) -> str:
    return "\n".join(
        [
            f"| Pre-Change | Engineering, support, service owner | Release channel and ticket update | {owner} | 24 hours before the change window |",
            f"| Change Start | Operations, stakeholders | ChatOps channel | {owner} | At deployment start |",
            f"| Phase Checkpoint | Stakeholders and incident bridge | ChatOps update | {owner} | After each major phase |",
            f"| Rollback / Escalation | Incident leadership and support | Incident channel and paging system | {owner} | Immediately if rollback trigger is met |",
            f"| Change Complete | All stakeholders | Email and ticket closure comment | {owner} | After post-deployment validation succeeds |",
        ]
    )


def format_contact_rows(owner: str) -> str:
    return "\n".join(
        [
            f"| Implementation Owner | {owner} | <!-- PLACEHOLDER: primary chat handle / phone --> | Level 1 |",
            "| Service Owner | <!-- PLACEHOLDER: service owner name --> | <!-- PLACEHOLDER: contact details --> | Level 2 |",
            "| Incident Manager | <!-- PLACEHOLDER: incident manager name --> | <!-- PLACEHOLDER: contact details --> | Level 2 |",
            "| Executive Escalation | <!-- PLACEHOLDER: executive sponsor --> | <!-- PLACEHOLDER: contact details --> | Level 3 |",
        ]
    )


def format_approval_rows() -> str:
    today = date.today().isoformat()
    return "\n".join(
        [
            f"| Service Owner | <!-- PLACEHOLDER: name --> | __________________ | {today} |",
            f"| Change Manager | <!-- PLACEHOLDER: name --> | __________________ | {today} |",
            f"| Platform Engineering Lead | <!-- PLACEHOLDER: name --> | __________________ | {today} |",
        ]
    )


def format_success_criteria(environments: Sequence[str]) -> str:
    highest = environments[-1] if environments else "prod"
    return "\n".join(
        [
            "- All deployment phases complete within the approved change window without unresolved critical incidents.",
            "- Smoke tests for authentication, core transaction paths, and external integrations pass in every promoted environment.",
            f"- Production error rate in `{highest}` does not exceed the pre-agreed threshold for more than five minutes.",
            "- p95 latency and saturation indicators remain within normal operating bounds or the documented release threshold.",
            "- No Sev1 or Sev2 alerts attributable to the release remain open after the observation window.",
            "- Service owner confirms business acceptance before the change is closed.",
        ]
    )


def format_post_deployment_checks() -> str:
    return "\n".join(
        [
            "1. Run the approved smoke-test suite and record the result in the change ticket.",
            "2. Confirm dashboards for latency, traffic, errors, saturation, and dependency health are stable.",
            "3. Review log anomalies, dead-letter queues, and failed background jobs for unexpected behavior.",
            "4. Verify business-critical workflows with the service owner or designated business approver.",
            "5. Confirm support teams have not reported new customer-impacting issues during the observation period.",
            "6. Capture final evidence, publish the closure update, and schedule a follow-up review if required.",
        ]
    )


def format_deployment_phases(owner: str, components: Sequence[Dict[str, Any]]) -> str:
    primary = components[0]["name"] if components else "primary service"
    secondary = components[1]["name"] if len(components) > 1 else "supporting components"
    return "\n\n".join(
        [
            "### Phase 1 — Pre-Deployment Readiness\n\n**Objective:** Confirm approvals, environment readiness, and rollback preparedness before any change is introduced.\n\n**Steps**\n1. Confirm the approved artifact, change ticket, and implementation window.\n2. Validate that monitoring dashboards, alerts, and support coverage are active.\n3. Confirm the last known good release for "
            + primary
            + " is immediately deployable.\n4. Verify dependencies, feature flags, secrets references, and freeze-window checks.\n\n**Dependencies:** Approved release artifact, active monitoring, stakeholder readiness.\n\n**Duration Estimate:** 15 minutes.\n\n**Rollback Trigger:** Abort before execution if any prerequisite, approval, or monitoring dependency is incomplete.",
            "### Phase 2 — Controlled Component Rollout\n\n**Objective:** Deploy "
            + primary
            + " and dependent release assets using the approved automation path.\n\n**Steps**\n1. Start the release for "
            + primary
            + " using the approved deployment pipeline.\n2. Apply any required configuration or infrastructure updates for "
            + secondary
            + ".\n3. Validate health checks, synthetic checks, and deployment pipeline signals at each checkpoint.\n4. Pause the rollout if abnormal latency, elevated errors, or failing smoke tests are observed.\n\n**Dependencies:** Healthy downstream dependencies, pipeline access, implementation owner "
            + owner
            + ".\n\n**Duration Estimate:** 30 minutes.\n\n**Rollback Trigger:** Initiate rollback if error rate or critical business-path failures exceed agreed thresholds during rollout.",
            "### Phase 3 — Progressive Validation and Promotion\n\n**Objective:** Confirm the deployment is stable and promote to the next environment or full production traffic level.\n\n**Steps**\n1. Run environment-specific smoke tests and regression probes.\n2. Review telemetry for latency, traffic, errors, and saturation.\n3. Confirm dependency health and support-team readiness before promotion.\n4. Approve promotion only after checkpoint acceptance criteria are met.\n\n**Dependencies:** Stable telemetry, successful smoke tests, service-owner checkpoint approval.\n\n**Duration Estimate:** 20 minutes.\n\n**Rollback Trigger:** Roll back if validation fails, business KPIs degrade, or support receives verified customer-impacting reports.",
            "### Phase 4 — Post-Deployment Closure\n\n**Objective:** Complete final validation, close communications, and capture audit evidence.\n\n**Steps**\n1. Confirm success criteria and observation-window checks are complete.\n2. Publish the deployment completion update to stakeholders.\n3. Attach validation evidence, dashboard snapshots, and notes to the change record.\n4. Schedule any required retrospective or PIR actions.\n\n**Dependencies:** Stable production health, validation evidence, stakeholder acknowledgement.\n\n**Duration Estimate:** 15 minutes.\n\n**Rollback Trigger:** If the observation window surfaces critical defects or instability, reopen the change and begin rollback immediately.",
        ]
    )


def generate_playbook(root: Path, output_path: Path) -> int:
    summary = scan_project(root)
    owner = os.environ.get("USER", "Platform Engineering")
    template = safe_read_text(DEFAULT_TEMPLATE)
    replacements = {
        "[PROJECT_NAME]": summary["project_name"],
        "[PLAYBOOK_ID]": make_playbook_id(summary["project_name"]),
        "[VERSION]": "1.0.0",
        "[STATUS]": "Draft",
        "[OWNER]": owner,
        "[DATE]": date.today().isoformat(),
        "[COMPONENT]": summary["components"][0]["name"] if summary["components"] else summary["project_name"],
        "[TECH_STACK]": ", ".join(summary["tech_stack"]),
        "[DEPLOYMENT_MODEL]": summary["deployment_model"],
        "[COMPONENT_SUMMARY]": format_component_summary(summary["components"]),
        "[DEPLOYMENT_PHASES]": format_deployment_phases(owner, summary["components"]),
        "[ENVIRONMENT_ROWS]": format_environment_rows(summary["environments"], summary["regions"]),
        "[CHANGE_TYPE]": "Normal",
        "[CHANGE_WINDOW]": "<!-- PLACEHOLDER: approved implementation window -->",
        "[RISK_ROWS]": format_risk_rows(summary["environments"], summary["components"]),
        "[COMMUNICATION_ROWS]": format_communication_rows(owner),
        "[SUCCESS_CRITERIA]": format_success_criteria(summary["environments"]),
        "[POST_DEPLOYMENT_CHECKS]": format_post_deployment_checks(),
        "[CONTACT_ROWS]": format_contact_rows(owner),
        "[APPROVAL_ROWS]": format_approval_rows(),
    }
    output = template
    for token, value in replacements.items():
        output = output.replace(token, value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output, encoding="utf-8")
    log("INFO", f"Generated playbook at {output_path}")
    return 0


def list_templates() -> int:
    for path in sorted(TEMPLATE_DIR.glob("*.md")):
        print(path.name)
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan a project and generate deployment playbooks.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan", metavar="DIR", help="Scan a project directory and print a JSON summary")
    group.add_argument("--generate", metavar="DIR", help="Scan a project directory and generate a deployment playbook")
    group.add_argument("--list-templates", action="store_true", help="List available templates")
    parser.add_argument("--output", metavar="FILE", help="Output markdown file for --generate")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.list_templates:
            return list_templates()
        target = Path(args.scan or args.generate).expanduser().resolve()
        if not target.exists() or not target.is_dir():
            log("ERROR", f"Project directory not found: {target}")
            return 1
        if args.scan:
            log("INFO", f"Scanning project: {target}")
            print(json.dumps(scan_project(target), indent=2))
            return 0
        if not args.output:
            log("ERROR", "--output is required with --generate")
            return 1
        log("INFO", f"Generating playbook from project: {target}")
        return generate_playbook(target, Path(args.output).expanduser().resolve())
    except Exception as exc:
        log("ERROR", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
