# Transactional CrewAI migration — 2026-10-08

Status: IN PROGRESS / NOT AUTHORIZED FOR PAID RUNS.

## Baseline and scope
- Target branch: public paper-kestrel infra/transactional-v2 (draft PR #1), not product production main.
- Existing governance: AGENT-OPERATING-MODEL.md.
- Master plan remains in assembled product workspace.
- No product or production deploy is authorized by this migration.
- Current integration remains single-run oriented and is not production-certified.

## Implemented so far
- Added state.py: SQLite WAL, explicit BEGIN IMMEDIATE, durable transitions, transactional outbox, write leases, reservation/charge primitives.
- Connected basic run transitions and writer leases in main.py.
- Added default product_engineer role; made architect advisory opt-in.
- Hard-clamped orchestrator run cap to USD 0.75.
- Reduced maximum work items to 3 and repair rounds to 1.
- Removed unconditional solution-architect fallback on exceptions.
- Corrected QA -> repair invocation argument mismatch.
- Made Master Plan mandatory, resolved from product workspace.
- Added test_state.py offline regression coverage, wired before paid execution.
- Disabled paid Crew workflow execution pending acceptance.

## Blocking work before enabling
1. Replace old sequential Crew loop with a fully resumable state driver, with reliable checkpoint/re-entry semantics (no duplicate agent calls on restart).
2. Hook every LLM call into atomic budget reservation and settlement; measured and unknown model prices must fail closed, and the model output-token ceiling must inform worst-case exposure.
3. Persist and enforce milestone cap USD 1.50 across *different* GitHub runner instances; ephemeral runner SQLite alone cannot do this.
4. Make outbox the only path for Jarvis telemetry and implement idempotent delivery acknowledgements.
5. Enforce writer authorization inside write tools, not only at the outer work-item boundary.
6. Convert UI critic into required conditional feedback/revision gate for user-facing changes.
7. Ensure all error paths write a durable terminal state and report; capture restartable patches and draft PR without treating a failed run as successful.
8. Add offline failure-injection tests, duplicate delivery tests, replay tests and branch workflow smoke; establish actual test results.
9. Validate run-level spec and master checksum, work item dependencies and typed output contracts.
10. Compare new implementation to known task fixtures before approval.

## Non-negotiable release gate
Only unlock paid runs after all points above are tested and the budget/milestone budget cannot be exceeded by an unapproved call. A dry-run flag is not evidence of compliance.

## Explicit limitations
SQLite provides ACID only for its local transactions. GitHub pushes, LLM calls and Jarvis events are distributed side effects requiring idempotency and compensation. SQLite files stored only as ephemeral workflow artifacts do not satisfy durable cross-run persistence without a reliable restore/writeback store.

## 2026-10-08 follow-up: writer-tool hardening
- Added fail-closed SQLite write-lease validation inside WriteFileTool and ReplaceInFileTool; a workspace lease without matching run/work-item identity is insufficient.
- The runner binds RUN_STATE_DB, RUN_STATE_ID and ACTIVE_WORK_ITEM only within its work-item execution boundary; releases the lease in finally.
- Added offline regression test_write_lease.py covering missing lease, valid lease, wrong work-item, and released lease.
- No paid workflow was enabled and no production branch was modified.

### Open security/economic limitations
- The lease guard is an application-level guard for the current allowlisted tools, not a sandbox against malicious code execution. RunChecksTool and the filesystem environment must be assessed for all write side effects.
- Cost reservations have not yet been wired to every LLM invocation; the existing run budget is still post-call enforcement, so it is NOT a guaranteed monetary spending cap.
- GitHub Actions jobs still need a durable cross-run budget authority and checkpoint restore before safe activation.
- Tests were committed but not executed in this session: a passing status must not be assumed.

## 2026-10-08 follow-up: deterministic budget admission and safe CI
- Implemented budget.py with provider-enforced token-limit contract, model price fail-closed handling, maximal tool-roundtrip exposure and atomic pre-transport reservation primitive.
- Added test_budget.py with unknown-model, missing-limit, multi-roundtrip, duplicate-reservation and uncertain-charge cases.
- Added repository-root .github/workflows/crewai-offline-audit.yml to allow free, no-API-key CI tests from the CrewAI development branch. This is distinct from the nested historical workflow.
- Nested workflow crew.yml now has an unconditional migration stop *before* configuration validation, clone, installation or paid calls; an environment-variable override cannot unlock it.
- The budget module is NOT YET wired at the actual provider transport boundary. CrewAI can internally make multiple inference calls; guarding only crew.kickoff() would not satisfy the policy.
- Remaining release blockers: provider call interception + enforced input/output and tool-roundtrip bounds; cross-run milestone atomic authority; recovery; outbox-only telemetry; integration testing. Do not enable paid runs.
- No offline CI test results are claimed until the workflow actually reports success.

## 2026-10-08: central budget authority (public repo + Supabase TSAND)
**Implemented**
- `src/paper_kestrel/budget_llm.py` wraps the concrete CrewAI adapter behind `BaseLLM` to prevent provider-factory bypass. Every synchronous/asynchronous LLM call attempts both local and remote pre-admission before invoking its transport.
- `src/paper_kestrel/budget_gateway.py` uses short-lived GitHub Actions OIDC; **no static Supabase key is stored in GitHub**. The budget endpoint validates audience `crew-budget-supabase`, issuer, repository, workflow, allowed refs and numeric run identity.
- `sql/crew-budget-authority.sql` was installed on the **TSAND** Supabase project, with private schema `crew_budget`, row locking and hard ceilings of $0.75 per GitHub run ID and $1.50 per milestone.
- `edge/crew-budget/index.ts` was deployed to TSAND as edge function `crew-budget`. The run cap persists across retry attempts under the same GitHub run ID; reservation keys include attempt numbers.
- SQL tests were executed in a rolled-back transaction for duplicate reservation, over-run denial and over-milestone denial; the follow-up metadata query confirmed no test rows persisted and that `anon` cannot execute the reservation RPC.
- No real LLM workflow has been launched. The paid workflow's unconditional fail-closed gate is still first in the job.

**Observed CI and corrective action**
- The first GitHub Actions offline run (ID `37828971373`) passed Python syntax and dependency installation; 20 of 22 tests passed, 2 failed because tests mocked `crewai.LLM` while the library selected a different native provider class, causing a 401 with a fake test API key. No valid user API key was provided.
- Follow-up changes mock the concrete inner adapter and globally forbid network sockets during offline provider tests. The revised suite must be rerun before claiming a green result.

**Release blockers (NO-GO)**
1. Obtain passing offline CI **including** mocked denial and retry cases.
2. Confirm all provider retries and token ceilings are included in authorized exposure; CrewAI adapter internals can retry, so the current per-wrapper-call budget guarantee is not yet independently proven end to end.
3. Validate end-to-end OIDC authorization from public GitHub Actions to TSAND *without* making an LLM call.
4. Meter and reconcile actual usage safely, including unknown costs and interrupted calls; until verified, retain the whole conservative reservation instead of undercounting spending.
5. Finish durable run recovery, deterministic Saga/PR compensation, Jarvis outbox-only delivery and UX critic loop.
6. Keep legacy main workflow and new feature-branch workflow risks separate. Do not merge an unverified migration into main.

**Settings required for future gated runs**
- GitHub Actions `id-token: write`; environment variable `CREW_BUDGET_URL` is the public TSAND Edge URL; `CREW_BUDGET_AUDIENCE=crew-budget-supabase`.
- An explicit `MILESTONE_KEY` and `MODEL_PRICING_JSON` containing positive per-million input/output rates for the exact configured models. Missing pricing or milestone blocks all paid LLM calls.
- Never publish `OPENAI_API_KEY` or any Supabase service role key as a public file.

## 2026-10-08 continued — strict TSAND-only, crash recovery and Jarvis outbox
- Environment restriction confirmed: **NO PRODUCTION DEPLOY, NO MERGE, NO CHANGE TO PRIVATE PRODUCT MAIN**. Supabase authority remains TSAND only.
- Created dedicated `t-sand` branches in both public workspaces (`winter-opal`, `quiet-spindle`). The **still-blocked** operational GitHub Actions workflow now refuses other PR bases and targets `t-sand`, never `main`.
- Added `CheckpointJournal` with durable input hashes, explicit STARTED/COMPLETED/UNCERTAIN markers and candidate-diff integrity on replay. A crashed/uncertain LLM or writing operation is **blocked from silent replay**. A finished response may be reused only when its inputs match.
- Connected checkpointing to every `run_single` kickoff and to work-item boundaries; committed offline tests for simulated crashes, output replay and candidate mismatch.
- Added Jarvis event enqueue to the local SQLite outbox. `JarvisEmitter` now acknowledges delivered rows **only after HTTP 2xx**; failed/unknown ACKs retain the row. State transitions can be projected to Jarvis. Standalone CLI requires the same initialized run state, and the operational workflow binds its state path.
- Inspected the exact pinned CrewAI 1.15.23 source: `BaseLLM` wraps calls with bounded rate-limit retries, while the native OpenAI SDK adapter defaults to 2 retries. Set `max_retries=0` for the underlying adapter; the outer CrewAI retry must reenter the guarded wrapper and reserve anew. Added an offline synthetic 429 test.
- GitHub standard-hosted Actions minutes on PUBLIC repositories are free; this does not make LLM API usage free and does not eliminate artifact-storage charges.

**Still NO-GO for autonomous paid runs**
1. Require green CI for all new recovery/outbox/retry tests. An incomplete CI run is not evidence of success.
2. Prove OIDC in a dedicated **no-spend** staging workflow end to end. New feature-branch workflow registration may differ from local tests.
3. The SQLite file is **runner-local**. Resume across runners requires authenticated checkpoint snapshot/artifact restoration with integrity checks; without that, fail closed. Do not claim cross-run recovery.
4. Audit token/input bounds against the provider's actual serialized request. Byte counting and a rough context bound are not a formal upper bound on provider billable input. Verify exact model and rates; provider-side token output bounds, caching and retries must be proven.
5. Make write-role authorization and external Git/PR Saga idempotent across cancelled GitHub jobs, not only within a single SQLite instance.
6. Jarvis outbox depends on its receiving endpoint's idempotent `event_key`; test actual delivery on TSAND, not production.
7. This project follows the user's instruction to work **only in TSAND**. No deployment to any production host or product branch is permitted.

## Phases 1–3 — TSAND integration acceptance, 2026-10-09

| Phase | Implementation | Verified | Remaining boundary |
|---|---|---|---|
| 1 Budget | `metering.py` reconciles per-call input/output delta against accepted reservation; `budget_gateway.py` adds remote idempotent settlement; TSAND Edge admits settlement via private Postgres RPC | Unit tests; transactional SQL reserve/settle/idempotence under ROLLBACK | Real provider-specific serialization/input token bound and rate card must be audited before real spending |
| 1 Recovery | Private `crew_budget.checkpoints`, OIDC RPC claim/commit and Python `RemoteCheckpoint`; local journal imports verified remotely committed result across a fresh runner; interrupted claims remain blocked | Offline cross-run two-database regression; GitHub OIDC authenticated claim/commit/replay; matching row present in TSAND Postgres | Candidate filesystem patch is **not** automatically restored on a new runner; absent exact state, fail closed |
| 2 Agent dialogue | One independent **post-implementation** UX critique for UI diffs or explicitly requested UX review, followed by at most one Product Engineer revision; final QA Reviewer is independent | UX feedback contract tests and deterministic simulated revision / approval cases | First real CrewAI multi-model dialogue is intentionally deferred to phase 4 |
| 3 Simulation | `python -m paper_kestrel.simulation --scenario ux_revision|approved|crash|review_block`: real SQLite journal, writer lease/file tool, UX handoff and Jarvis outbox, deterministic role responses | GitHub Actions run 37879031268, **52 offline tests passed**, OIDC TSAND job passed, remote smoke checkpoint completed | Not a proof of real model decision quality, browser UX, or live PR creation |

### Safety invariant (unchanged)
- TSAND Supabase project only: `u-venice-transport-tsand`, edge function `crew-budget` v9.
- Edge code has `PAID_ADMISSION_ENABLED = false`; real model reservation and settlement endpoints return 423 until separately authorized.
- Operational workflow in this draft branch still stops before any run. Do not merge, unlock, or use `main` for agent PRs.
- Public staging product targets are `winter-opal:t-sand` and `quiet-spindle:t-sand`; no product production deployment.
- The **older workflow on paper-kestrel/main is separate** and must be explicitly audited/disabled before any autonomous activation. A draft-branch gate alone cannot secure main.
- Provider-side retry ceiling is set to zero; CrewAI rate-limit retries cross our guarded wrapper and reserve again. Unknown usage retains reserved exposure (never credited as free).
- Supabase security advisors report INFO `rls_enabled_no_policy` on four private `crew_budget` tables: intentional deny-by-default; service_role-only RPC access. Separate pre-existing Auth password-protection warning does not belong to CrewAI migration.

### Phase-4 NO-GO checklist
- [ ] Independently verify model IDs, published rate cards, provider input token accounting and output/retry ceilings (no optimistic byte-to-token assumptions).
- [ ] Safely restore exact changed workspace on GitHub retry, or explicitly continue to block rather than restart it.
- [ ] Complete full workflow dry-run including report and candidate PR against public `t-sand` without merging.
- [ ] Harden the public `main` legacy workflow, independently of V2 branch.
- [ ] Get explicit approval for any first paid run or run over the established budget policy.
- [ ] Keep production release, deployment credentials and private app `main` entirely out of scope.
