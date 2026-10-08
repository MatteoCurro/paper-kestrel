# Growth, SEO & Analytics Memory

Last curated: 2026-10-08
Primary reader: Growth/SEO Specialist, Product Engineer for acquisition/measurement work.

## Product relationship

Transport App is part of Unlock Venice and should support the wider editorial/accommodation funnel without compromising mobility usability.

## SEO

9.0 introduces dedicated localized transport landing layers rather than relying only on the single app page.

Canonical localized content includes place and route landing pages with hreflang/sitemap/internal linking support.

SEO/editorial infrastructure lives under `seo/`, related scripts and WordPress integration.

## WordPress

Transport functionality can be surfaced through reusable WordPress shortcode/widget integration.
Do not duplicate routing/provider logic inside WordPress; keep a clean U.Venice application boundary.

## Analytics/attribution

Analytics and attribution must not make account registration mandatory.
Consent requirements remain separate from core transport use.
Do not mix marketing consent with operational notification preferences.

## Growth principle

Commercial/remarketing features are optional layers around a trustworthy mobility product.
Avoid dark patterns that damage the transport experience.

## Source pointers

- `ARCHITECTURE-9.0-MASTER-PLAN.md`
- `seo/`
- `wordpress/`
- analytics modules under `js/analytics/`
