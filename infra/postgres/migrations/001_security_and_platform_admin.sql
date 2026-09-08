BEGIN;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE public.organizations
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS public.user_sessions (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_active
    ON public.user_sessions (user_id, expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS public.platform_admins (
    user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE RESTRICT,
    role_code VARCHAR(40) NOT NULL
        CHECK (role_code IN ('platform_admin', 'platform_support')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.platform_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(100) NOT NULL,
    target_id UUID,
    organization_id UUID REFERENCES public.organizations(id) ON DELETE RESTRICT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_platform_audit_logs_created_at
    ON public.platform_audit_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_platform_audit_logs_target
    ON public.platform_audit_logs (target_type, target_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.fn_verify_user_org_membership(target_org_id UUID)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.organization_users ou
        JOIN public.organizations o ON o.id = ou.organization_id
        JOIN public.users u ON u.id = ou.user_id
        WHERE ou.organization_id = target_org_id
          AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
          AND ou.is_active = TRUE
          AND o.is_active = TRUE
          AND u.is_active = TRUE
    );
$$;

CREATE OR REPLACE FUNCTION public.list_user_organizations()
RETURNS TABLE (
    id UUID,
    name VARCHAR,
    slug VARCHAR,
    organization_user_id UUID
)
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT o.id, o.name, o.slug, ou.id
    FROM public.organizations o
    JOIN public.organization_users ou ON ou.organization_id = o.id
    JOIN public.users u ON u.id = ou.user_id
    WHERE ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
      AND ou.is_active = TRUE
      AND o.is_active = TRUE
      AND u.is_active = TRUE
    ORDER BY o.name;
$$;

CREATE OR REPLACE FUNCTION public.get_current_organization()
RETURNS TABLE (
    id UUID,
    name VARCHAR,
    slug VARCHAR
)
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT o.id, o.name, o.slug
    FROM public.organizations o
    JOIN public.users u
      ON u.id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
    WHERE o.id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
      AND o.is_active = TRUE
      AND u.is_active = TRUE
      AND EXISTS (
          SELECT 1
          FROM public.organization_users ou
          WHERE ou.organization_id = o.id
            AND ou.user_id = u.id
            AND ou.is_active = TRUE
      );
$$;

CREATE OR REPLACE FUNCTION public.fn_platform_actor_role()
RETURNS VARCHAR
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT pa.role_code
    FROM public.platform_admins pa
    JOIN public.users u ON u.id = pa.user_id
    WHERE pa.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
      AND pa.is_active = TRUE
      AND u.is_active = TRUE;
$$;

CREATE OR REPLACE FUNCTION public.get_platform_admin_context()
RETURNS TABLE (user_id UUID, role_code VARCHAR)
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT NULLIF(current_setting('app.current_user_id', true), '')::UUID,
           public.fn_platform_actor_role();
$$;

CREATE OR REPLACE FUNCTION public.platform_list_users(
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0,
    p_search TEXT DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    email VARCHAR,
    full_name VARCHAR,
    is_active BOOLEAN,
    created_at TIMESTAMPTZ,
    organization_count BIGINT
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
    SELECT u.id, u.email, u.full_name, u.is_active, u.created_at,
           COUNT(ou.id) FILTER (WHERE ou.is_active = TRUE AND o.is_active = TRUE)
    FROM public.users u
    LEFT JOIN public.organization_users ou ON ou.user_id = u.id
    LEFT JOIN public.organizations o ON o.id = ou.organization_id
    WHERE p_search IS NULL
       OR u.email ILIKE '%' || p_search || '%'
       OR u.full_name ILIKE '%' || p_search || '%'
    GROUP BY u.id
    ORDER BY u.created_at DESC, u.id
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 100))
    OFFSET GREATEST(COALESCE(p_offset, 0), 0);
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_list_organizations(
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0,
    p_search TEXT DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    name VARCHAR,
    slug VARCHAR,
    is_active BOOLEAN,
    created_at TIMESTAMPTZ,
    member_count BIGINT
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
    SELECT o.id, o.name, o.slug, o.is_active, o.created_at,
           COUNT(ou.id) FILTER (WHERE ou.is_active = TRUE AND u.is_active = TRUE)
    FROM public.organizations o
    LEFT JOIN public.organization_users ou ON ou.organization_id = o.id
    LEFT JOIN public.users u ON u.id = ou.user_id
    WHERE p_search IS NULL
       OR o.name ILIKE '%' || p_search || '%'
       OR o.slug ILIKE '%' || p_search || '%'
    GROUP BY o.id
    ORDER BY o.created_at DESC, o.id
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 100))
    OFFSET GREATEST(COALESCE(p_offset, 0), 0);
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_list_audit_logs(
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    id UUID,
    actor_user_id UUID,
    actor_email VARCHAR,
    action VARCHAR,
    target_type VARCHAR,
    target_id UUID,
    organization_id UUID,
    payload JSONB,
    created_at TIMESTAMPTZ
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
    SELECT pal.id, pal.actor_user_id, u.email, pal.action, pal.target_type,
           pal.target_id, pal.organization_id, pal.payload, pal.created_at
    FROM public.platform_audit_logs pal
    JOIN public.users u ON u.id = pal.actor_user_id
    ORDER BY pal.created_at DESC, pal.id DESC
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 50), 100))
    OFFSET GREATEST(COALESCE(p_offset, 0), 0);
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_set_user_active(
    p_target_user_id UUID,
    p_is_active BOOLEAN
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_actor_id UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    v_old_active BOOLEAN;
BEGIN
    IF public.fn_platform_actor_role() <> 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;
    IF p_target_user_id = v_actor_id AND p_is_active = FALSE THEN
        RAISE EXCEPTION 'No puedes desactivar tu propia cuenta administrativa' USING ERRCODE = '23514';
    END IF;

    SELECT is_active INTO v_old_active
    FROM public.users
    WHERE id = p_target_user_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF v_old_active IS NOT DISTINCT FROM p_is_active THEN
        RETURN TRUE;
    END IF;

    UPDATE public.users SET is_active = p_is_active WHERE id = p_target_user_id;
    IF p_is_active = FALSE THEN
        UPDATE public.user_sessions
        SET revoked_at = CURRENT_TIMESTAMP
        WHERE user_id = p_target_user_id AND revoked_at IS NULL;
    END IF;

    INSERT INTO public.platform_audit_logs
        (actor_user_id, action, target_type, target_id, payload)
    VALUES
        (v_actor_id, 'SET_USER_ACTIVE', 'users', p_target_user_id,
         jsonb_build_object('before', v_old_active, 'after', p_is_active));
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_set_organization_active(
    p_organization_id UUID,
    p_is_active BOOLEAN
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_actor_id UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    v_old_active BOOLEAN;
BEGIN
    IF public.fn_platform_actor_role() <> 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    SELECT is_active INTO v_old_active
    FROM public.organizations
    WHERE id = p_organization_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF v_old_active IS NOT DISTINCT FROM p_is_active THEN
        RETURN TRUE;
    END IF;

    UPDATE public.organizations SET is_active = p_is_active WHERE id = p_organization_id;
    INSERT INTO public.platform_audit_logs
        (actor_user_id, action, target_type, target_id, organization_id, payload)
    VALUES
        (v_actor_id, 'SET_ORGANIZATION_ACTIVE', 'organizations', p_organization_id,
         p_organization_id, jsonb_build_object('before', v_old_active, 'after', p_is_active));
    RETURN TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION public.platform_set_membership_active(
    p_organization_id UUID,
    p_organization_user_id UUID,
    p_is_active BOOLEAN
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_actor_id UUID := NULLIF(current_setting('app.current_user_id', true), '')::UUID;
    v_old_active BOOLEAN;
BEGIN
    IF public.fn_platform_actor_role() <> 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    SELECT ou.is_active INTO v_old_active
    FROM public.organization_users ou
    WHERE ou.id = p_organization_user_id
      AND ou.organization_id = p_organization_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;
    IF v_old_active IS NOT DISTINCT FROM p_is_active THEN
        RETURN TRUE;
    END IF;

    IF p_is_active = FALSE
       AND EXISTS (
           SELECT 1
           FROM public.organization_user_roles our
           JOIN public.roles r ON r.id = our.role_id AND r.organization_id = our.organization_id
           JOIN public.role_definitions rd ON rd.id = r.role_definition_id
           WHERE our.organization_id = p_organization_id
             AND our.organization_user_id = p_organization_user_id
             AND rd.code = 'owner'
       )
       AND NOT EXISTS (
           SELECT 1
           FROM public.organization_user_roles other_our
           JOIN public.roles other_r
             ON other_r.id = other_our.role_id
            AND other_r.organization_id = other_our.organization_id
           JOIN public.role_definitions other_rd ON other_rd.id = other_r.role_definition_id
           JOIN public.organization_users other_ou
             ON other_ou.id = other_our.organization_user_id
            AND other_ou.organization_id = other_our.organization_id
           WHERE other_our.organization_id = p_organization_id
             AND other_ou.is_active = TRUE
             AND other_our.organization_user_id <> p_organization_user_id
             AND other_rd.code = 'owner'
       ) THEN
        RAISE EXCEPTION 'La organización debe conservar al menos un propietario activo' USING ERRCODE = '23514';
    END IF;

    UPDATE public.organization_users
    SET is_active = p_is_active
    WHERE id = p_organization_user_id AND organization_id = p_organization_id;
    INSERT INTO public.platform_audit_logs
        (actor_user_id, action, target_type, target_id, organization_id, payload)
    VALUES
        (v_actor_id, 'SET_MEMBERSHIP_ACTIVE', 'organization_users', p_organization_user_id,
         p_organization_id, jsonb_build_object('before', v_old_active, 'after', p_is_active));
    RETURN TRUE;
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

CREATE OR REPLACE VIEW public.v_public_tournament_players
WITH (security_barrier = true) AS
SELECT
    r.tournament_id,
    p.id AS player_id,
    p.first_name,
    p.last_name,
    r.dorsal_number,
    r.team_id,
    (EXTRACT(YEAR FROM t.start_date) - EXTRACT(YEAR FROM p.birth_date))::INT AS public_age,
    CASE WHEN r.photo_consent THEN p.photo_url ELSE NULL END AS photo_url
FROM public.rosters r
JOIN public.players p ON p.id = r.player_id
JOIN public.tournaments t ON t.id = r.tournament_id
JOIN public.organizations org ON org.id = t.organization_id AND org.is_active = TRUE
WHERE r.is_active = TRUE
  AND t.status IN ('published', 'live', 'finished');

CREATE OR REPLACE VIEW public.v_public_standings
WITH (security_barrier = true) AS
SELECT
    s.tournament_id,
    s.stage_id,
    st.name AS stage_name,
    st.stage_order,
    s.group_id,
    g.name AS group_name,
    s.team_id,
    t.name AS team_name,
    t.short_code,
    s.played,
    s.won,
    s.drawn,
    s.lost,
    s.goals_for,
    s.goals_against,
    s.goal_difference,
    s.points,
    s.fair_play_points,
    s.rank,
    s.calculated_at
FROM public.standings s
JOIN public.tournaments tr
  ON tr.id = s.tournament_id
 AND tr.organization_id = s.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
JOIN public.stages st
  ON st.id = s.stage_id
 AND st.tournament_id = s.tournament_id
 AND st.organization_id = s.organization_id
 AND st.tournament_version_id = tr.published_version_id
LEFT JOIN public.groups g
  ON g.id = s.group_id
 AND g.stage_id = s.stage_id
 AND g.organization_id = s.organization_id
JOIN public.teams t
  ON t.id = s.team_id
 AND t.organization_id = s.organization_id
WHERE tr.status IN ('published', 'live', 'finished');

CREATE OR REPLACE VIEW public.v_public_matches
WITH (security_barrier = true) AS
SELECT
    m.id,
    m.tournament_id,
    m.stage_id,
    st.name AS stage_name,
    st.stage_order,
    m.group_id,
    g.name AS group_name,
    m.matchday,
    m.match_date,
    m.home_team_id,
    home_team.name AS home_team_name,
    home_team.short_code AS home_team_short_code,
    m.away_team_id,
    away_team.name AS away_team_name,
    away_team.short_code AS away_team_short_code,
    m.home_score_regular,
    m.away_score_regular,
    m.home_score,
    m.away_score,
    m.home_penalties,
    m.away_penalties,
    m.winner_team_id,
    m.status,
    m.resolution_type
FROM public.matches m
JOIN public.tournaments tr
  ON tr.id = m.tournament_id
 AND tr.organization_id = m.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
JOIN public.stages st
  ON st.id = m.stage_id
 AND st.tournament_id = m.tournament_id
 AND st.organization_id = m.organization_id
 AND st.tournament_version_id = tr.published_version_id
LEFT JOIN public.groups g
  ON g.id = m.group_id
 AND g.stage_id = m.stage_id
 AND g.organization_id = m.organization_id
LEFT JOIN public.teams home_team
  ON home_team.id = m.home_team_id
 AND home_team.organization_id = m.organization_id
LEFT JOIN public.teams away_team
  ON away_team.id = m.away_team_id
 AND away_team.organization_id = m.organization_id
WHERE tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

REVOKE ALL ON public.platform_admins, public.platform_audit_logs FROM PUBLIC;
REVOKE ALL ON public.user_sessions FROM PUBLIC;
GRANT SELECT (id, email, password_hash, full_name, is_active) ON public.users TO bracket_app;
GRANT SELECT (id, user_id, expires_at, revoked_at) ON public.user_sessions TO bracket_app;
GRANT INSERT (id, user_id, expires_at) ON public.user_sessions TO bracket_app;
GRANT UPDATE (revoked_at) ON public.user_sessions TO bracket_app;

REVOKE ALL ON FUNCTION public.fn_platform_actor_role() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_platform_admin_context() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_list_users(INTEGER, INTEGER, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_list_organizations(INTEGER, INTEGER, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_list_audit_logs(INTEGER, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_set_user_active(UUID, BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_set_organization_active(UUID, BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.platform_set_membership_active(UUID, UUID, BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_platform_admin_context() TO bracket_app;
GRANT EXECUTE ON FUNCTION public.platform_list_users(INTEGER, INTEGER, TEXT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.platform_list_organizations(INTEGER, INTEGER, TEXT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.platform_list_audit_logs(INTEGER, INTEGER) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.platform_set_user_active(UUID, BOOLEAN) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.platform_set_organization_active(UUID, BOOLEAN) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.platform_set_membership_active(UUID, UUID, BOOLEAN) TO bracket_app;

COMMIT;
