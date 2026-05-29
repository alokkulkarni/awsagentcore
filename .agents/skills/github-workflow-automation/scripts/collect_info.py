#!/usr/bin/env python3
"""Interactively collect GitHub Actions workflow scaffolding choices."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from scan_repo import scan_repository

DEFAULT_ENVS = ["dev", "staging", "prod"]


def prompt(prompt_text: str, default: str = "") -> str:
    try:
        answer = input(f"{prompt_text}: ").strip()
    except EOFError:
        return default
    return answer or default


def prompt_bool(prompt_text: str, default: bool) -> bool:
    raw = prompt(prompt_text, "y" if default else "n").lower()
    if raw in {"y", "yes", "true", "1"}:
        return True
    if raw in {"n", "no", "false", "0"}:
        return False
    return default


def prompt_int(prompt_text: str, default: int, min_value: int, max_value: int) -> int:
    raw = prompt(prompt_text, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return min(max(value, min_value), max_value)


def prompt_choice(prompt_text: str, default: str, choices: Sequence[str]) -> str:
    raw = prompt(prompt_text, default).strip().lower()
    return raw if raw in choices else default


def split_csv(raw: str) -> List[str]:
    return [item.strip() for item in re.split(r"\s*,\s*", raw) if item.strip()]


def normalize_repo_target(raw: str) -> Dict[str, str]:
    if raw.startswith(("http://", "https://", "git@", "ssh://")):
        project_name = raw.rstrip("/").split("/")[-1].removesuffix(".git") or "repository"
        return {"repo_path": str(Path.cwd()), "repo_source": raw, "project_name": project_name}
    path = Path(raw).expanduser().resolve()
    return {"repo_path": str(path), "repo_source": str(path), "project_name": path.name}


def detect_default_image_name(repo_source: str, project_name: str) -> str:
    remote = ""
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_source if Path(repo_source).exists() else None,
            capture_output=True,
            text=True,
            check=False,
        )
        remote = result.stdout.strip()
    except OSError:
        remote = ""
    if remote:
        match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", remote)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    owner = os.environ.get("GITHUB_REPOSITORY", "")
    if owner:
        return owner
    return f"my-org/{project_name}"


def collect(args: argparse.Namespace) -> Dict[str, Any]:
    repo_answer = args.repo or prompt("Repository path or URL? (current directory)", os.getcwd())
    repo_meta = normalize_repo_target(repo_answer or os.getcwd())
    gha_folder = prompt("GitHub Actions folder [.github/workflows]", ".github/workflows")

    findings = scan_repository(repo_meta["repo_path"])
    print("\nDetected repository profile:")
    print(json.dumps(findings, indent=2, sort_keys=True))
    print()

    create_ci = prompt_bool("Create CI workflow? [y/n] (y)", True)
    create_cd = prompt_bool("Create CD workflow? [y/n] (y)", True)
    create_integration = prompt_bool("Create integration tests workflow? [y/n] (y)", True)
    create_regression = prompt_bool("Create regression tests workflow? [y/n] (y)", True)
    create_image_scan = prompt_bool("Create image scanning workflow? [y/n] (y)", True)

    ci_config: Dict[str, Any] = {}
    if create_ci:
        default_image = detect_default_image_name(repo_meta["repo_path"], repo_meta["project_name"])
        suggested_registry = "ghcr"
        print(f"\n  💡 Suggested Docker image name: {default_image!r}  (derived from git remote)")
        ci_config = {
            "docker_registry": prompt_choice("Docker registry? [dockerhub|ghcr|ecr|acr|custom] (ghcr)", suggested_registry, ["dockerhub", "ghcr", "ecr", "acr", "custom"]),
            "image_name": prompt(f"Docker image name? [{default_image}]", default_image),
            "coverage_threshold": prompt_int("Coverage threshold %? [80]", 80, 1, 100),
            "fail_on_critical": prompt_bool("Fail CI on CRITICAL CVEs? [y/n] (y)", True),
            "fail_on_high": prompt_bool("Fail CI on HIGH CVEs? [y/n] (y)", True),
            "trigger_branches": split_csv(prompt("Branch pattern to trigger CI? [main,develop,feature/**,fix/**]", "main,develop,feature/**,fix/**")),
            "generate_sbom": True,
        }

    cd_config: Dict[str, Any] = {"environments": [], "generate_cbom": True}
    if create_cd:
        environment_count = prompt_int("How many environments? [1-5] (3)", 3, 1, 5)
        for index in range(environment_count):
            env_default = DEFAULT_ENVS[index] if index < len(DEFAULT_ENVS) else f"env{index + 1}"
            env_name = prompt(f"Name for environment {index + 1} of {environment_count}? [{env_default}]", env_default)
            default_target = "ecs" if env_name.lower() in ("dev", "staging") else "kubernetes"
            target = prompt_choice(
                f"Deployment target for '{env_name}'? [ecs|eks|lambda|aca|cloudrun|kubernetes] [{default_target}]",
                default_target,
                ["ecs", "eks", "lambda", "aca", "cloudrun", "kubernetes"],
            )
            default_auto = env_name.lower() != "prod"
            auto_deploy = prompt_bool(f"Auto-deploy '{env_name}' on push? [y/n, default: {'y' if default_auto else 'n'}]", default_auto)
            default_approval = env_name.lower() == "prod"
            approval_required = prompt_bool(f"Require manual approval gate for '{env_name}'? [y/n, default: {'y' if default_approval else 'n'}]", default_approval)
            smoke_url = prompt(f"Health-check / smoke test URL for '{env_name}'? [optional, press Enter to skip]", "")
            cd_config["environments"].append(
                {
                    "name": env_name,
                    "target": target,
                    "auto_deploy": auto_deploy,
                    "approval_required": approval_required,
                    "smoke_test_url": smoke_url,
                    "generate_cbom": True,
                }
            )
        cd_config["manual_prod_approval"] = any(e.get("approval_required") for e in cd_config["environments"])

    regression_config: Dict[str, Any] = {}
    if create_regression:
        staging_envs = [e["name"] for e in cd_config.get("environments", []) if e["name"].lower() in ("staging", "stage")]
        default_trigger_env = staging_envs[0] if staging_envs else "staging"
        regression_config = {
            "base_url": prompt(f"Base URL for regression tests? [e.g. https://staging.myapp.com]", "https://staging.example.com"),
            "trigger_env": prompt(f"Which environment triggers regression tests automatically? [{default_trigger_env}]", default_trigger_env),
            "test_command": prompt("Regression test command? [e.g. npm run test:regression | pytest tests/regression/]", ""),
        }

    image_scan_config: Dict[str, Any] = {}
    if create_image_scan:
        image_scan_config = {
            "scan_on": prompt_choice("Scan on: [push|schedule|both] (both)", "both", ["push", "schedule", "both"]),
            "schedule": prompt("Scan schedule (cron)? [0 6 * * *]", "0 6 * * *"),
            "email_to": prompt("Email scan reports to? [optional, press Enter to skip]", ""),
            "email_provider": prompt_choice("Email provider? [sendgrid|ses|smtp] (ses)", "ses", ["sendgrid", "ses", "smtp"]),
            "fail_on_critical": prompt_bool("Fail on CRITICAL CVEs in scan? [y/n] (y)", True),
            "compare_n1": prompt_bool("Compare with n-1 report and block on regressions? [y/n] (y)", True),
        }

    reports_config = {
        "folder": prompt("Save reports to repo folder? [.github/reports]", ".github/reports"),
        "retention_days": prompt_int("Report retention days? [90]", 90, 1, 365),
        "coverage_badge": prompt_bool("Generate live coverage badge in README? [y/n] (y)", True),
    }

    return {
        "project_name": repo_meta["project_name"],
        "repo_path": repo_meta["repo_path"],
        "repo_source": repo_meta["repo_source"],
        "github_actions_folder": gha_folder,
        "language": findings.get("language", "generic"),
        "framework": findings.get("framework", "generic"),
        "package_manager": findings.get("package_manager", "unknown"),
        "test_runner": findings.get("test_runner", "manual"),
        "node_version": findings.get("node_version", ""),
        "python_version": findings.get("python_version", ""),
        "has_dockerfile": findings.get("has_dockerfile", False),
        "has_docker_compose": findings.get("has_docker_compose", False),
        "docker_base_image": findings.get("docker_base_image", ""),
        "workflows": {
            "ci": create_ci,
            "cd": create_cd,
            "integration_tests": create_integration,
            "regression_tests": create_regression,
            "image_scan": create_image_scan,
        },
        "ci": ci_config,
        "cd": cd_config,
        "regression": regression_config,
        "image_scan": image_scan_config,
        "reports": reports_config,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect GitHub Actions workflow configuration interactively.")
    parser.add_argument("--repo", help="Repository path or URL. Defaults to the current directory.")
    parser.add_argument("--output-json", default="github-workflow-config.json", help="Where to save the collected configuration JSON.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = collect(args)
    output_path = Path(args.output_json).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Saved configuration to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
