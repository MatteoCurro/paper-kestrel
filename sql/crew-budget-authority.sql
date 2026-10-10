-- CrewAI V2 shared budget authority (TSAND). No customer data.
-- Authoritative caps: $0.75 per run, $1.50 per milestone.
CREATE SCHEMA IF NOT EXISTS crew_budget;
REVOKE ALL ON SCHEMA crew_budget FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA crew_budget TO service_role;

CREATE TABLE IF NOT EXISTS crew_budget.milestones (
  key text PRIMARY KEY,
  cap numeric(12,6) NOT NULL DEFAULT 1.500000 CHECK(cap > 0 AND cap <= 1.500000),
  spent numeric(12,6) NOT NULL DEFAULT 0 CHECK(spent >= 0),
  reserved numeric(12,6) NOT NULL DEFAULT 0 CHECK(reserved >= 0),
  CHECK(spent + reserved <= cap)
);
CREATE TABLE IF NOT EXISTS crew_budget.runs (
  run_id text PRIMARY KEY,
  milestone_key text NOT NULL REFERENCES crew_budget.milestones(key),
  cap numeric(12,6) NOT NULL DEFAULT 0.750000 CHECK(cap > 0 AND cap <= 0.750000),
  spent numeric(12,6) NOT NULL DEFAULT 0 CHECK(spent >= 0),
  reserved numeric(12,6) NOT NULL DEFAULT 0 CHECK(reserved >= 0),
  CHECK(spent + reserved <= cap)
);
CREATE TABLE IF NOT EXISTS crew_budget.reservations (
  key text PRIMARY KEY,
  run_id text NOT NULL REFERENCES crew_budget.runs(run_id),
  amount numeric(12,6) NOT NULL CHECK(amount > 0),
  charged numeric(12,6),
  created_at timestamptz NOT NULL DEFAULT now(),
  settled_at timestamptz,
  CHECK(charged IS NULL OR (charged >= 0 AND charged <= amount))
);
REVOKE ALL ON ALL TABLES IN SCHEMA crew_budget FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA crew_budget TO service_role;
ALTER TABLE crew_budget.milestones ENABLE ROW LEVEL SECURITY;
ALTER TABLE crew_budget.runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE crew_budget.reservations ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.crew_budget_reserve(
    p_run_id text, p_milestone text, p_key text, p_amount numeric
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE
    v_m crew_budget.milestones%ROWTYPE;
    v_r crew_budget.runs%ROWTYPE;
    v_existing crew_budget.reservations%ROWTYPE;
BEGIN
    IF coalesce(length(p_run_id),0)<4 OR coalesce(length(p_milestone),0)<1
       OR coalesce(length(p_key),0)<6 OR p_amount IS NULL
       OR p_amount<=0 OR p_amount>0.750000 THEN
       RAISE EXCEPTION 'invalid budget reservation';
    END IF;
    INSERT INTO crew_budget.milestones(key) VALUES (p_milestone)
    ON CONFLICT(key) DO NOTHING;
    SELECT * INTO STRICT v_m FROM crew_budget.milestones
      WHERE key=p_milestone FOR UPDATE;
    INSERT INTO crew_budget.runs(run_id,milestone_key)
    VALUES(p_run_id,p_milestone)
    ON CONFLICT(run_id) DO NOTHING;
    SELECT * INTO STRICT v_r FROM crew_budget.runs
      WHERE run_id=p_run_id FOR UPDATE;
    IF v_r.milestone_key <> p_milestone THEN
      RAISE EXCEPTION 'run milestone mismatch';
    END IF;
    SELECT * INTO v_existing FROM crew_budget.reservations
      WHERE key=p_key;
    IF FOUND THEN
      IF v_existing.run_id<>p_run_id OR v_existing.amount<>p_amount THEN
        RAISE EXCEPTION 'reservation id conflict';
      END IF;
      RETURN jsonb_build_object('accepted',true,'idempotent',true,
        'milestone_remaining',v_m.cap-v_m.spent-v_m.reserved,
        'run_remaining',v_r.cap-v_r.spent-v_r.reserved);
    END IF;
    IF v_r.spent+v_r.reserved+p_amount>v_r.cap THEN
      RAISE EXCEPTION 'run budget exhausted';
    END IF;
    IF v_m.spent+v_m.reserved+p_amount>v_m.cap THEN
      RAISE EXCEPTION 'milestone budget exhausted';
    END IF;
    UPDATE crew_budget.milestones SET reserved=reserved+p_amount
      WHERE key=p_milestone;
    UPDATE crew_budget.runs SET reserved=reserved+p_amount
      WHERE run_id=p_run_id;
    INSERT INTO crew_budget.reservations(key,run_id,amount)
      VALUES(p_key,p_run_id,p_amount);
    RETURN jsonb_build_object('accepted',true,'idempotent',false,
      'milestone_remaining',v_m.cap-v_m.spent-v_m.reserved-p_amount,
      'run_remaining',v_r.cap-v_r.spent-v_r.reserved-p_amount);
END; $$;

CREATE OR REPLACE FUNCTION public.crew_budget_settle(
    p_run_id text, p_key text, p_charged numeric
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $$
DECLARE
    v_milestone text;
    v_res crew_budget.reservations%ROWTYPE;
BEGIN
    SELECT milestone_key INTO STRICT v_milestone FROM crew_budget.runs
      WHERE run_id=p_run_id;
    -- Consistent lock order: milestone, then run, then reservation.
    PERFORM 1 FROM crew_budget.milestones WHERE key=v_milestone FOR UPDATE;
    PERFORM 1 FROM crew_budget.runs WHERE run_id=p_run_id FOR UPDATE;
    SELECT * INTO STRICT v_res FROM crew_budget.reservations
      WHERE key=p_key AND run_id=p_run_id FOR UPDATE;
    IF v_res.settled_at IS NOT NULL THEN
      IF v_res.charged<>p_charged THEN RAISE EXCEPTION 'settlement conflict'; END IF;
      RETURN jsonb_build_object('settled',true,'idempotent',true);
    END IF;
    IF p_charged IS NULL OR p_charged<0 OR p_charged>v_res.amount THEN
      RAISE EXCEPTION 'charge exceeds reservation';
    END IF;
    UPDATE crew_budget.reservations
      SET charged=p_charged,settled_at=now() WHERE key=p_key;
    UPDATE crew_budget.runs SET reserved=reserved-v_res.amount,
      spent=spent+p_charged WHERE run_id=p_run_id;
    UPDATE crew_budget.milestones SET reserved=reserved-v_res.amount,
      spent=spent+p_charged WHERE key=v_milestone;
    RETURN jsonb_build_object('settled',true,'idempotent',false);
END; $$;

-- All RPC invocations require service_role, supplied inside an OIDC-verified
-- Edge Function. Never expose these functions to anon/authenticated.
REVOKE ALL ON FUNCTION public.crew_budget_reserve(text,text,text,numeric) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.crew_budget_settle(text,text,numeric) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.crew_budget_reserve(text,text,text,numeric) TO service_role;
GRANT EXECUTE ON FUNCTION public.crew_budget_settle(text,text,numeric) TO service_role;
