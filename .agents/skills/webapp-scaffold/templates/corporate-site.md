# Corporate Site Template

## Purpose

Use this template for a services company, consultancy, B2B technology platform, or enterprise landing site with a clean nav, hero, services cards, about section, contact CTA, and optional chat support.

## Required config fields

- `project_name`
- `brand_name`
- `vertical=corporate`
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
- `--surface-muted`
- `--text`
- `--text-muted`

## Component list

- `Header`
- `Hero`
- `FeatureGrid`
- `ProductGrid` (optional services grid)
- `Footer`
- `ChatWidget` (optional)

## Template notes

- Reframe the product grid as services or capability cards.
- Include a trust/credibility strip in promo cards.
- Support optional chat for sales or support routing.

## Example config snippet

```json
{
  "project_name": "northstar-advisory",
  "brand_name": "Northstar Advisory",
  "vertical": "corporate",
  "brand_color": "#123E63",
  "accent_color": "#F26B3A",
  "background_color": "#F4F7FB",
  "include_features": true,
  "include_products": true,
  "chat": {
    "enabled": false,
    "provider": "none",
    "provider_config": {}
  }
}
```

## Jinja-style section sketch

```md
# {{BRAND_NAME}} Corporate Site

- Navigation: {{NAV_ITEMS}}
- Hero: {{HERO_HEADLINE}}
- Services cards: {{PRODUCT_ITEMS}}
- About / trust CTA: {{PROMO_COPY}}
- Chat enabled: {{CHAT_ENABLED}}
```
