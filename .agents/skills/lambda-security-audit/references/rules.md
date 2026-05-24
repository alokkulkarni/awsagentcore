# AWS Lambda Security Rules Reference

## Official AWS Documentation

- https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html
- https://docs.aws.amazon.com/lambda/latest/dg/security-iam.html
- https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-encryption
- https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html

## OWASP References

- https://owasp.org/www-project-top-ten/
- https://owasp.org/www-project-serverless-top-10/
- https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html

## CVE Scanner Tooling

- https://pypi.org/project/pip-audit/
- https://docs.npmjs.com/cli/v10/commands/npm-audit
- https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck
- https://owasp.org/www-project-dependency-check/

## CWE References

- CWE-532: https://cwe.mitre.org/data/definitions/532.html
- CWE-798: https://cwe.mitre.org/data/definitions/798.html
- CWE-95: https://cwe.mitre.org/data/definitions/95.html
- CWE-918: https://cwe.mitre.org/data/definitions/918.html
- CWE-502: https://cwe.mitre.org/data/definitions/502.html
- CWE-78: https://cwe.mitre.org/data/definitions/78.html
- CWE-327: https://cwe.mitre.org/data/definitions/327.html
- CWE-295: https://cwe.mitre.org/data/definitions/295.html
- CWE-611: https://cwe.mitre.org/data/definitions/611.html
- CWE-89: https://cwe.mitre.org/data/definitions/89.html
- CWE-117: https://cwe.mitre.org/data/definitions/117.html
- CWE-390: https://cwe.mitre.org/data/definitions/390.html
- CWE-200: https://cwe.mitre.org/data/definitions/200.html
- CWE-20: https://cwe.mitre.org/data/definitions/20.html

---

## Quick Reference — All Rules

| Rule ID | Language | Severity | CWE | Auto-fix |
|---------|----------|----------|-----|---------|
| PY_PII_IN_LOG | Python | CRITICAL | CWE-532 | No |
| PY_HARDCODED_SECRET | Python | CRITICAL | CWE-798 | No |
| PY_EVAL_EXEC | Python | CRITICAL | CWE-95 | No |
| PY_SSRF_URLOPEN | Python | HIGH | CWE-918 | Yes |
| PY_INSECURE_DESERIALISE | Python | HIGH | CWE-502 | No |
| PY_CMD_INJECTION | Python | HIGH | CWE-78 | No |
| PY_WEAK_CRYPTO | Python | HIGH | CWE-327 | No |
| PY_MISSING_TLS_VERIFY | Python | HIGH | CWE-295 | Yes |
| PY_XXE_RISK | Python | HIGH | CWE-611 | No |
| PY_SQL_INJECTION | Python | HIGH | CWE-89 | No |
| PY_LOG_INJECTION | Python | MEDIUM | CWE-117 | No |
| PY_SILENT_EXCEPT | Python | MEDIUM | CWE-390 | Yes |
| PY_SENSITIVE_IN_RESPONSE | Python | MEDIUM | CWE-200 | No |
| PY_MISSING_INPUT_VALIDATION | Python | MEDIUM | CWE-20 | No |
| JS_PII_IN_LOG | Node.js / TypeScript | CRITICAL | CWE-532 | No |
| JS_HARDCODED_SECRET | Node.js / TypeScript | CRITICAL | CWE-798 | No |
| JS_EVAL_RISK | Node.js / TypeScript | CRITICAL | CWE-95 | No |
| JS_SSRF_RISK | Node.js / TypeScript | HIGH | CWE-918 | No |
| JS_MISSING_TLS_VERIFY | Node.js / TypeScript | HIGH | CWE-295 | No |
| JS_CMD_INJECTION | Node.js / TypeScript | HIGH | CWE-78 | No |
| JS_SQL_INJECTION | Node.js / TypeScript | HIGH | CWE-89 | No |
| JS_LOG_INJECTION | Node.js / TypeScript | MEDIUM | CWE-117 | No |
| JS_SILENT_CATCH | Node.js / TypeScript | MEDIUM | CWE-390 | No |
| JS_SENSITIVE_IN_RESPONSE | Node.js / TypeScript | MEDIUM | CWE-200 | No |
| GO_PII_IN_LOG | Go | CRITICAL | CWE-532 | No |
| GO_HARDCODED_SECRET | Go | CRITICAL | CWE-798 | No |
| GO_MISSING_TLS_VERIFY | Go | HIGH | CWE-295 | No |
| GO_CMD_INJECTION | Go | HIGH | CWE-78 | No |
| GO_WEAK_CRYPTO | Go | HIGH | CWE-327 | No |
| GO_SQL_INJECTION | Go | HIGH | CWE-89 | No |
| GO_SILENT_ERROR | Go | MEDIUM | CWE-390 | No |
| GO_LOG_INJECTION | Go | MEDIUM | CWE-117 | No |
| JAVA_PII_IN_LOG | Java / Spring | CRITICAL | CWE-532 | No |
| JAVA_HARDCODED_SECRET | Java / Spring | CRITICAL | CWE-798 | No |
| JAVA_CMD_INJECTION | Java / Spring | HIGH | CWE-78 | No |
| JAVA_MISSING_TLS_VERIFY | Java / Spring | HIGH | CWE-295 | No |
| JAVA_WEAK_CRYPTO | Java / Spring | HIGH | CWE-327 | No |
| JAVA_XXE_RISK | Java / Spring | HIGH | CWE-611 | No |
| JAVA_SQL_INJECTION | Java / Spring | HIGH | CWE-89 | No |
| JAVA_SILENT_CATCH | Java / Spring | MEDIUM | CWE-390 | No |
| JAVA_LOG_INJECTION | Java / Spring | MEDIUM | CWE-117 | No |

