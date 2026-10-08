import tempfile
import unittest
from pathlib import Path
from paper_kestrel.state import RunStore


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = RunStore(self.path, "run-1")
        self.store.initialize(spec="spec", master="master", cap=.75, milestone="M11")

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_transitions_idempotent_and_detect_drift(self):
        self.assertTrue(self.store.transition("1","PLANNED",{"x":1}))
        self.assertFalse(self.store.transition("1","PLANNED",{"x":1}))
        with self.assertRaises(ValueError):
            self.store.transition("1","BLOCKED",{"x":1})
        self.assertEqual(len(self.store.pending_outbox()), 1)
        self.store.mark_delivered("run-1:1")
        self.assertEqual(len(self.store.pending_outbox()), 0)

    def test_durable_resume_and_input_integrity(self):
        other = RunStore(self.path, "run-1")
        self.assertTrue(self.store.transition("1","PLANNED",{"x":1}))
        self.assertFalse(other.transition("1","PLANNED",{"x":1}))
        with self.assertRaises(ValueError):
            other.initialize(spec="changed", master="master", cap=.75, milestone="M11")
        other.db.close()

    def test_writer_lease_exclusive(self):
        self.store.acquire_writer("/work", "one")
        other = RunStore(self.path, "run-2")
        with self.assertRaises(RuntimeError):
            other.acquire_writer("/work","two")
        self.store.release_writer("/work","one")
        other.acquire_writer("/work","two")
        other.release_writer("/work","two")
        other.db.close()

    def test_budget_reservation_atomic(self):
        self.store.reserve(.4,run_cap=.75,milestone_cap=1.50,milestone="M11",reservation_id="a")
        with self.assertRaises(ValueError):
            self.store.reserve(.4,run_cap=.75,milestone_cap=1.50,milestone="M11",reservation_id="b")
        self.store.charge(.35,"engineer",milestone="M11",reservation_id="a")
        with self.assertRaises(ValueError):
            self.store.charge(.35,"engineer",milestone="M11",reservation_id="a")
        self.store.reserve(.3,run_cap=.75,milestone_cap=1.50,milestone="M11",reservation_id="c")

    def test_rollback_on_conflict(self):
        self.store.transition("1","PLANNED")
        with self.assertRaises(ValueError):
            self.store.transition("1","FAILED")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],1)


if __name__ == "__main__":
    unittest.main()
