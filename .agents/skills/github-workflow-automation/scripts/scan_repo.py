#!/usr/bin/env python3
"""Detect repository language, framework, package manager, test runner, and container hints."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "bin", "obj", "vendor", "coverage", "__pycache__"}
FRAMEWORK_HINTS = {
    "node": [
        ("next", "nextjs"),
        ("react", "react"),
        ("express", "express"),
        ("nestjs", "nestjs"),
        ("@nestjs/core", "nestjs"),
        ("koa", "koa"),
        ("fastify", "fastify"),
        ("nuxt", "nuxt"),
    ],
    "python": [("django", "django"), ("fastapi", "fastapi"), ("flask", "flask"), ("falcon", "falcon")],
    "java": [("spring-boot", "spring"), ("springframework.boot", "spring"), ("quarkus", "quarkus"), ("micronaut", "micronaut")],
    "go": [("gin-gonic/gin", "gin"), ("labstack/echo", "echo"), ("gofiber/fiber", "fiber")],
    "rust": [("actix-web", "actix"), ("axum", "axum"), ("rocket", "rocket")],
    "dotnet": [("Microsoft.AspNetCore", "aspnet"), ("Azure.Functions", "azure-functions")],
}
TEST_RUNNER_HINTS = {
    "node": [("vitest", "vitest"), ("jest", "jest"), ("mocha", "mocha"), ("playwright", "playwright")],
    "python": [("pytest", "pytest"), ("nose", "nose"), ("unittest", "unittest")],
    "java": [("surefire", "junit"), ("junit", "junit"), ("testng", "testng")],
    "go": [("testing", "go test")],
    "rust": [("cargo test", "cargo test")],
    "dotnet": [("xunit", "xunit"), ("nunit", "nunit"), ("mstest", "mstest")],
}


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(safe_read_text(path) or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def iter_files(root: Path, patterns: Iterable[str]) -> Iterable[Path]:
    lowered_patterns = list(patterns)
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and any(path.match(pattern) for pattern in lowered_patterns):
            yield path


def detect_node(root: Path) -> Tuple[bool, Dict[str, Any]]:
    package_json = load_json(root / "package.json")
    if not package_json:
        return False, {}
    deps: Dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = package_json.get(section)
        if isinstance(values, dict):
            deps.update({str(key): str(value) for key, value in values.items()})
    framework = next((label for token, label in FRAMEWORK_HINTS["node"] if token in deps), "node")
    runner = "npm test"
    scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
    for token, label in TEST_RUNNER_HINTS["node"]:
        if token in deps or token in json.dumps(scripts):
            runner = label
            break
    if (root / "pnpm-lock.yaml").exists():
        package_manager = "pnpm"
    elif (root / "yarn.lock").exists():
        package_manager = "yarn"
    else:
        package_manager = "npm"
    node_version = ""
    engines = package_json.get("engines")
    if isinstance(engines, dict) and isinstance(engines.get("node"), str):
        node_version = engines["node"]
    elif (root / ".nvmrc").exists():
        node_version = safe_read_text(root / ".nvmrc").strip()
    return True, {
        "language": "node",
        "framework": framework,
        "package_manager": package_manager,
        "test_runner": runner,
        "node_version": node_version,
        "python_version": "",
    }


def detect_python(root: Path) -> Tuple[bool, Dict[str, Any]]:
    files = [root / "requirements.txt", root / "pyproject.toml", root / "setup.py"]
    if not any(path.exists() for path in files):
        return False, {}
    pyproject = safe_read_text(root / "pyproject.toml")
    requirements = safe_read_text(root / "requirements.txt")
    setup_py = safe_read_text(root / "setup.py")
    combined = "\n".join([pyproject, requirements, setup_py]).lower()
    framework = next((label for token, label in FRAMEWORK_HINTS["python"] if token in combined), "python")
    runner = next((label for token, label in TEST_RUNNER_HINTS["python"] if token in combined), "pytest")
    if "[tool.poetry]" in pyproject.lower():
        package_manager = "poetry"
    else:
        package_manager = "pip"
    python_version = ""
    match = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', pyproject)
    if match:
        python_version = match.group(1)
    return True, {
        "language": "python",
        "framework": framework,
        "package_manager": package_manager,
        "test_runner": runner,
        "node_version": "",
        "python_version": python_version,
    }


def detect_java(root: Path) -> Tuple[bool, Dict[str, Any]]:
    pom = safe_read_text(root / "pom.xml")
    gradle = safe_read_text(root / "build.gradle") or safe_read_text(root / "build.gradle.kts")
    if not pom and not gradle:
        return False, {}
    combined = f"{pom}\n{gradle}".lower()
    framework = next((label for token, label in FRAMEWORK_HINTS["java"] if token in combined), "java")
    return True, {
        "language": "java",
        "framework": framework,
        "package_manager": "maven" if pom else "gradle",
        "test_runner": next((label for token, label in TEST_RUNNER_HINTS["java"] if token in combined), "junit"),
        "node_version": "",
        "python_version": "",
    }


def detect_go(root: Path) -> Tuple[bool, Dict[str, Any]]:
    go_mod = safe_read_text(root / "go.mod")
    if not go_mod:
        return False, {}
    framework = next((label for token, label in FRAMEWORK_HINTS["go"] if token in go_mod), "go")
    return True, {
        "language": "go",
        "framework": framework,
        "package_manager": "go mod",
        "test_runner": "go test",
        "node_version": "",
        "python_version": "",
    }


def detect_rust(root: Path) -> Tuple[bool, Dict[str, Any]]:
    cargo = safe_read_text(root / "Cargo.toml")
    if not cargo:
        return False, {}
    framework = next((label for token, label in FRAMEWORK_HINTS["rust"] if token in cargo.lower()), "rust")
    return True, {
        "language": "rust",
        "framework": framework,
        "package_manager": "cargo",
        "test_runner": "cargo test",
        "node_version": "",
        "python_version": "",
    }


def detect_dotnet(root: Path) -> Tuple[bool, Dict[str, Any]]:
    csproj_files = list(iter_files(root, ["*.csproj"]))
    if not csproj_files:
        return False, {}
    combined = "\n".join(safe_read_text(path) for path in csproj_files)
    framework = next((label for token, label in FRAMEWORK_HINTS["dotnet"] if token.lower() in combined.lower()), "dotnet")
    return True, {
        "language": "dotnet",
        "framework": framework,
        "package_manager": "dotnet",
        "test_runner": next((label for token, label in TEST_RUNNER_HINTS["dotnet"] if token in combined.lower()), "dotnet test"),
        "node_version": "",
        "python_version": "",
    }


def detect_container_hints(root: Path) -> Dict[str, Any]:
    dockerfiles = list(iter_files(root, ["Dockerfile", "Dockerfile.*", "**/Dockerfile", "**/Dockerfile.*"]))
    compose_files = list(iter_files(root, ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", "**/docker-compose.yml", "**/docker-compose.yaml"]))
    docker_base_image = ""
    if dockerfiles:
        match = re.search(r"(?im)^FROM\s+([^\s]+)", safe_read_text(dockerfiles[0]))
        if match:
            docker_base_image = match.group(1).strip()
    return {
        "has_dockerfile": bool(dockerfiles),
        "has_docker_compose": bool(compose_files),
        "docker_base_image": docker_base_image,
    }


def scan_repository(repo_path: str | Path) -> Dict[str, Any]:
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return {
            "language": "generic",
            "framework": "generic",
            "package_manager": "unknown",
            "test_runner": "manual",
            "has_dockerfile": False,
            "has_docker_compose": False,
            "node_version": "",
            "python_version": "",
            "docker_base_image": "",
        }

    detectors = [detect_node, detect_python, detect_java, detect_go, detect_rust, detect_dotnet]
    detected: Dict[str, Any] = {}
    for detector in detectors:
        found, payload = detector(root)
        if found:
            detected = payload
            break
    if not detected:
        detected = {
            "language": "generic",
            "framework": "generic",
            "package_manager": "unknown",
            "test_runner": "manual",
            "node_version": "",
            "python_version": "",
        }
    detected.update(detect_container_hints(root))
    return detected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect repository language, framework, package manager, test runner, and Docker hints.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository path to scan.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON result.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = scan_repository(args.repo)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=bool(args.pretty)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