Detailed examples and remediation guidance:
- [rules-python.md](./rules-python.md)
- [rules-nodejs.md](./rules-nodejs.md)
- [rules-go.md](./rules-go.md)
- [rules-java-spring.md](./rules-java-spring.md)
- [cwe-reference.md](./cwe-reference.md)

---

## Python

(see [rules-python.md](./rules-python.md) for full detail)

### PY_PII_IN_LOG [CRITICAL] — CWE-532

**What it means:** Full event or sensitive object serialised directly into log statement

**Why it matters:** PII or account data can be retained in CloudWatch Logs and exported to downstream systems, creating GDPR and PCI-DSS exposure.

### PY_HARDCODED_SECRET [CRITICAL] — CWE-798

**What it means:** Possible hardcoded secret — sensitive variable name assigned a string literal

**Why it matters:** Hardcoded credentials can leak through source control, deployment bundles, or logs and are difficult to rotate safely.

### PY_EVAL_EXEC [CRITICAL] — CWE-95

**What it means:** eval() or exec() called — code injection risk if argument contains user input

**Why it matters:** Attacker-controlled expressions can execute arbitrary Python in the Lambda runtime.

### PY_SSRF_URLOPEN [HIGH] — CWE-918

**What it means:** urllib.request.urlopen() or requests call without HTTPS scheme validation

**Why it matters:** Unvalidated URLs can reach internal metadata or private services from within the Lambda VPC or AWS network plane.

### PY_INSECURE_DESERIALISE [HIGH] — CWE-502

**What it means:** Insecure deserialization: pickle.load/loads or yaml.load() without safe Loader

**Why it matters:** Pickle and unsafe YAML loaders can instantiate attacker-chosen objects and execute code paths during load.

### PY_CMD_INJECTION [HIGH] — CWE-78

**What it means:** Command injection risk: os.system/os.popen/subprocess with shell=True

**Why it matters:** Shell metacharacters can turn an operational helper into arbitrary command execution inside the Lambda runtime.

### PY_WEAK_CRYPTO [HIGH] — CWE-327

**What it means:** Weak cryptographic algorithm: MD5 or SHA-1 used — not suitable for security purposes

**Why it matters:** MD5 and SHA-1 are unsuitable for integrity or security checks and can be collided or brute-forced.

### PY_MISSING_TLS_VERIFY [HIGH] — CWE-295

**What it means:** TLS certificate verification disabled: requests called with verify=False

**Why it matters:** Disabling certificate validation allows man-in-the-middle interception or spoofing of upstream services.

### PY_XXE_RISK [HIGH] — CWE-611

**What it means:** XML parsing without XXE protection — xml.etree.ElementTree is vulnerable to XXE attacks

**Why it matters:** XML external entities can read local files or trigger SSRF-style network access during parsing.

### PY_SQL_INJECTION [HIGH] — CWE-89

**What it means:** Possible SQL injection — string formatting used to build a SQL query

**Why it matters:** Dynamic SQL construction lets attackers alter queries, exfiltrate data, or corrupt records.

### PY_LOG_INJECTION [MEDIUM] — CWE-117

