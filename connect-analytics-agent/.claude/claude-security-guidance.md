# Security Guidance — Connect Analytics Agent

Rules for anyone (human or AI agent) working in this repo. Full audit trail: `docs/security-review-2026-07-02.md`.

## 1. Never commit or disclose sensitive information (top priority)
- **Never commit**: AWS account IDs, Connect instance/queue IDs, ARNs, `.env`, `.deploy-state.json`, `agent/deploy-state.json`, `agent/data/*.json`, Cognito IDs, JWTs, presigned URLs, `sessions.db`. These are ignored via `.gitignore` — keep them ignored.
- **Never paste** the above into chat, PRs, commit messages, logs, screenshots, or diagrams. Redact to placeholders (`<ACCOUNT_ID>`, `<INSTANCE_ID>`).
- Secrets come only from env vars / AWS Secrets Manager at runtime — never hardcode them in code, `deploy.sh`, IAM JSON, or config.
- Before every commit: `git diff --cached` and confirm no secret, PII, or real identifier is staged.

## 2. Customer data / PII (this is a contact-centre app)
- Transcripts, recordings, contact attributes, phone numbers, and CTRs are **customer PII**. Treat as confidential; never log full events or PII (CWE-532) — redact before `logger`/`console`.
- Recording URLs are presigned with a short TTL (≤12h) — never persist or share them.
- Only expose PII to authenticated, authorised callers; never in error messages or client responses.

## 3. Authentication & authorisation
- Cloud API must stay behind the Cognito JWT authorizer (`API_AUTH=cognito`, the default). Never ship `API_AUTH=none` to a real environment.
- Cognito: SRP-only auth flow, ≥12-char password policy. Do not re-enable `ALLOW_USER_PASSWORD_AUTH`.
- Validate/scope every request; do not trust client-supplied instance/queue IDs blindly.

## 4. Least privilege (IAM)
- No wildcard `Action:*`/`Resource:*`. Scope Lambda invoke to `connect-analytics-*`, S3 reads to the recordings bucket, logs to needed actions. Never add `iam:PassRole` with `*`.
- Frontend S3 bucket stays private behind CloudFront OAC (Block Public Access ON).

## 5. Input validation & injection
- Validate IDs (UUID regex) before AWS SDK calls; cap message/body sizes; reject null bytes.
- No `eval`/`Function`/`dangerouslySetInnerHTML`; render markdown only with `rehypeSanitize`.
- Never build shell/SQL/log strings from unsanitised input (CWE-78/89/117).

## 6. Local / Docker
- Publish container ports on `127.0.0.1` only (unauthenticated FastAPI must not be LAN-reachable). Run containers as non-root; mount `~/.aws` read-only.
- Keep Vite `allowedHosts` explicit; do not bind dev servers to `0.0.0.0` outside the container.

## 7. Dependencies & verification (before merge)
- `npm audit` and `pip-audit` must be clean (0 high/critical). Do not run `npm audit fix --force` blindly.
- Run `lambda-security-audit` (SAST) on changed Python; resolve all CRITICAL/HIGH. Use `/security-review` on the branch diff.
- Handle every exception — no silent `except: pass` (log at least at debug, CWE-390).

## 8. Secure defaults
- HTTPS/TLS everywhere; keep security headers (CSP, HSTS, X-Content-Type-Options, X-Frame-Options).
- Prefer in-memory or httpOnly cookies for tokens over `localStorage`.
- When in doubt, fail closed and ask before weakening any control above.
