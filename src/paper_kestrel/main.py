from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

from crewai import Agent, Crew, LLM, Process, Task
from pydantic import BaseModel, Field

from .tools import developer_tools, reviewer_tools
from .jarvis import EMITTER
from .state import RunStore


DeveloperRole = Literal[
    "product_engineer",
    "frontend_lead",
    "frontend_quality",
    "backend_lead",
    "data_platform",
    "solution_architect",
]

CheckName = Literal["full_test", "diff_check", "python_compile", "account_focus"]
Effort = Literal["tiny", "small", "medium", "large"]
ReviewDisposition = Literal["approve", "approve_with_suggestions", "block"]
MemoryScope = Literal[
    "product_ux",
    "engineering",
    "transit_data",
    "security_identity",
    "infrastructure",
    "growth_seo",
]


MEMORY_FILES: dict[str, str] = {
    "product_ux": "PRODUCT-UX.md",
    "engineering": "ENGINEERING.md",
    "transit_data": "TRANSIT-DATA.md",
    "security_identity": "SECURITY-IDENTITY.md",
    "infrastructure": "INFRASTRUCTURE.md",
    "growth_seo": "GROWTH-SEO.md",
}

ROLE_MEMORY_DEFAULTS: dict[str, list[str]] = {
    "delivery_director": [],
    "product_engineer": ["engineering", "product_ux"],
    "solution_architect": ["engineering", "infrastructure"],
    "frontend_lead": ["engineering", "product_ux"],
    "frontend_quality": ["engineering", "product_ux"],
    "backend_lead": ["engineering", "security_identity"],
    "data_platform": ["engineering", "transit_data"],
    "product_growth": ["product_ux", "growth_seo"],
    "ui_ux": ["product_ux"],
    "qa_release": ["engineering"],
}


class WorkItem(BaseModel):
    id: str
    role: DeveloperRole
    objective: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    files_hint: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    effort: Effort = "small"
    max_iterations: int = Field(4, ge=2, le=7)
    budget_usd: float = Field(0.20, ge=0.03, le=0.60)
    optional: bool = False
    memory_scopes: list[MemoryScope] = Field(default_factory=list)


class DispatchPlan(BaseModel):
    summary: str
    risk: Literal["low", "medium", "high"]
    use_solution_architect: bool = False
    use_product_growth: bool = False
    use_ui_ux: bool = False
    work_items: list[WorkItem]
    mandatory_checks: list[CheckName] = Field(default_factory=lambda: ["full_test", "diff_check"])
    master_alignment: list[str] = Field(default_factory=list)
    run_budget_usd: float = Field(0.60, ge=0.03, le=0.75)
    stop_conditions: list[str] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    approved: bool
    disposition: ReviewDisposition
    summary: str
    blocking_issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    needs_owner: bool = False
    repair_role: DeveloperRole = "solution_architect"


class RepairAssignment(BaseModel):
    role: DeveloperRole
    objective: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    effort: Effort = "small"
    max_iterations: int = Field(3, ge=2, le=5)
    budget_usd: float = Field(0.15, ge=0.03, le=0.40)
    memory_scopes: list[MemoryScope] = Field(default_factory=list)


class RepairPlan(BaseModel):
    summary: str
    assignments: list[RepairAssignment] = Field(default_factory=list)


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


def agent_for(role: str, writable: bool = False, max_iter: int = 4) -> Agent:
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
        "product_engineer": (
            "Senior Product Engineer",
            "Implement the smallest coherent full-stack product change. Own product behavior, code, and focused tests.",
            "You understand the whole U.Venice product and avoid fragmented responsibilities.",
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
        max_iter=max(2, min(int(max_iter), 7)),
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
        "product_engineer": "Senior Product Engineer",
        "frontend_lead": "Senior Frontend Engineer",
        "frontend_quality": "Frontend Quality and Accessibility Engineer",
        "backend_lead": "Senior Backend and Integration Engineer",
        "data_platform": "Senior Data and Transit Platform Engineer",
        "solution_architect": "Solution Architect",
    }.get(role, role)


class BudgetStop(RuntimeError):
    pass


def load_master_context(spec_path: Path, spec: str) -> str:
    match = re.search(r"(?im)^Master plan:\s*`?([^\n`]+)`?\s*$", spec)
    if not match:
        raise RuntimeError("Missing mandatory Master plan reference in work order")
    raw = match.group(1).strip()
    work_root = Path(os.environ.get("AGENT_WORKSPACE", "work")).resolve()
    candidate = (work_root / raw).resolve()
    if candidate != work_root and work_root not in candidate.parents:
        raise RuntimeError(f"Master plan reference escapes product workspace: {raw}")
    if not candidate.is_file():
        raise RuntimeError(f"Referenced master plan not found in product workspace: {raw}")
    text = candidate.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise RuntimeError(f"Master plan is empty: {raw}")
    return text[:60000]


