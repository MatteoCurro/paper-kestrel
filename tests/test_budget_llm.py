"""No provider calls: patch the underlying CrewAI transport."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crewai import BaseLLM
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
        self.no_network = patch("socket.socket.connect",
                                side_effect=AssertionError("network forbidden in offline tests"))
        self.no_network.start()

    def tearDown(self):
        self.no_network.stop()
        self.env.stop()
        self.store.db.close()
        self.tmp.cleanup()

    def llm(self):
        llm = BudgetedLLM(model="openai/gpt-4o-mini", max_completion_tokens=1024)
        self.assertIsInstance(llm, BaseLLM)
        return llm

    def test_actual_provider_is_native_openai_with_wire_guard(self):
        llm = self.llm()
        self.assertEqual(type(llm._inner).__name__, "OpenAICompletion")
        self.assertIs(llm._inner.interceptor, llm._wire_guard)
        self.assertEqual(llm._inner.api, "responses")

    def test_transport_gate_sees_sdk_wire_request_before_mock_network(self):
        import httpx
        llm = self.llm()
        def fake_adapter(_self, *args, **kwargs):
            raw = httpx.Request(
                "POST","https://api.openai.com/v1/responses",
                json={"model":"gpt-4o-mini","input":"hello","max_output_tokens":1024},
            )
            llm._wire_guard.on_outbound(raw)
            return "ok"
        with patch("paper_kestrel.budget_llm.reserve_remote"):
            with patch.object(type(llm._inner), "call", fake_adapter):
                self.assertEqual(llm.call("hello"), "ok")

    def test_secondary_provider_dispatch_is_denied_after_first(self):
        import httpx
        llm = self.llm()
        def bad_adapter(_self,*args,**kwargs):
            def request():
                return httpx.Request(
                    "POST","https://api.openai.com/v1/responses",
                    json={"model":"gpt-4o-mini","input":"hello","max_output_tokens":1024},
                )
            llm._wire_guard.on_outbound(request())
            llm._wire_guard.on_outbound(request())
        with patch("paper_kestrel.budget_llm.reserve_remote"):
            with patch.object(type(llm._inner), "call", bad_adapter):
                with self.assertRaises(BudgetAdmissionError):
                    llm.call("hello")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM reservations"
        ).fetchone()[0],1)

    def test_native_sdk_retries_are_disabled(self):
        self.assertEqual(self.llm()._inner.max_retries, 0)
        with self.assertRaises(BudgetAdmissionError):
            BudgetedLLM(model="openai/gpt-4o-mini",
                        max_completion_tokens=1024, max_retries=2)

    def test_rate_limit_retry_requires_second_reservation(self):
        class Throttled(Exception):
            status_code = 429

        llm = self.llm()
        with patch("paper_kestrel.budget_llm.reserve_remote") as remote:
            with patch.object(type(llm._inner), "call",
                              side_effect=[Throttled("rate limit"), "ok"]):
                self.assertEqual(llm.call("hello"), "ok")
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM reservations"
        ).fetchone()[0], 2)

    def test_reservation_happens_before_provider(self):
        llm = self.llm()
        def fake_transport(_self, *args, **kwargs):
            pending = self.store.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0]
            self.assertEqual(pending, 1)
            return "model-output"
        with patch("paper_kestrel.budget_llm.reserve_remote", side_effect=lambda **k: None) as remote:
            with patch.object(type(llm._inner), "call", fake_transport):
                self.assertEqual(llm.call("hello"), "model-output")
            remote.assert_called_once()

    def test_known_provider_usage_settles_exact_delta(self):
        llm = self.llm()
        prior = {"prompt_tokens": 100, "completion_tokens": 50,
                 "successful_requests": 1}
        after = {"prompt_tokens": 1100, "completion_tokens": 250,
                 "successful_requests": 2}
        with patch("paper_kestrel.budget_llm.reserve_remote") as reserve:
            with patch("paper_kestrel.budget_llm.settle_remote") as settle:
                with patch.object(type(llm._inner), "call", return_value="ok"):
                    with patch.object(type(llm._inner), "get_token_usage_summary",
                                      side_effect=[prior, after]):
                        self.assertEqual(llm.call("hello"), "ok")
        reserve.assert_called_once()
        settle.assert_called_once()
        self.assertEqual(settle.call_args.kwargs["amount_usd"],
                         __import__("decimal").Decimal("0.004000"))
        self.assertEqual(self.store.db.execute(
            "SELECT settled FROM reservations").fetchone()[0], 1)
        self.assertAlmostEqual(self.store.db.execute(
            "SELECT amount FROM costs").fetchone()[0], .004)

    def test_repeated_calls_reserve_separately(self):
        llm = self.llm()
        with patch("paper_kestrel.budget_llm.reserve_remote"):
            with patch.object(type(llm._inner), "call", lambda *_a, **_kw: "ok"):
                llm.call("one")
                llm.call("two")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 2)

    def test_remote_denial_prevents_provider(self):
        llm = self.llm()
        with patch("paper_kestrel.budget_llm.reserve_remote",
                   side_effect=BudgetAdmissionError("remote offline")):
            with patch.object(type(llm._inner), "call", side_effect=AssertionError("provider called")):
                with self.assertRaises(BudgetAdmissionError):
                    llm.call("hello")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0],1)

    def test_unpriced_model_never_calls_provider(self):
        llm = self.llm()
        os.environ.pop("MODEL_PRICING_JSON")
        with patch.object(type(llm._inner), "call", side_effect=AssertionError("provider called")):
            with self.assertRaises(BudgetAdmissionError):
                llm.call("hello")

    def test_missing_store_context_never_calls_provider(self):
        llm = self.llm()
        os.environ.pop("RUN_STATE_DB")
        with patch.object(type(llm._inner), "call", side_effect=AssertionError("provider called")):
            with self.assertRaises(BudgetAdmissionError):
                llm.call("hello")

    def test_oversized_input_never_calls_provider(self):
        llm = self.llm()
        with patch.object(type(llm._inner), "call", side_effect=AssertionError("provider called")):
            with self.assertRaises(BudgetAdmissionError):
                llm.call("x" * 11000)


if __name__ == "__main__":
    unittest.main()
