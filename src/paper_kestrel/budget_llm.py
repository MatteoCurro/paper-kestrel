"""Per-provider-call budget guard for CrewAI (no paid network in tests).

Every synchronous/asynchronous LLM entrypoint reserves a worst-case exposure
*before* invoking the provider. Reservations stay held when usage is unknown.
Pricing is mandatory config, never silently zero or a guessed tariff.

IMPORTANT: No release until transport retry/output ceilings and shared
cross-run budget authority have integration evidence.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from crewai import BaseLLM, LLM

from .budget import BudgetAdmissionError, CallBound, ModelRate, reserve_before_transport
from .budget_gateway import reserve_remote
from .state import RunStore


def configured_rates() -> dict[str, ModelRate]:
    raw = os.environ.get("MODEL_PRICING_JSON", "")
    if not raw:
        raise BudgetAdmissionError("MODEL_PRICING_JSON missing; LLM calls disabled")
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("A non-empty pricing mapping is required")
        return {
            str(name): ModelRate(
                Decimal(str(row["input_per_million"])),
                Decimal(str(row["output_per_million"])),
            )
            for name, row in parsed.items()
        }
    except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
        raise BudgetAdmissionError("MODEL_PRICING_JSON is invalid") from exc


class BudgetedLLM(BaseLLM):
    """A strict BaseLLM proxy. CrewAI cannot replace this wrapper with a native
    provider in LLM.__new__ (which could bypass a subclass override).
    Each agent iteration enters call/acall and obtains a remote permit.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        if kwargs.get("stream", False):
            raise BudgetAdmissionError("Streaming is disabled until metering is verified")
        output_limit = int(kwargs.get("max_completion_tokens") or 0)
        if output_limit <= 0 or output_limit > 4096:
            raise BudgetAdmissionError("Bounded provider output <=4096 tokens required")
        model_name = kwargs.get("model") or (args[0] if args else "")
        if not model_name:
            raise BudgetAdmissionError("Explicit model is required")
        super().__init__(model=str(model_name), temperature=kwargs.get("temperature"))
        self._inner = LLM(*args, **kwargs)
        object.__setattr__(self, "_max_budget_output", output_limit)
        object.__setattr__(self, "_max_budget_input_bytes", int(os.environ.get("MAX_LLM_INPUT_BYTES", "100000")))
        if self._max_budget_input_bytes <= 0:
            raise BudgetAdmissionError("MAX_LLM_INPUT_BYTES must be positive")

    def supports_function_calling(self) -> bool:
        return self._inner.supports_function_calling()

    def supports_stop_words(self) -> bool:
        return self._inner.supports_stop_words()

    def get_context_window_size(self) -> int:
        return self._inner.get_context_window_size()

    def get_token_usage_summary(self):
        return self._inner.get_token_usage_summary()

    def __getattr__(self, name: str):
        # Delegate optional CrewAI adapter attributes, but never call/acall.
        if name in {"call", "acall"}:
            raise AttributeError(name)
        inner = self.__dict__.get("_inner")
        if inner is None:
            raise AttributeError(name)
        return getattr(inner, name)

    def _admit(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        # Guard checks the caller-supplied messages and tool schema. A byte
        # upper bound is conservative versus tokenizer accounting, but must
        # still be validated against the pinned CrewAI provider adapter.
        message = args[0] if args else kwargs.get("messages")
        tools = kwargs.get("tools")
        response_format = kwargs.get("response_model") or kwargs.get("response_format")
        request = json.dumps(
            {"messages": message, "tools": tools, "response_format": str(response_format)},
            ensure_ascii=False, default=str, separators=(",", ":"),
        )
        input_bytes = len(request.encode("utf-8"))
        if input_bytes > self._max_budget_input_bytes:
            raise BudgetAdmissionError(
                f"LLM input {input_bytes} bytes exceeds safe bound {self._max_budget_input_bytes}"
            )
        db_path = os.environ.get("RUN_STATE_DB")
        run_id = os.environ.get("RUN_STATE_ID")
        if not db_path or not run_id:
            raise BudgetAdmissionError("Durable run context missing; LLM call refused")
        # New connection per call supports parallel specialists and avoids
        # passing a shared transaction connection across worker threads.
        store = RunStore(Path(db_path), run_id)
        reservation_id = f"{run_id}:{uuid.uuid4().hex}"
        try:
            milestone = os.environ.get("MILESTONE_KEY", "unassigned")
            ceiling = min(Decimal("0.75"),
                          Decimal(os.environ.get("MAX_RUN_COST_USD", "0.75")),
                          Decimal(os.environ.get("HARD_RUN_COST_USD", "0.75")))
            exposure = reserve_before_transport(
                store,
                bound=CallBound(
                    model=str(self.model),
                    max_input_tokens=max(1, input_bytes),
                    max_output_tokens=self._max_budget_output,
                    max_tool_roundtrips=0,  # each actual call is admitted separately
                ),
                rates=configured_rates(),
                reservation_id=reservation_id,
                milestone=milestone,
                run_cap=ceiling,
                milestone_cap=Decimal("1.50"),
            )
            # Local state protects this run; the remote Postgres ledger is
            # authoritative across *all* GitHub runners. Never call the model
            # when remote admission fails, even if local admission succeeded.
            reserve_remote(
                reservation_id=reservation_id,
                milestone=milestone,
                amount_usd=exposure,
            )
        finally:
            store.db.close()
        return reservation_id

    def call(self, *args: Any, **kwargs: Any) -> Any:
        self._admit(args, kwargs)
        # On timeout/retry a charge may exist: keep the reserved exposure.
        return self._inner.call(*args, **kwargs)

    async def acall(self, *args: Any, **kwargs: Any) -> Any:
        self._admit(args, kwargs)
        return await self._inner.acall(*args, **kwargs)
