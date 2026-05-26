# Mobile Responsiveness Checklist — {{PROJECT_NAME}}

## Viewport & Layout
- [ ] `<meta name="viewport" content="width=device-width, initial-scale=1.0">` present
- [ ] No horizontal scroll on any viewport ≥320px
- [ ] Content readable without zoom at 320px width
- [ ] All breakpoints implemented: 640, 768, 1024, 1280

## Touch & Interaction
- [ ] All touch targets ≥44×44px (WCAG 2.5.5)
- [ ] No hover-only interactions (provide tap equivalent)
- [ ] Swipe gestures don't conflict with browser navigation
- [ ] Form inputs use appropriate type (tel, email, number)

## Typography
- [ ] Base font ≥16px on mobile
- [ ] Line height ≥1.5 for body text
- [ ] No text smaller than 12px

## Images & Media
- [ ] All images have responsive sizing (max-width: 100%)
- [ ] srcset used for hero images
- [ ] No fixed-width images wider than viewport

## Navigation
- [ ] Hamburger/mobile menu on screens <768px
- [ ] Skip-to-content link for keyboard/screen reader users
- [ ] Back button works correctly (no history manipulation)

## Performance (Mobile)
- [ ] Lighthouse mobile score ≥90 Performance
- [ ] First Contentful Paint <2.5s on 4G
- [ ] Total Blocking Time <300ms

## Chat Widget
- [ ] Chat button not obscuring content on mobile
- [ ] Chat panel scrollable and not clipped on small screens
- [ ] Widget z-index not conflicting with modals/overlays
