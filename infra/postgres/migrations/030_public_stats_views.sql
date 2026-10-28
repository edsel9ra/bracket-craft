BEGIN;

-- ============================================================================
-- 030 — public views for match events, segments and rosters (spec 022)
--
-- Aditiva: expone como vistas security_barrier las tablas tenant que el
-- endpoint publico de estadisticas necesita leer (eventos del acta, segmentos
-- y plantillas), filtradas por torneo publico. Se ejecutan como propietario y
-- respetan el aislamiento por organizacion a traves de los JOINs.
-- ============================================================================

CREATE OR REPLACE VIEW public.v_public_match_events
WITH (security_barrier = true) AS
SELECT
    me.id,
    me.match_id,
    m.tournament_id,
    me.team_id,
    me.player_id,
    me.event_type,
    me.minute,
    me.added_minute,
    me.player_out_id,
    me.player_in_id,
    me.beneficiary_team_id,
    me.metadata,
    me.is_voided
FROM public.match_events me
JOIN public.matches m
  ON m.id = me.match_id
 AND m.organization_id = me.organization_id
JOIN public.tournaments tr
  ON tr.id = m.tournament_id
 AND tr.organization_id = m.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
WHERE tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

CREATE OR REPLACE VIEW public.v_public_match_segments
WITH (security_barrier = true) AS
SELECT
    ms.id,
    ms.match_id,
    m.tournament_id,
    ms.segment_number,
    ms.minute_start,
    ms.minute_end,
    ms.status
FROM public.match_segments ms
JOIN public.matches m
  ON m.id = ms.match_id
 AND m.organization_id = ms.organization_id
JOIN public.tournaments tr
  ON tr.id = m.tournament_id
 AND tr.organization_id = m.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
WHERE tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

CREATE OR REPLACE VIEW public.v_public_tournament_rosters
WITH (security_barrier = true) AS
SELECT
    r.tournament_id,
    r.team_id,
    r.player_id,
    p.first_name,
    p.last_name,
    r.dorsal_number,
    r.is_active,
    r.photo_consent,
    CASE WHEN r.photo_consent THEN r.photo_object_key ELSE NULL END AS photo_url,
    t.name AS team_name
FROM public.rosters r
JOIN public.players p
  ON p.id = r.player_id
 AND p.organization_id = r.organization_id
JOIN public.teams t
  ON t.id = r.team_id
 AND t.organization_id = r.organization_id
JOIN public.tournaments tr
  ON tr.id = r.tournament_id
 AND tr.organization_id = r.organization_id
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
WHERE tr.status IN ('published', 'live', 'finished');

REVOKE ALL ON public.v_public_match_events FROM PUBLIC;
GRANT SELECT ON public.v_public_match_events TO bracket_app;

REVOKE ALL ON public.v_public_match_segments FROM PUBLIC;
GRANT SELECT ON public.v_public_match_segments TO bracket_app;

REVOKE ALL ON public.v_public_tournament_rosters FROM PUBLIC;
GRANT SELECT ON public.v_public_tournament_rosters TO bracket_app;

COMMIT;