**What it means:** User-controlled value logged without sanitization — potential log injection

**Why it matters:** Embedded control characters can forge log lines, break parsers, or hide malicious activity in CloudWatch.

### PY_SILENT_EXCEPT [MEDIUM] — CWE-390

**What it means:** Silent exception swallowing: except block with only 'pass' — errors are hidden

**Why it matters:** Important failures disappear, making abuse and operational defects impossible to detect or investigate.

### PY_SENSITIVE_IN_RESPONSE [MEDIUM] — CWE-200

**What it means:** Sensitive key name in function return value — may expose secrets to caller

**Why it matters:** Secrets or tokens may be returned to API callers, chained Lambdas, or audit logs.

### PY_MISSING_INPUT_VALIDATION [MEDIUM] — CWE-20

**What it means:** Event parameter used in AWS API call without format validation

**Why it matters:** Passing malformed resource identifiers to AWS APIs can cause unauthorized lookups, confusing errors, or unexpected resource access.


## Node.js / TypeScript

(see [rules-nodejs.md](./rules-nodejs.md) for full detail)

### JS_PII_IN_LOG [CRITICAL] — CWE-532

**What it means:** Full event or request body serialised directly to console.log — PII/sensitive data exposure

**Why it matters:** Customer payloads can be permanently stored in CloudWatch Logs and copied into SIEM or analytics pipelines.

### JS_HARDCODED_SECRET [CRITICAL] — CWE-798

**What it means:** Possible hardcoded secret — sensitive variable assigned a string literal

**Why it matters:** Static secrets in source or bundles can be extracted from repositories, build logs, or Lambda artifacts.

### JS_EVAL_RISK [CRITICAL] — CWE-95

**What it means:** eval() called — code injection risk

**Why it matters:** eval executes attacker-controlled JavaScript in the same process as your AWS credentials.

### JS_SSRF_RISK [HIGH] — CWE-918

**What it means:** HTTP request made with URL from event/environment without scheme validation

**Why it matters:** Attacker-supplied URLs can be used to probe internal services or metadata endpoints.

### JS_MISSING_TLS_VERIFY [HIGH] — CWE-295

**What it means:** TLS verification disabled: rejectUnauthorized: false

**Why it matters:** Trusting any certificate enables MITM interception and upstream spoofing.

### JS_CMD_INJECTION [HIGH] — CWE-78

**What it means:** Command injection risk: child_process.exec/execSync with shell interpolation

**Why it matters:** Shell interpolation lets attackers execute arbitrary commands inside the Lambda runtime.

### JS_SQL_INJECTION [HIGH] — CWE-89

**What it means:** Possible SQL injection — template literal or string concatenation used to build SQL

**Why it matters:** Attackers can alter SQL semantics, bypass filters, or dump sensitive rows.

### JS_LOG_INJECTION [MEDIUM] — CWE-117

**What it means:** User-controlled event field interpolated directly into log string

**Why it matters:** User-supplied newline characters can forge log entries or confuse downstream analysis.

### JS_SILENT_CATCH [MEDIUM] — CWE-390

**What it means:** Empty catch block — errors are silently discarded

**Why it matters:** Discarded exceptions hide abuse, retries, and partial processing failures.

### JS_SENSITIVE_IN_RESPONSE [MEDIUM] — CWE-200

**What it means:** Sensitive field name in returned object — may expose secrets to caller

**Why it matters:** Secrets can be returned to callers or logged by downstream systems.


## Go

(see [rules-go.md](./rules-go.md) for full detail)

### GO_PII_IN_LOG [CRITICAL] — CWE-532

**What it means:** Full request/event struct logged with %v or %+v — PII/sensitive data exposure

**Why it matters:** Printing full request structs can expose tokens, contact details, and request bodies in logs.

### GO_HARDCODED_SECRET [CRITICAL] — CWE-798

**What it means:** Possible hardcoded secret — sensitive variable assigned a string literal

**Why it matters:** Compiled Go binaries with embedded secrets are difficult to rotate and easy to reverse-engineer.

### GO_MISSING_TLS_VERIFY [HIGH] — CWE-295

**What it means:** TLS verification disabled: InsecureSkipVerify: true

**Why it matters:** Skipping certificate verification makes HTTPS susceptible to interception and impersonation.

### GO_CMD_INJECTION [HIGH] — CWE-78

**What it means:** Command injection risk: exec.Command with user-controlled string

