import tempfile
import unittest
from pathlib import Path
from paper_kestrel.recovery import CheckpointJournal, RecoveryBlocked
from paper_kestrel.state import RunStore


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "run.sqlite3"
        self.store = RunStore(self.path, "run-1")
        self.store.initialize(spec="spec", master="plan", cap=.75, milestone="test")
        self.j = CheckpointJournal(self.store)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_completed_model_step_is_idempotent(self):
        inputs = {"model":"light", "prompt":"read only"}
        self.assertIsNone(self.j.begin("llm:one", inputs))
        self.j.complete("llm:one", inputs, {"result":"ok"})
        self.assertEqual(self.j.begin("llm:one", inputs), {"result":"ok"})
        with self.assertRaises(RecoveryBlocked):
            self.j.begin("llm:one", {"prompt":"different"})

    def test_crash_does_not_repeat_an_uncertain_step(self):
        inputs = {"model":"core", "prompt":"possibly paid"}
        self.j.begin("llm:crash", inputs)
        recovered = CheckpointJournal(RunStore(self.path,"run-1"))
        with self.assertRaises(RecoveryBlocked):
            recovered.begin("llm:crash", inputs)
        self.j.uncertain("llm:crash")
        with self.assertRaises(RecoveryBlocked):
            recovered.begin("llm:crash", inputs)
        recovered.store.db.close()

    def test_workspace_integrity_required_before_replay(self):
        inputs = {"work":"change UI"}
        self.j.begin("work:UI", inputs, candidate_sha="old")
        self.j.complete("work:UI", inputs, {"summary":"done"}, candidate_sha="new")
        self.assertEqual(self.j.begin("work:UI", inputs, candidate_sha="new"), {"summary":"done"})
        with self.assertRaises(RecoveryBlocked):
            self.j.begin("work:UI", inputs, candidate_sha="different")

    def test_completion_requires_original_claim(self):
        with self.assertRaises(RecoveryBlocked):
            self.j.complete("unclaimed", {"a":1}, "output")
        self.j.begin("started", {"a":1})
        with self.assertRaises(RecoveryBlocked):
            self.j.complete("started", {"a":2}, "output")


if __name__ == "__main__":
    unittest.main()
