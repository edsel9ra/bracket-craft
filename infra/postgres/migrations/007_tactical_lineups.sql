BEGIN;

CREATE TABLE match_team_lineups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    match_id UUID NOT NULL,
    segment_id UUID NOT NULL,
    team_id UUID NOT NULL,
    formation_code VARCHAR(20) NOT NULL CHECK (
        formation_code IN ('4-3-3', '4-4-2', '3-5-2', '4-2-3-1')
    ),
    is_public BOOLEAN NOT NULL DEFAULT FALSE,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (match_id, organization_id)
        REFERENCES matches(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (segment_id, match_id, organization_id)
        REFERENCES match_segments(id, match_id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (team_id, organization_id)
        REFERENCES teams(id, organization_id) ON DELETE RESTRICT,
    CONSTRAINT uq_match_team_lineup_segment UNIQUE (segment_id, team_id),
    CONSTRAINT uq_match_team_lineup_context UNIQUE (id, organization_id),
    CONSTRAINT chk_match_team_lineup_publication CHECK (
        (is_public AND published_at IS NOT NULL)
        OR (NOT is_public AND published_at IS NULL)
    )
);

ALTER TABLE match_lineup_snapshots
    ADD COLUMN IF NOT EXISTS position_slot VARCHAR(20);

ALTER TABLE match_lineup_snapshots
    ADD CONSTRAINT chk_lineup_snapshot_position_slot
    CHECK (position_slot IS NULL OR position_slot ~ '^[A-Z0-9_]+$');

CREATE INDEX idx_match_team_lineups_match_segment
    ON match_team_lineups (organization_id, match_id, segment_id, team_id);

CREATE INDEX idx_match_team_lineups_public
    ON match_team_lineups (match_id, team_id, is_public, published_at)
    WHERE is_public = TRUE;

ALTER TABLE match_team_lineups ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_team_lineups FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_policy ON match_team_lineups
    FOR ALL
    USING (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND fn_verify_user_org_membership(organization_id)
    )
    WITH CHECK (
        organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::UUID
        AND fn_verify_user_org_membership(organization_id)
    );

GRANT SELECT, INSERT, UPDATE, DELETE ON match_team_lineups TO bracket_app;

CREATE VIEW public.v_public_match_lineups
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
        CASE WHEN roster.photo_consent THEN p.photo_url ELSE NULL END AS photo_url
    FROM public_team_lineups tl
    JOIN public.matches m
      ON m.id = tl.match_id
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
    LEFT JOIN LATERAL (
        SELECT r.dorsal_number, r.photo_consent
        FROM public.rosters r
        WHERE r.tournament_id = m.tournament_id
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
        CASE WHEN r.photo_consent THEN p.photo_url ELSE NULL END AS photo_url
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

REVOKE ALL ON public.v_public_match_lineups FROM PUBLIC;
GRANT SELECT ON public.v_public_match_lineups TO bracket_app;

COMMIT;
