from __future__ import annotations

import argparse
import json
import os
import subprocess
import traceback
from pathlib import Path
from typing import Literal

from crewai import Agent, Crew, LLM, Process, Task
from pydantic import BaseModel, Field

from .tools import developer_tools, reviewer_tools


DeveloperRole = Literal[
    "frontend_lead",
    "frontend_quality",
    "backend_lead",
    "data_platform",
    "solution_architect",
]


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
    mandatory_checks: list[str] = Field(default_factory=lambda: ["full_test", "diff_check"])


class ReviewDecision(BaseModel):
    approved: bool
    summary: str
    blocking_issues: list[str] = Field(default_factory=list)
    repair_role: DeveloperRole = "solution_architect"


def model(name: str, fallback: str, max_tokens: int = 12000) -> LLM:
    effort = "medium" if name == "MODEL_CORE" else "low"
    return LLM(
        model=os.environ.get(name, fallback),
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
    result = crew.kickoff()
    if output_pydantic is not None:
        parsed = task.output.pydantic
        if parsed is None:
            raise RuntimeError(f"Structured output missing from {agent.role}: {result}")
        return parsed
    return str(result)


def run_check(name: str, work: Path) -> tuple[int, str]:
    if name == "full_test":
        cmd = ["npm", "test"]
    elif name == "diff_check":
        cmd = ["git", "diff", "--check"]
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


def git_diff(work: Path, limit: int = 50000) -> str:
    p = subprocess.run(["git", "diff", "--", "."], cwd=work, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    return p.stdout[:limit] + ("\n...TRUNCATED..." if len(p.stdout) > limit else "")


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
- Every work item must have observable acceptance criteria.""",
        "A structured dispatch plan with ordered work items and mandatory checks.",
        DispatchPlan,
    )
    plan.work_items = plan.work_items[:6]
    event_log.append({"stage": "plan", "data": plan.model_dump()})

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
        missing = [d for d in item.depends_on if d not in completed]
        if missing:
            raise RuntimeError(f"Invalid plan: {item.id} depends on unfinished {missing}")
        try:
            summary = execute_work_item(item, spec, advice)
            event_log.append({"stage": "implementation", "item": item.id, "role": item.role, "summary": summary[-6000:]})
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
    checks = list(dict.fromkeys(plan.mandatory_checks + ["full_test", "diff_check"]))
    final_review = None
    final_checks: dict[str, dict] = {}

    for round_no in range(max_repairs + 1):
        final_checks = {}
        for check in checks:
            rc, out = run_check(check, work)
            final_checks[check] = {"returncode": rc, "output": out[-12000:]}
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

Approve only if the implementation is coherent, tests are acceptable, no unrelated behavior was changed, and privacy/security/deployment boundaries are preserved.
If blocking issues exist, list them concretely and choose the specialist role best suited to repair them.""",
            "A structured release decision.",
            ReviewDecision,
        )
        event_log.append({"stage": "review", "round": round_no, "data": final_review.model_dump()})

        checks_green = all(v["returncode"] == 0 for v in final_checks.values())
        if final_review.approved and checks_green:
            break
        if round_no >= max_repairs:
            break

        problems = "\n".join(final_review.blocking_issues) or "\n".join(
            f"{k}: returncode {v['returncode']}" for k, v in final_checks.items() if v["returncode"] != 0
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
    if not success:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        cli()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(3)
