"""Offline budget policy tests. No model or network needed."""
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from paper_kestrel.budget import (
    BudgetAdmissionError, ModelRate, CallBound, worst_case_usd,
    reserve_before_transport,
)
from paper_kestrel.state import RunStore


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.tmp.name) / "budget.db", "run-1")
        self.store.initialize(spec="spec", master="master", cap=.75, milestone="m1")
        self.rates = {"example": ModelRate(Decimal("2"), Decimal("10"))}

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_unpriced_models_fail_closed(self):
        with self.assertRaises(BudgetAdmissionError):
            worst_case_usd(CallBound("unknown", 1000, 1000), self.rates)

    def test_provider_limits_mandatory(self):
        with self.assertRaises(BudgetAdmissionError):
            CallBound("example", 1000, 0)

    def test_multiple_tool_calls_reserve_all_exposure(self):
        a = worst_case_usd(CallBound("example", 10000, 10000, 2), self.rates)
        self.assertEqual(a, Decimal("0.360000"))

    def test_budget_reserved_before_transport_and_not_double_counted(self):
        bound = CallBound("example", 10000, 10000, 1)
        a = reserve_before_transport(self.store, bound=bound, rates=self.rates,
                                     reservation_id="call-1", milestone="m1")
        self.assertEqual(a, Decimal("0.240000"))
        with self.assertRaises(BudgetAdmissionError):
            reserve_before_transport(self.store, bound=bound, rates=self.rates,
                                     reservation_id="call-1", milestone="m1")
        self.store.charge(.12, "llm", milestone="m1", reservation_id="call-1")
        reserve_before_transport(self.store, bound=bound, rates=self.rates,
                                 reservation_id="call-2", milestone="m1")

    def test_unknown_charge_is_not_refunded(self):
        bound = CallBound("example", 10000, 10000, 1)
        reserve_before_transport(self.store, bound=bound, rates=self.rates,
                                 reservation_id="call-uncertain", milestone="m1")
        reserved = self.store.db.execute("SELECT reserved FROM milestones WHERE key='m1'").fetchone()[0]
        self.assertAlmostEqual(reserved, .24)
        with self.assertRaises(ValueError):
            self.store.reserve(.75, run_cap=.75, milestone_cap=1.5,
                               milestone="m1", reservation_id="second")


if __name__ == "__main__":
    unittest.main()
