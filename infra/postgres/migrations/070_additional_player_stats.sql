BEGIN;

-- ============================================================================
-- Spec 052 (F17, T1): estadísticas adicionales.
--
-- Aditiva e idempotente:
-- 1. Amplía el catálogo de hechos con `penalty_saved` (penal atajado, DA-4)
--    en el acta, las versiones rectificadas y el borrador en vivo. Los CHECK
--    vigentes del catálogo se descubren por definición (contienen 'foul'),
--    porque su nombre generado no se garantiza, y se sustituyen por uno con
--    nombre estable.
-- 2. Añade `player_in_position` (posición de entrada, DA-3), opcional y solo
--    en sustituciones. El catálogo por modalidad se valida en la API.
-- 3. Repite `v_public_match_events` (060) y añade `player_in_position` al
--    final. La cronología pública no la lee ni muestra `penalty_saved`.
-- Hechos existentes intactos: ninguna fila cambia y la columna nueva es NULL.
-- ============================================================================

DO $$
DECLARE
    v_table TEXT;
    v_constraint TEXT;
BEGIN
    FOREACH v_table IN ARRAY ARRAY['match_events', 'match_report_version_events', 'match_live_events'] LOOP
        FOR v_constraint IN
            SELECT con.conname
            FROM pg_constraint con
            WHERE con.conrelid = format('public.%I', v_table)::regclass
              AND con.contype = 'c'
              AND pg_get_constraintdef(con.oid) ~ '\mevent_type\M'
              AND pg_get_constraintdef(con.oid) ~ '''foul'''
        LOOP
            EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I', v_table, v_constraint);
        END LOOP;

        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (event_type IN '
            '(''goal'', ''own_goal'', ''penalty_goal'', ''yellow_card'', ''red_card'', '
            '''substitution'', ''foul'', ''penalty_saved''))',
            v_table, 'chk_' || v_table || '_event_type'
        );

        EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS player_in_position VARCHAR(20)', v_table);
        EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I', v_table, 'chk_' || v_table || '_player_in_position');
        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (player_in_position IS NULL OR '
            '(event_type = ''substitution'' AND player_in_position ~ ''^[A-Z0-9_]{1,20}$''))',
            v_table, 'chk_' || v_table || '_player_in_position'
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE VIEW public.v_public_match_events
WITH (security_barrier = true) AS
WITH current_events AS (
SELECT me.organization_id, me.id, me.match_id, me.team_id, me.player_id, me.event_type,
    me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, me.is_voided, me.segment_id, me.player_in_position
FROM public.match_events me
WHERE NOT EXISTS (
        SELECT 1 FROM public.match_report_versions v
        WHERE v.match_id = me.match_id AND v.organization_id = me.organization_id
    )
UNION ALL
SELECT me.organization_id, me.id, me.match_id, me.team_id, me.player_id, me.event_type,
    me.minute, me.added_minute, me.player_out_id, me.player_in_id,
    me.beneficiary_team_id, me.metadata, FALSE AS is_voided, me.segment_id, me.player_in_position
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
    me.beneficiary_team_id, me.metadata, me.is_voided, me.segment_id, me.player_in_position
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
