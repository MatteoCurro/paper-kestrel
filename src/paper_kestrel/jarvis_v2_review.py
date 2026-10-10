"""Budgeted read-only CrewAI review of the actual published Jarvis TSAND UI.

The mission is NOT enabled until owner approves new paid LLM expense and the
dedicated OIDC budget authority explicitly admits this workflow. Default
GitHub Action remains disabled. Never edit Gandi, product repositories or DB.
"""
from __future__ import annotations
import json
import os
import re
import urllib.request
from pathlib import Path

from .jarvis_review import run_role
from .jarvis import JarvisEmitter
from .state import RunStore

JARVIS_STAGE="https://www.unlockvenice.com/t-sand/jarvis.html"
MILESTONE="JARVIS_V2_REVIEW_20261010"
REQUIRED_MARKERS=(
    "JARVIS_T_SAND_AUTH_V2_20261010",
    "JARVIS_T_SAND_CHAT_V3_20261010",
    "signInWithPassword(",
    'verifyOtp({email:codeEmail,token,type:"email"})',
    'id="runFilter"',
    'id="runSearch"',
)


def get_staged_source() -> str:
    req=urllib.request.Request(
        JARVIS_STAGE,
        headers={"User-Agent":"paper-kestrel-jarvis-v2-readonly-review/1.0"}
    )
    with urllib.request.urlopen(req,timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("Jarvis TSAND source not available")
        body=response.read(50000)
    if len(body)>=50000:
        raise RuntimeError("Jarvis source over allowed review size")
    source=body.decode("utf-8")
    if any(marker not in source for marker in REQUIRED_MARKERS):
        raise RuntimeError("TSAND stage source does not match reviewed code version")
    # Never send public publishable tokens (or opaque OAuth query fragments)
    # to the LLM even though the publishable key is not a secret.
    return re.sub(r"sb_publishable_[A-Za-z0-9_-]+","[REDACTED_PUBLIC_KEY]",source)


def safe_chat_excerpt(text: str) -> str:
    # Persist *bounded actual excerpts* of role output, no generated narrative.
    text=re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", "[email omessa]", text, flags=re.I)
    text=re.sub(r"(?:sb_secret_|sk-proj-|ghp_)[A-Za-z0-9_-]+","[chiave omessa]",text)
    text=re.sub(r"(?i)(?:api[_-]?key|password|bearer)\\s*[=:]\\s*\\S+","[credenziale omessa]",text)
    return " ".join(text.split())[:460]


def main() -> None:
    if os.environ.get("GITHUB_REPOSITORY")!="MatteoCurro/paper-kestrel":
        raise RuntimeError("Only public test orchestrator may run Jarvis V2 Crew review")
    if os.environ.get("GITHUB_REF")!="refs/heads/infra/transactional-v2":
        raise RuntimeError("Only transactional staging branch may run Jarvis V2 Crew review")
    if os.environ.get("MILESTONE_KEY")!=MILESTONE:
        raise RuntimeError("Dedicated approved TSAND milestone required")
    if os.environ.get("MAX_RUN_COST_USD")!="0.15":
        raise RuntimeError("New model-run limit must be exactly 15 cents")
    if not os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
        raise RuntimeError("Verified GitHub Actions OIDC required")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("Missing model key: run refuses, no paid calls attempted")
    output=Path("output");output.mkdir(parents=True,exist_ok=True)
    store=RunStore(output/"jarvis-v2-crew.sqlite3",os.environ["RUN_STATE_ID"])
    store.initialize(
        spec="orders/jarvis-control-room-v2.md",
        master="TSAND Jarvis V2 review only, no code writes",
        cap=.15,milestone=MILESTONE,
    )
    code=get_staged_source()
    js=re.findall(r"<script[^>]*>([\s\S]*?)</script>",code,re.I)
    css=re.findall(r"<style[^>]*>([\s\S]*?)</style>",code,re.I)
    excerpt=("STAGING URL: "+JARVIS_STAGE+"\nFRONTEND JAVASCRIPT:\n"
             + "\n".join(js)[-11500:]
             +"\nRESPONSIVE CSS:\n"+"\n".join(css)[-3500:])
    context=("Owner's Jarvis V2 master plan: OTP/password identity parity with "
             "U.Venice Transport; GitHub OAuth deliberately unavailable, no false "
             "GitHub button; real TSAND data is RLS-admin gated.\n"
             "Known staging tests: no-network Chrome OTP/password/admin denial; "
             "mobile 390px, desktop 1280px; read-only dashboard search and filters.\n")
    reviews=[]
    emitter=JarvisEmitter()
    emitter.run_store=store
    # Only short handoffs are posted to the TSAND event table; the complete
    # multi-agent transcript lives solely in a short-retention Actions artifact.
    def chat(seq:int, actor:str, body:str, *, target:str|None=None,
             phase:str="planning", finished:bool=False, ok:bool=True)->None:
        emitter.emit(
            "run.completed" if finished and ok else ("run.failed" if finished else "agent.message"),
            safe_chat_excerpt(body),agent=actor,
            status=("success" if ok else "failure") if finished else "running",
            phase="done" if finished and ok else phase,
            event_key=f"v2chat:{seq:02d}",
            details={"kind":"agent_chat","to":target} if target else {"kind":"agent_chat"},
            finished=finished,
        )
    chat(0,"Controller","Avvio della revisione Jarvis V2. Verificheremo codice, UX, sicurezza e passaggi tra agenti.",phase="planning")
    try:
        engineer=run_role(
            "Senior Product Engineer",
            "Review code correctness and suggest targeted next steps, no implementation.",
            "Inspect source critically. Find up to four P0/P1 issues grounded in "
            "actual code, including authentication state/races and token safety. "
            "Separate proven defects from hypotheses, propose acceptance tests.",
            excerpt[:16000]+context,
        )
        reviews.append(("Engineering",engineer))
        chat(1,"Senior Product Engineer",engineer,target="UX Critic")
        ux=run_role(
            "UX Critic",
            "Critique existing engineering decisions and propose better UX.",
            "Challenge the engineer's actual findings, prioritize clear next user "
            "actions, mobile accessibility, health/attention hierarchy and discoverability. "
            "Give concrete corrective feedback back to Engineering.",
            context+excerpt[:8500]+"\nENGINEERING HANDOFF:\n"+engineer[:3300],
        )
        reviews.append(("UX Critic",ux))
        chat(2,"UX Critic",ux,target="Senior Product Engineer",phase="qa")
        revision=run_role(
            "Senior Product Engineer",
            "Address UX Critic's actionable concerns; provide a grounded implementation proposal without making changes.",
            "Read the UX review critically. State which points you accept, reject or amend, with concrete validation tests and an efficient TSAND-only patch sequence. Reply directly to the critic; do not deploy.",
            "INITIAL ENGINEERING:\n"+engineer[:2400]+"\nUX CRITIQUE:\n"+ux[:3000],
        )
        reviews.append(("Engineering follow-up",revision))
        chat(3,"Senior Product Engineer",revision,target="Independent Security and Release Reviewer",phase="qa")
        reviewer=run_role(
            "Independent Security and Release Reviewer",
            "Make a prudent TSAND-only go/no-go decision.",
            "Check OTP authentication, account authorization and RLS, untrusted URLs, "
            "resend rate limits, stale state, accessibility, GitHub OAuth provider setup "
            "and zero production deploy. Flag mistaken UX/engineering assumptions. "
            "Provide exact smallest TSAND patch and regression checks; no production approval.",
            "ENGINEERING:\n"+engineer[:2300]+"\nUX FEEDBACK:\n"+ux[:2200]+
            "\nENGINEER RESPONSE TO UX:\n"+revision[:2200],
        )
        reviews.append(("Release Review",reviewer))
        chat(4,"Independent Security and Release Reviewer",reviewer,target="Controller",phase="qa")
        (output/"jarvis-v2-crew-review.json").write_text(json.dumps({
            "mode":"CREWAI_READONLY_TSAND_REVIEW",
            "staging_url":JARVIS_STAGE,
            "github_run_id":os.environ["GITHUB_RUN_ID"],
            "maximum_spend_usd":"0.15",
            "roles":[{"role":name,"review":review} for name,review in reviews],
            "code_writes":0,"deployments":0,"production_touch":False,
        },ensure_ascii=False,indent=2),encoding="utf-8")
        chat(5,"Controller","Revisione completata: Engineering, UX Critic, replica Engineering e Release Reviewer. Transcript completo archiviato temporaneamente su GitHub Actions.",finished=True)
        print("CrewAI Jarvis V2: 4 authentic role turns; <= 6 bounded Jarvis chat events; no writes or deployment")
    finally:
        store.db.close()


if __name__=="__main__":
    main()
