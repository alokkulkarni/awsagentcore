#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Collect configuration for the webapp scaffold skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

CONFIG_FILE = "webapp-config.json"
VERTICAL_CHOICES = {"banking", "insurance", "ecommerce", "corporate", "generic"}
DEPLOY_CHOICES = {"cloudfront", "docker", "both"}
CHAT_PROVIDER_CHOICES = {"amazon-connect", "intercom", "zendesk", "crisp", "freshchat", "custom"}
WIDGET_POSITION_CHOICES = {"bottom-right", "bottom-left"}
ICON_CHOICES = {"CHAT", "CHAT_VOICE"}

DEFAULTS: Dict[str, Any] = {
    "project_name": "my-webapp",
    "brand_name": "My App",
    "vertical": "generic",
    "brand_color": "#0D2A66",
    "accent_color": "#E63012",
    "background_color": "#f5f6fa",
    "logo": "text",
    "logo_text": "M",
    "nav_items": ["Home", "Solutions", "Support"],
    "hero_headline": "Banking made simple",
    "hero_subtitle": "Launch a polished, trusted experience with secure customer support built in.",
    "primary_cta_label": "Get started",
    "secondary_cta_label": "Sign in",
    "chat": {
        "enabled": False,
        "provider": "none",
        "provider_config": {},
        "widget_position": "bottom-right",
        "widget_color": "",
        "bot_display_name": "",
        "agent_display_name": "",
    },
    "deploy_target": "both",
    "port": 4001,
    "include_features": True,
    "feature_items": [
        {"icon": "✨", "label": "Launch-ready experiences"},
        {"icon": "🔒", "label": "Secure customer journeys"},
    ],
    "include_products": False,
    "footer_text": "© 2026 My App. All rights reserved.",
    "copyright_entity": "My App",
}

