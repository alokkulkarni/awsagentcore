---
name: webapp-scaffold
description: >
  Scaffold a production-ready React + Vite web application with optional chat
  widget integration (Amazon Connect, Intercom, Zendesk, Crisp, Freshchat, or
  custom), brand-aware CSS theming, mobile-first responsive behaviour,
  automated Vitest + Playwright test suites, Docker-ready deployment, and
  CloudFront-ready secure delivery. The skill asks all required questions
  before generating any code.
license: MIT
compatibility: >
  Python 3.9+ (python3 in PATH). Compatible with Copilot CLI, VS Code GitHub Copilot, Kiro, Claude Code, Cursor, and Gemini CLI.
metadata:
  category: frontend
  tags: [react, vite, webapp, chat-widget, cloudfront, docker, testing, security, scaffolding, branding, mobile-first]
  author: agentskills
allowed-tools: [Bash, Read, Edit, Glob, Grep, Write]
---

## Purpose

Use this skill to scaffold a secure-by-default React 18 + Vite web application with pure CSS theming, reusable layout components, mobile-first responsive behaviour, automated Vitest + Playwright test suites, optional chat widget integration, Docker-ready deployment assets, and CloudFront-ready secure delivery guidance.

## Interactive questions

Run `scripts/collect_info.py` before scaffolding. It asks these questions in order, one at a time, with defaults shown in brackets:

1. `Project name? (my-webapp)`
2. `Brand / organisation name? (My App)`
3. `Vertical / industry? [banking|insurance|ecommerce|corporate|generic] (generic)`
4. `Primary brand colour (hex)? (#0D2A66)`
5. `Accent / CTA colour (hex)? (#E63012)`
6. `Background colour (hex)? (#f5f6fa)`
7. `Logo: path to logo file, OR 'text' for text-only logo? (text)`
8. `Logo text / monogram? (M)`
9. `Header nav items? (comma-separated, e.g. "Accounts,Payments,Support")`
10. `Hero headline? ("Banking made simple")`
11. `Hero subtitle? (one sentence)`
12. `Primary CTA label? ("Get started")`
13. `Secondary CTA label? ("Sign in")`
14. `Include a chat widget? [y/n] (n)`
15. `Chat provider? [amazon-connect|intercom|zendesk|crisp|freshchat|custom]` (only asked if chat=y)
16. Provider-specific configuration questions (only asked for the chosen provider)
17. `Deploy target? [cloudfront|docker|both] (both)`
18. `Port for local dev? (4001)`
19. `Include feature cards section? [y/n] (y)`
20. If features are enabled: `Feature items? (comma-separated icons+labels, e.g. "💳 Instant Transfers,📊 Insights")`
21. `Include products/services grid? [y/n] (n)`
22. `Footer text? (© 2026 <Brand>. All rights reserved.)`
23. `Copyright entity? (<Brand>)`

If `webapp-config.json` already exists, the collector offers to reuse it or re-ask every question.

## Rules

The scaffold and validator enforce these WAP rules:

- **WAP-001** — Always use CSS custom properties for brand colours; never hardcode hex values in component CSS.
- **WAP-002** — Chat widget credentials (API keys, snippet IDs, app IDs) must come from env vars or runtime config — never hardcoded in committed source.
- **WAP-003** — If a third-party chat widget is included, `index.html` must include a Content-Security-Policy meta tag that allowlists the widget's script origin.
- **WAP-004** — `ChatWidget.jsx` must clean up event listeners, observers, and loaded scripts in the `useEffect` return function.
- **WAP-005** — Vite config must set `define: { global: 'globalThis' }` for compatibility with third-party widget SDKs that expect a browser global.
- **WAP-006** — All interactive elements must meet WCAG 2.1 AA contrast ratio (≥4.5:1 for normal text).
- **WAP-007** — Build output must be in `dist/`; no build artefacts committed to git.
- **WAP-008** — `package.json` must not have `"version"` bumped beyond `1.0.0` in the scaffold; versioning is manual.
- **WAP-009** — CloudFront deployment must enforce HTTPS redirect; no HTTP-only delivery.
- **WAP-010** — No inline event handlers such as `onclick="..."`; bind events via React or script listeners only.
- **WAP-011** — All images must have non-empty `alt` attributes; decorative SVGs must have `aria-hidden="true"`.
- **WAP-012** — CSS must use `min-height: 100vh` on the root `.app` to prevent short-page flash.
- **WAP-013** — `public/favicon.svg` must exist for baseline PWA-readiness.
- **WAP-014** (HIGH) — Vite dev and preview servers must bind `host: true` for Docker compatibility.
- **WAP-015** (HIGH) — CSS must include mobile breakpoints at 640px, 768px, 1024px, 1280px.
- **WAP-016** (HIGH) — Touch targets (buttons, links) must be ≥44×44px (WCAG 2.5.5).
- **WAP-017** (MEDIUM) — `package.json` must include scripts: `test`, `test:coverage`, `test:e2e`, `audit`.
- **WAP-018** (HIGH) — `vitest.config.js` coverage thresholds must be ≥80% for statements/branches/functions/lines.
- **WAP-019** (HIGH) — Playwright config must include mobile viewport projects (Pixel 7, iPhone 14, iPad).
- **WAP-020** (MEDIUM) — `build.target` in vite.config must be `'es2020'` or newer.
- **WAP-021** (HIGH) — Prod build must set `sourcemap: false` (never ship sourcemaps to production).
- **WAP-022** (MEDIUM) — `manualChunks` must separate `vendor` (react/react-dom) from app code.

## Security Rules

