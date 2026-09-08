BEGIN;

ALTER TABLE matches DROP CONSTRAINT IF EXISTS chk_penalties_consistency;
ALTER TABLE matches
    ADD CONSTRAINT chk_penalties_consistency CHECK (
        CASE
            WHEN resolution_type = 'penalties' THEN
                home_penalties IS NOT NULL
                AND away_penalties IS NOT NULL
                AND home_penalties <> away_penalties
                AND home_score IS NOT NULL
                AND away_score IS NOT NULL
                AND home_score = away_score
            ELSE
                home_penalties IS NULL AND away_penalties IS NULL
        END
    ) NOT VALID;
ALTER TABLE matches VALIDATE CONSTRAINT chk_penalties_consistency;

CREATE INDEX IF NOT EXISTS idx_organization_users_user_active
    ON organization_users (user_id, organization_id)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_matches_tournament_schedule
    ON matches (organization_id, tournament_id, tournament_version_id, stage_id, match_date, matchday, id);

CREATE INDEX IF NOT EXISTS idx_standings_tournament_rank
    ON standings (organization_id, tournament_id, stage_id, group_id, rank, team_id);

CREATE INDEX IF NOT EXISTS idx_outbox_pending_available
    ON outbox_events (available_at, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_outbox_processing_locked
    ON outbox_events (locked_at, created_at)
    WHERE status = 'processing';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_stage_team_group'
          AND conrelid = 'stage_teams'::regclass
    ) THEN
        ALTER TABLE stage_teams
            ADD CONSTRAINT fk_stage_team_group
            FOREIGN KEY (group_id, stage_id, organization_id)
            REFERENCES groups(id, stage_id, organization_id) ON DELETE RESTRICT;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_standing_group'
          AND conrelid = 'standings'::regclass
    ) THEN
        ALTER TABLE standings
            ADD CONSTRAINT fk_standing_group
            FOREIGN KEY (group_id, stage_id, organization_id)
            REFERENCES groups(id, stage_id, organization_id) ON DELETE RESTRICT;
    END IF;
END;
$$;

ALTER TABLE organization_users FORCE ROW LEVEL SECURITY;
ALTER TABLE roles FORCE ROW LEVEL SECURITY;
ALTER TABLE organization_user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE tournament_user_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE venues FORCE ROW LEVEL SECURITY;
ALTER TABLE tournaments FORCE ROW LEVEL SECURITY;
ALTER TABLE tournament_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE stages FORCE ROW LEVEL SECURITY;
ALTER TABLE stage_edges FORCE ROW LEVEL SECURITY;
ALTER TABLE groups FORCE ROW LEVEL SECURITY;
ALTER TABLE phase_slots FORCE ROW LEVEL SECURITY;
ALTER TABLE teams FORCE ROW LEVEL SECURITY;
ALTER TABLE tournament_teams FORCE ROW LEVEL SECURITY;
ALTER TABLE rosters FORCE ROW LEVEL SECURITY;
ALTER TABLE stage_teams FORCE ROW LEVEL SECURITY;
ALTER TABLE matches FORCE ROW LEVEL SECURITY;
ALTER TABLE match_officials FORCE ROW LEVEL SECURITY;
ALTER TABLE match_segments FORCE ROW LEVEL SECURITY;
ALTER TABLE match_rosters FORCE ROW LEVEL SECURITY;
ALTER TABLE match_lineup_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE match_segment_team_state FORCE ROW LEVEL SECURITY;
ALTER TABLE match_events FORCE ROW LEVEL SECURITY;
ALTER TABLE player_suspensions FORCE ROW LEVEL SECURITY;
ALTER TABLE player_suspension_serves FORCE ROW LEVEL SECURITY;
ALTER TABLE standings FORCE ROW LEVEL SECURITY;
ALTER TABLE advancement_links FORCE ROW LEVEL SECURITY;
ALTER TABLE ranking_draw_resolutions FORCE ROW LEVEL SECURITY;
ALTER TABLE administrative_audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION validate_advancement_link_context()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    source_tournament_id UUID;
    source_version_id UUID;
    target_tournament_id UUID;
    target_version_id UUID;
BEGIN
    SELECT tournament_id, tournament_version_id
    INTO STRICT source_tournament_id, source_version_id
    FROM matches
    WHERE id = NEW.source_match_id AND organization_id = NEW.organization_id;

    SELECT tournament_id, tournament_version_id
    INTO STRICT target_tournament_id, target_version_id
    FROM matches
    WHERE id = NEW.target_match_id AND organization_id = NEW.organization_id;

    IF source_tournament_id IS DISTINCT FROM target_tournament_id
       OR source_version_id IS DISTINCT FROM target_version_id
    THEN
        RAISE EXCEPTION 'Los enlaces de advancement deben pertenecer al mismo torneo y versión';
    END IF;
    RETURN NEW;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'Los partidos del enlace de advancement no existen en la organización';
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_advancement_link_context ON advancement_links;
CREATE TRIGGER trg_validate_advancement_link_context
BEFORE INSERT OR UPDATE ON advancement_links
FOR EACH ROW EXECUTE FUNCTION validate_advancement_link_context();

