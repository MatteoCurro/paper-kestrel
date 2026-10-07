from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Literal

from crewai import Agent, Crew, LLM, Process, Task
from pydantic import BaseModel, Field

from .tools import developer_tools, reviewer_tools
from .jarvis import EMITTER


DeveloperRole = Literal[
    "frontend_lead",
    "frontend_quality",
    "backend_lead",
    "data_platform",
    "solution_architect",
]

CheckName = Literal["full_test", "diff_check", "python_compile", "account_focus"]


class WorkItem(BaseModel):
    id: str
    role: DeveloperRole
    objective: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    files_hint: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class DispatchPlan(BaseModel):
    summary: str
    risk: Literal["low", "medium", "high"]
    use_solution_architect: bool = True
    use_product_growth: bool = False
    use_ui_ux: bool = False
    work_items: list[WorkItem]
    mandatory_checks: list[CheckName] = Field(default_factory=lambda: ["full_test", "diff_check"])


class ReviewDecision(BaseModel):
    approved: bool
    summary: str
    blocking_issues: list[str] = Field(default_factory=list)
    repair_role: DeveloperRole = "solution_architect"


def model(name: str, fallback: str, max_tokens: int = 12000) -> LLM:
    effort = "medium" if name == "MODEL_CORE" else "low"
    return LLM(
        model=os.environ.get(name, fallback),
        api="responses",
        timeout=300,
        max_completion_tokens=max_tokens,
        reasoning_effort=effort,
    )


CORE = lambda: model("MODEL_CORE", "openai/gpt-6.1-sol")
LIGHT = lambda: model("MODEL_LIGHT", "openai/gpt-6-luna", 8000)


def agent_for(role: str, writable: bool = False) -> Agent:
    tools = developer_tools() if writable else reviewer_tools()
    definitions = {
        "delivery_director": (
            "Delivery Director",
            "Turn the owner's technical specification into the smallest safe ordered execution plan. "
            "Choose who works, in what order, and keep the system moving when a specialist gets blocked.",
            "You are a principal engineering delivery manager. You value small diffs, explicit dependencies, "
            "testable acceptance criteria, cost control and rollback safety.",
            CORE(),
        ),
        "solution_architect": (
            "Solution Architect",
            "Protect architectural coherence, dependency boundaries, privacy and deployment safety.",
            "You understand large JavaScript applications, transport-data systems, GitHub Actions and incremental refactoring. "
            "You prevent duplicate abstractions and big-bang rewrites.",
            CORE(),
        ),
        "frontend_lead": (
            "Senior Frontend Engineer",
            "Implement robust mobile-first UI and client behavior with minimal regression surface.",
            "You are an expert in vanilla JavaScript, browser APIs, responsive layout, state management and performance.",
            CORE(),
        ),
        "frontend_quality": (
            "Frontend Quality and Accessibility Engineer",
            "Harden responsive behavior, accessibility, keyboard/viewport handling and browser compatibility.",
            "You specialize in iOS Safari, narrow mobile layouts, accessibility and regression-resistant CSS/DOM behavior.",
            CORE(),
        ),
        "backend_lead": (
            "Senior Backend and Integration Engineer",
            "Implement safe APIs, authentication/integration logic and server-side boundaries with minimal operational load.",
            "You specialize in PHP/Python integration, Supabase, API contracts, security boundaries and low-overhead hosting.",
            CORE(),
        ),
        "data_platform": (
            "Senior Data and Transit Platform Engineer",
            "Implement and validate data pipelines, provider adapters, schedules, realtime and deterministic transformations.",
            "You specialize in GTFS/GTFS-RT, ingestion pipelines, data provenance and resilient provider abstractions.",
            CORE(),
        ),
        "product_growth": (
            "Product Manager and Growth Strategist",
            "Check that requested changes create user value, support conversion and measurement, and avoid dark patterns.",
            "You connect UX, product strategy, analytics, consent and commercial goals. You are concise and evidence-oriented.",
            LIGHT(),
        ),
        "ui_ux": (
            "Senior UI/UX and Visual Design Reviewer",
            "Translate product intent into coherent interaction and visual guidance while preserving the existing design system.",
            "You specialize in mobile information architecture, hierarchy, spacing, typography, interaction states and visual consistency.",
            CORE(),
        ),
        "qa_release": (
            "QA, Security and Release Reviewer",
            "Try to break the implementation, identify regressions, verify acceptance criteria and block unsafe release candidates.",
            "You are independent from implementers. You inspect diffs and tests, prioritize user-visible regressions, privacy and security.",
            CORE(),
        ),
    }
    title, goal, backstory, llm = definitions[role]
    return Agent(
        role=title,
        goal=goal,
        backstory=backstory,
        tools=tools,
        llm=llm,
        allow_delegation=False,
        max_iter=6,
        max_retry_limit=1,
        verbose=False,
    )


