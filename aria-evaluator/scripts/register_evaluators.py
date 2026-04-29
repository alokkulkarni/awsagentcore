#!/usr/bin/env python3
"""
scripts/register_evaluators.py
================================
Registers all evaluator_configs/*.json files with AWS Bedrock AgentCore.

Usage::

    # Register all evaluator configs
    python scripts/register_evaluators.py

    # Register a specific category only
    python scripts/register_evaluators.py --category response_quality

    # List already-registered evaluators
    python scripts/register_evaluators.py --list

    # Dry-run (no API calls)
    python scripts/register_evaluators.py --dry-run

Environment variables required:
    AWS_REGION          e.g. eu-west-2
    AWS_PROFILE         optional, for named profiles
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from judge.agentcore_evaluators import AgentCoreEvaluatorRegistry  # noqa: E402


CONFIGS_DIR = Path(__file__).parent.parent / "evaluator_configs"


def load_configs(category: str | None = None) -> list[tuple[str, dict]]:
    """Load evaluator config JSONs from evaluator_configs/."""
    results = []
    search_root = CONFIGS_DIR / category if category else CONFIGS_DIR
    if not search_root.exists():
        print(f"[ERROR] Directory not found: {search_root}")
        sys.exit(1)

    for json_file in sorted(search_root.rglob("*.json")):
        try:
            config = json.loads(json_file.read_text())
            results.append((str(json_file.relative_to(CONFIGS_DIR)), config))
        except json.JSONDecodeError as exc:
            print(f"[WARN] Skipping malformed JSON {json_file}: {exc}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Register ARIA evaluators with AgentCore.")
    parser.add_argument("--category", help="Register only a specific category (e.g. response_quality)")
    parser.add_argument("--list", action="store_true", help="List registered evaluators")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be registered without calling APIs")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "eu-west-2"))
    args = parser.parse_args()

    registry = AgentCoreEvaluatorRegistry(region=args.region)

    if args.list:
        try:
            evaluators = registry.list_evaluators()
            if not evaluators:
                print("No evaluators registered.")
            else:
                print(f"{'Name':<50} {'Level':<15} {'Status'}")
                print("-" * 80)
                for ev in evaluators:
                    print(f"{ev.get('name', 'N/A'):<50} {ev.get('evaluationLevel', 'N/A'):<15} {ev.get('status', 'N/A')}")
        except Exception as exc:
            print(f"[ERROR] Could not list evaluators: {exc}")
        return

    configs = load_configs(args.category)
    print(f"Found {len(configs)} evaluator config(s){' in ' + args.category if args.category else ''}.")

    if args.dry_run:
        for path, cfg in configs:
            print(f"  [DRY-RUN] Would register: {path}  →  {cfg.get('name')}")
        return

    success = 0
    failed = 0
    for path, cfg in configs:
        name = cfg.get("name", path)
        try:
            ev_name = cfg.get("name", path)
            ev_level = cfg.get("evaluationLevel", "TRACE")
            ev_config = cfg.get("config", cfg)
            result = registry.register_one(ev_name, ev_config, ev_level)
            evaluator_id = result.get("evaluator_id") or result.get("name", "?")
            print(f"  [OK] {name:<50} → {evaluator_id}")
            success += 1
        except Exception as exc:
            print(f"  [FAIL] {name:<50} → {exc}")
            failed += 1

    print(f"\nRegistration complete: {success} succeeded, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
