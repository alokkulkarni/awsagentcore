#!/usr/bin/env python3
"""Scaffold a branded React + Vite webapp with optional chat widget integration."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Sequence
from urllib.parse import urlparse

from scaffold_tests import TEST_DEV_DEPENDENCIES, build_test_files, merge_package_json

VALID_VERTICALS = {"banking", "insurance", "ecommerce", "corporate", "generic"}
VALID_DEPLOY_TARGETS = {"cloudfront", "docker", "both"}
VALID_CHAT_PROVIDERS = {"none", "amazon-connect", "intercom", "zendesk", "crisp", "freshchat", "custom"}
VALID_WIDGET_POSITIONS = {"bottom-right", "bottom-left"}
VALID_ICON_TYPES = {"CHAT", "CHAT_VOICE"}
SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = SKILL_ROOT / "templates"

DEFAULT_FEATURE_DETAILS: Dict[str, Dict[str, str]] = {
    "banking": {
        "Instant transfers": "Move money in seconds with a reassuring, brand-led journey that reduces friction for everyday payments.",
        "Money insights": "Translate balances and spending trends into clear next steps for customers and support teams.",
        "Advisor support": "Escalate from self-service into assisted support without breaking the customer journey.",
    },
    "insurance": {
        "Policy clarity": "Surface cover details and service actions clearly so policyholders can move with confidence.",
        "Faster claims": "Guide customers through claim journeys with simpler copy, clearer status, and consistent support touchpoints.",
        "Always-on support": "Blend FAQs, chatbot answers, and assisted service so urgent questions do not stall key journeys.",
    },
    "ecommerce": {
        "Featured drops": "Highlight priority launches and seasonal campaigns with a layout built to convert attention into action.",
        "Fast fulfilment": "Reinforce delivery confidence with concise value messaging around shipping, tracking, and returns.",
        "Order help": "Offer support-ready pathways for questions about orders, products, and post-purchase care.",
    },
    "corporate": {
        "Growth services": "Explain complex service lines through concise messaging that helps prospects self-qualify faster.",
        "Clear positioning": "Use strong visual hierarchy and contrast to reinforce trust, capability, and differentiation.",
        "Sales enablement": "Create a straightforward handoff from marketing content to contact, consultation, or support workflows.",
    },
    "generic": {
        "Reusable layout": "Start from a clean structure with consistent spacing, typography, and responsive building blocks.",
        "Secure defaults": "Ship with sensible CSP, env-driven configuration, and deployment-ready guardrails from the first commit.",
        "Fast iteration": "Keep the stack lightweight so teams can move quickly from scaffold to production refinement.",
    },
}

DEFAULT_FEATURE_ICONS: Dict[str, List[str]] = {
    "banking": ["💳", "📊", "🤝"],
    "insurance": ["🛡️", "🚗", "📞"],
    "ecommerce": ["🛍️", "🚚", "💬"],
    "corporate": ["📈", "🧭", "🤝"],
    "generic": ["✨", "🔒", "⚡"],
}

DEFAULT_PRODUCTS: Dict[str, List[Dict[str, str]]] = {
    "banking": [
        {"title": "Current accounts", "description": "Showcase everyday banking journeys, switching incentives, and digital account servicing.", "href": "#current-accounts"},
        {"title": "Mortgages", "description": "Guide applicants through affordability, product comparison, and adviser-assisted next steps.", "href": "#mortgages"},
        {"title": "Savings", "description": "Promote goal-based saving, rate visibility, and confidence-building product detail.", "href": "#savings"},
        {"title": "Card support", "description": "Handle account help, fraud reassurance, and guided support escalation from one place.", "href": "#card-support"},
    ],
    "insurance": [
        {"title": "Motor cover", "description": "Feature quote journeys, cover highlights, and support options for policy changes.", "href": "#motor-cover"},
        {"title": "Home cover", "description": "Present product tiers, claims guidance, and reassurance-oriented content.", "href": "#home-cover"},
        {"title": "Claims hub", "description": "Use structured cards to direct customers to the right claim or emergency workflow fast.", "href": "#claims-hub"},
        {"title": "Member support", "description": "Support renewals, amendments, and policy questions through self-service and chat.", "href": "#member-support"},
    ],
    "ecommerce": [
        {"title": "New arrivals", "description": "Launch a flexible hero-to-category journey for seasonal campaigns and featured collections.", "href": "#new-arrivals"},
        {"title": "Best sellers", "description": "Highlight social-proofed inventory with strong CTA placement and clean product storytelling.", "href": "#best-sellers"},
        {"title": "Delivery & returns", "description": "Reduce purchase hesitation with concise support, shipping, and returns guidance.", "href": "#delivery-returns"},
        {"title": "Customer care", "description": "Route order questions and post-purchase support through the same branded shell.", "href": "#customer-care"},
    ],
    "corporate": [
        {"title": "Advisory services", "description": "Explain service pillars with a format that balances authority, clarity, and conversion focus.", "href": "#advisory-services"},
        {"title": "Delivery model", "description": "Summarise how engagements are structured, governed, and delivered to clients.", "href": "#delivery-model"},
        {"title": "Industry expertise", "description": "Showcase vertical knowledge and outcome-led credentials in a reusable grid.", "href": "#industry-expertise"},
        {"title": "Contact pathways", "description": "Offer direct routes to consultation, sales contact, and service support teams.", "href": "#contact-pathways"},
    ],
    "generic": [
        {"title": "Platform overview", "description": "Describe the core user journey and the value of the product in clear, benefit-led terms.", "href": "#platform-overview"},
        {"title": "Key workflows", "description": "Group major tasks or capabilities into easy-to-scan cards for first-time visitors.", "href": "#key-workflows"},
        {"title": "Operational trust", "description": "Highlight uptime, support responsiveness, and security posture in product language.", "href": "#operational-trust"},
        {"title": "Getting started", "description": "Help users move from first impression to action with minimal friction.", "href": "#getting-started"},
    ],
}

PROMO_CARDS: Dict[str, List[Dict[str, str]]] = {
    "banking": [
        {"eyebrow": "Digital confidence", "title": "Designed for trusted everyday banking", "body": "Use brand-led journeys, clear hierarchy, and optional chat support to reduce customer effort.", "tone": "brand"},
        {"eyebrow": "Operational readiness", "title": "CloudFront-ready from day one", "body": "The scaffold ships with env examples, CSP guidance, and deployment notes for HTTPS-only hosting.", "tone": "accent"},
    ],
    "insurance": [
        {"eyebrow": "Customer reassurance", "title": "Claim and support journeys that feel calm", "body": "Pair concise content with high-contrast controls and clear pathways into assisted support.", "tone": "brand"},
        {"eyebrow": "Secure rollout", "title": "Production defaults built in", "body": "Start with CSP, env-driven configuration, and deployment guidance that keeps public delivery predictable.", "tone": "accent"},
    ],
    "ecommerce": [
        {"eyebrow": "Conversion focus", "title": "Keep the path from hero to checkout simple", "body": "Use high-signal cards, clear CTAs, and optional support chat to reduce hesitation.", "tone": "brand"},
        {"eyebrow": "Support at scale", "title": "Handle pre- and post-purchase questions elegantly", "body": "Blend self-service content with the chat provider that fits your support model when responsive help matters.", "tone": "accent"},
    ],
    "corporate": [
        {"eyebrow": "Credibility", "title": "Present services with more authority", "body": "Combine a confident header, value-led hero, and structured service cards in one clean shell.", "tone": "brand"},
        {"eyebrow": "Contact ready", "title": "Create a stronger path to conversation", "body": "Position CTAs and optional chat support so teams can move prospects toward discovery faster.", "tone": "accent"},
    ],
    "generic": [
        {"eyebrow": "Reusable foundation", "title": "Move from scaffold to product quickly", "body": "Keep the implementation lightweight while retaining production-minded defaults and component boundaries.", "tone": "brand"},
        {"eyebrow": "Secure by default", "title": "Start with sensible frontend guardrails", "body": "CSP, env handling, and deployment guidance are included so the base project is ready for real delivery work.", "tone": "accent"},
    ],
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scaffold a React + Vite webapp from webapp-config.json.")
    parser.add_argument("--config", default="webapp-config.json", help="Path to the config JSON file.")
    parser.add_argument("--output", help="Target output directory. Defaults to ./<project-name>.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned writes without creating files.")
    return parser.parse_args(argv)


def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"[ERROR] Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] Failed to parse JSON from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("[ERROR] Config must be a JSON object.")
    return data


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return cleaned.strip("-") or "webapp"


def sanitize_string(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def sanitize_string_list(value: Any, fallback: List[str]) -> List[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return items
    return list(fallback)


def normalize_hex(value: str) -> str:
    candidate = value.strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", candidate):
        raise SystemExit(f"[ERROR] Invalid hex colour: {value}")
    return candidate.upper()


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    colour = normalize_hex(value).lstrip("#")
    return tuple(int(colour[index:index + 2], 16) for index in range(0, 6, 2))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, channel)):02X}" for channel in rgb)


def rgb_string(value: str) -> str:
    return " ".join(str(channel) for channel in hex_to_rgb(value))


def blend(hex_colour: str, target_hex: str, ratio: float) -> str:
    base = hex_to_rgb(hex_colour)
    target = hex_to_rgb(target_hex)
    mixed = tuple(round(base[index] + (target[index] - base[index]) * ratio) for index in range(3))
    return rgb_to_hex(mixed)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    def transform(channel: int) -> float:
        value = channel / 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (transform(channel) for channel in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    first = relative_luminance(hex_to_rgb(foreground))
    second = relative_luminance(hex_to_rgb(background))
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def accessible_text(background: str) -> str:
    white_ratio = contrast_ratio("#FFFFFF", background)
    dark_ratio = contrast_ratio("#111827", background)
    return "#FFFFFF" if white_ratio >= dark_ratio else "#111827"


def feature_description(label: str, vertical: str, brand_name: str) -> str:
    if label in DEFAULT_FEATURE_DETAILS[vertical]:
        return DEFAULT_FEATURE_DETAILS[vertical][label]
    return f"{brand_name} uses {label.lower()} to keep the experience clear, responsive, and ready for real customer traffic."




def build_feature_items(raw_items: Any, vertical: str, brand_name: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, dict):
                label = sanitize_string(item.get("label"), "")
                icon = sanitize_string(item.get("icon"), "✨")
            else:
                entry = str(item).strip()
                if not entry:
                    continue
                icon = "✨"
                label = entry
                parts = entry.split(maxsplit=1)
                if len(parts) == 2 and parts[0]:
                    first = parts[0].strip()
                    if len(first) <= 3 or any(ord(char) > 127 for char in first):
                        icon = first
                        label = parts[1].strip() or entry
            if not label:
                continue
            items.append(
                {
                    "icon": icon,
                    "title": label,
                    "description": feature_description(label, vertical, brand_name),
                }
            )
    if items:
        return items
    return [
        {"icon": DEFAULT_FEATURE_ICONS[vertical][index], "title": label, "description": description}
        for index, (label, description) in enumerate(DEFAULT_FEATURE_DETAILS[vertical].items())
    ]


def build_product_items(vertical: str) -> List[Dict[str, str]]:
    return [dict(item) for item in DEFAULT_PRODUCTS[vertical]]


def build_promo_cards(vertical: str) -> List[Dict[str, str]]:
    return [dict(item) for item in PROMO_CARDS[vertical]]




def load_config(config_path: Path) -> Dict[str, Any]:
    data = read_json(config_path)
    vertical = sanitize_string(data.get("vertical"), "generic").lower()
    if vertical not in VALID_VERTICALS:
        raise SystemExit(f"[ERROR] Unsupported vertical: {vertical}")

    project_name = sanitize_string(data.get("project_name"), "my-webapp")
    package_name = slugify(project_name)
    brand_name = sanitize_string(data.get("brand_name"), "My App")
    brand_color = normalize_hex(sanitize_string(data.get("brand_color"), "#0D2A66"))
    accent_color = normalize_hex(sanitize_string(data.get("accent_color"), "#E63012"))
    background_source = data.get("background_color") if data.get("background_color") is not None else data.get("bg_color")
    background_color = normalize_hex(sanitize_string(background_source, "#F5F6FA"))

    legacy_connect_cfg = data.get("connect") if isinstance(data.get("connect"), dict) else {}
    chat_cfg = data.get("chat") if isinstance(data.get("chat"), dict) else {}
    if not chat_cfg and legacy_connect_cfg:
        chat_cfg = {
            "enabled": bool(legacy_connect_cfg.get("enabled", False)),
            "provider": "amazon-connect" if legacy_connect_cfg.get("enabled", False) else "none",
            "provider_config": {
                "script_url": sanitize_string(legacy_connect_cfg.get("script_url"), ""),
                "snippet_id": sanitize_string(legacy_connect_cfg.get("snippet_id"), ""),
                "icon_type": sanitize_string(legacy_connect_cfg.get("icon_type"), "CHAT"),
            },
            "widget_color": sanitize_string(legacy_connect_cfg.get("widget_primary_color"), brand_color),
            "bot_display_name": sanitize_string(legacy_connect_cfg.get("bot_display_name"), "Assistant"),
            "agent_display_name": sanitize_string(legacy_connect_cfg.get("system_display_name"), brand_name),
        }

    deploy_target = sanitize_string(data.get("deploy_target"), "both").lower()
    if deploy_target not in VALID_DEPLOY_TARGETS:
        deploy_target = "both"

    port = int(data.get("port", 4001))
    if not 1 <= port <= 65535:
        port = 4001

    provider = sanitize_string(chat_cfg.get("provider"), "none").lower()
    if provider not in VALID_CHAT_PROVIDERS:
        provider = "none"

    raw_provider_config = chat_cfg.get("provider_config") if isinstance(chat_cfg.get("provider_config"), dict) else {}
    widget_position = sanitize_string(chat_cfg.get("widget_position"), "bottom-right").lower()
    if widget_position not in VALID_WIDGET_POSITIONS:
        widget_position = "bottom-right"
    widget_color = normalize_hex(sanitize_string(chat_cfg.get("widget_color"), brand_color))
    bot_display_name = sanitize_string(chat_cfg.get("bot_display_name"), "Assistant")
    agent_display_name = sanitize_string(chat_cfg.get("agent_display_name"), brand_name)
    chat_enabled = bool(chat_cfg.get("enabled", False)) and provider != "none"

    normalized_provider_config: Dict[str, Any] = {}
    if chat_enabled:
        if provider == "amazon-connect":
            icon_type = sanitize_string(raw_provider_config.get("icon_type"), "CHAT").upper()
            if icon_type not in VALID_ICON_TYPES:
                icon_type = "CHAT"
            on_widget = accessible_text(widget_color)
            normalized_provider_config = {
                "script_url": sanitize_string(raw_provider_config.get("script_url"), ""),
                "snippet_id": sanitize_string(raw_provider_config.get("snippet_id"), ""),
                "icon_type": icon_type,
                "script_integrity": sanitize_string(raw_provider_config.get("script_integrity"), ""),
                "bot_display_name": bot_display_name,
                "agent_display_name": agent_display_name,
                "widget_position": widget_position,
                "widget_color": widget_color,
                "styles": {
                    "openChat": {"color": on_widget, "backgroundColor": widget_color},
                    "closeChat": {"color": on_widget, "backgroundColor": widget_color},
                },
            }
        elif provider == "intercom":
            normalized_provider_config = {
                "app_id": sanitize_string(raw_provider_config.get("app_id"), ""),
                "settings": raw_provider_config.get("settings") if isinstance(raw_provider_config.get("settings"), dict) else {},
                "widget_position": widget_position,
                "widget_color": widget_color,
            }
        elif provider == "zendesk":
            normalized_provider_config = {
                "subdomain": sanitize_string(raw_provider_config.get("subdomain"), ""),
                "key": sanitize_string(raw_provider_config.get("key"), ""),
                "widget_position": widget_position,
                "widget_color": widget_color,
            }
        elif provider == "crisp":
            normalized_provider_config = {
                "website_id": sanitize_string(raw_provider_config.get("website_id"), ""),
                "widget_position": widget_position,
                "widget_color": widget_color,
            }
        elif provider == "freshchat":
            normalized_provider_config = {
                "token": sanitize_string(raw_provider_config.get("token"), ""),
                "host": sanitize_string(raw_provider_config.get("host"), "https://wchat.freshchat.com"),
                "widget_position": widget_position,
                "widget_color": widget_color,
            }
        elif provider == "custom":
            normalized_provider_config = {
                "script_url": sanitize_string(raw_provider_config.get("script_url"), ""),
                "init_function": sanitize_string(raw_provider_config.get("init_function"), "initChat"),
                "script_integrity": sanitize_string(raw_provider_config.get("script_integrity"), ""),
                "widget_position": widget_position,
                "widget_color": widget_color,
                "bot_display_name": bot_display_name,
                "agent_display_name": agent_display_name,
            }

    return {
        "project_name": project_name,
        "package_name": package_name,
        "brand_name": brand_name,
        "vertical": vertical,
        "brand_color": brand_color,
        "accent_color": accent_color,
        "background_color": background_color,
        "logo": sanitize_string(data.get("logo") if data.get("logo") is not None else data.get("logo_type"), "text"),
        "logo_text": sanitize_string(data.get("logo_text"), brand_name[:1].upper() or "M"),
        "nav_items": sanitize_string_list(data.get("nav_items"), ["Home", "Solutions", "Support"]),
        "hero_headline": sanitize_string(data.get("hero_headline"), "Launch with confidence"),
        "hero_subtitle": sanitize_string(data.get("hero_subtitle"), "Create a trusted, production-ready experience with secure defaults built in."),
        "primary_cta_label": sanitize_string(data.get("primary_cta_label") if data.get("primary_cta_label") is not None else data.get("cta_primary"), "Get started"),
        "secondary_cta_label": sanitize_string(data.get("secondary_cta_label") if data.get("secondary_cta_label") is not None else data.get("cta_secondary"), "Learn more"),
        "chat": {
            "enabled": chat_enabled,
            "provider": provider if chat_enabled else "none",
            "provider_config": normalized_provider_config,
            "widget_position": widget_position,
            "widget_color": widget_color,
            "bot_display_name": bot_display_name,
            "agent_display_name": agent_display_name,
        },
        "deploy_target": deploy_target,
        "port": port,
        "include_features": bool(data.get("include_features", True)),
        "feature_items": build_feature_items(data.get("feature_items"), vertical, brand_name),
        "include_products": bool(data.get("include_products", False)),
        "product_items": build_product_items(vertical),
        "promo_cards": build_promo_cards(vertical),
        "footer_text": sanitize_string(data.get("footer_text"), f"© 2026 {brand_name}. All rights reserved."),
        "copyright_entity": sanitize_string(data.get("copyright_entity"), brand_name),
    }


def chat_csp_origin(chat_config: Dict[str, Any]) -> str:
    provider_config = chat_config.get("provider_config") if isinstance(chat_config.get("provider_config"), dict) else {}
    script_url = sanitize_string(provider_config.get("script_url"), "")
    if not script_url:
        return ""
    parsed = urlparse(script_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def js(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def render_template(relative_path: str, replacements: Dict[str, str]) -> str:
    template = (TEMPLATE_ROOT / relative_path).read_text(encoding="utf-8")
    for key, value in replacements.items():
        template = template.replace(f"{{{{{key}}}}}", value)
    return template




def build_index_html(config: Dict[str, Any]) -> str:
    chat_origin = chat_csp_origin(config["chat"])
    script_src = "script-src 'self' 'unsafe-inline'"
    connect_src = "connect-src 'self'"
    if config["chat"]["enabled"] and chat_origin:
        script_src = f"{script_src} {chat_origin}"
        connect_src = f"{connect_src} {chat_origin}"
    chat_config_json = json.dumps(config["chat"]["provider_config"], ensure_ascii=False)
    return textwrap.dedent(
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta
      http-equiv="Content-Security-Policy"
      content="default-src 'self'; {script_src}; {connect_src}; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; frame-ancestors 'none';"
    />
    <title>{config['project_name']}</title>
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <script type="module">
      const chatEnabled = {str(config['chat']['enabled']).lower()};
      const chatProvider = import.meta.env.VITE_CHAT_PROVIDER || {json.dumps(config['chat']['provider'])};
      const chatConfig = JSON.parse(import.meta.env.VITE_CHAT_CONFIG || {json.dumps(chat_config_json)});

      if (chatEnabled && chatProvider !== 'none') {{
        // Provider-specific loader is in ChatWidget.jsx
        // This script block is intentionally minimal — all init logic lives in the component
        window.__chatConfig = {{ provider: chatProvider, config: chatConfig }};
      }}
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""
    ).strip() + "\n"


def build_package_json(config: Dict[str, Any]) -> str:
    package = {
        "name": config["package_name"],
        "private": True,
        "version": "1.0.0",
        "type": "module",
        "engines": {"node": ">=20"},
        "scripts": {
            "dev": "vite",
            "build": "vite build --mode production",
            "preview": "vite preview",
            "lint": "eslint src --ext .js,.jsx --report-unused-disable-directives --max-warnings 0",
            "audit": "npm audit --audit-level=high",
            "audit:fix": "npm audit fix",
        },
        "dependencies": {
            "react": "^18.3.1",
            "react-dom": "^18.3.1",
        },
        "devDependencies": {
            "vite": "^5.4.0",
            "@vitejs/plugin-react": "^4.3.1",
            "eslint": "^9.9.0",
            **TEST_DEV_DEPENDENCIES,
        },
    }
    package = merge_package_json(package)
    return json.dumps(package, indent=2) + "\n"


def build_vite_config(config: Dict[str, Any]) -> str:
    port = config["port"]
    return textwrap.dedent(
        f"""import {{ defineConfig }} from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({{ mode }}) => ({{
  plugins: [react()],
  server: {{ port: {port}, host: true }},
  preview: {{ port: {port}, host: true }},
  define: {{ global: 'globalThis' }},
  build: {{
    target: 'es2020',
    minify: 'esbuild',
    sourcemap: mode !== 'production',
    rollupOptions: {{
      output: {{
        manualChunks: {{
          vendor: ['react', 'react-dom'],
        }},
      }},
    }},
    chunkSizeWarningLimit: 500,
  }},
}}));
"""
    ).strip() + "\n"




def build_env_example(config: Dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""# Copy this file to .env for local development.
# Never commit real chat credentials or provider secrets.

# Chat widget configuration
# See docs/chat-providers.md for provider-specific config reference
# VITE_CHAT_PROVIDER=amazon-connect
# VITE_CHAT_CONFIG={{"script_url":"","provider_key":""}}
VITE_CHAT_PROVIDER={config['chat']['provider'] if config['chat']['enabled'] else ''}
VITE_CHAT_CONFIG={json.dumps(config['chat']['provider_config'], ensure_ascii=False)}
"""
    ).strip() + "\n"


