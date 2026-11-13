BEGIN;

CREATE FUNCTION public.authorize_realtime_recipients(
    p_organization_id UUID, p_candidates JSONB, p_event JSONB, p_evaluation_time TIMESTAMPTZ
)
RETURNS TABLE (user_id UUID, session_id UUID, decision TEXT)
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public
AS $$
DECLARE
    previous_org TEXT := current_setting('app.current_organization_id', true);
    previous_user TEXT := current_setting('app.current_user_id', true);
    previous_rectification TEXT := current_setting('app.rectification_authorization_id', true);
    previous_sanction TEXT := current_setting('app.sanction_authorization_id', true);
    actor RECORD;
    candidate JSONB;
    actor_id UUID;
    member_valid BOOLEAN;
    resource_valid BOOLEAN;
    event_valid BOOLEAN := FALSE;
    version_read BOOLEAN;
    operation_read BOOLEAN;
    target_match UUID;
    target_tournament UUID;
    target_version UUID;
    allowed_keys TEXT[];
    valid_sessions UUID[];
BEGIN
    IF jsonb_typeof(p_candidates) IS DISTINCT FROM 'array' OR jsonb_array_length(p_candidates) > 256
       OR p_evaluation_time IS NULL THEN
        RAISE EXCEPTION 'Invalid authorization batch' USING ERRCODE = '22023';
    END IF;
    BEGIN
        version_read := p_event->>'scope' = 'organization';
        operation_read := p_event->>'event_type' <> 'MATCH_REPORT_RECTIFIED';
        IF p_event ? 'scope' THEN
            event_valid := version_read AND p_event->>'event_type' IN
                ('MATCH_UPDATED', 'STANDINGS_UPDATED', 'MATCH_REPORT_RECTIFIED');
            allowed_keys := ARRAY['event_type','scope','match_id','tournament_id','version_id'];
            target_version := (p_event->>'version_id')::UUID;
            event_valid := event_valid AND target_version IS NOT NULL;
        ELSE
            version_read := FALSE;
            event_valid := p_event->>'event_type' IN ('MATCH_CLOSED','MATCH_UPDATED','STANDINGS_UPDATED');
            allowed_keys := ARRAY['event_type','match_id','tournament_id'];
        END IF;
        target_match := (p_event->>'match_id')::UUID;
        target_tournament := (p_event->>'tournament_id')::UUID;
        event_valid := event_valid AND target_match IS NOT NULL AND target_tournament IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM jsonb_object_keys(p_event) k WHERE NOT k = ANY(allowed_keys));
    EXCEPTION WHEN OTHERS THEN
        event_valid := FALSE;
    END;
    PERFORM set_config('app.rectification_authorization_id', '', true);
    PERFORM set_config('app.sanction_authorization_id', '', true);
    PERFORM set_config('app.current_organization_id', p_organization_id::TEXT, true);
    FOR actor IN SELECT value->>'user_id' AS actor_key, jsonb_agg(value) AS candidates
                 FROM jsonb_array_elements(p_candidates) GROUP BY value->>'user_id'
    LOOP
        BEGIN
            actor_id := actor.actor_key::UUID;
            PERFORM set_config('app.current_user_id', actor_id::TEXT, true);
            SELECT public.fn_verify_user_org_membership(p_organization_id) AND EXISTS (
                SELECT 1 FROM public.organization_users ou
                JOIN public.organization_user_roles our
                  ON our.organization_user_id = ou.id AND our.organization_id = ou.organization_id
                JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
                WHERE ou.organization_id = p_organization_id AND ou.user_id = actor_id AND ou.is_active
            ) INTO member_valid;
            resource_valid := FALSE;
            IF event_valid AND member_valid THEN
                SELECT EXISTS (
                    SELECT 1 FROM public.matches m
                    JOIN public.tournament_versions tv ON tv.id = m.tournament_version_id
                      AND tv.organization_id = m.organization_id
                    WHERE m.id = target_match AND m.organization_id = p_organization_id
                      AND m.tournament_id = target_tournament
                      AND (NOT operation_read OR (
                          tv.tournament_id = m.tournament_id AND EXISTS (
                              SELECT 1 FROM public.tournaments t JOIN public.stages st
                                ON st.organization_id = t.organization_id AND st.tournament_id = t.id
                              WHERE t.id = m.tournament_id AND t.organization_id = m.organization_id
                                AND st.id = m.stage_id AND st.tournament_version_id = m.tournament_version_id
                          )
                      ))
                      AND (NOT version_read OR (m.result_confirmed AND EXISTS (
                          SELECT 1 FROM public.match_report_versions v
                          JOIN public.match_report_rectification_requests r ON r.id = v.request_id
                            AND r.organization_id = v.organization_id AND r.match_id = v.match_id
                          WHERE v.id = target_version AND v.match_id = m.id
                            AND v.organization_id = m.organization_id
                      )))
                ) INTO resource_valid;
            END IF;
            SELECT COALESCE(array_agg(s.id), ARRAY[]::UUID[]) INTO valid_sessions
            FROM public.users u JOIN public.user_sessions s ON s.user_id=u.id
            WHERE u.id=actor_id AND u.is_active AND s.revoked_at IS NULL
                AND s.expires_at>p_evaluation_time
                AND s.id IN (SELECT CASE WHEN pg_input_is_valid(c->>'session_id','uuid')
                    THEN (c->>'session_id')::UUID END FROM jsonb_array_elements(actor.candidates) c);
            FOR candidate IN SELECT value FROM jsonb_array_elements(actor.candidates)
            LOOP
                user_id := actor_id;
                session_id := NULL;
                BEGIN
                    session_id := (candidate->>'session_id')::UUID;
                    decision := CASE WHEN member_valid AND resource_valid
                        AND session_id=ANY(valid_sessions) THEN 'ALLOW' ELSE 'DENY' END;
                    RETURN NEXT;
                EXCEPTION WHEN OTHERS THEN
                    decision := 'INDETERMINATE';
                    RETURN NEXT;
                END;
            END LOOP;
        EXCEPTION WHEN OTHERS THEN
            CONTINUE;
        END;
    END LOOP;
    PERFORM set_config('app.current_organization_id', COALESCE(previous_org, ''), true);
    PERFORM set_config('app.current_user_id', COALESCE(previous_user, ''), true);
    PERFORM set_config('app.rectification_authorization_id', COALESCE(previous_rectification, ''), true);
    PERFORM set_config('app.sanction_authorization_id', COALESCE(previous_sanction, ''), true);
END;
$$;

REVOKE ALL ON FUNCTION public.authorize_realtime_recipients(UUID, JSONB, JSONB, TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.authorize_realtime_recipients(UUID, JSONB, JSONB, TIMESTAMPTZ) TO bracket_app;

COMMIT;
