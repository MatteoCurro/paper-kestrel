"""Fail-closed outbound wire gate for pinned CrewAI 1.15.23 OpenAI Responses.

The transport interceptor examines the exact serialized HTTP request AFTER the
SDK has added schemas, instructions and provider parameters, BEFORE any I/O.
Only bounded, text-only, Standard-tier, official OpenAI Responses requests pass.
The enclosing call still needs a durable local+remote budget reservation first.
"""
from __future__ import annotations

import json
from contextvars import ContextVar, Token
from typing import Any

import httpx
from crewai.llms.hooks.base import BaseInterceptor

from .budget import BudgetAdmissionError

_BYTES_ALLOWANCE_FOR_PROTOCOL_TOKENS = 4096
_PROHIBITED_KEYS = ("input_image", "input_audio", "input_file", "image_url",
                    "file_id", "audio_url", "computer_use", "web_search",
                    "file_search", "code_interpreter")
_active: ContextVar[tuple[str, int, int] | None] = ContextVar(
    "paper_kestrel_outbound_permit", default=None
)


class OpenAIWireGuard(BaseInterceptor[httpx.Request, httpx.Response]):
    def arm(self, model: str, max_input_tokens: int, max_output_tokens: int) -> Token:
        if max_input_tokens <= _BYTES_ALLOWANCE_FOR_PROTOCOL_TOKENS:
            raise BudgetAdmissionError("Input budget excludes protocol overhead")
        return _active.set((model.removeprefix("openai/"), max_input_tokens,
                            max_output_tokens))

    def disarm(self, token: Token) -> None:
        _active.reset(token)

    def on_outbound(self, request: httpx.Request) -> httpx.Request:
        permit = _active.get()
        if permit is None:
            raise BudgetAdmissionError("No preflight reservation for outbound LLM request")
        model, reserved_input, reserved_output = permit
        if request.url.scheme != "https" or request.url.host != "api.openai.com" or (
            request.url.path != "/v1/responses"
        ) or request.method != "POST":
            raise BudgetAdmissionError("Unknown provider, protocol or endpoint refused")
        try:
            raw = request.content
            body: Any = json.loads(raw)
        except (ValueError, TypeError, RuntimeError, httpx.RequestNotRead) as exc:
            raise BudgetAdmissionError("Uninspectable provider request denied") from exc
        if not isinstance(body, dict):
            raise BudgetAdmissionError("Invalid JSON body")
        if body.get("model") != model:
            raise BudgetAdmissionError("LLM model mismatch at network boundary")
        if body.get("stream") not in (None, False):
            raise BudgetAdmissionError("Streaming LLM calls disabled")
        if type(body.get("max_output_tokens")) is not int or not (
            0 < body["max_output_tokens"] <= reserved_output
        ):
            raise BudgetAdmissionError("Provider output limit missing or too high")
        if body.get("service_tier") not in (None, "default"):
            raise BudgetAdmissionError("Unexpected billed service tier")
        if body.get("background") or body.get("store") or body.get("previous_response_id"):
            raise BudgetAdmissionError("Unpriced asynchronous or persisted responses blocked")
        # Reject usage dimensions beyond text input/output pricing; HTTP body
        # length is a conservative bound for text byte BPE tokens.
        canonical = raw.decode("utf-8", errors="strict").lower()
        if any('"' + banned + '"' in canonical for banned in _PROHIBITED_KEYS):
            raise BudgetAdmissionError("Multimodal or separately billed built-in tool blocked")
        if not isinstance(body.get("input"), (str, list)):
            raise BudgetAdmissionError("Unpriced or missing input content")
        if len(raw) + _BYTES_ALLOWANCE_FOR_PROTOCOL_TOKENS > reserved_input:
            raise BudgetAdmissionError("Serialized provider body exceeded reserved input bound")
        return request

    def on_inbound(self, response: httpx.Response) -> httpx.Response:
        return response

    async def aon_outbound(self, request: httpx.Request) -> httpx.Request:
        return self.on_outbound(request)

    async def aon_inbound(self, response: httpx.Response) -> httpx.Response:
        return self.on_inbound(response)
