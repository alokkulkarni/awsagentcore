# Banking Site Template

## Purpose

Use this template for Meridian/Nationwide-style financial services sites with a sticky header, trusted hero panel, feature grid, product grid, promo cards, regulatory footer, and optional chat widget support.

## Required config fields

- `project_name`
- `brand_name`
- `vertical=banking`
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
- `footer_text`
- `chat.enabled`

## CSS variable requirements

- `--brand`
- `--accent`
- `--bg`
- `--on-brand`
- `--on-accent`
- `--surface`
- `--border`

## Component list

- `Header`
- `Hero`
- `FeatureGrid`
- `ProductGrid`
- `Footer`
- `ChatWidget` (optional)

## Template notes

- Hero visual should resemble a card or statement summary.
- Footer should include regulatory-ready space for authorised entity copy.
- Products grid should favour cards such as current accounts, mortgages, savings, and insurance.

## Example config snippet

```json
{
  "project_name": "meridian-webapp",
  "brand_name": "Meridian Bank",
  "vertical": "banking",
  "brand_color": "#0D2A66",
  "accent_color": "#E63012",
  "background_color": "#f5f6fa",
  "include_features": true,
  "include_products": true,
  "chat": {
    "enabled": true,
    "provider": "amazon-connect",
    "provider_config": {
      "script_url": "",
      "icon_type": "CHAT"
    },
    "bot_display_name": "Assistant",
    "agent_display_name": "Meridian Bank"
  }
}
```

## Jinja-style section sketch

```md
# {{BRAND_NAME}} Digital Banking

- Sticky nav: {{NAV_ITEMS}}
- Hero headline: {{HERO_HEADLINE}}
- Hero subtitle: {{HERO_SUBTITLE}}
- Feature items: {{FEATURE_ITEMS}}
- Product grid: {{PRODUCT_ITEMS}}
- Footer: {{FOOTER_TEXT}}
```
