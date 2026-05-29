#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Scan a project and generate a deployment runbook markdown file."""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = SKILL_DIR / "templates"
IGNORED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".next",
    ".turbo",
}
KNOWN_COMMAND_PREFIXES = (
    "aws ",
    "sam ",
    "cdk ",
    "terraform ",
    "kubectl ",
    "helm ",
    "docker ",
    "docker-compose ",
    "make ",
    "npm ",
    "pnpm ",
    "yarn ",
    "poetry ",
    "pytest ",
    "python ",
    "uv ",
    "serverless ",
    "sls ",
    "ecs-cli ",
    "./",
)
MARKERS = {
    "PRECHECK_COMMAND": "precheck_commands",
    "BUILD_COMMAND": "build_commands",
    "ARTIFACT_COMMAND": "artifact_commands",
    "CHANGE_SET_COMMAND": "change_set_commands",
    "DEPLOY_COMMAND": "deploy_commands",
    "MONITOR_COMMAND": "monitor_commands",
    "SMOKE_TEST_COMMAND": "smoke_test_commands",
    "ROLLBACK_COMMAND": "rollback_commands",
}
TEMPLATE_DESCRIPTIONS = {
    "deployment-runbook.md": "Full deployment runbook with change, verify, troubleshoot, and rollback sections.",
    "rollback-runbook.md": "Focused rollback procedure with evidence capture, recovery, and post-checks.",
    "incident-response-runbook.md": "Incident response guide with severity, comms, mitigation, and resolution steps.",
    "troubleshooting-runbook.md": "Symptom-driven troubleshooting guide for cloud production issues.",
}


def log(level: str, message: str) -> None:
    print(f"[{level}] {message}")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def iter_files(project_dir: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [name for name in dirs if name not in IGNORED_DIRS and not name.startswith(".")]
        current = Path(root)
        for name in files:
            if name.startswith("."):
                continue
            path = current / name
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            yield path


def normalize_project_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9-]+", "-", name.strip()).strip("-")
    return cleaned or "application"


