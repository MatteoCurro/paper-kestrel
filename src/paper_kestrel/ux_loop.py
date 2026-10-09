"""One bounded post-implementation product critique/revision round.

The critic reads the candidate diff independently, gives actionable findings,
and the implementation owner gets exactly one targeted revision opportunity.
Release QA remains separate and authoritative. No endless agent discussion.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Literal
from pydantic import BaseModel, Field

class UXCritique(BaseModel):
    disposition: Literal["approve", "revise"]
    summary: str
    findings: list[str] = Field(default_factory=list)
    acceptance_tests: list[str] = Field(default_factory=list)

@dataclass(frozen=True)
class UXOutcome:
    disposition: str
    feedback: tuple[str, ...]
    revised: bool
    engineer_handoff: str = ""

def requires_ux_review(paths: list[str]) -> bool:
    return any(p.lower().endswith((".html",".css",".jsx",".tsx",".vue",".svelte"))
               or "/ui/" in p.lower() or "/components/" in p.lower()
               for p in paths)

def critique_and_revise(
    review: Callable[[], UXCritique],
    revise: Callable[[tuple[str,...],tuple[str,...]], str],
) -> UXOutcome:
    verdict = review()
    if verdict.disposition == "approve":
        return UXOutcome("approve",tuple(verdict.findings),False)
    actionable = tuple(x.strip() for x in verdict.findings if x.strip())
    if not actionable:
        raise ValueError("UX revision requested without actionable findings")
    tests = tuple(x.strip() for x in verdict.acceptance_tests if x.strip())
    summary = revise(actionable,tests)
    if not summary.strip():
        raise RuntimeError("UX revision produced no engineering handoff")
    return UXOutcome("revise",actionable,True,summary)
