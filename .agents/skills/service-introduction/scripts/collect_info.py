#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Collect business context for a Service Introduction Document.

When this script is used inside an AI agent runtime (GitHub Copilot, Claude Code, Cursor,
Kiro, and similar tools), MCP calls are made by the AI assistant rather than by Python itself.
Use build_mcp_prompt(owner, repo) to tell the agent which MCP tools to call, then pass the
raw MCP output into parse_mcp_response(mcp_output) for lightweight extraction.

Expected MCP tools in agent contexts:
- mcp__github-mcp-server__get_file_contents
- mcp__github-mcp-server__search_code
- mcp__filesystem__read_file
- mcp__filesystem__list_directory
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

DEFAULTS = {
    "project_name": "service-project",
    "description": "A formally introduced service supporting documented business outcomes.",
    "service_tier": 2,
    "owner": "[OWNER_NAME]",
    "business_purpose": "Provide a clear, supportable, and measurable digital service for internal or external users.",
    "business_drivers": [
        "Improve service reliability and operational readiness",
        "Create an auditable onboarding record for support and governance",
        "Provide stakeholders with clear ownership and SLO commitments"
    ],
    "compliance": ["none"],
    "availability_slo": "99.9%",
    "rto": "4h",
    "rpo": "1h",
    "l1_support": "Service Desk",
    "l2_support": "Platform Operations",
    "l3_support": "Engineering Team",
    "go_live_date": "TBD",
    "template_type": "generic",
    "mcp_source": None
}
ENV_MAP = {
    "project_name": "SID_PROJECT_NAME",
    "description": "SID_DESCRIPTION",
    "service_tier": "SID_SERVICE_TIER",
    "owner": "SID_OWNER",
    "business_purpose": "SID_BUSINESS_PURPOSE",
    "business_drivers": "SID_BUSINESS_DRIVERS",
    "compliance": "SID_COMPLIANCE",
    "availability_slo": "SID_AVAILABILITY_SLO",
    "rto": "SID_RTO",
    "rpo": "SID_RPO",
    "l1_support": "SID_L1_SUPPORT",
    "l2_support": "SID_L2_SUPPORT",
    "l3_support": "SID_L3_SUPPORT",
    "go_live_date": "SID_GO_LIVE_DATE",
    "template_type": "SID_TEMPLATE_TYPE"
}


def build_mcp_prompt(owner: str, repo: str) -> str:
    return (
        f"Use GitHub MCP to inspect {owner}/{repo}. Read README.md, package manifests, architecture docs, "
        "and search for API routes, service clients, and documentation directories. Return concise JSON with "
        "project_name, description, docs, apis, services, and notable findings."
    )


def parse_mcp_response(mcp_output: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(mcp_output)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    result: Dict[str, Any] = {}
    name_match = re.search(r'"project_name"\s*:\s*"([^"]+)"', mcp_output)
    description_match = re.search(r'"description"\s*:\s*"([^"]+)"', mcp_output)
    if name_match:
        result["project_name"] = name_match.group(1)
    if description_match:
        result["description"] = description_match.group(1)
    return result


def split_list(value: str) -> List[str]:
    return [item.strip() for item in re.split(r"[;,\n]", value) if item.strip()]


def ask(question: str, default: str) -> str:
    try:
        answer = input(f"{question} [{default}]: ").strip()
    except EOFError:
        return default
    return answer or default


def load_env_defaults() -> Dict[str, Any]:
    context = dict(DEFAULTS)
    for key, env_name in ENV_MAP.items():
        raw = os.environ.get(env_name)
        if not raw:
            continue
        if key in {"business_drivers", "compliance"}:
            context[key] = split_list(raw)
        elif key == "service_tier":
            try:
                context[key] = int(raw)
            except ValueError:
                context[key] = DEFAULTS[key]
        else:
            context[key] = raw
    return context


def collect_interactive(context: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(context)
    tier = ask("What is the intended service tier? [1=Business Critical / 2=Business Important / 3=Supporting]", str(data["service_tier"]))
    owner = ask("Who is the service owner? (name and team)", str(data["owner"]))
    purpose = ask("What is the primary business purpose of this service? (1-2 sentences)", str(data["business_purpose"]))
    drivers = ask("What are the key business drivers for introducing this service? (list 3)", "; ".join(data["business_drivers"]))
    compliance = ask("What regulatory or compliance frameworks apply? (PCI-DSS, GDPR, FCA, HIPAA, SOC2, ISO27001, none)", "; ".join(data["compliance"]))
    availability = ask("What is the target availability SLO? [99.9% / 99.5% / 99.0% / custom]", str(data["availability_slo"]))
    rto = ask("What is the RTO target? [1h / 4h / 8h / 24h / custom]", str(data["rto"]))
    rpo = ask("What is the RPO target? [1h / 4h / 8h / 24h / custom]", str(data["rpo"]))
    support = ask("Who are the L1/L2/L3 support contacts?", f"{data['l1_support']}; {data['l2_support']}; {data['l3_support']}")
    go_live = ask("Is there a go-live date planned? (YYYY-MM-DD or TBD)", str(data["go_live_date"]))
    template_type = ask("What template type? [generic / api-service / ai-service / platform-service]", str(data["template_type"]))

    support_parts = split_list(support)
    while len(support_parts) < 3:
        support_parts.append(DEFAULTS[["l1_support", "l2_support", "l3_support"][len(support_parts)]])

    data.update({
        "service_tier": int(tier) if tier in {"1", "2", "3"} else DEFAULTS["service_tier"],
        "owner": owner,
        "business_purpose": purpose,
        "business_drivers": split_list(drivers)[:3] or list(DEFAULTS["business_drivers"]),
        "compliance": split_list(compliance) or list(DEFAULTS["compliance"]),
        "availability_slo": availability,
        "rto": rto,
        "rpo": rpo,
        "l1_support": support_parts[0],
        "l2_support": support_parts[1],
        "l3_support": support_parts[2],
        "go_live_date": go_live,
        "template_type": template_type if template_type in {"generic", "api-service", "ai-service", "platform-service"} else "generic"
    })
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect SID context interactively or from environment variables.")
    parser.add_argument("--output-json", default=".sid-context.json", help="Path to write the collected JSON context.")
    parser.add_argument("--no-interactive", action="store_true", help="Skip prompts and use environment variables or defaults.")
    parser.add_argument("--mcp-github", metavar="OWNER/REPO", help="Record a GitHub repository as an MCP source hint.")
    parser.add_argument("--project-name", help="Seed project name before prompting.")
    parser.add_argument("--description", help="Seed project description before prompting.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    context = load_env_defaults()
    if args.project_name:
        context["project_name"] = args.project_name
    if args.description:
        context["description"] = args.description
    if args.mcp_github:
        context["mcp_source"] = f"github:{args.mcp_github}"

    if not args.no_interactive and sys.stdin.isatty():
        context = collect_interactive(context)

    output_path = Path(args.output_json).expanduser()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(context, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] Failed to write context JSON: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(context, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
