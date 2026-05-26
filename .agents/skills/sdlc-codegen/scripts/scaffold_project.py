#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
# Generate safe scaffold files from architecture artefacts.

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

GENERIC_HEADINGS = {
    "overview",
    "introduction",
    "architecture",
    "components",
    "requirements",
    "constraints",
    "risks",
    "assumptions",
}
COMPONENT_HINTS = (
    "service",
    "api",
    "worker",
    "gateway",
    "module",
    "component",
    "domain",
    "engine",
    "processor",
    "adapter",
    "repository",
    "store",
    "pipeline",
    "portal",
    "ui",
)

def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")

def load_json(path: Path) -> Dict[str, object]:
    text = safe_read_text(path)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}

def normalize_token(value: str) -> str:
    value = value.strip().lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()

def slugify(value: str) -> str:
    return re.sub(r"\s+", "-", normalize_token(value)).strip("-") or "component"

def snake_case(value: str) -> str:
    return slugify(value).replace("-", "_")

def pascal_case(value: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_\s]+", value) if part)

def sentence_case(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .:-")
    return value[:1].upper() + value[1:] if value else "Generated component"

def detect_stack(project_root: Path, requested_framework: str) -> Tuple[str, str]:
    if requested_framework != "auto":
        mapping = {"fastapi": ("python", "fastapi"), "express": ("typescript", "express"), "gin": ("go", "gin"), "spring": ("java", "spring"), "nextjs": ("typescript", "nextjs")}
        return mapping[requested_framework]
    package = load_json(project_root / "package.json")
    deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})} if package else {}
    if isinstance(deps, dict):
        lowered = {str(key).lower() for key in deps}
        if "next" in lowered:
            return "typescript", "nextjs"
        if "express" in lowered:
            return "typescript", "express"
        if "react" in lowered:
            return "typescript", "react"
        if package:
            return "typescript", "typescript"
    pyproject = project_root / "pyproject.toml"
    requirements = safe_read_text(project_root / "requirements.txt").lower()
    if pyproject.exists() or requirements:
        combined = (safe_read_text(pyproject) + "\n" + requirements).lower()
        if "fastapi" in combined:
            return "python", "fastapi"
        if "flask" in combined:
            return "python", "flask"
        if "django" in combined:
            return "python", "django"
        return "python", "python"
    go_mod = safe_read_text(project_root / "go.mod").lower()
    if go_mod:
        if "gin-gonic/gin" in go_mod:
            return "go", "gin"
        if "labstack/echo" in go_mod:
            return "go", "echo"
        return "go", "go"
    pom = safe_read_text(project_root / "pom.xml").lower() + safe_read_text(project_root / "build.gradle").lower() + safe_read_text(project_root / "build.gradle.kts").lower()
    if pom:
        if "spring-boot" in pom:
            return "java", "spring"
        if "quarkus" in pom:
            return "java", "quarkus"
        return "java", "java"
    cargo = safe_read_text(project_root / "Cargo.toml").lower()
    if cargo:
        if "actix-web" in cargo:
            return "rust", "actix"
        if "axum" in cargo:
            return "rust", "axum"
        return "rust", "rust"
    return "generic", "generic"

def extract_sections(markdown: str) -> List[Tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^#{2,4}\s+(.+?)\s*$", markdown))
    sections: List[Tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[start:end].strip()))
    return sections

def split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text)
    return [item.strip(" -") for item in re.split(r"(?<=[.!?])\s+", text) if len(item.strip()) > 20]

def extract_bullets(text: str) -> List[str]:
    items: List[str] = []
    for raw_line in text.splitlines():
        match = re.match(r"^\s*(?:[-*+] |\d+\. )(.+)$", raw_line)
        if match and len(match.group(1).strip()) > 8:
            items.append(match.group(1).strip())
    return items