def _jarvis_phase(role: str) -> str:
    if role == "Delivery Director":
        return "planning"
    if role in {"Solution Architect", "Senior UI/UX and Visual Design Reviewer", "Product Manager and Growth Strategist"}:
        return "architecture"
    if role == "QA, Security and Release Reviewer":
        return "qa"
    return "implementation"


def _role_title(role: str) -> str:
    return {
        "frontend_lead": "Senior Frontend Engineer",
        "frontend_quality": "Frontend Quality and Accessibility Engineer",
        "backend_lead": "Senior Backend and Integration Engineer",
        "data_platform": "Senior Data and Transit Platform Engineer",
        "solution_architect": "Solution Architect",
    }.get(role, role)


def run_single(agent: Agent, description: str, expected: str, output_pydantic=None):
    task = Task(
        description=description,
        expected_output=expected,
        agent=agent,
        output_pydantic=output_pydantic,
    )
    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        max_rpm=int(os.environ.get("MAX_RPM", "30")),
    )
    phase = _jarvis_phase(agent.role)
    model_name = getattr(agent.llm, "model", None)
    EMITTER.emit(
        "agent.started",
        f"{agent.role}: attività avviata",
        agent=agent.role,
        status="working",
        phase=phase,
        model=model_name,
    )
    try:
        result = crew.kickoff()
    except Exception as exc:
        EMITTER.emit(
            "agent.failed",
            f"{agent.role}: errore {type(exc).__name__}",
            agent=agent.role,
            status="failed",
            phase=phase,
            model=model_name,
        )
        raise
    EMITTER.emit(
        "agent.completed",
        f"{agent.role}: attività completata",
        agent=agent.role,
        status="done",
        phase=phase,
        model=model_name,
        usage=getattr(result, "token_usage", None),
    )
    if output_pydantic is not None:
        parsed = task.output.pydantic
        if parsed is None:
            raise RuntimeError(f"Structured output missing from {agent.role}: {result}")
        return parsed
    return str(result)


def _normalized_test_tail(output: str, roots: list[Path], limit: int = 16000) -> str:
    normalized = output
    for root in roots:
        normalized = normalized.replace(str(root), "<WORKSPACE>")
    return normalized[-limit:]


def _run_full_test_with_baseline(work: Path) -> tuple[int, str]:
    cmd = ["npm", "test"]
    try:
        candidate = subprocess.run(
            cmd,
            cwd=work,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=1200,
        )
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"

    if candidate.returncode == 0:
        return 0, candidate.stdout[-30000:]

    with tempfile.TemporaryDirectory(prefix="paper-kestrel-baseline-") as tmp:
        baseline = Path(tmp) / "baseline"
        add = subprocess.run(
            ["git", "worktree", "add", "--detach", str(baseline), "HEAD"],
            cwd=work,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if add.returncode != 0:
            return candidate.returncode, (
                candidate.stdout[-24000:]
                + "\n\nBASELINE_COMPARISON_UNAVAILABLE:\n"
                + add.stdout[-4000:]
            )

        try:
            node_modules = work / "node_modules"
            if node_modules.exists() and not (baseline / "node_modules").exists():
                (baseline / "node_modules").symlink_to(node_modules, target_is_directory=True)
            try:
                baseline_run = subprocess.run(
                    cmd,
                    cwd=baseline,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=1200,
                )
            except subprocess.TimeoutExpired:
                return candidate.returncode, candidate.stdout[-24000:] + "\n\nBASELINE_TEST_TIMEOUT"
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(baseline)],
                cwd=work,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )

    candidate_tail = _normalized_test_tail(candidate.stdout, [work, baseline])
    baseline_tail = _normalized_test_tail(baseline_run.stdout, [work, baseline])
    if candidate.returncode == baseline_run.returncode and candidate_tail == baseline_tail:
        return 0, (
            candidate.stdout[-26000:]
            + "\n\nBASELINE_EQUIVALENT_FAILURE: candidate and unchanged baseline fail identically; "
            "no regression detected in the full suite."
        )

    return candidate.returncode or 1, (
        "CANDIDATE_FULL_TEST:\n"
        + candidate.stdout[-14000:]
        + "\n\nBASELINE_FULL_TEST:\n"
        + baseline_run.stdout[-14000:]
    )


