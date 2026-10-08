# Durable Decisions

Last curated: 2026-10-08

Only accepted durable decisions belong here.

## Architecture

- Phase 9.0 master plan is the architectural source of truth.
- Static vanilla-JS web architecture remains intentional; no framework rewrite is planned.
- Public map uses Leaflet; Driver Utility may use MapLibre/PMTiles.
- Frontend deploy and transit runtime-data generation remain separate lifecycles.
- Provider-specific transit data stays behind provider-neutral application contracts.
- Intelligence/learning layers are optional fail-open consumers, not sources of truth.
- Core languages are IT/EN/FR/DE.
- Mobile complex tasks are full-screen workspaces; selected map objects use context cards.

## Identity

- Core transport remains usable without login.
- Supabase account data is protected by RLS.
- Current email auth is numeric OTP.
- GitHub login to Supabase dashboard is not equivalent to GitHub OAuth in project Auth.
- Do not change shared Auth email templates for a single surface without checking registration/login impact.

## Agent system

- Fewer standing roles are preferred over mandatory specialist pipelines.
- Engineering Manager owns planning + economics.
- Senior Product Engineer is the default writer.
- Product & UX Critic gives product/design feedback, not only code/style checks.
- Independent Reviewer can approve with non-blocking suggestions.
- Specialists are invoked only when materially needed.
- Persistent common/domain project memory must be read before relevant work.
- Owner should be interrupted only for spend approval above standing limits.
- Standing autonomous limits accepted by owner: USD 0.75 per run and USD 1.50 per milestone.
- Paid failed runs must preserve candidate artifacts/draft PRs.