def looks_like_component_name(value: str) -> bool:
    normalized = normalize_token(value)
    if not normalized or normalized in GENERIC_HEADINGS:
        return False
    if any(hint in normalized for hint in COMPONENT_HINTS):
        return True
    words = normalized.split()
    return 1 <= len(words) <= 4 and value[:1].isupper()

def extract_components(markdown: str, fallback_name: str) -> List[Dict[str, str]]:
    components: List[Dict[str, str]] = []
    seen = set()
    for heading, body in extract_sections(markdown):
        if not looks_like_component_name(heading):
            continue
        bullets = extract_bullets(body)
        description = bullets[0] if bullets else (split_sentences(body)[0] if split_sentences(body) else heading)
        slug = slugify(heading)
        if slug in seen:
            continue
        seen.add(slug)
        components.append({"name": heading.strip(), "description": sentence_case(description)})
    if not components:
        components.append({"name": fallback_name, "description": f"Generated scaffold for {fallback_name}"})
    return components

def detect_java_package(project_root: Path) -> str:
    pom = safe_read_text(project_root / "pom.xml")
    match = re.search(r"<groupId>([^<]+)</groupId>", pom)
    return match.group(1).strip() + ".generated" if match else "com.example.generated"

def dependency_suggestions(language: str, framework: str, project_root: Path) -> List[str]:
    suggestions: List[str] = []
    package = json.dumps(load_json(project_root / "package.json")).lower()
    py = (safe_read_text(project_root / "pyproject.toml") + safe_read_text(project_root / "requirements.txt")).lower()
    go_mod = safe_read_text(project_root / "go.mod").lower()
    pom = safe_read_text(project_root / "pom.xml").lower()
    cargo = safe_read_text(project_root / "Cargo.toml").lower()
    if framework == "fastapi" and "fastapi" not in py:
        suggestions.append("fastapi")
    if framework == "express" and "express" not in package:
        suggestions.append("express")
    if framework == "nextjs" and "next" not in package:
        suggestions.append("next")
    if framework == "gin" and "gin-gonic/gin" not in go_mod:
        suggestions.append("github.com/gin-gonic/gin")
    if framework == "spring" and "spring-boot" not in pom:
        suggestions.append("spring-boot-starter-web")
    if framework in {"actix", "axum"} and framework not in cargo:
        suggestions.append(framework)
    return suggestions

def fastapi_files(component: Dict[str, str]) -> Dict[str, str]:
    slug = snake_case(component["name"])
    title = pascal_case(component["name"])
    description = component["description"]
    return {
        f"app/{slug}/__init__.py": f"# {title} package\n",
        f"app/{slug}/router.py": f'''# FastAPI routes for {title}
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/{slug}", tags=["{title}"])

@router.get("/")
async def get_{slug}_status() -> dict[str, str]:
    try:
        return {{"component": "{slug}", "status": "stub-ready", "description": "{description}"}}
    except Exception as exc:  # pragma: no cover - defensive scaffold
        raise HTTPException(status_code=500, detail=f"Unable to serve {slug}: {{exc}}") from exc
''',
        f"app/{slug}/service.py": f'''# Service layer for {title}

class {title}Service:
    def describe(self) -> dict[str, str]:
        try:
            return {{"component": "{slug}", "summary": "{description}"}}
        except Exception as exc:  # pragma: no cover - defensive scaffold
            raise RuntimeError("Unable to describe the component") from exc
''',
        f"tests/test_{slug}.py": f'''# Basic contract test for {title}
from app.{slug}.service import {title}Service

def test_{slug}_service_description() -> None:
    payload = {title}Service().describe()
    assert payload["component"] == "{slug}"
''',
    }