def collect_region(text: str, counter: Counter) -> None:
    patterns = [
        r"(?:AWS_REGION|AWS_DEFAULT_REGION)\s*[:=]\s*[\"']?([a-z]{2}-[a-z]+-\d)[\"']?",
        r"--region\s+([a-z]{2}-[a-z]+-\d)",
        r"region:\s*([a-z]{2}-[a-z]+-\d)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            counter[match] += 1


def collect_stack_name(text: str, counter: Counter) -> None:
    patterns = [
        r"--stack-name\s+[\"']?([A-Za-z0-9_.-]+)[\"']?",
        r"\bStackName\b\s*[:=]\s*[\"']?([A-Za-z0-9_.-]+)[\"']?",
        r"\bSTACK_NAME\b\s*[:=]\s*[\"']?([A-Za-z0-9_.-]+)[\"']?",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text):
            counter[match] += 1


def extract_shell_functions(text: str) -> List[str]:
    return re.findall(r"^(?:function\s+)?([A-Za-z_][A-Za-z0-9_-]*)\s*(?:\(\))?\s*\{", text, flags=re.MULTILINE)


def extract_command_lines(text: str) -> List[str]:
    commands: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line or line.startswith("#"):
            continue
        if line.endswith("{") or line in {"fi", "then", "else", "do", "done"}:
            continue
        if any(line.startswith(prefix) for prefix in KNOWN_COMMAND_PREFIXES):
            commands.append(line)
            continue
        if line.startswith(("bash ", "sh ")) and ("deploy" in lowered or "rollback" in lowered):
            commands.append(line)
    deduped: List[str] = []
    seen = set()
    for command in commands:
        if command not in seen:
            seen.add(command)
            deduped.append(command)
    return deduped


def extract_make_targets(text: str) -> List[str]:
    targets: List[str] = []
    for raw_line in text.splitlines():
        if raw_line.startswith("\t"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+):(?:\s|$)", raw_line)
        if not match:
            continue
        target = match.group(1)
        if target.startswith("."):
            continue
        targets.append(target)
    return sorted(dict.fromkeys(targets))


def extract_compose_services(text: str) -> List[str]:
    services: List[str] = []
    in_services = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0 and stripped == "services:":
            in_services = True
            continue
        if indent == 0 and in_services:
            break
        if in_services:
            match = re.match(r"^\s{2,}([A-Za-z0-9_.-]+):\s*$", line)
            if match:
                services.append(match.group(1))
    return services


def is_cloudformation_template(path: Path, text: str) -> bool:
    if "AWSTemplateFormatVersion" in text or "Transform: AWS::Serverless-2016-10-31" in text:
        return True
    if path.suffix.lower() in {".yaml", ".yml", ".json"} and "Resources" in text and "AWS::" in text:
        return True
    return False


def choose_commands(commands: Sequence[str], keywords: Sequence[str], limit: int = 4) -> List[str]:
    selected: List[str] = []
    for command in commands:
        lowered = command.lower()
        if any(keyword in lowered for keyword in keywords) and command not in selected:
            selected.append(command)
        if len(selected) >= limit:
            break
    return selected


def synthesize_from_targets(targets: Sequence[str], preferred: Sequence[str]) -> List[str]:
    commands: List[str] = []
    for item in preferred:
        if item in targets:
            commands.append(f"make {item}")
    return commands


def build_command_buckets(raw_commands: Sequence[str], make_targets: Sequence[str], stack_name: str) -> Dict[str, List[str]]:
    precheck = choose_commands(raw_commands, ["lint", "test", "validate", "check", "plan", "diff"])
    build = choose_commands(raw_commands, ["build", "compile", "package", "synth"])
    artifact = choose_commands(raw_commands, ["docker push", "ecr", "publish", "aws s3 cp", "push "])
    change_set = choose_commands(raw_commands, ["change-set", "no-execute-changeset", "cloudformation deploy", "sam deploy"])
    deploy = choose_commands(raw_commands, [" deploy", "apply", "update-service", "rollout", "release"])
    monitor = choose_commands(raw_commands, ["wait", "describe-services", "describe-stacks", "rollout status", "get-deployment"])
    smoke = choose_commands(raw_commands, ["curl", "health", "ready", "smoke"])
    rollback = choose_commands(raw_commands, ["rollback", "undo", "previous", "redeploy"])

    if not precheck:
        precheck = synthesize_from_targets(make_targets, ["lint", "test", "validate", "check"])
    if not build:
        build = synthesize_from_targets(make_targets, ["build", "package", "compile"])
    if not deploy:
        deploy = synthesize_from_targets(make_targets, ["deploy", "release", "apply"])

    if not precheck:
        precheck = [
            "printf 'No project-specific precheck command detected; replace with the validated pre-deployment test command.\\n'",
            "true",
        ]
    if not build:
        build = [
            "printf 'No build command detected; replace with the project build artifact command.\\n'",
            "true",
        ]
    if not artifact:
        artifact = [
            "printf 'No publish command detected; replace with the artifact upload or registry push command.\\n'",
            "true",
        ]
    if not change_set:
        change_set = [
            f"printf 'No change-set command detected; review planned changes for stack {stack_name} before execution.\\n'",
            "true",
        ]
    if not deploy:
        deploy = [
            "printf 'No deploy command detected; replace with the project deployment command.\\n'",
            "true",
        ]
    if not monitor:
        monitor = [
            "printf 'No rollout monitor command detected; replace with the scheduler or stack verification command.\\n'",
            "true",
        ]
    if not smoke:
        smoke = [
            "printf 'No smoke-test command detected; replace with the production verification command.\\n'",
            "true",
        ]
    if not rollback:
        rollback = [
            "printf 'No rollback command detected; replace with the last-known-good restore command.\\n'",
            "true",
        ]

    return {
        "precheck_commands": precheck,
        "build_commands": build,
        "artifact_commands": artifact,
        "change_set_commands": change_set,
        "deploy_commands": deploy,
        "monitor_commands": monitor,
        "smoke_test_commands": smoke,
        "rollback_commands": rollback,
    }


def scan_project(project_dir: Path) -> Dict[str, object]:
    if not project_dir.exists() or not project_dir.is_dir():
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    deploy_scripts: List[Dict[str, object]] = []
    make_targets: List[str] = []
    compose_services: List[str] = []
    cloudformation_templates: List[str] = []
    raw_commands: List[str] = []
    region_counter: Counter = Counter()
    stack_counter: Counter = Counter()

    for path in iter_files(project_dir):
        text = read_text(path)
        collect_region(text, region_counter)
        collect_stack_name(text, stack_counter)
        relative = path.relative_to(project_dir).as_posix()
        lower_name = path.name.lower()

        if path.suffix.lower() == ".sh" and "deploy" in lower_name:
            commands = extract_command_lines(text)
            deploy_scripts.append(
                {
                    "path": relative,
                    "functions": extract_shell_functions(text),
                    "commands": commands,
                }
            )
            raw_commands.extend(commands)
        elif lower_name in {"makefile", "gnumakefile"}:
            make_targets.extend(extract_make_targets(text))
        elif lower_name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            compose_services.extend(extract_compose_services(text))
        elif path.suffix.lower() in {".yaml", ".yml", ".json"} and is_cloudformation_template(path, text):
            cloudformation_templates.append(relative)

    make_targets = sorted(dict.fromkeys(make_targets))
    project_name = normalize_project_name(project_dir.name)
    aws_region = region_counter.most_common(1)[0][0] if region_counter else "us-east-1"
    stack_name = stack_counter.most_common(1)[0][0] if stack_counter else f"{project_name}-prod"
    command_buckets = build_command_buckets(raw_commands, make_targets, stack_name)

    return {
        "project_name": project_name,
        "aws_region": aws_region,
        "stack_name": stack_name,
        "deploy_scripts": deploy_scripts,
        "make_targets": make_targets,
        "docker_compose_services": sorted(dict.fromkeys(compose_services)),
        "cloudformation_templates": sorted(dict.fromkeys(cloudformation_templates)),
        "detected_commands": raw_commands,
        "command_buckets": command_buckets,
    }


def replace_marker_blocks(template: str, command_buckets: Dict[str, List[str]]) -> str:
    rendered = template
    for marker, bucket_name in MARKERS.items():
        commands = command_buckets.get(bucket_name, [])
        replacement = "\n".join(commands).strip()
        if not replacement:
            continue
        pattern = re.compile(rf"<!-- {marker}_START -->.*?<!-- {marker}_END -->", re.DOTALL)
        rendered = pattern.sub(replacement, rendered)
    return rendered


def generate_runbook(project_dir: Path, output_path: Path) -> int:
    scan = scan_project(project_dir)
    template_path = TEMPLATES_DIR / "deployment-runbook.md"
    template = template_path.read_text(encoding="utf-8")
    rendered = replace_marker_blocks(template, scan["command_buckets"])

    for source, target in {
        "[PROJECT_NAME]": str(scan["project_name"]),
        "[STACK_NAME]": str(scan["stack_name"]),
        "[AWS_REGION]": str(scan["aws_region"]),
        "[DATE]": date.today().isoformat(),
    }.items():
        rendered = rendered.replace(source, target)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    log("INFO", f"Runbook written to {output_path}")
    return 0


def print_scan(scan: Dict[str, object]) -> None:
    log("INFO", f"Project name: {scan['project_name']}")
    log("INFO", f"Detected AWS region: {scan['aws_region']}")
    log("INFO", f"Detected stack name: {scan['stack_name']}")
    log("INFO", f"Deploy scripts found: {len(scan['deploy_scripts'])}")
    log("INFO", f"Make targets found: {len(scan['make_targets'])}")
    log("INFO", f"Compose services found: {len(scan['docker_compose_services'])}")
    log("INFO", f"CloudFormation templates found: {len(scan['cloudformation_templates'])}")
    print(json.dumps(scan, indent=2))


def list_templates() -> int:
    for name in sorted(TEMPLATE_DESCRIPTIONS):
        print(f"{name}: {TEMPLATE_DESCRIPTIONS[name]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scan a project and generate a deployment runbook.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scan", metavar="DIR", help="Scan a project directory for deployment signals.")
    group.add_argument("--generate", metavar="DIR", help="Generate a runbook from a project directory.")
    group.add_argument("--list-templates", action="store_true", help="List available templates.")
    parser.add_argument("--output", help="Output markdown path for --generate.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.list_templates:
            return list_templates()
        if args.scan:
            scan = scan_project(Path(args.scan).resolve())
            print_scan(scan)
            return 0
        if args.generate:
            if not args.output:
                log("ERROR", "--output is required when using --generate")
                return 1
            output_path = Path(args.output).resolve()
            generate_rc = generate_runbook(Path(args.generate).resolve(), output_path)
            if generate_rc != 0:
                return generate_rc
            validator = Path(__file__).with_name("validate_runbook.py")
            validation = subprocess.run([sys.executable, str(validator), str(output_path)], check=False, capture_output=True, text=True)
            if validation.stdout:
                print(validation.stdout.rstrip())
            if validation.stderr:
                print(validation.stderr.rstrip(), file=sys.stderr)
            return validation.returncode
    except FileNotFoundError as exc:
        log("ERROR", str(exc))
        return 1
    except OSError as exc:
        log("ERROR", f"I/O failure: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover
        log("ERROR", f"Unexpected failure: {exc}")
        return 1

    log("ERROR", "No action selected")
    return 1


if __name__ == "__main__":
    sys.exit(main())
