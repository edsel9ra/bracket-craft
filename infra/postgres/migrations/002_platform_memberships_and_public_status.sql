BEGIN;

CREATE OR REPLACE FUNCTION public.platform_list_memberships(
    p_organization_id UUID,
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    organization_user_id UUID,
    user_id UUID,
    email VARCHAR,
    full_name VARCHAR,
    is_active BOOLEAN,
    role_codes TEXT[]
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF public.fn_platform_actor_role() IS NULL THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    RETURN QUERY
    SELECT ou.id,
           u.id,
           u.email,
           u.full_name,
           ou.is_active,
           COALESCE(ARRAY_AGG(DISTINCT rd.code ORDER BY rd.code) FILTER (WHERE rd.code IS NOT NULL), ARRAY[]::TEXT[])::TEXT[]
    FROM public.organization_users ou
    JOIN public.users u ON u.id = ou.user_id
    LEFT JOIN public.organization_user_roles our
      ON our.organization_user_id = ou.id
     AND our.organization_id = ou.organization_id
    LEFT JOIN public.roles r
      ON r.id = our.role_id
     AND r.organization_id = our.organization_id
    LEFT JOIN public.role_definitions rd ON rd.id = r.role_definition_id
    WHERE ou.organization_id = p_organization_id
    GROUP BY ou.id, u.id
    ORDER BY u.full_name, u.id
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 100))
    OFFSET GREATEST(COALESCE(p_offset, 0), 0);
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_create_membership(
    p_organization_id UUID,
    p_user_id UUID,
    p_role_code VARCHAR
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_actor_id UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    v_member_id UUID;
    v_role_id UUID;
    v_definition_id UUID;
    v_role_name VARCHAR;
    v_permissions JSONB;
BEGIN
    IF public.fn_platform_actor_role() <> 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.organizations WHERE id = p_organization_id AND is_active = TRUE) THEN
        RAISE EXCEPTION 'Organización no encontrada o suspendida' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.users WHERE id = p_user_id AND is_active = TRUE) THEN
        RAISE EXCEPTION 'Usuario no encontrado o desactivado' USING ERRCODE = '23514';
    END IF;

    SELECT id, name, system_permissions
    INTO STRICT v_definition_id, v_role_name, v_permissions
    FROM public.role_definitions
    WHERE code = p_role_code;

    INSERT INTO public.organization_users (organization_id, user_id, is_active)
    VALUES (p_organization_id, p_user_id, TRUE)
    RETURNING id INTO v_member_id;

    INSERT INTO public.roles (organization_id, role_definition_id, name, permissions)
    VALUES (p_organization_id, v_definition_id, v_role_name, v_permissions)
    ON CONFLICT (organization_id, name) DO NOTHING;

    SELECT id INTO v_role_id
    FROM public.roles
    WHERE organization_id = p_organization_id
      AND role_definition_id = v_definition_id;

    INSERT INTO public.organization_user_roles (organization_id, organization_user_id, role_id)
    VALUES (p_organization_id, v_member_id, v_role_id);

    INSERT INTO public.platform_audit_logs
        (actor_user_id, action, target_type, target_id, organization_id, payload)
    VALUES
        (v_actor_id, 'CREATE_MEMBERSHIP', 'organization_users', v_member_id,
         p_organization_id, jsonb_build_object('user_id', p_user_id, 'role_code', p_role_code));
    RETURN v_member_id;
END;
$$;

CREATE OR REPLACE VIEW public.v_public_tournaments
WITH (security_barrier = true) AS
SELECT tr.id, tr.name, tr.season, tr.start_date, tr.status
FROM public.tournaments tr
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
JOIN public.tournament_versions tv
  ON tv.id = tr.published_version_id
 AND tv.organization_id = tr.organization_id
 AND tv.tournament_id = tr.id
 AND tv.status = 'published'
WHERE tr.status IN ('published', 'live', 'finished');

CREATE OR REPLACE VIEW public.v_public_standings
WITH (security_barrier = true) AS
SELECT
    s.tournament_id, s.stage_id, st.name AS stage_name, st.stage_order,
    s.group_id, g.name AS group_name, s.team_id, t.name AS team_name,
    t.short_code, s.played, s.won, s.drawn, s.lost, s.goals_for,
    s.goals_against, s.goal_difference, s.points, s.fair_play_points,
    s.rank, s.calculated_at
FROM public.standings s
JOIN public.tournaments tr
  ON tr.id = s.tournament_id AND tr.organization_id = s.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id AND org.is_active = TRUE
JOIN public.stages st
  ON st.id = s.stage_id
 AND st.tournament_id = s.tournament_id
 AND st.organization_id = s.organization_id
 AND st.tournament_version_id = tr.published_version_id
LEFT JOIN public.groups g
  ON g.id = s.group_id AND g.stage_id = s.stage_id AND g.organization_id = s.organization_id
JOIN public.teams t ON t.id = s.team_id AND t.organization_id = s.organization_id
WHERE tr.status IN ('published', 'live', 'finished');

CREATE OR REPLACE VIEW public.v_public_matches
WITH (security_barrier = true) AS
SELECT
    m.id, m.tournament_id, m.stage_id, st.name AS stage_name, st.stage_order,
    m.group_id, g.name AS group_name, m.matchday, m.match_date,
    m.home_team_id, home_team.name AS home_team_name, home_team.short_code AS home_team_short_code,
    m.away_team_id, away_team.name AS away_team_name, away_team.short_code AS away_team_short_code,
    m.home_score_regular, m.away_score_regular, m.home_score, m.away_score,
    m.home_penalties, m.away_penalties, m.winner_team_id, m.status, m.resolution_type
FROM public.matches m
JOIN public.tournaments tr
  ON tr.id = m.tournament_id AND tr.organization_id = m.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id AND org.is_active = TRUE
JOIN public.stages st
  ON st.id = m.stage_id
 AND st.tournament_id = m.tournament_id
 AND st.organization_id = m.organization_id
 AND st.tournament_version_id = tr.published_version_id
LEFT JOIN public.groups g
  ON g.id = m.group_id AND g.stage_id = m.stage_id AND g.organization_id = m.organization_id
LEFT JOIN public.teams home_team
  ON home_team.id = m.home_team_id AND home_team.organization_id = m.organization_id
LEFT JOIN public.teams away_team
  ON away_team.id = m.away_team_id AND away_team.organization_id = m.organization_id
WHERE tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

REVOKE ALL ON FUNCTION public.platform_list_memberships(UUID, INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_create_membership(UUID, UUID, VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.platform_list_memberships(UUID, INTEGER, INTEGER) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.platform_create_membership(UUID, UUID, VARCHAR) TO bracket_app;

COMMIT;
