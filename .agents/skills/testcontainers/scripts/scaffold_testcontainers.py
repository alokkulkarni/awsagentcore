#!/usr/bin/env python3
"""Generate Testcontainers scaffolding, dependency patches, and test files for supported languages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from scan_project import scan_project

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_DIR = SKILL_DIR / "templates"

JAVA_MODULE_ARTIFACT = {
    "postgresql": "postgresql",
    "mysql": "mysql",
    "mongodb": "mongodb",
    "kafka": "kafka",
    "localstack": "localstack",
    "elasticsearch": "elasticsearch",
    "rabbitmq": "rabbitmq",
    "redis": "testcontainers",
}

PYTHON_MODULE_PACKAGE = {
    "postgresql": "testcontainers[postgresql]==4.4.0",
    "mysql": "testcontainers[mysql]==4.4.0",
    "mongodb": "testcontainers[mongodb]==4.4.0",
    "redis": "testcontainers[redis]==4.4.0",
    "kafka": "testcontainers[kafka]==4.4.0",
    "localstack": "testcontainers[localstack]==4.4.0",
    "rabbitmq": "testcontainers==4.4.0",
    "elasticsearch": "testcontainers==4.4.0",
}

NODE_PACKAGES = {
    "postgresql": "@testcontainers/postgresql",
    "mysql": "@testcontainers/mysql",
    "mongodb": "@testcontainers/mongodb",
    "redis": "@testcontainers/redis",
    "kafka": "@testcontainers/kafka",
    "localstack": "testcontainers",
    "generic": "testcontainers",
}

DOTNET_PACKAGES = {
    "postgresql": "Testcontainers.PostgreSql",
    "redis": "Testcontainers.Redis",
    "mongodb": "Testcontainers.MongoDb",
    "mssql": "Testcontainers.MsSql",
    "mysql": "Testcontainers.MySql",
    "kafka": "Testcontainers.Kafka",
}

GO_MODULES = {
    "postgresql": "github.com/testcontainers/testcontainers-go/modules/postgres",
    "mysql": "github.com/testcontainers/testcontainers-go/modules/mysql",
    "mongodb": "github.com/testcontainers/testcontainers-go/modules/mongodb",
    "redis": "github.com/testcontainers/testcontainers-go/modules/redis",
    "kafka": "github.com/testcontainers/testcontainers-go/modules/kafka",
}

SERVICE_ENV_DEFAULTS = {
    "postgresql": ["DATABASE_URL", "spring.datasource.url"],
    "mysql": ["MYSQL_URL", "spring.datasource.url"],
    "mongodb": ["MONGODB_URI", "spring.data.mongodb.uri"],
    "redis": ["REDIS_URL", "spring.redis.url"],
    "kafka": ["KAFKA_BOOTSTRAP_SERVERS", "spring.kafka.bootstrap-servers"],
    "rabbitmq": ["RABBITMQ_URL", "spring.rabbitmq.host"],
    "localstack": ["AWS_ENDPOINT_URL", "cloud.aws.endpoint.uri"],
    "elasticsearch": ["ELASTICSEARCH_URL"],
}


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def render_template(template_path: Path, context: Dict[str, Any]) -> str:
    text = template_path.read_text(encoding="utf-8")
    for key, value in context.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


def load_config(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def first_env_var(scan: Dict[str, Any], service: str) -> str:
    for item in scan.get("env_vars", []):
        if item.get("service") == service:
            return str(item.get("key"))
    defaults = SERVICE_ENV_DEFAULTS.get(service, [service.upper()])
    return defaults[0]


def java_package(project_path: Path) -> str:
    for source in project_path.glob("src/main/java/**/*.java"):
        match = re.search(r"(?m)^package\s+([a-zA-Z0-9_.]+);", safe_read(source))
        if match:
            return match.group(1)
    pom_text = safe_read(project_path / "pom.xml")
    match = re.search(r"<groupId>([^<]+)</groupId>", pom_text)
    return match.group(1) if match else "com.example"


def ensure_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def summarize_connection_target(module: str, scan: Dict[str, Any]) -> Tuple[str, str]:
    env_name = first_env_var(scan, module)
    mapping = {
        "postgresql": "PostgresContainer.getJdbcUrl()",
        "mysql": "MySQLContainer.getJdbcUrl()",
        "mongodb": "MongoDBContainer.getConnectionString()",
        "redis": "RedisContainer.getRedisUrl()",
        "kafka": "KafkaContainer.getBootstrapServers()",
        "rabbitmq": "RabbitMQContainer.getAmqpUrl()",
        "localstack": "LocalStackContainer.getEndpointOverride()",
        "elasticsearch": "ElasticsearchContainer.getHttpHostAddress()",
    }
    return env_name, mapping.get(module, "container.getHost()")


def patch_pom(project_path: Path, modules: List[str], spring_boot: bool) -> List[str]:
    pom_path = project_path / "pom.xml"
    text = safe_read(pom_path)
    if not text:
        return []
    modified = False
    created: List[str] = []
    bom_block = """
    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>org.testcontainers</groupId>
                <artifactId>testcontainers-bom</artifactId>
                <version>1.19.8</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>
