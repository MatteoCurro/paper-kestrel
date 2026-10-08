"""GitHub OIDC -> Supabase TSAND budget authority.

No static Supabase key is distributed to the public repository or runner.
The budget Edge Function validates signed GitHub Actions identity and admits a
reservation in one PostgreSQL transaction before any provider LLM call.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import urllib.error
from decimal import Decimal

from .budget import BudgetAdmissionError


def _github_oidc_token() -> str:
    endpoint = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    credential = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not endpoint or not credential:
        raise BudgetAdmissionError("GitHub Actions OIDC unavailable; provider disabled")
    separator = "&" if "?" in endpoint else "?"
    url = endpoint + separator + urllib.parse.urlencode({
        "audience": os.environ.get("CREW_BUDGET_AUDIENCE", "crew-budget-supabase")
    })
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + credential,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=8) as result:
            value = json.loads(result.read().decode("utf-8"))["value"]
        if not isinstance(value, str) or not value:
            raise BudgetAdmissionError("GitHub Actions identity missing")
        return value
    except (KeyError, OSError, ValueError) as exc:
        raise BudgetAdmissionError("Cannot attest GitHub Actions identity") from exc


def reserve_remote(*, reservation_id: str, milestone: str, amount_usd: Decimal) -> None:
    url = os.environ.get("CREW_BUDGET_URL", "").strip()
    if not url.startswith("https://"):
        raise BudgetAdmissionError("HTTPS central budget authority is required")
    if not reservation_id or not milestone:
        raise BudgetAdmissionError("Budget reservation identity is missing")
    token = _github_oidc_token()
    request = urllib.request.Request(
        url,
        data=json.dumps({
            "action": "reserve",
            "reservation_id": reservation_id,
            "milestone": milestone,
            "amount_usd": format(amount_usd, ".6f"),
        }).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            accepted = json.loads(response.read().decode("utf-8"))
        if not isinstance(accepted, dict) or accepted.get("accepted") is not True:
            raise BudgetAdmissionError("Central budget authority refused request")
    except (OSError, ValueError) as exc:
        raise BudgetAdmissionError("Central budget authority unavailable or denied") from exc
