BEGIN;

CREATE FUNCTION public.sanction_lock_case(target_case UUID)
RETURNS public.sanction_cases LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    target public.sanction_cases; source public.player_suspensions; origin public.matches;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('discipline:' || org::TEXT, 0));
    SELECT * INTO target FROM public.sanction_cases WHERE id=target_case AND organization_id=org;
    IF target.id IS NULL THEN RAISE EXCEPTION 'SANCTION_NOT_FOUND' USING ERRCODE='P0002'; END IF;
    SELECT * INTO source FROM public.player_suspensions WHERE id=target.suspension_id AND organization_id=org;
    IF source.origin_match_id IS NOT NULL THEN
        SELECT * INTO origin FROM public.matches WHERE id=source.origin_match_id AND organization_id=org;
        PERFORM 1 FROM public.stages WHERE id=origin.stage_id AND organization_id=org FOR UPDATE;
        PERFORM 1 FROM public.tournament_versions WHERE id=origin.tournament_version_id AND organization_id=org FOR UPDATE;
    ELSE
        PERFORM 1 FROM public.tournament_versions WHERE tournament_id=source.source_tournament_id
            AND organization_id=org ORDER BY id FOR UPDATE;
    END IF;
    PERFORM 1 FROM public.matches WHERE tournament_id=source.source_tournament_id
        AND organization_id=org ORDER BY id FOR UPDATE;
    PERFORM 1 FROM public.player_suspensions WHERE id=source.id AND organization_id=org FOR UPDATE;
    SELECT * INTO target FROM public.sanction_cases WHERE id=target_case AND organization_id=org FOR UPDATE;
    RETURN target;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_lock_case(UUID) FROM PUBLIC;

CREATE FUNCTION public.withdraw_sanction_case(target_case UUID, withdrawal_reason TEXT)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.sanction_cases; actor UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
BEGIN
    SELECT * INTO target FROM public.sanction_cases WHERE id=target_case
        AND organization_id=NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    IF target.id IS NULL THEN RAISE EXCEPTION 'SANCTION_NOT_FOUND' USING ERRCODE='P0002'; END IF;
    IF target.submitted_by_user_id IS DISTINCT FROM actor OR NOT public.sanction_member_has_permission(
        target.organization_id, CASE WHEN target.case_type='appeal' THEN 'SUBMIT_SANCTION_APPEALS' ELSE 'RESOLVE_SANCTION_CASES' END) THEN
        RAISE EXCEPTION 'SANCTION_WITHDRAWAL_DENIED' USING ERRCODE='42501';
    END IF;
    target := public.sanction_lock_case(target_case);
    IF target.submitted_by_user_id IS DISTINCT FROM actor OR NOT public.sanction_member_has_permission(
        target.organization_id, CASE WHEN target.case_type='appeal' THEN 'SUBMIT_SANCTION_APPEALS' ELSE 'RESOLVE_SANCTION_CASES' END) THEN
        RAISE EXCEPTION 'SANCTION_WITHDRAWAL_DENIED' USING ERRCODE='42501';
    END IF;
    IF withdrawal_reason IS NULL OR btrim(withdrawal_reason)='' THEN
        RAISE EXCEPTION 'SANCTION_REASON_REQUIRED' USING ERRCODE='23514';
    END IF;
    IF target.status='withdrawn' AND EXISTS (SELECT 1 FROM public.sanction_case_events WHERE case_id=target.id
        AND organization_id=target.organization_id AND event_type='withdrawn' AND reason=withdrawal_reason AND actor_user_id=actor) THEN
        RETURN jsonb_build_object('id',target.id,'status',target.status);
    END IF;
    IF target.status <> 'pending' THEN RAISE EXCEPTION 'SANCTION_CASE_NOT_PENDING' USING ERRCODE='23514'; END IF;
    INSERT INTO public.sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
        VALUES (target.organization_id,target.id,'withdrawn',actor,withdrawal_reason);
    PERFORM public.sanction_finalize_case(target.id);
    RETURN jsonb_build_object('id',target.id,'status','withdrawn');
END;
$$;
REVOKE ALL ON FUNCTION public.withdraw_sanction_case(UUID,TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.withdraw_sanction_case(UUID,TEXT) TO bracket_app;

COMMIT;