def build_gitignore() -> str:
    return "node_modules/\ndist/\ncoverage/\nplaywright-report/\ntest-results/\n.DS_Store\n.env\n.env.*\n!.env.example\n"


def build_npmrc() -> str:
    return "audit=true\nfund=false\nengine-strict=false\n"


def build_eslint_config() -> str:
    return textwrap.dedent(
        """export default [
  {
    ignores: ['dist/**', 'coverage/**', 'playwright-report/**', 'node_modules/**'],
  },
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
      globals: {
        window: 'readonly',
        document: 'readonly',
        navigator: 'readonly',
        MutationObserver: 'readonly',
        NodeFilter: 'readonly',
        URLSearchParams: 'readonly',
        console: 'readonly',
      },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-undef': 'error',
    },
  },
];
"""
    )


def cloudfront_block() -> str:
    return textwrap.dedent(
        """
        ## CloudFront + S3 deployment

        1. Run `npm run build` to generate the production bundle in `dist/`.
        2. Upload the contents of `dist/` to an S3 bucket configured for static asset hosting.
        3. Front the bucket with CloudFront and set **Viewer protocol policy** to **Redirect HTTP to HTTPS**.
        4. If chat is enabled, add the widget script origin to your CSP and complete any provider-side domain allowlisting required for production.
        5. Do not commit real chat credentials or private provider configuration to source control.
        """
    ).strip()


