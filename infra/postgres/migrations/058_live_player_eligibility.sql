BEGIN;

CREATE OR REPLACE FUNCTION public.match_live_ineligible_players(
    target_match UUID, target_players UUID[], as_of TIMESTAMPTZ DEFAULT statement_timestamp()
) RETURNS TABLE (player_id UUID)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    org UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    first_started TIMESTAMPTZ;
    suspension RECORD;
    snapshot RECORD;
    measure RECORD;
    has_resolutions BOOLEAN;
    has_snapshot BOOLEAN;
    has_measure BOOLEAN;
    current_status TEXT;
    previous_status TEXT;
    duration INTEGER;
    served INTEGER;
    blocked UUID[] := ARRAY[]::UUID[];
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.matches m
        WHERE m.id = target_match AND m.organization_id = org)
        OR NOT COALESCE(public.match_live_has_permission(org, target_match, 'OPERATE_MATCH_LIVE'), FALSE)
    THEN
        RAISE EXCEPTION 'LIVE_ELIGIBILITY_NOT_AUTHORIZED' USING ERRCODE = '42501';
    END IF;
    IF target_players IS NULL OR array_position(target_players, NULL) IS NOT NULL
        OR as_of IS NULL OR NOT isfinite(as_of)
    THEN
        RAISE EXCEPTION 'LIVE_ELIGIBILITY_INVALID_INPUT' USING ERRCODE = '22023';
    END IF;
    SELECT min(ms.created_at) INTO first_started FROM public.match_segments ms
        WHERE ms.match_id = target_match AND ms.organization_id = org;

    FOR suspension IN
        SELECT ps.* FROM public.player_suspensions ps
        JOIN public.matches m ON m.id = target_match AND m.organization_id = ps.organization_id
        WHERE ps.organization_id = org AND ps.player_id = ANY(target_players)
          AND (ps.scope_type = 'organization' OR ps.source_tournament_id = m.tournament_id)
          AND (EXISTS (SELECT 1 FROM public.rosters r WHERE r.organization_id = org
                AND r.tournament_id = m.tournament_id AND r.team_id IN (m.home_team_id, m.away_team_id)
                AND r.player_id = ps.player_id)
            OR EXISTS (SELECT 1 FROM public.match_rosters mr WHERE mr.organization_id = org
                AND mr.match_id = target_match AND mr.player_id = ps.player_id))
    LOOP
        current_status := suspension.status;
        duration := suspension.matches_suspended;
        SELECT count(*) INTO served FROM public.player_suspension_serves s
            WHERE s.organization_id = org AND s.suspension_id = suspension.id AND NOT s.is_voided;
        SELECT EXISTS (SELECT 1 FROM public.sanction_resolutions r
            WHERE r.organization_id = org AND r.suspension_id = suspension.id AND r.created_at <= as_of)
            INTO has_resolutions;
        IF has_resolutions THEN
            SELECT s.resolution_id, s.applicable_status INTO snapshot
                FROM public.sanction_match_eligibility s
                WHERE s.organization_id = org AND s.suspension_id = suspension.id AND s.match_id = target_match;
            has_snapshot := FOUND;
            IF has_snapshot THEN
                current_status := snapshot.applicable_status;
                SELECT r.action, r.new_duration INTO measure FROM public.sanction_resolutions r
                    WHERE r.organization_id = org AND r.suspension_id = suspension.id
                        AND r.id = snapshot.resolution_id AND r.created_at <= as_of;
                has_measure := FOUND;
            ELSE
                SELECT r.action, r.new_duration INTO measure FROM public.sanction_resolutions r
                    WHERE r.organization_id = org AND r.suspension_id = suspension.id AND r.created_at <= as_of
                      AND NOT EXISTS (SELECT 1 FROM public.sanction_case_events e
                        WHERE e.organization_id = org AND e.case_id = r.case_id
                            AND e.event_type = 'affected_by_rectification')
                      AND (r.is_declarative OR EXISTS (SELECT 1 FROM public.sanction_effect_applications a
                        WHERE a.organization_id = org AND a.resolution_id = r.id AND a.effective_at <= as_of
                            AND a.effective_at <= COALESCE(first_started, as_of)))
                    ORDER BY r.created_at DESC, r.id DESC LIMIT 1;
                has_measure := FOUND;
                IF first_started IS NOT NULL THEN
                    SELECT a.before_status INTO previous_status FROM public.sanction_effect_applications a
                        WHERE a.organization_id = org AND a.suspension_id = suspension.id
                            AND a.effective_at > first_started AND a.effective_at <= as_of
                        ORDER BY a.effective_at, a.id LIMIT 1;
                    current_status := COALESCE(previous_status, current_status);
                END IF;
            END IF;
            IF has_measure THEN
                IF measure.action = 'annul' THEN
                    duration := 0;
                    current_status := 'cancelled';
                ELSE
                    duration := measure.new_duration;
                END IF;
            END IF;
        END IF;
        IF current_status = 'active' AND duration > served THEN
            blocked := array_append(blocked, suspension.player_id);
        END IF;
    END LOOP;
    RETURN QUERY SELECT DISTINCT p.id FROM unnest(blocked) AS p(id) ORDER BY p.id;
END;
$$;
REVOKE ALL ON FUNCTION public.match_live_ineligible_players(UUID, UUID[], TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.match_live_ineligible_players(UUID, UUID[], TIMESTAMPTZ) TO bracket_app;

COMMIT;
