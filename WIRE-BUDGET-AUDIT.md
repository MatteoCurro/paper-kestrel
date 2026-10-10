# CrewAI V2: conservative OpenAI transport budget audit (TSAND only)

**Status: NO-GO for paid tasks.** This document records the current design and
test requirements; it is not authority to enable the paid workflow.

## Pinned dependency contract

- `crewai==1.15.23`, Python 3.12, OpenAI **native Responses** transport.
- `BudgetedLLM(BaseLLM)` creates its inner provider using the **bare model name**
  to avoid new `openai/` model names falling back to LiteLLM. The constructor
  asserts the exact OpenAI interceptor is installed and native SDK retries = 0.
- Every guarded attempt reserves against SQLite *and* the OIDC-authenticated
  Supabase TSAND Postgres ledger before calling the native adapter.
- An `OpenAIWireGuard(BaseInterceptor)` inspects the **actual HTTP JSON body**
  in `on_outbound/aon_outbound`, before the HTTP transport makes a connection.
  It allows only `POST https://api.openai.com/v1/responses`, expected model,
  text-only content, bounded output tokens and default/Standard tier.
- Wire body size + 4096 protocol-token allowance must fit the already-reserved
  conservative input bound. The bound was padded by 12288 over the planner's
  serialized input size. Unexpected tool schemas or server-generated overhead
  cause an immediate deny *before* the provider request is sent.
- Exactly **one** outbound HTTP request can consume each reservation; hidden
  retries or subsequent provider requests require a new reservation.
- OpenAI hosted tools (web/file search, code interpreter), image/audio/file
  inputs, background, stored/chained responses, streaming, custom endpoints and
  non-default service tiers are disabled until priced separately.

## Conservative price floors (USD per 1M tokens)

| Configured model | Minimum input rate | Minimum output rate |
| --- | ---: | ---: |
| `openai/gpt-6.1-sol` | 5.500 | 16.500 |
| `openai/gpt-6-luna` | 0.275 | 0.825 |
| `openai/gpt-4o-mini` (legacy offline fixture) | 2.000 | 10.000 |

For the two intended models, these values conservatively cover the highest
published **Standard long-context input or cache-write** tariff and output
tariff with an extra 10% regional uplift (even when not applied). Lower prices
supplied via `MODEL_PRICING_JSON` are rejected, not blindly trusted.
Fast and UltraFast tiers are not permitted. Unpriced model names fail closed.

Official price reference: https://platform.openai.com/pricing/
This rate snapshot requires re-validation on any model, SKU, region or tier
change. It must not be used as an indefinite pricing guarantee.

## Limits and release gate

- For text-only OpenAI BPE tokenization, serialized UTF-8 body bytes plus an
  explicit protocol-token margin provide a conservative *budget bound*, not
  an exact provider-token prediction. Every actual outbound body is compared
  with that reservation; unsupported representations fail before network I/O.
- Billing reconciliation uses the adapter's *delta* usage counters after
  the attempt. Unknown usage or uncertain settlement retains the reserved
  maximum; nothing is silently credited as free.
- Cross-run shared checkpoints and local content-addressed Git candidate
  snapshots must continue to block unproven replay.
- The service at `u-venice-transport-tsand` has
  `PAID_ADMISSION_ENABLED=false`; no approved model charges can occur through
  that budget authority.
- The **legacy main workflow** was disabled separately at commit `520e360`,
  removing the automatic push trigger and applying a job-level `if: false`.
  That does not deploy or alter the product application.
- Mandatory: GitHub Actions tests for provider-wire guard, pricing floors,
  adapter identity, two-request rejection, and TSAND OIDC + read-only staging.
  If these do not pass, keep the entire paid agent workflow blocked.

## Hardening still needed before any real autonomous run

- Review actual provider token billing for the selected tier with independently
  verified low-cost canary before loosening any conservative reserve.
- Verify no chargeable call bypasses HTTPX interceptor (SDK upgrades require
  re-audit). Any provider changes must be reviewed at code level.
- Execute and verify the **actual** push/PR Saga in TSAND with strict
  draft-only staging branch permissions, anti-deploy branch protection and
  idempotent external-action tracking.
- Explicit owner authorization is required before spending beyond the
  established run/milestone caps. Never deploy to production from TSAND.