def run_check(name: str, work: Path) -> tuple[int, str]:
    if name == "full_test":
        return _run_full_test_with_baseline(work)
    elif name == "diff_check":
        _mark_untracked_for_diff(work)
        cmd = ["git", "diff", "--check", "--", ".", ":(exclude)node_modules/**"]
    elif name == "python_compile":
        cmd = ["python3", "-m", "py_compile", "server/build_transit_data.py", "scripts/build_topocivici.py"]
    elif name == "account_focus":
        cmd = ["bash", "-lc", "node tests/account-foundation.cjs && node tests/account-onboarding.cjs && node tests/account-sync-ui.cjs"]
    else:
        return 2, f"unknown check: {name}"
    try:
        p = subprocess.run(cmd, cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200)
        return p.returncode, p.stdout[-30000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def _mark_untracked_for_diff(work: Path) -> None:
    subprocess.run(
        ["git", "add", "-N", "--", ".", ":(exclude)node_modules/**"],
        cwd=work,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )


def git_diff(work: Path, limit: int = 50000) -> str:
    _mark_untracked_for_diff(work)
    p = subprocess.run(["git", "diff", "--", "."], cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    return p.stdout[:limit] + ("\n...TRUNCATED..." if len(p.stdout) > limit else "")


def changed_js_tests(work: Path) -> list[str]:
    _mark_untracked_for_diff(work)
    p = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "--", "tests/*.cjs"],
        cwd=work,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    return sorted({line.strip() for line in p.stdout.splitlines() if line.strip().startswith("tests/") and line.strip().endswith(".cjs")})


def run_changed_js_test(path: str, work: Path) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["node", path],
            cwd=work,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        return p.returncode, p.stdout[-12000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def execute_work_item(item: WorkItem, spec: str, advice: str) -> str:
    worker = agent_for(item.role, writable=True)
    return run_single(
        worker,
        f"""OWNER SPECIFICATION:
{spec}

WORK ITEM:
{item.model_dump_json(indent=2)}

ADVISORY CONTEXT:
{advice}

Work directly in the repository using the provided file/search/write/check tools.
First inspect the relevant existing code. Make the smallest coherent implementation that satisfies the acceptance criteria.
Do not edit GitHub workflows, deployment credentials, generated runtime data or unrelated features.
Preserve IT/EN/FR/DE parity for user-facing strings.
Run targeted checks before finishing. If blocked, inspect more context and choose a safe fallback instead of inventing APIs.
At the end summarize exactly what changed and any residual risk.""",
        "Implemented code changes plus a concise implementation summary and tests run.",
    )


def cli() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--workspace", default="work")
    ap.add_argument("--report-dir", default="output")
    args = ap.parse_args()

    work = Path(args.workspace).resolve()
    os.environ["AGENT_WORKSPACE"] = str(work)
    spec_path = Path(args.spec).resolve()
    spec = spec_path.read_text(encoding="utf-8")
    EMITTER.set_spec(args.spec)
    EMITTER.emit(
        "run.started",
        f"Run avviato per {args.spec}",
        status="running",
        phase="setup",
        event_key="run:started",
    )
    if len(spec) > 80000:
        raise SystemExit("Specification is too large; split it into a focused delivery order.")

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    event_log: list[dict] = []

    director = agent_for("delivery_director", writable=False)
    plan = run_single(
        director,
        f"""Read this owner-approved technical specification and create the execution plan.

{spec}

Rules:
- Maximum six coding work items.
- Use the smallest set of specialists necessary.
- Order items so dependencies are implemented first.
- Frontend behavior belongs to frontend_lead; responsive/accessibility hardening to frontend_quality.
- APIs/auth/server integration belong to backend_lead.
- Transit/provider/data pipeline work belongs to data_platform.
- Cross-cutting architecture or ambiguous ownership belongs to solution_architect.
- Request product/growth review only when conversion, onboarding, analytics, consent or commercial behavior is materially involved.
- Request UI/UX review when information architecture, screen layout, interaction flow or visual hierarchy changes.
- Never plan production deployment, DNS changes or secret handling.
- Every work item must have observable acceptance criteria.
- mandatory_checks may contain ONLY these exact identifiers: full_test, diff_check, python_compile, account_focus.
- Do not put prose, PR/delivery steps, file paths, or shell commands in mandatory_checks.
- Use full_test and diff_check for normal work; add python_compile or account_focus only when materially relevant.""",
        "A structured dispatch plan with ordered work items and mandatory checks.",
        DispatchPlan,
    )
    plan.work_items = plan.work_items[:6]
    event_log.append({"stage": "plan", "data": plan.model_dump()})
    EMITTER.emit(
        "plan.created",
        f"Piano creato: {len(plan.work_items)} work item · rischio {plan.risk}",
        agent="Delivery Director",
        status="done",
        phase="planning",
        summary=plan.summary,
        details={"work_items": len(plan.work_items), "risk": plan.risk},
    )

    advice_parts: list[str] = []
    if plan.use_solution_architect:
        advice_parts.append(
            run_single(
                agent_for("solution_architect"),
                f"Review the specification and current repository architecture. Identify boundaries, likely regression points and constraints the implementers must preserve.\n\n{spec}",
                "Concise architecture constraints and implementation guidance.",
            )
        )
    if plan.use_product_growth:
        advice_parts.append(
            run_single(
                agent_for("product_growth"),
                f"Review this change from product, growth, analytics and consent perspectives. Give concrete constraints, not generic marketing copy.\n\n{spec}",
                "Concise product/growth constraints and measurable acceptance guidance.",
            )
        )
    if plan.use_ui_ux:
        advice_parts.append(
            run_single(
                agent_for("ui_ux"),
                f"Review this change against the existing mobile-first UI. Specify hierarchy, interaction states, responsive behavior and visual constraints the frontend implementer should follow.\n\n{spec}",
                "Concise UI/UX implementation guidance.",
            )
        )
    advice = "\n\n--- ADVISOR ---\n".join(advice_parts) or "No additional advisory review requested."

    completed: list[str] = []
    for item in plan.work_items:
        EMITTER.emit(
            "handoff",
            f"Director → {_role_title(item.role)}: {item.objective}",
            agent="Delivery Director",
            status="done",
            phase="implementation",
            details={"work_item": item.id, "to": item.role},
        )
        missing = [d for d in item.depends_on if d not in completed]
        if missing:
            raise RuntimeError(f"Invalid plan: {item.id} depends on unfinished {missing}")
        try:
            summary = execute_work_item(item, spec, advice)
            event_log.append({"stage": "implementation", "item": item.id, "role": item.role, "summary": summary[-6000:]})
            EMITTER.emit(
                "agent.report",
                summary[-640:],
                agent=_role_title(item.role),
                status="done",
                phase="implementation",
                details={"work_item": item.id},
            )
            completed.append(item.id)
        except Exception as exc:
            event_log.append({"stage": "blocked", "item": item.id, "role": item.role, "error": str(exc)})
            fallback = WorkItem(
                id=item.id + "-fallback",
                role="solution_architect",
                objective=f"Unblock and complete this failed work item: {item.objective}. Failure: {exc}",
                acceptance_criteria=item.acceptance_criteria,
                files_hint=item.files_hint,
            )
            summary = execute_work_item(fallback, spec, advice)
            event_log.append({"stage": "fallback", "item": fallback.id, "role": fallback.role, "summary": summary[-6000:]})
            completed.append(item.id)

    max_repairs = int(os.environ.get("MAX_REPAIR_ROUNDS", "2"))
    allowed_checks: set[str] = {"full_test", "diff_check", "python_compile", "account_focus"}
    checks = [check for check in dict.fromkeys([*plan.mandatory_checks, "full_test", "diff_check"]) if check in allowed_checks]
    final_review = None
    final_checks: dict[str, dict] = {}

    for round_no in range(max_repairs + 1):
        final_checks = {}
        for check in checks:
            EMITTER.emit(
                "check.started",
                f"{check}: controllo in corso",
                agent="Controller",
                status="checking",
                phase="testing",
                details={"check": check},
            )
            rc, out = run_check(check, work)
            final_checks[check] = {"returncode": rc, "output": out[-12000:]}
            EMITTER.emit(
                "check.completed",
                f"{check}: {'ok' if rc == 0 else 'fallito'}",
                agent="Controller",
                status="success" if rc == 0 else "failed",
                phase="testing",
                details={"check": check, "returncode": rc},
            )
        for test_path in changed_js_tests(work):
            EMITTER.emit(
                "check.started",
                f"{test_path}: test mirato in corso",
                agent="Controller",
                status="checking",
                phase="testing",
                details={"check": "changed_js_test", "path": test_path},
            )
            rc, out = run_changed_js_test(test_path, work)
            final_checks[f"changed_js_test:{test_path}"] = {"returncode": rc, "output": out[-12000:]}
            EMITTER.emit(
                "check.completed",
                f"{test_path}: {'ok' if rc == 0 else 'fallito'}",
                agent="Controller",
                status="success" if rc == 0 else "failed",
                phase="testing",
                details={"check": "changed_js_test", "path": test_path, "returncode": rc},
            )
        diff = git_diff(work)

        reviewer = agent_for("qa_release", writable=False)
        final_review = run_single(
            reviewer,
            f"""Independently review this implementation against the owner specification.

OWNER SPECIFICATION:
{spec}

DISPATCH PLAN:
{plan.model_dump_json(indent=2)}

CHECK RESULTS:
{json.dumps(final_checks, indent=2)}

CURRENT DIFF:
{diff}

Approve only if the implementation is coherent, tests are acceptable, the diff matches the requested scope, no unrelated behavior was changed, and privacy/security/deployment boundaries are preserved.
The pull request is intentionally opened by the controller only AFTER your approval. Do not require a PR to exist yet and do not block approval because delivery has not happened.
A full_test result with returncode 0 and the marker BASELINE_EQUIVALENT_FAILURE means the candidate and unchanged baseline failed identically in the deliberately incomplete public validation workspace; treat that as a passed non-regression check.
When that marker is present, do not override it by rerunning full_test independently: the controller's baseline comparison is the authoritative non-regression result. You may still run targeted checks on changed files.
If blocking issues exist, list them concretely and choose the specialist role best suited to repair them.""",
            "A structured release decision.",
            ReviewDecision,
        )
        event_log.append({"stage": "review", "round": round_no, "data": final_review.model_dump()})
        EMITTER.emit(
            "review.decision",
            final_review.summary,
            agent="QA, Security and Release Reviewer",
            status="approved" if final_review.approved else "blocked",
            phase="qa",
            details={"round": round_no, "blocking_issues": len(final_review.blocking_issues)},
        )

        checks_green = all(v["returncode"] == 0 for v in final_checks.values())
        if final_review.approved and checks_green:
            break
        if round_no >= max_repairs:
            break

        problems = "\n".join(final_review.blocking_issues) or "\n".join(
            f"{k}: returncode {v['returncode']}" for k, v in final_checks.items() if v["returncode"] != 0
        )
        EMITTER.emit(
            "handoff",
            f"QA → {_role_title(final_review.repair_role)}: repair #{round_no + 1}",
            agent="QA, Security and Release Reviewer",
            status="done",
            phase="qa",
            details={"repair_round": round_no + 1, "to": final_review.repair_role},
        )
        repair = WorkItem(
            id=f"repair-{round_no + 1}",
            role=final_review.repair_role,
            objective="Repair the blocking review/test failures without broadening scope.\n" + problems,
            acceptance_criteria=["All mandatory checks pass", "Reviewer blockers are resolved", "No unrelated changes"],
        )
        summary = execute_work_item(repair, spec, advice)
        event_log.append({"stage": "repair", "round": round_no + 1, "role": repair.role, "summary": summary[-6000:]})

    success = bool(final_review and final_review.approved and all(v["returncode"] == 0 for v in final_checks.values()))
    report = {
        "success": success,
        "plan": plan.model_dump(),
        "checks": final_checks,
        "review": final_review.model_dump() if final_review else None,
        "events": event_log,
    }
    (report_dir / "agent-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (report_dir / "agent-report.md").write_text(
        "# Automation report\n\n"
        + f"Success: **{success}**\n\n"
        + f"Plan: {plan.summary}\n\n"
        + "Review: "
        + (final_review.summary if final_review else "not completed")
        + "\n",
        encoding="utf-8",
    )
    if success:
        EMITTER.emit(
            "run.ready",
            "QA approvato: candidato pronto per apertura PR",
            status="running",
            phase="delivery",
            summary=final_review.summary if final_review else "Review completata",
            event_key="run:ready",
        )
    else:
        EMITTER.emit(
            "run.failed",
            final_review.summary if final_review else "Run non approvato",
            status="failure",
            phase="qa",
            need_owner=True,
            summary=final_review.summary if final_review else "Run non approvato",
            finished=True,
            event_key="run:failed",
        )
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        cli()
    except SystemExit:
        raise
    except Exception as exc:
        EMITTER.emit(
            "run.failed",
            f"Errore orchestratore: {type(exc).__name__}",
            status="failure",
            phase="implementation",
            need_owner=True,
            summary=str(exc),
            finished=True,
            event_key="run:exception",
        )
        traceback.print_exc()
        raise SystemExit(3)
