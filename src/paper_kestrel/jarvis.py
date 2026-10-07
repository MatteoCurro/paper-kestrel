from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


# Standard, short-context API rates per 1M tokens (USD).
# Dashboard labels these values as estimates because service tier / long-context
# pricing can differ from these defaults.
MODEL_PRICES = {
    "gpt-6.1-sol": {"input": 2.00, "cached": 0.10, "output": 10.00},
    "gpt-6-luna": {"input": 0.10, "cached": 0.01, "output": 0.50},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _brief(value: Any, limit: int = 640) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit] or "Evento Jarvis"


def _usage_dict(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        return {}
    keys = (
        "prompt_tokens",
        "cached_prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
    )
    out: dict[str, int] = {}
    for key in keys:
        try:
            out[key] = max(0, int(value.get(key, 0) or 0))
        except (TypeError, ValueError):
            out[key] = 0
    return out


def estimate_cost(model: str | None, usage: dict[str, int]) -> float:
    key = (model or "").split("/")[-1]
    rates = MODEL_PRICES.get(key)
    if not rates:
        return 0.0
    prompt = usage.get("prompt_tokens", 0)
    cached = min(prompt, usage.get("cached_prompt_tokens", 0))
    uncached = max(0, prompt - cached)
    output = usage.get("completion_tokens", 0)
    return (
        uncached * rates["input"]
        + cached * rates["cached"]
        + output * rates["output"]
    ) / 1_000_000


class JarvisEmitter:
    def __init__(self) -> None:
        self.url = os.environ.get("JARVIS_INGEST_URL", "").strip()
        self.audience = os.environ.get("JARVIS_AUDIENCE", "jarvis-supabase").strip()
        self.run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
        self.attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip()
        self.spec_path = os.environ.get("JARVIS_SPEC_PATH", "").strip()
        self.enabled = bool(
            self.url
            and self.run_id
            and os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL")
            and os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        )
        self.sequence = 0
        self.started_at = _now()
        self._token: str | None = None
        self._token_at = 0.0
        self.totals = {
            "prompt_tokens": 0,
            "cached_prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
        }
        self.total_cost = 0.0
        self.has_usage = False

    def set_spec(self, spec_path: str) -> None:
        self.spec_path = spec_path

    def _oidc_token(self, force: bool = False) -> str:
        if not force and self._token and time.monotonic() - self._token_at < 240:
            return self._token
        base = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"]
        sep = "&" if "?" in base else "?"
        url = base + sep + urllib.parse.urlencode({"audience": self.audience})
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"],
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        self._token = str(data["value"])
        self._token_at = time.monotonic()
        return self._token

    def _post(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    self.url,
                    data=body,
                    method="POST",
                    headers={
                        "Authorization": "Bearer " + self._oidc_token(force=attempt > 0),
                        "Content-Type": "application/json",
                        "User-Agent": "paper-kestrel-jarvis/1",
                    },
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    response.read()
                return
            except Exception:
                if attempt:
                    return

    def emit(
        self,
        event_type: str,
        message: str,
        *,
        agent: str = "Controller",
        status: str = "running",
        phase: str | None = None,
        model: str | None = None,
        usage: Any = None,
        need_owner: bool | None = None,
        summary: str | None = None,
        pr_url: str | None = None,
        finished: bool = False,
        event_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.sequence += 1
        usage_data = _usage_dict(usage)
        cost = estimate_cost(model, usage_data)
        if any(usage_data.values()):
            self.has_usage = True
        for key in self.totals:
            self.totals[key] += usage_data.get(key, 0)
        self.total_cost += cost

        run: dict[str, Any] = {
            "spec_path": self.spec_path or None,
            "status": status if event_type.startswith("run.") or finished else "running",
            "phase": phase or "implementation",
        }
        if event_type == "run.started":
            run["started_at"] = self.started_at
        if need_owner is not None:
            run["need_owner"] = bool(need_owner)
        if self.has_usage:
            run.update({
                "prompt_tokens": self.totals["prompt_tokens"],
                "cached_prompt_tokens": self.totals["cached_prompt_tokens"],
                "completion_tokens": self.totals["completion_tokens"],
                "reasoning_tokens": self.totals["reasoning_tokens"],
                "estimated_cost_usd": round(self.total_cost, 6),
            })
        if summary is not None:
            run["summary"] = _brief(summary, 800)
        if pr_url is not None:
            run["pr_url"] = pr_url
        if finished:
            run["finished_at"] = _now()

        event = {
            "event_key": event_key or f"{self.sequence:04d}:{event_type}",
            "event_at": _now(),
            "agent": agent,
            "event_type": event_type,
            "status": status,
            "message": _brief(message),
            "model": model,
            "prompt_tokens": usage_data.get("prompt_tokens", 0),
            "cached_prompt_tokens": usage_data.get("cached_prompt_tokens", 0),
            "completion_tokens": usage_data.get("completion_tokens", 0),
            "reasoning_tokens": usage_data.get("reasoning_tokens", 0),
            "estimated_cost_usd": round(cost, 6),
            "details": details or {},
        }
        self._post({"run": run, "event": event})


EMITTER = JarvisEmitter()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--agent", default="Controller")
    parser.add_argument("--status", default="running")
    parser.add_argument("--phase", default="delivery")
    parser.add_argument("--spec-path", default="")
    parser.add_argument("--pr-url", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--need-owner", action="store_true")
    parser.add_argument("--finished", action="store_true")
    parser.add_argument("--event-key", default="")
    args = parser.parse_args()
    if args.spec_path:
        EMITTER.set_spec(args.spec_path)
    EMITTER.emit(
        args.event_type,
        args.message,
        agent=args.agent,
        status=args.status,
        phase=args.phase,
        need_owner=args.need_owner,
        summary=args.summary or None,
        pr_url=args.pr_url or None,
        finished=args.finished,
        event_key=args.event_key or None,
    )


if __name__ == "__main__":
    main()