def memory_root(spec_path: Path) -> Path:
    repo_root = spec_path.parent.parent if spec_path.parent.name == "orders" else spec_path.parent
    return repo_root / "memory"


def load_memory_file(root: Path, filename: str, limit: int = 18000) -> str:
    path = root / filename
    if not path.is_file():
        return f"[memory missing: {filename}]"
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def load_common_memory(spec_path: Path) -> str:
    root = memory_root(spec_path)
    common = load_memory_file(root, "COMMON.md", 22000)
    decisions = load_memory_file(root, "DECISIONS.md", 12000)
    return f"COMMON PROJECT MEMORY:\n{common}\n\nDURABLE DECISIONS:\n{decisions}"


def resolve_memory_scopes(role: str, explicit: list[str] | None = None) -> list[str]:
    scopes: list[str] = []
    for scope in [*(ROLE_MEMORY_DEFAULTS.get(role, [])), *((explicit or []))]:
        if scope in MEMORY_FILES and scope not in scopes:
            scopes.append(scope)
    return scopes


def load_domain_memory(spec_path: Path, role: str, explicit: list[str] | None = None) -> str:
    root = memory_root(spec_path)
    chunks: list[str] = []
    for scope in resolve_memory_scopes(role, explicit):
        chunks.append(f"DOMAIN MEMORY — {scope}:\n{load_memory_file(root, MEMORY_FILES[scope])}")
    return "\n\n".join(chunks) or "No additional domain memory required."


def load_run_memory(spec_path: Path, scopes: list[str]) -> str:
    root = memory_root(spec_path)
    chunks = [load_common_memory(spec_path)]
    seen: set[str] = set()
    for scope in scopes:
        if scope in MEMORY_FILES and scope not in seen:
            seen.add(scope)
            chunks.append(f"DOMAIN MEMORY — {scope}:\n{load_memory_file(root, MEMORY_FILES[scope])}")
    return "\n\n".join(chunks)


def effective_run_budget(plan: DispatchPlan) -> float:
    soft_cap = min(0.75, float(os.environ.get("MAX_RUN_COST_USD", "0.75")))
    hard_cap = min(0.75, float(os.environ.get("HARD_RUN_COST_USD", "0.75")))
    return max(0.0, min(plan.run_budget_usd, soft_cap, hard_cap))


def remaining_budget(limit: float) -> float:
    return max(0.0, limit - float(getattr(EMITTER, "total_cost", 0.0) or 0.0))


def enforce_budget(limit: float, label: str, *, optional: bool = False, reserve: float = 0.0) -> bool:
    spent = float(getattr(EMITTER, "total_cost", 0.0) or 0.0)
    remaining = max(0.0, limit - spent)
    if optional and remaining <= max(0.08, reserve):
        EMITTER.emit(
            "budget.skipped",
            f"{label}: attività opzionale saltata per rispettare il budget",
            agent="Delivery Director",
            status="done",
            phase="planning",
            details={"spent_usd": round(spent, 4), "remaining_usd": round(remaining, 4), "limit_usd": round(limit, 4)},
        )
        return False
    if spent >= limit:
        raise BudgetStop(f"Run budget exhausted before {label}: spent ${spent:.3f} / limit ${limit:.3f}")
    return True


def emit_budget_result(agent_role: str, planned: float, before: float, limit: float, *, label: str) -> float:
    after = float(getattr(EMITTER, "total_cost", 0.0) or 0.0)
    spent = max(0.0, after - before)
    ratio = spent / planned if planned > 0 else 0.0
    status = "over" if ratio > 1.25 else "ok"
    EMITTER.emit(
        "budget.agent",
        f"{agent_role}: ${spent:.3f} / ${planned:.3f} previsti",
        agent=agent_role,
        status="done",
        phase="planning",
        details={
            "label": label,
            "planned_usd": round(planned, 4),
            "actual_usd": round(spent, 4),
            "ratio": round(ratio, 3),
            "run_limit_usd": round(limit, 4),
            "run_spent_usd": round(after, 4),
            "budget_status": status,
        },
    )
    return spent


def compact_handoff(role: str, summary: str, limit: int = 1200) -> str:
    clean = " ".join(summary.split())
    return f"{role}: {clean[:limit]}"


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


def changed_paths(work: Path) -> list[str]:
    _mark_untracked_for_diff(work)
    p = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "--", ".", ":(exclude)node_modules/**"],
        cwd=work,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    return sorted({line.strip() for line in p.stdout.splitlines() if line.strip()})