CREATE OR REPLACE FUNCTION validate_published_version_reference()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    version_tournament_id UUID;
    version_status VARCHAR(20);
BEGIN
    IF NEW.published_version_id IS NOT NULL THEN
        SELECT tournament_id, status
        INTO version_tournament_id, version_status
        FROM tournament_versions
        WHERE id = NEW.published_version_id
          AND organization_id = NEW.organization_id;

        IF NOT FOUND
           OR version_tournament_id IS DISTINCT FROM NEW.id
           OR version_status <> 'published'
        THEN
            RAISE EXCEPTION 'La versión publicada no pertenece al torneo o no está publicada';
        END IF;
    END IF;

    IF NEW.status IN ('published', 'live', 'finished')
       AND NEW.published_version_id IS NULL
    THEN
        RAISE EXCEPTION 'Un torneo público debe tener una versión publicada';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_published_version_reference ON tournaments;
CREATE TRIGGER trg_validate_published_version_reference
BEFORE INSERT OR UPDATE ON tournaments
FOR EACH ROW EXECUTE FUNCTION validate_published_version_reference();

CREATE OR REPLACE FUNCTION validate_match_stage_teams()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    version_status VARCHAR(20);
BEGIN
    SELECT tv.status
    INTO version_status
    FROM tournament_versions tv
    WHERE tv.id = NEW.tournament_version_id
      AND tv.organization_id = NEW.organization_id;

    IF version_status = 'draft' THEN
        IF NEW.home_team_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM stage_teams st
            WHERE st.organization_id = NEW.organization_id
              AND st.tournament_id = NEW.tournament_id
              AND st.tournament_version_id = NEW.tournament_version_id
              AND st.stage_id = NEW.stage_id
              AND st.team_id = NEW.home_team_id
              AND st.group_id IS NOT DISTINCT FROM NEW.group_id
        ) THEN
            RAISE EXCEPTION 'El equipo local no está asignado a la fase y grupo del partido';
        END IF;
        IF NEW.away_team_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM stage_teams st
            WHERE st.organization_id = NEW.organization_id
              AND st.tournament_id = NEW.tournament_id
              AND st.tournament_version_id = NEW.tournament_version_id
              AND st.stage_id = NEW.stage_id
              AND st.team_id = NEW.away_team_id
              AND st.group_id IS NOT DISTINCT FROM NEW.group_id
        ) THEN
            RAISE EXCEPTION 'El equipo visitante no está asignado a la fase y grupo del partido';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_match_stage_teams ON matches;
CREATE TRIGGER trg_validate_match_stage_teams
BEFORE INSERT OR UPDATE ON matches
FOR EACH ROW EXECUTE FUNCTION validate_match_stage_teams();

CREATE OR REPLACE FUNCTION prevent_published_match_structure_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    old_version_status VARCHAR(20);
    new_version_status VARCHAR(20);
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT status INTO new_version_status
        FROM tournament_versions
        WHERE id = NEW.tournament_version_id
          AND organization_id = NEW.organization_id;
        IF new_version_status IN ('published', 'archived') THEN
            RAISE EXCEPTION 'La estructura de partidos de una versión publicada o archivada es inmutable';
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        SELECT status INTO old_version_status
        FROM tournament_versions
        WHERE id = OLD.tournament_version_id
          AND organization_id = OLD.organization_id;
        IF old_version_status IN ('published', 'archived') THEN
            RAISE EXCEPTION 'La estructura de partidos de una versión publicada o archivada es inmutable';
        END IF;
    ELSE
        SELECT status INTO old_version_status
        FROM tournament_versions
        WHERE id = OLD.tournament_version_id
          AND organization_id = OLD.organization_id;
        SELECT status INTO new_version_status
        FROM tournament_versions
        WHERE id = NEW.tournament_version_id
          AND organization_id = NEW.organization_id;
        IF OLD.tournament_version_id IS DISTINCT FROM NEW.tournament_version_id THEN
            RAISE EXCEPTION 'Un partido no puede cambiar de versión';
        END IF;
        IF old_version_status IN ('published', 'archived')
           OR new_version_status IN ('published', 'archived')
        THEN
            IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.tournament_id IS DISTINCT FROM OLD.tournament_id
               OR NEW.tournament_version_id IS DISTINCT FROM OLD.tournament_version_id
               OR NEW.stage_id IS DISTINCT FROM OLD.stage_id
               OR NEW.group_id IS DISTINCT FROM OLD.group_id
               OR (
                     NEW.home_team_id IS DISTINCT FROM OLD.home_team_id
                     AND NOT (OLD.home_team_id IS NULL AND NEW.home_team_id IS NOT NULL)
                   )
               OR (
                     NEW.away_team_id IS DISTINCT FROM OLD.away_team_id
                     AND NOT (OLD.away_team_id IS NULL AND NEW.away_team_id IS NOT NULL)
                   )
               OR NEW.home_slot_id IS DISTINCT FROM OLD.home_slot_id
               OR NEW.away_slot_id IS DISTINCT FROM OLD.away_slot_id
               OR NEW.replacement_match_id IS DISTINCT FROM OLD.replacement_match_id
               OR NEW.matchday IS DISTINCT FROM OLD.matchday
               OR NEW.bracket_code IS DISTINCT FROM OLD.bracket_code
            THEN
                RAISE EXCEPTION 'La estructura de un partido publicado o archivado es inmutable';
            END IF;
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_published_match_structure ON matches;
CREATE TRIGGER trg_protect_published_match_structure
BEFORE INSERT OR UPDATE OR DELETE ON matches
FOR EACH ROW EXECUTE FUNCTION prevent_published_match_structure_mutation();

