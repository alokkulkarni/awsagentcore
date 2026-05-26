# Webapp Scaffold Validation Rules

This reference defines the WAP and SEC rules used by `validate_webapp.py` and expected by the scaffolded output.

## Severity model

- **CRITICAL** — security, runtime compatibility, or deployment control missing.
- **HIGH** — strong production readiness or accessibility issue.
- **MEDIUM** — quality issue that should be corrected before launch.
- **LOW** — advisory issue that improves maintainability and polish.

## Rule index

| Rule ID | Severity | Summary |
| --- | --- | --- |
| WAP-001 | HIGH | CSS custom properties must define and drive brand colours. |
| WAP-002 | CRITICAL | Chat widget credentials must come from env/runtime config. |
| WAP-003 | CRITICAL | `index.html` must include a CSP meta tag when a chat widget is enabled. |
| WAP-004 | HIGH | `ChatWidget.jsx` must clean up widget observers/listeners. |
| WAP-005 | CRITICAL | `vite.config.js` must define `global: 'globalThis'`. |
| WAP-006 | HIGH | Interactive colours must satisfy WCAG 2.1 AA contrast expectations. |
| WAP-007 | HIGH | `dist/` must be gitignored; build artefacts stay out of git. |
| WAP-008 | MEDIUM | Scaffolded `package.json` version remains `1.0.0`. |
| WAP-009 | HIGH | CloudFront guidance must enforce HTTPS redirect. |
| WAP-010 | HIGH | No inline event handlers in generated markup. |
| WAP-011 | HIGH | Images need `alt`; decorative SVGs need `aria-hidden="true"`. |
| WAP-012 | MEDIUM | `.app` must use `min-height: 100vh`. |
| WAP-013 | LOW | `public/favicon.svg` must exist. |
| WAP-014 | HIGH | Vite dev and preview must bind `host: true`. |
| WAP-015 | HIGH | CSS must include 640/768/1024/1280 responsive breakpoints. |
| WAP-016 | HIGH | Touch targets must be at least 44×44px. |
| WAP-017 | MEDIUM | `package.json` must include `test`, `test:coverage`, `test:e2e`, and `audit`. |
| WAP-018 | HIGH | Vitest coverage thresholds must be ≥80% in all four categories. |
| WAP-019 | HIGH | Playwright config must include Pixel 7, iPhone 14, and iPad projects. |
| WAP-020 | MEDIUM | Vite build target must be `es2020` or newer. |
| WAP-021 | HIGH | Production builds must disable sourcemaps. |
| WAP-022 | MEDIUM | Vite must split `vendor` chunks from app code. |
| SEC-001 | CRITICAL | No CRITICAL/HIGH npm vulnerabilities may remain before production build. |
| SEC-002 | HIGH | `package-lock.json` must exist and be committed. |
| SEC-003 | HIGH | No wildcard or loose greater-than dependency ranges in `package.json`. |
| SEC-004 | HIGH | External scripts must use SRI and `crossorigin`. |
| SEC-005 | CRITICAL | `npm audit --audit-level=high` must exit 0 before release. |
| SEC-006 | CRITICAL | No `eval()`, `new Function()`, or `setTimeout(string)` in source. |
| SEC-007 | CRITICAL | No `dangerouslySetInnerHTML` in React source. |
| SEC-008 | HIGH | All `VITE_*` vars used in source must be documented in `.env.example`. |
| SEC-009 | HIGH | HTTP security headers must be set in nginx/edge config. |
| SEC-010 | HIGH | No secrets, tokens, or API keys may be committed. |

## WAP-001 — CSS custom properties must define and drive brand colours

**Severity:** HIGH

**Description:** Brand, accent, and background colours must be declared as CSS custom properties and consumed through `var(...)` in component styles.

### ✅ PASS example
```css
:root {
  --brand: #0D2A66;
  --accent: #E63012;
}

.btn-primary {
  background: var(--brand);
  color: var(--on-brand);
}
```

### ❌ FAIL example
```css
.btn-primary {
  background: #0D2A66;
  color: #ffffff;
}
```

## WAP-002 — Chat widget credentials must come from env/runtime config

