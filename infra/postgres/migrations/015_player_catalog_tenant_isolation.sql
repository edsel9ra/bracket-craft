BEGIN;

-- ============================================================================
-- 015 — Tenant-owned player catalog
--
-- Turns `players` into a tenant-owned table, splits rows that were shared by
-- several organizations, repoints every historical reference and recreates the
-- two public views that join `players`. The whole migration is atomic: any
-- failure leaves the database in its previous state.
-- ============================================================================

ALTER TABLE public.players
    ADD COLUMN IF NOT EXISTS organization_id UUID;

-- The global document uniqueness must disappear before the split creates one
-- copy per organization.
ALTER TABLE public.players
    DROP CONSTRAINT IF EXISTS uq_player_document;

-- ----------------------------------------------------------------------------
-- 1. Remove the foreign keys that would be violated while references move.
--    They are recreated with composite tenant keys at the end of the migration.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    constraint_row RECORD;
BEGIN
    FOR constraint_row IN
        SELECT conrelid, conname
        FROM pg_constraint
        WHERE contype = 'f'
          AND (
              (
                  conrelid IN (
                      'public.rosters'::regclass,
                      'public.match_lineup_snapshots'::regclass,
                      'public.match_events'::regclass,
                      'public.player_suspensions'::regclass
                  )
                  AND confrelid = 'public.players'::regclass
              )
              OR (
                  conrelid = 'public.match_rosters'::regclass
                  AND confrelid = 'public.rosters'::regclass
              )
              OR (
                  conrelid = 'public.player_suspensions'::regclass
                  AND confrelid = 'public.match_events'::regclass
              )
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE %s DROP CONSTRAINT %I',
            constraint_row.conrelid::regclass,
            constraint_row.conname
        );
    END LOOP;
END
$$;

-- ----------------------------------------------------------------------------
-- 2. Split or assign every existing player deterministically.
--
--    Only rows with organization_id IS NULL are processed, which makes the
--    data block idempotent. The organization with the oldest reference keeps
--    the original player id; ties are broken by organization UUID. Copies are
--    created with a new UUID and preserve every personal field.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS player_split_map;

CREATE TEMP TABLE player_split_map (
    old_player_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    new_player_id UUID NOT NULL,
    PRIMARY KEY (old_player_id, organization_id)
) ON COMMIT DROP;

WITH player_references AS (
    SELECT r.player_id, r.organization_id, r.registered_at AS reference_at
    FROM public.rosters r
    UNION ALL
    SELECT mr.player_id, mr.organization_id,
           COALESCE(m.match_date, m.created_at)
    FROM public.match_rosters mr
    JOIN public.matches m
      ON m.id = mr.match_id
     AND m.organization_id = mr.organization_id
    UNION ALL
    SELECT ls.player_id, ls.organization_id, m.created_at
    FROM public.match_lineup_snapshots ls
    JOIN public.matches m
      ON m.id = ls.match_id
     AND m.organization_id = ls.organization_id
    UNION ALL
    SELECT me.player_id, me.organization_id, me.created_at
    FROM public.match_events me
    UNION ALL
    SELECT ps.player_id, ps.organization_id, ps.created_at
    FROM public.player_suspensions ps
),
aggregated_references AS (
    SELECT
        r.player_id,
        r.organization_id,
        MIN(r.reference_at) AS first_reference_at
    FROM player_references r
    GROUP BY r.player_id, r.organization_id
),
ranked_references AS (
    SELECT
        a.player_id,
        a.organization_id,
        ROW_NUMBER() OVER (
            PARTITION BY a.player_id
            ORDER BY a.first_reference_at, a.organization_id
        ) AS organization_rank
    FROM aggregated_references a
    JOIN public.players p
      ON p.id = a.player_id
     AND p.organization_id IS NULL
)
INSERT INTO player_split_map (old_player_id, organization_id, new_player_id)
SELECT
    r.player_id,
    r.organization_id,
    CASE WHEN r.organization_rank = 1 THEN r.player_id ELSE gen_random_uuid() END
FROM ranked_references r;

-- Players without any reference are residuals: the application always creates
-- the roster in the same transaction as the player.
DELETE FROM public.players p
WHERE p.organization_id IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM player_split_map m
      WHERE m.old_player_id = p.id
  );

