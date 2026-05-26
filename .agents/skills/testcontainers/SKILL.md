---
name: testcontainers
description: >
  Add and configure Testcontainers to any project for integration and E2E testing against real containerised dependencies (PostgreSQL, MySQL, MongoDB, Redis, Kafka, RabbitMQ, LocalStack, Keycloak, Elasticsearch, and 100+ more). Scans the project to detect language, framework, and existing dependencies; asks targeted questions about required containers; generates test scaffolding, updates dependency files, configures credentials from existing env/property files, and patches CI/CD pipelines to enable Docker-in-Docker. Use when asked to add integration tests, E2E tests, test containers, or remove mocks in favour of real services.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH). Supports Java (Maven/Gradle), Python (pytest), Node.js (Jest/Vitest), Go, and .NET projects. Requires Docker or Testcontainers Cloud at test runtime.
metadata:
  category: testing
  tags: [testcontainers, integration-testing, e2e, docker, java, python, nodejs, go, dotnet, postgresql, kafka, redis, mongodb]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Activation

Activate this skill when asked to:
- Add TestContainers to a project
- Replace mocks with real containers
- Set up integration tests with real services
- Configure E2E test infrastructure
- Add DB/queue/cache tests using Docker containers

---

## MANDATORY: Ask ALL questions before writing any files

You MUST ask every question below before writing a single file. Do NOT infer, assume, or skip questions. Ask one at a time and wait for the answer.

### PHASE 1 — Project scan

**Q1.** "What is the path to the project? [default: current directory]"

After getting the path, run `scripts/scan_project.py` to auto-detect:
- Language and version (Java/Python/Node.js/Go/.NET)
- Build tool (Maven/Gradle/npm/pip/go mod/dotnet)
- Test framework (JUnit5/pytest/Jest/Vitest/go test/xUnit)
- Existing dependencies (databases, message brokers, caches)
- Existing env/property files with connection strings
- Whether `.github/workflows/` exists with CI pipelines
- Whether docker-compose.yml exists

Tell the user what was detected, confirm accuracy:
> "I detected: Java 21 / Spring Boot / Maven / JUnit5. Found existing deps: PostgreSQL JDBC, Spring Data Redis. Found .env with DATABASE_URL, REDIS_URL. Is this correct? [y/n]"

**Q2.** "Can this project run Docker? (Required for Testcontainers.) [y/n, default: y]"
If no: explain TestContainers Cloud as alternative. Ask: "Would you like to configure Testcontainers Cloud instead? [y/n]"

### PHASE 2 — Select containers

Show the user categories and ask which they need. For each detected existing dependency, suggest the matching Testcontainers module:

> "I found PostgreSQL in your dependencies. Add a Testcontainers PostgreSQL module for integration tests? [y/n, default: y]"

Then ask broadly:
**Q3.** "Which additional container modules do you need? (select all that apply)"
Show grouped list:
```
Relational DBs:  postgresql, mysql, mariadb, mssql, oracle-free
NoSQL/Cache:     mongodb, redis, cassandra, dynamodb, elasticsearch, opensearch
Messaging:       kafka, rabbitmq, nats, pulsar, activemq
Cloud emulators: localstack (AWS), azurite (Azure), google-cloud (GCP)
Auth:            keycloak
HTTP mocking:    wiremock, mockserver
Other:           vault, k3s, nginx, custom (generic)
```

For each selected module, ask language-specific config questions:

**PostgreSQL:**
- "Database name? [testdb]"
- "Username? [test]"
- "Password? [test]"
- "Docker image tag? [postgres:16-alpine]"
- "Should I auto-wire this to your existing DATABASE_URL / spring.datasource.url config? [y/n, default: y]"

**MySQL:**
- "Database name? [testdb]"
- "Root password? [rootpass]"
- "Username? [test]" / "Password? [test]"
- "Docker image tag? [mysql:8.0]"
- "Auto-wire existing MYSQL_URL / spring.datasource.url? [y/n, default: y]"

**MongoDB:**
- "Database name? [testdb]"
- "Docker image tag? [mongo:7]"
- "Auto-wire existing MONGODB_URI / spring.data.mongodb.uri? [y/n, default: y]"

