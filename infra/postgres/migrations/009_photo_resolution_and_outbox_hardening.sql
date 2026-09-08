BEGIN;

ALTER TABLE public.rosters
    ADD COLUMN IF NOT EXISTS photo_object_key TEXT;

ALTER TABLE public.matches
    ADD COLUMN IF NOT EXISTS resolution_reason TEXT;

-- Keep historical administrative results readable while requiring a real reason
-- for every new administrative resolution.
UPDATE public.matches
SET resolution_reason = 'Legacy administrative resolution; reason not recorded'
WHERE resolution_type = 'administrative'
  AND NULLIF(BTRIM(resolution_reason), '') IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_roster_photo_consent'
          AND conrelid = 'public.rosters'::regclass
    ) THEN
        ALTER TABLE public.rosters
            ADD CONSTRAINT chk_roster_photo_consent
            CHECK (photo_consent = TRUE OR photo_object_key IS NULL);
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_administrative_resolution_reason'
          AND conrelid = 'public.matches'::regclass
    ) THEN
        ALTER TABLE public.matches
            ADD CONSTRAINT chk_administrative_resolution_reason
            CHECK (
                (
                    resolution_type = 'administrative'
                    AND resolution_reason IS NOT NULL
                    AND LENGTH(BTRIM(resolution_reason)) BETWEEN 1 AND 1000
                )
                OR (
                    resolution_type IS DISTINCT FROM 'administrative'
                    AND resolution_reason IS NULL
                )
            );
    END IF;
END
$$;

UPDATE public.role_definitions
SET system_permissions = system_permissions || '["RESOLVE_MATCH_ADMINISTRATIVELY"]'::jsonb
WHERE code IN ('owner', 'administrator')
  AND NOT system_permissions @> '["RESOLVE_MATCH_ADMINISTRATIVELY"]'::jsonb;

UPDATE public.roles r
SET permissions = r.permissions || '["RESOLVE_MATCH_ADMINISTRATIVELY"]'::jsonb
FROM public.role_definitions rd
WHERE rd.id = r.role_definition_id
  AND rd.code IN ('owner', 'administrator')
  AND NOT r.permissions @> '["RESOLVE_MATCH_ADMINISTRATIVELY"]'::jsonb;

CREATE OR REPLACE FUNCTION public.set_roster_photo_object(
    p_roster_id UUID,
    p_photo_object_key TEXT
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_organization_id UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    v_tournament_id UUID;
    v_old_key TEXT;
    v_expected_prefix TEXT;
BEGIN
    IF v_organization_id IS NULL
       OR NOT public.fn_verify_user_org_membership(v_organization_id)
    THEN
        RAISE EXCEPTION 'Membresía no válida' USING ERRCODE = '42501';
    END IF;

    SELECT r.tournament_id, r.photo_object_key
    INTO STRICT v_tournament_id, v_old_key
    FROM public.rosters r
    WHERE r.id = p_roster_id
      AND r.organization_id = v_organization_id;

    IF p_photo_object_key IS NOT NULL THEN
        v_expected_prefix := 'private/organizations/'
            || v_organization_id::TEXT
            || '/tournaments/'
            || v_tournament_id::TEXT
            || '/rosters/'
            || p_roster_id::TEXT
            || '/';
        IF LEFT(p_photo_object_key, LENGTH(v_expected_prefix)) <> v_expected_prefix
           OR POSITION('..' IN p_photo_object_key) > 0
        THEN
            RAISE EXCEPTION 'La clave de la foto no pertenece a la plantilla' USING ERRCODE = '42501';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM public.rosters r
            WHERE r.id = p_roster_id
              AND r.organization_id = v_organization_id
              AND r.photo_consent = TRUE
        ) THEN
            RAISE EXCEPTION 'No existe consentimiento para cargar la foto' USING ERRCODE = '23514';
        END IF;
    END IF;

    UPDATE public.rosters
    SET photo_object_key = p_photo_object_key
    WHERE id = p_roster_id
      AND organization_id = v_organization_id;
    RETURN v_old_key;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'La plantilla no fue encontrada' USING ERRCODE = '23503';
END;
$$;

