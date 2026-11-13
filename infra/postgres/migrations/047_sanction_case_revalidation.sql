BEGIN;

ALTER FUNCTION public.decide_sanction_case(UUID,JSONB) RENAME TO sanction_decide_validated;
REVOKE ALL ON FUNCTION public.sanction_decide_validated(UUID,JSONB) FROM PUBLIC, bracket_app;

CREATE FUNCTION public.decide_sanction_case(target_case UUID, payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE target public.sanction_cases; source public.player_suspensions; fingerprint JSONB; version UUID;
    org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    actor UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
BEGIN
    SELECT * INTO target FROM public.sanction_cases WHERE id=target_case AND organization_id=org;
    IF target.id IS NULL THEN RAISE EXCEPTION 'SANCTION_NOT_FOUND' USING ERRCODE='P0002'; END IF;
    IF NOT (public.sanction_member_has_permission(org,'RESOLVE_SANCTION_CASES') OR public.sanction_platform_scope(target.id)) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_DENIED' USING ERRCODE='42501';
    END IF;
    target := public.sanction_lock_case(target_case);
    IF NOT (public.sanction_member_has_permission(org,'RESOLVE_SANCTION_CASES') OR public.sanction_platform_scope(target.id)) THEN
        RAISE EXCEPTION 'SANCTION_DECISION_DENIED' USING ERRCODE='42501';
    END IF;
    IF target.status='closed_by_rectification' THEN
        RETURN jsonb_build_object('id',target.id,'status',target.status);
    END IF;
    IF target.status='pending' THEN
        SELECT * INTO source FROM public.player_suspensions WHERE id=target.suspension_id AND organization_id=org;
        SELECT jsonb_object_agg(key,to_jsonb(source)->>key) INTO fingerprint
            FROM unnest(ARRAY['id','player_id','source_tournament_id','scope_type','matches_suspended',
                'source_type','origin_match_id','source_event_id','source_version_event_id']) AS key;
        IF source.status='cancelled' OR fingerprint IS DISTINCT FROM target.base_fingerprint THEN
            SELECT a.version_id INTO version FROM public.player_suspension_annulments a
                JOIN public.match_report_versions v ON v.id=a.version_id AND v.organization_id=a.organization_id
                WHERE a.suspension_id=source.id AND a.organization_id=org
                    AND v.match_id=source.origin_match_id AND source.source_type='match_event'
                ORDER BY v.version_number DESC LIMIT 1;
            IF version IS NULL THEN RAISE EXCEPTION 'SANCTION_STALE_BASE' USING ERRCODE='23514'; END IF;
            INSERT INTO public.sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason,rectification_version_id)
                VALUES (org,target.id,'closed_by_rectification',actor,'Source sanction changed by published rectification',version);
            PERFORM public.sanction_finalize_case(target.id);
            RETURN jsonb_build_object('id',target.id,'status','closed_by_rectification');
        END IF;
    END IF;
    RETURN public.sanction_decide_validated(target.id,payload);
END;
$$;
REVOKE ALL ON FUNCTION public.decide_sanction_case(UUID,JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.decide_sanction_case(UUID,JSONB) TO bracket_app;

COMMIT;
