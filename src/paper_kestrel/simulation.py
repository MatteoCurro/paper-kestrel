"""Zero-cost integration rehearsal using real transactional primitives.

The model roles are deterministic stubs. This proves contract sequencing,
exclusive file writes, bounded UX feedback, checkpoint behavior, independent
review and outbox ack semantics; it does NOT prove model quality or provider
billing. It never calls a provider or deploys anything.
"""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from unittest.mock import patch

from .recovery import CheckpointJournal, RecoveryBlocked
from .state import RunStore
from .tools import WriteFileTool
from .ux_loop import UXCritique, critique_and_revise
from .jarvis import JarvisEmitter

@dataclass
class RehearsalReport:
    scenario: str
    steps: list[str]
    accepted: bool
    blocked_on_crash: bool
    delivered_events: int
    pending_events: int

def rehearse(scenario: str = "ux_revision") -> RehearsalReport:
    if scenario not in {"ux_revision","approved","crash","review_block"}:
        raise ValueError("unknown simulation scenario")
    with tempfile.TemporaryDirectory(prefix="crew-tsand-rehearsal-") as temp:
        root = Path(temp)/"workspace"
        root.mkdir()
        state = Path(temp)/"ledger.sqlite"
        store = RunStore(state, "sim:1")
        store.initialize(spec="simulation-spec",master="simulation-master",
                         cap=.75,milestone="TSAND-SIM")
        journal = CheckpointJournal(store)
        events: list[dict] = []
        emitter = JarvisEmitter()
        emitter.enabled = False
        emitter.run_id = "1"
        emitter.attempt = "1"
        emitter.run_store = store
        steps = ["manager:plan"]
        store.transition("plan","PLANNED",{"work_items":1})
        env = {
            "AGENT_WORKSPACE":str(root),
            "RUN_STATE_DB":str(state),
            "RUN_STATE_ID":"sim:1",
            "ACTIVE_WORK_ITEM":"task1",
        }
        blocked = False
        accepted = False
        with patch.dict(os.environ, env):
            store.acquire_writer(str(root.resolve()), "task1")
            journal.begin("work:task1", {"objective":"Create accessible form"})
            try:
                WriteFileTool()._run(
                    path="account.html",
                    content="<form><input aria-label='Email'></form>",
                )
                steps.append("engineer:write")
                if scenario == "crash":
                    journal.uncertain("work:task1")
                    # Another runner sees the same committed journal, never repeats.
                else:
                    digest = hashlib.sha256((root/"account.html").read_bytes()).hexdigest()
                    journal.complete("work:task1",{"objective":"Create accessible form"},
                                     {"summary":"Initial form"},candidate_sha=digest)
            finally:
                store.release_writer(str(root.resolve()),"task1")
            if scenario == "crash":
                reopened = RunStore(state,"sim:1")
                try:
                    CheckpointJournal(reopened).begin(
                        "work:task1",{"objective":"Create accessible form"})
                except RecoveryBlocked:
                    blocked=True
                    steps.append("recovery:blocked")
                finally:
                    reopened.db.close()
            else:
                def review():
                    steps.append("ux:review")
                    if scenario == "ux_revision":
                        return UXCritique(
                            disposition="revise",summary="Missing submit",
                            findings=["Submit is missing from account form"],
                            acceptance_tests=["Accessible submit is present"])
                    return UXCritique(disposition="approve",summary="Usable")
                def revise(findings,checks):
                    steps.append("engineer:revision")
                    with patch.dict(os.environ,{"ACTIVE_WORK_ITEM":"ux-revision-1"}):
                        store.acquire_writer(str(root.resolve()),"ux-revision-1")
                        try:
                            WriteFileTool()._run(
                                path="account.html",
                                content="<form><input aria-label='Email'>"
                                        "<button type='submit'>Send</button></form>",
                            )
                        finally:
                            store.release_writer(str(root.resolve()),"ux-revision-1")
                    return "Added accessible submit; target verified"
                outcome = critique_and_revise(review,revise)
                assert outcome.revised == (scenario=="ux_revision")
                steps.append("reviewer:independent")
                accepted = scenario != "review_block" and (
                    "<button" in (root/"account.html").read_text()
                    or scenario=="approved")
                store.transition("finish","ACCEPTED" if accepted else "BLOCKED",
                                 {"simulation":True,"ux_revision":outcome.revised})
        emitter.enabled=True
        emitter._post=lambda msg: events.append(msg) or True
        delivered=emitter.flush_outbox()
        pending=len(store.pending_outbox())
        store.db.close()
        return RehearsalReport(scenario,steps,accepted,blocked,delivered,pending)

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--scenario",choices=["ux_revision","approved","crash","review_block"],
                        default="ux_revision")
    args=parser.parse_args()
    report=rehearse(args.scenario)
    print(json.dumps(asdict(report),sort_keys=True))
    if (args.scenario=="crash" and not report.blocked_on_crash) or (
        args.scenario!="crash" and report.pending_events != 0):
        raise SystemExit(1)

if __name__=="__main__":
    main()
