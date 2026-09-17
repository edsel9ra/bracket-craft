BEGIN;

DROP VIEW IF EXISTS public.v_public_stages;
CREATE VIEW public.v_public_stages
WITH (security_barrier = true) AS
SELECT
    st.id,
    st.tournament_id,
    st.name,
    st.stage_type,
    st.stage_order
FROM public.stages st
JOIN public.tournaments tr
  ON tr.id = st.tournament_id
 AND tr.organization_id = st.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
WHERE tr.status IN ('published', 'live', 'finished')
  AND st.tournament_version_id = tr.published_version_id;

CREATE OR REPLACE VIEW public.v_public_matches
WITH (security_barrier = true) AS
SELECT
    m.id, m.tournament_id, m.stage_id, st.name AS stage_name, st.stage_order,
    m.group_id, g.name AS group_name, m.matchday, m.match_date,
    m.home_team_id, home_team.name AS home_team_name, home_team.short_code AS home_team_short_code,
    m.away_team_id, away_team.name AS away_team_name, away_team.short_code AS away_team_short_code,
    m.home_score_regular, m.away_score_regular, m.home_score, m.away_score,
    m.home_penalties, m.away_penalties, m.winner_team_id, m.status, m.resolution_type,
    m.bracket_code
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

REVOKE ALL ON public.v_public_stages FROM PUBLIC;
GRANT SELECT ON public.v_public_stages TO bracket_app;

COMMIT;
