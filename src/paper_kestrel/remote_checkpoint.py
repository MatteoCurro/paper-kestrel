"""Private Supabase TSAND crash ledger, authenticated with GitHub OIDC.

Never substitute a new run for the original GitHub run_id: retries reuse the
original budget and checkpoint authority. A missing/uncertain remote response
must block execution, not turn into a fresh local attempt.
"""
from __future__ import annotations
import json
import os
import urllib.request
from .budget_gateway import _github_oidc_token
from .recovery import RecoveryBlocked

class RemoteCheckpoint:
    def __init__(self, url: str):
        if not url.startswith("https://"):
            raise RecoveryBlocked("Checkpoint authority must use HTTPS")
        self.url=url

    def _rpc(self, action: str, step: str, input_sha: str,
             candidate_sha: str | None, result: dict | None = None) -> dict:
        token=_github_oidc_token()
        body={"action":action,"step":step,"input_sha":input_sha,
              "candidate_sha":candidate_sha}
        if result is not None:
            body["result"]=result
        request=urllib.request.Request(
            self.url,
            data=json.dumps(body,sort_keys=True).encode("utf-8"),
            method="POST",
            headers={"Authorization":"Bearer "+token,
                     "Content-Type":"application/json"},
        )
        try:
            with urllib.request.urlopen(request,timeout=12) as response:
                received=json.loads(response.read().decode("utf-8"))
        except (OSError,ValueError) as exc:
            raise RecoveryBlocked("Shared checkpoint unavailable or inconsistent") from exc
        if not isinstance(received,dict) or received.get("accepted") is not True:
            raise RecoveryBlocked("Shared checkpoint rejected")
        return received

    def claim(self, step: str, input_sha: str, candidate_sha: str | None) -> dict:
        return self._rpc("checkpoint_claim",step,input_sha,candidate_sha)

    def complete(self, step: str, input_sha: str,
                 candidate_sha: str | None, result: dict) -> None:
        self._rpc("checkpoint_complete",step,input_sha,candidate_sha,result)
