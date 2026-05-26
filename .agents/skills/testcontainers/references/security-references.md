# Container security references

- Docker image best practices: https://docs.docker.com/develop/dev-best-practices/
- OWASP Docker Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html
- Trivy image scanning: https://aquasecurity.github.io/trivy/
- Snyk container best practices: https://snyk.io/learn/container-security/

## Testcontainers-specific guidance
- Pin image tags to known-good versions.
- Avoid `latest` and mutable tags.
- Keep secrets in test-only env variables.
- Use minimal images and documented wait strategies.
- Do not disable Ryuk cleanup unless you own an equivalent cleanup mechanism.
