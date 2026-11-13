BEGIN;

CREATE OR REPLACE FUNCTION public.sanction_record_resolution(target_decision UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE decided public.sanction_case_decisions; target public.sanction_cases;
    source public.player_suspensions; served INTEGER; action TEXT; declarative BOOLEAN;
BEGIN
    SELECT * INTO decided FROM public.sanction_case_decisions WHERE id=target_decision;
    IF decided.decision IN ('maintain','reject') THEN RETURN; END IF;
    SELECT * INTO target FROM public.sanction_cases WHERE id=decided.case_id AND organization_id=decided.organization_id;
    SELECT * INTO source FROM public.player_suspensions WHERE id=target.suspension_id AND organization_id=target.organization_id;
    SELECT count(*) INTO served FROM public.player_suspension_serves
        WHERE organization_id=target.organization_id AND suspension_id=source.id AND NOT is_voided;
    action := CASE WHEN decided.decision='approve' THEN target.proposed_action ELSE decided.decision END;
    declarative := source.status='served' OR served >= target.base_duration;
    INSERT INTO public.sanction_resolutions(organization_id,case_id,decision_id,suspension_id,action,
        original_duration,before_duration,new_duration,served_count,is_declarative)
        VALUES (target.organization_id,target.id,decided.id,source.id,action,source.matches_suspended,
            target.base_duration,decided.after_duration,served,declarative);
    IF declarative THEN
        UPDATE public.player_suspensions SET status=CASE WHEN action='annul' THEN 'cancelled' ELSE 'served' END
            WHERE id=source.id AND organization_id=target.organization_id;
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_record_resolution(UUID) FROM PUBLIC;

COMMIT;