CREATE OR REPLACE FUNCTION public.set_roster_photo_consent(
    p_roster_id UUID,
    p_photo_consent BOOLEAN
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_organization_id UUID := NULLIF(current_setting('app.current_organization_id', true), '')::UUID;
    v_old_key TEXT;
BEGIN
    IF v_organization_id IS NULL
       OR NOT public.fn_verify_user_org_membership(v_organization_id)
    THEN
        RAISE EXCEPTION 'Membresía no válida' USING ERRCODE = '42501';
    END IF;

    SELECT r.photo_object_key
    INTO STRICT v_old_key
    FROM public.rosters r
    WHERE r.id = p_roster_id
      AND r.organization_id = v_organization_id;

    UPDATE public.rosters
    SET photo_consent = p_photo_consent,
        photo_object_key = CASE WHEN p_photo_consent THEN photo_object_key ELSE NULL END
    WHERE id = p_roster_id
      AND organization_id = v_organization_id;
    RETURN v_old_key;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'La plantilla no fue encontrada' USING ERRCODE = '23503';
END;
$$;

CREATE OR REPLACE FUNCTION public.validate_match_event_context()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_home_team_id UUID;
    v_away_team_id UUID;
    v_match_status VARCHAR(30);
    v_segment_start INT;
    v_segment_end INT;
    v_segment_status VARCHAR(20);
BEGIN
    SELECT m.home_team_id, m.away_team_id, m.status
    INTO STRICT v_home_team_id, v_away_team_id, v_match_status
    FROM public.matches m
    WHERE m.id = NEW.match_id
      AND m.organization_id = NEW.organization_id;

    IF v_match_status IN ('finished', 'cancelled', 'administrative_resolution') THEN
        RAISE EXCEPTION 'El partido no admite nuevos eventos';
    END IF;
    IF NEW.team_id IS DISTINCT FROM v_home_team_id
       AND NEW.team_id IS DISTINCT FROM v_away_team_id
    THEN
        RAISE EXCEPTION 'El evento pertenece a un equipo que no participa en el partido';
    END IF;
    IF NEW.beneficiary_team_id IS NOT NULL
       AND NEW.beneficiary_team_id IS DISTINCT FROM v_home_team_id
       AND NEW.beneficiary_team_id IS DISTINCT FROM v_away_team_id
    THEN
        RAISE EXCEPTION 'El equipo beneficiario no participa en el partido';
    END IF;

    SELECT ms.minute_start, ms.minute_end, ms.status
    INTO STRICT v_segment_start, v_segment_end, v_segment_status
    FROM public.match_segments ms
    WHERE ms.id = NEW.segment_id
      AND ms.match_id = NEW.match_id
      AND ms.organization_id = NEW.organization_id;
    IF v_segment_status NOT IN ('active', 'completed') THEN
        RAISE EXCEPTION 'No se pueden registrar eventos en un segmento interrumpido';
    END IF;
    IF NEW.minute < v_segment_start
       OR (v_segment_end IS NOT NULL AND NEW.minute > v_segment_end)
    THEN
        RAISE EXCEPTION 'El evento está fuera del intervalo de su segmento';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.match_rosters mr
        WHERE mr.match_id = NEW.match_id
          AND mr.organization_id = NEW.organization_id
          AND mr.player_id = NEW.player_id
          AND mr.team_id = NEW.team_id
          AND mr.is_valid = TRUE
    ) THEN
        RAISE EXCEPTION 'El jugador del evento no está en la planilla válida';
    END IF;
    RETURN NEW;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'El partido o segmento del evento no existe en la organización';
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_match_event_context ON public.match_events;
CREATE TRIGGER trg_validate_match_event_context
BEFORE INSERT OR UPDATE ON public.match_events
FOR EACH ROW EXECUTE FUNCTION public.validate_match_event_context();

CREATE OR REPLACE VIEW public.v_public_tournament_players
WITH (security_barrier = true) AS
SELECT
    r.tournament_id,
    p.id AS player_id,
    p.first_name,
    p.last_name,
    r.dorsal_number,
    r.team_id,
    (
        EXTRACT(YEAR FROM t.start_date)
        - EXTRACT(YEAR FROM p.birth_date)
    )::INT AS public_age,
    CASE WHEN r.photo_consent THEN r.photo_object_key ELSE NULL END AS photo_url
FROM public.rosters r
JOIN public.players p ON p.id = r.player_id
JOIN public.tournaments t ON t.id = r.tournament_id
JOIN public.organizations org ON org.id = t.organization_id AND org.is_active = TRUE
WHERE r.is_active = TRUE
  AND t.status IN ('published', 'live', 'finished');

