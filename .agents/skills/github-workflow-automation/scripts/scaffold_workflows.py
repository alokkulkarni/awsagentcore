#!/usr/bin/env python3
"""Generate GitHub Actions workflows from complete skill templates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any, Dict, List

SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = SKILL_ROOT / "templates"
ASSETS_ROOT = SKILL_ROOT / "assets"
DEFAULT_ACTION_VERSIONS = {
    "actions/checkout": {"version": "v4"},
    "actions/setup-node": {"version": "v4"},
    "actions/setup-python": {"version": "v3"},
    "actions/setup-java": {"version": "v4"},
    "actions/setup-go": {"version": "v5"},
    "actions/setup-dotnet": {"version": "v4"},
    "actions/upload-artifact": {"version": "v4"},
    "actions/download-artifact": {"version": "v4"},
    "actions/cache": {"version": "v4"},
    "docker/login-action": {"version": "v3"},
    "docker/build-push-action": {"version": "v5"},
    "docker/metadata-action": {"version": "v5"},
    "docker/setup-buildx-action": {"version": "v3"},
    "docker/scout-action": {"version": "v1"},
    "aquasecurity/trivy-action": {"version": "0.20.0"},
    "anchore/scan-action": {"version": "v3"},
    "github/codeql-action/init": {"version": "v3"},
    "github/codeql-action/autobuild": {"version": "v3"},
    "github/codeql-action/analyze": {"version": "v3"},
    "github/codeql-action/upload-sarif": {"version": "v3"},
    "codecov/codecov-action": {"version": "v4"},
    "aws-actions/configure-aws-credentials": {"version": "v4"},
    "aws-actions/amazon-ecs-deploy-task-definition": {"version": "v1"},
    "azure/login": {"version": "v2"},
    "azure/container-apps-deploy-action": {"version": "v1"},
    "google-github-actions/auth": {"version": "v2"},
    "google-github-actions/deploy-cloudrun": {"version": "v2"},
    "dtolnay/rust-toolchain": {"version": "stable"},
}


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Required file not found: {path}") from exc


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(safe_read_text(path))


def load_action_versions() -> Dict[str, Dict[str, str]]:
    versions = dict(DEFAULT_ACTION_VERSIONS)
    candidate = ASSETS_ROOT / "action-versions.json"
    if candidate.exists():
        versions.update(load_json(candidate))
    return versions


def use(action: str, versions: Dict[str, Dict[str, str]]) -> str:
    return f"{action}@{versions.get(action, {}).get('version', 'v1')}"


def indent_block(text: str, spaces: int = 6) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else prefix.rstrip() for line in text.rstrip().splitlines())


def join_blocks(*blocks: str) -> str:
    return "\n".join(block.rstrip() for block in blocks if block and block.strip())


def normalize_branch(branch: str) -> str:
    branch = branch.strip()
    if "*" in branch and "**" not in branch:
        branch = branch.replace("*", "**")
    return branch


def format_branches(branches: List[str]) -> str:
    rendered = []
    for branch in branches:
        normalized = normalize_branch(branch)
        rendered.append(f"'{normalized}'" if any(token in normalized for token in ['*', '/']) else normalized)
    return "[" + ", ".join(rendered) + "]"


def render_template(template_path: Path, mapping: Dict[str, str]) -> str:
    text = safe_read_text(template_path)
    for key, value in mapping.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def quote(value: str) -> str:
    return json.dumps(value)


def project_repo_slug(repo_path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_path,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return f"my-org/{repo_path.name}"
    remote = result.stdout.strip()
    if remote:
        import re
        match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", remote)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return f"my-org/{repo_path.name}"


def registry_config(config: Dict[str, Any], versions: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    ci = config.get("ci", {})
    registry = ci.get("docker_registry", "ghcr")
    image_name = ci.get("image_name") or project_repo_slug(Path(config["repo_path"]))
    if registry == "ghcr":
        registry_image = image_name if image_name.startswith("ghcr.io/") else f"ghcr.io/{image_name}"
        login = dedent(
            f"""\
            - name: Log in to GHCR
              uses: {use('docker/login-action', versions)}
              with:
                registry: ghcr.io
                username: ${{{{ github.actor }}}}
                password: ${{{{ secrets.GITHUB_TOKEN }}}}
            """
        )
    elif registry == "dockerhub":
        registry_image = image_name if image_name.startswith("docker.io/") else f"docker.io/{image_name}"
        login = dedent(
            f"""\
            - name: Log in to Docker Hub
              uses: {use('docker/login-action', versions)}
              with:
                username: ${{{{ secrets.DOCKERHUB_USERNAME }}}}
                password: ${{{{ secrets.DOCKERHUB_TOKEN }}}}
            """
        )
    elif registry == "ecr":
        registry_image = f"${{{{ vars.ECR_REGISTRY }}}}/{image_name}"
        login = dedent(
            f"""\
            - name: Configure AWS credentials
              uses: {use('aws-actions/configure-aws-credentials', versions)}
              with:
                aws-access-key-id: ${{{{ secrets.AWS_ACCESS_KEY_ID }}}}
                aws-secret-access-key: ${{{{ secrets.AWS_SECRET_ACCESS_KEY }}}}
                aws-region: ${{{{ vars.AWS_REGION }}}}
            - name: Log in to Amazon ECR
              shell: bash
              run: |
                set -euo pipefail
                aws ecr get-login-password --region "${{{{ vars.AWS_REGION }}}}" | docker login --username AWS --password-stdin "${{{{ vars.ECR_REGISTRY }}}}"
            """
        )
    elif registry == "acr":
        registry_image = f"${{{{ vars.ACR_LOGIN_SERVER }}}}/{image_name}"
        login = dedent(
            f"""\
            - name: Login to Azure
              uses: {use('azure/login', versions)}
              with:
                creds: ${{{{ secrets.AZURE_CREDENTIALS }}}}
            - name: Log in to Azure Container Registry
              shell: bash
              run: |
                set -euo pipefail
                az acr login --name "${{{{ vars.ACR_NAME }}}}"
            """
        )
    else:
        registry_image = f"${{{{ vars.CUSTOM_REGISTRY }}}}/{image_name}"
        login = dedent(
            f"""\
            - name: Log in to custom registry
              uses: {use('docker/login-action', versions)}
              with:
                registry: ${{{{ vars.CUSTOM_REGISTRY }}}}
                username: ${{{{ secrets.CUSTOM_REGISTRY_USERNAME }}}}
                password: ${{{{ secrets.CUSTOM_REGISTRY_PASSWORD }}}}
            """
        )
    return {"registry": registry, "image_name": image_name, "registry_image": registry_image, "login_steps": login.rstrip()}


def coverage_gate_step(threshold: int, allow_missing: bool) -> str:
    script = dedent(
        """\
        import json
        import os
        import re
        import sys
        from pathlib import Path

        threshold = float(os.environ['COVERAGE_THRESHOLD'])
        allow_missing = os.environ['ALLOW_MISSING_COVERAGE'].lower() == 'true'
        candidates = [
            Path('coverage/coverage-summary.json'),
            Path('coverage-summary.json'),
            Path('coverage.xml'),
            Path('coverage.cobertura.xml'),
            Path('target/site/jacoco/jacoco.xml'),
            Path('build/reports/jacoco/test/jacocoTestReport.xml'),
            Path('coverage.out'),
        ]
        value = None
        for candidate in candidates:
            if not candidate.exists():
                continue
            text = candidate.read_text(encoding='utf-8', errors='ignore')
            if candidate.suffix == '.json':
                data = json.loads(text)
                totals = data.get('total', {}) if isinstance(data, dict) else {}
                lines = totals.get('lines') if isinstance(totals, dict) else None
                if isinstance(lines, dict) and isinstance(lines.get('pct'), (int, float)):
                    value = float(lines['pct'])
                    break
            if candidate.name.endswith('.xml'):
                match = re.search(r'line-rate="([0-9.]+)"', text)
                if match:
                    value = round(float(match.group(1)) * 100, 2)
                    break
                match = re.search(r'lines-valid="(\\d+)".*lines-covered="(\\d+)"', text)
                if match and float(match.group(1)):
                    value = round((float(match.group(2)) / float(match.group(1))) * 100, 2)
                    break
            if candidate.name == 'coverage.out':
                total = 0
                covered = 0
                for line in text.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    counts = parts[1].split(',')
                    span = counts[0].split(':')[-1]
                    start_line = int(span.split('.')[0])
                    end_line = int(counts[1].split('.')[0])
                    block_lines = max(1, end_line - start_line + 1)
                    total += block_lines
                    if int(parts[2]) > 0:
                        covered += block_lines
                if total:
                    value = round((covered / total) * 100, 2)
                    break
        if value is None:
            if allow_missing:
                print('No coverage report found; skipping strict coverage gate for this language.')
                Path('coverage-percent.txt').write_text('0.00', encoding='utf-8')
                sys.exit(0)
            raise SystemExit('No coverage report found. Ensure the test command emits coverage output.')
        print(f'Detected line coverage: {value:.2f}%')
        Path('coverage-percent.txt').write_text(f'{value:.2f}', encoding='utf-8')
        if value < threshold:
            raise SystemExit(f'Coverage {value:.2f}% is below threshold {threshold:.2f}%')
        """
    )
    command = "python3 - <<'PY'\n" + script + "PY"
    return dedent(
        f"""\
        - name: Enforce coverage threshold
          shell: bash
          env:
            COVERAGE_THRESHOLD: {quote(str(threshold))}
            ALLOW_MISSING_COVERAGE: {quote('true' if allow_missing else 'false')}
          run: |
            set -euo pipefail
{indent_block(command, 12)}
        """
    )


def security_report_step(reports_folder: str, fail_on_critical: bool, fail_on_high: bool) -> str:
    script = dedent(
        """\
        import json
        import os
        from pathlib import Path

        reports_dir = Path(os.environ['REPORTS_DIR'])
        fail_on_critical = os.environ['FAIL_ON_CRITICAL'].lower() == 'true'
        fail_on_high = os.environ['FAIL_ON_HIGH'].lower() == 'true'
        today = os.environ['RUN_DATE']
        payload = json.loads(Path('trivy-fs.json').read_text(encoding='utf-8'))
        findings = []
        for result in payload.get('Results', []):
            for vuln in result.get('Vulnerabilities') or []:
                findings.append({
                    'id': vuln.get('VulnerabilityID', 'UNKNOWN'),
                    'severity': str(vuln.get('Severity', 'UNKNOWN')).upper(),
                    'package': vuln.get('PkgName', 'unknown'),
                    'installed_version': vuln.get('InstalledVersion', ''),
                    'fixed_version': vuln.get('FixedVersion', ''),
                })
        findings = sorted({(item['id'], item['package']): item for item in findings}.values(), key=lambda item: (item['severity'], item['id']))
        dated_dirs = sorted([path for path in reports_dir.rglob('*') if path.is_dir() and path.name != today and len(path.name) == 10], reverse=True)
        previous = None
        previous_map = {}
        for dated in dated_dirs:
            candidate = dated / 'security-findings.json'
            if candidate.exists():
                previous = candidate
                previous_map = {item['id']: item for item in json.loads(candidate.read_text(encoding='utf-8'))}
                break
        current_map = {item['id']: item for item in findings}
        new_ids = sorted(set(current_map) - set(previous_map))
        fixed_ids = sorted(set(previous_map) - set(current_map))
        critical_count = sum(1 for item in findings if item['severity'] == 'CRITICAL')
        high_count = sum(1 for item in findings if item['severity'] == 'HIGH')
        lines = [
            '# Security Report',
            '',
            f'- Date: {today}',
            f'- Previous report: {previous if previous else "none"}',
            f'- Critical findings: {critical_count}',
            f'- High findings: {high_count}',
            '',
            '## Findings',
            '',
            '| Severity | ID | Package | Installed | Fixed |',
            '| --- | --- | --- | --- | --- |',
        ]
        if findings:
            for item in findings:
                lines.append(f"| {item['severity']} | {item['id']} | {item['package']} | {item['installed_version']} | {item['fixed_version']} |")
        else:
            lines.append('| NONE | - | - | - | - |')
        if new_ids:
            lines.extend(['', '## New since previous report', ''])
            for vuln_id in new_ids:
                lines.append(f"- {vuln_id} ({current_map[vuln_id]['severity']})")
        if fixed_ids:
            lines.extend(['', '## Fixed since previous report', ''])
            for vuln_id in fixed_ids:
                lines.append(f'- {vuln_id}')
        Path('security-findings.json').write_text(json.dumps(findings, indent=2), encoding='utf-8')
        Path('security-report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        if fail_on_critical and critical_count:
            raise SystemExit(f'CRITICAL vulnerabilities detected: {critical_count}')
        if fail_on_high and high_count:
            raise SystemExit(f'HIGH vulnerabilities detected: {high_count}')
        if any(current_map[vuln_id]['severity'] == 'CRITICAL' for vuln_id in new_ids):
            raise SystemExit('New CRITICAL vulnerabilities detected compared with the previous report.')
        """
    )
    command = "python3 - <<'PY'\n" + script + "PY"
    return dedent(
        f"""\
        - name: Build security report and compare with n-1
          shell: bash
          env:
            REPORTS_DIR: {quote(reports_folder)}
            RUN_DATE: ${{{{ steps.meta.outputs.run_date }}}}
            FAIL_ON_CRITICAL: {quote('true' if fail_on_critical else 'false')}
            FAIL_ON_HIGH: {quote('true' if fail_on_high else 'false')}
          run: |
            set -euo pipefail
{indent_block(command, 12)}
        """
    )


def build_report_commit_steps(reports_folder: str, badge_enabled: bool, retention_days: int, versions: Dict[str, Dict[str, str]]) -> str:
    badge_script = dedent(
        """\
        import os
        import re
        from pathlib import Path

        badge_enabled = os.environ['BADGE_ENABLED'].lower() == 'true'
        if not badge_enabled:
            print('Coverage badge update disabled.')
            raise SystemExit(0)
        coverage_file = next(iter(Path('artifacts').rglob('coverage-percent.txt')), None)
        if coverage_file is None:
            print('No coverage-percent.txt artifact found; skipping badge update.')
            raise SystemExit(0)
        try:
            value = float(coverage_file.read_text(encoding='utf-8').strip() or '0.0')
        except ValueError:
            value = 0.0
        color = 'green' if value >= 90 else 'yellow' if value >= 80 else 'red'
        badge = f'![Coverage](https://img.shields.io/badge/Coverage-{value:.2f}%25-{color})'
        readme = Path('README.md')
        if not readme.exists():
            print('README.md not found; skipping badge update.')
            raise SystemExit(0)
        text = readme.read_text(encoding='utf-8')
        if re.search(r'!\\[Coverage\\]\\(https://img\\.shields\\.io/badge/Coverage-[^)]+\\)', text):
            updated = re.sub(r'!\\[Coverage\\]\\(https://img\\.shields\\.io/badge/Coverage-[^)]+\\)', badge, text, count=1)
        else:
            updated = badge + '\n\n' + text
        readme.write_text(updated, encoding='utf-8')
        """
    )
    badge_command = "python3 - <<'PY'\n" + badge_script + "PY"
    return join_blocks(
        dedent(
            f"""\
            - name: Checkout repository
              uses: {use('actions/checkout', versions)}
              with:
                persist-credentials: true
            - name: Download workflow artifacts
              uses: {use('actions/download-artifact', versions)}
              with:
                path: artifacts
            - name: Commit dated reports back to the repository
              shell: bash
              env:
                REPORTS_DIR: {quote(reports_folder)}
              run: |
                set -euo pipefail
                REPORT_DATE="$(date +%F)"
                TARGET_DIR="$REPORTS_DIR/$REPORT_DATE"
                mkdir -p "$TARGET_DIR"
                cp -R artifacts/. "$TARGET_DIR/" || true
            """
        ),
        dedent(
            f"""\
            - name: Update coverage badge
              shell: bash
              env:
                BADGE_ENABLED: {quote('true' if badge_enabled else 'false')}
              run: |
                set -euo pipefail
{indent_block(badge_command, 16)}
            """
        ),
        dedent(
            f"""\
            - name: Push report commit
              shell: bash
              env:
                REPORTS_DIR: {quote(reports_folder)}
              run: |
                set -euo pipefail
                git config user.name "github-actions[bot]"
                git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
                git add "$REPORTS_DIR" README.md || true
                git diff --cached --quiet && exit 0
                git commit -m "chore: update CI reports [skip ci]"
                git push
            """
        ),
    )

def language_profile(language: str, config: Dict[str, Any], versions: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    language = language.lower()
    if language == 'node':
        return {
            'template': 'ci-node.yml',
            'allow_missing_coverage': False,
            'codeql_languages': '[javascript]',
            'setup': dedent(
                f"""\
                - name: Capture run metadata
                  id: meta
                  shell: bash
                  run: |
                    set -euo pipefail
                    echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
                - name: Setup Node.js
                  uses: {use('actions/setup-node', versions)}
                  with:
                    node-version: {quote(config.get('node_version') or '20')}
                    cache: {quote(config.get('package_manager') or 'npm')}
                """
            ),
            'install': dedent(
                """\
                - name: Install dependencies
                  shell: bash
                  run: |
                    set -euo pipefail
                    corepack enable || true
                    if [ -f pnpm-lock.yaml ]; then
                      pnpm install --frozen-lockfile
                    elif [ -f yarn.lock ]; then
                      yarn install --immutable || yarn install --frozen-lockfile
                    elif [ -f package-lock.json ]; then
                      npm ci
                    else
                      npm install
                    fi
                """
            ),
            'lint': dedent(
                """\
                - name: Lint source
                  shell: bash
                  run: |
                    set -euo pipefail
                    if node -e "const s=require('./package.json').scripts||{}; process.exit(s['lint']?0:1)"; then
                      if [ -f pnpm-lock.yaml ]; then pnpm run lint; elif [ -f yarn.lock ]; then yarn lint; else npm run lint; fi
                    else
                      echo "No lint script configured; skipping."
                    fi
                """
            ),
            'test': dedent(
                """\
                - name: Run unit tests with coverage
                  shell: bash
                  run: |
                    set -euo pipefail
                    mkdir -p test-results
                    if node -e "const s=require('./package.json').scripts||{}; process.exit(s['test:coverage']?0:1)"; then
                      if [ -f pnpm-lock.yaml ]; then pnpm run test:coverage; elif [ -f yarn.lock ]; then yarn test:coverage; else npm run test:coverage; fi
                    elif node -e "const s=require('./package.json').scripts||{}; process.exit(s['coverage']?0:1)"; then
                      if [ -f pnpm-lock.yaml ]; then pnpm run coverage; elif [ -f yarn.lock ]; then yarn coverage; else npm run coverage; fi
                    elif node -e "const s=require('./package.json').scripts||{}; process.exit(s['test']?0:1)"; then
                      if [ -f pnpm-lock.yaml ]; then pnpm test -- --coverage --ci; elif [ -f yarn.lock ]; then yarn test --coverage --ci; else npm test -- --coverage --ci; fi
                    else
                      npx vitest run --coverage
                    fi
                """
            ),
            'native_audit': dedent(
                """\
                - name: Run native dependency audit
                  shell: bash
                  run: |
                    set -euo pipefail
                    corepack enable || true
                    if [ -f pnpm-lock.yaml ]; then
                      pnpm audit --json > native-audit.json || true
                    elif [ -f yarn.lock ]; then
                      yarn npm audit --all --recursive --json > native-audit.json || true
                    else
                      npm audit --audit-level=high --json > native-audit.json || true
                    fi
                """
            ),
            'integration': dedent(
                """\
                if node -e "const s=require('./package.json').scripts||{}; process.exit(s['test:integration']?0:1)"; then
                  if [ -f pnpm-lock.yaml ]; then pnpm run test:integration; elif [ -f yarn.lock ]; then yarn test:integration; else npm run test:integration; fi
                elif node -e "const s=require('./package.json').scripts||{}; process.exit(s['integration']?0:1)"; then
                  if [ -f pnpm-lock.yaml ]; then pnpm run integration; elif [ -f yarn.lock ]; then yarn integration; else npm run integration; fi
                else
                  if [ -f pnpm-lock.yaml ]; then pnpm test -- --runInBand; elif [ -f yarn.lock ]; then yarn test --runInBand; else npm test -- --runInBand; fi
                fi
                """
            ).strip(),
        }
    if language == 'python':
        return {
            'template': 'ci-python.yml',
            'allow_missing_coverage': False,
            'codeql_languages': '[python]',
            'setup': dedent(
                f"""\
                - name: Capture run metadata
                  id: meta
                  shell: bash
                  run: |
                    set -euo pipefail
                    echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
                - name: Setup Python
                  uses: {use('actions/setup-python', versions)}
                  with:
                    python-version: {quote(config.get('python_version') or '3.11')}
                - name: Cache pip
                  uses: {use('actions/cache', versions)}
                  with:
                    path: ~/.cache/pip
                    key: ${{{{ runner.os }}}}-pip-${{{{ hashFiles('**/requirements*.txt', '**/pyproject.toml') }}}}
                    restore-keys: |
                      ${{{{ runner.os }}}}-pip-
                """
            ),
            'install': dedent(
                """\
                - name: Install dependencies
                  shell: bash
                  run: |
                    set -euo pipefail
                    python -m pip install --upgrade pip
                    if [ -f pyproject.toml ] && grep -qi '\\[tool.poetry\\]' pyproject.toml; then
                      python -m pip install poetry
                      poetry install --no-interaction
                    else
                      if [ -f requirements.txt ]; then python -m pip install -r requirements.txt; fi
                      if [ -f requirements-dev.txt ]; then python -m pip install -r requirements-dev.txt; fi
                    fi
                    python -m pip install pytest pytest-cov pip-audit || true
                """
            ),
            'lint': dedent(
                """\
                - name: Lint source
                  shell: bash
                  run: |
                    set -euo pipefail
                    if python -m pip show ruff >/dev/null 2>&1; then
                      ruff check .
                    elif python -m pip show flake8 >/dev/null 2>&1; then
                      flake8 .
                    else
                      echo "No Python linter configured; skipping."
                    fi
                """
            ),
            'test': dedent(
                """\
                - name: Run unit tests with coverage
                  shell: bash
                  run: |
                    set -euo pipefail
                    mkdir -p test-results
                    if python -c "import pytest" >/dev/null 2>&1; then
                      pytest --maxfail=1 --disable-warnings --cov=. --cov-report=xml --cov-report=term-missing --junitxml=test-results/junit.xml
                    else
                      python -m unittest discover
                    fi
                """
            ),
            'native_audit': dedent(
                """\
                - name: Run native dependency audit
                  shell: bash
                  run: |
                    set -euo pipefail
                    python -m pip install pip-audit
                    pip-audit -f json -o native-audit.json || true
                """
            ),
            'integration': "pytest -m integration --junitxml=test-results/integration-junit.xml || pytest tests/integration --junitxml=test-results/integration-junit.xml",
        }
    if language == 'java':
        return {
            'template': 'ci-java.yml',
            'allow_missing_coverage': False,
            'codeql_languages': '[java-kotlin]',
            'setup': dedent(
                f"""\
                - name: Capture run metadata
                  id: meta
                  shell: bash
                  run: |
                    set -euo pipefail
                    echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
                - name: Setup Java
                  uses: {use('actions/setup-java', versions)}
                  with:
                    distribution: temurin
                    java-version: '21'
                    cache: {quote('maven' if config.get('package_manager') == 'maven' else 'gradle')}
                """
            ),
            'install': dedent(
                """\
                - name: Restore Java dependencies
                  shell: bash
                  run: |
                    set -euo pipefail
                    chmod +x mvnw gradlew 2>/dev/null || true
                    if [ -f pom.xml ]; then
                      ./mvnw -B -q -DskipTests dependency:go-offline || mvn -B -q -DskipTests dependency:go-offline
                    else
                      ./gradlew dependencies || gradle dependencies
                    fi
                """
            ),
            'lint': dedent(
                """\
                - name: Run static checks
                  shell: bash
                  run: |
                    set -euo pipefail
                    if [ -f pom.xml ]; then
                      ./mvnw -B -q -DskipTests compile || mvn -B -q -DskipTests compile
                    else
                      ./gradlew classes || gradle classes
                    fi
                """
            ),
            'test': dedent(
                """\
                - name: Run unit tests with coverage
                  shell: bash
                  run: |
                    set -euo pipefail
                    mkdir -p test-results
                    if [ -f pom.xml ]; then
                      ./mvnw -B test jacoco:report || mvn -B test jacoco:report
                    else
                      ./gradlew test jacocoTestReport || gradle test jacocoTestReport
                    fi
                """
            ),
            'native_audit': dedent(
                """\
                - name: Run native dependency audit
                  shell: bash
                  run: |
                    set -euo pipefail
                    if [ -f pom.xml ]; then
                      ./mvnw -B -Dformat=JSON -DfailBuildOnCVSS=11 org.owasp:dependency-check-maven:check || mvn -B -Dformat=JSON -DfailBuildOnCVSS=11 org.owasp:dependency-check-maven:check || true
                    else
                      ./gradlew dependencyCheckAnalyze || gradle dependencyCheckAnalyze || true
                    fi
                """
            ),
            'integration': "if [ -f pom.xml ]; then ./mvnw -B -Dtest='*IT' test || mvn -B -Dtest='*IT' test; else ./gradlew integrationTest || gradle integrationTest; fi",
        }
    if language == 'go':
        return {
            'template': 'ci-go.yml',
            'allow_missing_coverage': False,
            'codeql_languages': '[go]',
            'setup': dedent(
                f"""\
                - name: Capture run metadata
                  id: meta
                  shell: bash
                  run: |
                    set -euo pipefail
                    echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
                - name: Setup Go
                  uses: {use('actions/setup-go', versions)}
                  with:
                    go-version: '1.22'
                    cache: true
                """
            ),
            'install': dedent(
                """\
                - name: Download Go modules
                  shell: bash
                  run: |
                    set -euo pipefail
                    go mod download
                """
            ),
            'lint': dedent(
                """\
                - name: Lint source
                  shell: bash
                  run: |
                    set -euo pipefail
                    test -z "$(gofmt -l .)"
                """
            ),
            'test': dedent(
                """\
                - name: Run unit tests with coverage
                  shell: bash
                  run: |
                    set -euo pipefail
                    mkdir -p test-results
                    go test ./... -coverprofile=coverage.out -json > test-results/go-test.json
                """
            ),
            'native_audit': dedent(
                """\
                - name: Run native dependency audit
                  shell: bash
                  run: |
                    set -euo pipefail
                    go install golang.org/x/vuln/cmd/govulncheck@latest
                    govulncheck -json ./... > native-audit.json || true
                """
            ),
            'integration': "go test ./... -run Integration -json > test-results/integration-go-test.json",
        }
    if language == 'rust':
        return {
            'template': 'ci-generic.yml',
            'allow_missing_coverage': True,
            'codeql_languages': '[rust]',
            'setup': dedent(
                f"""\
                - name: Capture run metadata
                  id: meta
                  shell: bash
                  run: |
                    set -euo pipefail
                    echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
                - name: Setup Rust toolchain
                  uses: {use('dtolnay/rust-toolchain', versions)}
                  with:
                    toolchain: stable
                    components: rustfmt, clippy
                """
            ),
            'install': dedent(
                """\
                - name: Fetch Cargo dependencies
                  shell: bash
                  run: |
                    set -euo pipefail
                    cargo fetch
                """
            ),
            'lint': dedent(
                """\
                - name: Lint source
                  shell: bash
                  run: |
                    set -euo pipefail
                    cargo fmt --all -- --check
                    cargo clippy --all-targets --all-features -- -D warnings
                """
            ),
            'test': dedent(
                """\
                - name: Run unit tests
                  shell: bash
                  run: |
                    set -euo pipefail
                    cargo test --all --all-features
                """
            ),
            'native_audit': dedent(
                """\
                - name: Run native dependency audit
                  shell: bash
                  run: |
                    set -euo pipefail
                    cargo install cargo-audit --locked || true
                    cargo audit -q --json > native-audit.json || true
                """
            ),
            'integration': "cargo test integration -- --nocapture",
        }
    if language == 'dotnet':
        return {
            'template': 'ci-generic.yml',
            'allow_missing_coverage': False,
            'codeql_languages': '[csharp]',
            'setup': dedent(
                f"""\
                - name: Capture run metadata
                  id: meta
                  shell: bash
                  run: |
                    set -euo pipefail
                    echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
                - name: Setup .NET
                  uses: {use('actions/setup-dotnet', versions)}
                  with:
                    dotnet-version: '8.0.x'
                """
            ),
            'install': dedent(
                """\
                - name: Restore dependencies
                  shell: bash
                  run: |
                    set -euo pipefail
                    dotnet restore
                """
            ),
            'lint': dedent(
                """\
                - name: Verify formatting
                  shell: bash
                  run: |
                    set -euo pipefail
                    dotnet format --verify-no-changes || echo "dotnet format skipped; tool or analyzers not configured."
                """
            ),
            'test': dedent(
                """\
                - name: Run unit tests with coverage
                  shell: bash
                  run: |
                    set -euo pipefail
                    mkdir -p test-results
                    dotnet test --collect:"XPlat Code Coverage" --logger trx --results-directory test-results
                """
            ),
            'native_audit': dedent(
                """\
                - name: Run native dependency audit
                  shell: bash
                  run: |
                    set -euo pipefail
                    dotnet list package --vulnerable --include-transitive > native-audit.txt || true
                """
            ),
            'integration': "dotnet test --filter Category=Integration --logger trx --results-directory test-results",
        }
    return {
        'template': 'ci-generic.yml',
        'allow_missing_coverage': True,
        'codeql_languages': '[javascript]',
        'setup': dedent(
            """\
            - name: Capture run metadata
              id: meta
              shell: bash
              run: |
                set -euo pipefail
                echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
            """
        ),
        'install': dedent(
            """\
            - name: Bootstrap project
              shell: bash
              run: |
                set -euo pipefail
                if [ -f Makefile ]; then
                  make bootstrap || true
                else
                  echo "No generic bootstrap step configured."
                fi
            """
        ),
        'lint': dedent(
            """\
            - name: Lint source
              shell: bash
              run: |
                set -euo pipefail
                if [ -f Makefile ]; then
                  make lint
                else
                  echo "No generic lint target configured; skipping."
                fi
            """
        ),
        'test': dedent(
            """\
            - name: Run tests
              shell: bash
              run: |
                set -euo pipefail
                if [ -f Makefile ]; then
                  make test
                else
                  echo "No generic test target configured."
                fi
            """
        ),
        'native_audit': dedent(
            """\
            - name: Run native dependency audit
              shell: bash
              run: |
                set -euo pipefail
                echo "No language-specific audit command configured." > native-audit.txt
            """
        ),
        'integration': "if [ -f Makefile ]; then make integration-test; else echo 'No generic integration target configured'; fi",
    }


def build_ci_workflow(config: Dict[str, Any], versions: Dict[str, Dict[str, str]]) -> str:
    profile = language_profile(config['language'], config, versions)
    branches = config.get('ci', {}).get('trigger_branches') or ['main', 'develop', 'feature/*']
    pr_branches = [branch for branch in branches if 'feature' not in branch] or branches[:2]
    reports_folder = config.get('reports', {}).get('folder', '.github/reports')
    retention_days = int(config.get('reports', {}).get('retention_days', 90))
    coverage_threshold = int(config.get('ci', {}).get('coverage_threshold', 80))
    registry = registry_config(config, versions)

    lint_and_test_steps = join_blocks(
        dedent(f"""\
        - name: Checkout repository
          uses: {use('actions/checkout', versions)}
        """),
        profile['setup'],
        profile['install'],
        profile['lint'],
        profile['test'],
        dedent(
            f"""\
            - name: Upload coverage artifact
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: coverage-${{{{ steps.meta.outputs.run_date }}}}
                path: |
                  coverage
                  coverage.xml
                  coverage.cobertura.xml
                  coverage.out
                  test-results
                if-no-files-found: warn
                retention-days: {retention_days}
            - name: Upload coverage to Codecov
              if: ${{{{ secrets.CODECOV_TOKEN != '' }}}}
              uses: {use('codecov/codecov-action', versions)}
              with:
                token: ${{{{ secrets.CODECOV_TOKEN }}}}
                fail_ci_if_error: false
            """
        ),
        coverage_gate_step(coverage_threshold, profile['allow_missing_coverage']),
        dedent(
            f"""\
            - name: Upload coverage threshold result
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: coverage-summary-${{{{ steps.meta.outputs.run_date }}}}
                path: coverage-percent.txt
                if-no-files-found: warn
                retention-days: {retention_days}
            """
        ),
    )

    security_scan_steps = join_blocks(
        dedent(f"""\
        - name: Checkout repository
          uses: {use('actions/checkout', versions)}
        """),
        profile['setup'],
        profile['install'],
        dedent(
            f"""\
            - name: Initialize CodeQL
              uses: {use('github/codeql-action/init', versions)}
              with:
                languages: {profile['codeql_languages']}
            - name: Autobuild
              uses: {use('github/codeql-action/autobuild', versions)}
            """
        ),
        profile['native_audit'],
        dedent(
            f"""\
            - name: Run Trivy filesystem scan
              uses: {use('aquasecurity/trivy-action', versions)}
              with:
                scan-type: fs
                scan-ref: .
                format: json
                output: trivy-fs.json
                ignore-unfixed: true
                severity: CRITICAL,HIGH
                exit-code: '0'
            """
        ),
        security_report_step(reports_folder, bool(config.get('ci', {}).get('fail_on_critical', True)), bool(config.get('ci', {}).get('fail_on_high', True))),
        dedent(
            f"""\
            - name: Upload security report artifact
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: security-report-${{{{ steps.meta.outputs.run_date }}}}
                path: |
                  security-report.md
                  security-findings.json
                  native-audit.json
                  native-audit.txt
                  trivy-fs.json
                if-no-files-found: warn
                retention-days: {retention_days}
            - name: Analyze CodeQL
              uses: {use('github/codeql-action/analyze', versions)}
            """
        ),
    )

    docker_build_steps = join_blocks(
        dedent(f"""\
        - name: Checkout repository
          uses: {use('actions/checkout', versions)}
        - name: Capture run metadata
          id: meta
          shell: bash
          run: |
            set -euo pipefail
            echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
        - name: Set up Buildx
          uses: {use('docker/setup-buildx-action', versions)}
        """),
        registry['login_steps'],
        dedent(
            f"""\
            - name: Extract image metadata
              id: meta_image
              uses: {use('docker/metadata-action', versions)}
              with:
                images: {registry['registry_image']}
                tags: |
                  type=sha,format=long,prefix=sha-
                  type=ref,event=branch
                  type=semver,pattern={{{{version}}}}
            - name: Build and push image
              id: build
              uses: {use('docker/build-push-action', versions)}
              with:
                context: .
                push: ${{{{ github.event_name != 'pull_request' }}}}
                tags: ${{{{ steps.meta_image.outputs.tags }}}}
                labels: ${{{{ steps.meta_image.outputs.labels }}}}
                sbom: true
                provenance: mode=max
            - name: Generate build report
              shell: bash
              run: |
                set -euo pipefail
                cat <<REPORT > build-report.md
                # Build Report

                - Date: ${{{{ steps.meta.outputs.run_date }}}}
                - Image: {registry['registry_image']}
                - Digest: ${{{{ steps.build.outputs.digest }}}}
                - Tags:
                  ${{{{ steps.meta_image.outputs.tags }}}}
                REPORT
            - name: Upload build report artifact
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: build-report-${{{{ steps.meta.outputs.run_date }}}}
                path: build-report.md
                retention-days: {retention_days}
            """
        ),
    )

    report_commit_steps = build_report_commit_steps(reports_folder, bool(config.get('reports', {}).get('coverage_badge', True)), retention_days, versions)

    return render_template(
        TEMPLATE_ROOT / 'ci' / profile['template'],
        {
            'PUSH_BRANCHES': format_branches(branches),
            'PR_BRANCHES': format_branches(pr_branches),
            'LINT_AND_TEST_STEPS': indent_block(lint_and_test_steps, 6),
            'SECURITY_SCAN_STEPS': indent_block(security_scan_steps, 6),
            'DOCKER_BUILD_STEPS': indent_block(docker_build_steps, 6),
            'REPORT_COMMIT_STEPS': indent_block(report_commit_steps, 6),
        },
    )

def cd_target_blocks(target: str, versions: Dict[str, Dict[str, str]]) -> str:
    if target == 'ecs':
        return dedent(
            f"""\
            - name: Configure AWS credentials
              uses: {use('aws-actions/configure-aws-credentials', versions)}
              with:
                aws-access-key-id: ${{{{ secrets.AWS_ACCESS_KEY_ID }}}}
                aws-secret-access-key: ${{{{ secrets.AWS_SECRET_ACCESS_KEY }}}}
                aws-region: ${{{{ vars.AWS_REGION }}}}
            - name: Capture current task definition
              shell: bash
              run: |
                set -euo pipefail
                aws ecs describe-services --cluster "${{{{ vars.ECS_CLUSTER }}}}" --services "${{{{ vars.ECS_SERVICE }}}}" --query 'services[0].taskDefinition' --output text > previous-taskdef.txt
            - name: Deploy to ECS
              shell: bash
              env:
                IMAGE_REF: ${{{{ steps.image.outputs.image_ref }}}}
                CONTAINER_NAME: ${{{{ vars.ECS_CONTAINER_NAME }}}}
              run: |
                set -euo pipefail
                aws ecs describe-task-definition --task-definition "$(cat previous-taskdef.txt)" --query 'taskDefinition' > taskdef.json
                python3 - <<'PY'
                import json
                import os
                td = json.load(open('taskdef.json', encoding='utf-8'))
                for key in ['taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'compatibilities', 'registeredAt', 'registeredBy']:
                    td.pop(key, None)
                for container in td.get('containerDefinitions', []):
                    if container.get('name') == os.environ['CONTAINER_NAME']:
                        container['image'] = os.environ['IMAGE_REF']
                json.dump(td, open('taskdef-rendered.json', 'w', encoding='utf-8'), indent=2)
                PY
                NEW_TASK_DEF=$(aws ecs register-task-definition --cli-input-json file://taskdef-rendered.json --query 'taskDefinition.taskDefinitionArn' --output text)
                echo "$NEW_TASK_DEF" > new-taskdef.txt
                aws ecs update-service --cluster "${{{{ vars.ECS_CLUSTER }}}}" --service "${{{{ vars.ECS_SERVICE }}}}" --task-definition "$NEW_TASK_DEF"
                aws ecs wait services-stable --cluster "${{{{ vars.ECS_CLUSTER }}}}" --services "${{{{ vars.ECS_SERVICE }}}}"
            - name: Roll back ECS deployment
              if: ${{{{ failure() }}}}
              shell: bash
              run: |
                set -euo pipefail
                if [ -f previous-taskdef.txt ]; then
                  aws ecs update-service --cluster "${{{{ vars.ECS_CLUSTER }}}}" --service "${{{{ vars.ECS_SERVICE }}}}" --task-definition "$(cat previous-taskdef.txt)"
                  aws ecs wait services-stable --cluster "${{{{ vars.ECS_CLUSTER }}}}" --services "${{{{ vars.ECS_SERVICE }}}}"
                fi
            """
        ).rstrip()
    if target == 'eks':
        return dedent(
            f"""\
            - name: Configure AWS credentials
              uses: {use('aws-actions/configure-aws-credentials', versions)}
              with:
                aws-access-key-id: ${{{{ secrets.AWS_ACCESS_KEY_ID }}}}
                aws-secret-access-key: ${{{{ secrets.AWS_SECRET_ACCESS_KEY }}}}
                aws-region: ${{{{ vars.AWS_REGION }}}}
            - name: Configure kubeconfig for EKS
              shell: bash
              run: |
                set -euo pipefail
                aws eks update-kubeconfig --name "${{{{ vars.EKS_CLUSTER }}}}" --region "${{{{ vars.AWS_REGION }}}}"
            - name: Deploy to EKS
              shell: bash
              run: |
                set -euo pipefail
                kubectl set image deployment/${{{{ vars.K8S_DEPLOYMENT }}}} ${{{{ vars.K8S_CONTAINER }}}}=${{{{ steps.image.outputs.image_ref }}}} -n "${{{{ vars.K8S_NAMESPACE }}}}"
                kubectl rollout status deployment/${{{{ vars.K8S_DEPLOYMENT }}}} -n "${{{{ vars.K8S_NAMESPACE }}}}" --timeout=300s
            - name: Roll back EKS deployment
              if: ${{{{ failure() }}}}
              shell: bash
              run: |
                set -euo pipefail
                kubectl rollout undo deployment/${{{{ vars.K8S_DEPLOYMENT }}}} -n "${{{{ vars.K8S_NAMESPACE }}}}"
                kubectl rollout status deployment/${{{{ vars.K8S_DEPLOYMENT }}}} -n "${{{{ vars.K8S_NAMESPACE }}}}" --timeout=300s
            """
        ).rstrip()
    if target == 'lambda':
        return dedent(
            f"""\
            - name: Configure AWS credentials
              uses: {use('aws-actions/configure-aws-credentials', versions)}
              with:
                aws-access-key-id: ${{{{ secrets.AWS_ACCESS_KEY_ID }}}}
                aws-secret-access-key: ${{{{ secrets.AWS_SECRET_ACCESS_KEY }}}}
                aws-region: ${{{{ vars.AWS_REGION }}}}
            - name: Capture current Lambda image
              shell: bash
              run: |
                set -euo pipefail
                aws lambda get-function --function-name "${{{{ vars.LAMBDA_FUNCTION_NAME }}}}" --query 'Code.ImageUri' --output text > previous-image.txt
            - name: Deploy to Lambda
              shell: bash
              run: |
                set -euo pipefail
                aws lambda update-function-code --function-name "${{{{ vars.LAMBDA_FUNCTION_NAME }}}}" --image-uri "${{{{ steps.image.outputs.image_ref }}}}"
                aws lambda wait function-updated --function-name "${{{{ vars.LAMBDA_FUNCTION_NAME }}}}"
            - name: Roll back Lambda deployment
              if: ${{{{ failure() }}}}
              shell: bash
              run: |
                set -euo pipefail
                if [ -f previous-image.txt ]; then
                  aws lambda update-function-code --function-name "${{{{ vars.LAMBDA_FUNCTION_NAME }}}}" --image-uri "$(cat previous-image.txt)"
                  aws lambda wait function-updated --function-name "${{{{ vars.LAMBDA_FUNCTION_NAME }}}}"
                fi
            """
        ).rstrip()
    if target == 'aca':
        return dedent(
            f"""\
            - name: Login to Azure
              uses: {use('azure/login', versions)}
              with:
                creds: ${{{{ secrets.AZURE_CREDENTIALS }}}}
            - name: Capture current ACA revision
              shell: bash
              run: |
                set -euo pipefail
                az extension add --name containerapp --upgrade
                az containerapp revision list --name "${{{{ vars.ACA_APP_NAME }}}}" --resource-group "${{{{ vars.ACA_RESOURCE_GROUP }}}}" --query "[?properties.active].name | [0]" -o tsv > previous-revision.txt
            - name: Deploy to Azure Container Apps
              uses: {use('azure/container-apps-deploy-action', versions)}
              with:
                acrName: ${{{{ vars.ACR_NAME }}}}
                resourceGroup: ${{{{ vars.ACA_RESOURCE_GROUP }}}}
                containerAppName: ${{{{ vars.ACA_APP_NAME }}}}
                imageToDeploy: ${{{{ steps.image.outputs.image_ref }}}}
            - name: Roll back ACA deployment
              if: ${{{{ failure() }}}}
              shell: bash
              run: |
                set -euo pipefail
                if [ -f previous-revision.txt ]; then
                  az containerapp revision activate --name "${{{{ vars.ACA_APP_NAME }}}}" --resource-group "${{{{ vars.ACA_RESOURCE_GROUP }}}}" --revision "$(cat previous-revision.txt)"
                fi
            """
        ).rstrip()
    if target == 'cloudrun':
        return dedent(
            f"""\
            - name: Authenticate to Google Cloud
              uses: {use('google-github-actions/auth', versions)}
              with:
                credentials_json: ${{{{ secrets.GCP_SA_KEY }}}}
            - name: Capture current Cloud Run revision
              shell: bash
              run: |
                set -euo pipefail
                gcloud run services describe "${{{{ vars.CLOUDRUN_SERVICE }}}}" --region "${{{{ vars.GCP_REGION }}}}" --format='value(status.latestReadyRevisionName)' > previous-revision.txt
            - name: Deploy to Cloud Run
              uses: {use('google-github-actions/deploy-cloudrun', versions)}
              with:
                service: ${{{{ vars.CLOUDRUN_SERVICE }}}}
                region: ${{{{ vars.GCP_REGION }}}}
                image: ${{{{ steps.image.outputs.image_ref }}}}
            - name: Roll back Cloud Run deployment
              if: ${{{{ failure() }}}}
              shell: bash
              run: |
                set -euo pipefail
                if [ -f previous-revision.txt ]; then
                  gcloud run services update-traffic "${{{{ vars.CLOUDRUN_SERVICE }}}}" --region "${{{{ vars.GCP_REGION }}}}" --to-revisions "$(cat previous-revision.txt)=100"
                fi
            """
        ).rstrip()
    return dedent(
        """\
        - name: Configure kubeconfig
          shell: bash
          run: |
            set -euo pipefail
            mkdir -p ~/.kube
            echo "${{ secrets.KUBECONFIG_B64 }}" | base64 --decode > ~/.kube/config
        - name: Deploy to Kubernetes
          shell: bash
          run: |
            set -euo pipefail
            kubectl set image deployment/${{ vars.K8S_DEPLOYMENT }} ${{ vars.K8S_CONTAINER }}=${{ steps.image.outputs.image_ref }} -n "${{ vars.K8S_NAMESPACE }}"
            kubectl rollout status deployment/${{ vars.K8S_DEPLOYMENT }} -n "${{ vars.K8S_NAMESPACE }}" --timeout=300s
        - name: Roll back Kubernetes deployment
          if: ${{ failure() }}
          shell: bash
          run: |
            set -euo pipefail
            kubectl rollout undo deployment/${{ vars.K8S_DEPLOYMENT }} -n "${{ vars.K8S_NAMESPACE }}"
            kubectl rollout status deployment/${{ vars.K8S_DEPLOYMENT }} -n "${{ vars.K8S_NAMESPACE }}" --timeout=300s
        """
    ).rstrip()


def build_cd_workflow(config: Dict[str, Any], env_config: Dict[str, Any], versions: Dict[str, Dict[str, str]]) -> str:
    registry = registry_config(config, versions)
    reports_folder = config.get('reports', {}).get('folder', '.github/reports')
    retention_days = int(config.get('reports', {}).get('retention_days', 90))
    env_name = env_config['name']
    env_slug = env_name.lower().replace(' ', '-')
    target = env_config['target']
    smoke_url = env_config.get('smoke_test_url') or config.get('cd', {}).get('smoke_test_url', '')
    if env_config.get('auto_deploy', False):
        triggers = dedent(
            """\
              workflow_dispatch:
                inputs:
                  image_tag:
                    description: Image tag to deploy
                    required: true
              push:
                branches: [main]
            """
        ).rstrip()
    else:
        triggers = dedent(
            """\
              workflow_dispatch:
                inputs:
                  image_tag:
                    description: Image tag to deploy
                    required: true
            """
        ).rstrip()
    deploy_steps = join_blocks(
        dedent(f"""\
        - name: Checkout repository
          uses: {use('actions/checkout', versions)}
        - name: Capture run metadata
          id: meta
          shell: bash
          run: |
            set -euo pipefail
            echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
        - name: Resolve image reference
          id: image
          shell: bash
          run: |
            set -euo pipefail
            if [ "${{{{ github.event_name }}}}" = "workflow_dispatch" ] && [ -n "${{{{ inputs.image_tag }}}}" ]; then
              TAG="${{{{ inputs.image_tag }}}}"
            else
              TAG="sha-${{{{ github.sha }}}}"
            fi
            echo "image_ref={registry['registry_image']}:$TAG" >> "$GITHUB_OUTPUT"
            echo "image_tag=$TAG" >> "$GITHUB_OUTPUT"
        """),
        registry['login_steps'],
        dedent(
            """\
            - name: Pull image from registry
              shell: bash
              run: |
                set -euo pipefail
                docker pull "${{ steps.image.outputs.image_ref }}"
            """
        ),
        cd_target_blocks(target, versions),
        dedent(
            f"""\
            - name: Run smoke tests
              if: ${{{{ success() }}}}
              shell: bash
              run: |
                set -euo pipefail
                if [ -n {quote(smoke_url)} ]; then
                  curl --fail --show-error --silent --retry 5 --retry-delay 10 {quote(smoke_url)}
                else
                  echo "No smoke test URL configured; skipping."
                fi
            - name: Generate deployment report
              if: ${{{{ always() }}}}
              shell: bash
              run: |
                set -euo pipefail
                mkdir -p deployment-report
                cat <<REPORT > deployment-report/deployment-report.md
                # Deployment Report

                - Date: ${{{{ steps.meta.outputs.run_date }}}}
                - Environment: {env_name}
                - Target: {target}
                - Image: ${{{{ steps.image.outputs.image_ref }}}}
                - Workflow status: ${{{{ job.status }}}}
                - Smoke URL: {smoke_url or 'not-configured'}
                REPORT
            - name: Upload deployment report artifact
              if: ${{{{ always() }}}}
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: deployment-report-{env_slug}-${{{{ steps.meta.outputs.run_date }}}}
                path: deployment-report/deployment-report.md
                retention-days: {retention_days}
            - name: Commit deployment report
              if: ${{{{ always() }}}}
              shell: bash
              env:
                REPORTS_DIR: {quote(reports_folder)}
              run: |
                set -euo pipefail
                REPORT_DATE="$(date +%F)"
                TARGET_DIR="$REPORTS_DIR/{env_slug}/$REPORT_DATE"
                mkdir -p "$TARGET_DIR"
                cp deployment-report/deployment-report.md "$TARGET_DIR/"
                git config user.name "github-actions[bot]"
                git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
                git add "$REPORTS_DIR"
                git diff --cached --quiet && exit 0
                git commit -m "chore: update deployment report for {env_slug} [skip ci]"
                git push
            """
        ),
    )
    notify_steps = dedent(
        f"""\
        - name: Checkout repository
          uses: {use('actions/checkout', versions)}
        - name: Publish deployment summary
          shell: bash
          run: |
            set -euo pipefail
            echo "Deployment to {env_name} finished with status: ${{{{ needs.deploy-{env_slug}.result }}}}" >> "$GITHUB_STEP_SUMMARY"
        """
    )
    return render_template(
        TEMPLATE_ROOT / 'cd' / f'cd-{target}.yml',
        {
            'ENV_NAME': env_name,
            'ENV_SLUG': env_slug,
            'TRIGGERS': triggers,
            'PERMISSIONS': "  contents: write\n  packages: read\n  id-token: write",
            'DEPLOY_STEPS': indent_block(deploy_steps, 6),
            'NOTIFY_STEPS': indent_block(notify_steps, 6),
        },
    )


def build_integration_workflow(config: Dict[str, Any], versions: Dict[str, Dict[str, str]]) -> str:
    profile = language_profile(config['language'], config, versions)
    reports_folder = config.get('reports', {}).get('folder', '.github/reports')
    retention_days = int(config.get('reports', {}).get('retention_days', 90))
    envs = config.get('cd', {}).get('environments', [])
    trigger_workflow = 'CD - staging'
    default_env = 'staging'
    for env in envs:
        if env.get('name', '').lower() == 'staging':
            trigger_workflow = f"CD - {env['name']}"
            default_env = env['name']
            break
    else:
        if envs:
            trigger_workflow = f"CD - {envs[0]['name']}"
            default_env = envs[0]['name']
    summary_script = dedent(
        """\
        import os
        from pathlib import Path
        report_dir = Path('integration-report')
        report_dir.mkdir(parents=True, exist_ok=True)
        exit_code = int(Path('test-results/exit-code.txt').read_text(encoding='utf-8').strip()) if Path('test-results/exit-code.txt').exists() else 0
        lines = [
            '# Integration Test Report',
            '',
            f'- Environment: {os.environ.get("TARGET_ENV", "staging")}',
            f'- Base URL: {os.environ.get("BASE_URL", "") or "not-set"}',
            f'- Exit code: {exit_code}',
            '',
        ]
        junit_files = sorted(Path('test-results').glob('*.xml'))
        if junit_files:
            lines.append('JUnit artifacts generated:')
            for junit in junit_files:
                lines.append(f'- {junit.name}')
        else:
            lines.append('No JUnit XML was generated by the selected integration command.')
        Path('integration-report/summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        """
    )
    steps = join_blocks(
        dedent(f"""\
        - name: Checkout repository
          uses: {use('actions/checkout', versions)}
        """),
        profile['setup'],
        profile['install'],
        dedent(
            f"""\
            - name: Resolve integration target
              id: target
              shell: bash
              env:
                INPUT_BASE_URL: ${{{{ inputs.base_url }}}}
                DEFAULT_BASE_URL: ${{{{ vars.INTEGRATION_BASE_URL }}}}
              run: |
                set -euo pipefail
                echo "base_url=${{INPUT_BASE_URL:-$DEFAULT_BASE_URL}}" >> "$GITHUB_OUTPUT"
            - name: Run integration test suite
              shell: bash
              env:
                BASE_URL: ${{{{ steps.target.outputs.base_url }}}}
              run: |
                set -euo pipefail
                mkdir -p test-results
                EXIT_CODE=0
{indent_block(profile['integration'], 16)} || EXIT_CODE=$?
                echo "$EXIT_CODE" > test-results/exit-code.txt
            - name: Generate integration report
              if: ${{{{ always() }}}}
              shell: bash
              env:
                TARGET_ENV: ${{{{ inputs.environment || '{default_env}' }}}}
                BASE_URL: ${{{{ steps.target.outputs.base_url }}}}
              run: |
                set -euo pipefail
{indent_block("python3 - <<'PY'\n" + summary_script + "PY", 16)}
            - name: Upload integration report artifact
              if: ${{{{ always() }}}}
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: integration-report-${{{{ steps.meta.outputs.run_date }}}}
                path: |
                  integration-report
                  test-results
                retention-days: {retention_days}
            - name: Publish integration summary
              if: ${{{{ always() }}}}
              shell: bash
              run: |
                set -euo pipefail
                cat integration-report/summary.md >> "$GITHUB_STEP_SUMMARY"
            - name: Commit integration report
              if: ${{{{ always() }}}}
              shell: bash
              env:
                REPORTS_DIR: {quote(reports_folder)}
              run: |
                set -euo pipefail
                REPORT_DATE="$(date +%F)"
                TARGET_DIR="$REPORTS_DIR/integration/$REPORT_DATE"
                mkdir -p "$TARGET_DIR"
                cp -R integration-report/. "$TARGET_DIR/"
                git config user.name "github-actions[bot]"
                git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
                git add "$REPORTS_DIR"
                git diff --cached --quiet && exit 0
                git commit -m "chore: update integration report [skip ci]"
                git push
            - name: Fail if integration tests failed
              shell: bash
              run: |
                set -euo pipefail
                test "$(cat test-results/exit-code.txt)" -eq 0
            """
        ),
    )
    return render_template(
        TEMPLATE_ROOT / 'integration-tests.yml',
        {
            'TRIGGER_WORKFLOW_NAME': trigger_workflow,
            'DEFAULT_ENV': default_env,
            'INTEGRATION_STEPS': indent_block(steps, 6),
        },
    )

def build_image_scan_workflow(config: Dict[str, Any], versions: Dict[str, Dict[str, str]]) -> str:
    registry = registry_config(config, versions)
    retention_days = int(config.get('reports', {}).get('retention_days', 90))
    reports_folder = config.get('reports', {}).get('folder', '.github/reports')
    image_scan = config.get('image_scan', {})
    scan_on = image_scan.get('scan_on', 'both')
    cron = image_scan.get('schedule', '0 6 * * *')
    scan_triggers = ['  workflow_dispatch:', '    inputs:', '      image_tag:', '        description: Image tag to scan', '        required: false']
    if scan_on in {'push', 'both'}:
        scan_triggers.extend(['  push:', '    branches: [main]'])
    if scan_on in {'schedule', 'both'}:
        scan_triggers.extend(['  schedule:', f"    - cron: '{cron}'"])

    def scan_common_steps() -> str:
        return join_blocks(
            dedent(f"""\
            - name: Checkout repository
              uses: {use('actions/checkout', versions)}
            - name: Capture run metadata
              id: meta
              shell: bash
              run: |
                set -euo pipefail
                echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
            - name: Resolve image reference
              id: image
              shell: bash
              run: |
                set -euo pipefail
                if [ -n "${{{{ inputs.image_tag }}}}" ]; then
                  TAG="${{{{ inputs.image_tag }}}}"
                elif [ "${{{{ github.event_name }}}}" = "push" ]; then
                  TAG="sha-${{{{ github.sha }}}}"
                else
                  TAG="latest"
                fi
                echo "image_ref={registry['registry_image']}:$TAG" >> "$GITHUB_OUTPUT"
            """),
            registry['login_steps'],
        )

    trivy_steps = join_blocks(
        scan_common_steps(),
        dedent(
            f"""\
            - name: Run Trivy image scan
              uses: {use('aquasecurity/trivy-action', versions)}
              with:
                image-ref: ${{{{ steps.image.outputs.image_ref }}}}
                format: sarif
                output: trivy.sarif
                ignore-unfixed: true
                severity: CRITICAL,HIGH
                exit-code: '0'
            - name: Upload Trivy SARIF
              uses: {use('github/codeql-action/upload-sarif', versions)}
              with:
                sarif_file: trivy.sarif
            - name: Upload Trivy artifact
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: trivy-results-${{{{ steps.meta.outputs.run_date }}}}
                path: trivy.sarif
                retention-days: {retention_days}
            """
        ),
    )
    grype_steps = join_blocks(
        scan_common_steps(),
        dedent(
            f"""\
            - name: Run Grype image scan
              uses: {use('anchore/scan-action', versions)}
              with:
                image: ${{{{ steps.image.outputs.image_ref }}}}
                fail-build: false
                severity-cutoff: high
                output-format: sarif
                output-file: grype.sarif
            - name: Upload Grype SARIF
              uses: {use('github/codeql-action/upload-sarif', versions)}
              with:
                sarif_file: grype.sarif
            - name: Upload Grype artifact
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: grype-results-${{{{ steps.meta.outputs.run_date }}}}
                path: grype.sarif
                retention-days: {retention_days}
            """
        ),
    )
    consolidate_script = dedent(
        """\
        import json
        import os
        from pathlib import Path

        reports_dir = Path(os.environ['REPORTS_DIR'])
        today = os.environ['RUN_DATE']
        compare_n1 = os.environ['COMPARE_N1'].lower() == 'true'

        def load_sarif_ids(path: Path):
            payload = json.loads(path.read_text(encoding='utf-8'))
            ids = []
            for run in payload.get('runs', []):
                for result in run.get('results', []):
                    rule_id = result.get('ruleId') or 'UNKNOWN'
                    ids.append(rule_id)
            return sorted(set(ids))

        current = sorted(set(load_sarif_ids(Path('artifacts/trivy.sarif')) + load_sarif_ids(Path('artifacts/grype.sarif'))))
        previous = []
        previous_file = None
        if compare_n1 and reports_dir.exists():
            dated_dirs = sorted([path for path in reports_dir.rglob('*') if path.is_dir() and path.name != today and len(path.name) == 10], reverse=True)
            for dated in dated_dirs:
                candidate = dated / 'image-scan-findings.json'
                if candidate.exists():
                    previous_file = candidate
                    previous = json.loads(candidate.read_text(encoding='utf-8'))
                    break
        previous_set = set(previous)
        current_set = set(current)
        new_issues = sorted(current_set - previous_set)
        fixed_issues = sorted(previous_set - current_set)
        Path('image-scan-findings.json').write_text(json.dumps(current, indent=2), encoding='utf-8')
        lines = ['# Image Scan Report', '', f'- Previous report: {previous_file if previous_file else "none"}', f'- Current findings: {len(current)}', f'- New findings: {len(new_issues)}', '', '## Findings', '']
        lines.extend(f'- {item}' for item in current) if current else lines.append('- No CRITICAL/HIGH findings in current SARIF inputs')
        if new_issues:
            lines.extend(['', '## New since previous report', ''])
            lines.extend(f'- {item}' for item in new_issues)
        if fixed_issues:
            lines.extend(['', '## Fixed since previous report', ''])
            lines.extend(f'- {item}' for item in fixed_issues)
        Path('consolidated-report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as handle:
            handle.write(f"regression={'true' if bool(new_issues) else 'false'}\n")
        """
    )
    email_step = dedent(
        f"""\
        - name: Email image scan report
          if: ${{{{ always() }}}}
          shell: bash
          env:
            EMAIL_TO: {quote(image_scan.get('email_to', ''))}
            EMAIL_PROVIDER: {quote(image_scan.get('email_provider', 'ses'))}
          run: |
            set -euo pipefail
            if [ -z "$EMAIL_TO" ]; then
              echo "No report recipient configured; skipping email."
            else
              echo "Prepared ${{EMAIL_PROVIDER}} notification for $EMAIL_TO" >> "$GITHUB_STEP_SUMMARY"
            fi
        """
    )
    consolidate_steps = join_blocks(
        dedent(f"""\
        - name: Checkout repository
          uses: {use('actions/checkout', versions)}
        - name: Capture run metadata
          id: meta
          shell: bash
          run: |
            set -euo pipefail
            echo "run_date=$(date +%F)" >> "$GITHUB_OUTPUT"
        - name: Download scan artifacts
          uses: {use('actions/download-artifact', versions)}
          with:
            path: artifacts
        - name: Flatten scan artifacts
          shell: bash
          run: |
            set -euo pipefail
            find artifacts -name '*.sarif' -exec cp {{}} artifacts/ \\;
        - name: Consolidate image scan reports
          id: consolidate
          shell: bash
          env:
            REPORTS_DIR: {quote(reports_folder)}
            RUN_DATE: ${{{{ steps.meta.outputs.run_date }}}}
            COMPARE_N1: {quote('true' if image_scan.get('compare_n1', True) else 'false')}
          run: |
            set -euo pipefail
{indent_block("python3 - <<'PY'\n" + consolidate_script + "PY", 12)}
        - name: Upload consolidated image scan artifact
          uses: {use('actions/upload-artifact', versions)}
          with:
            name: image-scan-report-${{{{ steps.meta.outputs.run_date }}}}
            path: |
              consolidated-report.md
              image-scan-findings.json
            retention-days: {retention_days}
        - name: Commit image scan report
          shell: bash
          env:
            REPORTS_DIR: {quote(reports_folder)}
          run: |
            set -euo pipefail
            REPORT_DATE="$(date +%F)"
            TARGET_DIR="$REPORTS_DIR/image-scans/$REPORT_DATE"
            mkdir -p "$TARGET_DIR"
            cp consolidated-report.md image-scan-findings.json "$TARGET_DIR/"
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add "$REPORTS_DIR"
            git diff --cached --quiet && exit 0
            git commit -m "chore: update image scan report [skip ci]"
            git push
        """),
        email_step,
        dedent(
            f"""\
            - name: Fail on new CRITICAL/HIGH findings
              if: ${{{{ steps.consolidate.outputs.regression == 'true' && {str(bool(image_scan.get('fail_on_critical', True))).lower()} }}}}
              shell: bash
              run: |
                set -euo pipefail
                echo "New CRITICAL/HIGH findings detected versus n-1."
                exit 1
            """
        ),
    )
    scout_steps = join_blocks(
        scan_common_steps(),
        dedent(
            f"""\
            - name: Evaluate Docker Scout policies
              uses: {use('docker/scout-action', versions)}
              with:
                command: cves
                image: ${{{{ steps.image.outputs.image_ref }}}}
                only-severities: critical,high
                output: scout-report.md
            - name: Upload Docker Scout artifact
              uses: {use('actions/upload-artifact', versions)}
              with:
                name: docker-scout-${{{{ steps.meta.outputs.run_date }}}}
                path: scout-report.md
                if-no-files-found: warn
                retention-days: {retention_days}
            """
        ),
    )
    return render_template(
        TEMPLATE_ROOT / 'image-scan.yml',
        {
            'SCAN_TRIGGERS': '\n'.join(scan_triggers),
            'TRIVY_STEPS': indent_block(trivy_steps, 6),
            'GRYPE_STEPS': indent_block(grype_steps, 6),
            'CONSOLIDATE_STEPS': indent_block(consolidate_steps, 6),
            'SCOUT_STEPS': indent_block(scout_steps, 6),
        },
    )


def build_regression_workflow(config: Dict[str, Any], versions: Dict[str, Dict[str, str]]) -> str:
    """Generate regression-tests.yml using the regression-tests.yml template."""
    profile = language_profile(config['language'], config, versions)
    reports_folder = config.get('reports', {}).get('folder', '.github/reports')
    retention_days = int(config.get('reports', {}).get('retention_days', 90))
    regression = config.get('regression', {})
    base_url = regression.get('base_url', 'https://staging.example.com')
    test_cmd = regression.get('test_command', profile.get('test_cmd', 'npm test -- --testPathPattern=regression'))
    trigger_env = regression.get('trigger_env', 'staging')

    # Determine staging env name for workflow_run trigger
    envs = config.get('cd', {}).get('environments', [])
    staging_env_name = trigger_env
    for env in envs:
        if env.get('name', '').lower() in ('staging', trigger_env.lower()):
            staging_env_name = env['name']
            break

    template_path = TEMPLATE_ROOT / 'regression-tests.yml'
    return render_template(
        template_path,
        {
            'STAGING_ENV_NAME': staging_env_name,
            'REGRESSION_BASE_URL': base_url,
            'REGRESSION_TEST_CMD': test_cmd,
            'REPORTS_FOLDER': reports_folder,
            'RETENTION_DAYS': str(retention_days),
            'CHECKOUT_ACTION': use('actions/checkout', versions),
            'CACHE_ACTION': use('actions/cache', versions),
            'UPLOAD_ARTIFACT_ACTION': use('actions/upload-artifact', versions),
            'SETUP_LANGUAGE_STEP': profile.get('setup', '').rstrip(),
            'INSTALL_CMD': profile.get('install_cmd', 'npm ci'),
            'CACHE_PATH': profile.get('cache_path', '~/.npm'),
            'LOCKFILE': profile.get('lockfile', 'package-lock.json'),
        },
    )


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + '\n', encoding='utf-8')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Generate GitHub Actions workflows from a saved configuration JSON.')
    parser.add_argument('--config', required=True, help='Path to the workflow configuration JSON from collect_info.py')
    parser.add_argument('--output', help='Optional repository root override. Defaults to repo_path from config.')
    parser.add_argument('--validate', action='store_true', help='Run validate_workflows.py after generating files.')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_json(Path(args.config).expanduser())
    versions = load_action_versions()
    repo_root = Path(args.output or config['repo_path']).expanduser().resolve()
    workflows_root = repo_root / config.get('github_actions_folder', '.github/workflows')
    written: List[Path] = []

    workflows_cfg = config.get('workflows', {})

    if workflows_cfg.get('ci', True):
        ci_path = workflows_root / 'ci.yml'
        print(f"⚙️  Creating CI workflow → {ci_path}")
        ci_cfg = config.get('ci', {})
        registry = ci_cfg.get('docker_registry', 'ghcr')
        image_name = ci_cfg.get('image_name', project_repo_slug(repo_root))
        print(f"    Docker registry : {registry}")
        print(f"    Image name      : {image_name}")
        print(f"    Coverage gate   : {ci_cfg.get('coverage_threshold', 80)}%")
        write_file(ci_path, build_ci_workflow(config, versions))
        written.append(ci_path)
        print(f"    ✅ Written: {ci_path}")

    if workflows_cfg.get('cd', True):
        envs = config.get('cd', {}).get('environments', [])
        for env_config in envs:
            env_name = env_config['name']
            target = env_config.get('target', 'ecs')
            auto = env_config.get('auto_deploy', True)
            approval = env_config.get('approval_required', False)
            target_path = workflows_root / f"cd-{env_name.lower().replace(' ', '-')}.yml"
            print(f"⚙️  Creating CD workflow for '{env_name}' → {target_path}")
            print(f"    Target          : {target}")
            print(f"    Auto-deploy     : {auto}")
            print(f"    Approval gate   : {approval}")
            write_file(target_path, build_cd_workflow(config, env_config, versions))
            written.append(target_path)
            print(f"    ✅ Written: {target_path}")

    if workflows_cfg.get('integration_tests', True):
        integration_path = workflows_root / 'integration-tests.yml'
        print(f"⚙️  Creating integration tests workflow → {integration_path}")
        write_file(integration_path, build_integration_workflow(config, versions))
        written.append(integration_path)
        print(f"    ✅ Written: {integration_path}")

    if workflows_cfg.get('regression_tests', True):
        regression_path = workflows_root / 'regression-tests.yml'
        reg_cfg = config.get('regression', {})
        print(f"⚙️  Creating regression tests workflow → {regression_path}")
        print(f"    Base URL        : {reg_cfg.get('base_url', 'https://staging.example.com')}")
        print(f"    Test command    : {reg_cfg.get('test_command', '<auto-detected>')}")
        write_file(regression_path, build_regression_workflow(config, versions))
        written.append(regression_path)
        print(f"    ✅ Written: {regression_path}")

    if workflows_cfg.get('image_scan', True):
        image_scan_path = workflows_root / 'image-scan.yml'
        scan_cfg = config.get('image_scan', {})
        print(f"⚙️  Creating image scanning workflow → {image_scan_path}")
        print(f"    Schedule        : {scan_cfg.get('schedule', '0 6 * * *')}")
        print(f"    Email report to : {scan_cfg.get('email_to', '(not configured)')}")
        write_file(image_scan_path, build_image_scan_workflow(config, versions))
        written.append(image_scan_path)
        print(f"    ✅ Written: {image_scan_path}")

    print(f"\n✅ Done — {len(written)} workflow file(s) generated:")
    for p in written:
        print(f"   {p}")

    print(json.dumps({'generated_files': [str(path) for path in written]}, indent=2))
    if args.validate:
        validator = Path(__file__).resolve().parent / 'validate_workflows.py'
        result = subprocess.run([sys.executable, str(validator), str(workflows_root)], check=False)
        return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
