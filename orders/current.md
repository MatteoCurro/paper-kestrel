# Jarvis v1 — M1 Source-controlled control room

Status: approved.
Master plan: MASTERPLAN-JARVIS.md

## Objective

Build the first maintainable, source-controlled Jarvis dashboard for U.Venice Transport.

This is a monitoring-only milestone. Do not deploy it and do not change production DNS, deployment credentials or Supabase secrets.

## Existing backend contract

The dashboard reads from the existing Supabase project using browser-safe credentials and RLS.

Canonical tables:
- public.agent_runs
- public.agent_events

Important run fields include:
- github_run_id
- run_attempt
- status
- phase
- summary
- needs_interaction
- interaction_reason
- active_agents
- input_tokens
- output_tokens
- cached_tokens
- reasoning_tokens
- estimated_cost_usd
- pr_urls
- started_at
- completed_at
- last_event_at

Important event fields include:
- occurred_at
- agent
- event_type
- status
- message
- handoff_to
- model
- input_tokens
- output_tokens
- cached_tokens
- reasoning_tokens
- estimated_cost_usd
- metadata

Realtime is already enabled and RLS is authoritative.

## Required source changes

Presentation surface:
- create root-level `jarvis.html`;
- create maintainable modules under `js/app/jarvis/`;
- reuse existing project Supabase/auth configuration where practical instead of duplicating secrets/configuration;
- browser code may use only the public/publishable Supabase key, never a secret/service-role key.

Tests:
- add focused deterministic contract tests under `tests/`.

Do not modify the main transport interface unless a tiny shared-auth extraction is clearly safer than duplication.

## UX requirements

Mobile-first, dark control-room style consistent with the project but visually distinct from the passenger interface.

At minimum show:

1. Header
   - JARVIS / Agent Control Room
   - realtime connection state
   - authenticated user state / logout

2. Current run
   - GitHub run number and attempt
   - overall status
   - current phase
   - elapsed duration when timestamps exist
   - total tokens
   - estimated USD cost
   - PR link(s) when available

3. Owner interaction
   - very prominent state:
     - `NON SERVE MATTEO`
     - `SERVE MATTEO`
   - show interaction_reason when present

4. Agent grid
   - Delivery Director
   - Solution Architect
   - Senior Frontend Engineer
   - Frontend Quality and Accessibility Engineer
   - Senior Backend and Integration Engineer
   - Senior Data and Transit Platform Engineer
   - Product Manager and Growth Strategist
   - Senior UI/UX and Visual Design Reviewer
   - QA, Security and Release Reviewer
   - Controller
   - visually distinguish active vs idle;
   - derive state safely from run/event data; do not invent activity.

5. Live feed
   - concise event timeline;
   - timestamp;
   - agent;
   - message;
   - handoff target when present;
   - newest events visible immediately;
   - no hidden chain-of-thought, full prompts or sensitive payload dumps.

6. History
   - recent runs;
   - select a prior run and inspect its timeline;
   - status, phase, cost and completion state.

## Authentication

Primary CTA: `Continua con GitHub` using Supabase Auth OAuth.

Important:
- Supabase dashboard GitHub authentication and project Auth are separate systems.
- If GitHub OAuth is not configured or the resulting account is not authorized by RLS, show a clear safe error state. Do not bypass RLS.
- Retain a compact fallback compatible with the project's existing auth implementation; do not invent a second user database.
- Never auto-grant admin access from browser state.

## Realtime / resilience

- subscribe to Postgres changes for the two canonical tables;
- refresh the selected run when it changes;
- insert events into the timeline without a full page reload where practical;
- reconnect cleanly;
- show useful loading, empty and disconnected states;
- application remains read-only.

## Cost presentation

- show total estimated cost from the authoritative run aggregate;
- when event-level cost data exists, compute a display-only per-agent rollup;
- label costs as estimates;
- do not recalculate model pricing in the browser if the backend already provides cost.

## Accessibility / mobile

- usable at 320px width;
- no horizontal scrolling;
- touch targets >= 44px where interactive;
- semantic buttons/forms;
- visible focus states;
- reasonable contrast;
- respects reduced motion;
- iOS Safari compatible.

## Tests

Add deterministic tests that verify at least:
- no secret/service-role key is embedded in Jarvis browser files;
- canonical tables are referenced;
- GitHub OAuth CTA exists;
- `SERVE MATTEO` / `NON SERVE MATTEO` states exist;
- realtime subscription exists;
- PR link rendering exists;
- page is responsive by contract (viewport meta and no obvious fixed desktop-only width);
- no production/deploy workflow is modified.

Run:
- focused Jarvis test;
- existing full suite through the controller baseline policy;
- git diff --check.

## Delivery boundaries

- PR only.
- No merge.
- No production deploy.
- No DNS changes.
- No Supabase schema migration in this work item.
- Keep the diff narrowly scoped to Jarvis.
