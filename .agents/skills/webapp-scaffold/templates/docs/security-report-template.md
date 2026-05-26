# Security Audit Report — {{PROJECT_NAME}}

**Report Date:** {{DATE}}
**Auditor:** {{AUDITOR}}
**Version:** {{VERSION}}
**Status:** [CLEAN | WARNINGS | ACTION REQUIRED]

## Executive Summary
...

## Vulnerability Summary
| Severity | Total Found | Fixed | Accepted Risk | Remaining |
...

## Critical & High Findings
### Finding #N — {{CVE_ID}}
- **Package:** 
- **Affected Versions:**
- **CVSS Score:**
- **OWASP Category:**
- **CWE:** 
- **Dependency Path:**
- **Remediation:**
- **Status:**

## Transitive Dependency Analysis
...

## OWASP Top 10 Coverage
| Category | Status | Notes |
...

## Compliance Checklist
- [ ] npm audit passes (exit 0)
- [ ] No wildcard versions in package.json
- [ ] SRI hashes on CDN scripts
- [ ] CSP header in place
- [ ] HTTPS enforced
- [ ] Secrets not in source
- [ ] .env not committed

## Sign-off
