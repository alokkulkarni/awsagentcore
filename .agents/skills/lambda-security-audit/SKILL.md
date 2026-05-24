---
name: lambda-security-audit
description: >
  Validate AWS Lambda handlers for security vulnerabilities, CVEs, hardcoded secrets,
  PII/sensitive data exposure in logs, insecure dependencies, and OWASP/CWE-class code
  weaknesses across all supported runtimes.
  Activate when writing, reviewing, creating, or scanning Lambda functions in Python,
  Node.js, TypeScript, Go, or Java (Spring / Spring Cloud Function).
  Covers: PII/sensitive data in CloudWatch logs (CWE-532), SSRF without URL scheme
  validation (CWE-918), hardcoded secrets (CWE-798), silent exception swallowing (CWE-390),
  missing input validation (CWE-20), insecure deserialization (CWE-502), command injection
  (CWE-78), weak cryptography (CWE-327), missing TLS verification (CWE-295), XXE risk
  (CWE-611), log injection (CWE-117), eval/exec (CWE-95), SQL injection (CWE-89), and
  sensitive data in responses (CWE-200). CVE scanning via pip-audit (PyPI Advisory / NVD /
  OSV), npm audit (GitHub Advisory DB), govulncheck (Go Vulnerability DB / OSV), and
  OWASP Dependency-Check (Maven/Gradle).
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH); Node.js 18+ (node/npm in PATH); Go 1.21+ (go in PATH);
  Java 11+. pip-audit optional (pip install pip-audit). govulncheck optional
  (go install golang.org/x/vuln/cmd/govulncheck@latest). uv optional.
metadata:
  category: aws
  tags:
    - lambda
    - aws
    - security
    - sast
    - cve
    - owasp
    - cwe
    - nvd
    - osv
    - serverless
    - python
    - nodejs
    - typescript
    - go
    - java
    - spring
    - pci-dss
    - gdpr
    - secrets
    - pii
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep]
---

## Activation

Activate whenever a Lambda handler file is written, modified, reviewed, or security-audited.
Also activate when a dependency manifest is present.

| Extension | Runtime |
|-----------|---------|
| `.py` | Python |
| `.js` `.mjs` `.cjs` `.ts` | Node.js / TypeScript |
| `.go` | Go |
| `.java` | Java / Spring |
| `requirements.txt` | Python CVE scan |
| `package.json` | Node.js CVE scan |
| `go.mod` | Go CVE scan |
| `pom.xml` `build.gradle` | Java CVE scan |

## Workflow

```
1. SAST audit:   python3 scripts/audit_security.py <handler_file>
2. CVE scan:     python3 scripts/scan_deps.py <manifest_file>
3. Auto-fix:     python3 scripts/fix_security.py <handler_file> --dry-run
4. Re-audit:     python3 scripts/audit_security.py <handler_file>   # exit 0 = clean
```

## Security Rules by Runtime

### Python (AST-based)

| Rule ID | Severity | CWE | OWASP 2021 | Auto-fix |
|---------|----------|-----|-----------|---------|
| PY_PII_IN_LOG | CRITICAL | CWE-532 | A09 – Logging Failures | No |
| PY_HARDCODED_SECRET | CRITICAL | CWE-798 | A02 – Crypto Failures | No |
| PY_EVAL_EXEC | CRITICAL | CWE-95 | A03 – Injection | No |
| PY_SSRF_URLOPEN | HIGH | CWE-918 | A10 – SSRF | Yes |
| PY_INSECURE_DESERIALISE | HIGH | CWE-502 | A08 – Integrity Failures | No |
| PY_CMD_INJECTION | HIGH | CWE-78 | A03 – Injection | No |
| PY_WEAK_CRYPTO | HIGH | CWE-327 | A02 – Crypto Failures | No |
| PY_MISSING_TLS_VERIFY | HIGH | CWE-295 | A02 – Crypto Failures | Yes |
| PY_XXE_RISK | HIGH | CWE-611 | A05 – Misconfiguration | No |
| PY_SQL_INJECTION | HIGH | CWE-89 | A03 – Injection | No |
| PY_LOG_INJECTION | MEDIUM | CWE-117 | A09 – Logging Failures | No |
| PY_SILENT_EXCEPT | MEDIUM | CWE-390 | A09 – Logging Failures | Yes |
| PY_SENSITIVE_IN_RESPONSE | MEDIUM | CWE-200 | A01 – Broken Access Control | No |
| PY_MISSING_INPUT_VALIDATION | MEDIUM | CWE-20 | A03 – Injection | No |