""".strip("\n")
    if "testcontainers-bom" not in text:
        if "<dependencyManagement>" in text:
            replacement = "<dependencyManagement>\n        <dependencies>\n            <dependency>\n                <groupId>org.testcontainers</groupId>\n                <artifactId>testcontainers-bom</artifactId>\n                <version>1.19.8</version>\n                <type>pom</type>\n                <scope>import</scope>\n            </dependency>"
            text = text.replace("<dependencyManagement>\n        <dependencies>", replacement, 1)
        elif "<dependencies>" in text:
            text = text.replace("<dependencies>", bom_block + "\n\n    <dependencies>", 1)
        else:
            text = text.replace("</project>", "\n" + bom_block + "\n</project>")
        modified = True
        created.append("pom.xml")
    dependency_blocks = []
    if "org.testcontainers:junit-jupiter" not in text and "<artifactId>junit-jupiter</artifactId>" not in text:
        dependency_blocks.append("""
        <dependency>
            <groupId>org.testcontainers</groupId>
            <artifactId>junit-jupiter</artifactId>
            <scope>test</scope>
        </dependency>
""".rstrip())
    if spring_boot and "spring-boot-testcontainers" not in text:
        dependency_blocks.append("""
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-testcontainers</artifactId>
            <scope>test</scope>
        </dependency>
""".rstrip())
    for module in modules:
        artifact = JAVA_MODULE_ARTIFACT.get(module)
        if artifact and f"<artifactId>{artifact}</artifactId>" not in text:
            dependency_blocks.append(f"""
        <dependency>
            <groupId>org.testcontainers</groupId>
            <artifactId>{artifact}</artifactId>
            <scope>test</scope>
        </dependency>
