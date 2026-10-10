-- Approved TSAND-only Jarvis V2 CrewAI review, one total $0.15 budget.
-- $0.15 total across all retries for the same milestone and individual run.
-- No database or production application credentials on GitHub runner.
CREATE OR REPLACE FUNCTION public.crew_budget_reserve_jarvis_v2(
  p_run_id text, p_milestone text, p_key text, p_amount numeric
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_limit numeric(12,6) := 0.150000;
  v_run_cap numeric(12,6);
  v_milestone_cap numeric(12,6);
BEGIN
  IF p_milestone <> 'JARVIS_V2_REVIEW_20261010'
     OR p_amount IS NULL OR p_amount <= 0 OR p_amount > 0.025000
     OR p_run_id IS NULL OR p_key IS NULL THEN
     RAISE EXCEPTION 'Canary scope or per-call budget limit refused';
  END IF;
  INSERT INTO crew_budget.milestones(key,cap)
    VALUES(p_milestone,v_limit) ON CONFLICT DO NOTHING;
  INSERT INTO crew_budget.runs(run_id,milestone_key,cap)
    VALUES(p_run_id,p_milestone,v_limit) ON CONFLICT DO NOTHING;
  SELECT cap INTO STRICT v_milestone_cap
    FROM crew_budget.milestones WHERE key=p_milestone FOR UPDATE;
  SELECT cap INTO STRICT v_run_cap
    FROM crew_budget.runs WHERE run_id=p_run_id FOR UPDATE;
  IF v_milestone_cap > v_limit OR v_run_cap > v_limit THEN
    RAISE EXCEPTION 'Unsafe canary budget cap';
  END IF;
  RETURN public.crew_budget_reserve(p_run_id,p_milestone,p_key,p_amount);
END $$;

REVOKE ALL ON FUNCTION public.crew_budget_reserve_jarvis_v2(text,text,text,numeric)
  FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.crew_budget_reserve_jarvis_v2(text,text,text,numeric)
  TO service_role;
