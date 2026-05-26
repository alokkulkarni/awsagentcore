### TC-001: Use specific module containers over GenericContainer when available
Pick `PostgreSQLContainer`, `KafkaContainer`, `MongoDBContainer`, or the closest language-native module before reaching for a generic wrapper.

### TC-002: Always use @Container static field for shared containers (JUnit5)
JUnit 5 tests should model suite-scoped shared containers as static `@Container` fields so startup cost is paid once per class.

### TC-003: Prefer @ServiceConnection (Spring Boot 3.x) over manual @DynamicPropertySource
When Spring Boot supports the module, `@ServiceConnection` is simpler, more idiomatic, and less error-prone than manual property wiring.

### TC-004: Never hardcode localhost — always use container.getHost() / getMappedPort()
Docker routing differs between local machines, CI runners, and remote Docker hosts.

### TC-005: Use reusable containers (withReuse(true)) for faster local dev; disable in CI
Reuse is a developer-experience optimization, not a CI default.

### TC-006: Declare TestContainers BOM to manage version alignment
For Java, import the BOM once and omit per-module versions.

### TC-007: Use wait strategies appropriate to the container (LogMessageWait, HttpWait)
Choose readiness checks that prove the service is actually ready, not merely listening on a port.

### TC-008: Store container credentials in test-scoped env vars, never in production config
Test-generated usernames, passwords, and URLs must stay inside test bootstrap logic.

### TC-009: Clean up test data between tests; do not share mutable state across test classes
Shared containers are fine; shared mutable database state is not.

### TC-010: Pin Docker image tags — never use :latest in tests
Pinned tags reduce flakiness and make failures reproducible.

### TC-011: Configure RYUK_DISABLED=false (default) — never disable resource cleanup
Ryuk is part of safe cleanup and should remain enabled unless you have a documented replacement.

### TC-012: Use network aliases when containers need to communicate with each other
Networks and aliases make multi-container integration tests predictable.

### TC-013: CI pipelines must mount Docker socket or use DinD for Testcontainers to work
Hosted or self-hosted runners must expose a functioning Docker daemon to tests.

### TC-014: Use alpine or slim base images in tests to reduce pull time
Smaller images speed up feedback loops and reduce CI cost.

### TC-015: Generate and commit test reports to repository on CI runs
Artifacts should be retained so failures can be triaged after the run finishes.

### TC-016: Add testcontainers.reuse.enable=true to .testcontainers.properties for local dev only
Treat reuse as an opt-in local convenience and keep CI deterministic.

### TC-017: Inject container-derived URLs via @DynamicPropertySource or env overrides — never modify production config
Tests should override runtime wiring without changing committed production settings.

### TC-018: Test classes using Testcontainers must not extend other integration test base classes that conflict
Avoid competing lifecycle hooks, duplicate container startup, or conflicting property initialisers.

### TC-019: Use Singleton container pattern (static field + @Container) to share across test methods
When tests are read-only or reset state safely, singleton containers keep test suites fast.

### TC-020: Document which containers are used in README or test plan
Future maintainers need to know which services are emulated, why they exist, and how CI supports them.
