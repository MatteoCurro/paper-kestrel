"""Durable SQLite state for the CrewAI orchestrator.

State transitions, cost reservations and the outbox share the same ACID transaction.
The Git workspace remains an isolated candidate; external side effects require
idempotency by consumers and are not themselves SQLite transactions.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self, path: str | Path, run_id: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(
          run_id TEXT PRIMARY KEY, status TEXT NOT NULL,
          spec_sha TEXT NOT NULL, master_sha TEXT NOT NULL,
          run_cap REAL NOT NULL, milestone_key TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transitions(
          run_id TEXT NOT NULL, step_key TEXT NOT NULL,
          state TEXT NOT NULL, payload TEXT NOT NULL,
          occurred_at TEXT NOT NULL, PRIMARY KEY(run_id,step_key)
        );
        CREATE TABLE IF NOT EXISTS reservations(
          reservation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
          amount REAL NOT NULL, settled INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS costs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL, amount REAL NOT NULL,
          category TEXT NOT NULL, occurred_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS milestones(
          key TEXT PRIMARY KEY, spent REAL NOT NULL DEFAULT 0,
          reserved REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS leases(
          workspace TEXT PRIMARY KEY, run_id TEXT NOT NULL,
          work_item TEXT NOT NULL, acquired_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS outbox(
          event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
          payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        """)

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def initialize(self, *, spec: str, master: str, cap: float, milestone: str) -> None:
        now = utc_now()
        spec_sha = hashlib.sha256(spec.encode()).hexdigest()
        master_sha = hashlib.sha256(master.encode()).hexdigest()
        with self.tx():
            old = self.db.execute("SELECT spec_sha,master_sha,run_cap,milestone_key FROM runs WHERE run_id=?", (self.run_id,)).fetchone()
            if old and (old[0] != spec_sha or old[1] != master_sha or
                        old[2] != cap or old[3] != milestone):
                raise ValueError("Resume refused: specification, master, cap or milestone changed")
            self.db.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?,?,?,?)",
                            (self.run_id,"PREFLIGHT",spec_sha,master_sha,cap,milestone,now,now))
            self.db.execute("INSERT OR IGNORE INTO milestones(key) VALUES(?)", (milestone,))

    def transition(self, step_key: str, state: str, payload: dict | None = None) -> bool:
        body = json.dumps(payload or {},sort_keys=True)
        now = utc_now()
        with self.tx():
            old = self.db.execute("SELECT state,payload FROM transitions WHERE run_id=? AND step_key=?",
                                  (self.run_id,step_key)).fetchone()
            if old:
                if old != (state,body):
                    raise ValueError(f"Conflicting transition: {step_key}")
                return False
            self.db.execute("INSERT INTO transitions VALUES(?,?,?,?,?)",
                            (self.run_id,step_key,state,body,now))
            self.db.execute("UPDATE runs SET status=?,updated_at=? WHERE run_id=?",
                            (state,now,self.run_id))
            event_id = f"{self.run_id}:{step_key}"
            self.db.execute("INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?)",
                            (event_id,self.run_id,json.dumps({"event_key":event_id,"state":state,"payload":payload or {}}),0,now))
        return True

    def reserve(self, amount: float, *, run_cap: float, milestone_cap: float, milestone: str, reservation_id: str) -> None:
        if amount <= 0 or not reservation_id or not milestone:
            raise ValueError("Positive reservation, ID and milestone required")
        with self.tx():
            run = self.db.execute("SELECT run_cap,milestone_key FROM runs WHERE run_id=?", (self.run_id,)).fetchone()
            if not run or run[1] != milestone or run_cap > run[0] + 1e-9:
                raise ValueError("Uninitialized run, mismatched milestone or excessive cap")
            if self.db.execute("SELECT 1 FROM reservations WHERE reservation_id=?", (reservation_id,)).fetchone():
                raise ValueError("Reservation already exists")
            spent = self.db.execute("SELECT COALESCE(SUM(amount),0) FROM costs WHERE run_id=?", (self.run_id,)).fetchone()[0]
            own_reserved = self.db.execute("SELECT COALESCE(SUM(amount),0) FROM reservations WHERE run_id=? AND settled=0", (self.run_id,)).fetchone()[0]
            if spent + own_reserved + amount > run_cap + 1e-9:
                raise ValueError("Run budget exhausted")
            self.db.execute("INSERT OR IGNORE INTO milestones(key) VALUES(?)", (milestone,))
            current = self.db.execute("SELECT spent,reserved FROM milestones WHERE key=?", (milestone,)).fetchone()
            if sum(current)+amount > milestone_cap + 1e-9:
                raise ValueError("Milestone budget exhausted")
            self.db.execute("INSERT INTO reservations VALUES(?,?,?,0)", (reservation_id,self.run_id,amount))
            self.db.execute("UPDATE milestones SET reserved=reserved+? WHERE key=?", (amount,milestone))

    def charge(self, amount: float, category: str, *, milestone: str, reservation_id: str) -> None:
        if amount < 0:
            raise ValueError("Negative charge")
        with self.tx():
            row = self.db.execute("SELECT amount,settled FROM reservations WHERE reservation_id=? AND run_id=?",
                                  (reservation_id,self.run_id)).fetchone()
            if not row or row[1]:
                raise ValueError("Missing or already settled reservation")
            linked = self.db.execute("SELECT milestone_key FROM runs WHERE run_id=?", (self.run_id,)).fetchone()
            if not linked or linked[0] != milestone:
                raise ValueError("Charge milestone differs from reserved run milestone")
            reserved = row[0]
            if amount > reserved + 1e-9:
                raise ValueError("Actual charge exceeds reserved budget")
            self.db.execute("UPDATE reservations SET settled=1 WHERE reservation_id=?", (reservation_id,))
            self.db.execute("INSERT INTO costs(run_id,amount,category,occurred_at) VALUES(?,?,?,?)",
                            (self.run_id,amount,category,utc_now()))
            self.db.execute("UPDATE milestones SET reserved=max(0,reserved-?),spent=spent+? WHERE key=?",
                            (reserved,amount,milestone))

    def acquire_writer(self, workspace: str, item: str) -> None:
        with self.tx():
            holder = self.db.execute("SELECT run_id,work_item FROM leases WHERE workspace=?", (workspace,)).fetchone()
            if holder and holder != (self.run_id,item):
                raise RuntimeError(f"Write lease owned by {holder[0]}/{holder[1]}")
            self.db.execute("INSERT OR IGNORE INTO leases VALUES(?,?,?,?)",
                            (workspace,self.run_id,item,utc_now()))

    def release_writer(self, workspace: str, item: str) -> None:
        with self.tx():
            self.db.execute("DELETE FROM leases WHERE workspace=? AND run_id=? AND work_item=?",
                            (workspace,self.run_id,item))

    def pending_outbox(self) -> list[tuple[str,dict]]:
        return [(row[0],json.loads(row[1])) for row in self.db.execute(
            "SELECT event_id,payload FROM outbox WHERE delivered=0 ORDER BY created_at,event_id")]

    def mark_delivered(self,event_id: str) -> None:
        with self.tx():
            self.db.execute("UPDATE outbox SET delivered=1 WHERE event_id=?", (event_id,))
