-- TSAND only. Cross-run crash-safe metadata, owned by GitHub Actions run ID.
-- Private schema; all RPCs are SECURITY INVOKER and service_role-only.
CREATE TABLE IF NOT EXISTS crew_budget.checkpoints(
    run_id text NOT NULL,
    step_key text NOT NULL,
    input_sha text NOT NULL CHECK(input_sha ~ '^[a-f0-9]{64}$'),
    status text NOT NULL CHECK(status IN ('STARTED','COMPLETED','UNCERTAIN')),
    candidate_sha text,
    output jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(run_id,step_key),
    CHECK(candidate_sha IS NULL OR candidate_sha ~ '^[a-f0-9]{64}$')
);
ALTER TABLE crew_budget.checkpoints ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON crew_budget.checkpoints FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON crew_budget.checkpoints TO service_role;

CREATE OR REPLACE FUNCTION public.crew_checkpoint_claim(
    p_run_id text, p_step text, p_input_sha text, p_candidate_sha text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE v crew_budget.checkpoints%ROWTYPE;
BEGIN
    IF p_step IS NULL OR length(p_step) > 180 OR length(p_step) < 1
       OR p_input_sha !~ '^[a-f0-9]{64}$'
       OR (p_candidate_sha IS NOT NULL AND p_candidate_sha !~ '^[a-f0-9]{64}$')
    THEN RAISE EXCEPTION 'invalid checkpoint identity'; END IF;
    SELECT * INTO v FROM crew_budget.checkpoints
        WHERE run_id=p_run_id AND step_key=p_step FOR UPDATE;
    IF FOUND THEN
        IF v.input_sha <> p_input_sha THEN
            RAISE EXCEPTION 'checkpoint input drift'; END IF;
        IF v.status <> 'COMPLETED' THEN
            RAISE EXCEPTION 'checkpoint interrupted or uncertain'; END IF;
        IF v.candidate_sha IS NOT NULL
           AND v.candidate_sha IS DISTINCT FROM p_candidate_sha THEN
            RAISE EXCEPTION 'candidate workspace mismatch'; END IF;
        RETURN jsonb_build_object('accepted',true,'cached',true,'result',v.output);
    END IF;
    INSERT INTO crew_budget.checkpoints(run_id,step_key,input_sha,status)
        VALUES (p_run_id,p_step,p_input_sha,'STARTED');
    RETURN jsonb_build_object('accepted',true,'cached',false);
END; $$;

CREATE OR REPLACE FUNCTION public.crew_checkpoint_complete(
    p_run_id text, p_step text, p_input_sha text, p_candidate_sha text, p_result jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE v crew_budget.checkpoints%ROWTYPE;
BEGIN
    IF p_result IS NULL OR pg_catalog.octet_length(p_result::text) > 32768
       OR p_input_sha !~ '^[a-f0-9]{64}$'
       OR (p_candidate_sha IS NOT NULL AND p_candidate_sha !~ '^[a-f0-9]{64}$')
    THEN RAISE EXCEPTION 'checkpoint payload invalid'; END IF;
    SELECT * INTO STRICT v FROM crew_budget.checkpoints
        WHERE run_id=p_run_id AND step_key=p_step FOR UPDATE;
    IF v.input_sha <> p_input_sha THEN RAISE EXCEPTION 'checkpoint input drift'; END IF;
    IF v.status='COMPLETED' THEN
        IF v.output IS DISTINCT FROM p_result OR
           v.candidate_sha IS DISTINCT FROM p_candidate_sha
        THEN RAISE EXCEPTION 'checkpoint completion conflict'; END IF;
        RETURN jsonb_build_object('accepted',true,'idempotent',true);
    END IF;
    IF v.status <> 'STARTED' THEN
        RAISE EXCEPTION 'uncertain checkpoint cannot be committed'; END IF;
    UPDATE crew_budget.checkpoints SET status='COMPLETED',
       candidate_sha=p_candidate_sha,output=p_result,updated_at=now()
      WHERE run_id=p_run_id AND step_key=p_step;
    RETURN jsonb_build_object('accepted',true,'idempotent',false);
END; $$;

REVOKE ALL ON FUNCTION public.crew_checkpoint_claim(text,text,text,text)
  FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.crew_checkpoint_complete(text,text,text,text,jsonb)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.crew_checkpoint_claim(text,text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.crew_checkpoint_complete(text,text,text,text,jsonb) TO service_role;
