BEGIN;

-- ============================================================================
-- Spec 036 (PR B3, T49): the public matches route orders the union of the
-- classic projection and the live/suspended selection before paginating, by
-- `stage_order, stage_id, matchday, bracket_code, match_date, id` — the same
-- ordering the classic `v_public_matches` uses. The suspended branch therefore
-- needs `bracket_code` internally, so it does not change page or fall to the
-- end of its stage when a match moves to `suspended`.
--
-- Additive: `bracket_code` is appended at the end of the internal selection
-- view's output. `CREATE OR REPLACE VIEW` suffices because the column is
-- appended at the end and keeps the existing column names and types; grants,
-- ownership, RLS exemption and `security_barrier` are preserved by the
-- replacement. The public view `v_public_match_live` still selects the same 14
-- columns explicitly, so the anonymous payload is unchanged.
-- ============================================================================

CREATE OR REPLACE VIEW public.v_match_live_public_selection
WITH (security_barrier = true) AS
SELECT m.id, m.tournament_id, m.stage_id, m.group_id, m.matchday, m.match_date,
    m.home_team_id, ht.name AS home_team_name, m.away_team_id, at.name AS away_team_name,
    m.status, ls.home_score, ls.away_score, TRUE AS is_provisional,
    ms.segment_number AS clock_segment_number,
    CASE WHEN ls.clock_state = 'not_started' THEN NULL ELSE
        (ls.clock_elapsed_us + CASE WHEN ls.clock_state = 'running' THEN
            (GREATEST(0, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ls.clock_anchor_at))) * 1000000)::BIGINT ELSE 0 END) / 1000000 END AS clock_elapsed_seconds,
    ls.clock_state, CURRENT_TIMESTAMP AS clock_observed_at,
    m.bracket_code
FROM public.matches m
JOIN public.match_live_state ls ON ls.match_id = m.id AND ls.organization_id = m.organization_id
JOIN public.tournaments t ON t.id = m.tournament_id AND t.organization_id = m.organization_id
JOIN public.organizations o ON o.id = m.organization_id AND o.is_active
JOIN public.tournament_versions tv ON tv.id = m.tournament_version_id AND tv.organization_id = m.organization_id
    AND tv.tournament_id = t.id AND tv.status = 'published'
JOIN public.stages st ON st.id = m.stage_id AND st.organization_id = m.organization_id
    AND st.tournament_id = t.id AND st.tournament_version_id = tv.id
JOIN public.teams ht ON ht.id = m.home_team_id AND ht.organization_id = m.organization_id
JOIN public.teams at ON at.id = m.away_team_id AND at.organization_id = m.organization_id
LEFT JOIN public.match_segments ms ON ms.id = ls.segment_id AND ms.match_id = m.id AND ms.organization_id = m.organization_id
WHERE t.status IN ('published','live','finished') AND m.tournament_version_id = t.published_version_id
    AND m.status IN ('live','suspended') AND NOT m.result_confirmed AND ls.frozen_at IS NULL;

COMMIT;
