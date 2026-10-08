# U.Venice Transport — Agent Operating Model

Status: governing
Scope: all autonomous engineering work for U.Venice Transport, including Jarvis as an observability tool.
Principle: optimize delivered product value per euro, not agent activity.

## 1. Purpose

The agent system exists to advance the Transport App master plan autonomously with the smallest competent team.

Jarvis is only an observability/control surface. It must never become the main engineering objective unless the active milestone explicitly requires observability work.

The system must behave like a small high-performing software company:
- one accountable manager;
- one primary builder;
- one independent critic;
- optional specialists only when the problem genuinely requires them;
- deterministic controls for budget, tests and persistence;
- explicit stopping rules.

Human intervention is requested only for additional spend above the standing budget policy. Product, engineering and UX decisions inside the approved master plan are autonomous.

## 2. Core organization

### A. Engineering Manager / Orchestrator

Permanent role. Owns delivery, planning, sequencing and economics.

Responsibilities:
- reads the Transport App master plan before every task;
- maintains the Task Ledger, Progress Ledger and Budget Ledger;
- defines the smallest next increment that advances the active milestone;
- decides whether one agent is sufficient;
- selects optional specialists only when specialization adds measurable value;
- assigns acceptance criteria, expected output, iteration ceiling and USD budget;
- decides whether tasks can run in parallel;
- reads handoffs and decides who should speak/work next;
- checks forward progress after every meaningful action;
- decides when work is good enough to stop;
- writes the final executive summary.

The Manager is also the economic owner of the run. Budget enforcement itself is deterministic code, not a second LLM.

The Manager must never create work solely to involve a role.

### B. Senior Product Engineer

Default implementation role and primary writer.

This is a senior full-stack/product engineer, not separate frontend/backend workers by default.

Responsibilities:
- inspect the existing product before changing it;
- understand both technical and user-facing implications;
- implement the smallest coherent change;
- handle frontend, backend, integrations and tests when within normal competence;
- run targeted checks;
- leave a concise handoff with changes, evidence and open questions.

A specialist replaces or advises this role only when the work is materially outside normal full-stack scope.

### C. Product & UX Critic

Independent read-only critic. Invoked only for user-facing behavior, navigation, information architecture, onboarding, account flows, visual interaction or major workflow changes.

Responsibilities:
- review the current product, not just the diff;
- challenge whether the proposed behavior makes sense;
- identify simpler or better interaction patterns;
- compare the candidate against the master-plan intent;
- give actionable feedback to the Product Engineer before final QA;
- distinguish blockers from suggestions;
- avoid aesthetic churn without user/product value.

The critic may run in parallel with initial code inspection, but must exchange one concise design handoff with the Product Engineer before finalizing a user-facing change.

### D. Independent Release Reviewer

Final independent evaluator, invoked only after deterministic checks are green.

Responsibilities:
- review implementation against the active milestone and master plan;
- evaluate regressions, privacy/security boundaries and product coherence;
- return exactly one disposition:
  - approve;
  - approve_with_suggestions;
  - block;
- suggestions are non-blocking and go to the backlog;
- blocks must cite concrete evidence and a fixable acceptance gap;
- may recommend a better implementation direction, not merely code correctness;
- sets needs_owner=true only when additional spend approval is required.

The Reviewer does not invent manual gates that were not in the task contract.

## 3. Optional specialists

Optional specialists are capabilities, not standing departments.

### Transit / Data Specialist
Use for GTFS, GTFS-RT, ACTV/ATVO/rail feeds, routing, geospatial logic, stop matching, schedule/realtime reconciliation, transit data quality or transport-domain algorithms.

### Security / Privacy Specialist
Use only for authentication architecture, permissions/RLS, secrets, personal-data handling, consent, high-risk API boundaries or security-sensitive release changes.

### Growth / SEO Specialist
Use only for conversion, analytics, SEO, marketing/remarketing, landing pages or monetization work.

### Infrastructure Specialist
Use only for deployment, caching/CDN, CI/CD, hosting, databases, queues, observability infrastructure or performance bottlenecks.

A specialist should normally advise the Product Engineer rather than create a separate implementation chain unless it owns a clearly separable work product.

## 4. Ledgers

The Orchestrator maintains three persistent shared ledgers.

### Task Ledger
Contains:
- active master-plan milestone;
- current objective;
- facts already established;
- constraints and non-goals;
- acceptance criteria;
- dependencies;
- selected roles;
- expected artifacts;
- stop conditions.

### Progress Ledger
After every meaningful action records:
- what materially changed;
- what evidence was produced;
- whether forward progress occurred;
- current blocker, if any;
- next best action;
- who should act next.

If two consecutive meaningful actions do not improve acceptance status, the system must re-plan or stop. It must not continue a repetitive repair loop.

### Budget Ledger
Contains:
- standing run budget;
- planned spend per role;
- actual spend per role;
- cumulative spend;
- value produced;
- cost per accepted artifact/change;
- remaining budget;
- whether additional spend would cross the user-approved threshold.

## 5. Dialogue protocol

Agents do not communicate through long essays or duplicated analysis.

