"""No provider calls: patch the underlying CrewAI transport."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crewai import LLM
from paper_kestrel.budget import BudgetAdmissionError
from paper_kestrel.budget_llm import BudgetedLLM
from paper_kestrel.state import RunStore


class GuardedLLMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "state.sqlite3", "run-1")
        self.store.initialize(spec="spec", master="master", cap=.75, milestone="M11")
        self.env = patch.dict(os.environ, {
            "RUN_STATE_DB": str(self.store.path),
            "RUN_STATE_ID": "run-1",
            "MILESTONE_KEY": "M11",
            "MODEL_PRICING_JSON": '{"openai/gpt-4o-mini":{"input_per_million":"2","output_per_million":"10"}}',
            "MAX_RUN_COST_USD": "0.75",
            "HARD_RUN_COST_USD": "0.75",
            "MAX_LLM_INPUT_BYTES": "10000",
            "OPENAI_API_KEY": "offline-mock-never-used",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.store.db.close()
        self.tmp.cleanup()

    def llm(self):
        return BudgetedLLM(model="openai/gpt-4o-mini", max_completion_tokens=1024)

    def test_reservation_happens_before_provider(self):
        llm = self.llm()
        def fake_transport(_self, *args, **kwargs):
            pending = self.store.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
            self.assertEqual(pending, 1)
            return "model-output"
        with patch("paper_kestrel.budget_llm.reserve_remote", side_effect=lambda **k: None) as remote:
            with patch.object(LLM, "call", fake_transport):
                self.assertEqual(llm.call("hello"), "model-output")
            remote.assert_called_once()

    def test_repeated_calls_reserve_separately(self):
        llm = self.llm()
        with patch("paper_kestrel.budget_llm.reserve_remote"):
            with patch.object(LLM, "call", lambda *_a, **_kw: "ok"):
                llm.call("one")
                llm.call("two")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 2)

    def test_remote_denial_prevents_provider(self):
        llm = self.llm()
        with patch("paper_kestrel.budget_llm.reserve_remote",
                   side_effect=BudgetAdmissionError("remote offline")):
            with patch.object(LLM, "call", side_effect=AssertionError("provider called")):
                with self.assertRaises(BudgetAdmissionError):
                    llm.call("hello")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0],1)

    def test_unpriced_model_never_calls_provider(self):
        llm = self.llm()
        os.environ.pop("MODEL_PRICING_JSON")
        with patch.object(LLM, "call", side_effect=AssertionError("provider called")):
            with self.assertRaises(BudgetAdmissionError):
                llm.call("hello")

    def test_missing_store_context_never_calls_provider(self):
        llm = self.llm()
        os.environ.pop("RUN_STATE_DB")
        with patch.object(LLM, "call", side_effect=AssertionError("provider called")):
            with self.assertRaises(BudgetAdmissionError):
                llm.call("hello")

    def test_oversized_input_never_calls_provider(self):
        llm = self.llm()
        with patch.object(LLM, "call", side_effect=AssertionError("provider called")):
            with self.assertRaises(BudgetAdmissionError):
                llm.call("x" * 11000)


if __name__ == "__main__":
    unittest.main()
