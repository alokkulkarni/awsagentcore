#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Generate backlog epics and user stories from architecture artefacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

GENERIC_HEADINGS = {
    "overview",
    "introduction",
    "context",
    "requirements",
    "architecture",
    "high level design",
    "components",
    "component view",
    "non functional requirements",
    "assumptions",
    "constraints",
    "risks",
    "appendix",
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
GLOBAL_DEFINITION_OF_DONE = [
    "Acceptance criteria are testable and reviewed with stakeholders.",
    "Observability, logging, and failure handling are covered.",
    "Security, privacy, and dependency impacts are assessed.",
    "Implementation notes and operational handoff details are documented.",
]


@dataclass
class Story:
    story_id: str
    epic_id: str
    title: str
    story_text: str
    acceptance_criteria: List[str]
    story_points: int
    priority: str
    sprint: str
    dependencies: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Epic:
    epic_id: str
    title: str
    description: str
    business_value: str
    acceptance_criteria: List[str]
    dependencies: List[str]
    definition_of_done: List[str]
    stories: List[Story] = field(default_factory=list)


@dataclass
class Component:
    name: str
    description: str
    responsibilities: List[str]


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def normalize_token(value: str) -> str:
    value = value.strip().lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()


def slugify(value: str) -> str:
    value = normalize_token(value)
    return re.sub(r"\s+", "-", value).strip("-") or "component"


def title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", value) if part)


def sentence_case(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .:-")
    return value[0].upper() + value[1:] if value else "deliver the required capability"


def extract_tables(markdown: str) -> List[List[List[str]]]:
    tables: List[List[List[str]]] = []
    current: List[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            current.append(line)
        elif current:
            if len(current) >= 2:
                tables.append([[cell.strip() for cell in row.strip("|").split("|")] for row in current])
            current = []
    if current and len(current) >= 2:
        tables.append([[cell.strip() for cell in row.strip("|").split("|")] for row in current])
    return tables


def extract_sections(markdown: str) -> List[Tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^#{2,4}\s+(.+?)\s*$", markdown))
    sections: List[Tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append((match.group(1).strip(), markdown[start:end].strip()))
    return sections


def split_sentences(text: str) -> List[str]:
    compact = re.sub(r"\s+", " ", text)
    return [item.strip(" -") for item in re.split(r"(?<=[.!?])\s+", compact) if len(item.strip()) > 20]


def extract_bullets(text: str) -> List[str]:
    bullets: List[str] = []
    for raw_line in text.splitlines():
        match = re.match(r"^\s*(?:[-*+] |\d+\. )(.+)$", raw_line)
        if match and len(match.group(1).strip()) > 8:
            bullets.append(re.sub(r"[`*_]", "", match.group(1)).strip(" ."))
    return bullets


def looks_like_component_name(value: str) -> bool:
    normalized = normalize_token(value)
    if not normalized or normalized in GENERIC_HEADINGS:
        return False
    if any(hint in normalized for hint in COMPONENT_HINTS):
        return True
    words = normalized.split()
    return 1 <= len(words) <= 4 and value[:1].isupper()


def add_component(components: Dict[str, Component], name: str, description: str, responsibilities: Iterable[str]) -> None:
    slug = slugify(name)
    filtered = [sentence_case(item) for item in responsibilities if item and len(item.strip()) > 8]
    summary = sentence_case(description)
    if slug in components:
        current = components[slug]
        if len(summary) > len(current.description):
            current.description = summary
        for item in filtered:
            if item not in current.responsibilities:
                current.responsibilities.append(item)
        return
    components[slug] = Component(name=title_case(name), description=summary, responsibilities=filtered[:5])


def extract_components(markdown: str, fallback_name: str) -> List[Component]:
    components: Dict[str, Component] = {}
    for table in extract_tables(markdown):
        headers = [normalize_token(cell) for cell in table[0]]
        if "component" not in headers:
            continue
        name_index = headers.index("component")
        detail_index = next((idx for idx, value in enumerate(headers) if value in {"responsibility", "responsibilities", "description", "purpose", "role"}), None)
        for row in table[2:]:
            if name_index >= len(row):
                continue
            name = row[name_index].strip()
            detail = row[detail_index].strip() if detail_index is not None and detail_index < len(row) else ""
            if name:
                add_component(components, name, detail, [detail] if detail else [])

    for raw_line in markdown.splitlines():
        match = re.match(r"^\s*[-*+]\s+([^:–-]{2,60})\s*[:–-]\s+(.+)$", raw_line)
        if match and looks_like_component_name(match.group(1).strip()):
            add_component(components, match.group(1).strip(), match.group(2).strip(), [match.group(2).strip()])

    for heading, body in extract_sections(markdown):
        if not looks_like_component_name(heading):
            continue
        bullets = extract_bullets(body)
        sentences = split_sentences(body)
        description = bullets[0] if bullets else (sentences[0] if sentences else heading)
        responsibilities = bullets or sentences[:3]
        add_component(components, heading, description, responsibilities)

    if not components:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", markdown) if item.strip()]
        responsibilities = split_sentences(" ".join(paragraphs[:3]))[:3]
        default_responsibilities = responsibilities or [
            f"Provide the core capabilities described in the architecture for {fallback_name}",
            f"Expose measurable behaviour and failure handling for {fallback_name}",
            f"Support delivery planning and implementation tracking for {fallback_name}",
        ]
        add_component(components, fallback_name, default_responsibilities[0], default_responsibilities)

    normalized: List[Component] = []
    for component in components.values():
        if not component.responsibilities:
            component.responsibilities = [component.description]
        normalized.append(component)
    return normalized


def infer_project_name(project_root: Path, markdown: str) -> str:
    for raw_line in markdown.splitlines():
        if raw_line.startswith("# "):
            return raw_line[2:].strip()
    return project_root.name


def choose_persona(component_name: str, responsibility: str) -> str:
    text = f"{component_name} {responsibility}".lower()
    if any(token in text for token in ["auth", "security", "identity", "access"]):
        return "security administrator"
    if any(token in text for token in ["report", "analytics", "data", "dashboard"]):
        return "business analyst"
    if any(token in text for token in ["api", "integration", "partner", "event"]):
        return "service consumer"
    if any(token in text for token in ["admin", "ops", "monitor", "support", "queue", "worker"]):
        return "platform operator"
    if any(token in text for token in ["ui", "portal", "web", "checkout", "customer"]):
        return "end user"
    return "product user"


def choose_benefit(component_name: str, responsibility: str) -> str:
    text = responsibility.lower()
    if any(token in text for token in ["validate", "rule", "policy"]):
        return "business rules are enforced consistently"
    if any(token in text for token in ["store", "persist", "record", "audit"]):
        return "data remains accurate and traceable"
    if any(token in text for token in ["notify", "event", "message", "publish"]):
        return "stakeholders receive timely updates"
    if any(token in text for token in ["report", "dashboard", "search"]):
        return "teams can make faster evidence-based decisions"
    return f"{component_name} delivers measurable value safely"


def choose_priority(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["auth", "security", "payment", "compliance", "critical"]):
        return "Must"
    if any(token in lowered for token in ["report", "dashboard", "insight"]):
        return "Could"
    return "Should"


def estimate_points(text: str) -> int:
    words = len(re.findall(r"\w+", text))
    if words <= 6:
        return 2
    if words <= 10:
        return 3
    if words <= 18:
        return 5
    if words <= 28:
        return 8
    return 13


def build_story(component: Component, epic_id: str, story_number: int, responsibility: str, sprint: str) -> Story:
    persona = choose_persona(component.name, responsibility)
    capability = responsibility.rstrip(".")
    benefit = choose_benefit(component.name, responsibility)
    story_text = f"As a {persona}, I want {capability.lower()} so that {benefit}"
    acceptance = [
        f"Given the {component.name.lower()} capability is configured and available",
        f"When the {persona} triggers the {capability.lower()} flow",
        f"Then the platform completes the {component.name.lower()} outcome and records a verifiable result",
    ]
    return Story(
        story_id=f"STORY-{story_number:03d}",
        epic_id=epic_id,
        title=sentence_case(f"Enable {component.name} to {capability.lower()}"),
        story_text=story_text,
        acceptance_criteria=acceptance,
        story_points=estimate_points(responsibility),
        priority=choose_priority(f"{component.name} {responsibility}"),
        sprint=sprint,
        dependencies=[],
        notes=f"Derived from architecture responsibility: {responsibility}",
    )


def build_epics(components: List[Component]) -> List[Epic]:
    epics: List[Epic] = []
    story_counter = 1
    for index, component in enumerate(components, start=1):
        epic_id = f"EPIC-{index:03d}"
        sprint = f"Sprint {index}"
        epic = Epic(
            epic_id=epic_id,
            title=component.name,
            description=component.description,
            business_value=f"Deliver the {component.name.lower()} capability as a traceable backlog slice that maps directly to the architecture.",
            acceptance_criteria=[
                f"The {component.name} scope is represented by sprint-ready stories.",
                "Dependencies and sizing are visible for planning.",
                "Acceptance criteria are testable in Given / When / Then form.",
            ],
            dependencies=[],
            definition_of_done=list(GLOBAL_DEFINITION_OF_DONE),
        )
        for responsibility in component.responsibilities[:3]:
            epic.stories.append(build_story(component, epic_id, story_counter, responsibility, sprint))
            story_counter += 1
        epics.append(epic)

    while epics and sum(len(epic.stories) for epic in epics) < 3:
        component = components[0]
        epic = epics[0]
        epic.stories.append(build_story(component, epic.epic_id, story_counter, f"Capture observability and failure handling for {component.name.lower()}", epic.stories[0].sprint if epic.stories else "Sprint 1"))
        story_counter += 1
    return epics


def render_epics_markdown(project_name: str, epics: List[Epic]) -> str:
    lines = [f"# Epics for {project_name}", ""]
    for epic in epics:
        lines.extend([
            f"## {epic.epic_id} — {epic.title}",
            "",
            f"**Description:** {epic.description}",
            "",
            f"**Business Value:** {epic.business_value}",
            "",
            "### User Stories",
            *[f"- {story.story_id} — {story.title}" for story in epic.stories],
            "",
            "### Acceptance Criteria",
            *[f"- {criterion}" for criterion in epic.acceptance_criteria],
            "",
            "### Dependencies",
            "- None identified",
            "",
            "### Definition of Done",
            *[f"- {item}" for item in epic.definition_of_done],
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def render_acceptance_markdown(project_name: str, epics: List[Epic]) -> str:
    lines = [f"# Acceptance Criteria for {project_name}", ""]
    for epic in epics:
        lines.extend([f"## {epic.epic_id} — {epic.title}", ""])
        for story in epic.stories:
            lines.extend([
                f"### {story.story_id} — {story.title}",
                "",
                f"**Story:** {story.story_text}",
                "",
                "```gherkin",
                *story.acceptance_criteria,
                "```",
                "",
            ])
    return "\n".join(lines).strip() + "\n"


def render_summary_markdown(project_name: str, epics: List[Epic], source_hld: Path) -> str:
    lines = [
        f"# Backlog Summary for {project_name}",
        "",
        f"- Generated: {date.today().isoformat()}",
        f"- Source HLD: {source_hld.as_posix()}",
        f"- Epics: {len(epics)}",
        f"- User Stories: {sum(len(epic.stories) for epic in epics)}",
        "",
        "## Definition of Done",
        *[f"- {item}" for item in GLOBAL_DEFINITION_OF_DONE],
        "",
        "## Epics",
        "",
    ]
    for epic in epics:
        lines.extend([
            f"### Epic {epic.epic_id} — {epic.title}",
            f"- Description: {epic.description}",
            f"- Business Value: {epic.business_value}",
            "- Dependencies: None identified",
            f"- Stories: {', '.join(story.story_id for story in epic.stories)}",
            "",
        ])
    lines.extend(["## User Stories", ""])
    for epic in epics:
        for story in epic.stories:
            lines.extend([
                f"### Story {story.story_id} — {story.title}",
                f"- Epic: {story.epic_id}",
                f"- Story: {story.story_text}",
                f"- Story Points: {story.story_points}",
                f"- Size: {story.story_points}",
                f"- Priority: {story.priority}",
                f"- Sprint: {story.sprint}",
                f"- Dependencies: {', '.join(story.dependencies) if story.dependencies else 'None'}",
                f"- Notes: {story.notes}",
                "#### Acceptance Criteria",
                *[f"- {criterion}" for criterion in story.acceptance_criteria],
                "",
            ])
    return "\n".join(lines).strip() + "\n"


def render_json(project_name: str, source_hld: Path, epics: List[Epic]) -> str:
    payload = {
        "project": project_name,
        "generated_on": date.today().isoformat(),
        "source_hld": source_hld.as_posix(),
        "definition_of_done": GLOBAL_DEFINITION_OF_DONE,
        "epics": [asdict(epic) for epic in epics],
    }
    return json.dumps(payload, indent=2) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate epics and stories from architecture/hld.md")
    parser.add_argument("--project-root", default=".", help="Project root containing architecture artefacts.")
    parser.add_argument("--hld-path", help="Path to architecture/hld.md. Defaults to <project-root>/architecture/hld.md")
    parser.add_argument("--output-dir", help="Backlog output directory. Defaults to <project-root>/backlog")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Optional additional machine-readable output format.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).expanduser().resolve()
    hld_path = Path(args.hld_path).expanduser().resolve() if args.hld_path else project_root / "architecture" / "hld.md"
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else project_root / "backlog"

    markdown = safe_read_text(hld_path)
    if not markdown:
        print(f"[ERROR] HLD file not found or empty: {hld_path}", file=sys.stderr)
        return 1

    project_name = infer_project_name(project_root, markdown)
    epics = build_epics(extract_components(markdown, fallback_name=project_name))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "stories-summary.md").write_text(render_summary_markdown(project_name, epics, hld_path), encoding="utf-8")
    (output_dir / "epics.md").write_text(render_epics_markdown(project_name, epics), encoding="utf-8")
    (output_dir / "acceptance-criteria.md").write_text(render_acceptance_markdown(project_name, epics), encoding="utf-8")
    if args.format == "json":
        (output_dir / "stories-summary.json").write_text(render_json(project_name, hld_path, epics), encoding="utf-8")
    print(f"Generated {len(epics)} epics and {sum(len(epic.stories) for epic in epics)} stories")
    return 0


if __name__ == "__main__":
    sys.exit(main())
