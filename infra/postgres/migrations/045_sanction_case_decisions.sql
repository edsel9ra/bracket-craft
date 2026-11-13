BEGIN;

CREATE FUNCTION public.sanction_record_resolution(target_decision UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.sanction_case_decisions
        WHERE id=target_decision AND decision NOT IN ('maintain','reject')) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_CATALOG' USING ERRCODE='23514';
    END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_record_resolution(UUID) FROM PUBLIC;

CREATE FUNCTION public.decide_sanction_case(target_case UUID, payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.sanction_cases; source public.player_suspensions; previous public.sanction_case_decisions;
    org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    actor UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    platform_mode BOOLEAN; member UUID; decision_id UUID := gen_random_uuid(); after_duration INTEGER;
BEGIN
    SELECT * INTO target FROM public.sanction_cases WHERE id=target_case AND organization_id=org;
    IF target.id IS NULL THEN RAISE EXCEPTION 'SANCTION_NOT_FOUND' USING ERRCODE='P0002'; END IF;
    IF NOT (public.sanction_member_has_permission(org,'RESOLVE_SANCTION_CASES') OR public.sanction_platform_scope(target.id)) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_DENIED' USING ERRCODE='42501';
    END IF;
    target := public.sanction_lock_case(target_case);
    platform_mode := public.sanction_platform_scope(target.id);
    IF NOT (platform_mode OR public.sanction_member_has_permission(org,'RESOLVE_SANCTION_CASES')) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_DENIED' USING ERRCODE='42501';
    END IF;
    IF target.submitted_by_user_id=actor THEN RAISE EXCEPTION 'SANCTION_SELF_DECISION' USING ERRCODE='23514'; END IF;
    after_duration := CASE WHEN payload->>'decision'='approve' THEN target.proposed_duration
        WHEN payload->>'decision'='reduce' THEN (payload->>'after_duration')::INTEGER ELSE NULL END;
    IF payload->>'decision'='approve' AND payload->>'after_duration' IS NOT NULL
        AND (payload->>'after_duration')::INTEGER IS DISTINCT FROM target.proposed_duration THEN
        RAISE EXCEPTION 'SANCTION_DECISION_CATALOG' USING ERRCODE='23514';
    END IF;
    IF target.status <> 'pending' THEN
        SELECT * INTO previous FROM public.sanction_case_decisions WHERE case_id=target.id AND organization_id=org;
        IF target.status='resolved' AND previous.decided_by_user_id=actor AND previous.decision=payload->>'decision'
            AND previous.reason=payload->>'reason' AND previous.evidence_text IS NOT DISTINCT FROM payload->>'evidence_text'
            AND previous.evidence_links=COALESCE(payload->'evidence_links','[]'::JSONB)
            AND previous.before_duration=(payload->>'expected_base_duration')::INTEGER
            AND previous.after_duration IS NOT DISTINCT FROM after_duration THEN
            RETURN jsonb_build_object('id',target.id,'status','resolved');
        END IF;
        RAISE EXCEPTION 'SANCTION_CASE_NOT_PENDING' USING ERRCODE='23514';
    END IF;
    SELECT * INTO source FROM public.player_suspensions WHERE id=target.suspension_id AND organization_id=org;
    IF source.status='cancelled' OR target.base_duration <> (payload->>'expected_base_duration')::INTEGER THEN
        RAISE EXCEPTION 'SANCTION_STALE_BASE' USING ERRCODE='23514';
    END IF;
    IF platform_mode THEN
        PERFORM public.sanction_lock_platform_authorization(target.id);
    ELSE
        SELECT id INTO member FROM public.organization_users WHERE organization_id=org AND user_id=actor AND is_active;
    END IF;
    INSERT INTO public.sanction_case_decisions
        (id,organization_id,case_id,decided_by_user_id,decided_by_member_id,decided_as,authorization_id,
         decision,reason,evidence_text,evidence_links,before_duration,after_duration)
        VALUES (decision_id,org,target.id,actor,member,CASE WHEN platform_mode THEN 'platform_admin' ELSE 'member' END,
            CASE WHEN platform_mode THEN NULLIF(current_setting('app.sanction_authorization_id', true),'')::UUID ELSE NULL END,
            payload->>'decision',payload->>'reason',payload->>'evidence_text',COALESCE(payload->'evidence_links','[]'::JSONB),
            target.base_duration,after_duration);
    PERFORM public.sanction_record_resolution(decision_id);
    IF NOT platform_mode THEN
        INSERT INTO public.administrative_audit_logs(organization_id,entity_type,entity_id,action,payload,performed_by_user_id)
            VALUES (org,'sanction_cases',target.id,'DECIDE_SANCTION_CASE',
                jsonb_build_object('decision_id',decision_id,'decision',payload->>'decision'),actor);
    END IF;
    PERFORM public.sanction_finalize_case(target.id);
    RETURN jsonb_build_object('id',target.id,'status','resolved');
END;
$$;
REVOKE ALL ON FUNCTION public.decide_sanction_case(UUID,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.decide_sanction_case(UUID,JSONB) TO bracket_app;

COMMIT;