def docker_block(port: int) -> str:
    return textwrap.dedent(
        f"""
        ## Docker-friendly local preview

        The scaffold binds Vite dev and preview to `host: true`, so it works cleanly in containers and remote environments.

        ```bash
        docker compose --profile dev up --build
        open http://localhost:{port}
        ```
        """
    ).strip()




def build_readme(config: Dict[str, Any], output_name: str, logo_asset: str | None) -> str:
    tree_lines = [
        f"{output_name}/",
        "├── index.html",
        "├── package.json",
        "├── package-lock.json",
        "├── vite.config.js",
        "├── vitest.config.js",
        "├── playwright.config.js",
        "├── .env.example",
        "├── .npmrc",
        "├── .gitignore",
        "├── eslint.config.js",
        "├── Dockerfile.prod",
        "├── Dockerfile.dev",
        "├── docker-compose.yml",
        "├── nginx.conf",
        "├── SECURITY.md",
        "├── README.md",
        "├── docs/",
        "│   ├── test-plan.md",
        "│   ├── mobile-checklist.md",
        "│   └── chat-providers.md",
        "├── public/",
        "│   └── favicon.svg",
        "├── e2e/",
        "│   ├── homepage.spec.js",
        "│   ├── mobile.spec.js",
        "│   └── accessibility.spec.js",
        "└── src/",
        "    ├── main.jsx",
        "    ├── App.jsx",
        "    ├── App.css",
        "    ├── index.css",
        "    ├── __tests__/",
        "    │   ├── setup.js",
        "    │   ├── Header.test.jsx",
        "    │   ├── Hero.test.jsx",
        "    │   ├── Footer.test.jsx",
        "    │   └── App.test.jsx",
        "    └── components/",
        "        ├── Header.jsx",
        "        ├── Hero.jsx",
        "        └── Footer.jsx",
    ]
    if logo_asset:
        tree_lines.insert(tree_lines.index("├── e2e/"), f"│   └── {logo_asset}")
    if config["chat"]["enabled"]:
        tree_lines.insert(tree_lines.index("└── src/"), "│   └── chat-widget.spec.js")
        tree_lines.insert(tree_lines.index("    └── components/"), "    │   └── ChatWidget.test.jsx")
        tree_lines.append("        ├── ChatWidget.jsx")
    if config["include_features"]:
        tree_lines.append("        ├── FeatureGrid.jsx")
    if config["include_products"]:
        tree_lines.append("        └── ProductGrid.jsx")

    sections = [
        f"# {config['brand_name']} webapp",
        "",
        f"Production-ready React 18 + Vite scaffold for **{config['brand_name']}** with mobile-first CSS, Vitest + Playwright coverage, optional chat widget support, and Docker-ready deployment assets.",
        "",
        "## Quick start",
        "",
        "```bash",
        "npm install",
        "cp .env.example .env",
        "npm run dev",
        "```",
        "",
        f"The development server runs on port `{config['port']}` by default.",
        "",
        "## Chat Widget",
        "",
        "Configure your chat provider in `webapp-config.json` under the `chat` key. Set `VITE_CHAT_PROVIDER` and `VITE_CHAT_CONFIG` env vars for runtime override. See `docs/chat-providers.md` for all supported providers.",
        "",
        "## Environment variables",
        "",
        "- `VITE_CHAT_PROVIDER` — optional runtime override for the selected chat provider.",
        "- `VITE_CHAT_CONFIG` — optional JSON blob for provider-specific runtime configuration.",
        "",
        "> Never commit real provider credentials or private chat configuration to source control.",
        "",
        "## Project structure",
        "",
        "```text",
        *tree_lines,
        "```",
        "",
        "## Testing and security",
        "",
        "- `npm run test` executes the generated Vitest suite.",
        "- `npm run test:coverage` enforces 80% thresholds across statements, branches, functions, and lines.",
        "- `npm run test:e2e` runs Playwright against desktop and mobile projects.",
        "- `npm run audit` checks for high-severity dependency issues.",
        "- Companion skill scripts can generate markdown dependency and security reports when needed.",
        "",
    ]
    if config["deploy_target"] in {"cloudfront", "both"}:
        sections.extend([cloudfront_block(), ""])
    if config["deploy_target"] in {"docker", "both"}:
        sections.extend([docker_block(config["port"]), ""])
    return "\n".join(sections).rstrip() + "\n"