""".rstrip())
    if dependency_blocks:
        if "<dependencies>" in text:
            text = text.replace("</dependencies>", "\n" + "\n".join(dependency_blocks) + "\n    </dependencies>", 1)
        else:
            text = text.replace("</project>", "\n    <dependencies>\n" + "\n".join(dependency_blocks) + "\n    </dependencies>\n</project>")
        modified = True
        created.append("pom.xml")
    if modified:
        pom_path.write_text(text, encoding="utf-8")
    return created


def patch_gradle(project_path: Path, modules: List[str]) -> List[str]:
    gradle_path = project_path / ("build.gradle.kts" if (project_path / "build.gradle.kts").exists() else "build.gradle")
    text = safe_read(gradle_path)
    if not text:
        return []
    lines: List[str] = []
    if "testcontainers-bom:1.19.8" not in text:
        lines.append("    testImplementation platform('org.testcontainers:testcontainers-bom:1.19.8')")
    if "org.testcontainers:junit-jupiter" not in text:
        lines.append("    testImplementation 'org.testcontainers:junit-jupiter'")
    for module in modules:
        artifact = JAVA_MODULE_ARTIFACT.get(module)
        if artifact and f"org.testcontainers:{artifact}" not in text:
            lines.append(f"    testImplementation 'org.testcontainers:{artifact}'")
    if lines:
        addition = "\ndependencies {\n" + "\n".join(lines) + "\n}\n"
        gradle_path.write_text(text.rstrip() + addition, encoding="utf-8")
        return [gradle_path.name]
    return []


def patch_python(project_path: Path, modules: List[str]) -> List[str]:
    requirements_test = project_path / "requirements-test.txt"
    existing = safe_read(requirements_test)
    lines = ["pytest"] if "pytest" not in existing else []
    if "psycopg2-binary" not in existing and "postgresql" in modules:
        lines.append("psycopg2-binary>=2.9")
    if "pymongo" not in existing and "mongodb" in modules:
        lines.append("pymongo>=4.6")
    if "redis" not in existing and "redis" in modules:
        lines.append("redis>=5.0")
    for module in modules:
        package = PYTHON_MODULE_PACKAGE.get(module)
        if package and package not in existing:
            lines.append(package)
    if lines:
        requirements_test.write_text(existing.rstrip() + ("\n" if existing.strip() else "") + "\n".join(lines) + "\n", encoding="utf-8")
        return [requirements_test.name]
    return []


def patch_node(project_path: Path, modules: List[str]) -> List[str]:
    package_path = project_path / "package.json"
    try:
        data = json.loads(safe_read(package_path))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    dev_dependencies = data.setdefault("devDependencies", {})
    if not isinstance(dev_dependencies, dict):
        data["devDependencies"] = {}
        dev_dependencies = data["devDependencies"]
    changed = False
    if "testcontainers" not in dev_dependencies:
        dev_dependencies["testcontainers"] = "^10.9.0"
        changed = True
    for module in modules:
        package = NODE_PACKAGES.get(module)
        if package and package not in dev_dependencies:
            dev_dependencies[package] = "^10.9.0"
            changed = True
    if changed:
        package_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return [package_path.name]
    return []


def patch_go(project_path: Path, modules: List[str]) -> List[str]:
    go_mod = project_path / "go.mod"
    text = safe_read(go_mod)
    if not text:
        return []
    additions = []
    if "github.com/testcontainers/testcontainers-go v0.31.0" not in text:
        additions.append("\tgithub.com/testcontainers/testcontainers-go v0.31.0")
    for module in modules:
        module_path = GO_MODULES.get(module)
        if module_path and module_path not in text:
            additions.append(f"\t{module_path} v0.31.0")
    if additions:
        text += "\nrequire (\n" + "\n".join(additions) + "\n)\n"
        go_mod.write_text(text, encoding="utf-8")
        return [go_mod.name]
    return []


def patch_dotnet(project_path: Path, modules: List[str]) -> List[str]:
    csproj_files = list(project_path.glob("*.csproj"))
    if not csproj_files:
        return []
    csproj = csproj_files[0]
    text = safe_read(csproj)
    packages = []
    for module in modules:
        package = DOTNET_PACKAGES.get(module)
        if package and package not in text:
            packages.append(f'    <PackageReference Include="{package}" Version="3.9.0" />')
    if packages:
        snippet = "  <ItemGroup>\n" + "\n".join(packages) + "\n  </ItemGroup>\n"
        text = text.replace("</Project>", snippet + "</Project>")
        csproj.write_text(text, encoding="utf-8")
        return [csproj.name]
    return []


def module_file_name(module: str) -> str:
    parts = [segment.capitalize() for segment in module.replace("-", "_").split("_") if segment]
    return "".join(parts) + "IntegrationTest"


def build_context(module: str, module_config: Dict[str, Any], scan: Dict[str, Any], language: str, project_path: Path) -> Dict[str, Any]:
    env_var = first_env_var(scan, module)
    package = java_package(project_path) if language == "java" else "integration"
    return {
        "PACKAGE": package,
        "POSTGRES_IMAGE": module_config.get("image", "postgres:16-alpine"),
        "MYSQL_IMAGE": module_config.get("image", "mysql:8.0"),
        "MONGODB_IMAGE": module_config.get("image", "mongo:7"),
        "REDIS_IMAGE": module_config.get("image", "redis:7-alpine"),
        "KAFKA_IMAGE": module_config.get("image", "confluentinc/cp-kafka:7.6.0"),
        "RABBITMQ_IMAGE": module_config.get("image", "rabbitmq:3.13-management-alpine"),
        "LOCALSTACK_IMAGE": module_config.get("image", "localstack/localstack:3.4"),
        "KEYCLOAK_IMAGE": module_config.get("image", "quay.io/keycloak/keycloak:24.0"),
        "ELASTICSEARCH_IMAGE": module_config.get("image", "elasticsearch:8.13.0"),
        "GENERIC_IMAGE": module_config.get("image", "nginx:1.27-alpine"),
        "DB_NAME": module_config.get("db_name", "testdb"),
        "DB_USER": module_config.get("username", "test"),
        "DB_PASSWORD": module_config.get("password", "test"),
        "MYSQL_ROOT_PASSWORD": module_config.get("root_password", "rootpass"),
        "TOPICS": ", ".join(module_config.get("topics", [])),
        "LOCALSTACK_SERVICES": ",".join(module_config.get("services", ["s3", "sqs"])),
        "REALM_NAME": module_config.get("realm", "test-realm"),
        "ADMIN_USER": module_config.get("admin_username", "admin"),
        "ADMIN_PASSWORD": module_config.get("admin_password", "admin"),
        "WIREMOCK_FOLDER": module_config.get("stub_folder", "src/test/resources/wiremock"),
        "ENV_VAR_NAME": env_var,
        "EXPOSED_PORT": (module_config.get("ports") or [80])[0],
        "WAIT_LOG": module_config.get("wait_log", "ready"),
    }


def select_template(language: str, module: str, framework: str) -> Path:
    if language == "java" and framework == "spring-boot" and module == "postgresql":
        return TEMPLATE_DIR / "java" / "spring-boot-test.java.tmpl"
    filename = {
        "java": f"junit5-{module}.java.tmpl",
        "python": f"pytest-{module}.py.tmpl",
        "node": f"jest-{module}.ts.tmpl",
        "go": f"go-{module}.go.tmpl",
        "dotnet": f"xunit-{module}.cs.tmpl",
    }.get(language)
    candidate = TEMPLATE_DIR / language / filename if filename else TEMPLATE_DIR / language
    if candidate.exists():
        return candidate
    fallbacks = {
        "java": TEMPLATE_DIR / "java" / "junit5-generic.java.tmpl",
        "python": TEMPLATE_DIR / "python" / "pytest-generic.py.tmpl",
        "node": TEMPLATE_DIR / "node" / "jest-generic.ts.tmpl",
        "go": TEMPLATE_DIR / "go" / "go-generic.go.tmpl",
        "dotnet": TEMPLATE_DIR / "dotnet" / "xunit-generic.cs.tmpl",
    }
    return fallbacks[language]


def output_path(project_path: Path, language: str, placement: str, module: str) -> Path:
    placement_path = project_path / placement
    if language == "java":
        return placement_path / f"{module_file_name(module)}.java"
    if language == "python":
        return placement_path / f"test_{module.replace('-', '_')}_integration.py"
    if language == "node":
        return placement_path / f"{module.replace('-', '_')}.integration.test.ts"
    if language == "go":
        return placement_path / f"{module.replace('-', '_')}_integration_test.go"
    return placement_path / f"{module_file_name(module)}.cs"


def write_tests(project_path: Path, config: Dict[str, Any]) -> List[str]:
    scan = config.get("scan", scan_project(project_path))
    language = scan.get("language", "python")
    framework = scan.get("framework", "generic")
    placement = config.get("test_placement") or "tests/integration"
    created: List[str] = []
    for item in config.get("containers", []):
        module = item["name"]
        context = build_context(module, item.get("config", {}), scan, language, project_path)
        template = select_template(language, module, framework)
        destination = output_path(project_path, language, placement, module)
        ensure_file(destination, render_template(template, context))
        created.append(str(destination.relative_to(project_path)))
    if language == "java":
        props_template = TEMPLATE_DIR / "configs" / "testcontainers.properties.tmpl"
        props_path = project_path / "src" / "test" / "resources" / "testcontainers.properties"
        ensure_file(props_path, render_template(props_template, {"TC_REUSE": str(config.get("reuse_containers", False)).lower()}))
        created.append(str(props_path.relative_to(project_path)))
    return created


def patch_dependencies(project_path: Path, scan: Dict[str, Any], modules: List[str]) -> List[str]:
    language = scan.get("language")
    if language == "java":
        if scan.get("build_tool") == "maven":
            return patch_pom(project_path, modules, scan.get("framework") == "spring-boot")
        return patch_gradle(project_path, modules)
    if language == "python":
        return patch_python(project_path, modules)
    if language == "node":
        return patch_node(project_path, modules)
    if language == "go":
        return patch_go(project_path, modules)
    if language == "dotnet":
        return patch_dotnet(project_path, modules)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold Testcontainers dependencies and tests.")
    parser.add_argument("--project", default=".", help="Project root to update.")
    parser.add_argument("--config", required=True, help="Path to JSON config collected by collect_info.py.")
    args = parser.parse_args()

    project_path = Path(args.project).expanduser().resolve()
    config = load_config(Path(args.config).expanduser())
    scan = config.get("scan") or scan_project(project_path)
    modules = [item["name"] for item in config.get("containers", [])]
    modified = patch_dependencies(project_path, scan, modules)
    created = write_tests(project_path, config)

    if config.get("patch_ci"):
        try:
            from patch_pipeline import patch_project_pipelines

            patched = patch_project_pipelines(project_path, config.get("ci_provider", scan.get("ci_provider", "github-actions")))
        except Exception:
            patched = []
    else:
        patched = []

    connections = [summarize_connection_target(module, scan) for module in modules]
    print("I will now create/modify:")
    for path in modified + created + patched:
        print(f"  ✅ {path}")
    if connections:
        print("\nConnections auto-wired from detected env/property files:")
        for source, target in connections:
            print(f"  - {source} → {target}")
    print("\nScaffolding complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