### Node.js / TypeScript (regex-based)

| Rule ID | Severity | CWE | OWASP 2021 | Auto-fix |
|---------|----------|-----|-----------|---------|
| JS_PII_IN_LOG | CRITICAL | CWE-532 | A09 – Logging Failures | No |
| JS_HARDCODED_SECRET | CRITICAL | CWE-798 | A02 – Crypto Failures | No |
| JS_EVAL_RISK | CRITICAL | CWE-95 | A03 – Injection | No |
| JS_SSRF_RISK | HIGH | CWE-918 | A10 – SSRF | No |
| JS_MISSING_TLS_VERIFY | HIGH | CWE-295 | A02 – Crypto Failures | No |
| JS_CMD_INJECTION | HIGH | CWE-78 | A03 – Injection | No |
| JS_SQL_INJECTION | HIGH | CWE-89 | A03 – Injection | No |
| JS_LOG_INJECTION | MEDIUM | CWE-117 | A09 – Logging Failures | No |
| JS_SILENT_CATCH | MEDIUM | CWE-390 | A09 – Logging Failures | No |
| JS_SENSITIVE_IN_RESPONSE | MEDIUM | CWE-200 | A01 – Broken Access Control | No |

### Go (regex-based)

| Rule ID | Severity | CWE | OWASP 2021 | Auto-fix |
|---------|----------|-----|-----------|---------|
| GO_PII_IN_LOG | CRITICAL | CWE-532 | A09 – Logging Failures | No |
| GO_HARDCODED_SECRET | CRITICAL | CWE-798 | A02 – Crypto Failures | No |
| GO_MISSING_TLS_VERIFY | HIGH | CWE-295 | A02 – Crypto Failures | No |
| GO_CMD_INJECTION | HIGH | CWE-78 | A03 – Injection | No |
| GO_WEAK_CRYPTO | HIGH | CWE-327 | A02 – Crypto Failures | No |
| GO_SQL_INJECTION | HIGH | CWE-89 | A03 – Injection | No |
| GO_SILENT_ERROR | MEDIUM | CWE-390 | A09 – Logging Failures | No |
| GO_LOG_INJECTION | MEDIUM | CWE-117 | A09 – Logging Failures | No |

### Java / Spring (regex-based)

| Rule ID | Severity | CWE | OWASP 2021 | Auto-fix |
|---------|----------|-----|-----------|---------|
| JAVA_PII_IN_LOG | CRITICAL | CWE-532 | A09 – Logging Failures | No |
| JAVA_HARDCODED_SECRET | CRITICAL | CWE-798 | A02 – Crypto Failures | No |
| JAVA_CMD_INJECTION | HIGH | CWE-78 | A03 – Injection | No |
| JAVA_MISSING_TLS_VERIFY | HIGH | CWE-295 | A02 – Crypto Failures | No |
| JAVA_WEAK_CRYPTO | HIGH | CWE-327 | A02 – Crypto Failures | No |
| JAVA_XXE_RISK | HIGH | CWE-611 | A05 – Misconfiguration | No |
| JAVA_SQL_INJECTION | HIGH | CWE-89 | A03 – Injection | No |
| JAVA_SILENT_CATCH | MEDIUM | CWE-390 | A09 – Logging Failures | No |
| JAVA_LOG_INJECTION | MEDIUM | CWE-117 | A09 – Logging Failures | No |

## Standard Secure Patterns

