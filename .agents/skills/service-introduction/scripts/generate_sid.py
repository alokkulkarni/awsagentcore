#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Generate Service Introduction Documents (SID) from repository scans and user context."""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_ROOT / "templates"
SCRIPT_DIR = Path(__file__).resolve().parent
VALIDATOR_PATH = SCRIPT_DIR / "validate_sid.py"
COLLECTOR_PATH = SCRIPT_DIR / "collect_info.py"
SKIP_DIRS = {"node_modules", "__pycache__", ".git", "dist", "build", "vendor", ".venv", "target"}
SERVICE_PATTERNS = {
    "s3": "Amazon S3",
    "dynamodb": "Amazon DynamoDB",
    "sqs": "Amazon SQS",
    "sns": "Amazon SNS",
    "lambda": "AWS Lambda",
    "bedrock": "Amazon Bedrock",
    "opensearch": "Amazon OpenSearch",
    "rds": "Amazon RDS",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "redis": "Redis",
    "mongodb": "MongoDB",
    "stripe": "Stripe",
    "twilio": "Twilio",
    "slack": "Slack",
    "openai": "OpenAI",
    "azure": "Microsoft Azure",
    "gcp": "Google Cloud",
    "google cloud": "Google Cloud",
    "github": "GitHub"
}
API_ROUTE_PATTERNS = [
    re.compile(r"app\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE),
    re.compile(r"router\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE),
    re.compile(r"@(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE),
    re.compile(r"@app\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
]


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
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        base = Path(current_root)
        for file_name in files:
            path = base / file_name
            relative = path.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(file_name, pattern) or fnmatch.fnmatch(relative, pattern) for pattern in pattern_list):
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


def toml_value(text: str, section: str, key: str) -> str:
    pattern = rf"(?ms)^\[{re.escape(section)}\].*?^\s*{re.escape(key)}\s*=\s*['\"]([^'\"]+)['\"]"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def detect_project_name(root: Path) -> str:
    package = load_json(root / "package.json")
    if isinstance(package.get("name"), str) and package["name"].strip():
        return package["name"].strip()

    pyproject = safe_read_text(root / "pyproject.toml")
    if pyproject:
        value = toml_value(pyproject, "project", "name")
        if value:
            return value

    go_mod = safe_read_text(root / "go.mod")
    if go_mod:
        match = re.search(r"(?m)^module\s+(.+)$", go_mod)
        if match:
            return match.group(1).strip().split("/")[-1]

    cargo = safe_read_text(root / "Cargo.toml")
    if cargo:
        value = toml_value(cargo, "package", "name")
        if value:
            return value

    readme = safe_read_text(root / "README.md")
    for line in readme.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()

    return root.name


def detect_description(root: Path) -> str:
    readme = safe_read_text(root / "README.md")
    if readme:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", readme) if item.strip()]
        for paragraph in paragraphs:
            if paragraph.startswith("#") or paragraph.startswith("!"):
                continue
            return paragraph.replace("\n", " ").strip()

    package = load_json(root / "package.json")
    description = package.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()

    return "Service introduction record generated from repository evidence and operator input."


def detect_tech_stack(root: Path) -> List[Dict[str, str]]:
    stack: List[Dict[str, str]] = []
    package = load_json(root / "package.json")
    if package:
        engines = package.get("engines") if isinstance(package.get("engines"), dict) else {}
        node_version = str(engines.get("node", "")).strip() if engines else ""
        stack.append({"technology": "Node.js", "version": node_version or "Detected from package.json", "evidence": "package.json"})

    pyproject = safe_read_text(root / "pyproject.toml")
    if pyproject:
        stack.append({"technology": "Python", "version": toml_value(pyproject, "project", "requires-python") or "Detected from pyproject.toml", "evidence": "pyproject.toml"})
    elif (root / "requirements.txt").exists():
        stack.append({"technology": "Python", "version": "Detected from requirements.txt", "evidence": "requirements.txt"})

    go_mod = safe_read_text(root / "go.mod")
    if go_mod:
        version = re.search(r"(?m)^go\s+([\d.]+)$", go_mod)
        stack.append({"technology": "Go", "version": version.group(1) if version else "Detected from go.mod", "evidence": "go.mod"})

    cargo = safe_read_text(root / "Cargo.toml")
    if cargo:
        version = re.search(r"(?m)^edition\s*=\s*[\"']([^\"']+)[\"']", cargo)
        stack.append({"technology": "Rust", "version": version.group(1) if version else "Detected from Cargo.toml", "evidence": "Cargo.toml"})

    pom = safe_read_text(root / "pom.xml")
    if pom:
        java_version = re.search(r"<maven.compiler.source>([^<]+)</maven.compiler.source>", pom)
        stack.append({"technology": "Java", "version": java_version.group(1) if java_version else "Detected from pom.xml", "evidence": "pom.xml"})
    elif (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        stack.append({"technology": "Java / Gradle", "version": "Detected from build.gradle", "evidence": "build.gradle"})

    if any(iter_files(root, ["Dockerfile", "Dockerfile.*", "docker-compose.yml", "docker-compose.yaml"])):
        stack.append({"technology": "Containers", "version": "Docker / OCI", "evidence": "Dockerfile or docker-compose"})
    if any(iter_files(root, ["*.tf"])):
        stack.append({"technology": "Terraform", "version": "Infrastructure as Code", "evidence": "*.tf"})
    if any(iter_files(root, ["cdk.json", "**/cdk.json"])):
        stack.append({"technology": "AWS CDK", "version": "Detected from cdk.json", "evidence": "cdk.json"})
    if any(iter_files(root, ["serverless.yml", "serverless.yaml"])):
        stack.append({"technology": "Serverless Framework", "version": "Detected from serverless.yml", "evidence": "serverless.yml"})

    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in stack:
        key = (item["technology"], item["evidence"])
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped or [{"technology": "Unknown", "version": "Manual review required", "evidence": "No common manifests detected"}]


def detect_runtime_environments(root: Path) -> List[Dict[str, str]]:
    envs: List[Dict[str, str]] = []
    patterns = [".env", ".env.*", "Dockerfile", "Dockerfile.*", "docker-compose.yml", "docker-compose.yaml", "serverless.yml", "serverless.yaml", "cdk.json", "*.tf"]
    for path in iter_files(root, patterns):
        name = path.name
        if name.startswith(".env"):
            envs.append({"environment": name, "type": "Environment Variables", "evidence": str(path.relative_to(root))})
        elif name.startswith("Dockerfile"):
            envs.append({"environment": "container", "type": "Docker Runtime", "evidence": str(path.relative_to(root))})
        elif name.startswith("docker-compose"):
            envs.append({"environment": "compose", "type": "Container Orchestration", "evidence": str(path.relative_to(root))})
        elif name == "cdk.json":
            envs.append({"environment": "aws-cdk", "type": "Cloud Deployment", "evidence": str(path.relative_to(root))})
        elif name.startswith("serverless"):
            envs.append({"environment": "serverless", "type": "Function Runtime", "evidence": str(path.relative_to(root))})
        elif path.suffix == ".tf":
            envs.append({"environment": "terraform", "type": "Infrastructure as Code", "evidence": str(path.relative_to(root))})
    return envs or [{"environment": "application", "type": "Undeclared", "evidence": "No runtime manifests detected"}]


def detect_apis(root: Path) -> List[Dict[str, str]]:
    apis: List[Dict[str, str]] = []
    for path in iter_files(root, ["*.yaml", "*.yml", "*.json", "*.py", "*.js", "*.ts", "*.go"]):
        text = safe_read_text(path)
        rel = str(path.relative_to(root))
        lowered = text.lower()
        rel_lower = rel.lower()
        if any(token in rel_lower for token in ["openapi", "swagger"]) or "openapi:" in lowered or "swagger:" in lowered:
            apis.append({"interface": "HTTP API", "contract": "OpenAPI / Swagger", "source": rel, "notes": "Structured API contract detected"})
        for pattern in API_ROUTE_PATTERNS:
            for match in pattern.finditer(text):
                apis.append({"interface": match.group(1).upper(), "contract": match.group(2), "source": rel, "notes": "Route definition detected"})
        if "lambda_handler" in text or "exports.handler" in text or "def handler(" in text:
            apis.append({"interface": "Function", "contract": "Lambda handler", "source": rel, "notes": "Function entry point detected"})

    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in apis:
        key = tuple(item.items())
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped[:25]


def detect_external_services(root: Path) -> List[Dict[str, str]]:
    services: List[Dict[str, str]] = []
    for path in list(iter_files(root, ["*.py", "*.js", "*.ts", "*.go", "*.java", "*.json", "*.yaml", "*.yml", "*.tf", "*.md"]))[:400]:
        text = safe_read_text(path).lower()
        for needle, service_name in SERVICE_PATTERNS.items():
            if needle in text:
                services.append({
                    "dependency": service_name,
                    "version": "Repository scan",
                    "owner": "[OWNER_NAME]",
                    "criticality": "Medium",
                    "source": str(path.relative_to(root))
                })
    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in services:
        if item["dependency"] not in seen:
            deduped.append(item)
            seen.add(item["dependency"])
    return deduped[:20]


def detect_existing_docs(root: Path) -> List[str]:
    docs: List[str] = []
    for candidate in [root / "README.md", root / "CONTRIBUTING.md", root / "CHANGELOG.md"]:
        if candidate.exists():
            docs.append(str(candidate.relative_to(root)))
    docs_dir = root / "docs"
    if docs_dir.exists():
        for path in iter_files(docs_dir, ["*.md", "*.rst", "*.adoc"]):
            docs.append(str(path.relative_to(root)))
    return docs


def detect_cicd(root: Path) -> Dict[str, Any]:
    workflows_dir = root / ".github" / "workflows"
    if workflows_dir.exists():
        workflows = [str(path.relative_to(root)) for path in workflows_dir.glob("*.y*ml")]
        if workflows:
            return {"platform": "GitHub Actions", "evidence": workflows}
    if (root / ".gitlab-ci.yml").exists():
        return {"platform": "GitLab CI", "evidence": [".gitlab-ci.yml"]}
    if (root / "Jenkinsfile").exists():
        return {"platform": "Jenkins", "evidence": ["Jenkinsfile"]}
    if (root / ".circleci" / "config.yml").exists():
        return {"platform": "CircleCI", "evidence": [".circleci/config.yml"]}
    return {"platform": "Manual / Undetected", "evidence": []}


def detect_security_config(root: Path) -> List[str]:
    findings: List[str] = []
    patterns = {
        "jwt": "JWT authentication library detected",
        "oauth": "OAuth / OpenID Connect signal detected",
        "kms": "Key management or envelope encryption detected",
        "encrypt": "Encryption-related code detected",
        "helmet": "HTTP security headers middleware detected",
        "authmiddleware": "Authentication middleware detected",
        "bcrypt": "Password hashing dependency detected",
        "csp": "Content Security Policy configuration detected"
    }
    for path in iter_files(root, ["*.py", "*.js", "*.ts", "*.go", "*.java", "*.json", "*.yaml", "*.yml"]):
        lowered = safe_read_text(path).lower()
        for needle, label in patterns.items():
            if needle in lowered and label not in findings:
                findings.append(label)
    return findings or ["Manual security control review required"]


def detect_service_tier(root: Path) -> int:
    combined = "\n".join(safe_read_text(path).lower() for path in iter_files(root, ["*.md", "*.py", "*.js", "*.ts", "*.go", "*.yaml", "*.yml", "*.json"]))
    if any(token in combined for token in ["banking", "payment", "pci", "trading", "customer funds"]):
        return 1
    if any(token in combined for token in ["test", "evaluation", "prototype", "sandbox", "demo"]):
        return 2
    return 3


def generate_sid_id(project_name: str) -> str:
    words = [re.sub(r"[^A-Za-z]", "", word).upper() for word in re.split(r"[^A-Za-z0-9]+", project_name) if word]
    initials = "".join(word[0] for word in words if word)[:3]
    prefix = (initials or re.sub(r"[^A-Za-z]", "", project_name).upper()[:3] or "GEN").ljust(3, "X")
    return f"SID-{prefix}-001"


def scan_project(root: Path) -> Dict[str, Any]:
    project_name = detect_project_name(root)
    return {
        "project_root": str(root.resolve()),
        "project_name": project_name,
        "description": detect_description(root),
        "tech_stack": detect_tech_stack(root),
        "runtime_environments": detect_runtime_environments(root),
        "apis": detect_apis(root),
        "external_services": detect_external_services(root),
        "existing_docs": detect_existing_docs(root),
        "cicd": detect_cicd(root),
        "security_config": detect_security_config(root),
        "service_tier": detect_service_tier(root),
        "sid_id": generate_sid_id(project_name)
    }


def load_context_json(path: Path) -> Dict[str, Any]:
    text = safe_read_text(path)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def load_collector_module():
    spec = importlib.util.spec_from_file_location("service_intro_collect_info", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_context(scan: Dict[str, Any], no_interactive: bool) -> Dict[str, Any]:
    module = load_collector_module()
    if module is None:
        return {}
    seed = module.load_env_defaults()
    seed["project_name"] = scan.get("project_name", seed["project_name"])
    seed["description"] = scan.get("description", seed["description"])
    seed["service_tier"] = scan.get("service_tier", seed["service_tier"])
    if no_interactive or not sys.stdin.isatty():
        return seed
    return module.collect_interactive(seed)


def merge_context(scan: Dict[str, Any], extra: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    context = dict(scan)
    for key, value in extra.items():
        if value not in (None, "", [], {}):
            context[key] = value
    if args.sid_id:
        context["sid_id"] = args.sid_id
    if args.service_tier:
        context["service_tier"] = int(args.service_tier)
    context.setdefault("sid_id", generate_sid_id(context.get("project_name", "service")))
    context.setdefault("service_tier", detect_service_tier(Path(context["project_root"])))
    context.setdefault("availability_slo", "99.9%")
    context.setdefault("rto", "4h")
    context.setdefault("rpo", "1h")
    context.setdefault("business_purpose", context.get("description", "Provide a supportable service capability."))
    context.setdefault("business_drivers", [
        "Improve operational readiness and supportability",
        "Provide measurable service targets and accountable ownership",
        "Create a governed onboarding record for change and service management"
    ])
    context.setdefault("compliance", ["none"])
    context.setdefault("owner", "[OWNER_NAME]")
    context.setdefault("l1_support", "Service Desk")
    context.setdefault("l2_support", "Platform Operations")
    context.setdefault("l3_support", "Engineering Team")
    context.setdefault("go_live_date", "TBD")
    context.setdefault("template_type", args.template)
    return context


def markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def format_tech_stack_table(stack: List[Dict[str, str]]) -> str:
    rows = [[item["technology"], item["version"], item["evidence"]] for item in stack]
    return markdown_table(["Technology", "Version / Hint", "Evidence"], rows)


def format_dependencies_table(services: List[Dict[str, str]]) -> str:
    if not services:
        services = [{"dependency": "Manual review required", "version": "Unknown", "owner": "[OWNER_NAME]", "criticality": "Medium", "source": "No dependency evidence detected"}]
    rows = [[item["dependency"], item["version"], item["owner"], item["criticality"], item["source"]] for item in services]
    return markdown_table(["Dependency", "Version", "Owner", "Criticality", "Evidence"], rows)


def format_detected_apis(apis: List[Dict[str, str]]) -> str:
    if not apis:
        apis = [{"interface": "HTTP", "contract": "/health", "source": "Manual review", "notes": "No API contracts auto-detected"}]
    rows = [[item["interface"], item["contract"], item["source"], item["notes"]] for item in apis]
    return markdown_table(["Interface", "Endpoint / Contract", "Source", "Notes"], rows)


def format_detected_services(services: List[Dict[str, str]]) -> str:
    if not services:
        return "- Manual review required to identify downstream platforms, suppliers, and managed services."
    return "\n".join(f"- **{item['dependency']}** detected in `{item['source']}`." for item in services)


def format_environments_table(envs: List[Dict[str, str]]) -> str:
    rows = [[item["environment"], item["type"], item["evidence"]] for item in envs]
    return markdown_table(["Environment / Runtime", "Type", "Evidence"], rows)


def render_template(template_path: Path, context: Dict[str, Any]) -> str:
    template = safe_read_text(template_path)
    replacements = {
        "PROJECT_NAME": str(context.get("project_name", "service-project")),
        "SID_ID": str(context.get("sid_id", "SID-GEN-001")),
        "SERVICE_TIER": str(context.get("service_tier", 2)),
        "TECH_STACK_TABLE": format_tech_stack_table(context.get("tech_stack", [])),
        "DEPENDENCIES_TABLE": format_dependencies_table(context.get("external_services", [])),
        "DETECTED_APIS": format_detected_apis(context.get("apis", [])),
        "DETECTED_SERVICES": format_detected_services(context.get("external_services", [])),
        "CI_CD_PLATFORM": str(context.get("cicd", {}).get("platform", "Manual / Undetected")),
        "ENVIRONMENTS_TABLE": format_environments_table(context.get("runtime_environments", [])),
        "TODAY_DATE": date.today().isoformat(),
        "DESCRIPTION": str(context.get("description", "Service introduction record.")),
        "OWNER": str(context.get("owner", "[OWNER_NAME]")),
        "BUSINESS_PURPOSE": str(context.get("business_purpose", context.get("description", "Provide a supportable service capability."))),
        "BUSINESS_DRIVERS_LIST": "\n".join(f"- {item}" for item in context.get("business_drivers", [])),
        "COMPLIANCE_LIST": ", ".join(context.get("compliance", ["none"])),
        "AVAILABILITY_SLO": str(context.get("availability_slo", "99.9%")),
        "RTO": str(context.get("rto", "4h")),
        "RPO": str(context.get("rpo", "1h")),
        "L1_SUPPORT": str(context.get("l1_support", "Service Desk")),
        "L2_SUPPORT": str(context.get("l2_support", "Platform Operations")),
        "L3_SUPPORT": str(context.get("l3_support", "Engineering Team")),
        "GO_LIVE_DATE": str(context.get("go_live_date", "TBD")),
        "EXISTING_DOCS": "\n".join(f"- {item}" for item in context.get("existing_docs", [])) or "- README.md\n- docs/ service documentation (if present)",
        "SECURITY_SIGNALS": "\n".join(f"- {item}" for item in context.get("security_config", [])) or "- Manual security review required"
    }
    for key, value in replacements.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def default_output_path(project_root: Path, project_name: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-") or "service"
    return project_root / "docs" / "service-introduction" / f"{slug}-sid.md"


def run_validator(output_path: Path) -> int:
    result = subprocess.run([sys.executable, str(VALIDATOR_PATH), str(output_path)], capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        print("Remediation guide:")
        print("- Populate missing governance metadata in Document Control.")
        print("- Add or complete required tables for dependencies, risks, and approvals.")
        print("- Define availability, latency, RTO, and RPO targets explicitly.")
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a repository, collect business context, and generate a Service Introduction Document.")
    parser.add_argument("--project-root", default=".", help="Project root to scan (default: current directory).")
    parser.add_argument("--output", help="Output markdown path (default: docs/service-introduction/<project-name>-sid.md).")
    parser.add_argument("--template", choices=["generic", "api-service", "ai-service", "platform-service"], default="generic", help="Template type to render.")
    parser.add_argument("--scan-only", action="store_true", help="Scan the project and print detected context as JSON.")
    parser.add_argument("--output-json", action="store_true", help="Compatibility flag for scan mode; JSON is always printed to stdout.")
    parser.add_argument("--no-interactive", action="store_true", help="Skip interactive questions and use defaults or context JSON.")
    parser.add_argument("--sid-id", help="Override the auto-generated SID ID.")
    parser.add_argument("--service-tier", choices=["1", "2", "3"], help="Override the detected service tier.")
    parser.add_argument("--context-json", help="Path to context JSON generated by collect_info.py.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.exists() or not project_root.is_dir():
        print(f"[ERROR] Project root not found: {project_root}", file=sys.stderr)
        return 1

    scan = scan_project(project_root)
    if args.scan_only:
        print(json.dumps(scan, indent=2))
        return 0

    context = load_context_json(Path(args.context_json).expanduser()) if args.context_json else {}
    if not context:
        context = collect_context(scan, args.no_interactive)
    merged = merge_context(scan, context, args)

    template_key = str(merged.get("template_type", args.template))
    template_map = {
        "generic": TEMPLATE_DIR / "service-introduction.md",
        "api-service": TEMPLATE_DIR / "api-service-sid.md",
        "ai-service": TEMPLATE_DIR / "ai-service-sid.md",
        "platform-service": TEMPLATE_DIR / "platform-service-sid.md"
    }
    template_path = template_map.get(template_key, template_map[args.template])
    rendered = render_template(template_path, merged)

    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(project_root, merged["project_name"]).resolve()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] Failed to write SID output: {exc}", file=sys.stderr)
        return 1

    print(f"Generated SID: {output_path}")
    return run_validator(output_path)


if __name__ == "__main__":
    sys.exit(main())
