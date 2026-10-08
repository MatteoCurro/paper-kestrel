"""Fail-closed checkpoints for costly or workspace-mutating CrewAI operations.

A completed step can be replayed only when its input fingerprint matches, and
(for write steps) when its candidate workspace still has the same diff.
An interrupted step has UNKNOWN side effects and MUST NOT be executed again
without separate reconciliation. This is a safety boundary, not a magic resume.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .state import RunStore, utc_now


class RecoveryBlocked(RuntimeError):
    """A prior attempt might already have incurred cost or modified files."""


def fingerprint(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class CheckpointJournal:
    def __init__(self, store: RunStore):
        self.store = store
        with store.tx():
            store.db.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints(
              run_id TEXT NOT NULL,
              step_key TEXT NOT NULL,
              input_sha TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('STARTED','COMPLETED','UNCERTAIN')),
              result_json TEXT,
              candidate_sha TEXT,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(run_id,step_key)
            )""")

    def begin(self, step_key: str, inputs: Any, *, candidate_sha: str | None = None) -> Any | None:
        """Return previously committed output or claim a brand-new step.

        If candidate_sha is supplied it must match the prior committed diff;
        never skip work from a restored ledger against a clean workspace.
        """
        sha = fingerprint(inputs)
        with self.store.tx():
            row = self.store.db.execute(
                """SELECT input_sha,status,result_json,candidate_sha FROM checkpoints
                   WHERE run_id=? AND step_key=?""",
                (self.store.run_id, step_key),
            ).fetchone()
            if row is not None:
                stored_sha, status, output, stored_candidate = row
                if stored_sha != sha:
                    raise RecoveryBlocked(f"Checkpoint input drift: {step_key}")
                if status != "COMPLETED":
                    raise RecoveryBlocked(f"Interrupted/uncertain step requires reconciliation: {step_key}")
                if stored_candidate is not None and stored_candidate != candidate_sha:
                    raise RecoveryBlocked(f"Restored candidate does not match checkpoint: {step_key}")
                return json.loads(output)
            self.store.db.execute(
                "INSERT INTO checkpoints VALUES(?,?,?,'STARTED',NULL,NULL,?)",
                (self.store.run_id, step_key, sha, utc_now()),
            )
        return None

    def complete(self, step_key: str, inputs: Any, result: Any, *, candidate_sha: str | None = None) -> None:
        sha = fingerprint(inputs)
        output = json.dumps(result, sort_keys=True, ensure_ascii=False)
        with self.store.tx():
            row = self.store.db.execute(
                "SELECT input_sha,status FROM checkpoints WHERE run_id=? AND step_key=?",
                (self.store.run_id,step_key),
            ).fetchone()
            if row != (sha, "STARTED"):
                raise RecoveryBlocked(f"Cannot commit unclaimed, changed or already finished step: {step_key}")
            self.store.db.execute(
                """UPDATE checkpoints SET status='COMPLETED',result_json=?,candidate_sha=?,
                   updated_at=? WHERE run_id=? AND step_key=?""",
                (output,candidate_sha,utc_now(),self.store.run_id,step_key),
            )

    def uncertain(self, step_key: str) -> None:
        with self.store.tx():
            self.store.db.execute(
                """UPDATE checkpoints SET status='UNCERTAIN',updated_at=?
                   WHERE run_id=? AND step_key=? AND status='STARTED'""",
                (utc_now(),self.store.run_id,step_key),
            )