### Python — Redact PII before logging
```python
_REDACT_KEYS = frozenset({
    "date_of_birth", "dob", "mobile", "phone", "password", "pin", "otp",
    "cvv", "card_number", "account_number", "secret", "token", "auth_token",
})
def _redact_event(event: dict) -> dict:
    return {k: "***REDACTED***" if k.lower() in _REDACT_KEYS else v
            for k, v in event.items()}
logger.info("handler invoked: %s", json.dumps(_redact_event(event)))
```

### Python — SSRF-safe URL validation
```python
from urllib.parse import urlparse
_parsed = urlparse(ENDPOINT_URL)
if _parsed.scheme != "https" or not _parsed.netloc:
    raise ValueError(f"URL must be HTTPS, got: {ENDPOINT_URL!r}")
```

### Node.js — Redact before logging
```javascript
const REDACT_KEYS = new Set(['password','pin','cvv','cardNumber','accountNumber','dob','token','secret']);
const redactEvent = (e) => Object.fromEntries(
  Object.entries(e).map(([k,v]) => [k, REDACT_KEYS.has(k) ? '***REDACTED***' : v])
);
console.log(JSON.stringify({ handler: 'invoked', params: redactEvent(event) }));
```

### Java — Disable XXE on DocumentBuilderFactory
```java
DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
dbf.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
dbf.setFeature("http://xml.org/sax/features/external-general-entities", false);
dbf.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
dbf.setExpandEntityReferences(false);
```

## OWASP Top 10 2021 Reference

| # | Category | Relevant CWEs |
|---|----------|--------------|
| A01 | Broken Access Control | CWE-200 |
| A02 | Cryptographic Failures | CWE-295, CWE-327, CWE-798 |
| A03 | Injection | CWE-20, CWE-78, CWE-89, CWE-95 |
| A05 | Security Misconfiguration | CWE-611 |
| A08 | Software and Data Integrity Failures | CWE-502 |
| A09 | Security Logging and Monitoring Failures | CWE-117, CWE-390, CWE-532 |
| A10 | Server-Side Request Forgery | CWE-918 |

## CVE Database References

| Database | URL | Best For |
|---------|-----|---------|
| MITRE CVE | https://cve.mitre.org/ | Canonical CVE IDs |
| NVD | https://nvd.nist.gov/ | CVSS scores, vendor advisories |
| OSV | https://osv.dev/ | Open-source package vulns (all ecosystems) |
| GitHub Advisory DB | https://github.com/advisories | GHSA IDs, GitHub-hosted packages |
| PyPI Advisory DB | https://pypi.org/security/ | Python package vulns |
| npm Advisory DB | https://docs.npmjs.com/cli/v10/commands/npm-audit | Node.js package vulns |
| Go Vulnerability DB | https://vuln.go.dev/ | Go module vulns |
| Snyk Vulnerability DB | https://security.snyk.io/ | Multi-ecosystem, exploitability context |

## Security Standards & Frameworks

| Standard | Relevance | URL |
|---------|-----------|-----|
| OWASP Top 10 2021 | Application security baseline | https://owasp.org/www-project-top-ten/ |
| OWASP Serverless Top 10 | Lambda-specific risks | https://owasp.org/www-project-serverless-top-10/ |
| OWASP ASVS v4.0 | Verification standard | https://owasp.org/www-project-application-security-verification-standard/ |
| OWASP Cheat Sheets | Implementation guidance | https://cheatsheetseries.owasp.org/ |
| CWE Top 25 (2023) | Most dangerous weaknesses | https://cwe.mitre.org/top25/archive/2023/2023_top25_list.html |
| PCI-DSS v4.0 Req 6.3 | Secure dev for cardholder data | https://www.pcisecuritystandards.org/document_library/ |
| GDPR Article 32 | Data security obligations | https://gdpr-info.eu/art-32-gdpr/ |
| AWS Lambda Security | AWS-official security guidance | https://docs.aws.amazon.com/lambda/latest/dg/lambda-security.html |
| AWS Secrets Manager | Credential management | https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html |