**Severity:** CRITICAL

**Description:** Provider credentials such as snippet IDs, app IDs, and widget keys must not be hardcoded as the only source of truth; they must come from env vars or runtime config.

### ✅ PASS example
```js
const chatConfig = JSON.parse(import.meta.env.VITE_CHAT_CONFIG || fallbackConfig);
```

### ❌ FAIL example
```js
const chatConfig = { app_id: 'real-intercom-app-id' };
```

## WAP-003 — index.html must include a CSP meta tag when chat is enabled

**Severity:** CRITICAL

**Description:** The app shell must ship with a restrictive CSP. If a third-party chat widget is enabled, the CSP must allow local assets plus the widget script origin.

### ✅ PASS example
```html
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' https://widget.intercom.io; connect-src 'self' https://widget.intercom.io; img-src 'self' data:; style-src 'self' 'unsafe-inline';">
```

### ❌ FAIL example
```html
<head>
  <title>No CSP present</title>
</head>
```

## WAP-004 — ChatWidget.jsx must clean up widget observers/listeners

**Severity:** HIGH

**Description:** The chat helper component must clean up observers, listeners, and any temporary runtime hooks during unmount.

### ✅ PASS example
```jsx
useEffect(() => {
  const observer = new MutationObserver(() => renameNodes());
  observer.observe(document.body, { subtree: true, childList: true });
  return () => observer.disconnect();
}, []);
```

### ❌ FAIL example
```jsx
useEffect(() => {
  window.addEventListener('resize', handleResize);
}, []);
```

## WAP-005 — vite.config.js must define globalThis compatibility

**Severity:** CRITICAL

**Description:** Some third-party widget SDKs expect a browser-global `global` binding; Vite must map it to `globalThis`.

### ✅ PASS example
```js
define: {
  global: 'globalThis',
}
```

### ❌ FAIL example
```js
export default defineConfig({
  plugins: [react()],
});
```

## WAP-006 — Interactive colours must satisfy WCAG 2.1 AA contrast expectations

**Severity:** HIGH

**Description:** Buttons, nav links, and CTA surfaces must use accessible foreground/background combinations.

### ✅ PASS example
```css
:root {
  --brand: #0D2A66;
  --on-brand: #ffffff;
}
```

### ❌ FAIL example
```css
:root {
  --brand: #c7d4ff;
  --on-brand: #ffffff;
}
```

## WAP-007 — dist/ must be gitignored

**Severity:** HIGH

**Description:** Build output belongs in `dist/` and must be excluded from git.

### ✅ PASS example
```gitignore
dist/
```

### ❌ FAIL example
```gitignore
node_modules/
```

## WAP-008 — Scaffolded package.json version remains 1.0.0

**Severity:** MEDIUM

**Description:** Initial scaffold versioning stays at `1.0.0`; release cadence is managed manually.

### ✅ PASS example
```json
{"version": "1.0.0"}
```

### ❌ FAIL example
```json
{"version": "2.0.0"}
```

## WAP-009 — CloudFront guidance must enforce HTTPS redirect

**Severity:** HIGH

**Description:** Deployment documentation must explicitly require HTTP-to-HTTPS redirect at the CDN layer.

### ✅ PASS example
```md
Set the CloudFront viewer protocol policy to Redirect HTTP to HTTPS.
```

### ❌ FAIL example
```md
Allow both HTTP and HTTPS for convenience.
```

## WAP-010 — No inline event handlers in generated markup

**Severity:** HIGH

**Description:** Event binding must happen in React or script logic, not via inline HTML handlers.

### ✅ PASS example
```jsx
<button type="button" className="primary-action">Start now</button>
```

### ❌ FAIL example
```html
<button onclick="openChat()">Start now</button>
```

## WAP-011 — Images need alt; decorative SVGs need aria-hidden

**Severity:** HIGH

**Description:** Media must be accessible and correctly classified as informative or decorative.

### ✅ PASS example
```jsx
<img src="/logo.svg" alt="Meridian Bank logo" />
<svg aria-hidden="true" viewBox="0 0 120 120"></svg>
```

