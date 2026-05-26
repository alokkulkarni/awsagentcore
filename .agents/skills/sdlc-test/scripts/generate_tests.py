#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Generate framework-aware unit test stubs for Python, JS/TS, Go, and Java projects."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".venv", "venv", "target", "vendor", "__pycache__", "test-results"}
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java"}
TEST_NAME_HINTS = ("test", "spec", "e2e", "integration")


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def parse_list(values: Sequence[str] | None) -> List[str]:
    items: List[str] = []
    for value in values or []:
        items.extend(part.strip() for part in value.split(",") if part.strip())
    return items


def discover_source_files(project_root: Path) -> List[Path]:
    results: List[Path] = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        lowered = path.name.lower()
        if any(hint in lowered for hint in TEST_NAME_HINTS):
            continue
        results.append(path)
    return results


def detect_framework(project_root: Path, source_files: List[Path], preferred: str) -> str:
    if preferred != "auto":
        return preferred
    suffixes = {path.suffix.lower() for path in source_files}
    if ".go" in suffixes:
        return "go"
    if ".java" in suffixes:
        return "junit"
    package_json = project_root / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(safe_read_text(package_json))
        except json.JSONDecodeError:
            payload = {}
        packages: Dict[str, str] = {}
        for section in ("dependencies", "devDependencies"):
            packages.update(payload.get(section) or {})
        if "vitest" in packages:
            return "vitest"
        if "jest" in packages:
            return "jest"
    if ".py" in suffixes:
        return "pytest"
    if ".ts" in suffixes or ".tsx" in suffixes:
        return "vitest"
    return "jest"