def express_files(component: Dict[str, str]) -> Dict[str, str]:
    slug = slugify(component["name"])
    title = pascal_case(component["name"])
    description = component["description"]
    return {
        f"src/{slug}/router.ts": f'''/** Express routes for {title}. */
import {{ Router, type Request, type Response, type NextFunction }} from "express";

export const {title}Router = Router();

{title}Router.get("/", async (_req: Request, res: Response, next: NextFunction) => {{
  try {{
    res.json({{ component: "{slug}", status: "stub-ready", description: "{description}" }});
  }} catch (error) {{
    next(error);
  }}
}});
''',
        f"src/{slug}/service.ts": f'''/** Service implementation scaffold for {title}. */
export class {title}Service {{
  describe(): {{ component: string; summary: string }} {{
    try {{
      return {{ component: "{slug}", summary: "{description}" }};
    }} catch (error) {{
      throw new Error(`Unable to describe {slug}: ${String(error)}`);
    }}
  }}
}}
''',
        f"tests/{slug}.test.ts": f'''/** Smoke test scaffold for {title}. */
import {{ describe, it }} from "node:test";
import assert from "node:assert/strict";
import {{ {title}Service }} from "../src/{slug}/service";

describe("{title}Service", () => {{
  it("returns component metadata", () => {{
    const payload = new {title}Service().describe();
    assert.equal(payload.component, "{slug}");
  }});
}});
''',
    }

def nextjs_files(component: Dict[str, str]) -> Dict[str, str]:
    slug = slugify(component["name"])
    title = pascal_case(component["name"])
    description = component["description"]
    return {
        f"app/api/{slug}/route.ts": f'''/** Next.js route scaffold for {title}. */
import {{ NextResponse }} from "next/server";

export async function GET() {{
  try {{
    return NextResponse.json({{ component: "{slug}", status: "stub-ready", description: "{description}" }});
  }} catch (error) {{
    return NextResponse.json({{ error: `Unable to load {slug}: ${String(error)}` }}, {{ status: 500 }});
  }}
}}
''',
        f"components/{title}Panel.tsx": f'''/** Minimal UI scaffold for {title}. */
export function {title}Panel() {{
  return (
    <section>
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}}
''',
        f"tests/{slug}.test.tsx": f'''/** Basic UI contract scaffold for {title}. */
import assert from "node:assert/strict";
import {{ {title}Panel }} from "../components/{title}Panel";

assert.equal(typeof {title}Panel, "function");
''',
    }

def gin_files(component: Dict[str, str]) -> Dict[str, str]:
    slug = snake_case(component["name"])
    title = pascal_case(component["name"])
    description = component["description"]
    return {
        f"internal/{slug}/handler.go": f'''package {slug}

import (
    "net/http"

    "github.com/gin-gonic/gin"
)

// RegisterRoutes wires the generated {title} routes.
func RegisterRoutes(router gin.IRouter) {{
    router.GET("/{slug}", func(c *gin.Context) {{
        c.JSON(http.StatusOK, gin.H{{
            "component":   "{slug}",
            "status":      "stub-ready",
            "description": "{description}",
        }})
    }})
}}
''',
        f"internal/{slug}/service.go": f'''package {slug}

import "fmt"

// Describe returns a stable payload for the scaffolded component.
func Describe() (map[string]string, error) {{
    payload := map[string]string{{
        "component": "{slug}",
        "summary":   "{description}",
    }}
    if payload["component"] == "" {{
        return nil, fmt.Errorf("component slug missing")
    }}
    return payload, nil
}}
''',
        f"internal/{slug}/service_test.go": f'''package {slug}

import "testing"

func TestDescribe(t *testing.T) {{
    payload, err := Describe()
    if err != nil {{
        t.Fatalf("unexpected error: %v", err)
    }}
    if payload["component"] != "{slug}" {{
        t.Fatalf("unexpected component: %v", payload["component"])
    }}
}}
''',
    }

