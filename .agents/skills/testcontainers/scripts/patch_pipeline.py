#!/usr/bin/env python3
"""Patch CI/CD pipelines so Testcontainers can access Docker correctly."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def write_if_changed(path: Path, content: str) -> bool:
    original = safe_read(path)
    if original == content:
        return False
    path.write_text(content, encoding="utf-8")
    return True


def patch_github_actions_file(path: Path) -> bool:
    text = safe_read(path)
    updated = text
    if "permissions:" not in updated:
        if re.search(r"(?m)^on:\s*", updated):
            updated = re.sub(r"(?m)^on:\s*", "permissions:\n  contents: read\non:\n", updated, count=1)
        else:
            updated = "permissions:\n  contents: read\n" + updated
    updated = re.sub(r"(?m)^(\s*runs-on:)\s*.*$", r"\1 ubuntu-latest", updated)
    if "self-hosted" in text and "TESTCONTAINERS_HOST_OVERRIDE" not in updated:
        if re.search(r"(?m)^env:\s*$", updated):
            updated = re.sub(r"(?m)^env:\s*$", "env:\n  TESTCONTAINERS_HOST_OVERRIDE: localhost", updated, count=1)
        else:
            updated = "env:\n  TESTCONTAINERS_HOST_OVERRIDE: localhost\n" + updated
    return write_if_changed(path, updated)


def patch_gitlab(path: Path) -> bool:
    text = safe_read(path)
    updated = text
    if "docker:dind" not in updated:
        updated = "services:\n  - docker:dind\nvariables:\n  DOCKER_HOST: tcp://docker:2375\n  DOCKER_TLS_CERTDIR: \"\"\n  TESTCONTAINERS_HOST_OVERRIDE: docker\n\n" + updated
    return write_if_changed(path, updated)


JENKINS_AGENT = """agent {
    docker {
        image 'maven:3.9-eclipse-temurin-21'
        args '-v /var/run/docker.sock:/var/run/docker.sock'
    }
}
"""


def patch_jenkins(path: Path) -> bool:
    text = safe_read(path)
    updated = text
    if "docker.sock" not in updated:
        if "agent any" in updated:
            updated = updated.replace("agent any", JENKINS_AGENT, 1)
        elif "pipeline {" in updated:
            updated = updated.replace("pipeline {", "pipeline {\n" + JENKINS_AGENT, 1)
        else:
            updated = JENKINS_AGENT + "\n" + updated
    return write_if_changed(path, updated)


def patch_project_pipelines(project_path: Path, provider: str) -> List[str]:
    patched: List[str] = []
    provider = provider or "github-actions"
    if provider == "github-actions":
        for workflow in sorted((project_path / ".github" / "workflows").glob("*.y*ml")):
            if patch_github_actions_file(workflow):
                patched.append(str(workflow.relative_to(project_path)))
    elif provider == "gitlab-ci":
        path = project_path / ".gitlab-ci.yml"
        if path.exists() and patch_gitlab(path):
            patched.append(path.name)
    elif provider == "jenkins":
        path = project_path / "Jenkinsfile"
        if path.exists() and patch_jenkins(path):
            patched.append(path.name)
    else:
        guidance = project_path / "testcontainers-ci-instructions.txt"
        guidance.write_text(
            "Mount /var/run/docker.sock or provide DinD for Testcontainers. Set TESTCONTAINERS_HOST_OVERRIDE appropriately for your CI runner.\n",
            encoding="utf-8",
        )
        patched.append(guidance.name)
    return patched


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch CI pipeline files for Testcontainers runtime requirements.")
    parser.add_argument("--project", default=".", help="Project root.")
    parser.add_argument("--provider", default="github-actions", help="CI provider name.")
    parser.add_argument("--output-json", help="Optional JSON output file.")
    args = parser.parse_args()
    project = Path(args.project).expanduser().resolve()
    patched = patch_project_pipelines(project, args.provider)
    payload: Dict[str, List[str]] = {"patched_files": patched}
    if args.output_json:
        Path(args.output_json).expanduser().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
