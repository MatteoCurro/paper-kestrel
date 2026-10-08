import { createClient } from "npm:@supabase/supabase-js@2.49.8";
import { createRemoteJWKSet, jwtVerify } from "npm:jose@6.1.0";

// GitHub Actions OIDC is validated here; Supabase service credentials never
// leave the Edge Function runtime. This endpoint is NOT an anonymous API.
const ISSUER = "https://token.actions.githubusercontent.com";
const REPOSITORY = "MatteoCurro/paper-kestrel";
const WORKFLOW = "Maintenance pass";
const AUDIENCE = "crew-budget-supabase";
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
    if (payload.repository !== REPOSITORY || payload.workflow !== WORKFLOW ||
        !ALLOWED_REFS.has(String(payload.ref || ""))) {
      return respond({ error: "unauthorized Actions identity" }, 403);
    }
    const numericRun = Number(payload.run_id);
    const numericAttempt = Number(payload.run_attempt || 1);
    if (!Number.isSafeInteger(numericRun) || numericRun <= 0 ||
        !Number.isSafeInteger(numericAttempt) || numericAttempt <= 0) {
      return respond({ error: "invalid run identity" }, 403);
    }
    const runId = String(numericRun) + ":" + String(numericAttempt);
    const body = await request.json();
    if (body?.action !== "reserve" || !validIdentifier(body?.milestone) ||
        !validIdentifier(body?.reservation_id) ||
        !body.reservation_id.startsWith(runId + ":")) {
      return respond({ error: "invalid budget request" }, 400);
    }
    const amountText = body.amount_usd;
    if (typeof amountText !== "string" || !/^0\\.[0-9]{6}$/.test(amountText)) {
      return respond({ error: "amount must have 6 decimal places" }, 400);
    }
    const amount = Number(amountText);
    if (!Number.isFinite(amount) || amount <= 0 || amount > .75) {
      return respond({ error: "invalid precise amount" }, 400);
    }
    const { data, error } = await adminClient().rpc("crew_budget_reserve", {
      p_run_id: runId,
      p_milestone: body.milestone,
      p_key: body.reservation_id,
      p_amount: amount,
    });
    if (error) {
      console.warn("Budget reservation refused:", error.code);
      return respond({ error: "budget reservation denied" }, 409);
    }
    if (!data?.accepted) return respond({ error: "budget not admitted" }, 409);
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