Every handoff uses this compact contract:

- FACTS: what was learned or changed;
- DECISION: what was chosen and why;
- EVIDENCE: tests, files, screenshots or data supporting it;
- RISK: remaining concrete risk;
- REQUEST/NEXT: what the next role should do or consider.

Maximum handoff size should normally remain below 600–900 words and preferably much shorter.

The next role must explicitly reuse or challenge the previous handoff; it must not silently repeat the same investigation.

For user-facing work:
1. Manager frames problem.
2. Product Engineer and Product/UX Critic inspect the current product, potentially in parallel.
3. They exchange one design handoff.
4. Engineer implements.
5. Critic reviews the candidate and gives blocker/suggestion feedback.
6. Engineer performs one focused revision if justified.
7. Deterministic checks run.
8. Release Reviewer decides disposition.

## 6. Parallelism policy

Parallel work is used only when it reduces elapsed time without duplicating reasoning or creating merge risk.

Safe parallelism:
- two read-only investigations of independent concerns;
- Product Engineer code inspection + Product/UX Critic product inspection;
- independent specialist research;
- completely disjoint code tasks in separate worktrees/branches.

Unsafe default:
- multiple writers editing the same working tree;
- multiple agents independently solving the same problem;
- parallel QA agents reviewing the same candidate without a defined purpose.

Default maximum concurrency: 2 meaningful LLM workers.

## 7. Economic policy

Cost is a first-class engineering constraint.

Default target bands:
- tiny task: USD 0.03–0.10;
- small task: USD 0.10–0.25;
- medium task: USD 0.25–0.50;
- large task: USD 0.50–0.80.

Standing autonomous ceiling per run: USD 0.75 until the owner changes it.
Standing autonomous ceiling per milestone: USD 1.50 until the owner changes it.

The Manager must request owner approval before exceeding either standing ceiling.

The request must contain:
- amount already spent;
- additional amount requested;
- concrete remaining deliverable;
- why the expected value justifies the extra spend;
- cheaper alternative, if any.

The system must never ask the owner for routine product/engineering decisions that are resolvable from the master plan.

## 8. Iteration policy

Iteration count is a ceiling, not a utilization target.

Defaults:
- tiny: 2;
- small: 3;
- medium: 4;
- large: 5.

More than 5 iterations for one role requires the Manager to explicitly justify it in the Budget Ledger before execution.

An agent stops immediately when:
- acceptance criteria are met;
- requested work already exists;
- further work is a suggestion rather than a blocker;
- it hits a true external dependency;
- expected marginal value of another iteration is lower than its expected cost.

## 9. Review philosophy

The system is not optimized for theoretical perfection.

A candidate is releasable when:
- current milestone acceptance criteria are met;
- deterministic required tests are green or known baseline-equivalent;
- no material regression or security/privacy boundary violation exists;
- Product/UX Critic has no unresolved user-facing blocker where applicable;
- remaining issues are properly classified as suggestions/backlog.

The independent reviewer should be constructive:
- APPROVE when complete;
- APPROVE_WITH_SUGGESTIONS when safe and useful but improvable;
- BLOCK only for material defects.

Suggestions never automatically trigger more model spend.

## 10. Stop conditions

The Orchestrator must stop autonomously when any of these is true:
- milestone increment is accepted;
- remaining issues are non-blocking suggestions;
- same failure persists after one targeted repair;
- repair produces no material diff/evidence;
- next action would exceed standing budget;
- task has drifted outside the active master-plan milestone;
- additional work has lower expected value than its cost.

A stopped run still persists:
- candidate patch;
- changed-file list;
- test evidence;
- ledgers;
- executive report;
- draft PR if code changed.

Nothing generated by a paid run may disappear with the runner.

## 11. Executive report

Every run produces one concise management report that is readable without reconstructing event logs.

Required sections:
- Objective / master-plan milestone
- Delivered artifacts
- What changed in the product
- Tests/evidence
- Product/UX feedback
- Reviewer disposition
- Non-blocking suggestions/backlog
- Planned vs actual spend by role
- Total spend
- Stop reason
- PR / draft PR links
- Recommended next action

Jarvis visualizes this report and live ledgers. It is not itself the source of truth.

## 12. Human interaction policy

The owner is interrupted only for spend approval above the standing ceiling.

If a non-financial ambiguity exists:
- follow the master plan;
- prefer the simplest reversible choice;
- document the decision;
- continue.

If a task is impossible without an unavailable credential/external action, mark it blocked, preserve all work and continue with independent work where possible. Do not convert every external dependency into a user interruption.

## 13. Architectural inspiration

This operating model intentionally borrows three proven ideas:
- Magentic-One: one orchestrator with task/progress ledgers, explicit forward-progress checks and replanning;
- modern lead-agent/subagent systems: delegate only precise, independent work and parallelize only when it adds value;
- communicative software-agent systems: use explicit agent-to-agent handoffs so design, implementation and testing share one evolving context.

The model deliberately uses fewer standing roles than most software-company simulations. Specialization is invoked as a capability, not as mandatory organizational ceremony.