**Redis:**
- "Docker image tag? [redis:7-alpine]"
- "Auto-wire existing REDIS_URL / spring.redis.url? [y/n, default: y]"

**Kafka:**
- "Docker image? [confluentinc/cp-kafka:7.6.0 | apache/kafka:3.7.0]"
- "Topic(s) to pre-create? (optional)"
- "Auto-wire existing KAFKA_BOOTSTRAP_SERVERS? [y/n, default: y]"

**RabbitMQ:**
- "Docker image tag? [rabbitmq:3.13-management-alpine]"
- "VHost? [/]" / "Username? [guest]" / "Password? [guest]"
- "Auto-wire existing RABBITMQ_URL / spring.rabbitmq.host? [y/n, default: y]"

**LocalStack:**
- "Which AWS services to emulate? [s3, sqs, sns, dynamodb, lambda, secretsmanager, ssm...]"
- "Docker image tag? [localstack/localstack:3.4]"
- "Auto-wire existing AWS_ENDPOINT_URL / cloud.aws.endpoint.uri? [y/n, default: y]"

**Keycloak:**
- "Realm name? [test-realm]"
- "Admin username/password? [admin/admin]"
- "Docker image tag? [quay.io/keycloak/keycloak:24.0]"

**Elasticsearch:**
- "Docker image tag? [elasticsearch:8.13.0]"
- "Auto-wire existing ELASTICSEARCH_URL? [y/n, default: y]"

**WireMock:**
- "Docker image tag? [wiremock/wiremock:3.5.4-alpine]"
- "Stub mappings folder? [src/test/resources/wiremock]"

**Generic container:**
- "Docker image? (required)"
- "Exposed ports? (comma-separated)"
- "Environment variables? (KEY=VALUE pairs)"
- "Wait strategy? [log-message | http-get | port | none, default: port]"
- "Log message to wait for? (if log-message strategy)"

### PHASE 3 — Test placement

**Q4.** "Where should integration/E2E tests be placed?"
- Java: `src/test/java/<package>/integration/` (default)
- Python: `tests/integration/` (default)
- Node.js: `test/integration/` or `__tests__/integration/` (default)
- Go: `internal/<pkg>/<pkg>_integration_test.go` (default)
- .NET: `<Project>.IntegrationTests/` (default)

**Q5.** "Should Testcontainers use shared containers (one container per test suite, not per test) to speed up tests? [y/n, default: y]"

**Q6.** "Should containers be reused across test runs (TC_REUSE=true) for even faster local dev? [y/n, default: n]"

### PHASE 4 — CI/CD pipeline integration

**Q7.** "I found these CI pipeline files: [list them]. Should I patch them to add Docker socket access / Docker-in-Docker required for Testcontainers? [y/n, default: y]"

**Q8.** "CI provider? [github-actions | gitlab-ci | jenkins | circleci | bitbucket | azure-devops, detected: <detected>]"

---

## After collecting ALL answers — show a creation summary

Before writing files, print:
```
I will now create/modify:
  ✅ pom.xml / build.gradle — add TC dependencies for: postgresql, kafka, redis
  ✅ src/test/java/com/example/integration/PostgresContainerTest.java
  ✅ src/test/java/com/example/integration/KafkaContainerTest.java
  ✅ src/test/java/com/example/integration/RedisContainerTest.java
  ✅ src/test/resources/testcontainers.properties — configure reuse & logging
  ✅ .github/workflows/ci.yml — patch to add Docker socket permissions
  
Connections auto-wired from .env / application.properties:
  - DATABASE_URL → PostgresContainer.getJdbcUrl()
  - REDIS_URL    → RedisContainer.getRedisUrl()
  - KAFKA_BOOTSTRAP_SERVERS → KafkaContainer.getBootstrapServers()

Shall I proceed? [y/n]
```

---

## Credential & connection auto-wiring

