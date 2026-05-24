# CWE Reference

| Rule ID | CWE | CWE Name | OWASP Top 10 2021 | CVSS Base Score Range | OWASP Cheat Sheet | Brief description |
|---------|-----|----------|-------------------|-----------------------|-------------------|------------------|
| PY_PII_IN_LOG | CWE-532 | Insertion of Sensitive Information into Log File | A09: Security Logging and Monitoring Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | PII or account data can be retained in CloudWatch Logs and exported to downstream systems, creating GDPR and PCI-DSS exposure. |
| PY_HARDCODED_SECRET | CWE-798 | Use of Hard-coded Credentials | A07: Identification and Authentication Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html | Hardcoded credentials can leak through source control, deployment bundles, or logs and are difficult to rotate safely. |
| PY_EVAL_EXEC | CWE-95 | Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection') | A03: Injection | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html | Attacker-controlled expressions can execute arbitrary Python in the Lambda runtime. |
| PY_SSRF_URLOPEN | CWE-918 | Server-Side Request Forgery (SSRF) | A10: Server-Side Request Forgery | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html | Unvalidated URLs can reach internal metadata or private services from within the Lambda VPC or AWS network plane. |
| PY_INSECURE_DESERIALISE | CWE-502 | Deserialization of Untrusted Data | A08: Software and Data Integrity Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Deserialization_Cheat_Sheet.html | Pickle and unsafe YAML loaders can instantiate attacker-chosen objects and execute code paths during load. |
| PY_CMD_INJECTION | CWE-78 | OS Command Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html | Shell metacharacters can turn an operational helper into arbitrary command execution inside the Lambda runtime. |
| PY_WEAK_CRYPTO | CWE-327 | Use of a Broken or Risky Cryptographic Algorithm | A02: Cryptographic Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html | MD5 and SHA-1 are unsuitable for integrity or security checks and can be collided or brute-forced. |
| PY_MISSING_TLS_VERIFY | CWE-295 | Improper Certificate Validation | A02: Cryptographic Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html | Disabling certificate validation allows man-in-the-middle interception or spoofing of upstream services. |
| PY_XXE_RISK | CWE-611 | Improper Restriction of XML External Entity Reference | A05: Security Misconfiguration | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html | XML external entities can read local files or trigger SSRF-style network access during parsing. |
| PY_SQL_INJECTION | CWE-89 | SQL Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html | Dynamic SQL construction lets attackers alter queries, exfiltrate data, or corrupt records. |
| PY_LOG_INJECTION | CWE-117 | Improper Output Neutralization for Logs | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Embedded control characters can forge log lines, break parsers, or hide malicious activity in CloudWatch. |
| PY_SILENT_EXCEPT | CWE-390 | Detection of Error Condition Without Action | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Important failures disappear, making abuse and operational defects impossible to detect or investigate. |
| PY_SENSITIVE_IN_RESPONSE | CWE-200 | Exposure of Sensitive Information to an Unauthorized Actor | A01: Broken Access Control | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/User_Privacy_Protection_Cheat_Sheet.html | Secrets or tokens may be returned to API callers, chained Lambdas, or audit logs. |
| PY_MISSING_INPUT_VALIDATION | CWE-20 | Improper Input Validation | A04: Insecure Design | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html | Passing malformed resource identifiers to AWS APIs can cause unauthorized lookups, confusing errors, or unexpected resource access. |
| JS_PII_IN_LOG | CWE-532 | Insertion of Sensitive Information into Log File | A09: Security Logging and Monitoring Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Customer payloads can be permanently stored in CloudWatch Logs and copied into SIEM or analytics pipelines. |
| JS_HARDCODED_SECRET | CWE-798 | Use of Hard-coded Credentials | A07: Identification and Authentication Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html | Static secrets in source or bundles can be extracted from repositories, build logs, or Lambda artifacts. |
| JS_EVAL_RISK | CWE-95 | Improper Neutralization of Directives in Dynamically Evaluated Code ('Eval Injection') | A03: Injection | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html | eval executes attacker-controlled JavaScript in the same process as your AWS credentials. |
| JS_SSRF_RISK | CWE-918 | Server-Side Request Forgery (SSRF) | A10: Server-Side Request Forgery | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html | Attacker-supplied URLs can be used to probe internal services or metadata endpoints. |
| JS_MISSING_TLS_VERIFY | CWE-295 | Improper Certificate Validation | A02: Cryptographic Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html | Trusting any certificate enables MITM interception and upstream spoofing. |
| JS_CMD_INJECTION | CWE-78 | OS Command Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html | Shell interpolation lets attackers execute arbitrary commands inside the Lambda runtime. |
| JS_SQL_INJECTION | CWE-89 | SQL Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html | Attackers can alter SQL semantics, bypass filters, or dump sensitive rows. |
| JS_LOG_INJECTION | CWE-117 | Improper Output Neutralization for Logs | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | User-supplied newline characters can forge log entries or confuse downstream analysis. |
| JS_SILENT_CATCH | CWE-390 | Detection of Error Condition Without Action | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Discarded exceptions hide abuse, retries, and partial processing failures. |
| JS_SENSITIVE_IN_RESPONSE | CWE-200 | Exposure of Sensitive Information to an Unauthorized Actor | A01: Broken Access Control | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/User_Privacy_Protection_Cheat_Sheet.html | Secrets can be returned to callers or logged by downstream systems. |
| GO_PII_IN_LOG | CWE-532 | Insertion of Sensitive Information into Log File | A09: Security Logging and Monitoring Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Printing full request structs can expose tokens, contact details, and request bodies in logs. |
| GO_HARDCODED_SECRET | CWE-798 | Use of Hard-coded Credentials | A07: Identification and Authentication Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html | Compiled Go binaries with embedded secrets are difficult to rotate and easy to reverse-engineer. |
| GO_MISSING_TLS_VERIFY | CWE-295 | Improper Certificate Validation | A02: Cryptographic Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html | Skipping certificate verification makes HTTPS susceptible to interception and impersonation. |
| GO_CMD_INJECTION | CWE-78 | OS Command Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html | Passing user-controlled values into exec.Command can execute unexpected binaries or arguments. |
| GO_WEAK_CRYPTO | CWE-327 | Use of a Broken or Risky Cryptographic Algorithm | A02: Cryptographic Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html | Weak digests are collision-prone and unsuitable for security-sensitive identifiers or signatures. |
| GO_SQL_INJECTION | CWE-89 | SQL Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html | String-formatted SQL allows attackers to manipulate query structure and exfiltrate data. |
| GO_SILENT_ERROR | CWE-390 | Detection of Error Condition Without Action | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Ignoring errors hides failed writes, cleanup issues, and security control failures. |
| GO_LOG_INJECTION | CWE-117 | Improper Output Neutralization for Logs | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Malicious log content can create forged records or break analytics pipelines. |
| JAVA_PII_IN_LOG | CWE-532 | Insertion of Sensitive Information into Log File | A09: Security Logging and Monitoring Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Logging entire request objects or toString() output can expose tokens and personal data. |
| JAVA_HARDCODED_SECRET | CWE-798 | Use of Hard-coded Credentials | A07: Identification and Authentication Failures | 8.0-10.0 | https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html | Embedded credentials in jars are persistent and difficult to rotate across Lambda aliases and environments. |
| JAVA_CMD_INJECTION | CWE-78 | OS Command Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html | Runtime.exec and ProcessBuilder can execute arbitrary commands when arguments come from the request. |
| JAVA_MISSING_TLS_VERIFY | CWE-295 | Improper Certificate Validation | A02: Cryptographic Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html | Trust-all TLS configuration removes endpoint authentication and enables MITM attacks. |
| JAVA_WEAK_CRYPTO | CWE-327 | Use of a Broken or Risky Cryptographic Algorithm | A02: Cryptographic Failures | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html | MD5 and SHA-1 are deprecated for security-sensitive hashing and signature workflows. |
| JAVA_XXE_RISK | CWE-611 | Improper Restriction of XML External Entity Reference | A05: Security Misconfiguration | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/XML_External_Entity_Prevention_Cheat_Sheet.html | Unsafe XML parsers can read files or trigger network requests via crafted entities. |
| JAVA_SQL_INJECTION | CWE-89 | SQL Injection | A03: Injection | 7.0-8.9 | https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html | String-built queries let attackers change WHERE clauses or execute unintended statements. |
| JAVA_SILENT_CATCH | CWE-390 | Detection of Error Condition Without Action | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Empty catch blocks hide failures and make abuse or partial execution invisible. |
| JAVA_LOG_INJECTION | CWE-117 | Improper Output Neutralization for Logs | A09: Security Logging and Monitoring Failures | 4.0-6.9 | https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html | Direct concatenation of request data can forge or split log records. |

