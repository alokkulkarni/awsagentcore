#!/usr/bin/env python3
"""Scan a project to detect language, framework, test setup, dependencies, env files, and CI signals."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from xml.etree import ElementTree as ET

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

SERVICE_PATTERNS: Dict[str, List[str]] = {
    "postgresql": ["postgres", "pgjdbc", "psycopg", "asyncpg", "sqlalchemy", "npgsql"],
    "mysql": ["mysql", "pymysql", "mysqlclient", "mysql2", "mysql.connector"],
    "mariadb": ["mariadb"],
    "mssql": ["sqlserver", "mssql", "microsoft.data.sqlclient"],
    "mongodb": ["mongo", "mongodb", "pymongo", "mongoose"],
    "redis": ["redis", "lettuce", "ioredis"],
    "kafka": ["kafka", "spring-kafka", "confluent", "kafkajs", "aiokafka", "sarama"],
    "rabbitmq": ["rabbitmq", "amqp", "pika", "mass transit"],
    "localstack": ["localstack"],
    "elasticsearch": ["elasticsearch", "opensearch"],
    "dynamodb": ["dynamodb", "aws-sdk-dynamodb", "boto3"],
    "keycloak": ["keycloak"],
}

ENV_SERVICE_MAP: Dict[str, str] = {
    "DATABASE_URL": "postgresql",
    "POSTGRES_URL": "postgresql",
    "PG_URL": "postgresql",
    "MYSQL_URL": "mysql",
    "MYSQL_DATABASE": "mysql",
    "MYSQL_HOST": "mysql",
    "MONGODB_URI": "mongodb",
    "MONGO_URL": "mongodb",
    "REDIS_URL": "redis",
    "REDIS_HOST": "redis",
    "KAFKA_BOOTSTRAP_SERVERS": "kafka",
    "KAFKA_BROKERS": "kafka",
    "RABBITMQ_URL": "rabbitmq",
    "AMQP_URL": "rabbitmq",
    "SPRING_RABBITMQ_HOST": "rabbitmq",
    "AWS_ENDPOINT_URL": "localstack",
    "LOCALSTACK_HOST": "localstack",
    "ELASTICSEARCH_URL": "elasticsearch",
    "ES_URL": "elasticsearch",
    "spring.datasource.url": "postgresql",
    "spring.data.mongodb.uri": "mongodb",
    "spring.redis.url": "redis",
    "spring.kafka.bootstrap-servers": "kafka",
    "spring.rabbitmq.host": "rabbitmq",
    "cloud.aws.endpoint.uri": "localstack",
}

FRAMEWORK_PATTERNS: Dict[str, List[str]] = {
    "spring-boot": ["spring-boot", "spring-web", "spring-boot-starter"],
    "django": ["django"],
    "fastapi": ["fastapi"],
    "flask": ["flask"],
    "express": ["express"],
    "nextjs": ["next"],
    "nestjs": ["@nestjs/core"],
    "gin": ["github.com/gin-gonic/gin"],
    "fiber": ["github.com/gofiber/fiber"],
    "aspnetcore": ["microsoft.aspnetcore"],
}

TEST_PATTERNS: Dict[str, List[str]] = {
    "junit5": ["junit-jupiter", "org.junit.jupiter"],
    "pytest": ["pytest"],
    "jest": ["jest", "ts-jest"],
    "vitest": ["vitest"],
    "go test": ["testing"],
    "xunit": ["xunit"],
}

ENV_FILES = [
    ".env",
    ".env.test",
    ".env.local",
    "application.properties",
    "application-test.properties",
    "application.yml",
    "application-test.yml",
    "config.py",
    "settings.py",
    "database.yml",
    "appsettings.json",
    "appsettings.Test.json",
    "config/default.json",
    "config/test.json",
]


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def flatten_dict(data: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            result.update(flatten_dict(value, full_key))
        else:
            result[full_key] = value
    return result


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_pom(path: Path) -> List[str]:
    text = safe_read(path)
    results: List[str] = []
    if not text:
        return results
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return re.findall(r"<artifactId>([^<]+)</artifactId>", text)
    for element in root.iter():
        if local_name(element.tag) != "dependency":
            continue
        group = ""
        artifact = ""
        for child in element:
            name = local_name(child.tag)
            if name == "groupId" and child.text:
                group = child.text.strip()
            elif name == "artifactId" and child.text:
                artifact = child.text.strip()
        if artifact:
            results.append(f"{group}:{artifact}" if group else artifact)
    return results


GRADLE_RE = re.compile(r"(?:implementation|api|runtimeOnly|testImplementation|testRuntimeOnly)\s*\(?\s*['\"]([^'\"]+)['\"]")
CS_PROJ_RE = re.compile(r"<PackageReference\s+Include=\"([^\"]+)\"", re.IGNORECASE)
REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.\-\[\]]+)")
GO_RE = re.compile(r"^\s*require\s+(?:\((?P<block>.*?)\)|(?P<single>[^\s]+))", re.MULTILINE | re.DOTALL)


def parse_gradle(path: Path) -> List[str]:
    return GRADLE_RE.findall(safe_read(path))


def parse_requirements(path: Path) -> List[str]:
    values: List[str] = []
    for line in safe_read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = REQ_RE.match(line)
        if match:
            values.append(match.group(1))
    return values


def parse_go_mod(path: Path) -> List[str]:
    text = safe_read(path)
    values: List[str] = []
    for match in GO_RE.finditer(text):
        block = match.group("block")
        single = match.group("single")
        if block:
            for line in block.splitlines():
                line = line.strip()
                if line and not line.startswith("//"):
                    values.append(line.split()[0])
        elif single:
            values.append(single.strip())
    return values


def parse_csproj(path: Path) -> List[str]:
    return CS_PROJ_RE.findall(safe_read(path))


def parse_package_json(path: Path) -> Tuple[List[str], Dict[str, Any]]:
    try:
        data = json.loads(safe_read(path))
    except json.JSONDecodeError:
        return [], {}
    deps: List[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        values = data.get(section, {})
        if isinstance(values, dict):
            deps.extend(values.keys())
    return deps, data if isinstance(data, dict) else {}


def parse_pyproject(path: Path) -> Dict[str, Any]:
    if tomllib is None:
        return {}
    try:
        return tomllib.loads(safe_read(path))
    except Exception:
        return {}


def parse_pyproject_dependencies(path: Path) -> List[str]:
    data = parse_pyproject(path)
    deps: List[str] = []
    project = data.get("project", {}) if isinstance(data, dict) else {}
    for value in project.get("dependencies", []) if isinstance(project, dict) else []:
        if isinstance(value, str):
            deps.append(value)
    optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
    if isinstance(optional, dict):
        for values in optional.values():
            if isinstance(values, list):
                deps.extend(str(item) for item in values)
    tool = data.get("tool", {}) if isinstance(data, dict) else {}
    poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
    for section in ("dependencies", "group"):
        value = poetry.get(section, {}) if isinstance(poetry, dict) else {}
        if isinstance(value, dict):
            deps.extend(str(key) for key in value.keys())
    return deps


def detect_language(project_path: Path) -> Tuple[str, str, str]:
    if (project_path / "pom.xml").exists():
        return "java", detect_java_version(project_path), "maven"
    if (project_path / "build.gradle").exists() or (project_path / "build.gradle.kts").exists():
        return "java", detect_java_version(project_path), "gradle"
    if (project_path / "package.json").exists():
        return "node", detect_node_version(project_path), "npm"
    if (project_path / "go.mod").exists():
        return "go", detect_go_version(project_path), "go mod"
    if list(project_path.glob("*.csproj")):
        return "dotnet", detect_dotnet_version(project_path), "dotnet"
    if (project_path / "requirements.txt").exists() or (project_path / "pyproject.toml").exists():
        return "python", detect_python_version(project_path), "pip"
    return "unknown", "unknown", "unknown"


def detect_java_version(project_path: Path) -> str:
    pom = safe_read(project_path / "pom.xml")
    for pattern in [r"<java.version>([^<]+)</java.version>", r"<maven.compiler.source>([^<]+)</maven.compiler.source>"]:
        match = re.search(pattern, pom)
        if match:
            return match.group(1).strip()
    gradle = safe_read(project_path / "build.gradle") + safe_read(project_path / "build.gradle.kts")
    match = re.search(r"(?:sourceCompatibility|targetCompatibility)\s*=\s*['\"]?([^'\"\n]+)", gradle)
    return match.group(1).strip() if match else "unknown"


def detect_python_version(project_path: Path) -> str:
    data = parse_pyproject(project_path / "pyproject.toml") if (project_path / "pyproject.toml").exists() else {}
    project = data.get("project", {}) if isinstance(data, dict) else {}
    requires = project.get("requires-python") if isinstance(project, dict) else None
    if isinstance(requires, str):
        return requires
    req = safe_read(project_path / "requirements.txt")
    match = re.search(r"python[<>=!~]+([0-9.]+)", req, re.IGNORECASE)
    return match.group(1) if match else f"{sys.version_info.major}.{sys.version_info.minor}"


def detect_node_version(project_path: Path) -> str:
    _, data = parse_package_json(project_path / "package.json")
    engines = data.get("engines", {}) if isinstance(data, dict) else {}
    if isinstance(engines, dict) and isinstance(engines.get("node"), str):
        return str(engines["node"])
    return "unknown"


def detect_go_version(project_path: Path) -> str:
    text = safe_read(project_path / "go.mod")
    match = re.search(r"(?m)^go\s+([0-9.]+)$", text)
    return match.group(1) if match else "unknown"


def detect_dotnet_version(project_path: Path) -> str:
    for csproj in project_path.glob("*.csproj"):
        match = re.search(r"<TargetFramework>net([^<]+)</TargetFramework>", safe_read(csproj))
        if match:
            return match.group(1)
    return "unknown"


def collect_dependency_strings(project_path: Path) -> Tuple[List[str], Dict[str, List[str]]]:
    manifests: Dict[str, List[str]] = {}
    if (project_path / "pom.xml").exists():
        manifests["pom.xml"] = parse_pom(project_path / "pom.xml")
    if (project_path / "build.gradle").exists():
        manifests["build.gradle"] = parse_gradle(project_path / "build.gradle")
    if (project_path / "build.gradle.kts").exists():
        manifests["build.gradle.kts"] = parse_gradle(project_path / "build.gradle.kts")
    if (project_path / "package.json").exists():
        deps, _ = parse_package_json(project_path / "package.json")
        manifests["package.json"] = deps
    if (project_path / "requirements.txt").exists():
        manifests["requirements.txt"] = parse_requirements(project_path / "requirements.txt")
    if (project_path / "pyproject.toml").exists():
        manifests["pyproject.toml"] = parse_pyproject_dependencies(project_path / "pyproject.toml")
    if (project_path / "go.mod").exists():
        manifests["go.mod"] = parse_go_mod(project_path / "go.mod")
    csproj_files = list(project_path.glob("*.csproj"))
    if csproj_files:
        manifests[csproj_files[0].name] = parse_csproj(csproj_files[0])
    all_deps: List[str] = []
    for values in manifests.values():
        all_deps.extend(values)
    return all_deps, manifests


def detect_dependencies(project_path: str | Path) -> Dict[str, List[str]]:
    project = Path(project_path)
    dependency_strings, _ = collect_dependency_strings(project)
    found: Dict[str, List[str]] = {}
    lowered = [item.lower() for item in dependency_strings]
    for service, patterns in SERVICE_PATTERNS.items():
        matches = sorted({dependency_strings[idx] for idx, value in enumerate(lowered) if any(pattern in value for pattern in patterns)})
        if matches:
            found[service] = matches
    return found


ENV_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*)\s*$")
PROP_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*[=:]\s*(.*)\s*$")


def parse_env_like(path: Path, pattern: re.Pattern[str]) -> Dict[str, str]:
    results: Dict[str, str] = {}
    for line in safe_read(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = pattern.match(stripped)
        if match:
            results[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return results


def parse_yaml_like(path: Path) -> Dict[str, Any]:
    text = safe_read(path)
    if yaml is not None:
        try:
            loaded = yaml.safe_load(text)
            if isinstance(loaded, dict):
                return flatten_dict(loaded)
        except Exception:
            pass
    results: Dict[str, Any] = {}
    stack: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        indent = len(raw) - len(raw.lstrip())
        key, value = raw.strip().split(":", 1)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, key))
        dotted = ".".join(part for _, part in stack)
        if value.strip():
            results[dotted] = value.strip().strip('"').strip("'")
    return results


def parse_json_like(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(safe_read(path))
    except json.JSONDecodeError:
        return {}
    return flatten_dict(data) if isinstance(data, dict) else {}


def extract_env_vars(project_path: str | Path) -> List[Dict[str, str]]:
    project = Path(project_path)
    findings: List[Dict[str, str]] = []
    for relative in ENV_FILES:
        path = project / relative
        if not path.exists():
            continue
        values: Dict[str, Any]
        if path.suffix in {".yml", ".yaml"}:
            values = parse_yaml_like(path)
        elif path.suffix == ".json":
            values = parse_json_like(path)
        elif path.suffix == ".py":
            values = parse_env_like(path, PROP_RE)
        elif path.name.endswith(".properties") or path.name == "database.yml":
            values = parse_yaml_like(path) if path.name.endswith(".yml") else parse_env_like(path, PROP_RE)
        else:
            values = parse_env_like(path, ENV_RE)
        for key, value in values.items():
            normalized = str(key)
            service = ENV_SERVICE_MAP.get(normalized) or ENV_SERVICE_MAP.get(normalized.upper())
            if service:
                findings.append({"file": str(path.relative_to(project)), "key": normalized, "value": str(value), "service": service})
    return findings


def detect_framework(dependency_strings: Iterable[str]) -> str:
    lowered = "\n".join(item.lower() for item in dependency_strings)
    for framework, patterns in FRAMEWORK_PATTERNS.items():
        if any(pattern.lower() in lowered for pattern in patterns):
            return framework
    return "generic"


def detect_test_framework(project_path: Path, dependency_strings: Iterable[str]) -> str:
    lowered = "\n".join(item.lower() for item in dependency_strings)
    for framework, patterns in TEST_PATTERNS.items():
        if any(pattern.lower() in lowered for pattern in patterns):
            return framework
    if list(project_path.glob("tests/**/*.py")):
        return "pytest"
    if list(project_path.glob("**/*test*.ts")) or list(project_path.glob("**/*test*.js")):
        return "jest"
    if list(project_path.glob("**/*_test.go")):
        return "go test"
    return "unknown"


def detect_ci_files(project_path: Path) -> Tuple[List[str], str]:
    files: List[str] = []
    if (project_path / ".github" / "workflows").exists():
        files.extend(str(path.relative_to(project_path)) for path in sorted((project_path / ".github" / "workflows").glob("*.y*ml")))
    for candidate in [".gitlab-ci.yml", "Jenkinsfile", "bitbucket-pipelines.yml"]:
        if (project_path / candidate).exists():
            files.append(candidate)
    if (project_path / ".circleci" / "config.yml").exists():
        files.append(".circleci/config.yml")
    azure = sorted(project_path.glob("azure-pipelines*.yml"))
    files.extend(str(path.relative_to(project_path)) for path in azure)
    provider = "unknown"
    if any(path.startswith(".github/workflows/") for path in files):
        provider = "github-actions"
    elif ".gitlab-ci.yml" in files:
        provider = "gitlab-ci"
    elif "Jenkinsfile" in files:
        provider = "jenkins"
    elif ".circleci/config.yml" in files:
        provider = "circleci"
    elif "bitbucket-pipelines.yml" in files:
        provider = "bitbucket"
    elif azure:
        provider = "azure-devops"
    return files, provider


def detect_docker(project_path: Path) -> Dict[str, Any]:
    docker_files = []
    for candidate in ["Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        if (project_path / candidate).exists():
            docker_files.append(candidate)
    docker_available = False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)
        docker_available = result.returncode == 0
    except OSError:
        docker_available = False
    return {"has_docker": bool(docker_files), "docker_files": docker_files, "docker_available": docker_available}


def scan_project(project_path: str | Path) -> Dict[str, Any]:
    project = Path(project_path).expanduser().resolve()
    language, version, build_tool = detect_language(project)
    dependency_strings, manifests = collect_dependency_strings(project)
    dependencies = detect_dependencies(project)
    env_vars = extract_env_vars(project)
    ci_files, ci_provider = detect_ci_files(project)
    docker = detect_docker(project)
    framework = detect_framework(dependency_strings)
    test_framework = detect_test_framework(project, dependency_strings)
    testcontainers_present = any("testcontainers" in dep.lower() for dep in dependency_strings)
    return {
        "project_path": str(project),
        "language": language,
        "version": version,
        "build_tool": build_tool,
        "framework": framework,
        "test_framework": test_framework,
        "dependencies": sorted(dependencies.keys()),
        "dependency_details": dependencies,
        "manifests": manifests,
        "env_vars": env_vars,
        "ci_files": ci_files,
        "ci_provider": ci_provider,
        "has_docker": docker["has_docker"],
        "docker_files": docker["docker_files"],
        "docker_available": docker["docker_available"],
        "testcontainers_present": testcontainers_present,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a project for Testcontainers scaffolding signals.")
    parser.add_argument("project_path", nargs="?", default=".", help="Project root to scan.")
    parser.add_argument("--output-json", help="Optional path to write the scan result JSON.")
    args = parser.parse_args()
    result = scan_project(args.project_path)
    payload = json.dumps(result, indent=2)
    if args.output_json:
        Path(args.output_json).expanduser().write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
