BEGIN;

-- ============================================================================
-- Spec 037 (F13, T1): la cronología pública ordena y separa los hechos por
-- segmento (RF-009, DA-4), pero v_public_match_events no expone el segmento.
--
-- Aditiva: repite la definición vigente de la 035 (versión vigente del acta,
-- torneo visible, versión publicada, organización activa) y añade
-- `segment_id` al final de la salida. `CREATE OR REPLACE VIEW` conserva
-- nombres y tipos previos, privilegios y `security_barrier`. Sin cambio de
-- filas ni consumidores rotos: las rutas existentes seleccionan columnas
-- explícitas.
-- ============================================================================

CREATE OR REPLACE VIEW public.v_public_match_events
WITH (security_barrier = true) AS
WITH current_events AS (
SELECT me.organization_id, me.id, me.match_id, me.team_id, me.player_id, me.event_type,
    me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, me.is_voided, me.segment_id
FROM public.match_events me
WHERE NOT EXISTS (
        SELECT 1 FROM public.match_report_versions v
        WHERE v.match_id = me.match_id AND v.organization_id = me.organization_id
    )
UNION ALL
SELECT me.organization_id, me.id, me.match_id, me.team_id, me.player_id, me.event_type,
    me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, FALSE AS is_voided, me.segment_id
FROM public.match_report_version_events me
WHERE NOT me.is_voided AND EXISTS (
        SELECT 1 FROM public.match_report_versions v
        WHERE v.id = me.version_id
          AND v.organization_id = me.organization_id AND v.match_id = me.match_id
          AND NOT EXISTS (
              SELECT 1 FROM public.match_report_versions newer
              WHERE newer.match_id = v.match_id AND newer.organization_id = v.organization_id
                AND newer.version_number > v.version_number
          )
    )
)
SELECT
    me.id, me.match_id, m.tournament_id, me.team_id, me.player_id,
    me.event_type, me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, me.is_voided, me.segment_id
FROM current_events me
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

REVOKE ALL ON public.v_public_match_events FROM PUBLIC;
GRANT SELECT ON public.v_public_match_events TO bracket_app;

COMMIT;
