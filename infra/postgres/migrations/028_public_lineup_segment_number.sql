BEGIN;

-- ============================================================================
-- 028 — segment_number in the public lineup projection
--
-- Recreates `public.v_public_match_lineups_unpublished` adding `segment_number`
-- (integer, nullable) so the public lineup can be labelled with the segment it
-- belongs to (spec 021, RF-007/RF-013/RF-015). The value comes from
-- `match_segments` in the tactical (published formation) branch and is NULL in
-- the classic (planilla) branch, where there is no segment.
--
-- Additive: no table, column, row, policy, grant or index is added or removed.
-- The only change is a new nullable output column of a read-only projection.
-- `engine_version` stays 2026.1.
--
-- The view is dropped and recreated because PostgreSQL does not allow
-- `CREATE OR REPLACE VIEW` to change the number of output columns. Both views
-- (`v_public_match_lineups` wrapper and `..._unpublished` raw) are rebuilt in
-- the same transaction; the wrapper keeps `SELECT raw.*` so it inherits the
-- new column automatically. `security_barrier`, ownership, RLS exemption and
-- grants are restored exactly as before.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Drop the wrapper first (it depends on the raw view), then the raw view.
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS public.v_public_match_lineups;
DROP VIEW IF EXISTS public.v_public_match_lineups_unpublished;

-- ----------------------------------------------------------------------------
-- 2. Recreate the raw (unpublished) projection with segment_number.
-- ----------------------------------------------------------------------------
CREATE VIEW public.v_public_match_lineups_unpublished
WITH (security_barrier = true) AS
WITH public_team_lineups AS (
    SELECT DISTINCT ON (tl.match_id, tl.team_id)
           tl.match_id,
           tl.segment_id,
           ms.segment_number,
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
        tl.segment_number,
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
        NULL::INT AS segment_number,
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

-- ----------------------------------------------------------------------------
-- 3. Recreate the published wrapper (filters out unpublished formations).
-- ----------------------------------------------------------------------------
CREATE VIEW public.v_public_match_lineups
WITH (security_barrier = true) AS
SELECT raw.*
FROM public.v_public_match_lineups_unpublished raw
WHERE raw.formation_code IS NOT NULL
   OR (
       raw.formation_code IS NULL
       AND NOT EXISTS (
           SELECT 1
           FROM public.match_team_lineups tl
           WHERE tl.match_id = raw.match_id
             AND tl.team_id = raw.team_id
       )
   );

-- ----------------------------------------------------------------------------
-- 4. Restore grants exactly as before: raw view inaccessible to bracket_app,
--    published wrapper readable by bracket_app, neither accessible to PUBLIC.
-- ----------------------------------------------------------------------------
REVOKE ALL ON public.v_public_match_lineups_unpublished FROM PUBLIC;
REVOKE ALL ON public.v_public_match_lineups_unpublished FROM bracket_app;
REVOKE ALL ON public.v_public_match_lineups FROM PUBLIC;
GRANT SELECT ON public.v_public_match_lineups TO bracket_app;

COMMIT;