def build_favicon(config: Dict[str, Any]) -> str:
    letter = (config["logo_text"] or config["brand_name"][:1]).strip()[:1].upper() or "W"
    return textwrap.dedent(
        f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="{config['brand_name']} favicon">
  <defs>
    <linearGradient id="brandGradient" x1="0%" x2="100%" y1="0%" y2="100%">
      <stop offset="0%" stop-color="{config['brand_color']}" />
      <stop offset="100%" stop-color="{config['accent_color']}" />
    </linearGradient>
  </defs>
  <rect width="128" height="128" rx="28" fill="url(#brandGradient)" />
  <circle cx="96" cy="34" r="12" fill="rgba(255,255,255,0.35)" />
  <text x="64" y="78" text-anchor="middle" font-size="56" font-family="Inter, Arial, sans-serif" font-weight="700" fill="{accessible_text(config['brand_color'])}">{letter}</text>
</svg>
"""
    )


def build_main_jsx() -> str:
    return textwrap.dedent(
        """import React, { StrictMode } from 'react';
import ReactDOM from 'react-dom/client';
import App from './App.jsx';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
"""
    )






def build_app_jsx(config: Dict[str, Any], logo_asset: str | None) -> str:
    imports = [
        "import './App.css';",
        "import { Header } from './components/Header.jsx';",
        "import { Hero } from './components/Hero.jsx';",
        "import { Footer } from './components/Footer.jsx';",
    ]
    if config["chat"]["enabled"]:
        imports.append("import ChatWidget from './components/ChatWidget.jsx';")
    if config["include_features"]:
        imports.append("import { FeatureGrid } from './components/FeatureGrid.jsx';")
    if config["include_products"]:
        imports.append("import { ProductGrid } from './components/ProductGrid.jsx';")

    nav_items = [{"label": item, "href": f"#{slugify(item)}"} for item in config["nav_items"]]
    hero_stats = [
        {"value": "24/7", "label": "Always-on support"},
        {"value": "WCAG", "label": "Accessible patterns"},
        {"value": "Vite", "label": "Fast delivery"},
    ]
    primary_href = "#features" if config["include_features"] else ("#products" if config["include_products"] else "#support")
    secondary_href = "#support"
    lines = [
        *imports,
        "",
        f"const navItems = {js(nav_items)};",
        f"const featureItems = {js(config['feature_items'])};",
        f"const productItems = {js(config['product_items'])};",
        f"const promoCards = {js(config['promo_cards'])};",
        f"const heroStats = {js(hero_stats)};",
    ]
    if config["chat"]["enabled"]:
        lines.append(f"const chatConfig = {js(config['chat'])};")
    lines.extend(
        [
            "",
            "export default function App() {",
            "  return (",
            '    <div className="app">',
            f"      <Header brandName={js(config['brand_name'])} navItems={{navItems}} primaryCtaLabel={js(config['primary_cta_label'])} secondaryCtaLabel={js(config['secondary_cta_label'])} primaryHref={js(primary_href)} secondaryHref={js(secondary_href)} logoMode={js('image' if logo_asset else 'text')} logoText={js(config['logo_text'])} logoSrc={js('/' + logo_asset if logo_asset else '')} />",
            '      <main className="main" id="main-content">',
            f"        <Hero headline={js(config['hero_headline'])} subtitle={js(config['hero_subtitle'])} primaryCtaLabel={js(config['primary_cta_label'])} secondaryCtaLabel={js(config['secondary_cta_label'])} primaryHref={js(primary_href)} secondaryHref={js(secondary_href)} brandName={js(config['brand_name'])} vertical={js(config['vertical'])} stats={{heroStats}} />",
        ]
    )
    if config["include_features"]:
        lines.append('        <FeatureGrid items={featureItems} sectionId="features" heading="Why teams choose this experience" />')
    if config["include_products"]:
        lines.append('        <ProductGrid items={productItems} sectionId="products" heading="Explore products and services" />')
    lines.extend(
        [
            '        <section className="promo-section section" id="support">',
            '          <div className="section-shell">',
            '            <div className="section__header">',
            '              <h2>Operationally ready from the first commit</h2>',
            '              <p>Use the generated docs, test suite, Docker assets, and security checks to move from scaffold to production without reworking the foundation.</p>',
            '            </div>',
            '            <div className="promo-grid">',
            '              {promoCards.map((card) => (',
            '                <article key={card.title} className={`promo-card promo-card--${card.tone}`}>',
            '                  <p className="promo-eyebrow">{card.eyebrow}</p>',
            '                  <h3>{card.title}</h3>',
            '                  <p>{card.body}</p>',
            '                </article>',
            '              ))}',
            '            </div>',
            '          </div>',
            '        </section>',
            f"        <Footer brandName={js(config['brand_name'])} footerText={js(config['footer_text'])} copyrightEntity={js(config['copyright_entity'])} navItems={{navItems}} />",
            '      </main>',
        ]
    )
    if config["chat"]["enabled"]:
        lines.append('      <ChatWidget enabled={chatConfig.enabled} provider={chatConfig.provider} config={chatConfig.provider_config} />')
    lines.extend(
        [
            '    </div>',
            '  );',
            '}',
        ]
    )
    return "\n".join(lines) + "\n"


def build_app_css() -> str:
    return textwrap.dedent(
        """html,
body {
  overflow-x: hidden;
  max-width: 100vw;
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.main {
  flex: 1;
}

.section-shell {
  width: min(1120px, calc(100% - 1.5rem));
  margin: 0 auto;
}

.skip-link {
  position: absolute;
  left: -9999px;
  top: 0.75rem;
  z-index: 300;
  background: var(--brand);
  color: var(--on-brand);
  padding: 0.75rem 1rem;
  border-radius: 999px;
}

.skip-link:focus {
  left: 0.75rem;
}

.site-header {
  position: sticky;
  top: 0;
  z-index: 200;
  backdrop-filter: blur(16px);
  background: rgb(255 255 255 / 0.92);
  border-bottom: 1px solid var(--border);
}

.site-header__inner {
  width: min(1120px, calc(100% - 1.5rem));
  margin: 0 auto;
  min-height: 4.5rem;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 1rem;
  align-items: center;
  padding: 0.75rem 0;
}

.site-logo {
  display: inline-flex;
  align-items: center;
  gap: 0.85rem;
  font-weight: 700;
  color: var(--text);
  text-decoration: none;
}

.site-logo__mark {
  width: 2.75rem;
  height: 2.75rem;
  border-radius: 1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--brand), var(--accent));
  color: var(--on-brand);
  box-shadow: 0 12px 28px rgb(var(--brand-rgb) / 0.24);
  font-size: 1rem;
  font-weight: 800;
}

