"""OIDC request and remote budget authorization, with all HTTP mocked."""
import json
import os
import unittest
from decimal import Decimal
from unittest.mock import patch
from paper_kestrel.budget import BudgetAdmissionError
from paper_kestrel.budget_gateway import reserve_remote


class MockResponse:
    def __init__(self, response):
        self.payload = json.dumps(response).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return self.payload


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "CREW_BUDGET_URL": "https://example.test/functions/v1/crew-budget",
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://actions.test/token?request=1",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "mock-only",
            "CREW_BUDGET_AUDIENCE": "crew-budget-supabase",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_oidc_and_decimal_request(self):
        requests = []
        def fake_urlopen(request, timeout=None):
            requests.append(request)
            if len(requests) == 1:
                return MockResponse({"value":"test-oidc-token"})
            return MockResponse({"accepted": True, "milestone_remaining": .75})
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            reserve_remote(reservation_id="12:1:abcd1234", milestone="M11",
                           amount_usd=Decimal("0.123456"))
        self.assertIn("audience=crew-budget-supabase", requests[0].full_url)
        self.assertEqual(requests[1].get_header("Authorization"), "Bearer test-oidc-token")
        self.assertEqual(json.loads(requests[1].data)["amount_usd"], "0.123456")

    def test_no_oidc_refuses_before_any_budget_request(self):
        os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        with patch("urllib.request.urlopen", side_effect=AssertionError("network touched")):
            with self.assertRaises(BudgetAdmissionError):
                reserve_remote(reservation_id="12:1:abcd1234", milestone="M11",
                               amount_usd=Decimal("0.001000"))

    def test_remote_denial_is_not_silent(self):
        with patch("urllib.request.urlopen", side_effect=[
            MockResponse({"value":"mock-oidc-token"}),
            MockResponse({"accepted":False}),
        ]):
            with self.assertRaises(BudgetAdmissionError):
                reserve_remote(reservation_id="12:1:abcd1234", milestone="M11",
                               amount_usd=Decimal("0.001000"))


if __name__ == "__main__":
    unittest.main()
