# Transactional CrewAI migration — 2026-10-08

Status: IN PROGRESS / NOT AUTHORIZED FOR PAID RUNS.

## Baseline and scope
- Target branch: infra/crewai-bootstrap, not product production main.
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