When scanning the project, `scan_project.py` MUST look for:
- `.env`, `.env.test`, `.env.local`
- `application.properties`, `application-test.properties` (Spring Boot)
- `application.yml`, `application-test.yml`
- `config.py`, `settings.py` (Python/Django/FastAPI)
- `database.yml` (Rails)
- `appsettings.json`, `appsettings.Test.json` (.NET)
- `config/default.json`, `config/test.json` (Node config)

For each file found, extract known connection string patterns:
```
DATABASE_URL, POSTGRES_URL, PG_URL → PostgreSQL
MYSQL_URL, MYSQL_DATABASE, MYSQL_HOST → MySQL
MONGODB_URI, MONGO_URL → MongoDB
REDIS_URL, REDIS_HOST → Redis
KAFKA_BOOTSTRAP_SERVERS, KAFKA_BROKERS → Kafka
RABBITMQ_URL, AMQP_URL, SPRING_RABBITMQ_HOST → RabbitMQ
AWS_ENDPOINT_URL, LOCALSTACK_HOST → LocalStack
ELASTICSEARCH_URL, ES_URL → Elasticsearch
```

When generating test scaffolding, inject the container's dynamic URL into test setup via the language-appropriate mechanism:
- Java Spring Boot: `@DynamicPropertySource`
- Java plain: set system properties or pass to constructor
- Python pytest: `monkeypatch.setenv` or `os.environ` in `conftest.py`
- Node.js: set `process.env` in `beforeAll`
- Go: `os.Setenv` in `TestMain`
- .NET: override `IConfiguration` in test setup

---

## Language-specific dependency additions

### Java (Maven)
Add to `pom.xml` in `<dependencyManagement>` and `<dependencies>`:
```xml
<!-- BOM — import once -->
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>testcontainers-bom</artifactId>
    <version>1.19.8</version>
    <type>pom</type>
    <scope>import</scope>
</dependency>

<!-- Per module — no version needed when using BOM -->
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>postgresql</artifactId>  <!-- or kafka, mongodb, redis, etc. -->
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>junit-jupiter</artifactId>
    <scope>test</scope>
</dependency>
```

For Spring Boot projects also add:
```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-testcontainers</artifactId>
    <scope>test</scope>
</dependency>
```

### Java (Gradle)
```groovy
testImplementation platform('org.testcontainers:testcontainers-bom:1.19.8')
testImplementation 'org.testcontainers:postgresql'
testImplementation 'org.testcontainers:junit-jupiter'
```

### Python
Add to `requirements-test.txt` or `pyproject.toml [test]`:
```
testcontainers[postgresql]==4.4.0
testcontainers[mysql]==4.4.0
testcontainers[mongodb]==4.4.0
testcontainers[redis]==4.4.0
testcontainers[kafka]==4.4.0
testcontainers[localstack]==4.4.0
```

### Node.js
```bash
npm install --save-dev testcontainers
# Also needs @types/testcontainers for TypeScript
```

### Go
```bash
go get github.com/testcontainers/testcontainers-go@v0.31.0
go get github.com/testcontainers/testcontainers-go/modules/postgres@v0.31.0
```

### .NET
```xml
<PackageReference Include="Testcontainers.PostgreSql" Version="3.9.0" />
<PackageReference Include="Testcontainers.Kafka" Version="3.9.0" />
```

---

## Implementation workflow

1. Run `python3 scripts/scan_project.py <project>` and present the findings.
2. Collect answers with `python3 scripts/collect_info.py --project <project> --output-json testcontainers-config.json` when interactive collection is appropriate.
3. Generate scaffolding with `python3 scripts/scaffold_testcontainers.py --project <project> --config testcontainers-config.json`.
4. Patch CI files with `python3 scripts/patch_pipeline.py --project <project> --provider <provider>`.
5. Validate everything with `python3 scripts/validate_setup.py <project>`.
6. Do not stop until validation has been run and the user sees a concise PASS/WARN summary.

## Safety rules

- Prefer official Testcontainers modules over generic containers whenever available.
- Never write container endpoints into production config files.
- Never use `:latest` image tags in generated tests.
- Keep container credentials test-scoped only.
- Enable reuse only for local development; avoid reuse in CI.
- If Docker is unavailable, explain the Testcontainers Cloud option before making changes.