.site-logo__image {
  width: auto;
  max-height: 2.75rem;
}

.site-logo__text {
  font-size: 1rem;
  letter-spacing: -0.02em;
}

.menu-toggle,
.button-link,
.site-nav a,
.footer-nav a,
.product-card__link {
  min-height: 44px;
  min-width: 44px;
}

.menu-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: end;
  gap: 0.5rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  padding: 0.75rem 1rem;
  font-weight: 700;
}

.site-header__panel {
  grid-column: 1 / -1;
  display: none;
  gap: 1rem;
  padding-bottom: 0.75rem;
}

.site-header__panel.is-open {
  display: grid;
}

.site-nav,
.footer-nav {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.site-nav a,
.footer-nav a,
.product-card__link {
  display: inline-flex;
  align-items: center;
  color: var(--text-muted);
  text-decoration: none;
  font-weight: 600;
}

.site-nav a:hover,
.site-nav a:focus-visible,
.footer-nav a:hover,
.footer-nav a:focus-visible,
.product-card__link:hover,
.product-card__link:focus-visible {
  color: var(--brand);
}

.header-cta {
  display: grid;
  gap: 0.75rem;
}

.button-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.75rem 1.25rem;
  border-radius: 999px;
  font-weight: 700;
  text-decoration: none;
  border: 1px solid transparent;
  transition: transform 0.15s ease, box-shadow 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.button-link:hover,
.button-link:focus-visible {
  transform: translateY(-1px);
  box-shadow: 0 10px 20px rgb(var(--brand-rgb) / 0.18);
}

.button-link--primary {
  background: var(--brand);
  color: var(--on-brand);
}

.button-link--secondary {
  background: var(--surface);
  color: var(--brand);
  border-color: var(--border-strong);
}

.hero {
  padding: 3.5rem 0 2.5rem;
}

.hero__inner {
  width: min(1120px, calc(100% - 1.5rem));
  margin: 0 auto;
  display: grid;
  gap: 1.5rem;
  align-items: center;
}

.hero__copy {
  max-width: 42rem;
}

.hero__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.45rem 0.85rem;
  border-radius: 999px;
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 0.9rem;
  font-weight: 700;
}

.hero h1 {
  margin: 1rem 0 0;
  font-size: clamp(2.5rem, 11vw, 4.5rem);
  line-height: 1.02;
  letter-spacing: -0.04em;
  color: var(--text);
}

.hero__subtitle {
  margin-top: 1rem;
  color: var(--text-muted);
  font-size: 1.05rem;
  line-height: 1.7;
}

