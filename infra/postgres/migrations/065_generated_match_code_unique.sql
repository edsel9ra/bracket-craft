BEGIN;

-- ============================================================================
-- Spec 042 (F11, T1): un partido generado no repite código dentro de su fase y
-- versión, también si una ruta futura omitiera el bloqueo fase → versión.
--
-- 1. Bloquea las escrituras en `matches` mientras comprueba los datos.
-- 2. Si ya hay códigos repetidos, aborta sin cambiar nada e indica cuántas
--    fases están afectadas y cuáles, para regenerarlas antes de reintentar.
-- 3. Índice único parcial: los partidos manuales (sin código) quedan fuera;
--    otra fase u otra versión (clonada) pueden repetir código.
-- Idempotente: reaplicarla no cambia nada.
-- ============================================================================

LOCK TABLE public.matches IN SHARE ROW EXCLUSIVE MODE;

DO $$
DECLARE
    v_count INT;
    v_stages TEXT;
BEGIN
    SELECT count(*), string_agg(stage_id::text, ', ' ORDER BY stage_id::text)
    INTO v_count, v_stages
    FROM (
        SELECT DISTINCT stage_id
        FROM public.matches
        WHERE bracket_code IS NOT NULL
        GROUP BY organization_id, tournament_version_id, stage_id, bracket_code
        HAVING count(*) > 1
    ) duplicated;

    IF v_count > 0 THEN
        RAISE EXCEPTION
            'MIGRACION 065: % fase(s) con códigos de partido repetidos: %', v_count, v_stages
            USING HINT = 'Regenera el calendario de esas fases y vuelve a aplicar la migración.';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_matches_generated_code
    ON public.matches (organization_id, tournament_version_id, stage_id, bracket_code)
    WHERE bracket_code IS NOT NULL;

COMMIT;