### ❌ FAIL example
```jsx
<img src="/logo.svg" alt="" />
<svg viewBox="0 0 120 120"></svg>
```

## WAP-012 — .app must use min-height: 100vh

**Severity:** MEDIUM

**Description:** The shell layout must occupy the viewport to avoid short-page flashing and footer jumps.

### ✅ PASS example
```css
.app {
  min-height: 100vh;
}
```

### ❌ FAIL example
```css
.app {
  min-height: auto;
}
```

## WAP-013 — public/favicon.svg must exist

**Severity:** LOW

**Description:** The scaffold should always include a favicon asset for baseline browser/PWA polish.

### ✅ PASS example
```text
public/favicon.svg
```

### ❌ FAIL example
```text
(no favicon present)
```

## WAP-014 — Vite dev and preview must bind host: true

**Severity:** HIGH

**Description:** Development and preview servers must bind all interfaces for containerised and remote-device testing.

### ✅ PASS example
```js
server: { port: 4001, host: true },
preview: { port: 4001, host: true },
```

### ❌ FAIL example
```js
server: { port: 4001 },
preview: { port: 4001 },
```

## WAP-015 — CSS must include standard mobile breakpoints

**Severity:** HIGH

**Description:** Mobile-first styles must include at least `640px`, `768px`, `1024px`, and `1280px` media queries.

### ✅ PASS example
```css
@media (min-width: 640px) {}
@media (min-width: 768px) {}
@media (min-width: 1024px) {}
@media (min-width: 1280px) {}
```

### ❌ FAIL example
```css
@media (max-width: 900px) {}
```

## WAP-016 — Touch targets must be at least 44×44px

**Severity:** HIGH

**Description:** Buttons, links, and button-like controls must meet WCAG 2.5.5 sizing guidance.

### ✅ PASS example
```css
button,
a,
[role="button"] {
  min-height: 44px;
  min-width: 44px;
}
```

### ❌ FAIL example
```css
button {
  min-height: 28px;
}
```

## WAP-017 — package.json must include test and audit scripts

**Severity:** MEDIUM

**Description:** Generated apps must ship with baseline unit, E2E, coverage, and audit commands.

### ✅ PASS example
```json
{
  "scripts": {
    "test": "vitest run",
    "test:coverage": "vitest run --coverage",
    "test:e2e": "playwright test",
    "audit": "npm audit --audit-level=high"
  }
}
```

### ❌ FAIL example
```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build"
  }
}
```

## WAP-018 — Vitest coverage thresholds must be ≥80%

**Severity:** HIGH

**Description:** The generated Vitest config must enforce 80% thresholds for statements, branches, functions, and lines.

### ✅ PASS example
```js
coverage: {
  thresholds: { statements: 80, branches: 80, functions: 80, lines: 80 },
}
```

### ❌ FAIL example
```js
coverage: {
  thresholds: { lines: 60 },
}
```

## WAP-019 — Playwright config must include mobile projects

**Severity:** HIGH

**Description:** Playwright coverage must include desktop plus Pixel 7, iPhone 14, and iPad projects.

### ✅ PASS example
```js
projects: [
  { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  { name: 'Mobile Chrome', use: { ...devices['Pixel 7'] } },
  { name: 'Mobile Safari', use: { ...devices['iPhone 14'] } },
  { name: 'iPad', use: { ...devices['iPad (gen 7)'] } },
]
```

### ❌ FAIL example
```js
projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]
```

## WAP-020 — Vite build target must be es2020 or newer

**Severity:** MEDIUM

**Description:** Generated builds must target modern browsers and Node-compatible syntax.

### ✅ PASS example
```js
build: {
  target: 'es2020',
}
```

### ❌ FAIL example
```js
build: {
  target: 'es2015',
}
```

## WAP-021 — Production builds must disable sourcemaps

**Severity:** HIGH

**Description:** Production bundles must not ship sourcemaps; dev/test builds may enable them.

### ✅ PASS example
```js
sourcemap: mode !== 'production'
```

### ❌ FAIL example
```js
sourcemap: true
```

## WAP-022 — Vite must split vendor chunks from app code