.hero__actions {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

.hero__stats {
  margin-top: 1.5rem;
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.85rem;
}

.hero__stat,
.feature-card,
.product-card,
.promo-card {
  padding: 1.25rem;
  border-radius: 1.25rem;
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: 0 18px 40px rgb(var(--brand-rgb) / 0.08);
}

.hero__stat-value {
  display: block;
  font-size: 1.25rem;
  font-weight: 800;
  color: var(--brand);
}

.hero__stat-label,
.feature-card p,
.product-card p,
.promo-card p,
.footer-meta {
  color: var(--text-muted);
  line-height: 1.65;
}

.hero__visual {
  min-height: 22rem;
}

.hero-card {
  position: relative;
  min-height: 100%;
  padding: 1.75rem;
  border-radius: 1.5rem;
  overflow: hidden;
  background: linear-gradient(135deg, var(--brand), var(--brand-strong));
  color: var(--on-brand);
  box-shadow: 0 28px 70px rgb(var(--brand-rgb) / 0.28);
}

.hero-card__badge {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.4rem 0.8rem;
  border-radius: 999px;
  background: rgb(255 255 255 / 0.14);
  font-size: 0.85rem;
  font-weight: 700;
}

.hero-card__title {
  margin-top: 1rem;
  font-size: clamp(1.5rem, 5vw, 2.2rem);
  line-height: 1.1;
}

.hero-card__body {
  margin-top: 0.85rem;
  max-width: 22rem;
  color: rgb(255 255 255 / 0.86);
  line-height: 1.6;
}

.hero-card__panel {
  margin-top: 2rem;
  display: grid;
  gap: 0.75rem;
  padding: 1rem 1.1rem;
  border-radius: 1rem;
  background: rgb(255 255 255 / 0.12);
  backdrop-filter: blur(10px);
}

.hero-card__panel span {
  display: block;
  color: rgb(255 255 255 / 0.82);
  font-size: 0.92rem;
}

.hero-card__spark {
  position: absolute;
  right: -1rem;
  top: 1rem;
  width: 10rem;
  height: 10rem;
  opacity: 0.3;
}

.section {
  padding: 1rem 0 1.5rem;
}

.section__header {
  margin-bottom: 1.25rem;
}

.section__header h2,
.promo-card h3 {
  margin: 0;
  font-size: clamp(1.6rem, 4vw, 2.25rem);
  letter-spacing: -0.03em;
  color: var(--text);
}

.section__header p {
  margin: 0.75rem 0 0;
  color: var(--text-muted);
  line-height: 1.7;
}

.card-grid,
.promo-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1rem;
}

.feature-card__icon {
  width: 3rem;
  height: 3rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 0.95rem;
  background: var(--accent-soft);
  font-size: 1.4rem;
}

.feature-card h3,
.product-card h3 {
  margin: 1rem 0 0;
  color: var(--text);
  font-size: 1.15rem;
}

.product-card__link {
  margin-top: 1rem;
  gap: 0.45rem;
  color: var(--brand);
  font-weight: 700;
}

.promo-card--brand {
  background: linear-gradient(145deg, var(--surface), var(--brand-soft));
}

.promo-card--accent {
  background: linear-gradient(145deg, var(--surface), var(--accent-soft));
}

.promo-eyebrow {
  color: var(--brand);
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.8rem;
}

.site-footer {
  border-top: 1px solid var(--border);
  background: var(--surface);
  margin-top: 1rem;
}

.site-footer__inner {
  width: min(1120px, calc(100% - 1.5rem));
  margin: 0 auto;
  display: grid;
  gap: 1rem;
  padding: 1.5rem 0 2rem;
}

:focus-visible {
  outline: 3px solid var(--accent);
  outline-offset: 3px;
}