CREATE OR REPLACE VIEW public.v_public_match_lineups_unpublished
WITH (security_barrier = true) AS
WITH public_team_lineups AS (
    SELECT DISTINCT ON (tl.match_id, tl.team_id)
           tl.match_id,
           tl.segment_id,
           tl.team_id,
           tl.formation_code
    FROM public.match_team_lineups tl
    JOIN public.match_segments ms
      ON ms.id = tl.segment_id
     AND ms.match_id = tl.match_id
     AND ms.organization_id = tl.organization_id
    JOIN public.matches m
      ON m.id = tl.match_id
     AND m.organization_id = tl.organization_id
    JOIN public.tournaments tr
      ON tr.id = m.tournament_id
     AND tr.organization_id = m.organization_id
    JOIN public.organizations org
      ON org.id = tr.organization_id
     AND org.is_active = TRUE
    WHERE tl.is_public = TRUE
      AND tl.published_at IS NOT NULL
      AND tr.status IN ('published', 'live', 'finished')
      AND m.tournament_version_id = tr.published_version_id
      AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution')
      AND EXISTS (
          SELECT 1
          FROM public.match_lineup_snapshots ls
          WHERE ls.match_id = tl.match_id
            AND ls.segment_id = tl.segment_id
            AND ls.team_id = tl.team_id
            AND ls.organization_id = tl.organization_id
      )
    ORDER BY tl.match_id, tl.team_id, ms.segment_number, tl.published_at, tl.id
), tactical_rows AS (
    SELECT
        m.id AS match_id,
        m.tournament_id,
        tl.segment_id,
        tl.team_id,
        team.name AS team_name,
        CASE WHEN m.home_team_id = tl.team_id THEN 'home' ELSE 'away' END AS side,
        tl.formation_code,
        ls.player_id,
        p.first_name,
        p.last_name,
        roster.dorsal_number,
        CASE WHEN ls.is_starter THEN 'starter' ELSE 'substitute' END AS role,
        ls.position_slot,
        CASE WHEN roster.photo_consent THEN roster.photo_object_key ELSE NULL END AS photo_url
    FROM public_team_lineups tl
    JOIN public.matches m ON m.id = tl.match_id
    JOIN public.teams team
      ON team.id = tl.team_id
     AND team.organization_id = m.organization_id
    JOIN public.match_lineup_snapshots ls
      ON ls.match_id = tl.match_id
     AND ls.segment_id = tl.segment_id
     AND ls.team_id = tl.team_id
     AND ls.organization_id = m.organization_id
    JOIN public.players p ON p.id = ls.player_id
    LEFT JOIN LATERAL (
        SELECT r.dorsal_number, r.photo_consent, r.photo_object_key
        FROM public.rosters r
        WHERE r.tournament_id = m.tournament_id
          AND r.organization_id = m.organization_id
          AND r.team_id = ls.team_id
          AND r.player_id = ls.player_id
        ORDER BY r.is_active DESC, r.valid_from DESC, r.id DESC
        LIMIT 1
    ) roster ON TRUE
), classic_rows AS (
    SELECT
        m.id AS match_id,
        m.tournament_id,
        NULL::UUID AS segment_id,
        mr.team_id,
        team.name AS team_name,
        CASE WHEN m.home_team_id = mr.team_id THEN 'home' ELSE 'away' END AS side,
        NULL::VARCHAR(20) AS formation_code,
        mr.player_id,
        p.first_name,
        p.last_name,
        r.dorsal_number,
        mr.role,
        NULL::VARCHAR(20) AS position_slot,
        CASE WHEN r.photo_consent THEN r.photo_object_key ELSE NULL END AS photo_url
    FROM public.match_rosters mr
    JOIN public.matches m
      ON m.id = mr.match_id
     AND m.tournament_id = mr.tournament_id
     AND m.organization_id = mr.organization_id
    JOIN public.tournaments tr
      ON tr.id = m.tournament_id
     AND tr.organization_id = m.organization_id
    JOIN public.organizations org
      ON org.id = tr.organization_id
     AND org.is_active = TRUE
    JOIN public.rosters r
      ON r.id = mr.roster_id
     AND r.organization_id = mr.organization_id
    JOIN public.players p ON p.id = mr.player_id
    JOIN public.teams team
      ON team.id = mr.team_id
     AND team.organization_id = mr.organization_id
    WHERE mr.is_valid = TRUE
      AND tr.status IN ('published', 'live', 'finished')
      AND m.tournament_version_id = tr.published_version_id
      AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution')
      AND NOT EXISTS (
          SELECT 1
          FROM public_team_lineups tl
          WHERE tl.match_id = mr.match_id
            AND tl.team_id = mr.team_id
      )
)
SELECT * FROM tactical_rows
UNION ALL
SELECT * FROM classic_rows;

CREATE OR REPLACE FUNCTION public.requeue_outbox_events(p_limit INT DEFAULT 100)
RETURNS INT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_count INT;
BEGIN
    IF public.fn_platform_actor_role() <> 'platform_admin' THEN
        RAISE EXCEPTION 'Permiso de plataforma requerido' USING ERRCODE = '42501';
    END IF;

    WITH candidates AS (
        SELECT oe.id
        FROM public.outbox_events oe
        WHERE oe.status = 'failed'
           OR (
               oe.status = 'processing'
               AND oe.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
           )
        ORDER BY oe.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 100), 1000))
    )
    UPDATE public.outbox_events oe
    SET status = 'pending',
        attempts = 0,
        available_at = CURRENT_TIMESTAMP,
        last_error = NULL,
        locked_at = NULL,
        processed_at = NULL
    FROM candidates
    WHERE oe.id = candidates.id;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

REVOKE SELECT (photo_url) ON public.players FROM bracket_app;
REVOKE UPDATE (photo_url) ON public.players FROM bracket_app;
GRANT UPDATE (photo_object_key, photo_consent) ON public.rosters TO bracket_app;
REVOKE ALL ON FUNCTION public.set_roster_photo_object(UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.set_roster_photo_consent(UUID, BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.requeue_outbox_events(INT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.set_roster_photo_object(UUID, TEXT) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.set_roster_photo_consent(UUID, BOOLEAN) TO bracket_app;
GRANT EXECUTE ON FUNCTION public.requeue_outbox_events(INT) TO bracket_app;

COMMIT;