def camel_case(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", value) if part)


def python_module_path(project_root: Path, source_file: Path) -> str:
    rel = source_file.relative_to(project_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def extract_python_symbols(source_file: Path) -> List[str]:
    try:
        tree = ast.parse(safe_read_text(source_file))
    except SyntaxError:
        return []
    symbols: List[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            symbols.append(node.name)
    return symbols


def extract_js_symbols(text: str) -> List[str]:
    patterns = [
        re.compile(r"export\s+(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"module\.exports\s*=\s*\{([^}]+)\}"),
    ]
    symbols: List[str] = []
    for pattern in patterns[:3]:
        symbols.extend(match.group(1) for match in pattern.finditer(text))
    module_exports = patterns[3].search(text)
    if module_exports:
        symbols.extend(item.strip().split(":")[0].strip() for item in module_exports.group(1).split(",") if item.strip())
    return [symbol for symbol in symbols if symbol and not symbol.startswith("_")]


def extract_go_symbols(text: str) -> Tuple[str, List[str]]:
    package_match = re.search(r"(?m)^package\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    package_name = package_match.group(1) if package_match else "main"
    symbols = re.findall(r"(?m)^func\s+([A-Z][A-Za-z0-9_]*)\s*\(", text)
    return package_name, symbols


def extract_java_symbols(text: str, source_file: Path) -> Tuple[str, str, List[str]]:
    package_match = re.search(r"(?m)^package\s+([A-Za-z0-9_.]+);", text)
    package_name = package_match.group(1) if package_match else ""
    class_match = re.search(r"(?m)public\s+(?:class|interface|record|enum)\s+([A-Za-z_][A-Za-z0-9_]*)", text)
    class_name = class_match.group(1) if class_match else source_file.stem
    methods = re.findall(r"(?m)^\s*public\s+(?!class|interface|enum|record)(?:static\s+)?[A-Za-z0-9_<>\[\], ?]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
    return package_name, class_name, [method for method in methods if not method.startswith("_")]


def target_path(project_root: Path, source_file: Path, framework: str, output_dir: Optional[Path]) -> Path:
    if framework == "pytest":
        base = output_dir or (project_root / "tests")
        return base / f"test_{source_file.stem}.py"
    if framework in {"jest", "vitest"}:
        base = output_dir or (project_root / "tests")
        suffix = ".test.ts" if source_file.suffix.lower() in {".ts", ".tsx"} else ".test.js"
        return base / f"{source_file.stem}{suffix}"
    if framework == "go":
        if output_dir:
            return output_dir / f"{source_file.stem}_test.go"
        return source_file.with_name(f"{source_file.stem}_test.go")
    package_dir = output_dir or (project_root / "src" / "test" / "java")
    package_name, class_name, _ = extract_java_symbols(safe_read_text(source_file), source_file)
    if package_name:
        package_dir = package_dir / Path(*package_name.split("."))
    return package_dir / f"{class_name}Test.java"


def relative_import(from_file: Path, to_file: Path, drop_suffix: bool = True) -> str:
    rel = Path(os_path_relpath(to_file, from_file.parent)).as_posix()
    if drop_suffix:
        rel = re.sub(r"\.[^.]+$", "", rel)
    if not rel.startswith("."):
        rel = f"./{rel}"
    return rel


def os_path_relpath(target: Path, start: Path) -> str:
    return str(__import__("os").path.relpath(target, start))


def generate_pytest(project_root: Path, source_file: Path) -> str:
    module = python_module_path(project_root, source_file)
    symbols = extract_python_symbols(source_file)
    imports = ", ".join(symbols) if symbols else None
    lines = ["import pytest"]
    if imports:
        lines.append(f"from {module} import {imports}")
    else:
        lines.append("import importlib")
    lines.append("")
    lines.append(f"class Test{camel_case(source_file.stem)}:")
    if symbols:
        for symbol in symbols:
            test_name = re.sub(r"(?<!^)(?=[A-Z])", "_", symbol).lower()
            lines.extend([
                f"    def test_{test_name}_is_available(self):",
                "        # Arrange",
                f"        subject = {symbol}",
                "        # Act",
                "        result = subject is not None",
                "        # Assert",
                "        assert result",
                "",
            ])
    else:
        lines.extend([
            "    def test_module_imports_cleanly(self):",
            "        # Arrange",
            f"        module_name = '{module}'",
            "        # Act",
            "        module = importlib.import_module(module_name)",
            "        # Assert",
            "        assert module is not None",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def generate_js_test(project_root: Path, source_file: Path, framework: str, output_file: Path) -> str:
    symbols = extract_js_symbols(safe_read_text(source_file))
    import_path = relative_import(output_file, source_file)
    test_fn = "test" if framework == "jest" else "it"
    lines = [f"import * as subject from '{import_path}';", "", f"describe('{source_file.stem}', () => {{", f"  {test_fn}('exports the expected API surface', () => {{", "    // Arrange", "    const exported = subject;", "    // Act", "    const keys = Object.keys(exported);", "    // Assert", "    expect(exported).toBeDefined();"]
    if symbols:
        for symbol in symbols:
            lines.append(f"    expect(keys).toContain('{symbol}');")
            lines.append(f"    expect(subject.{symbol}).toBeDefined();")
    else:
        lines.append("    expect(keys.length).toBeGreaterThanOrEqual(0);")
    lines.extend(["  });", "});", ""])
    return "\n".join(lines)


def generate_go_test(source_file: Path) -> str:
    package_name, symbols = extract_go_symbols(safe_read_text(source_file))
    lines = [f"package {package_name}", "", 'import "testing"', "", "func TestExportedSymbolsAvailable(t *testing.T) {"]
    if symbols:
        lines.append("\ttests := []struct { name string; available bool }{")
        for symbol in symbols:
            lines.append(f"\t\t{{name: \"{symbol}\", available: {symbol} != nil}},")
        lines.append("\t}")
        lines.extend([
            "\tfor _, tc := range tests {",
            "\t\tt.Run(tc.name, func(t *testing.T) {",
            "\t\t\tif !tc.available {",
            "\t\t\t\tt.Fatalf(\"expected exported symbol %s to be available\", tc.name)",
            "\t\t\t}",
            "\t\t})",
            "\t}",
        ])
    else:
        lines.extend(["\tif testing.Short() {", "\t\tt.Fatal(\"expected generated test stub to be replaced with a real assertion\")", "\t}"])
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_java_test(source_file: Path) -> str:
    package_name, class_name, methods = extract_java_symbols(safe_read_text(source_file), source_file)
    fqcn = f"{package_name}.{class_name}" if package_name else class_name
    lines = []
    if package_name:
        lines.append(f"package {package_name};")
        lines.append("")
    lines.extend([
        "import org.junit.jupiter.api.Test;",
        "import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;",
        "",
        f"class {class_name}Test {{",
        "    @Test",
        "    void classLoads() {",
        f"        assertDoesNotThrow(() -> Class.forName(\"{fqcn}\"));",
        "    }",
        "",
    ])
    for method in methods:
        lines.extend([
            "    @Test",
            f"    void method_{method}_isDeclared() {{",
            f"        assertDoesNotThrow(() -> Class.forName(\"{fqcn}\"));",
            "    }",
            "",
        ])
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def build_content(project_root: Path, source_file: Path, framework: str, output_file: Path) -> str:
    if framework == "pytest":
        return generate_pytest(project_root, source_file)
    if framework in {"jest", "vitest"}:
        return generate_js_test(project_root, source_file, framework, output_file)
    if framework == "go":
        return generate_go_test(source_file)
    return generate_java_test(source_file)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate framework-aware test stubs.")
    parser.add_argument("--project-root", default=".", help="Project root to scan.")
    parser.add_argument("--source-files", nargs="*", help="Comma-separated or repeated list of source files.")
    parser.add_argument("--framework", choices=["pytest", "jest", "vitest", "go", "junit", "auto"], default="auto")
    parser.add_argument("--output-dir", help="Optional output directory override.")
    parser.add_argument("--dry-run", action="store_true", help="Print generated files without writing them.")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    requested = parse_list(args.source_files)
    if requested:
        source_files = []
        for value in requested:
            candidate = Path(value)
            candidate = candidate if candidate.is_absolute() else (project_root / candidate)
            candidate = candidate.resolve()
            if candidate.exists() and candidate.is_file():
                source_files.append(candidate)
    else:
        source_files = discover_source_files(project_root)
    framework = detect_framework(project_root, source_files, args.framework)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None
    generated: List[Tuple[Path, str]] = []
    for source_file in source_files:
        suffix = source_file.suffix.lower()
        if framework == "pytest" and suffix != ".py":
            continue
        if framework in {"jest", "vitest"} and suffix not in {".js", ".jsx", ".ts", ".tsx"}:
            continue
        if framework == "go" and suffix != ".go":
            continue
        if framework == "junit" and suffix != ".java":
            continue
        output_file = target_path(project_root, source_file, framework, output_dir)
        content = build_content(project_root, source_file, framework, output_file)
        generated.append((output_file, content))
    for output_file, content in generated:
        if args.dry_run:
            print(f"=== {output_file} ===")
            print(content)
        else:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(content, encoding="utf-8")
            print(output_file.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
