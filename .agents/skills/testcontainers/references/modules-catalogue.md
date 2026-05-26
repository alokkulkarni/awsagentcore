# Testcontainers modules catalogue

This skill covers the most common official and widely adopted Testcontainers modules across Java, Python, Node.js, Go, and .NET.

## Relational databases
- PostgreSQL
- MySQL
- MariaDB
- SQL Server / MSSQL
- Oracle Free / Oracle XE

## NoSQL and search
- MongoDB
- Redis
- Cassandra
- DynamoDB Local
- Elasticsearch
- OpenSearch

## Messaging
- Kafka
- RabbitMQ
- NATS
- Pulsar
- ActiveMQ

## Cloud emulators and platform services
- LocalStack
- Azurite
- MinIO
- Vault
- K3s
- NGINX

## HTTP and auth
- WireMock
- MockServer
- Keycloak

## Language notes
- Java: prefer official `org.testcontainers:*` artifacts, and community add-ons only where official modules are unavailable.
- Python: `testcontainers` extras cover PostgreSQL, MySQL, MongoDB, Redis, Kafka, and LocalStack; other services may use `DockerContainer` wrappers.
- Node.js: use `testcontainers` core plus official module packages such as `@testcontainers/postgresql` where available.
- Go: prefer `testcontainers-go/modules/*`; fall back to generic containers only when no module exists.
- .NET: use `Testcontainers.*` packages per module.
