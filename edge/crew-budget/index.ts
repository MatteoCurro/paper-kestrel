import { createClient } from "npm:@supabase/supabase-js@2.49.8";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

// GitHub Actions OIDC is validated here; Supabase service credentials never
// leave the Edge Function runtime. This endpoint is NOT an anonymous API.
const ISSUER = "https://token.actions.githubusercontent.com";
const REPOSITORY = "MatteoCurro/paper-kestrel";
const WORKFLOW = "Maintenance pass";
const CANARY_WORKFLOW = "Jarvis TSAND review canary";
const PROBE_WORKFLOWS = new Set(["CrewAI budget OIDC smoke", "CrewAI offline safety audit"]);
const AUDIENCE = "crew-budget-supabase";
// Phases 1–3 only: allow authenticated identity probes, NEVER real monetary admission.
const PAID_ADMISSION_ENABLED = false;
// The single approved Jarvis review completed. Disable subsequent attempts.
const CANARY_ADMISSION_ENABLED = false;
const ALLOWED_REFS = new Set(["refs/heads/main", "refs/heads/infra/transactional-v2"]);
const JWKS = createRemoteJWKSet(new URL(ISSUER + "/.well-known/jwks"));

function respond(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: { "cache-control": "no-store" } });
}

function adminClient() {
  const secrets = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
  const secret = secrets.default || Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  const url = Deno.env.get("SUPABASE_URL");
  if (!url || !secret) throw new Error("Budget service environment unavailable");
  return createClient(url, secret, { auth: { persistSession: false, autoRefreshToken: false } });
}

function validIdentifier(v: unknown): v is string {
  return typeof v === "string" && /^[a-zA-Z0-9._:\-]{1,100}$/.test(v);
}

