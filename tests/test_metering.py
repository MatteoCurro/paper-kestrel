from decimal import Decimal
import unittest
from paper_kestrel.metering import actual_cost_usd, MeteringBlocked

R = dict(input_per_million=Decimal("2"), output_per_million=Decimal("10"))

class MeteringTests(unittest.TestCase):
    def test_single_call_delta_not_lifetime(self):
        before = dict(prompt_tokens=100000, completion_tokens=20000, successful_requests=3)
        after = dict(prompt_tokens=101000, completion_tokens=20400, successful_requests=4)
        self.assertEqual(actual_cost_usd(before,after,maximum=Decimal(".1"),**R),
                         Decimal("0.006000"))

    def test_missing_or_ambiguous_metrics_keep_reservation(self):
        before = dict(prompt_tokens=0,completion_tokens=0,successful_requests=0)
        self.assertIsNone(actual_cost_usd(before,{},maximum=Decimal(".1"),**R))
        self.assertIsNone(actual_cost_usd(before,dict(prompt_tokens=20,completion_tokens=10,successful_requests=0),
                                          maximum=Decimal(".1"),**R))
        self.assertIsNone(actual_cost_usd(before,dict(prompt_tokens=20,completion_tokens=10,successful_requests=2),
                                          maximum=Decimal(".1"),**R))

    def test_exposure_breach_blocks(self):
        before = dict(prompt_tokens=0,completion_tokens=0,successful_requests=0)
        after = dict(prompt_tokens=1000,completion_tokens=1000,successful_requests=1)
        with self.assertRaises(MeteringBlocked):
            actual_cost_usd(before,after,maximum=Decimal(".001"),**R)

    def test_negative_or_invalid_tokens_not_settled(self):
        before = dict(prompt_tokens=10,completion_tokens=10,successful_requests=1)
        after = dict(prompt_tokens=5,completion_tokens=20,successful_requests=2)
        self.assertIsNone(actual_cost_usd(before,after,maximum=Decimal(".1"),**R))

if __name__=="__main__":
    unittest.main()