def spring_files(component: Dict[str, str], package_name: str) -> Dict[str, str]:
    slug = slugify(component["name"])
    title = pascal_case(component["name"])
    description = component["description"]
    package_path = package_name.replace('.', '/')
    return {
        f"src/main/java/{package_path}/{title}Controller.java": f'''package {package_name};

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** REST controller scaffold for {title}. */
@RestController
@RequestMapping("/{slug}")
public class {title}Controller {{
    @GetMapping
    public ResponseEntity<Map<String, String>> getStatus() {{
        try {{
            return ResponseEntity.ok(Map.of(
                "component", "{slug}",
                "status", "stub-ready",
                "description", "{description}"
            ));
        }} catch (RuntimeException ex) {{
            return ResponseEntity.internalServerError().body(Map.of("error", ex.getMessage()));
        }}
    }}
}}
''',
        f"src/main/java/{package_path}/{title}Service.java": f'''package {package_name};

import java.util.Map;

/** Service scaffold for {title}. */
public class {title}Service {{
    public Map<String, String> describe() {{
        return Map.of(
            "component", "{slug}",
            "summary", "{description}"
        );
    }}
}}
''',
        f"src/test/java/{package_path}/{title}ServiceTest.java": f'''package {package_name};

import static org.junit.jupiter.api.Assertions.assertEquals;
import org.junit.jupiter.api.Test;

class {title}ServiceTest {{
    @Test
    void describeReturnsComponentName() {{
        {title}Service service = new {title}Service();
        assertEquals("{slug}", service.describe().get("component"));
    }}
}}
''',
    }

def generic_files(language: str, framework: str, component: Dict[str, str], package_name: str) -> Dict[str, str]:
    if language == "python":
        return fastapi_files(component)
    if language == "typescript":
        return nextjs_files(component) if framework == "react" else express_files(component)
    if language == "go":
        if framework == "gin":
            return gin_files(component)
        slug = snake_case(component["name"])
        return {
            f"internal/{slug}/handler.go": f'''package {slug}

import (
    "encoding/json"
    "net/http"
)

func Handler(w http.ResponseWriter, _ *http.Request) {{
    payload := map[string]string{{"component": "{slug}", "status": "stub-ready", "description": "{component['description']}"}}
    if err := json.NewEncoder(w).Encode(payload); err != nil {{
        http.Error(w, err.Error(), http.StatusInternalServerError)
    }}
}}
''',
            f"internal/{slug}/handler_test.go": f'''package {slug}

import "testing"

func TestHandlerPackageName(t *testing.T) {{
    if "{slug}" == "" {{
        t.Fatal("component slug should not be empty")
    }}
}}
''',
        }
    if language == "java":
        return spring_files(component, package_name)
    if language == "rust":
        slug = snake_case(component["name"])
        title = pascal_case(component["name"])
        description = component["description"]
        return {
            f"src/{slug}.rs": f'''/// Scaffolded module for {title}.
pub fn describe() -> Result<&'static str, &'static str> {{
    if "{slug}".is_empty() {{
        return Err("component slug missing");
    }}
    Ok("{description}")
}}
''',
            f"tests/{slug}_tests.rs": f'''#[test]
fn describe_returns_ok() {{
    assert!(!"{description}".is_empty());
}}
''',
        }
    return {f"generated/{slugify(component['name'])}.txt": f"Generated placeholder for {component['name']}\n"}

def files_for_component(language: str, framework: str, component: Dict[str, str], package_name: str) -> Dict[str, str]:
    if framework == "fastapi":
        return fastapi_files(component)
    if framework == "express":
        return express_files(component)
    if framework == "nextjs":
        return nextjs_files(component)
    if framework == "gin":
        return gin_files(component)
    if framework == "spring":
        return spring_files(component, package_name)
    return generic_files(language, framework, component, package_name)

def write_if_missing(base_dir: Path, relative_path: str, content: str, created: List[str], skipped: List[str], dry_run: bool) -> None:
    target = base_dir / relative_path
    if target.exists():
        skipped.append(relative_path)
        return
    if dry_run:
        created.append(relative_path)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")
    created.append(relative_path)

