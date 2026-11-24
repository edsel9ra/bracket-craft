BEGIN;

-- ============================================================================
-- Spec 044 (F12, T1): catálogo cerrado de formaciones por modalidad.
--
-- Sustituye el CHECK anónimo de la 007 (solo las cuatro formaciones de 11v11)
-- por uno con nombre que acepta también las de 5v5, 7v7 y 9v9. Solo amplía
-- el catálogo: todas las filas existentes lo cumplen y no se reescribe nada.
-- Fuente única: backend/app/modules/rule_contract.py (FORMATION_SLOTS).
-- Idempotente: reaplicarla no cambia nada.
-- ============================================================================

ALTER TABLE public.match_team_lineups
    DROP CONSTRAINT IF EXISTS match_team_lineups_formation_code_check,
    DROP CONSTRAINT IF EXISTS chk_match_team_lineup_formation_code;

ALTER TABLE public.match_team_lineups
    ADD CONSTRAINT chk_match_team_lineup_formation_code CHECK (
        formation_code IN ('4-3-3', '4-4-2', '3-5-2', '4-2-3-1', '1-2-1', '2-1-1', '2-2', '2-3-1', '3-2-1', '3-1-2', '3-3-2', '3-4-1', '4-3-1')
    );

COMMIT;
