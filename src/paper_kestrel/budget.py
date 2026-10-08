"""Strict pre-call budget admission.

A bounded *call* needs a provider-enforced maximum input/output token count.
This module intentionally does not guess input limits or live provider prices.
Admission is not a substitute for the actual LLM transport enforcing bounds.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_UP


class BudgetAdmissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelRate:
    input_per_million: Decimal
    output_per_million: Decimal

    def __post_init__(self):
        if self.input_per_million <= 0 or self.output_per_million <= 0:
            raise ValueError("Unknown, zero or negative model rates are forbidden")


@dataclass(frozen=True)
class CallBound:
    model: str
    max_input_tokens: int
    max_output_tokens: int
    max_tool_roundtrips: int = 0

    def __post_init__(self):
        if min(self.max_input_tokens, self.max_output_tokens) <= 0:
            raise BudgetAdmissionError("Provider-enforced token limits required")
        if self.max_tool_roundtrips < 0:
            raise BudgetAdmissionError("Invalid tool roundtrip bound")


def worst_case_usd(bound: CallBound, rates: dict[str, ModelRate]) -> Decimal:
    rate = rates.get(bound.model)
    if rate is None:
        raise BudgetAdmissionError(f"Unpriced model blocked: {bound.model}")
    # Each tool roundtrip can be another inference with a refreshed context.
    calls = bound.max_tool_roundtrips + 1
    tokens_cost = (
        rate.input_per_million * bound.max_input_tokens
        + rate.output_per_million * bound.max_output_tokens
    )
    return (tokens_cost * calls / Decimal(1_000_000)).quantize(
        Decimal("0.000001"), rounding=ROUND_UP
    )


def reserve_before_transport(
    store,
    *,
    bound: CallBound,
    rates: dict[str, ModelRate],
    reservation_id: str,
    milestone: str,
    run_cap: Decimal = Decimal("0.75"),
    milestone_cap: Decimal = Decimal("1.50"),
) -> Decimal:
    """Reserve worst-case cost; caller MUST ensure bounds in the provider request.

    Reserve immediately before the provider transport call. An exception after
    dispatch is an *uncertain charge*: preserve the reservation until usage can
    be reconciled; never quietly release it.
    """
    exposure = worst_case_usd(bound, rates)
    if exposure > run_cap:
        raise BudgetAdmissionError("Single-call exposure exceeds run cap")
    try:
        store.reserve(
            float(exposure),
            run_cap=float(run_cap),
            milestone_cap=float(milestone_cap),
            milestone=milestone,
            reservation_id=reservation_id,
        )
    except ValueError as exc:
        raise BudgetAdmissionError(str(exc)) from exc
    return exposure