-- The organization with the oldest reference keeps the original identifier.
UPDATE public.players p
SET organization_id = m.organization_id
FROM player_split_map m
WHERE p.id = m.old_player_id
  AND m.new_player_id = p.id
  AND p.organization_id IS NULL;

-- Independent copies for every other organization.
INSERT INTO public.players (
    id,
    organization_id,
    first_name,
    last_name,
    document_type,
    national_id_encrypted,
    national_id_hmac,
    issuing_country,
    birth_date,
    photo_url,
    created_at
)
SELECT
    m.new_player_id,
    m.organization_id,
    p.first_name,
    p.last_name,
    p.document_type,
    p.national_id_encrypted,
    p.national_id_hmac,
    p.issuing_country,
    p.birth_date,
    p.photo_url,
    p.created_at
FROM player_split_map m
JOIN public.players p ON p.id = m.old_player_id
WHERE m.new_player_id <> m.old_player_id;

-- Repoint references by set. Rosters go first because match_rosters and the
-- match-event validation trigger depend on the roster's player.
UPDATE public.rosters r
SET player_id = m.new_player_id
FROM player_split_map m
WHERE r.player_id = m.old_player_id
  AND r.organization_id = m.organization_id
  AND r.player_id IS DISTINCT FROM m.new_player_id;

UPDATE public.match_rosters mr
SET player_id = m.new_player_id
FROM player_split_map m
WHERE mr.player_id = m.old_player_id
  AND mr.organization_id = m.organization_id
  AND mr.player_id IS DISTINCT FROM m.new_player_id;

UPDATE public.match_lineup_snapshots ls
SET player_id = m.new_player_id
FROM player_split_map m
WHERE ls.player_id = m.old_player_id
  AND ls.organization_id = m.organization_id
  AND ls.player_id IS DISTINCT FROM m.new_player_id;

UPDATE public.match_events me
SET player_id = m.new_player_id
FROM player_split_map m
WHERE me.player_id = m.old_player_id
  AND me.organization_id = m.organization_id
  AND me.player_id IS DISTINCT FROM m.new_player_id;

UPDATE public.player_suspensions ps
SET player_id = m.new_player_id
FROM player_split_map m
WHERE ps.player_id = m.old_player_id
  AND ps.organization_id = m.organization_id
  AND ps.player_id IS DISTINCT FROM m.new_player_id;

DROP TABLE IF EXISTS player_split_map;

-- ----------------------------------------------------------------------------
-- 3. Tenant schema: NOT NULL, uniqueness and keys.
-- ----------------------------------------------------------------------------
ALTER TABLE public.players
    ALTER COLUMN organization_id SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_player_organization_document
    ON public.players (
        organization_id,
        document_type,
        issuing_country,
        national_id_hmac
    );

CREATE UNIQUE INDEX IF NOT EXISTS uq_player_organization_context
    ON public.players (id, organization_id);

CREATE INDEX IF NOT EXISTS idx_players_organization_id
    ON public.players (organization_id);

ALTER TABLE public.players
    DROP CONSTRAINT IF EXISTS fk_players_organization;

ALTER TABLE public.players
    ADD CONSTRAINT fk_players_organization
    FOREIGN KEY (organization_id)
    REFERENCES public.organizations (id)
    ON DELETE RESTRICT;

-- ----------------------------------------------------------------------------
-- 4. Row level security, using the same tenant policy as the rest of the schema.
-- ----------------------------------------------------------------------------
ALTER TABLE public.players ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.players FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_policy ON public.players;

CREATE POLICY tenant_isolation_policy ON public.players
    FOR ALL
    USING (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND public.fn_verify_user_org_membership(organization_id)
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND public.fn_verify_user_org_membership(organization_id)
    );

-- ----------------------------------------------------------------------------
-- 5. Composite foreign keys: an application role cannot cross organizations.
-- ----------------------------------------------------------------------------
ALTER TABLE public.rosters
    DROP CONSTRAINT IF EXISTS fk_rosters_player_organization;
ALTER TABLE public.rosters
    ADD CONSTRAINT fk_rosters_player_organization
    FOREIGN KEY (player_id, organization_id)
    REFERENCES public.players (id, organization_id)
    ON DELETE RESTRICT;