def _required_paths_from_spec(spec: str) -> list[str]:
    match = re.search(
        r"(?ims)^##\s+Required source files\s*$\n(.*?)(?=^##\s|\Z)",
        spec,
    )
    if not match:
        return []
    paths: list[str] = []
    for raw in re.findall(r"`([^`\n]+)`", match.group(1)):
        path = raw.strip().strip("/")
        if not path or any(ch in path for ch in "*{}"):
            continue
        if path.startswith(("public.", "auth.", "supabase.")):
            continue
        if "/" in path or path.endswith((".html", ".js", ".cjs", ".css", ".json", ".py", ".php", ".md")):
            paths.append(path)
    return sorted(set(paths))


def candidate_integrity_check(spec: str, work: Path) -> tuple[int, str]:
    issues: list[str] = []

    for path in _required_paths_from_spec(spec):
        if not (work / path).is_file():
            issues.append(f"required source file missing: {path}")

    for path in changed_paths(work):
        target = work / path
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        if path.endswith(".cjs"):
            for ref in re.findall(r"['\"](tests/[A-Za-z0-9_./-]+\.cjs)['\"]", text):
                if not (work / ref).is_file():
                    issues.append(f"{path} references missing test: {ref}")
        if path.endswith(".html"):
            for ref in re.findall(r"(?:src|href)=['\"]([^'\"]+)['\"]", text, flags=re.I):
                clean = ref.split("?", 1)[0].split("#", 1)[0]
                if clean.startswith(("assets/", "js/", "config/", "locales/")) and not (work / clean).is_file():
                    issues.append(f"{path} references missing local asset: {clean}")

    if issues:
        return 1, "CANDIDATE_INTEGRITY_FAILED:\n" + "\n".join(f"- {x}" for x in sorted(set(issues)))
    required = _required_paths_from_spec(spec)
    return 0, (
        "candidate integrity: ok"
        + (f" · required paths verified: {len(required)}" if required else "")
    )


def collect_validation_results(checks: list[str], spec: str, work: Path) -> dict[str, dict]:
    results: dict[str, dict] = {}

    EMITTER.emit(
        "check.started",
        "candidate_integrity: controllo in corso",
        agent="Controller",
        status="checking",
        phase="testing",
        details={"check": "candidate_integrity"},
    )
    rc, out = candidate_integrity_check(spec, work)
    results["candidate_integrity"] = {"returncode": rc, "output": out[-12000:]}
    EMITTER.emit(
        "check.completed",
        f"candidate_integrity: {'ok' if rc == 0 else 'fallito'}",
        agent="Controller",
        status="success" if rc == 0 else "failed",
        phase="testing",
        details={"check": "candidate_integrity", "returncode": rc},
    )

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
        results[check] = {"returncode": rc, "output": out[-12000:]}
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
        results[f"changed_js_test:{test_path}"] = {"returncode": rc, "output": out[-12000:]}
        EMITTER.emit(
            "check.completed",
            f"{test_path}: {'ok' if rc == 0 else 'fallito'}",
            agent="Controller",
            status="success" if rc == 0 else "failed",
            phase="testing",
            details={"check": "changed_js_test", "path": test_path, "returncode": rc},
        )
    return results


def coordinate_repairs(
    spec: str,
    master: str,
    problems: str,
    diff: str,
    run_budget: float,
) -> RepairPlan:
    enforce_budget(run_budget, "repair coordination", optional=False)
    before = float(getattr(EMITTER, "total_cost", 0.0) or 0.0)
    coordinator = agent_for("delivery_director", writable=False, max_iter=2)
    repair_plan = run_single(
        coordinator,
        f"""Create the smallest focused repair plan for this failed candidate.

GOVERNING MASTER PLAN:
{master}

CURRENT OWNER SPECIFICATION:
{spec}

BLOCKING EVIDENCE:
{problems}

CURRENT DIFF:
{diff[:26000]}

Rules:
- Use at most three repair assignments and prefer one when one specialist can resolve all blockers.
- Use each specialist role at most once; group related blockers owned by the same specialist.
- Assign frontend behavior/runtime defects to frontend_lead.
- Assign responsive/accessibility/test-harness/browser-contract defects to frontend_quality.
- Assign auth/API/Supabase/integration defects to backend_lead.
- Assign transit/data-pipeline defects to data_platform.
- Assign genuinely cross-cutting contract/architecture blockers to solution_architect.
- Do not assign an architect merely to restate a blocker another specialist can directly fix.
- Each assignment must set effort, max_iterations and budget_usd to the smallest realistic values.
- Treat max_iterations as a ceiling, not a target.
- Include every concrete repository-fixable blocker, but do not invent new scope.
- Do not ask the owner for information already present in the master/specification.
- Do not change deployment workflows, weaken existing tests, or invent backend APIs.
- Every assignment must have observable acceptance criteria and a targeted check.
""",
        "A minimal structured repair plan grouped by specialist ownership and bounded by cost.",
        RepairPlan,
    )
    emit_budget_result("Delivery Director", 0.08, before, run_budget, label="repair coordination")
    repair_plan.assignments = repair_plan.assignments[:3]

    if not repair_plan.assignments:
        repair_plan.assignments = [
            RepairAssignment(
                role="solution_architect",
                objective="Resolve the blocking evidence without broadening scope.\n" + problems,
                acceptance_criteria=["Blocking evidence is resolved", "Targeted checks pass", "No unrelated changes"],
                effort="small",
                max_iterations=3,
                budget_usd=0.12,
            )
        ]

    available = max(0.0, remaining_budget(run_budget) - 0.08)
    bounded: list[RepairAssignment] = []
    for assignment in repair_plan.assignments:
        if available < 0.05:
            break
        assignment.max_iterations = max(2, min(assignment.max_iterations, 5))
        assignment.budget_usd = max(0.03, min(assignment.budget_usd, 0.30, available))
        bounded.append(assignment)
        available -= assignment.budget_usd
    repair_plan.assignments = bounded
    return repair_plan


