#!/usr/bin/env python3
"""Validate scaffolded webapps against WAP and SEC rules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
RuleResult = Dict[str, str]


CREDENTIAL_PATTERN = re.compile(
    r"(?:snippet_id|app_id|website_id)\s*[:=]\s*[\'\"](?P<value>[^\'\"]+)[\'\"]",
    re.IGNORECASE,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a scaffolded webapp against WAP and SEC rules.")
    parser.add_argument("project_dir", help="Path to the generated webapp directory.")
    return parser.parse_args(argv)


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_json(path: Path) -> Dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def src_files(project_dir: Path) -> List[Path]:
    src = project_dir / "src"
    return [path for path in src.rglob("*") if path.suffix in {".js", ".jsx", ".ts", ".tsx"}]


def src_text(project_dir: Path) -> str:
    return "\n".join(safe_read(path) for path in src_files(project_dir))


def format_table(rows: List[Tuple[str, str, str, str]]) -> str:
    headers = ("Rule", "Severity", "Status", "Message")
    widths = [len(item) for item in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row: Tuple[str, str, str, str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([render(headers), separator, *[render(row) for row in rows]])


def check_css_custom_properties(project_dir: Path) -> Tuple[bool, str]:
    index_css = safe_read(project_dir / "src" / "index.css")
    app_css = safe_read(project_dir / "src" / "App.css")
    has_root_vars = ":root" in index_css and all(token in index_css for token in ["--brand:", "--accent:", "--bg:"])
    uses_vars = all(token in app_css for token in ["var(--brand)", "var(--accent)", "min-height: 100vh"])
    return has_root_vars and uses_vars, "Brand tokens defined in index.css and consumed from App.css."


def check_chat_credentials(project_dir: Path) -> Tuple[bool, str]:
    findings: List[str] = []
    for path in src_files(project_dir):
        for match in CREDENTIAL_PATTERN.finditer(safe_read(path)):
            value = match.group('value').strip()
            if value:
                findings.append(f"{path.relative_to(project_dir)}:{match.group(0)}")
    if findings:
        sample = "; ".join(findings[:3])
        return False, f"Hardcoded chat credential literal found: {sample}"
    return True, "No hardcoded chat provider credentials found in source files."


def check_csp(project_dir: Path) -> Tuple[bool, str]:
    index_html = safe_read(project_dir / "index.html")
    passed = "Content-Security-Policy" in index_html
    return passed, "index.html includes a Content-Security-Policy meta tag."


def check_chat_widget_cleanup(project_dir: Path) -> Tuple[bool, str]:
    widget_path = project_dir / "src" / "components" / "ChatWidget.jsx"
    if not widget_path.exists():
        return True, "ChatWidget.jsx not generated; cleanup rule not applicable."
    widget = safe_read(widget_path)
    has_cleanup = "return () =>" in widget and any(token in widget for token in ["disconnect()", "observer.disconnect", "removeEventListener", ".remove("])
    return has_cleanup, "ChatWidget.jsx cleans up listeners, observers, or injected elements in useEffect cleanup."


def check_global_this(project_dir: Path) -> Tuple[bool, str]:
    vite = safe_read(project_dir / "vite.config.js")
    return "global: 'globalThis'" in vite, "Vite defines global: 'globalThis' for browser compatibility with third-party widget SDKs."


def check_svg_aria(project_dir: Path) -> Tuple[bool, str]:
    sources = [safe_read(path) for path in src_files(project_dir)]
    inline_svgs = re.findall(r"<svg[^>]*>", "\n".join(sources))
    missing = [tag for tag in inline_svgs if 'aria-hidden="true"' not in tag and "aria-hidden='true'" not in tag]
    return not missing, 'All inline decorative SVG tags use aria-hidden="true".'


def check_gitignore(project_dir: Path) -> Tuple[bool, str]:
    gitignore = safe_read(project_dir / ".gitignore")
    passed = re.search(r"(?m)^dist/$", gitignore) is not None
    return passed, "dist/ is ignored in .gitignore."


def check_host_true(project_dir: Path) -> Tuple[bool, str]:
    vite = safe_read(project_dir / "vite.config.js")
    server_pass = re.search(r"server:\s*\{[^}]*host:\s*true", vite, re.DOTALL) is not None
    preview_pass = re.search(r"preview:\s*\{[^}]*host:\s*true", vite, re.DOTALL) is not None
    return server_pass and preview_pass, "Vite server and preview bind host: true."


def check_mobile_breakpoints(project_dir: Path) -> Tuple[bool, str]:
    app_css = safe_read(project_dir / "src" / "App.css")
    passed = "@media (min-width: 640px)" in app_css and "@media (min-width: 768px)" in app_css
    return passed, "App.css includes 640px and 768px responsive breakpoints."


def check_touch_targets(project_dir: Path) -> Tuple[bool, str]:
    combined = safe_read(project_dir / "src" / "App.css") + "\n" + safe_read(project_dir / "src" / "index.css")
    passed = re.search(r"button[^\{]*,[^\{]*a[^\{]*\{[^}]*min-height:\s*44px", combined, re.DOTALL) is not None
    return passed, "CSS enforces 44px minimum touch targets for buttons and links."


def check_test_scripts(project_dir: Path) -> Tuple[bool, str]:
    package_data = read_json(project_dir / "package.json")
    scripts = package_data.get("scripts") if isinstance(package_data, dict) else {}
    required = {"test", "test:coverage", "test:e2e", "audit"}
    passed = isinstance(scripts, dict) and required.issubset(scripts.keys())
    return passed, "package.json includes required test and audit scripts."


def check_vitest_thresholds(project_dir: Path) -> Tuple[bool, str]:
    vitest = safe_read(project_dir / "vitest.config.js")
    passed = bool(vitest) and "thresholds" in vitest and all(token in vitest for token in ["statements: 80", "branches: 80", "functions: 80", "lines: 80"])
    return passed, "vitest.config.js exists and sets 80% coverage thresholds."


def check_playwright_mobile(project_dir: Path) -> Tuple[bool, str]:
    content = safe_read(project_dir / "playwright.config.js")
    passed = all(token in content for token in ["Pixel 7", "iPhone 14", "iPad (gen 7)"])
    return passed, "playwright.config.js includes Pixel 7, iPhone 14, and iPad projects."


def check_build_target(project_dir: Path) -> Tuple[bool, str]:
    vite = safe_read(project_dir / "vite.config.js")
    passed = "target: 'es2020'" in vite or 'target: "es2020"' in vite
    return passed, "Vite build target is es2020 or newer."


def check_sourcemap(project_dir: Path) -> Tuple[bool, str]:
    vite = safe_read(project_dir / "vite.config.js")
    passed = "sourcemap" in vite
    return passed, "vite.config.js configures sourcemap behaviour for production builds."


def check_manual_chunks(project_dir: Path) -> Tuple[bool, str]:
    vite = safe_read(project_dir / "vite.config.js")
    passed = "manualChunks" in vite and "vendor" in vite and "react-dom" in vite
    return passed, "Vite separates vendor chunks from app code."


def check_package_lock(project_dir: Path) -> Tuple[bool, str]:
    return (project_dir / "package-lock.json").exists(), "package-lock.json exists for lockfile integrity."


def check_dependency_versions(project_dir: Path) -> Tuple[bool, str]:
    package_data = read_json(project_dir / "package.json")
    specs = []
    for section in ("dependencies", "devDependencies"):
        values = package_data.get(section, {}) if isinstance(package_data, dict) else {}
        if isinstance(values, dict):
            specs.extend(str(value) for value in values.values())
    loose = [spec for spec in specs if spec.strip() == "*" or spec.strip().startswith(">")]
    return not loose, "package.json avoids wildcard and loose greater-than dependency specifiers."


def check_no_eval(project_dir: Path) -> Tuple[bool, str]:
    passed = "eval(" not in src_text(project_dir)
    return passed, "Source files do not use eval()."


def check_no_dangerous_html(project_dir: Path) -> Tuple[bool, str]:
    passed = "dangerouslySetInnerHTML" not in src_text(project_dir)
    return passed, "Source files do not use dangerouslySetInnerHTML."


def check_env_documentation(project_dir: Path) -> Tuple[bool, str]:
    env_example = safe_read(project_dir / ".env.example")
    references = set(re.findall(r"import\.meta\.env\.(VITE_[A-Z0-9_]+)", src_text(project_dir)))
    missing = sorted(name for name in references if name not in env_example)
    return not missing, "All VITE_* variables referenced in src/ are documented in .env.example."


def evaluate(project_dir: Path) -> List[RuleResult]:
    checks: List[Tuple[str, str, Callable[[Path], Tuple[bool, str]]]] = [
        ("WAP-001", "HIGH", check_css_custom_properties),
        ("WAP-002", "CRITICAL", check_chat_credentials),
        ("WAP-003", "CRITICAL", check_csp),
        ("WAP-004", "HIGH", check_chat_widget_cleanup),
        ("WAP-005", "CRITICAL", check_global_this),
        ("WAP-007", "HIGH", check_gitignore),
        ("WAP-011", "HIGH", check_svg_aria),
        ("WAP-014", "HIGH", check_host_true),
        ("WAP-015", "HIGH", check_mobile_breakpoints),
        ("WAP-016", "HIGH", check_touch_targets),
        ("WAP-017", "MEDIUM", check_test_scripts),
        ("WAP-018", "HIGH", check_vitest_thresholds),
        ("WAP-019", "HIGH", check_playwright_mobile),
        ("WAP-020", "MEDIUM", check_build_target),
        ("WAP-021", "HIGH", check_sourcemap),
        ("WAP-022", "MEDIUM", check_manual_chunks),
        ("SEC-002", "HIGH", check_package_lock),
        ("SEC-003", "HIGH", check_dependency_versions),
        ("SEC-006", "CRITICAL", check_no_eval),
        ("SEC-007", "CRITICAL", check_no_dangerous_html),
        ("SEC-008", "HIGH", check_env_documentation),
    ]
    results: List[RuleResult] = []
    for rule_id, severity, checker in checks:
        outcome, message = checker(project_dir)
        results.append({"rule": rule_id, "severity": severity, "status": "PASS" if outcome else "FAIL", "message": message})
    return sorted(results, key=lambda item: (SEVERITY_ORDER[item["severity"]], item["rule"]))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_dir = Path(args.project_dir).expanduser().resolve()
    if not project_dir.exists():
        print(f"[ERROR] Project directory not found: {project_dir}", file=sys.stderr)
        return 1

    results = evaluate(project_dir)
    rows = [(item["rule"], item["severity"], item["status"], item["message"]) for item in results]
    print(format_table(rows))

    failing = [item for item in results if item["status"] == "FAIL"]
    critical_or_high = [item for item in failing if item["severity"] in {"CRITICAL", "HIGH"}]
    print()
    print(f"Summary: {len(failing)} failing rule(s), {len(critical_or_high)} critical/high finding(s).")
    return 1 if critical_or_high else 0


if __name__ == "__main__":
    raise SystemExit(main())
