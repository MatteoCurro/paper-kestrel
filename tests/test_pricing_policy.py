"""Provider tariff changes cannot silently underprice a paid API request."""
import os
import unittest
from unittest.mock import patch
from decimal import Decimal
from paper_kestrel.budget import BudgetAdmissionError
from paper_kestrel.budget_llm import configured_rates

class PriceAdmissionTests(unittest.TestCase):
    def rates(self, raw):
        with patch.dict(os.environ, {"MODEL_PRICING_JSON":raw}):
            return configured_rates()

    def test_underpriced_flagship_model_refused(self):
        for value in [
            '{"openai/gpt-6.1-sol":{"input_per_million":"2","output_per_million":"10"}}',
            '{"openai/gpt-6-luna":{"input_per_million":"0.10","output_per_million":"0.50"}}',
        ]:
            with self.assertRaises(BudgetAdmissionError):
                self.rates(value)

    def test_conservative_pinned_prices_approved(self):
        found=self.rates(
            '{"openai/gpt-6.1-sol":{"input_per_million":"5.5","output_per_million":"16.5"},'
            '"openai/gpt-6-luna":{"input_per_million":"0.275","output_per_million":"0.825"}}'
        )
        self.assertEqual(found["openai/gpt-6.1-sol"].input_per_million,Decimal("5.5"))

    def test_unknown_model_refused(self):
        with self.assertRaises(BudgetAdmissionError):
            self.rates('{"openai/random":{"input_per_million":"99","output_per_million":"99"}}')

    def test_infinite_prices_refused(self):
        with self.assertRaises(BudgetAdmissionError):
            self.rates('{"openai/gpt-6-luna":{"input_per_million":"Infinity","output_per_million":"1"}}')

if __name__=="__main__":
    unittest.main()