CREATE OR REPLACE VIEW v_public_tournaments
WITH (security_barrier = true) AS
SELECT tr.id, tr.name, tr.season, tr.start_date, tr.status
FROM tournaments tr
JOIN tournament_versions tv
  ON tv.id = tr.published_version_id
 AND tv.organization_id = tr.organization_id
 AND tv.tournament_id = tr.id
 AND tv.status = 'published'
WHERE tr.status IN ('published', 'live', 'finished');

CREATE OR REPLACE FUNCTION claim_outbox_events(p_limit INT DEFAULT 20)
RETURNS TABLE (
    id UUID,
    organization_id UUID,
    event_type VARCHAR,
    payload JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    RETURN QUERY
    WITH candidates AS (
        SELECT oe.id
        FROM public.outbox_events oe
        WHERE (
                oe.status = 'pending'
                AND oe.available_at <= CURRENT_TIMESTAMP
              )
           OR (
                oe.status = 'processing'
                AND oe.locked_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
              )
        ORDER BY oe.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 100))
    )
    UPDATE public.outbox_events oe
    SET status = 'processing',
        locked_at = CURRENT_TIMESTAMP,
        attempts = oe.attempts + 1
    FROM candidates
    WHERE oe.id = candidates.id
    RETURNING oe.id, oe.organization_id, oe.event_type, oe.payload;
END;
$$;

CREATE OR REPLACE FUNCTION fail_outbox_event(p_event_id UUID, p_error TEXT)
RETURNS BOOLEAN
LANGUAGE SQL
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    UPDATE public.outbox_events
    SET status = CASE WHEN attempts >= 5 THEN 'failed' ELSE 'pending' END,
        available_at = CASE
            WHEN attempts >= 5 THEN available_at
            ELSE CURRENT_TIMESTAMP + INTERVAL '5 seconds'
        END,
        last_error = LEFT(COALESCE(p_error, 'Error de procesamiento'), 2000),
        locked_at = NULL
    WHERE id = p_event_id AND status = 'processing'
    RETURNING TRUE;
$$;

DROP FUNCTION IF EXISTS list_user_organizations(UUID);
CREATE OR REPLACE FUNCTION list_user_organizations()
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
    WHERE ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
      AND ou.is_active = TRUE
    ORDER BY o.name;
$$;

CREATE OR REPLACE FUNCTION get_current_organization()
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
    WHERE o.id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
      AND EXISTS (
          SELECT 1
          FROM public.organization_users ou
          WHERE ou.organization_id = o.id
            AND ou.user_id = NULLIF(current_setting('app.current_user_id', true), '')::UUID
            AND ou.is_active = TRUE
      );
$$;

REVOKE ALL ON FUNCTION claim_outbox_events(INT) FROM PUBLIC;
REVOKE ALL ON FUNCTION fail_outbox_event(UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION list_user_organizations() FROM PUBLIC;
REVOKE ALL ON FUNCTION get_current_organization() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_outbox_events(INT) TO bracket_app;
GRANT EXECUTE ON FUNCTION fail_outbox_event(UUID, TEXT) TO bracket_app;
GRANT EXECUTE ON FUNCTION list_user_organizations() TO bracket_app;
GRANT EXECUTE ON FUNCTION get_current_organization() TO bracket_app;
REVOKE ALL ON organizations FROM bracket_app;
GRANT SELECT ON role_definitions TO bracket_app;
GRANT SELECT (id, email, password_hash, full_name) ON users TO bracket_app;

COMMIT;
