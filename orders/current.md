# Jarvis v1 — complete M1 implementation from current baseline

Status: approved.
Master plan: MASTERPLAN-JARVIS.md

Implement Jarvis M1 completely from the current split-repository baseline. Do not depend on files from previous failed runs or external artifacts. Create every required Jarvis source/test file that is absent.

## Product goal

A private, mobile-first, read-only Agent Control Room for observing paper-kestrel runs in near real time.

## Canonical backend contract

Supabase tables:
- public.agent_runs
- public.agent_events

Browser access is authenticated and RLS-authorized. Realtime is supplemental; initial REST reads must work independently.

## Authentication — mandatory

The hosted Supabase project's email template sends a numeric OTP.

Implement:
1. email entry;
2. supabase.auth.signInWithOtp({ email, options: { shouldCreateUser: false } });
3. explicit numeric code entry;
4. supabase.auth.verifyOtp({ email, token, type: 'email' });
5. authenticated dashboard after a valid session.

Do not change Supabase email templates.
Do not create users automatically.
Do not use magic-link-only UX.
Do not make GitHub OAuth operational in M1.
Document that GitHub OAuth is deferred until it can be safely linked to the already-authorized identity.

## Required source files

Presentation repository:
- jarvis.html
- assets/jarvis.css
- js/app/jarvis/config.js
- js/app/jarvis/integration.js
- js/app/jarvis/ui.js
- js/app/jarvis/main.js

Test repository:
- tests/jarvis.cjs

Reuse the existing vendored Supabase browser SDK/config pattern where practical. Never embed a service-role or secret key.

## Current run UI

Show:
- GitHub run number + attempt;
- overall status;
- current phase;
- elapsed duration;
- total tokens including reasoning/cached where present;
- authoritative estimated USD cost;
- PR links;
- prominent `SERVE MATTEO` / `NON SERVE MATTEO`;
- interaction reason when present.

## Agent grid

Show the known agents and derive state only from data:
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

At minimum distinguish active vs idle. Do not invent activity.

## Live timeline

Show concise safe fields only:
- timestamp;
- agent;
- event type/status when useful;
- message;
- handoff_to.

Never render hidden reasoning, full prompts, raw metadata dumps, credentials or sensitive payloads.

## History

- list recent runs;
- allow selecting an older run;
- load its events;
- preserve run status/cost/completion visibility.

## Realtime resilience

Critical:
- initial authenticated REST reads of agent_runs/agent_events MUST run immediately after session bootstrap and MUST NOT wait for a SUBSCRIBED realtime callback;
- if Realtime never subscribes or returns CHANNEL_ERROR/TIMED_OUT/CLOSED, available REST data must still render;
- show realtime as disconnected/stale;
- retry must retry both REST data reads and the realtime channel;
- Realtime inserts should update the visible timeline without full-page reload when possible.

## Responsive/accessibility

- usable at 320px viewport width;
- no page-level horizontal overflow;
- interactive touch targets >=44px;
- explicit labels for email and OTP;
- autocomplete="email" and autocomplete="one-time-code";
- visible keyboard focus;
- aria-live/status for loading/errors/connection changes;
- long IDs/messages/links wrap;
- respects reduced motion;
- iOS Safari compatible.

## Deterministic tests

tests/jarvis.cjs must verify all of the following without false positives:

1. Security
- no service-role/secret key in browser files;
- no mutation/write methods to telemetry tables;
- safe display-field allowlist or equivalent rendering contract.

2. OTP
- signInWithOtp uses shouldCreateUser:false;
- verifyOtp uses email + token + type:'email';
- invalid/expired OTP produces a safe user-facing error.

3. Data/realtime
- canonical agent_runs and agent_events are used;
- initial REST reads happen without waiting for SUBSCRIBED;
- REST data still renders if channel never subscribes;
- CHANNEL_ERROR/TIMED_OUT/CLOSED produces stale/disconnected state but does not erase available data;
- retry retries REST + realtime;
- realtime event insert updates data path.

4. UI
- SERVE MATTEO and NON SERVE MATTEO states exist;
- current run, agent grid, timeline, history, cost/tokens and PR links exist;
- loading/empty/error states exist.

5. Responsive contract
- viewport meta exists;
- no obvious fixed/min-width desktop-only page/container rule that causes overflow at 320px;
- IMPORTANT: the test must NOT reject legitimate max-width declarations or @media(max-width:...) breakpoints merely because they contain pixel values;
- include positive and negative CSS fixtures proving this distinction.

6. Boundaries
- no production/deploy workflow modifications.

## Verification

Run:
- node tests/jarvis.cjs;
- full_test through controller baseline policy;
- account_focus;
- diff_check.

The reviewer must inspect the actual responsive-test evidence and the actual OTP/realtime deterministic tests before approval.

## Delivery

- PR only.
- No merge.
- No production deploy.
- No DNS changes.
- No Supabase schema/config/email-template changes.
- No secret changes.

## Orchestration observability

Jarvis should expose the new company-style orchestration signals when present in agent_events metadata:

- planned vs actual USD spend per agent/task;
- run budget and actual total;
- concise team handoffs;
- reviewer disposition: approve / approve_with_suggestions / block;
- reviewer non-blocking suggestions;
- stop reason;
- whether owner interaction is genuinely required.

These are display-only. Do not derive hidden reasoning or expose raw metadata dumps.

