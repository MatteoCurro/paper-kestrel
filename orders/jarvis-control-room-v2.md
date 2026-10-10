# Mission JARVIS-V2 — TSAND Control Room modernization
Owner: Unlock Venice / U.Venice Transport · Last reviewed 2026-10-10
Status: IMPLEMENTATION IN PUBLIC FEATURE BRANCH; no automatic production deploy.
Target frontend: MatteoCurro/u-venice-transport:feature/jarvis-tsand-20261010, URL https://www.unlockvenice.com/t-sand/jarvis.html
Target database: Supabase project xiiexzvuvzsiacbmwras ONLY
Other review source: MatteoCurro/quiet-spindle draft PR #2 (not merged)
Orchestrator: MatteoCurro/paper-kestrel:infra/transactional-v2 (draft PR #1)

## Confirmed baseline problems
- GitHub OAuth button leads to Supabase 400 'Unsupported provider: provider is not enabled'. No GitHub provider secrets are configured in TSAND. NEVER re-enable GitHub sign-in until app credentials exist and OAuth callback has been verified.
- Current Jarvis signInWithOtp() can send a code but UI only asks user to follow a magic link. It lacks verifyOtp({email,token,type:'email'}).
- Transport M10 login is **password-first**, email+password, while initial confirmation may use links. Reuse the same Supabase TSAND identity (not a separate user store). An admin must already be permitted by jarvis_admins RLS.
- Jarvis needs meaningful operational visibility, not just a passive feed. Existing counts double-counted cached/reasoning, corrected in PR #2.
- Supabase Edge HTML served as text/plain, so host static frontend exclusively at Unlock Venice /t-sand/jarvis.html.

## Nonnegotiable authority
- No writes to production servers, /trasporti, private source or main branch.
- No service_role secrets, service credentials, GitHub OAuth client secrets, user emails or tokens in public repository/logs.
- Only Gandi SFTP upload of jarvis.html to /lamp0/web/vhosts/unlockvenice.com/htdocs/t-sand; keep deploy-preview single-file.
- Only read operations from agent_runs/agent_events/approved admin membership in browser; no delete/change/re-run agent actions without new explicit user approval.
- No LLM run without expense approval. Crew budget authority remains disabled except a separately authorized one-shot canary. Never remove guardrails just to run tests.
- Roles must challenge design choices; independent security/UX reviews; each decision evidenced and bounded, shared memory updated with checks.

## Iteration A (P0, testable, owner-visible)
- Email OTP form: request with shouldCreateUser:false, show six-digit code input with numeric keyboard, verify type=email, feedback for invalid/expired code, resend cooldown, change email and focus management, no token in logs. Don't silently promise a code if project email template instead sends a magic link: verify template configuration.
- Email/password login identical to Transport user account via signInWithPassword; no self-registration in Jarvis, link to Transport registration where relevant.
- Disabled GitHub OAuth button (don't request unsupported provider). User-facing note and setup checklist GitHub OAuth app + provider secret in Supabase TSAND; do NOT put secrets in front-end.
- After login re-check jarvis_admins RLS before showing dashboard; robust logout, session restore and token/url callback handling; never sign out a valid app account solely because the user has no Jarvis admin role (reject Jarvis UI access instead).
- Clear auth errors without exposing provider exception dumps or leaking account existence.

## Iteration B (P1, actionable operations)
- Run search by ID/phase, status chips (running/blocked/failed/succeeded), manual refresh and last successful sync time.
- Summary KPIs: run counts by outcome, total actual input+output tokens (not including nested cached+reasoning), estimated cost clearly labeled; overdue/stale feedback warning does NOT rewrite DB status.
- Run details with phase, elapsed time, last event, PR links, grouped agents and filtered event timeline.
- UX Critic findings/Engineer handoffs distinguish warnings vs actionable blockers, read-only presentation.
- Mobile-friendly full-height layout; primary controls tappable, no horizontal scroll, visible focus and proper label/status semantics.

## Iteration C (P2, after A/B verified)
- Cost per run/milestone with server ledger reconciliation, unknown billing marked reserved.
- Alerts and notification digest for blocked/stale/failed runs; no automatic spending.
- Artifact/evidence links (GitHub actions, candidate diff, tests, screenshots, PR); no secrets or signed urls stored client-side.
- Memory provenance and revision history panel; reconciled state across runners.
- Controlled approvals: budget grants and release decisions must be explicitly attributable to user, never implicit button clicks.
- Multi-project filtering (future), configurable retention policies, audit export.

## Crew workflow
1. Product Engineering analyses app, data and live implementation, proposes minimal scoped diff with tests.
2. UX Critic evaluates user-facing value, interaction flow, accessibility and unnecessary complexity. At most one targeted change round; feedback delivered to Engineer and archived.
3. Security/Data Reviewer validates RLS, authentication, error behavior, budget isolation, staging-only deploy, idempotency and rollback.
4. Release Reviewer confirms evidence from GitHub Actions, reports GO/NO-GO for TSAND only. No automatic approval.
5. Jarvis mirrors this dialogue as read-only run events and identifies which tasks require user budget approval.

## Acceptance gates
- Node unit tests for invalid/successful OTP, resend guard, password flow, disabled GitHub, admin denied, account reuse.
- Browser Chromium mobile and desktop: login → code field, wrong code feedback, password mode, no unwanted OAuth redirect; guest cannot render private dashboard.
- GitHub Actions staging-only deploy of ONE html file, verify remote marker and TSAND config.
- No live email send unless specifically authorized to test with real mailbox (no unsolicited mail).
- No GitHub OAuth activation without Client ID/secret and callback/redirect allowlist check.
- No LLM spend unless explicitly approved. Deterministic CI simulated feedback can run free but MUST NOT be labeled a real LLM review.
- User runs manual Safari confirmation, then next milestone.

## Agent deliverables
- Engineer: versioned patch, targeted tests and app UX changelog.
- UX Critic: 3 prioritized findings including why they matter; actionable accept/reject feedback to developer.
- Reviewer: threat model, no-prod verification and evidence-backed GO/NO-GO.
- Controller: reservations, pricing, actual vs estimated costs, halt unknown values.