ALTER TABLE public.match_lineup_snapshots
    DROP CONSTRAINT IF EXISTS fk_match_lineup_snapshots_player_organization;
ALTER TABLE public.match_lineup_snapshots
    ADD CONSTRAINT fk_match_lineup_snapshots_player_organization
    FOREIGN KEY (player_id, organization_id)
    REFERENCES public.players (id, organization_id)
    ON DELETE RESTRICT;

ALTER TABLE public.match_events
    DROP CONSTRAINT IF EXISTS fk_match_events_player_organization;
ALTER TABLE public.match_events
    ADD CONSTRAINT fk_match_events_player_organization
    FOREIGN KEY (player_id, organization_id)
    REFERENCES public.players (id, organization_id)
    ON DELETE RESTRICT;

ALTER TABLE public.player_suspensions
    DROP CONSTRAINT IF EXISTS fk_player_suspensions_player_organization;
ALTER TABLE public.player_suspensions
    ADD CONSTRAINT fk_player_suspensions_player_organization
    FOREIGN KEY (player_id, organization_id)
    REFERENCES public.players (id, organization_id)
    ON DELETE RESTRICT;

ALTER TABLE public.match_rosters
    DROP CONSTRAINT IF EXISTS fk_match_rosters_roster_player;
ALTER TABLE public.match_rosters
    ADD CONSTRAINT fk_match_rosters_roster_player
    FOREIGN KEY (roster_id, player_id, team_id, tournament_id, organization_id)
    REFERENCES public.rosters (
        id,
        player_id,
        team_id,
        tournament_id,
        organization_id
    )
    ON DELETE RESTRICT;

ALTER TABLE public.player_suspensions
    DROP CONSTRAINT IF EXISTS fk_player_suspensions_source_event;
ALTER TABLE public.player_suspensions
    ADD CONSTRAINT fk_player_suspensions_source_event
    FOREIGN KEY (source_event_id, origin_match_id, player_id, organization_id)
    REFERENCES public.match_events (id, match_id, player_id, organization_id)
    ON DELETE RESTRICT;

-- ----------------------------------------------------------------------------
-- 6. Grants: organization_id is readable/writable; the encrypted document stays
--    private and the application never receives UPDATE or DELETE on players.
-- ----------------------------------------------------------------------------
REVOKE ALL ON public.players FROM PUBLIC;
REVOKE ALL ON public.players FROM bracket_app;

GRANT SELECT (
    id,
    organization_id,
    first_name,
    last_name,
    document_type,
    national_id_hmac,
    issuing_country,
    birth_date,
    created_at
) ON public.players TO bracket_app;

GRANT INSERT (
    organization_id,
    first_name,
    last_name,
    document_type,
    national_id_encrypted,
    national_id_hmac,
    issuing_country,
    birth_date
) ON public.players TO bracket_app;

-- ----------------------------------------------------------------------------
-- 7. Public projections: same columns, player joined by (id, organization_id).
--    The owner remains the role that applies migrations (exempt from RLS) and
--    security_invoker is deliberately not enabled, so anonymous requests still
--    receive published rows.
-- ----------------------------------------------------------------------------
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
JOIN public.players p
  ON p.id = r.player_id
 AND p.organization_id = r.organization_id
JOIN public.tournaments t
  ON t.id = r.tournament_id
 AND t.organization_id = r.organization_id
JOIN public.organizations org
  ON org.id = t.organization_id
 AND org.is_active = TRUE
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
    ORDER BY tl.match_id, tl.team_id, tl.published_at DESC, ms.segment_number DESC, tl.id DESC
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
    JOIN public.players p
      ON p.id = ls.player_id
     AND p.organization_id = ls.organization_id
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
    JOIN public.players p
      ON p.id = mr.player_id
     AND p.organization_id = mr.organization_id
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

REVOKE ALL ON public.v_public_tournament_players FROM PUBLIC;
REVOKE ALL ON public.v_public_match_lineups_unpublished FROM PUBLIC;
REVOKE ALL ON public.v_public_match_lineups_unpublished FROM bracket_app;
GRANT SELECT ON public.v_public_tournament_players TO bracket_app;
GRANT SELECT ON public.v_public_match_lineups TO bracket_app;

COMMIT;