**Why it matters:** Passing user-controlled values into exec.Command can execute unexpected binaries or arguments.

### GO_WEAK_CRYPTO [HIGH] — CWE-327

**What it means:** Weak cryptographic algorithm: crypto/md5 or crypto/sha1 used

**Why it matters:** Weak digests are collision-prone and unsuitable for security-sensitive identifiers or signatures.

### GO_SQL_INJECTION [HIGH] — CWE-89

**What it means:** Possible SQL injection — fmt.Sprintf used to build SQL query string

**Why it matters:** String-formatted SQL allows attackers to manipulate query structure and exfiltrate data.

### GO_SILENT_ERROR [MEDIUM] — CWE-390

**What it means:** Error silently discarded with blank identifier: _ = err

**Why it matters:** Ignoring errors hides failed writes, cleanup issues, and security control failures.

### GO_LOG_INJECTION [MEDIUM] — CWE-117

**What it means:** User-controlled value passed to log.Printf — potential log injection

**Why it matters:** Malicious log content can create forged records or break analytics pipelines.


## Java / Spring

(see [rules-java-spring.md](./rules-java-spring.md) for full detail)

### JAVA_PII_IN_LOG [CRITICAL] — CWE-532

**What it means:** Full request/event object logged with toString() or directly — PII/sensitive data exposure

**Why it matters:** Logging entire request objects or toString() output can expose tokens and personal data.

### JAVA_HARDCODED_SECRET [CRITICAL] — CWE-798

**What it means:** Possible hardcoded secret — sensitive field assigned a string literal

**Why it matters:** Embedded credentials in jars are persistent and difficult to rotate across Lambda aliases and environments.

### JAVA_CMD_INJECTION [HIGH] — CWE-78

**What it means:** Command injection risk: Runtime.exec() or ProcessBuilder with user input

**Why it matters:** Runtime.exec and ProcessBuilder can execute arbitrary commands when arguments come from the request.

### JAVA_MISSING_TLS_VERIFY [HIGH] — CWE-295

**What it means:** TLS verification disabled: TrustAllCerts or NoopHostnameVerifier in use

**Why it matters:** Trust-all TLS configuration removes endpoint authentication and enables MITM attacks.

### JAVA_WEAK_CRYPTO [HIGH] — CWE-327

**What it means:** Weak cryptographic algorithm: MD5 or SHA-1 MessageDigest in use

**Why it matters:** MD5 and SHA-1 are deprecated for security-sensitive hashing and signature workflows.

### JAVA_XXE_RISK [HIGH] — CWE-611

**What it means:** XXE risk: DocumentBuilderFactory or SAXParserFactory without XXE protection features disabled

**Why it matters:** Unsafe XML parsers can read files or trigger network requests via crafted entities.

### JAVA_SQL_INJECTION [HIGH] — CWE-89

**What it means:** Possible SQL injection — string concatenation used to build SQL query

**Why it matters:** String-built queries let attackers change WHERE clauses or execute unintended statements.

### JAVA_SILENT_CATCH [MEDIUM] — CWE-390

**What it means:** Empty catch block — exception silently swallowed

**Why it matters:** Empty catch blocks hide failures and make abuse or partial execution invisible.

### JAVA_LOG_INJECTION [MEDIUM] — CWE-117

**What it means:** User-controlled value concatenated directly into log statement

**Why it matters:** Direct concatenation of request data can forge or split log records.

---

## CVE Database References

| Database | URL | Ecosystems | Notes |
|---------|-----|-----------|-------|
| MITRE CVE | https://cve.mitre.org/ | All | Canonical CVE IDs and descriptions |
| NVD | https://nvd.nist.gov/ | All | CVSS scores, vendor advisories, CPE data |
| OSV | https://osv.dev/ | Python, Node.js, Go, Ruby, Java, Rust | Structured JSON API, all ecosystems |
| GitHub Advisory DB | https://github.com/advisories | Python, Node.js, Go, Java, Ruby | GHSA IDs, GitHub-scoped packages |
| PyPI Advisory DB | https://pypi.org/security/ | Python | Python package-specific advisories |
| npm Security Advisories | https://docs.npmjs.com/cli/v10/commands/npm-audit | Node.js | npm registry vulnerability reports |
| Go Vulnerability DB | https://vuln.go.dev/ | Go | Go module security, govulncheck integration |
| Snyk Vulnerability DB | https://security.snyk.io/ | All | Multi-ecosystem, exploitability context |
| OWASP Dep-Check | https://owasp.org/www-project-dependency-check/ | Java, .NET, Python | NVD-backed dependency scanner |