def execute_repair_plan(
    repair_plan: RepairPlan,
    round_no: int,
    spec_path: Path,
    spec: str,
    master: str,
    advice: str,
    handoffs: list[str],
    run_budget: float,
    event_log: list[dict],
) -> bool:
    seen: set[str] = set()
    changed_any = False
    for index, assignment in enumerate(repair_plan.assignments, start=1):
        if assignment.role in seen:
            continue
        seen.add(assignment.role)
        if not enforce_budget(run_budget, f"repair {round_no}/{assignment.role}", optional=False):
            break
        EMITTER.emit(
            "handoff",
            f"Repair #{round_no} → {_role_title(assignment.role)}: {assignment.objective}",
            agent="Controller",
            status="done",
            phase="repair",
            details={
                "repair_round": round_no,
                "to": assignment.role,
                "assignment": index,
                "effort": assignment.effort,
                "max_iterations": assignment.max_iterations,
                "budget_usd": assignment.budget_usd,
            },
        )
        item = WorkItem(
            id=f"repair-{round_no}-{index}",
            role=assignment.role,
            objective=assignment.objective,
            acceptance_criteria=assignment.acceptance_criteria or [
                "Blocking evidence is resolved",
                "Targeted checks pass",
                "No unrelated changes",
            ],
            effort=assignment.effort,
            max_iterations=assignment.max_iterations,
            budget_usd=assignment.budget_usd,
            memory_scopes=assignment.memory_scopes,
        )
        before_diff = git_diff(Path(os.environ["AGENT_WORKSPACE"]))
        summary = execute_work_item(item, spec_path, spec, master, advice, handoffs, run_budget)
        after_diff = git_diff(Path(os.environ["AGENT_WORKSPACE"]))
        changed = after_diff != before_diff
        changed_any = changed_any or changed
        handoffs.append(compact_handoff(_role_title(assignment.role), summary))
        event_log.append(
            {
                "stage": "repair",
                "round": round_no,
                "role": assignment.role,
                "changed": changed,
                "summary": summary[-6000:],
            }
        )
    return changed_any