Deno.serve(async (request: Request) => {
  if (request.method !== "POST") return respond({ error: "method not allowed" }, 405);
  const bearer = request.headers.get("authorization") || "";
  if (!bearer.startsWith("Bearer ")) return respond({ error: "authorization required" }, 401);
  try {
    const { payload } = await jwtVerify(bearer.slice(7), JWKS, {
      issuer: ISSUER, audience: AUDIENCE,
    });
    const workflow = String(payload.workflow || "");
    const branchRef = String(payload.ref || "");
    const stagingPrProbe =
      workflow === "CrewAI offline safety audit" &&
      payload.event_name === "pull_request" &&
      payload.head_ref === "infra/transactional-v2" &&
      payload.base_ref === "main" &&
      branchRef === "refs/pull/1/merge";
    const trustedBranch = ALLOWED_REFS.has(branchRef);
    const canary = workflow === CANARY_WORKFLOW &&
      branchRef === "refs/heads/infra/transactional-v2" &&
      payload.event_name === "push";
    if (payload.repository !== REPOSITORY ||
        String(payload.repository_id) !== "1409141984" ||
        !(workflow === WORKFLOW || PROBE_WORKFLOWS.has(workflow) || canary) ||
        !(trustedBranch || stagingPrProbe)) {
      return respond({ error: "unauthorized Actions identity" }, 403);
    }
    const numericRun = Number(payload.run_id);
    const numericAttempt = Number(payload.run_attempt || 1);
    if (!Number.isSafeInteger(numericRun) || numericRun <= 0 ||
        !Number.isSafeInteger(numericAttempt) || numericAttempt <= 0) {
      return respond({ error: "invalid run identity" }, 403);
    }
    // The *same GitHub run* shares one cap across all workflow retry attempts.
    const runId = String(numericRun);
    const reservationPrefix = runId + ":" + String(numericAttempt) + ":";
    const body = await request.json();
    if (body?.action === "probe" && PROBE_WORKFLOWS.has(workflow)) {
      return respond({ ok: true, authorized: true, repository: REPOSITORY,
                       github_run_id: runId, branch: String(payload.ref) });
    }
    // Checkpoints are free and safe during the simulation phase.
    // A PR workflow may use only its own synthetic smoke-test keys.
    const action = String(body?.action || "");
    if (action === "checkpoint_claim" || action === "checkpoint_complete") {
      if (workflow !== WORKFLOW && !(stagingPrProbe && action.startsWith("checkpoint_"))) {
        return respond({ error: "checkpoint workflow forbidden" }, 403);
      }
      const step = String(body?.step || "");
      const inputSha = String(body?.input_sha || "");
      const candidateSha = body?.candidate_sha === null ? null : String(body?.candidate_sha || "");
      if (step.length < 1 || step.length > 180 ||
          (workflow !== WORKFLOW && !step.startsWith("smoke:")) ||
          !/^[a-f0-9]{64}$/.test(inputSha) ||
          (candidateSha !== null && !/^[a-f0-9]{64}$/.test(candidateSha))) {
        return respond({ error: "invalid checkpoint request" }, 400);
      }
      if (action === "checkpoint_complete" &&
          (!body?.result || JSON.stringify(body.result).length > 30000)) {
        return respond({ error: "invalid checkpoint result" }, 400);
      }
      const params: Record<string, unknown> = {
        p_run_id: runId, p_step: step,
        p_input_sha: inputSha, p_candidate_sha: candidateSha,
      };
      if (action === "checkpoint_complete") params.p_result = body.result;
      const name = action === "checkpoint_claim"
        ? "crew_checkpoint_claim" : "crew_checkpoint_complete";
      const { data, error } = await adminClient().rpc(name, params);
      if (error || data?.accepted !== true) {
        return respond({ error: "checkpoint denied or needs reconciliation" }, 409);
      }
      return respond(data);
    }
    if (workflow !== WORKFLOW && !canary) {
      return respond({ error: "workflow cannot reserve budget" }, 403);
    }
    if (canary && !CANARY_ADMISSION_ENABLED) {
      return respond({ error: "Jarvis TSAND one-shot review closed", run_id: runId }, 423);
    }
    if (!canary && (!PAID_ADMISSION_ENABLED || branchRef !== "refs/heads/infra/transactional-v2")) {
      return respond({ error: "paid activity disabled in TSAND until Phase 4" }, 423);
    }
    if (canary && (action !== "reserve" && action !== "settle")) {
      return respond({ error: "canary action refused" }, 403);
    }
    if (!["reserve", "settle"].includes(action) ||
        !validIdentifier(body?.reservation_id) ||
        !body.reservation_id.startsWith(reservationPrefix)) {
      return respond({ error: "invalid budget request" }, 400);
    }
    if (action === "reserve" && !validIdentifier(body?.milestone)) {
      return respond({ error: "invalid milestone" }, 400);
    }
    const amountText = body.amount_usd;
    // JSON strings preserve decimal precision. Reject any precision drift.
    if (typeof amountText !== "string" || !/^[0-9]+[.][0-9]{6}$/.test(amountText)) {
      return respond({ error: "amount must have exactly 6 decimal places" }, 400);
    }
    const amount = Number(amountText);
    if (!Number.isFinite(amount) || amount < 0 ||
        amount > (canary ? 0.025 : 0.75) ||
        (action === "reserve" && amount === 0) ||
        (canary && action === "reserve" && body.milestone !== "JARVIS_CANARY_20261010")) {
      return respond({ error: "invalid precise amount" }, 400);
    }
    const argumentsForRpc = action === "reserve"
      ? {p_run_id: runId, p_milestone: body.milestone, p_key: body.reservation_id, p_amount: amountText}
      : {p_run_id: runId, p_key: body.reservation_id, p_charged: amountText};
    const { data, error } = await adminClient().rpc(
      action === "reserve"
        ? (canary ? "crew_budget_reserve_jarvis_canary" : "crew_budget_reserve")
        : "crew_budget_settle",
      argumentsForRpc
    );
    if (error) {
      console.warn("Budget reservation refused:", error.code);
      return respond({ error: "budget reservation denied" }, 409);
    }
    if (action === "reserve" && data?.accepted !== true) return respond({ error: "budget not admitted" }, 409);
    if (action === "settle" && data?.settled !== true) return respond({ error: "settlement not accepted" }, 409);
    return respond(data);
  } catch (error) {
    // Do not leak token metadata, SQL state or privileged client internals.
    if (error && typeof error === "object" &&
        ("code" in error || "claim" in error)) {
      return respond({ error: "invalid GitHub OIDC token" }, 401);
    }
    console.error("Budget service failure:", error instanceof Error ? error.name : "unknown");
    return respond({ error: "budget authority unavailable" }, 503);
  }
});