## OWASP Top 10 2021 Complete Reference

| Category | Description | URL |
|---------|-------------|-----|
| A01:2021 | Broken Access Control | https://owasp.org/Top10/A01_2021-Broken_Access_Control/ |
| A02:2021 | Cryptographic Failures | https://owasp.org/Top10/A02_2021-Cryptographic_Failures/ |
| A03:2021 | Injection | https://owasp.org/Top10/A03_2021-Injection/ |
| A04:2021 | Insecure Design | https://owasp.org/Top10/A04_2021-Insecure_Design/ |
| A05:2021 | Security Misconfiguration | https://owasp.org/Top10/A05_2021-Security_Misconfiguration/ |
| A06:2021 | Vulnerable and Outdated Components | https://owasp.org/Top10/A06_2021-Vulnerable_and_Outdated_Components/ |
| A07:2021 | Identification and Authentication Failures | https://owasp.org/Top10/A07_2021-Identification_and_Authentication_Failures/ |
| A08:2021 | Software and Data Integrity Failures | https://owasp.org/Top10/A08_2021-Software_and_Data_Integrity_Failures/ |
| A09:2021 | Security Logging and Monitoring Failures | https://owasp.org/Top10/A09_2021-Security_Logging_and_Monitoring_Failures/ |
| A10:2021 | Server-Side Request Forgery | https://owasp.org/Top10/A10_2021-Server-Side_Request_Forgery_%28SSRF%29/ |

## CWE → OWASP Mapping (this skill)

| CWE | Name | OWASP 2021 | NVD Link |
|-----|------|-----------|---------|
| CWE-20 | Improper Input Validation | A03 – Injection | https://nvd.nist.gov/vuln/search?query=CWE-20 |
| CWE-78 | OS Command Injection | A03 – Injection | https://nvd.nist.gov/vuln/search?query=CWE-78 |
| CWE-89 | SQL Injection | A03 – Injection | https://nvd.nist.gov/vuln/search?query=CWE-89 |
| CWE-95 | Eval Injection | A03 – Injection | https://nvd.nist.gov/vuln/search?query=CWE-95 |
| CWE-117 | Log Injection | A09 – Logging | https://nvd.nist.gov/vuln/search?query=CWE-117 |
| CWE-200 | Sensitive Info Exposure | A01 – Access Control | https://nvd.nist.gov/vuln/search?query=CWE-200 |
| CWE-295 | Improper Cert Validation | A02 – Crypto Failures | https://nvd.nist.gov/vuln/search?query=CWE-295 |
| CWE-327 | Broken Crypto Algorithm | A02 – Crypto Failures | https://nvd.nist.gov/vuln/search?query=CWE-327 |
| CWE-390 | Silent Error | A09 – Logging | https://nvd.nist.gov/vuln/search?query=CWE-390 |
| CWE-502 | Insecure Deserialization | A08 – Integrity Failures | https://nvd.nist.gov/vuln/search?query=CWE-502 |
| CWE-532 | PII in Logs | A09 – Logging | https://nvd.nist.gov/vuln/search?query=CWE-532 |
| CWE-611 | XXE | A05 – Misconfiguration | https://nvd.nist.gov/vuln/search?query=CWE-611 |
| CWE-798 | Hardcoded Credentials | A02 – Crypto Failures | https://nvd.nist.gov/vuln/search?query=CWE-798 |
| CWE-918 | SSRF | A10 – SSRF | https://nvd.nist.gov/vuln/search?query=CWE-918 |

## Security Standards

| Standard | Requirement | URL |
|---------|-------------|-----|
| PCI-DSS v4.0 | Req 6.3 – Secure Development | https://www.pcisecuritystandards.org/document_library/ |
| PCI-DSS v4.0 | Req 3.4 – Protect stored cardholder data | https://www.pcisecuritystandards.org/document_library/ |
| GDPR | Art. 32 – Technical security measures | https://gdpr-info.eu/art-32-gdpr/ |
| GDPR | Art. 25 – Data protection by design | https://gdpr-info.eu/art-25-gdpr/ |
| SOC 2 | CC6.1 – Logical and Physical Access Controls | https://www.aicpa.org/resources/download/soc-2-audit-reports |
| ISO 27001 | A.14.2 – Security in development | https://www.iso.org/standard/27001 |