def render_summary_md(project_name: str, framework: str, language: str, components: List[Dict[str, object]], created: List[str], skipped: List[str], dependencies: List[str], manifest_updates: List[str]) -> str:
    lines = [
        f"# Code Generation Summary for {project_name}",
        "",
        f"- Date: {date.today().isoformat()}",
        f"- Framework detected: {framework}",
        f"- Language: {language}",
        f"- Components scaffolded: {len(components)}",
        "",
        "## Components Scaffolded",
        "",
        "| Component | Files Generated |",
        "|-----------|-----------------|",
        *[f"| {component['name']} | {len(component['files'])} |" for component in components],
        "",
        "## Files Created / Modified",
        "",
        *[f"- Created: {path}" for path in created],
        *[f"- Skipped existing: {path}" for path in skipped],
        "",
        "## Test Coverage Baseline",
        "",
        "Generated scaffold includes smoke or contract tests alongside source files where supported.",
        "",
        "## Known Gaps / TODOs",
        "",
        "- Merge skipped files manually when a target path already exists.",
        "- Review dependency suggestions before enabling runtime integration.",
        "",
        "## Dependencies Added",
        "",
        *([f"- {dependency}" for dependency in dependencies] or ["- None"]),
        "",
        "## Configuration Changes",
        "",
        *([f"- {item}" for item in manifest_updates] or ["- None applied automatically"]),
    ]
    return "\n".join(lines).strip() + "\n"

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scaffold code from architecture artefacts without overwriting existing files.")
    parser.add_argument("--project-root", default=".", help="Repository root")
    parser.add_argument("--framework", choices=["fastapi", "express", "gin", "spring", "nextjs", "auto"], default="auto", help="Explicit framework override")
    parser.add_argument("--dry-run", action="store_true", help="Show planned files without writing them")
    parser.add_argument("--output-dir", help="Output directory for scaffolded files. Defaults to the project root.")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else project_root
    language, framework = detect_stack(project_root, args.framework)
    package_name = detect_java_package(project_root)
    components = extract_components(safe_read_text(project_root / "architecture" / "hld.md"), fallback_name=project_root.name)
    dependencies = dependency_suggestions(language, framework, project_root)
    created: List[str] = []
    skipped: List[str] = []
    component_summaries: List[Dict[str, object]] = []
    for component in components:
        files = files_for_component(language, framework, component, package_name)
        component_summaries.append({"name": component["name"], "path": next(iter(files), ""), "files": list(files)})
        for relative_path, content in files.items():
            write_if_missing(output_dir, relative_path, content, created, skipped, args.dry_run)
    manifest_updates: List[str] = []
    changelog_path = output_dir / "CHANGELOG.md"
    if not changelog_path.exists() and not args.dry_run:
        changelog_path.write_text(f"# Changelog\n\n## {date.today().isoformat()}\n- Scaffolded components for {project_root.name} using {framework}.\n", encoding="utf-8")
        created.append("CHANGELOG.md")
        manifest_updates.append("Created CHANGELOG.md with scaffold entry")
    elif changelog_path.exists():
        skipped.append("CHANGELOG.md")
    summary_payload = {"project": project_root.name, "generated_on": date.today().isoformat(), "framework_detected": framework, "language": language, "components": component_summaries, "created_files": created, "skipped_files": skipped, "modified_files": [], "dependencies_added": dependencies, "manifest_updates": manifest_updates}
    if args.dry_run:
        print(json.dumps(summary_payload, indent=2))
        return 0
    codegen_dir = output_dir / "codegen"
    codegen_dir.mkdir(parents=True, exist_ok=True)
    (codegen_dir / "scaffold-summary.md").write_text(render_summary_md(project_root.name, framework, language, component_summaries, created, skipped, dependencies, manifest_updates), encoding="utf-8")
    (codegen_dir / "scaffold-summary.json").write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary_payload, indent=2))
    return 0

if __name__ == "__main__":
    sys.exit(main())