def execute_work_item(
    item: WorkItem,
    spec_path: Path,
    spec: str,
    master: str,
    advice: str,
    handoffs: list[str],
    run_budget: float,
) -> str:
    label = f"{item.id} / {_role_title(item.role)}"
    if not enforce_budget(run_budget, label, optional=item.optional, reserve=0.18):
        return f"SKIPPED_OPTIONAL: {label}"

    before = float(getattr(EMITTER, "total_cost", 0.0) or 0.0)
    worker = agent_for(item.role, writable=True, max_iter=item.max_iterations)
    board = "\n".join(f"- {x}" for x in handoffs[-8:]) or "- No prior team handoffs."
    project_memory = load_common_memory(spec_path)
    domain_memory = load_domain_memory(spec_path, item.role, item.memory_scopes)
    store = getattr(EMITTER, "run_store", None)
    workspace = str(Path(os.environ["AGENT_WORKSPACE"]).resolve())
    if store is None:
        raise RuntimeError("Write operations require a durable RunStore")
    store.acquire_writer(workspace, item.id)
    os.environ["ACTIVE_WORK_ITEM"] = item.id
    try:
        output = run_single(
        worker,
        f"""GOVERNING MASTER PLAN:
{master}

CURRENT OWNER SPECIFICATION:
{spec}

PERSISTENT PROJECT MEMORY:
{project_memory}

RELEVANT DOMAIN MEMORY:
{domain_memory}

WORK ITEM:
{item.model_dump_json(indent=2)}

SHARED ADVISORY CONTEXT:
{advice}

TEAM HANDOFF BOARD:
{board}

OPERATING CONTRACT:
- Your iteration limit is a ceiling, not a target. Stop as soon as acceptance criteria are satisfied.
- Your planned spend is ${item.budget_usd:.2f}; minimize tool/LLM turns and reread only what changed.
- Inspect existing code first, then make the smallest coherent implementation.
- Reuse decisions and facts already present on the handoff board; do not redo another specialist's analysis unless evidence contradicts it.
- Run the smallest targeted check that proves your change before finishing.
- Do not edit GitHub workflows, deployment credentials, generated runtime data or unrelated features.
- Preserve IT/EN/FR/DE parity for user-facing strings where relevant.
- If the requested work is already satisfied, report that and stop without creating churn.
- If blocked by a genuine external decision or unavailable credential, stop and state exactly what is needed; do not invent APIs.
- Finish with a concise handoff: what changed, checks run, residual blockers, and what the next role needs to know.""",
        "Implemented code changes plus a concise team handoff and tests run.",
        )
    finally:
        os.environ.pop("ACTIVE_WORK_ITEM", None)
        store.release_writer(workspace, item.id)
    emit_budget_result(_role_title(item.role), item.budget_usd, before, run_budget, label=item.id)
    EMITTER.emit(
        "handoff",
        compact_handoff(_role_title(item.role), output, 620),
        agent=_role_title(item.role),
        status="done",
        phase="implementation",
        details={"to": "Team", "work_item": item.id, "kind": "implementation"},
    )
    return output


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
    master = load_master_context(spec_path, spec)
    common_memory = load_common_memory(spec_path)
    EMITTER.set_spec(args.spec)
    run_id = os.environ.get("GITHUB_RUN_ID", "local") + ":" + os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    store = RunStore(Path(args.report_dir) / "run-state.sqlite3", run_id)
    store.initialize(spec=spec, master=master, cap=0.75, milestone=os.environ.get("MILESTONE_KEY", "unassigned"))
    EMITTER.run_store = store
    os.environ["RUN_STATE_DB"] = str(store.path.resolve())
    os.environ["RUN_STATE_ID"] = store.run_id
    store.transition("000:preflight", "PREFLIGHT", {"spec_path":str(spec_path)})
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

    director = agent_for("delivery_director", writable=False, max_iter=3)
    plan = run_single(
        director,
        f"""Read the governing master plan and the owner-approved current specification, then create the smallest execution plan that advances only the current milestone.

GOVERNING MASTER PLAN:
{master}

CURRENT OWNER SPECIFICATION:
{spec}

PERSISTENT COMMON PROJECT MEMORY:
{common_memory}

Rules:
- The master plan is authoritative for sequencing, boundaries and stopping points. The current specification may narrow it but must not silently broaden it.
- Maximum three work items, prefer ONE product_engineer writer. Only add specialist work when truly independent.
- Use the smallest set of specialists necessary; do not create work merely to involve every role.
- Order items so dependencies are implemented first.
- For every work item assign effort, max_iterations and budget_usd proportionate to the task.
- For every work item assign only the memory_scopes materially relevant to that work. Do not load every domain by default.
- Typical guidance: tiny=2 iterations/$0.05-$0.10, small=3-4/$0.10-$0.20, medium=4-5/$0.20-$0.35, large=5-7/$0.35-$0.55.
- Set optional=true for nice-to-have analysis that may be skipped if budget is tight.
- Set run_budget_usd to the lowest realistic total budget; never exceed $0.75 without a separate owner authorization.
- Define stop_conditions that tell the controller when the milestone is good enough and further work has low marginal value.
- Frontend, backend and normal product implementation belong to product_engineer. Other coding roles are exceptional.
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
    plan.work_items = plan.work_items[:3]
    run_budget = effective_run_budget(plan)
    event_log.append({"stage": "plan", "data": plan.model_dump(), "effective_run_budget_usd": run_budget})
    store.transition("010:plan", "PLANNED", {"work_items": [i.id for i in plan.work_items], "budget": run_budget})
    EMITTER.emit(
        "plan.created",
        f"Piano creato: {len(plan.work_items)} work item · rischio {plan.risk}",
        agent="Delivery Director",
        status="done",
        phase="planning",
        summary=plan.summary,
        details={
            "work_items": len(plan.work_items),
            "risk": plan.risk,
            "run_budget_usd": round(run_budget, 3),
            "stop_conditions": plan.stop_conditions,
            "master_alignment": plan.master_alignment,
        },
    )

    advisor_specs: list[tuple[str, str, float]] = []
    planned_roles = {item.role for item in plan.work_items}
    if plan.use_solution_architect and "solution_architect" not in planned_roles:
        advisor_specs.append((
            "solution_architect",
            "Review architecture boundaries, dependencies and regression risks. Return only constraints implementers need.",
            0.10,
        ))
    if plan.use_product_growth:
        advisor_specs.append((
            "product_growth",
            "Review product value, analytics/consent and conversion implications. Return only actionable constraints.",
            0.05,
        ))
    if plan.use_ui_ux:
        advisor_specs.append((
            "ui_ux",
            "Review information hierarchy, responsive interaction and visual constraints. Return only actionable implementation guidance.",
            0.08,
        ))

    def run_advisor(role: str, instruction: str, planned_cost: float) -> str:
        if not enforce_budget(run_budget, f"advisor {role}", optional=True, reserve=0.30):
            return ""
        before = float(getattr(EMITTER, "total_cost", 0.0) or 0.0)
        advisor_memory = load_domain_memory(spec_path, role)
        output = run_single(
            agent_for(role, writable=False, max_iter=2),
            f"""GOVERNING MASTER PLAN:
{master}

CURRENT OWNER SPECIFICATION:
{spec}

PERSISTENT COMMON PROJECT MEMORY:
{common_memory}

RELEVANT DOMAIN MEMORY:
{advisor_memory}

ADVISORY REQUEST:
{instruction}

Do not redesign the whole solution. Do not write code. Be concise and surface only constraints or risks that materially affect implementation.""",
            "A concise advisory note for the implementation team.",
        )
        emit_budget_result(_role_title(role), planned_cost, before, run_budget, label="advisor")
        EMITTER.emit(
            "handoff",
            compact_handoff(_role_title(role), output, 520),
            agent=_role_title(role),
            status="done",
            phase="architecture",
            details={"to": "Team", "kind": "advisor"},
        )
        return f"{_role_title(role)}: {output}"

    advice_parts: list[str] = []
    if advisor_specs:
        with ThreadPoolExecutor(max_workers=min(2, len(advisor_specs))) as pool:
            futures = {
                pool.submit(run_advisor, role, instruction, cost): role
                for role, instruction, cost in advisor_specs
            }
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        advice_parts.append(result)
                except BudgetStop:
                    continue
    advice = "\n\n--- ADVISOR ---\n".join(advice_parts) or "No additional advisory review requested."
    team_handoffs: list[str] = [compact_handoff("Advisor board", x, 1000) for x in advice_parts]

    completed: list[str] = []
    for item in plan.work_items:
        EMITTER.emit(
            "handoff",
            f"Director → {_role_title(item.role)}: {item.objective}",
            agent="Delivery Director",
            status="done",
            phase="implementation",
            details={
                "work_item": item.id,
                "to": item.role,
                "effort": item.effort,
                "max_iterations": item.max_iterations,
                "budget_usd": item.budget_usd,
            },
        )
        missing = [d for d in item.depends_on if d not in completed]
        if missing:
            raise RuntimeError(f"Invalid plan: {item.id} depends on unfinished {missing}")
        try:
            summary = execute_work_item(item, spec_path, spec, master, advice, team_handoffs, run_budget)
            event_log.append({"stage": "implementation", "item": item.id, "role": item.role, "summary": summary[-6000:]})
            team_handoffs.append(compact_handoff(_role_title(item.role), summary))
            EMITTER.emit(
                "agent.report",
                summary[-640:],
                agent=_role_title(item.role),
                status="done",
                phase="implementation",
                details={"work_item": item.id},
            )
            completed.append(item.id)
            store.transition("work:" + item.id, "EXECUTING", {"completed": item.id})
        except BudgetStop:
            raise
        except Exception as exc:
            event_log.append({"stage": "blocked", "item": item.id, "role": item.role, "error": str(exc)})
            raise RuntimeError(f"Work item {item.id} failed; no automatic architect fallback") from exc

    max_repairs = min(int(os.environ.get("MAX_REPAIR_ROUNDS", "1")), 1)
    allowed_checks: set[str] = {"full_test", "diff_check", "python_compile", "account_focus"}
    checks = [check for check in dict.fromkeys([*plan.mandatory_checks, "full_test", "diff_check"]) if check in allowed_checks]
    final_review = None
    final_checks: dict[str, dict] = {}
    stop_reason = "not_completed"
    last_failure_signature: str | None = None

    for round_no in range(max_repairs + 1):
        if round_no > 0 and remaining_budget(run_budget) < 0.08:
            final_review = ReviewDecision(
                approved=False,
                disposition="block",
                summary="Stopped because the remaining run budget is too small for another safe repair/review cycle.",
                blocking_issues=["Run cost budget exhausted before convergence."],
                suggestions=[],
                needs_owner=False,
                repair_role="solution_architect",
            )
            stop_reason = "budget_exhausted"
            break

        final_checks = collect_validation_results(checks, spec, work)
        store.transition("validation:" + str(round_no), "VALIDATING",
                         {"checks": {k: v["returncode"] for k,v in final_checks.items()}})
        diff = git_diff(work)
        checks_green = all(v["returncode"] == 0 for v in final_checks.values())

        if not checks_green:
            failed_items = {
                name: {
                    "returncode": result["returncode"],
                    "tail": result["output"][-1800:],
                }
                for name, result in final_checks.items()
                if result["returncode"] != 0
            }
            failed = "\n\n".join(
                f"{name}: returncode {result['returncode']}\n{result['tail']}"
                for name, result in failed_items.items()
            )
            signature = json.dumps(failed_items, sort_keys=True)
            event_log.append({"stage": "validation_failed", "round": round_no, "checks": final_checks})

            if signature == last_failure_signature:
                final_review = ReviewDecision(
                    approved=False,
                    disposition="block",
                    summary="Stopped because the same deterministic failures persisted after a repair cycle.",
                    blocking_issues=list(failed_items),
                    suggestions=[],
                    needs_owner=False,
                    repair_role="solution_architect",
                )
                stop_reason = "stalled_same_failure"
                break
            last_failure_signature = signature

            if round_no >= max_repairs or remaining_budget(run_budget) < 0.16:
                final_review = ReviewDecision(
                    approved=False,
                    disposition="block",
                    summary="Deterministic validation still fails and the bounded repair budget is exhausted.",
                    blocking_issues=list(failed_items),
                    suggestions=[],
                    needs_owner=False,
                    repair_role="solution_architect",
                )
                stop_reason = "repair_budget_exhausted"
                break

            try:
                repair_plan = coordinate_repairs(
                    spec,
                    master,
                    "DETERMINISTIC VALIDATION FAILURES:\n" + failed,
                    diff,
                    run_budget,
                )
            except BudgetStop as exc:
                final_review = ReviewDecision(
                    approved=False,
                    disposition="block",
                    summary=str(exc),
                    blocking_issues=list(failed_items),
                    suggestions=[],
                    needs_owner=False,
                    repair_role="solution_architect",
                )
                stop_reason = "budget_exhausted"
                break

            event_log.append(
                {
                    "stage": "repair_plan",
                    "round": round_no + 1,
                    "source": "validation",
                    "data": repair_plan.model_dump(),
                }
            )
            if not repair_plan.assignments:
                final_review = ReviewDecision(
                    approved=False,
                    disposition="block",
                    summary="Stopped because no safe repair assignment fits the remaining run budget.",
                    blocking_issues=list(failed_items),
                    suggestions=[],
                    needs_owner=False,
                    repair_role="solution_architect",
                )
                stop_reason = "budget_exhausted"
                break

            changed = execute_repair_plan(
                repair_plan,
                round_no + 1,
                spec_path,
                spec,
                master,
                advice,
                team_handoffs,
                run_budget,
                event_log,
            )
            if not changed:
                EMITTER.emit(
                    "repair.stalled",
                    f"Repair #{round_no + 1}: nessuna modifica materiale prodotta",
                    agent="Controller",
                    status="blocked",
                    phase="repair",
                    details={"round": round_no + 1, "source": "validation"},
                )
                final_review = ReviewDecision(
                    approved=False,
                    disposition="block",
                    summary="Stopped because the repair cycle produced no material change.",
                    blocking_issues=list(failed_items),
                    suggestions=[],
                    needs_owner=False,
                    repair_role="solution_architect",
                )
                stop_reason = "stalled_no_progress"
                break
            continue

        last_failure_signature = None
        enforce_budget(run_budget, "independent QA review", optional=False)
        before_review = float(getattr(EMITTER, "total_cost", 0.0) or 0.0)
        review_scopes: list[str] = []
        for planned_item in plan.work_items:
            for scope in resolve_memory_scopes(planned_item.role, planned_item.memory_scopes):
                if scope not in review_scopes:
                    review_scopes.append(scope)
        review_memory = load_run_memory(spec_path, review_scopes)
        reviewer = agent_for("qa_release", writable=False, max_iter=3)
        final_review = run_single(
            reviewer,
            f"""Independently review this implementation against the master plan and current owner specification.

GOVERNING MASTER PLAN:
{master}

CURRENT OWNER SPECIFICATION:
{spec}

PERSISTENT PROJECT MEMORY FOR THIS RUN:
{review_memory}

DISPATCH PLAN:
{plan.model_dump_json(indent=2)}

CHECK RESULTS:
{json.dumps(final_checks, indent=2)}

CURRENT DIFF:
{diff}

Release-review rules:
- Return one disposition: approve, approve_with_suggestions, or block.
- approve: acceptance criteria and safety boundaries are satisfied with no material follow-up.
- approve_with_suggestions: candidate is safe and complete enough to deliver; suggestions are useful but MUST NOT trigger another repair cycle.
- block: only for concrete evidence of an unmet acceptance criterion, regression, security/privacy problem, broken required test, or unsafe scope violation.
- Put improvements that are not release blockers in suggestions, not blocking_issues.
- Set needs_owner=true only when a genuine product/priority/credential/legal decision cannot be resolved from the master/spec/repository.
- Do not invent release gates, manual browser sessions, live deployment checks, production configuration requirements, or external evidence not required by the owner specification.
- If responsive/accessibility behavior is explicitly covered by deterministic contract tests and code inspection, do not additionally require unavailable manual iOS/Safari evidence unless explicitly named as a hard gate.
- Treat owner-declared existing backend/schema/config contracts as contracts; do not block merely because private production configuration is absent from the public coding workspace.
- The pull request is intentionally opened only AFTER approval; do not require a PR to exist yet.
- A full_test result with returncode 0 and BASELINE_EQUIVALENT_FAILURE is an authoritative passed non-regression result.
- Do not block on stylistic preferences or speculative future enhancements.
- Be self-critical but proportionate: the goal is a safe, useful increment, not theoretical perfection.
""",
            "A structured release decision with disposition, blockers, suggestions and owner-decision flag.",
            ReviewDecision,
        )
        emit_budget_result("QA, Security and Release Reviewer", 0.12, before_review, run_budget, label="release review")

        if final_review.disposition in {"approve", "approve_with_suggestions"}:
            final_review.approved = True
        else:
            final_review.approved = False

        event_log.append({"stage": "review", "round": round_no, "data": final_review.model_dump()})
        EMITTER.emit(
            "review.decision",
            final_review.summary,
            agent="QA, Security and Release Reviewer",
            status="approved" if final_review.approved else "blocked",
            phase="qa",
            details={
                "round": round_no,
                "disposition": final_review.disposition,
                "blocking_issues": len(final_review.blocking_issues),
                "suggestions": final_review.suggestions,
                "needs_owner": final_review.needs_owner,
            },
        )

        if final_review.approved:
            stop_reason = final_review.disposition
            break
        if final_review.needs_owner:
            stop_reason = "owner_decision_required"
            break
        if round_no >= max_repairs or remaining_budget(run_budget) < 0.16:
            stop_reason = "review_repair_budget_exhausted"
            break

        problems = "\n".join(final_review.blocking_issues) or final_review.summary
        review_signature = "\n".join(sorted(final_review.blocking_issues))
        if review_signature and review_signature == last_failure_signature:
            stop_reason = "stalled_same_review"
            break
        last_failure_signature = review_signature or final_review.summary

        try:
            repair_plan = coordinate_repairs(
                spec,
                master,
                "QA REVIEW BLOCKERS:\n" + problems,
                diff,
                run_budget,
            )
        except BudgetStop:
            stop_reason = "budget_exhausted"
            break

        event_log.append(
            {
                "stage": "repair_plan",
                "round": round_no + 1,
                "source": "qa",
                "data": repair_plan.model_dump(),
            }
        )
        changed = execute_repair_plan(
            repair_plan,
            round_no + 1,
            spec_path,
            spec,
            master,
            advice,
            team_handoffs,
            run_budget,
            event_log,
        )
        if not changed:
            EMITTER.emit(
                "repair.stalled",
                f"Repair #{round_no + 1}: nessuna modifica materiale prodotta",
                agent="Controller",
                status="blocked",
                phase="repair",
                details={"round": round_no + 1, "source": "qa"},
            )
            stop_reason = "stalled_no_progress"
            break

    success = bool(
        final_review
        and final_review.disposition in {"approve", "approve_with_suggestions"}
        and all(v["returncode"] == 0 for v in final_checks.values())
    )
    actual_cost = float(getattr(EMITTER, "total_cost", 0.0) or 0.0)
    report = {
        "success": success,
        "stop_reason": stop_reason,
        "planned_run_budget_usd": run_budget,
        "actual_cost_usd": round(actual_cost, 6),
        "plan": plan.model_dump(),
        "checks": final_checks,
        "review": final_review.model_dump() if final_review else None,
        "events": event_log,
    }
    store.transition("900:finish", "ACCEPTED" if success else "BLOCKED", {"reason": stop_reason})
    (report_dir / "agent-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    suggestions_md = ""
    if final_review and final_review.suggestions:
        suggestions_md = "\n\nSuggestions (non-blocking):\n" + "\n".join(f"- {x}" for x in final_review.suggestions)
    (report_dir / "agent-report.md").write_text(
        "# Automation report\n\n"
        + f"Success: **{success}**\n\n"
        + f"Stop reason: **{stop_reason}**\n\n"
        + f"Budget: **USD {run_budget:.3f} planned / USD {actual_cost:.3f} actual**\n\n"
        + f"Plan: {plan.summary}\n\n"
        + "Review: "
        + (final_review.summary if final_review else "not completed")
        + suggestions_md
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
            need_owner=bool(final_review.needs_owner) if final_review else False,
            summary=(final_review.summary if final_review else "Run non approvato") + f" · stop={stop_reason}",
            finished=True,
            event_key="run:failed",
        )
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        cli()
    except SystemExit:
        raise
    except BudgetStop as exc:
        EMITTER.emit(
            "run.stopped",
            str(exc),
            status="failure",
            phase="planning",
            need_owner=False,
            summary=str(exc),
            finished=True,
            event_key="run:budget-stop",
        )
        print(str(exc))
        raise SystemExit(4)
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
