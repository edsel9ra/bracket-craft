BEGIN;

CREATE FUNCTION public.sanction_platform_history(target_case UUID)
RETURNS JSONB LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE target public.sanction_cases; result JSONB;
BEGIN
    IF NOT public.sanction_platform_scope(target_case) THEN
        RAISE EXCEPTION 'SANCTION_AUTHORIZATION_REQUIRED' USING ERRCODE='42501';
    END IF;
    SELECT * INTO target FROM public.sanction_cases WHERE id=target_case
        AND organization_id=NULLIF(current_setting('app.current_organization_id',true),'')::UUID;
    SELECT jsonb_build_object('source',public.sanction_platform_source(target.id) || jsonb_build_object('source_type',ps.source_type),
        'serves',COALESCE((SELECT jsonb_agg(jsonb_build_object('match_id',s.match_id,'served_at',s.served_at,'is_voided',s.is_voided)
            ORDER BY s.served_at,s.match_id) FROM public.player_suspension_serves s
            WHERE s.suspension_id=ps.id AND s.organization_id=target.organization_id),'[]'::JSONB),
        'resolutions',COALESCE((SELECT jsonb_agg(to_jsonb(r) || jsonb_build_object('excluded',EXISTS (
            SELECT 1 FROM public.sanction_case_events e WHERE e.case_id=r.case_id AND e.organization_id=r.organization_id
                AND e.event_type='affected_by_rectification')) ORDER BY r.created_at,r.id)
            FROM public.sanction_resolutions r WHERE r.case_id=target.id AND r.organization_id=target.organization_id),'[]'::JSONB),
        'applications',COALESCE((SELECT jsonb_agg(jsonb_build_object('resolution_id',a.resolution_id,'match_id',a.match_id,
            'effective_at',a.effective_at,'before_status',a.before_status,'after_status',a.after_status) ORDER BY a.effective_at,a.id)
            FROM public.sanction_effect_applications a JOIN public.sanction_resolutions r
                ON r.id=a.resolution_id AND r.organization_id=a.organization_id
            WHERE r.case_id=target.id AND a.organization_id=target.organization_id),'[]'::JSONB)) INTO result
        FROM public.player_suspensions ps WHERE ps.id=target.suspension_id AND ps.organization_id=target.organization_id;
    RETURN result;
END;
$$;
REVOKE ALL ON FUNCTION public.sanction_platform_history(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.sanction_platform_history(UUID) TO bracket_app;

COMMIT;
