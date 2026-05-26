# E-commerce Site Template

## Purpose

Use this template for retail and commerce frontends with hero banner, category grid, featured value cards, fast CTA buttons, and optional support chat.

## Required config fields

- `project_name`
- `brand_name`
- `vertical=ecommerce`
- `brand_color`
- `accent_color`
- `background_color`
- `nav_items`
- `hero_headline`
- `hero_subtitle`
- `primary_cta_label`
- `secondary_cta_label`
- `include_features`
- `include_products`

## CSS variable requirements

- `--brand`
- `--accent`
- `--bg`
- `--surface`
- `--on-accent`
- `--text`
- `--border`

## Component list

- `Header`
- `Hero`
- `FeatureGrid`
- `ProductGrid`
- `Footer`
- `ChatWidget` (optional)

## Template notes

- Products grid should map to categories or featured collections.
- Promo cards should emphasise delivery, returns, and support benefits.
- Chat widget is typically used for order help and live support.

## Example config snippet

```json
{
  "project_name": "aurora-shop",
  "brand_name": "Aurora Shop",
  "vertical": "ecommerce",
  "brand_color": "#1E3A5F",
  "accent_color": "#FF6A3D",
  "background_color": "#FFF9F3",
  "include_features": true,
  "include_products": true,
  "chat": {
    "enabled": true,
    "provider": "intercom",
    "provider_config": {
      "app_id": ""
    },
    "bot_display_name": "Shop Support",
    "agent_display_name": "Aurora Shop"
  }
}
```

## Jinja-style section sketch

```md
# {{BRAND_NAME}} Storefront

- Hero banner: {{HERO_HEADLINE}}
- Feature cards: {{FEATURE_ITEMS}}
- Categories: {{PRODUCT_ITEMS}}
- Support chat: {{CHAT_ENABLED}}
```
