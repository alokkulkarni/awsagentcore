# Generic Webapp Template

## Purpose

Use this minimal template for SaaS landing pages, internal portals, accelerators, or proof-of-value frontends where the layout should stay simple and reusable.

## Required config fields

- `project_name`
- `brand_name`
- `vertical=generic`
- `brand_color`
- `accent_color`
- `background_color`
- `nav_items`
- `hero_headline`
- `hero_subtitle`
- `primary_cta_label`
- `secondary_cta_label`
- `footer_text`

## CSS variable requirements

- `--brand`
- `--accent`
- `--bg`
- `--surface`
- `--text`
- `--text-muted`
- `--border`

## Component list

- `Header`
- `Hero`
- `FeatureGrid` (optional)
- `Footer`
- `ChatWidget` (optional)

## Template notes

- Keep copy neutral and reusable.
- Product/services grid is optional and may be omitted entirely.
- Chat can be disabled for documentation-only or static marketing pages.

## Example config snippet

```json
{
  "project_name": "my-webapp",
  "brand_name": "My App",
  "vertical": "generic",
  "brand_color": "#0D2A66",
  "accent_color": "#E63012",
  "background_color": "#f5f6fa",
  "include_features": true,
  "include_products": false,
  "chat": {
    "enabled": false,
    "provider": "none",
    "provider_config": {}
  }
}
```

## Jinja-style section sketch

```md
# {{PROJECT_NAME}}

- Navigation: {{NAV_ITEMS}}
- Hero: {{HERO_HEADLINE}}
- Features: {{FEATURE_ITEMS}}
- Footer: {{FOOTER_TEXT}}
```
