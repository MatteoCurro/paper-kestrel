"""Transport gate inspects the exact SDK JSON wire request, no provider I/O."""
import unittest
import httpx
from paper_kestrel.budget import BudgetAdmissionError
from paper_kestrel.wire_guard import OpenAIWireGuard

class WireGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard=OpenAIWireGuard()
        self.base={"model":"gpt-6-luna","input":"Hello","max_output_tokens":200}

    def req(self, data=None, url="https://api.openai.com/v1/responses"):
        return httpx.Request("POST",url,json=data or self.base)

    def test_valid_text_payload(self):
        token=self.guard.arm("openai/gpt-6-luna",9000,200)
        try:
            self.assertIsInstance(self.guard.on_outbound(self.req()),httpx.Request)
        finally:
            self.guard.disarm(token)

    def test_local_function_tools_are_token_priced(self):
        payload={
            **self.base,
            "tools":[{
                "type":"function","name":"inspect_file",
                "description":"Return lines",
                "parameters":{"type":"object","properties":{"path":{"type":"string"}}},
            }],
        }
        token=self.guard.arm("openai/gpt-6-luna",9000,200)
        try:
            self.assertIsInstance(self.guard.on_outbound(self.req(payload)),httpx.Request)
        finally:
            self.guard.disarm(token)

    def test_one_agent_cannot_borrow_another_agents_permit(self):
        other=OpenAIWireGuard()
        token=self.guard.arm("openai/gpt-6-luna",9000,200)
        try:
            with self.assertRaises(BudgetAdmissionError):
                other.on_outbound(self.req())
        finally:
            self.guard.disarm(token)

    def test_no_approval_blocks(self):
        with self.assertRaises(BudgetAdmissionError):
            self.guard.on_outbound(self.req())

    def test_provider_retry_cannot_reuse_reservation(self):
        token=self.guard.arm("openai/gpt-6-luna",9000,200)
        try:
            self.guard.on_outbound(self.req())
            with self.assertRaises(BudgetAdmissionError):
                self.guard.on_outbound(self.req())
        finally:
            self.guard.disarm(token)

    def test_oversized_wire_payload_denied(self):
        token=self.guard.arm("openai/gpt-6-luna",5000,200)
        try:
            with self.assertRaises(BudgetAdmissionError):
                self.guard.on_outbound(self.req({**self.base,"input":"x"*7000}))
        finally:
            self.guard.disarm(token)

    def test_endpoint_and_model_mismatch_denied(self):
        for url in ("https://evil.example/v1/responses",
                    "http://api.openai.com/v1/responses",
                    "https://api.openai.com/v1/chat/completions"):
            token=self.guard.arm("openai/gpt-6-luna",9000,200)
            try:
                with self.assertRaises(BudgetAdmissionError):
                    self.guard.on_outbound(self.req(url=url))
            finally:
                self.guard.disarm(token)
        token=self.guard.arm("openai/gpt-6.1-sol",9000,200)
        try:
            with self.assertRaises(BudgetAdmissionError):
                self.guard.on_outbound(self.req())
        finally:
            self.guard.disarm(token)

    def test_no_multimodal_builtin_tools_or_unbounded_output(self):
        cases=[
            {**self.base,"input":[{"type":"input_image","image_url":"test"}]},
            {**self.base,"tools":[{"type":"web_search"}]},
            {**self.base,"max_output_tokens":99999},
            {**self.base,"service_tier":"priority"},
            {**self.base,"stream":True},
            {**self.base,"background":True},
        ]
        for data in cases:
            token=self.guard.arm("openai/gpt-6-luna",9000,200)
            try:
                with self.assertRaises(BudgetAdmissionError):
                    self.guard.on_outbound(self.req(data))
            finally:
                self.guard.disarm(token)

    def test_async_hook_follows_identical_policy(self):
        import asyncio
        token=self.guard.arm("openai/gpt-6-luna",9000,200)
        try:
            self.assertIsInstance(asyncio.run(self.guard.aon_outbound(self.req())),httpx.Request)
        finally:
            self.guard.disarm(token)

if __name__=="__main__":
    unittest.main()
