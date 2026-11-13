BEGIN;

CREATE FUNCTION public.sanction_can_close_match(target_org UUID, target_match UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT public.sanction_can_operate_match(target_org, target_match) OR COALESCE(
        target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND EXISTS (
            SELECT 1 FROM public.matches m
            JOIN public.organizations o ON o.id = m.organization_id AND o.is_active
            JOIN public.organization_users ou ON ou.organization_id = m.organization_id AND ou.is_active
            JOIN public.users u ON u.id = ou.user_id AND u.is_active
            JOIN public.organization_user_roles our ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
            JOIN public.roles r ON r.id = our.role_id AND r.organization_id = ou.organization_id
            JOIN public.role_definitions rd ON rd.id = r.role_definition_id
            WHERE m.id = target_match AND m.organization_id = target_org
                AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
                AND rd.code IN ('owner', 'administrator')
                AND r.permissions @> '["RESOLVE_MATCH_ADMINISTRATIVELY"]'::JSONB
        ), FALSE);
$$;
REVOKE ALL ON FUNCTION public.sanction_can_close_match(UUID, UUID) FROM PUBLIC;

CREATE FUNCTION public.sanction_can_read_match(target_org UUID, target_match UUID)
RETURNS BOOLEAN LANGUAGE SQL STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT COALESCE(target_org = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND EXISTS (SELECT 1 FROM public.matches WHERE id = target_match AND organization_id = target_org)
        AND (public.sanction_can_close_match(target_org, target_match)
            OR public.sanction_member_has_permission(target_org, 'REQUEST_MATCH_REPORT_RECTIFICATION')
            OR public.sanction_member_has_permission(target_org, 'APPROVE_MATCH_REPORT_RECTIFICATION')
            OR EXISTS (SELECT 1 FROM public.rectification_platform_scopes() a
                JOIN public.match_report_rectification_requests q ON q.id = a.request_id AND q.organization_id = a.organization_id
                WHERE a.organization_id = target_org AND q.match_id = target_match
                    AND a.id = NULLIF(current_setting('app.rectification_authorization_id', true), '')::UUID)), FALSE);
$$;
REVOKE ALL ON FUNCTION public.sanction_can_read_match(UUID, UUID) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.sanction_operational_facts(target_match UUID)
RETURNS TABLE (suspension_id UUID, player_id UUID, source_tournament_id UUID, scope_type TEXT,
    original_duration INTEGER, status TEXT, created_at TIMESTAMPTZ, origin_match_id UUID,
    serves JSONB, resolutions JSONB, applications JSONB, snapshot JSONB)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
BEGIN
    IF NOT public.sanction_can_read_match(org, target_match) THEN
        RAISE EXCEPTION 'SANCTION_OPERATION_DENIED' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY SELECT ps.id, ps.player_id, ps.source_tournament_id, ps.scope_type::TEXT,
        ps.matches_suspended, ps.status::TEXT, ps.created_at, ps.origin_match_id,
        COALESCE((SELECT jsonb_agg(jsonb_build_object('match_id', s.match_id, 'served_at', s.served_at) ORDER BY s.served_at, s.match_id)
            FROM public.player_suspension_serves s WHERE s.suspension_id = ps.id AND NOT s.is_voided), '[]'::JSONB),
        COALESCE((SELECT jsonb_agg(jsonb_build_object('id', r.id, 'action', r.action,
            'new_duration', r.new_duration, 'is_declarative', r.is_declarative, 'created_at', r.created_at,
            'excluded', EXISTS (SELECT 1 FROM public.sanction_case_events e WHERE e.case_id = r.case_id
                AND e.event_type = 'affected_by_rectification')) ORDER BY r.created_at, r.id)
            FROM public.sanction_resolutions r WHERE r.suspension_id = ps.id), '[]'::JSONB),
        COALESCE((SELECT jsonb_agg(jsonb_build_object('resolution_id', a.resolution_id,
            'match_id', a.match_id, 'effective_at', a.effective_at, 'before_status', a.before_status,
            'after_status', a.after_status) ORDER BY a.effective_at, a.id)
            FROM public.sanction_effect_applications a WHERE a.suspension_id = ps.id), '[]'::JSONB),
        (SELECT jsonb_build_object('effective_duration', s.effective_duration, 'applicable_status', s.applicable_status,
            'resolution_id', s.resolution_id, 'started_at', s.started_at, 'served_count', s.served_count)
            FROM public.sanction_match_eligibility s WHERE s.suspension_id = ps.id AND s.match_id = target_match)
    FROM public.player_suspensions ps
    JOIN public.matches m ON m.id = target_match AND m.organization_id = ps.organization_id
    WHERE ps.organization_id = org AND (ps.scope_type = 'organization' OR ps.source_tournament_id = m.tournament_id)
        AND (EXISTS (SELECT 1 FROM public.rosters r WHERE r.organization_id = org
                AND r.tournament_id = m.tournament_id AND r.team_id IN (m.home_team_id, m.away_team_id) AND r.player_id = ps.player_id)
            OR EXISTS (SELECT 1 FROM public.match_rosters mr WHERE mr.organization_id = org
                AND mr.match_id = target_match AND mr.player_id = ps.player_id))
    ORDER BY ps.id;
END;
$$;

COMMIT;
