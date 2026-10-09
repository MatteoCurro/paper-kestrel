"""Conservative reconciliation of a single pinned CrewAI LLM attempt.

The CrewAI provider reports lifetime counters. Never bill the entire cumulative
counter again: compute a delta around the ONE guarded transport attempt.
Unknown or malformed usage is not assumed free: leave reservation outstanding.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_UP
from typing import Any

class MeteringBlocked(RuntimeError):
    pass

def _field(metrics: Any, field: str) -> int | None:
    value = metrics.get(field) if isinstance(metrics, dict) else getattr(metrics, field, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value

def actual_cost_usd(before: Any, after: Any, *, input_per_million: Decimal,
                    output_per_million: Decimal, maximum: Decimal) -> Decimal | None:
    """None means evidence insufficient and the full reservation must remain held.

    Cached tokens are charged at the full input rate, deliberately conservative.
    Reasoning tokens are already included in provider output token counts.
    """
    keys = ("prompt_tokens", "completion_tokens", "successful_requests")
    old = [_field(before, k) for k in keys]
    new = [_field(after, k) for k in keys]
    if any(x is None for x in old + new):
        return None
    prompt, completion, calls = (n - o for n, o in zip(new, old))
    if min(prompt, completion) < 0 or calls != 1:
        return None
    cost = ((Decimal(prompt) * input_per_million
             + Decimal(completion) * output_per_million)
            / Decimal(1_000_000)).quantize(Decimal("0.000001"), rounding=ROUND_UP)
    if cost > maximum:
        raise MeteringBlocked("Provider-reported usage exceeded admitted exposure")
    return cost