---

## CVE Database Quick Links

| Database | URL |
|---------|-----|
| NVD — search by CWE | https://nvd.nist.gov/vuln/search |
| MITRE CVE | https://cve.mitre.org/ |
| OSV | https://osv.dev/ |
| GitHub Advisory DB | https://github.com/advisories |
| Snyk Vulnerability DB | https://security.snyk.io/ |

## NVD CVSS Severity Scale

| Severity | CVSS Base Score | Typical Impact |
|---------|-----------------|---------------|
| CRITICAL | 9.0–10.0 | Remote code execution, full data compromise |
| HIGH | 7.0–8.9 | Significant data exposure or partial RCE |
| MEDIUM | 4.0–6.9 | Limited data exposure, requires privileges |
| LOW | 0.1–3.9 | Minor information leakage, low exploitability |
| None | 0.0 | No security impact |

Reference: https://nvd.nist.gov/vuln-metrics/cvss

## OWASP Serverless Top 10

Lambda-specific risks beyond OWASP Top 10:
https://owasp.org/www-project-serverless-top-10/

| # | Risk |
|---|------|
| SAS-1 | Function Event Data Injection |
| SAS-2 | Broken Authentication |
| SAS-3 | Insecure Serverless Deployment Configuration |
| SAS-4 | Over-Privileged Function Permissions and Roles |
| SAS-5 | Inadequate Function Monitoring and Logging |
| SAS-6 | Insecure 3rd Party Dependencies |
| SAS-7 | Insecure Application Secrets Storage |
| SAS-8 | Denial of Service & Financial Resource Exhaustion |
| SAS-9 | Serverless Business Logic Manipulation |
| SAS-10 | Improper Exception Handling and Verbose Error Messages |
