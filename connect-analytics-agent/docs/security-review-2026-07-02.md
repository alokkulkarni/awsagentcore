# Security Review — Connect Analytics Agent (2026-07-02)

Full-codebase review covering the cloud deployment (`deploy.sh deploy`: API Gateway, Cognito,
Lambda, S3/CloudFront, IAM, AgentCore Gateway) and the local deployment
(`deploy.sh local`: Docker Compose, FastAPI, Vite). SAST via lambda-security-audit
(OWASP/CWE ruleset), dependency CVE scans via pip-audit and npm audit, plus manual review of
deploy.sh, IAM policies, Docker, and the React frontend.

## Fixed findings

| # | Severity | Finding | CWE | Fix |
|---|----------|---------|-----|-----|
| 1 | CRITICAL | API Gateway deployed with `--authorization-type NONE` on all methods; Cognito pool existed but no authorizer was attached — `/api/query` (Bedrock + Connect PII) was publicly callable | CWE-306 | `deploy.sh`: Cognito user-pool authorizer created and attached to `POST /api/query` and `GET /api/metrics` (`/api/health` stays open). Default `API_AUTH=cognito`; `API_AUTH=none` opt-out prints a loud warning. Cognito now deploys before API Gateway. |
| 2 | CRITICAL | `tools/force_logout/handler.py` logged the full Lambda event object on error (PII → CloudWatch) | CWE-532 | Log a static message only; no event payload in logs. |
| 3 | HIGH | Agent IAM role: `lambda:InvokeFunction` on `Resource:*` (lateral movement to any Lambda in the account) | CWE-732 | Scoped to `arn:aws:lambda:*:*:function:connect-analytics-*`; `logs:*` also reduced to the five needed actions. |
| 4 | HIGH | Tool IAM role: `s3:GetObject` on `Resource:*` (could presign any object in any bucket) | CWE-732 | Scoped to `arn:aws:s3:::amazon-connect-*/*` (default Connect recording buckets — adjust if you use a custom recordings bucket). |
| 5 | HIGH | `vite@7.3.3` vulnerable (GHSA-fx2h-pf6j-xcff `server.fs.deny` bypass + launch-editor advisory) | CWE-22 | Bumped to `^7.3.5`; `npm audit` now reports 0 vulnerabilities. |
| 6 | MEDIUM | Frontend served from a public S3 *website* bucket (Block Public Access disabled, `Principal:"*"` policy) with CloudFront fetching over plain HTTP; bucket URL bypassed CloudFront entirely | CWE-319 | Rewrote hosting to the S3 REST endpoint + CloudFront **Origin Access Control**: Block Public Access fully ON, bucket policy allows only `cloudfront.amazonaws.com` with a `AWS:SourceArn` condition, HTTPS to origin. Existing distributions print a warning to teardown/redeploy for OAC. |
| 7 | MEDIUM | Cognito app client allowed `ALLOW_USER_PASSWORD_AUTH`; no password policy on the pool | CWE-521 | SRP-only auth flows; 12-char password policy (upper/lower/number/symbol). |
| 8 | MEDIUM | Docker published the unauthenticated agent API (8100) and dev server (5274) on `0.0.0.0` — LAN-reachable, with live AWS creds mounted | CWE-306/668 | Compose ports now bind `127.0.0.1` only. |
| 9 | MEDIUM | Vite dev server: `allowedHosts: true` disabled Host-header (DNS-rebinding) protection; listened on all interfaces | CWE-346 | Explicit `allowedHosts: ['localhost','127.0.0.1']`; binds localhost by default (container passes `--host 0.0.0.0` on the CLI where it is needed). |
| 10 | MEDIUM | Transitive npm vulns: `form-data` CRLF injection, `protobufjs` DoS, `esbuild`/`@babel/core` dev advisories | CWE-93/674 | `npm update` of affected chains; lockfile refreshed; audit clean. |
| 11 | MEDIUM | `search_contacts` passed `contact_id` to `describe_contact` without format validation | CWE-20 | UUID regex validation, 400 on mismatch (same pattern as `recording_url`). |
| 12 | MEDIUM | 24 silent `except: pass` blocks across agent modules and tool handlers hid operational/security errors | CWE-390 | All now log the suppressed exception at debug level. |
| 13 | LOW | `agent/handler.py` fell back to `Access-Control-Allow-Origin: "null"` (spoofable by sandboxed iframes); accepted arbitrary `session_id` and unbounded `message` | CWE-346/20 | Header omitted when `ALLOWED_ORIGIN` unset; `session_id` must match `[A-Za-z0-9_-]{1,64}` or a fresh UUID is issued; message capped at 4000 chars. |
| 14 | LOW | `.deploy-state.json`, `agent/deploy-state.json`, `agent/data/discovered_resources.json` tracked in git with real AWS account/instance IDs; no `.gitignore` | CWE-200 | Untracked (files kept on disk) and `.gitignore` added covering state, env, build artifacts. |
| 15 | LOW | Both containers ran as root; agent container mounted host AWS creds at `/root/.aws` | CWE-250 | Agent runs as `appuser` (uid 10001, creds mount moved to `/home/appuser/.aws`), frontend runs as `node`. |

Dependency scans: `pip-audit` on `agent/requirements.txt` — no known CVEs. `npm audit` — 0 vulnerabilities after updates.

## Verified clean

No XSS sinks (`dangerouslySetInnerHTML`/`innerHTML`/`eval` absent); all five ReactMarkdown
usages pass `rehypeSanitize`; no hardcoded credentials anywhere; IAM trust policies correctly
scoped; CCP iframe URL not attacker-controlled; deploy.sh temp files use `mktemp` and no
`curl|bash`; FastAPI local server already had CORS allow-list, security headers, and rate
limiting; `recording_url` validates contact IDs and caps presign expiry at 12 h.

## Operational notes after these fixes

- **Cloud chat now requires a Cognito JWT.** Create users in the pool and send
  `Authorization: Bearer <IdToken>`; the SPA reads the token from
  `localStorage['connect.analytics.jwt']` but has no login UI yet (see follow-ups).
  For throwaway demos: `API_AUTH=none ./deploy.sh deploy`.
- **Existing local volumes:** the agent container now runs as non-root; if an `agent_data`
  volume was created by an older root container, run `docker compose down -v` once.
- **Custom recording buckets:** widen `ConnectRecordingsBucketAccess` in
  `infrastructure/iam/lambda-tools-policy.json` if recordings are not in an
  `amazon-connect-*` bucket.
- **Pre-existing CloudFront distributions** keep the old public-website origin until
  torn down and redeployed.

## Recommended follow-ups (not fixed — design-level)

1. **SPA login flow** (Amplify/`amazon-cognito-identity-js`) so cloud mode is usable with the
   new authorizer; store tokens in memory or httpOnly cookies rather than `localStorage` (CWE-922).
2. **Per-user session ownership**: `session_store` is keyed by `session_id` alone — any
   authenticated caller can list/read/delete any session (CWE-639). Partition by Cognito `sub`.
3. **WAF / usage plan** on API Gateway to bound Bedrock spend even for authenticated users.
4. **Pin Python dependencies** (ranges like `boto3>=1.35.0` are unpinned; generate a lock/constraints file).
5. **Scope Bedrock `InvokeModel`** to the specific model/inference-profile ARNs in use.
