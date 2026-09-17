BEGIN;

CREATE OR REPLACE VIEW v_public_stages
WITH (security_barrier = true) AS
SELECT
    st.id,
    st.tournament_id,
    st.name,
    st.stage_type,
    st.stage_order
FROM stages st
JOIN tournaments tr
  ON tr.id = st.tournament_id
 AND tr.organization_id = st.organization_id
WHERE tr.status IN ('published', 'live', 'finished')
  AND st.tournament_version_id = tr.published_version_id;

CREATE OR REPLACE VIEW v_public_standings
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
FROM standings s
JOIN tournaments tr
  ON tr.id = s.tournament_id
 AND tr.organization_id = s.organization_id
JOIN stages st
  ON st.id = s.stage_id
 AND st.tournament_id = s.tournament_id
 AND st.organization_id = s.organization_id
 AND st.tournament_version_id = tr.published_version_id
LEFT JOIN groups g
  ON g.id = s.group_id
 AND g.stage_id = s.stage_id
 AND g.organization_id = s.organization_id
JOIN teams t
  ON t.id = s.team_id
 AND t.organization_id = s.organization_id
WHERE tr.status IN ('published', 'live', 'finished');

CREATE OR REPLACE VIEW v_public_matches
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
    m.resolution_type,
    m.bracket_code
FROM matches m
JOIN tournaments tr
  ON tr.id = m.tournament_id
 AND tr.organization_id = m.organization_id
JOIN stages st
  ON st.id = m.stage_id
 AND st.tournament_id = m.tournament_id
 AND st.organization_id = m.organization_id
 AND st.tournament_version_id = tr.published_version_id
LEFT JOIN groups g
  ON g.id = m.group_id
 AND g.stage_id = m.stage_id
 AND g.organization_id = m.organization_id
LEFT JOIN teams home_team
  ON home_team.id = m.home_team_id
 AND home_team.organization_id = m.organization_id
LEFT JOIN teams away_team
  ON away_team.id = m.away_team_id
 AND away_team.organization_id = m.organization_id
WHERE tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

REVOKE ALL ON v_public_stages, v_public_standings, v_public_matches FROM PUBLIC;
GRANT SELECT ON v_public_stages, v_public_standings, v_public_matches TO bracket_app;

COMMIT;
