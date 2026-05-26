#!/usr/bin/env python3
"""Collect Testcontainers configuration interactively or from defaults."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from scan_project import scan_project

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "postgresql": {"db_name": "testdb", "username": "test", "password": "test", "image": "postgres:16-alpine", "auto_wire": True},
    "mysql": {"db_name": "testdb", "root_password": "rootpass", "username": "test", "password": "test", "image": "mysql:8.0", "auto_wire": True},
    "mongodb": {"db_name": "testdb", "image": "mongo:7", "auto_wire": True},
    "redis": {"image": "redis:7-alpine", "auto_wire": True},
    "kafka": {"image": "confluentinc/cp-kafka:7.6.0", "topics": [], "auto_wire": True},
    "rabbitmq": {"image": "rabbitmq:3.13-management-alpine", "vhost": "/", "username": "guest", "password": "guest", "auto_wire": True},
    "localstack": {"services": ["s3", "sqs", "sns"], "image": "localstack/localstack:3.4", "auto_wire": True},
    "keycloak": {"realm": "test-realm", "admin_username": "admin", "admin_password": "admin", "image": "quay.io/keycloak/keycloak:24.0"},
    "elasticsearch": {"image": "elasticsearch:8.13.0", "auto_wire": True},
    "wiremock": {"image": "wiremock/wiremock:3.5.4-alpine", "stub_folder": "src/test/resources/wiremock"},
    "generic": {"image": "nginx:1.27-alpine", "ports": [80], "env": {}, "wait_strategy": "port", "wait_log": ""},
}

CATEGORIES = {
    "Relational DBs": ["postgresql", "mysql", "mariadb", "mssql", "oracle-free"],
    "NoSQL/Cache": ["mongodb", "redis", "cassandra", "dynamodb", "elasticsearch", "opensearch"],
    "Messaging": ["kafka", "rabbitmq", "nats", "pulsar", "activemq"],
    "Cloud emulators": ["localstack", "azurite", "google-cloud"],
    "Auth": ["keycloak"],
    "HTTP mocking": ["wiremock", "mockserver"],
    "Other": ["vault", "k3s", "nginx", "generic"],
}


def prompt(text: str, default: str, interactive: bool) -> str:
    if not interactive:
        return default
    try:
        answer = input(f"{text} ").strip()
    except EOFError:
        return default
    return answer or default


def prompt_bool(text: str, default: bool, interactive: bool) -> bool:
    raw = prompt(text, "y" if default else "n", interactive).strip().lower()
    if raw in {"y", "yes", "true", "1"}:
        return True
    if raw in {"n", "no", "false", "0"}:
        return False
    return default


def split_csv(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def detect_default_test_path(language: str, project_name: str) -> str:
    return {
        "java": "src/test/java/com/example/integration",
        "python": "tests/integration",
        "node": "test/integration",
        "go": "internal/integration",
        "dotnet": f"{project_name}.IntegrationTests",
    }.get(language, "tests/integration")


def collect_module(module: str, interactive: bool) -> Dict[str, Any]:
    defaults = DEFAULTS.get(module, DEFAULTS["generic"]).copy()
    if module == "postgresql":
        defaults["db_name"] = prompt('Database name? [testdb]', defaults["db_name"], interactive)
        defaults["username"] = prompt('Username? [test]', defaults["username"], interactive)
        defaults["password"] = prompt('Password? [test]', defaults["password"], interactive)
        defaults["image"] = prompt('Docker image tag? [postgres:16-alpine]', defaults["image"], interactive)
        defaults["auto_wire"] = prompt_bool('Should I auto-wire this to your existing DATABASE_URL / spring.datasource.url config? [y/n, default: y]', True, interactive)
    elif module == "mysql":
        defaults["db_name"] = prompt('Database name? [testdb]', defaults["db_name"], interactive)
        defaults["root_password"] = prompt('Root password? [rootpass]', defaults["root_password"], interactive)
        defaults["username"] = prompt('Username? [test]', defaults["username"], interactive)
        defaults["password"] = prompt('Password? [test]', defaults["password"], interactive)
        defaults["image"] = prompt('Docker image tag? [mysql:8.0]', defaults["image"], interactive)
        defaults["auto_wire"] = prompt_bool('Auto-wire existing MYSQL_URL / spring.datasource.url? [y/n, default: y]', True, interactive)
    elif module == "mongodb":
        defaults["db_name"] = prompt('Database name? [testdb]', defaults["db_name"], interactive)
        defaults["image"] = prompt('Docker image tag? [mongo:7]', defaults["image"], interactive)
        defaults["auto_wire"] = prompt_bool('Auto-wire existing MONGODB_URI / spring.data.mongodb.uri? [y/n, default: y]', True, interactive)
    elif module == "redis":
        defaults["image"] = prompt('Docker image tag? [redis:7-alpine]', defaults["image"], interactive)
        defaults["auto_wire"] = prompt_bool('Auto-wire existing REDIS_URL / spring.redis.url? [y/n, default: y]', True, interactive)
    elif module == "kafka":
        defaults["image"] = prompt('Docker image? [confluentinc/cp-kafka:7.6.0 | apache/kafka:3.7.0]', defaults["image"], interactive)
        defaults["topics"] = split_csv(prompt('Topic(s) to pre-create? (optional)', ",".join(defaults["topics"]), interactive))
        defaults["auto_wire"] = prompt_bool('Auto-wire existing KAFKA_BOOTSTRAP_SERVERS? [y/n, default: y]', True, interactive)
    elif module == "rabbitmq":
        defaults["image"] = prompt('Docker image tag? [rabbitmq:3.13-management-alpine]', defaults["image"], interactive)
        defaults["vhost"] = prompt('VHost? [/]', defaults["vhost"], interactive)
        defaults["username"] = prompt('Username? [guest]', defaults["username"], interactive)
        defaults["password"] = prompt('Password? [guest]', defaults["password"], interactive)
        defaults["auto_wire"] = prompt_bool('Auto-wire existing RABBITMQ_URL / spring.rabbitmq.host? [y/n, default: y]', True, interactive)
    elif module == "localstack":
        defaults["services"] = split_csv(prompt('Which AWS services to emulate? [s3, sqs, sns, dynamodb, lambda, secretsmanager, ssm...]', ",".join(defaults["services"]), interactive))
        defaults["image"] = prompt('Docker image tag? [localstack/localstack:3.4]', defaults["image"], interactive)
        defaults["auto_wire"] = prompt_bool('Auto-wire existing AWS_ENDPOINT_URL / cloud.aws.endpoint.uri? [y/n, default: y]', True, interactive)
    elif module == "keycloak":
        defaults["realm"] = prompt('Realm name? [test-realm]', defaults["realm"], interactive)
        defaults["admin_username"] = prompt('Admin username? [admin]', defaults["admin_username"], interactive)
        defaults["admin_password"] = prompt('Admin password? [admin]', defaults["admin_password"], interactive)
        defaults["image"] = prompt('Docker image tag? [quay.io/keycloak/keycloak:24.0]', defaults["image"], interactive)
    elif module == "elasticsearch":
        defaults["image"] = prompt('Docker image tag? [elasticsearch:8.13.0]', defaults["image"], interactive)
        defaults["auto_wire"] = prompt_bool('Auto-wire existing ELASTICSEARCH_URL? [y/n, default: y]', True, interactive)
    elif module == "wiremock":
        defaults["image"] = prompt('Docker image tag? [wiremock/wiremock:3.5.4-alpine]', defaults["image"], interactive)
        defaults["stub_folder"] = prompt('Stub mappings folder? [src/test/resources/wiremock]', defaults["stub_folder"], interactive)
    else:
        defaults["image"] = prompt('Docker image? (required)', defaults["image"], interactive)
        defaults["ports"] = [int(port) for port in split_csv(prompt('Exposed ports? (comma-separated)', ",".join(str(port) for port in defaults["ports"]), interactive)) or ["80"]]
        defaults["wait_strategy"] = prompt('Wait strategy? [log-message | http-get | port | none, default: port]', defaults["wait_strategy"], interactive)
        defaults["wait_log"] = prompt('Log message to wait for? (if log-message strategy)', defaults["wait_log"], interactive)
    return defaults


def collect(args: argparse.Namespace) -> Dict[str, Any]:
    interactive = not args.no_interactive and sys.stdin.isatty()
    project_path = Path(prompt('What is the path to the project? [default: current directory]', args.project, interactive)).expanduser().resolve()
    scan = scan_project(project_path)
    print(json.dumps(scan, indent=2))
    confirmation = prompt_bool(
        f"I detected: {scan['language']} {scan['version']} / {scan['framework']} / {scan['build_tool']} / {scan['test_framework']}. Found existing deps: {', '.join(scan['dependencies']) or 'none'}. Found env vars: {', '.join(item['key'] for item in scan['env_vars']) or 'none'}. Is this correct? [y/n]",
        True,
        interactive,
    )
    docker_enabled = prompt_bool('Can this project run Docker? (Required for Testcontainers.) [y/n, default: y]', True, interactive)
    use_tc_cloud = False
    if not docker_enabled:
        use_tc_cloud = prompt_bool('Would you like to configure Testcontainers Cloud instead? [y/n]', True, interactive)

    selected_modules: List[str] = []
    for dependency in scan["dependencies"]:
        if prompt_bool(f"I found {dependency} in your dependencies. Add a Testcontainers {dependency} module for integration tests? [y/n, default: y]", True, interactive):
            selected_modules.append(dependency)

    print('Which additional container modules do you need? (select all that apply)')
    for category, modules in CATEGORIES.items():
        print(f"{category:<17}: {', '.join(modules)}")
    requested = split_csv(prompt('Modules (comma-separated, optional)', args.modules or "", interactive))
    for module in requested:
        if module not in selected_modules:
            selected_modules.append(module)
    if not selected_modules:
        selected_modules = split_csv(args.modules) if args.modules else ["postgresql"]

    containers = [{"name": module, "config": collect_module(module, interactive)} for module in selected_modules]
    test_placement = prompt('Where should integration/E2E tests be placed?', detect_default_test_path(scan["language"], project_path.name), interactive)
    shared_containers = prompt_bool('Should Testcontainers use shared containers (one container per test suite, not per test) to speed up tests? [y/n, default: y]', True, interactive)
    reuse_containers = prompt_bool('Should containers be reused across test runs (TC_REUSE=true) for even faster local dev? [y/n, default: n]', False, interactive)
    patch_ci = prompt_bool(f"I found these CI pipeline files: {scan['ci_files'] or ['none']}. Should I patch them to add Docker socket access / Docker-in-Docker required for Testcontainers? [y/n, default: y]", True, interactive)
    ci_provider = prompt('CI provider? [github-actions | gitlab-ci | jenkins | circleci | bitbucket | azure-devops]', scan.get("ci_provider", "github-actions"), interactive)

    return {
        "project_path": str(project_path),
        "confirmed_scan": confirmation,
        "docker_enabled": docker_enabled,
        "use_testcontainers_cloud": use_tc_cloud,
        "scan": scan,
        "containers": containers,
        "test_placement": test_placement,
        "shared_containers": shared_containers,
        "reuse_containers": reuse_containers,
        "patch_ci": patch_ci,
        "ci_provider": ci_provider,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Testcontainers requirements interactively.")
    parser.add_argument("--project", default=".", help="Project root to inspect.")
    parser.add_argument("--modules", default="", help="Comma-separated module list for non-interactive mode.")
    parser.add_argument("--output-json", default="testcontainers-config.json", help="Output path for collected JSON.")
    parser.add_argument("--no-interactive", action="store_true", help="Use defaults and supplied flags without prompting.")
    args = parser.parse_args()
    config = collect(args)
    output_path = Path(args.output_json).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Saved configuration to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
