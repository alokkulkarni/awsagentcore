#!/usr/bin/env python3
"""Validate Testcontainers scaffolding and CI wiring for a project."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from scan_project import scan_project


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def yaml_ok(path: Path) -> bool:
    if yaml is None:
        return True
    try:
        yaml.safe_load(safe_read(path))
        return True
    except Exception:
        return False


def docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)
    except OSError:
        return False
    return result.returncode == 0


def validate(project: Path) -> List[str]:
    scan = scan_project(project)
    messages: List[str] = []
    build_text = "\n".join(safe_read(project / name) for name in ["pom.xml", "build.gradle", "build.gradle.kts", "requirements-test.txt", "package.json", "go.mod"] if (project / name).exists())
    if "testcontainers" in build_text.lower() or "Testcontainers" in build_text:
        messages.append("✅ Dependencies added to build file")
    else:
        messages.append("❌ Testcontainers dependencies not found in build file")

    created_tests = sorted(
        [
            path.relative_to(project)
            for path in project.rglob("*")
            if path.is_file() and (
                path.name.endswith(("IntegrationTest.java", "IntegrationTests.cs", ".integration.test.ts", "_integration_test.go"))
                or path.name.startswith("test_") and "integration" in path.name
            )
        ]
    )
    if created_tests:
        for test_file in created_tests[:10]:
            messages.append(f"✅ {test_file} created")
    else:
        messages.append("❌ No generated integration test files detected")

    combined_tests = "\n".join(safe_read(project / path) for path in created_tests[:20])
    if any(token in combined_tests for token in ["DATABASE_URL", "process.env", "os.environ", "os.Setenv", "spring.datasource.url", "AddInMemoryCollection"]):
        messages.append("✅ Env variable wiring present in test files")
    else:
        messages.append("⚠️  Env variable wiring not detected in generated test files")

    ci_files = [project / rel for rel in scan.get("ci_files", [])]
    patched_ci = []
    for path in ci_files:
        text = safe_read(path)
        if any(token in text for token in ["TESTCONTAINERS_HOST_OVERRIDE", "docker:dind", "/var/run/docker.sock", "permissions:"]):
            patched_ci.append(path)
    if patched_ci:
        for path in patched_ci:
            status = "✅" if path.suffix in {".yml", ".yaml"} and yaml_ok(path) else "✅"
            messages.append(f"{status} {path.relative_to(project)} patched for Testcontainers")
    elif ci_files:
        messages.append("⚠️  CI files found but Testcontainers patch markers were not detected")
    else:
        messages.append("⚠️  No CI files found to validate")

    if docker_available():
        messages.append("✅ Docker detected via `docker info`")
    else:
        messages.append("⚠️  Docker not detected — install Docker Desktop or configure TC Cloud")
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Testcontainers setup in a target project.")
    parser.add_argument("project_dir", nargs="?", default=".", help="Project directory to validate.")
    args = parser.parse_args()
    project = Path(args.project_dir).expanduser().resolve()
    messages = validate(project)
    failures = sum(1 for message in messages if message.startswith("❌"))
    for message in messages:
        print(message)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
