# Jarvis / Agent Control Room — Master Plan

Status: active
Owner: U.Venice Transport
Execution model: incremental PR-only delivery through paper-kestrel. No automatic merge or production deploy.

## Goal

Provide a private, mobile-friendly control room for long-running CrewAI work so the owner can see, in near real time:

- which run is active and its current phase;
- which agents are active, idle, blocked or reviewing;
- short handoff/status messages between agents;
- validation/test progress;
- estimated token usage and cost, including per-agent attribution when available;
- whether owner interaction is required;
- final QA outcome and pull-request links;
- recent run history.

The UI must expose concise operational summaries only. Never expose hidden chain-of-thought or sensitive prompts.

## Canonical architecture

GitHub Actions / paper-kestrel
→ GitHub OIDC
→ Supabase Edge Function `jarvis-ingest`
→ Supabase Realtime
→ authenticated Jarvis web UI

No PHP polling and no dependency on Gandi cron capacity.

Canonical telemetry storage for the first production version:
- `public.agent_runs`
- `public.agent_events`

`jarvis_runs` / `jarvis_events` are legacy/prototype structures and must not gain new dependencies. Their cleanup is a later migration after the canonical UI has been validated.

## Security

- Browser reads use Supabase Auth + RLS only.
- No service-role/secret key in browser or repositories.
- Ingestion is authenticated by GitHub Actions OIDC and restricted to `MatteoCurro/paper-kestrel` on `main`.
- Jarvis must fail closed for unauthorized users.
- Telemetry publishing from the orchestrator is fail-open: an observability outage must never stop a coding run.
- GitHub dashboard authentication and project Supabase Auth are separate identities. The UI should support GitHub OAuth when the provider is configured, while retaining a safe fallback until the authorized identity is linked.
- No hidden reasoning traces are persisted.

## M0 — Pipeline foundation [DONE]

- CrewAI end-to-end smoke validated.
- Responses API compatibility fixed.
- baseline-equivalent test failures handled deterministically.
- PR-only delivery verified.
- automatic push trigger on `orders/current.md` verified.
- Supabase OIDC ingest verified.
- realtime run/event storage verified.
- token/cost telemetry verified.

## Auth decision — 2026-10-07

The hosted Supabase project's email auth template currently emits a numeric OTP through `{{ .Token }}`. Jarvis M1 must therefore use the existing passwordless **email → code → verifyOtp** flow, with `shouldCreateUser:false`, so it reuses the already-authorized account and does not alter U.Venice registration behavior.

GitHub OAuth is deferred until the GitHub provider is configured inside project Auth and can be safely linked to the existing authorized identity without creating a second account. Do not change the global email template solely for Jarvis.

## M1 — Source-controlled Jarvis UI [IN PROGRESS]

Create the first maintainable UI in the split repositories rather than keeping the dashboard only as an inline Edge Function string.

Required source surface:
- `jarvis.html` → presentation repo
- `js/app/jarvis/**` → presentation repo
- deterministic contract tests under `tests/**` → engine/test repo

Features:
- responsive dark control-room layout;
- GitHub OAuth primary CTA, with explicit unauthorized/error state;
- existing project-auth fallback without duplicating account systems;
- RLS-backed read of `agent_runs` and `agent_events`;
- realtime subscription;
- current run summary;
- phases;
- active agents;
- owner-interaction state;
- timeline;
- recent history;
- total token/cost estimate;
- PR links when available;
- robust empty/loading/error states.

No production deploy in this milestone.

## M2 — Operational clarity

- duration / elapsed timer;
- per-agent token and cost rollup;
- agent state machine: idle / working / reviewing / blocked / done;
- explicit `SERVE MATTEO` / `NON SERVE MATTEO` indicator;
- human-readable handoffs;
- current check/test display;
- repair-round counter;
- direct GitHub run / PR links;
- concise run summary suitable for resuming a ChatGPT conversation.

## M3 — Reliability and data hygiene

- deduplicate prototype telemetry tables after migration verification;
- retention policy for detailed events;
- keep aggregate run history longer than event detail;
- ensure Realtime publication only exposes RLS-safe tables;
- optimize RLS policies using init-plan-safe expressions;
- remove duplicate indexes;
- document recovery behavior when Supabase is unavailable;
- add contract tests for event idempotency and reruns.

## M4 — Notifications and owner handoff

- optional notification when `needs_interaction=true`;
- optional notification when run succeeds/fails;
- link directly to the relevant run;
- no noisy per-event notifications;
- notification preference stored separately from application marketing consent.

## M5 — Control actions (later)

Read-only remains the default. Only after the monitoring layer is stable evaluate:
- safe retry;
- cancel;
- approve next macro-step;
- acknowledge owner decision.

Any action must be separately authorized and audited. No merge/deploy control is part of Jarvis v1.

## Definition of done for Jarvis v1

Jarvis v1 is done when a real multi-agent run can be observed from a phone from start to finish, including agent activity, handoffs, tests, cost estimate, owner-interaction state and PR delivery, with no manual refresh and no access to private data by an unauthorized account.
