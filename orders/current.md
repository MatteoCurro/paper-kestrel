# Jarvis v1 — M1 repair and auth alignment

Status: approved.
Master plan: MASTERPLAN-JARVIS.md

Continue the failed Jarvis M1 implementation and resolve only the concrete blockers from run 37676262065.

## Mandatory auth decision

The hosted Supabase project's email template emits a numeric OTP via {{ .Token }}.

Jarvis must use:
1. email entry;
2. supabase.auth.signInWithOtp({ email, options: { shouldCreateUser: false } });
3. explicit OTP code entry;
4. supabase.auth.verifyOtp({ email, token, type: 'email' });
5. authenticated RLS-backed dashboard.

Do NOT change the global Supabase email template.
Do NOT use a magic-link-only UX.
Do NOT make GitHub OAuth the primary operational path in this milestone.
GitHub OAuth is deferred until it can be safely linked to the existing authorized identity without creating a second account.

## Existing review blockers to fix

1. Responsive contract test
- tests/jarvis.cjs currently rejects legitimate responsive CSS because its regex matches max-width declarations and media-query breakpoints.
- Rewrite the assertion so it detects genuinely fixed/minimum desktop-only element widths without rejecting max-width or media queries.
- Preserve meaningful overflow protection.
- Rerun the focused Jarvis test.

2. Initial data must not depend on Realtime
- js/app/jarvis/integration.js currently loads initial runs only after a realtime SUBSCRIBED callback.
- Authenticated initial REST reads of agent_runs/agent_events must happen independently of realtime readiness.
- If Realtime fails but REST works, the dashboard must still show current/history data and mark realtime as disconnected/stale.
- Retry must retry data reads as well as the channel.
- Add deterministic tests for channel never subscribing / CHANNEL_ERROR while REST data remains available.

3. Finish operational UI
- ensure jarvis.html + assets/jarvis.css + js/app/jarvis/* all exist and initialize;
- OTP code flow works with shouldCreateUser:false;
- current run, owner interaction, agents, timeline, history, PR links, token/cost data and safe errors render correctly;
- no hidden chain-of-thought or sensitive payloads;
- read-only only.

## Verification

Run:
- focused Jarvis tests;
- full suite through controller baseline policy;
- account_focus;
- git diff --check.

Document any external Auth/RLS limitation without changing Supabase configuration.

## Delivery boundaries

- PR only.
- No merge.
- No production deploy.
- No DNS changes.
- No Supabase schema migration.
- No email-template modification.
- No credential or secret changes.