**Severity:** MEDIUM

**Description:** Rollup output should place React dependencies into a dedicated `vendor` chunk.

### ✅ PASS example
```js
manualChunks: {
  vendor: ['react', 'react-dom'],
}
```

### ❌ FAIL example
```js
manualChunks: {}
```

## SEC-001 — No CRITICAL/HIGH npm vulnerabilities before release

**Severity:** CRITICAL

**Description:** The production pipeline must block builds when CRITICAL or HIGH findings remain.

### ✅ PASS example
```bash
python3 audit_security.py . --report-only
# exits 0
```

### ❌ FAIL example
```bash
npm audit --audit-level=high
# exits 1 but release still proceeds
```

## SEC-002 — package-lock.json must exist and be committed

**Severity:** HIGH

**Description:** The scaffold must generate a lockfile and the repository must keep it under source control.

### ✅ PASS example
```text
package-lock.json
```

### ❌ FAIL example
```text
(no package-lock.json present)
```

## SEC-003 — No wildcard or loose greater-than ranges in package.json

**Severity:** HIGH

**Description:** Dependency ranges must be pinned or semver-scoped, never `*` or `>1.0.0` style open-ended ranges.

### ✅ PASS example
```json
{
  "react": "^18.3.1"
}
```

### ❌ FAIL example
```json
{
  "react": "*",
  "vite": ">5.0.0"
}
```

## SEC-004 — External scripts must use SRI and crossorigin

**Severity:** HIGH

**Description:** Third-party script tags must carry `integrity` and `crossorigin="anonymous"` when loaded from CDNs.

### ✅ PASS example
```html
<script src="https://cdn.example.com/app.js" integrity="sha384-..." crossorigin="anonymous"></script>
```

### ❌ FAIL example
```html
<script src="https://cdn.example.com/app.js"></script>
```

## SEC-005 — npm audit must pass before production build

**Severity:** CRITICAL

**Description:** `npm audit --audit-level=high` must exit 0 before release packaging or deployment.

### ✅ PASS example
```bash
npm audit --audit-level=high
# exits 0
```

### ❌ FAIL example
```bash
npm run build
# no audit gate executed
```

## SEC-006 — No eval/new Function/setTimeout(string) in source

**Severity:** CRITICAL

**Description:** Generated source must not contain string-evaluated JavaScript execution paths.

### ✅ PASS example
```js
setTimeout(() => doThing(), 100);
```

### ❌ FAIL example
```js
eval(userInput);
new Function(code)();
setTimeout('runInjectedCode()', 1000);
```

## SEC-007 — No dangerouslySetInnerHTML in React source

**Severity:** CRITICAL

**Description:** Scaffolded React components must avoid raw HTML injection to reduce XSS risk.

### ✅ PASS example
```jsx
<p>{content}</p>
```

### ❌ FAIL example
```jsx
<div dangerouslySetInnerHTML={{ __html: html }} />
```

## SEC-008 — All VITE_* vars used in source must be documented in .env.example

**Severity:** HIGH

**Description:** Every public env var referenced in source must appear in `.env.example` so deployments are reproducible.

### ✅ PASS example
```env
VITE_CHAT_PROVIDER=
VITE_CHAT_CONFIG={}
```

### ❌ FAIL example
```js
const cfg = import.meta.env.VITE_CHAT_CONFIG;
// but .env.example does not mention it
```

## SEC-009 — HTTP security headers must be configured

**Severity:** HIGH

**Description:** Production edge/server config must set core headers including XFO, XCTO, XXSS, and HSTS.

### ✅ PASS example
```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### ❌ FAIL example
```nginx
server {
  listen 80;
}
```

## SEC-010 — No secrets or tokens may be committed

**Severity:** HIGH

**Description:** Generated output and supporting docs must not include obvious secrets such as OpenAI keys, AWS access keys, GitHub PATs, or Slack tokens.

### ✅ PASS example
```env
VITE_CHAT_PROVIDER=
```

### ❌ FAIL example
```text
AKIAIOSFODNN7EXAMPLE
ghp_examplePersonalAccessToken
sk-live-example
```
