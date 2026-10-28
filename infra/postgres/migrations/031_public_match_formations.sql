BEGIN;

-- ============================================================================
-- 031 — internal projection with every published tactical formation (spec 022)
--
-- PROYECCIÓN INTERNA. No la consume ninguna ruta pública: alimenta solo el
-- cálculo de la portería imbatida (RF-015, RF-026, casos límite 14 y 16b).
-- Publica, por partido, segmento y equipo, TODAS las formaciones tácticas con
-- `is_public` verdadero —jugador, `position_slot`, titular y `segment_number`—
-- porque `public.v_public_match_lineups` devuelve solo la última formación
-- publicada por equipo (`DISTINCT ON (match_id, team_id)`) desde la 007/028 y
-- con ella la formación del primer segmento y la del portero entrante son
-- inalcanzables.
--
-- No cambia el contrato público de la spec 021: `v_public_match_lineups`, la
-- alineación publicada en `GET /tournaments/public/{id}/matches` y
-- `PublicTeamLineupResponse.segment_number` se quedan exactamente como están.
-- `engine_version` sigue en 2026.1.
--
-- Aditiva: no crea ni altera tablas, columnas, filas, políticas ni índices y no
-- reescribe datos. Sin *backfill*. La visibilidad repite la condición de las
-- vistas de la 028/030 y de `v_public_tournaments` (organización activa, torneo
-- en estado público, versión publicada) y el aislamiento por organización sale
-- de los JOINs.
-- ============================================================================

CREATE OR REPLACE VIEW public.v_public_match_formations
WITH (security_barrier = true) AS
SELECT
    tl.match_id,
    m.tournament_id,
    tl.segment_id,
    ms.segment_number,
    tl.team_id,
    ls.player_id,
    ls.position_slot,
    ls.is_starter,
    tl.is_public,
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
JOIN public.match_lineup_snapshots ls
  ON ls.match_id = tl.match_id
 AND ls.segment_id = tl.segment_id
 AND ls.team_id = tl.team_id
 AND ls.organization_id = tl.organization_id
WHERE tl.is_public = TRUE
  AND tl.published_at IS NOT NULL
  AND tr.status IN ('published', 'live', 'finished')
  AND m.tournament_version_id = tr.published_version_id
  AND m.status IN ('scheduled', 'live', 'finished', 'administrative_resolution');

REVOKE ALL ON public.v_public_match_formations FROM PUBLIC;
GRANT SELECT ON public.v_public_match_formations TO bracket_app;

COMMIT;
