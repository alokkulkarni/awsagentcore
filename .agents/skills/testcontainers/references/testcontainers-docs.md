# Official Testcontainers documentation and API references

- Main docs: https://testcontainers.com/
- Java docs: https://java.testcontainers.org/
- Python docs: https://testcontainers-python.readthedocs.io/
- Node docs: https://node.testcontainers.org/
- Go docs: https://golang.testcontainers.org/
- .NET docs: https://dotnet.testcontainers.org/

## Frequently used APIs
- Java `PostgreSQLContainer`, `KafkaContainer`, `MongoDBContainer`, `LocalStackContainer`
- Python `PostgresContainer`, `RedisContainer`, `DockerContainer`, `LocalStackContainer`
- Node `PostgreSqlContainer`, `GenericContainer`, `KafkaContainer`
- Go `postgres.RunContainer`, `mysql.RunContainer`, `mongodb.RunContainer`, `testcontainers.GenericContainer`
- .NET `PostgreSqlBuilder`, `MsSqlBuilder`, `RedisBuilder`, `ContainerBuilder`

## Suggested reference flow
1. Read the language quickstart.
2. Check module-specific docs for required images and wait strategies.
3. Verify CI guidance before enabling Testcontainers in hosted runners.
