import { createClient } from "npm:@supabase/supabase-js@2.49.8";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

// GitHub Actions OIDC is validated here; Supabase service credentials never
// leave the Edge Function runtime. This endpoint is NOT an anonymous API.
const ISSUER = "https://token.actions.githubusercontent.com";
const REPOSITORY = "MatteoCurro/paper-kestrel";
const WORKFLOW = "Maintenance pass";
const PROBE_WORKFLOWS = new Set(["CrewAI budget OIDC smoke", "CrewAI offline safety audit"]);
const AUDIENCE = "crew-budget-supabase";
// Phases 1–3 only: allow authenticated identity probes, NEVER real monetary admission.
const PAID_ADMISSION_ENABLED = false;
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
    if (payload.repository !== REPOSITORY ||
        String(payload.repository_id) !== "1409141984" ||
        !(workflow === WORKFLOW || PROBE_WORKFLOWS.has(workflow)) ||
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
    if (workflow !== WORKFLOW) {
      return respond({ error: "workflow cannot reserve budget" }, 403);
    }
    if (!PAID_ADMISSION_ENABLED || branchRef !== "refs/heads/infra/transactional-v2") {
      return respond({ error: "paid activity disabled in TSAND until Phase 4" }, 423);
    }
    const action = String(body?.action || "");
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
    if (typeof amountText !== "string" || !/^\\d+\\.\\d{6}$/.test(amountText)) {
      return respond({ error: "amount must have exactly 6 decimal places" }, 400);
    }
    const amount = Number(amountText);
    if (!Number.isFinite(amount) || amount < 0 || amount > .75 ||
        (action === "reserve" && amount === 0)) {
      return respond({ error: "invalid precise amount" }, 400);
    }
    const argumentsForRpc = action === "reserve"
      ? {p_run_id: runId, p_milestone: body.milestone, p_key: body.reservation_id, p_amount: amountText}
      : {p_run_id: runId, p_key: body.reservation_id, p_charged: amountText};
    const { data, error } = await adminClient().rpc(
      action === "reserve" ? "crew_budget_reserve" : "crew_budget_settle",
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