- **SEC-001** (CRITICAL) — No npm deps with known CRITICAL or HIGH CVEs in production build.
- **SEC-002** (HIGH) — `package-lock.json` must be committed to source control (lockfile integrity).
- **SEC-003** (HIGH) — No wildcard (`*`) or loose (`>1.0.0`) version specifiers in `package.json`.
- **SEC-004** (HIGH) — All external CDN/third-party scripts must use SRI (Subresource Integrity) `integrity` + `crossorigin` attributes.
- **SEC-005** (CRITICAL) — `npm audit --audit-level=high` must exit 0 before production build.
- **SEC-006** (CRITICAL) — No `eval()`, `new Function()`, or `setTimeout(string)` anywhere in source.
- **SEC-007** (CRITICAL) — No `dangerouslySetInnerHTML` in React components (XSS vector).
- **SEC-008** (HIGH) — All `VITE_*` env vars used in source must be documented in `.env.example`.
- **SEC-009** (HIGH) — HTTP headers: X-Frame-Options, X-Content-Type-Options, X-XSS-Protection, HSTS must be set (nginx.conf or CloudFront response headers policy).
- **SEC-010** (HIGH) — No secrets, tokens, or API keys committed to source (scan for patterns: `sk-`, `AKIA`, `ghp_`, `xoxb-`).

## Pre-generation checklist

Before running the scaffold:

- Confirm branding inputs, logo mode, and target industry template.
- Decide whether a chat widget is needed and, if so, which provider — the skill will ask before generating any code.
- Confirm the local development port and whether Docker output is required.
- Decide whether feature cards and product/service grids should be generated.
- Confirm the desired security posture: CSP allowlist, lockfile generation, dependency audit, and environment variable documentation.
- Confirm the test expectations: Vitest unit tests, Playwright E2E coverage, accessibility checks, and responsive/mobile validation.

## Usage

### GitHub Copilot CLI

```bash
python3 .agents/skills/webapp-scaffold/scripts/collect_info.py
python3 .agents/skills/webapp-scaffold/scripts/scaffold_webapp.py --config webapp-config.json --output ./my-webapp
python3 .agents/skills/webapp-scaffold/scripts/validate_webapp.py ./my-webapp
```

### Direct script usage

```bash
python3 .agents/skills/webapp-scaffold/scripts/collect_info.py
python3 .agents/skills/webapp-scaffold/scripts/scaffold_webapp.py --config webapp-config.json --dry-run
python3 .agents/skills/webapp-scaffold/scripts/scaffold_tests.py ./my-webapp
python3 .agents/skills/webapp-scaffold/scripts/check_versions.py ./my-webapp
python3 .agents/skills/webapp-scaffold/scripts/audit_security.py ./my-webapp --report-only
bash .agents/skills/webapp-scaffold/scripts/build_prod.sh
python3 .agents/skills/webapp-scaffold/scripts/validate_webapp.py ./my-webapp
```

## Scripts

The skill ships with these seven operational scripts:

1. `scripts/collect_info.py` — collects scaffold configuration into `webapp-config.json`.
2. `scripts/scaffold_webapp.py` — generates the complete React + Vite project, docs, tests, Docker files, `.npmrc`, and lockfile.
3. `scripts/validate_webapp.py` — validates generated output against WAP and SEC rules.
4. `scripts/audit_security.py` — runs `npm audit`, lockfile analysis, registry lookups, OWASP mapping, and markdown reporting.
5. `scripts/check_versions.py` — checks direct dependency freshness, semver-safe upgrades, and deprecated packages.
6. `scripts/scaffold_tests.py` — generates Vitest unit tests, Playwright E2E tests, and related config files.
7. `scripts/build_prod.sh` — production build pipeline with Node version checks, audit gating, lint/test hooks, and build stats.

## What gets generated

- React + Vite application shell (`index.html`, `src/`, `vite.config.js`, `package.json`, `package-lock.json`)
- Mobile-first CSS with responsive breakpoints and hamburger navigation
- Dockerfile.prod, Dockerfile.dev, docker-compose.yml, nginx.conf
- vitest.config.js, playwright.config.js
- src/__tests__/setup.js + component tests
- e2e/ Playwright tests
- `ChatWidget.jsx` (if chat enabled)
- `.npmrc`
- `SECURITY.md` (auto-generated from template)
- `docs/test-plan.md` (auto-generated)
- `docs/mobile-checklist.md` (auto-generated)
- `docs/chat-providers.md`
- security-audit-report.md and dependency-report.md when the audit/version scripts are executed

## Output structure

```text
<project-name>/
├── index.html
├── package.json
├── package-lock.json
├── vite.config.js
├── vitest.config.js
├── playwright.config.js
├── .env.example
├── .npmrc
├── .gitignore
├── eslint.config.js
├── Dockerfile.prod
├── Dockerfile.dev
├── docker-compose.yml
├── nginx.conf
├── SECURITY.md
├── docs/
│   ├── test-plan.md
│   ├── mobile-checklist.md
│   └── chat-providers.md
├── public/
│   └── favicon.svg
├── e2e/
│   ├── homepage.spec.js
│   ├── mobile.spec.js
│   ├── accessibility.spec.js
│   └── chat-widget.spec.js        # if chat enabled
└── src/
    ├── main.jsx
    ├── App.jsx
    ├── App.css
    ├── index.css
    ├── __tests__/
    │   ├── setup.js
    │   ├── Header.test.jsx
    │   ├── Hero.test.jsx
    │   ├── Footer.test.jsx
    │   ├── App.test.jsx
    │   └── ChatWidget.test.jsx    # if chat enabled
    └── components/
        ├── Header.jsx
        ├── Hero.jsx
        ├── Footer.jsx
        ├── ChatWidget.jsx         # if chat enabled
        ├── FeatureGrid.jsx        # if features=y
        └── ProductGrid.jsx        # if products=y
```

The scaffolder may also copy a supplied logo into `public/` when the configuration points at a local file.