/* ── Mobile-first responsive breakpoints ──────────────────────────────────── */
/* Base styles target mobile (≤639px) */
/* 640px+: small tablets / large phones */
@media (min-width: 640px) {
  .section-shell,
  .site-header__inner,
  .hero__inner,
  .site-footer__inner {
    width: min(1120px, calc(100% - 2rem));
  }

  .hero__actions {
    flex-direction: row;
    flex-wrap: wrap;
  }

  .hero__stats,
  .card-grid,
  .promo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* 768px+: tablets */
@media (min-width: 768px) {
  .site-header__inner {
    grid-template-columns: auto 1fr auto;
  }

  .menu-toggle {
    display: none;
  }

  .site-header__panel,
  .site-header__panel.is-open {
    grid-column: auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 0;
  }

  .site-nav,
  .footer-nav,
  .header-cta {
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;
  }

  .hero__inner {
    grid-template-columns: minmax(0, 1.05fr) minmax(18rem, 0.95fr);
  }

  .site-footer__inner {
    grid-template-columns: auto 1fr auto;
    align-items: start;
  }
}

/* 1024px+: desktops */
@media (min-width: 1024px) {
  .hero {
    padding: 4.5rem 0 3.5rem;
  }

  .card-grid--features {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .card-grid--products {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .promo-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* 1280px+: large desktops */
@media (min-width: 1280px) {
  .hero__inner,
  .section-shell,
  .site-header__inner,
  .site-footer__inner {
    width: min(1200px, calc(100% - 3rem));
  }

  .hero-card {
    padding: 2rem;
  }
}
"""
    ).strip() + "\n"


def build_index_css(config: Dict[str, Any]) -> str:
    brand = config["brand_color"]
    accent = config["accent_color"]
    background = config["background_color"]
    brand_strong = blend(brand, "#000000", 0.2)
    brand_soft = blend(brand, "#FFFFFF", 0.82)
    accent_soft = blend(accent, "#FFFFFF", 0.84)
    border = blend(brand, "#FFFFFF", 0.82)
    border_strong = blend(brand, "#FFFFFF", 0.7)
    surface = "#FFFFFF"
    surface_muted = blend(background, "#FFFFFF", 0.35)
    text = blend(brand, "#111827", 0.78)
    text_muted = blend(text, "#FFFFFF", 0.42)
    on_brand = accessible_text(brand)
    on_accent = accessible_text(accent)
    return textwrap.dedent(
        f"""*, *::before, *::after {{
  box-sizing: border-box;
}}

:root {{
  --brand: {brand};
  --brand-strong: {brand_strong};
  --brand-soft: {brand_soft};
  --brand-rgb: {rgb_string(brand)};
  --accent: {accent};
  --accent-soft: {accent_soft};
  --accent-rgb: {rgb_string(accent)};
  --bg: {background};
  --surface: {surface};
  --surface-muted: {surface_muted};
  --border: {border};
  --border-strong: {border_strong};
  --text: {text};
  --text-muted: {text_muted};
  --on-brand: {on_brand};
  --on-accent: {on_accent};
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  line-height: 1.5;
  font-weight: 400;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

html {{
  scroll-behavior: smooth;
  overflow-x: hidden;
  max-width: 100vw;
}}

body {{
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-size: 16px;
  line-height: 1.5;
  overflow-x: hidden;
  max-width: 100vw;
}}

body,
button,
input,
textarea,
select {{
  font: inherit;
}}

img {{
  max-width: 100%;
  height: auto;
  display: block;
}}

a {{
  color: inherit;
}}

button,
a,
[role='button'] {{
  min-height: 44px;
  min-width: 44px;
}}

/* ── Mobile-first responsive breakpoints ──────────────────────────────────── */
/* Base styles target mobile (≤639px) */
/* 640px+: small tablets / large phones */
@media (min-width: 640px) {{
  body {{
    font-size: 16px;
  }}
}}

/* 768px+: tablets */
@media (min-width: 768px) {{
  body {{
    font-size: 16px;
  }}
}}

/* 1024px+: desktops */
@media (min-width: 1024px) {{
  body {{
    font-size: 16px;
  }}
}}

/* 1280px+: large desktops */
@media (min-width: 1280px) {{
  body {{
    font-size: 16px;
  }}
}}
"""
    ).strip() + "\n"


def build_header_component() -> str:
    return textwrap.dedent(
        """import { useEffect, useState } from 'react';

export function Header({ brandName, navItems, primaryCtaLabel, secondaryCtaLabel, primaryHref, secondaryHref, logoMode, logoText, logoSrc }) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth >= 768) {
        setMenuOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const closeMenu = () => setMenuOpen(false);

  return (
    <>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="site-header" role="banner">
        <div className="site-header__inner">
          <a className="site-logo" href="#top" aria-label={`${brandName} home`} onClick={closeMenu}>
            {logoMode === 'image' && logoSrc ? (
              <img className="site-logo__image" src={logoSrc} alt={`${brandName} logo`} />
            ) : (
              <span className="site-logo__mark" aria-hidden="true">{logoText}</span>
            )}
            <span className="site-logo__text">{brandName}</span>
          </a>
          <button
            type="button"
            className="menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="primary-nav"
            aria-label="Toggle navigation"
            onClick={() => setMenuOpen((value) => !value)}
          >
            Menu
          </button>
          <div className={`site-header__panel ${menuOpen ? 'is-open' : ''}`}>
            <nav className="site-nav" id="primary-nav" aria-label="Primary navigation">
              {navItems.map((item) => (
                <a key={item.label} href={item.href} onClick={closeMenu}>{item.label}</a>
              ))}
            </nav>
            <div className="header-cta">
              <a className="button-link button-link--secondary" href={secondaryHref} onClick={closeMenu}>{secondaryCtaLabel}</a>
              <a className="button-link button-link--primary" href={primaryHref} onClick={closeMenu}>{primaryCtaLabel}</a>
            </div>
          </div>
        </div>
      </header>
    </>
  );
}
"""
    ).strip() + "\n"


def build_hero_component() -> str:
    return textwrap.dedent(
        """export function Hero({ headline, subtitle, primaryCtaLabel, secondaryCtaLabel, primaryHref, secondaryHref, brandName, vertical, stats }) {
  return (
    <section className="hero" id="top">
      <div className="hero__inner">
        <div className="hero__copy">
          <span className="hero__eyebrow">{brandName} · {vertical}</span>
          <h1>{headline}</h1>
          <p className="hero__subtitle">{subtitle}</p>
          <nav className="hero__actions" aria-label="Hero actions">
            <a className="button-link button-link--primary" href={primaryHref}>{primaryCtaLabel}</a>
            <a className="button-link button-link--secondary" href={secondaryHref}>{secondaryCtaLabel}</a>
          </nav>
          <div className="hero__stats">
            {stats.map((stat) => (
              <div className="hero__stat" key={stat.label}>
                <span className="hero__stat-value">{stat.value}</span>
                <span className="hero__stat-label">{stat.label}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="hero__visual" aria-hidden="true">
          <div className="hero-card">
            <span className="hero-card__badge">Production-ready scaffold</span>
            <h2 className="hero-card__title">Trusted brand shell with optional chat widget support</h2>
            <p className="hero-card__body">
              Clean component boundaries, responsive layout, and env-driven chat configuration give teams a strong first delivery baseline.
            </p>
            <svg className="hero-card__spark" viewBox="0 0 160 160" aria-hidden="true">
              <circle cx="80" cy="80" r="62" fill="none" stroke="currentColor" strokeWidth="10" opacity="0.24" />
              <path d="M24 96C42 60 70 36 132 30" fill="none" stroke="currentColor" strokeWidth="10" strokeLinecap="round" />
              <circle cx="118" cy="40" r="10" fill="currentColor" />
            </svg>
            <div className="hero-card__panel">
              <div>
                <strong>Secure defaults</strong>
                <span>CSP, env examples, Docker assets, and deployment guidance included.</span>
              </div>
              <strong>React 18 + Vite</strong>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
"""
    ).strip() + "\n"


def build_feature_component() -> str:
    return textwrap.dedent(
        """export function FeatureGrid({ items, sectionId, heading }) {
  return (
    <section className="section" id={sectionId}>
      <div className="section-shell">
        <div className="section__header">
          <h2>{heading}</h2>
          <p>Use branded cards to explain the strongest reasons to engage with the experience.</p>
        </div>
        <div className="card-grid card-grid--features">
          {items.map((item) => (
            <article className="feature-card" key={item.title}>
              <span className="feature-card__icon" aria-hidden="true">{item.icon}</span>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
"""
    ).strip() + "\n"


def build_product_component() -> str:
    return textwrap.dedent(
        """export function ProductGrid({ items, sectionId, heading }) {
  return (
    <section className="section" id={sectionId}>
      <div className="section-shell">
        <div className="section__header">
          <h2>{heading}</h2>
          <p>Adapt this grid for product categories, service lines, or outcome-led journeys.</p>
        </div>
        <div className="card-grid card-grid--products">
          {items.map((item) => (
            <article className="product-card" key={item.title}>
              <h3>{item.title}</h3>
              <p>{item.description}</p>
              <a className="product-card__link" href={item.href}>Explore <span aria-hidden="true">→</span></a>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
"""
    ).strip() + "\n"


def build_footer_component() -> str:
    return textwrap.dedent(
        """export function Footer({ brandName, footerText, copyrightEntity, navItems }) {
  return (
    <footer className="site-footer" role="contentinfo">
      <div className="site-footer__inner">
        <strong>{brandName}</strong>
        <nav className="footer-nav" aria-label="Footer navigation">
          {navItems.map((item) => (
            <a key={item.label} href={item.href}>{item.label}</a>
          ))}
        </nav>
        <div className="footer-meta">
          <p>{footerText}</p>
          <p>© 2026 {copyrightEntity}. Hosted with secure delivery guidance for CloudFront, Docker, and mobile-first responsive testing.</p>
        </div>
      </div>
    </footer>
  );
}
"""
    ).strip() + "\n"




def build_chat_component() -> str:
    return textwrap.dedent(
        """/**
 * ChatWidget — provider-agnostic chat integration
 * Provider: runtime-configured
 *
 * Supported providers: amazon-connect, intercom, zendesk, crisp, freshchat, custom
 * Config is read from window.__chatConfig (set in index.html).
 *
 * To add a new provider: add a case to initProvider() and loadScript().
 */
import { useEffect, useRef } from 'react';

function loadScript(src, id, integrity) {
  return new Promise((resolve, reject) => {
    if (document.getElementById(id)) { resolve(); return; }
    const s = document.createElement('script');
    s.src = src; s.id = id; s.async = true;
    if (integrity) { s.integrity = integrity; s.crossOrigin = 'anonymous'; }
    s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
}

function renameNodes(root, nameMap) {
  const selectors = [
    '[class*="participantName"]','[class*="participant-name"]',
    '[class*="senderName"]','[class*="sender-name"]','[data-testid="participant-name"]',
  ].join(',');
  root.querySelectorAll(selectors).forEach(el => {
    const t = el.textContent.trim();
    if (nameMap[t]) el.textContent = nameMap[t];
  });
}

export default function ChatWidget({ enabled, provider, config }) {
  const observerRef = useRef(null);

  useEffect(() => {
    if (!enabled || !provider || provider === 'none') return undefined;

    const cfg = config || window.__chatConfig?.config || {};

    async function initProvider() {
      switch (provider) {
        case 'amazon-connect': {
          const scriptUrl = cfg.script_url || '';
          if (!scriptUrl) { console.warn('[ChatWidget] amazon-connect: no script_url in config'); return; }
          await loadScript(scriptUrl, 'chat-widget-script', cfg.script_integrity || '');
          const nameMap = {};
          if (cfg.bot_display_name) nameMap.BOT = cfg.bot_display_name;
          if (cfg.agent_display_name) nameMap.SYSTEM = cfg.agent_display_name;
          if (typeof window.amazon_connect === 'function') {
            if (cfg.snippet_id) window.amazon_connect('snippetId', cfg.snippet_id);
            if (cfg.styles) window.amazon_connect('styles', cfg.styles);
            if (cfg.bot_display_name || cfg.agent_display_name) {
              window.amazon_connect('customDisplayNames', {
                transcript: {
                  botMessageDisplayName: cfg.bot_display_name || 'Assistant',
                  systemMessageDisplayName: cfg.agent_display_name || '',
                },
              });
            }
          }
          if (Object.keys(nameMap).length) {
            observerRef.current = new MutationObserver(() => renameNodes(document.body, nameMap));
            observerRef.current.observe(document.body, { subtree: true, childList: true });
          }
          break;
        }
        case 'intercom': {
          const appId = cfg.app_id || '';
          if (!appId) { console.warn('[ChatWidget] intercom: no app_id in config'); return; }
          window.intercomSettings = { app_id: appId, ...cfg.settings };
          await loadScript(`https://widget.intercom.io/widget/${appId}`, 'chat-widget-script');
          break;
        }
        case 'zendesk': {
          const key = cfg.key || '';
          if (!key) { console.warn('[ChatWidget] zendesk: no key in config'); return; }
          await loadScript(`https://static.zdassets.com/ekr/snippet.js?key=${key}`, 'ze-snippet');
          break;
        }
        case 'crisp': {
          const websiteId = cfg.website_id || '';
          if (!websiteId) { console.warn('[ChatWidget] crisp: no website_id in config'); return; }
          window.$crisp = []; window.CRISP_WEBSITE_ID = websiteId;
          await loadScript('https://client.crisp.chat/l.js', 'chat-widget-script');
          break;
        }
        case 'freshchat': {
          const token = cfg.token || '';
          if (!token) { console.warn('[ChatWidget] freshchat: no token in config'); return; }
          await loadScript('https://wchat.freshchat.com/js/widget.js', 'chat-widget-script');
          if (window.fcWidget) window.fcWidget.init({ token, host: cfg.host || 'https://wchat.freshchat.com' });
          break;
        }
        case 'custom': {
          const scriptUrl = cfg.script_url || '';
          if (!scriptUrl) { console.warn('[ChatWidget] custom: no script_url in config'); return; }
          await loadScript(scriptUrl, 'chat-widget-script', cfg.script_integrity || '');
          if (cfg.init_function && typeof window[cfg.init_function] === 'function') {
            window[cfg.init_function](cfg);
          }
          break;
        }
        default:
          console.warn(`[ChatWidget] Unknown provider: ${provider}`);
      }
    }

    initProvider().catch(err => console.error('[ChatWidget] init error:', err));

    return () => {
      if (observerRef.current) { observerRef.current.disconnect(); observerRef.current = null; }
    };
  }, [enabled, provider, config]);

  return null;
}
"""
    ).strip() + "\n"


def copy_logo(config: Dict[str, Any], output_dir: Path, dry_run: bool) -> str | None:
    raw_logo = config["logo"].strip()
    if raw_logo.lower() == "text":
        return None
    source = Path(raw_logo).expanduser()
    if not source.is_absolute():
        source = Path.cwd() / source
    if not source.exists() or not source.is_file():
        print(f"[WARN] Logo file not found, falling back to text logo: {source}", file=sys.stderr)
        return None
    target_name = f"logo{source.suffix.lower() or '.svg'}"
    if dry_run:
        return target_name
    destination = output_dir / "public" / target_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return target_name


def write_text(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[DRY-RUN] would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_package_lock(output_dir: Path) -> None:
    subprocess.run(
        ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-fund", "--no-audit"],
        cwd=output_dir,
        check=True,
        capture_output=True,
        text=True,
    )




def build_chat_providers_doc() -> str:
    return textwrap.dedent(
        """# Chat Widget Providers

This webapp supports the following chat providers. Configure via `webapp-config.json` `chat` section.

## amazon-connect
Requires: `script_url` (HTTPS URL to hosted widget JS), snippet ID (or env var `VITE_CHAT_CONFIG`)
See: https://docs.aws.amazon.com/connect/latest/adminguide/add-chat-to-website.html

## intercom
Requires: `app_id`
See: https://developers.intercom.com/installing-intercom/docs/basic-javascript

## zendesk
Requires: `key` (Web Widget key)
See: https://developer.zendesk.com/documentation/classic-web-widget-sdks/web-widget/getting-started/

## crisp
Requires: `website_id`
See: https://help.crisp.chat/en/article/how-to-add-crisp-chat-to-your-website-de9cpf/

## freshchat
Requires: `token`, optional `host`
See: https://developers.freshchat.com/web-sdk-reference/

## custom
Requires: `script_url`, optional `init_function`

## none
No chat widget. Default.
"""
    ).strip() + "\n"


def build_files(config: Dict[str, Any], output_dir: Path, logo_asset: str | None, output_name: str) -> Dict[Path, str]:
    replacements = {
        "PORT": str(config["port"]),
        "PROJECT_NAME": config["project_name"],
        "DATE": "TBD",
        "AUDITOR": "Platform Team",
        "VERSION": "1.0.0",
    }
    files: Dict[Path, str] = {
        output_dir / "index.html": build_index_html(config),
        output_dir / "package.json": build_package_json(config),
        output_dir / "vite.config.js": build_vite_config(config),
        output_dir / ".env.example": build_env_example(config),
        output_dir / ".npmrc": build_npmrc(),
        output_dir / ".gitignore": build_gitignore(),
        output_dir / "eslint.config.js": build_eslint_config(),
        output_dir / "README.md": build_readme(config, output_name, logo_asset),
        output_dir / "public" / "favicon.svg": build_favicon(config),
        output_dir / "src" / "main.jsx": build_main_jsx(),
        output_dir / "src" / "App.jsx": build_app_jsx(config, logo_asset),
        output_dir / "src" / "App.css": build_app_css(),
        output_dir / "src" / "index.css": build_index_css(config),
        output_dir / "src" / "components" / "Header.jsx": build_header_component(),
        output_dir / "src" / "components" / "Hero.jsx": build_hero_component(),
        output_dir / "src" / "components" / "Footer.jsx": build_footer_component(),
        output_dir / "Dockerfile.prod": render_template("Dockerfile.prod", replacements),
        output_dir / "Dockerfile.dev": render_template("Dockerfile.dev", replacements),
        output_dir / "docker-compose.yml": render_template("docker-compose.yml", replacements),
        output_dir / "nginx.conf": render_template("nginx.conf", replacements),
        output_dir / "SECURITY.md": render_template("docs/security-report-template.md", replacements),
        output_dir / "docs" / "test-plan.md": render_template("docs/test-plan-template.md", replacements),
        output_dir / "docs" / "mobile-checklist.md": render_template("docs/mobile-checklist.md", replacements),
        output_dir / "docs" / "chat-providers.md": build_chat_providers_doc(),
    }
    if config["chat"]["enabled"]:
        files[output_dir / "src" / "components" / "ChatWidget.jsx"] = build_chat_component()
    if config["include_features"]:
        files[output_dir / "src" / "components" / "FeatureGrid.jsx"] = build_feature_component()
    if config["include_products"]:
        files[output_dir / "src" / "components" / "ProductGrid.jsx"] = build_product_component()

    for relative_path, content in build_test_files(
        config["port"],
        config["project_name"],
        chat_enabled=config["chat"]["enabled"],
        chat_provider=config["chat"]["provider"],
    ).items():
        files[output_dir / relative_path] = content
    return files


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    output_dir = Path(args.output).expanduser().resolve() if args.output else (Path.cwd() / config["package_name"]).resolve()
    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    logo_asset = copy_logo(config, output_dir, args.dry_run)
    files = build_files(config, output_dir, logo_asset, output_dir.name)

    print(f"Scaffolding project: {config['project_name']}")
    print(f"Target directory: {output_dir}")
    if args.dry_run:
        print("Dry run enabled; no files will be written.")

    for path, content in files.items():
        write_text(path, content, args.dry_run)

    if args.dry_run and logo_asset:
        print(f"[DRY-RUN] would copy logo asset to {output_dir / 'public' / logo_asset}")

    if not args.dry_run:
        try:
            ensure_package_lock(output_dir)
        except subprocess.CalledProcessError as exc:
            print("[WARN] Failed to generate package-lock.json automatically.", file=sys.stderr)
            if exc.stderr:
                print(exc.stderr.strip(), file=sys.stderr)

    print(f"Planned files: {len(files) + (1 if logo_asset else 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