VERTICAL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "banking": {
        "nav_items": ["Accounts", "Payments", "Support"],
        "hero_headline": "Banking made simple",
        "hero_subtitle": "Deliver trusted self-service, fast account journeys, and instant help from one branded experience.",
        "feature_items": [
            {"icon": "💳", "label": "Instant transfers"},
            {"icon": "📊", "label": "Money insights"},
            {"icon": "🤝", "label": "Advisor support"},
        ],
    },
    "insurance": {
        "nav_items": ["Cover", "Claims", "Support"],
        "hero_headline": "Insurance that feels reassuring",
        "hero_subtitle": "Help customers quote, claim, and get answers quickly through a calm, accessible journey.",
        "feature_items": [
            {"icon": "🛡️", "label": "Policy clarity"},
            {"icon": "🚗", "label": "Faster claims"},
            {"icon": "📞", "label": "Always-on support"},
        ],
    },
    "ecommerce": {
        "nav_items": ["Shop", "Collections", "Support"],
        "hero_headline": "Shop smarter, faster",
        "hero_subtitle": "Launch a storefront that highlights categories, promotions, and responsive customer support.",
        "feature_items": [
            {"icon": "🛍️", "label": "Featured drops"},
            {"icon": "🚚", "label": "Fast fulfilment"},
            {"icon": "💬", "label": "Order help"},
        ],
    },
    "corporate": {
        "nav_items": ["Services", "About", "Contact"],
        "hero_headline": "Trusted digital experiences for modern teams",
        "hero_subtitle": "Present your services clearly, reinforce credibility, and create a strong path to contact or conversion.",
        "feature_items": [
            {"icon": "📈", "label": "Growth services"},
            {"icon": "🧭", "label": "Clear positioning"},
            {"icon": "🤝", "label": "Sales enablement"},
        ],
    },
    "generic": {
        "nav_items": ["Home", "Features", "Support"],
        "hero_headline": "Launch with confidence",
        "hero_subtitle": "Create a clean, production-ready webapp shell with reusable branding and secure defaults.",
        "feature_items": [
            {"icon": "✨", "label": "Reusable layout"},
            {"icon": "🔒", "label": "Secure defaults"},
            {"icon": "⚡", "label": "Fast iteration"},
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect inputs for the webapp scaffold skill.")
    parser.add_argument("--output", default=CONFIG_FILE, help="Path to write the collected configuration JSON.")
    parser.add_argument("--reask", action="store_true", help="Ignore any existing config and prompt again.")
    return parser.parse_args()


def prompt(question: str, default: str) -> str:
    try:
        answer = input(f"{question} [{default}]: ").strip()
    except EOFError:
        return default
    return answer or default


def prompt_bool(question: str, default: bool) -> bool:
    label = "y" if default else "n"
    while True:
        value = prompt(question, label).lower()
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please answer y or n.")


def prompt_choice(question: str, choices: set[str], default: str) -> str:
    while True:
        value = prompt(question, default).lower()
        if value in choices:
            return value
        print(f"Please choose one of: {', '.join(sorted(choices))}.")


def prompt_int(question: str, default: int) -> int:
    while True:
        value = prompt(question, str(default))
        try:
            port = int(value)
        except ValueError:
            print("Please enter a valid integer.")
            continue
        if 1 <= port <= 65535:
            return port
        print("Please enter a port between 1 and 65535.")


def split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_feature_items(value: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for entry in split_csv(value):
        icon = "✨"
        label = entry
        parts = entry.split(maxsplit=1)
        if len(parts) == 2 and parts[0]:
            first = parts[0].strip()
            if len(first) <= 3 or any(ord(char) > 127 for char in first):
                icon = first
                label = parts[1].strip() or entry
        items.append({"icon": icon, "label": label})
    return items


def build_defaults(vertical: str, brand_name: str) -> Dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULTS))
    merged.update(VERTICAL_DEFAULTS.get(vertical, {}))
    merged["brand_name"] = brand_name
    merged["chat"]["agent_display_name"] = brand_name
    merged["footer_text"] = f"© 2026 {brand_name}. All rights reserved."
    merged["copyright_entity"] = brand_name
    return merged


def should_reuse(path: Path) -> bool:
    if not path.exists():
        return False
    if not sys.stdin.isatty():
        return True
    try:
        answer = input(f"{path.name} already exists. Reuse it instead of re-asking? [Y/n]: ").strip().lower()
    except EOFError:
        return True
    return answer in {"", "y", "yes"}


def load_existing(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def collect_config() -> Dict[str, Any]:
    project_name = prompt("Project name?", DEFAULTS["project_name"])
    brand_name = prompt("Brand / organisation name?", DEFAULTS["brand_name"])
    vertical = prompt_choice(
        "Vertical / industry? [banking|insurance|ecommerce|corporate|generic]",
        VERTICAL_CHOICES,
        DEFAULTS["vertical"],
    )

    defaults = build_defaults(vertical, brand_name)

    brand_color = prompt("Primary brand colour (hex)?", defaults["brand_color"])
    accent_color = prompt("Accent / CTA colour (hex)?", defaults["accent_color"])
    background_color = prompt("Background colour (hex)?", defaults["background_color"])
    logo = prompt("Logo: path to logo file, OR 'text' for text-only logo?", defaults["logo"])
    logo_text = prompt("Logo text / monogram?", defaults["logo_text"])
    nav_items = split_csv(prompt(
        'Header nav items? (comma-separated, e.g. "Accounts,Payments,Support")',
        ", ".join(defaults["nav_items"]),
    )) or list(defaults["nav_items"])
    hero_headline = prompt("Hero headline?", defaults["hero_headline"])
    hero_subtitle = prompt("Hero subtitle?", defaults["hero_subtitle"])
    primary_cta_label = prompt("Primary CTA label?", defaults["primary_cta_label"])
    secondary_cta_label = prompt("Secondary CTA label?", defaults["secondary_cta_label"])

    include_chat = prompt_bool("Include a chat / messaging widget? [y/n]", defaults["chat"]["enabled"])
    chat = {
        "enabled": include_chat,
        "provider": "none",
        "provider_config": {},
        "widget_position": defaults["chat"]["widget_position"],
        "widget_color": defaults["chat"]["widget_color"],
        "bot_display_name": defaults["chat"]["bot_display_name"],
        "agent_display_name": brand_name,
    }
    if include_chat:
        provider = prompt_choice(
            "Chat provider? [amazon-connect|intercom|zendesk|crisp|freshchat|custom]",
            CHAT_PROVIDER_CHOICES,
            "amazon-connect",
        )
        provider_config: Dict[str, Any] = {}
        bot_display_name = defaults["chat"]["bot_display_name"] or "Assistant"
        agent_display_name = brand_name

        if provider == "amazon-connect":
            provider_config["script_url"] = prompt("Widget script URL? (leave blank — will prompt at deploy time)", "")
            provider_config["snippet_id"] = prompt("Snippet ID? (leave blank — use env var VITE_CHAT_SNIPPET_ID)", "")
            bot_display_name = prompt("Bot display name?", "Assistant")
            agent_display_name = prompt("System / brand display name?", brand_name)
            provider_config["icon_type"] = prompt_choice("Widget icon type? [CHAT|CHAT_VOICE]", ICON_CHOICES, "CHAT").upper()
        elif provider == "intercom":
            provider_config["app_id"] = prompt("Intercom App ID? (leave blank — use env var VITE_CHAT_APP_ID)", "")
        elif provider == "zendesk":
            provider_config["subdomain"] = prompt("Zendesk subdomain? (leave blank — use env var VITE_CHAT_SUBDOMAIN)", "")
            provider_config["key"] = prompt("Zendesk Web Widget key? (leave blank — use env var VITE_CHAT_KEY)", "")
        elif provider == "crisp":
            provider_config["website_id"] = prompt("Crisp Website ID? (leave blank — use env var VITE_CHAT_WEBSITE_ID)", "")
        elif provider == "freshchat":
            provider_config["token"] = prompt("Freshchat token? (leave blank — use env var VITE_CHAT_TOKEN)", "")
        elif provider == "custom":
            provider_config["script_url"] = prompt("Widget script URL? (leave blank — use env var VITE_CHAT_SCRIPT_URL)", "")
            provider_config["init_function"] = prompt("Widget init function name?", "initChat")

        chat = {
            "enabled": True,
            "provider": provider,
            "provider_config": provider_config,
            "widget_position": prompt_choice("Widget position? [bottom-right|bottom-left]", WIDGET_POSITION_CHOICES, defaults["chat"]["widget_position"]),
            "widget_color": prompt("Widget primary colour?", brand_color),
            "bot_display_name": bot_display_name,
            "agent_display_name": agent_display_name,
        }

    deploy_target = prompt_choice("Deploy target? [cloudfront|docker|both]", DEPLOY_CHOICES, defaults["deploy_target"])
    port = prompt_int("Port for local dev?", defaults["port"])

    include_features = prompt_bool("Include feature cards section? [y/n]", defaults["include_features"])
    feature_items = list(defaults["feature_items"])
    if include_features:
        feature_items = parse_feature_items(prompt(
            'Feature items? (comma-separated icons+labels, e.g. "💳 Instant Transfers,📊 Insights")',
            ", ".join(f"{item['icon']} {item['label']}" for item in defaults["feature_items"]),
        )) or list(defaults["feature_items"])

    include_products = prompt_bool("Include products/services grid? [y/n]", defaults["include_products"])
    footer_text = prompt("Footer text?", f"© 2026 {brand_name}. All rights reserved.")
    copyright_entity = prompt("Copyright entity?", brand_name)

    return {
        "project_name": project_name,
        "brand_name": brand_name,
        "vertical": vertical,
        "brand_color": brand_color,
        "accent_color": accent_color,
        "background_color": background_color,
        "logo": logo,
        "logo_text": logo_text,
        "nav_items": nav_items,
        "hero_headline": hero_headline,
        "hero_subtitle": hero_subtitle,
        "primary_cta_label": primary_cta_label,
        "secondary_cta_label": secondary_cta_label,
        "chat": chat,
        "deploy_target": deploy_target,
        "port": port,
        "include_features": include_features,
        "feature_items": feature_items,
        "include_products": include_products,
        "footer_text": footer_text,
        "copyright_entity": copyright_entity,
    }


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).expanduser().resolve()

    if output_path.exists() and not args.reask and should_reuse(output_path):
        existing = load_existing(output_path)
        print(json.dumps(existing, indent=2, ensure_ascii=False))
        return 0

    if sys.stdin.isatty():
        config = collect_config()
    else:
        brand_name = DEFAULTS["brand_name"]
        config = build_defaults(DEFAULTS["vertical"], brand_name)
        config["project_name"] = DEFAULTS["project_name"]

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] Failed to write {output_path}: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(config, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
