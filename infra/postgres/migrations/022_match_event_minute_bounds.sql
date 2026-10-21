BEGIN;

-- ============================================================================
-- 022 — Structural minute bounds on match events (additive)
--
-- Adds the two structural CHECK constraints the API already enforces (minute
-- 0..180 and added_minute 0..30) so the database rejects impossible values no
-- matter which client writes them.
--
--   * Additive only: two CHECK constraints on `public.match_events`. No column,
--     table, row, policy, grant or index is added, removed or rewritten.
--   * No data rollback and no repair: the pre-check aborts the whole migration
--     when an out-of-range row exists, naming both counts. It never trims,
--     clamps or rewrites rows; the operator decides the forward-fix.
--   * Both constraints are added **validated** (not NOT VALID): the pre-check
--     in step 1 has already proven that no stored row violates the bounds, so a
--     full validation costs nothing extra and leaves the catalog in the state a
--     clean volume reaches. PostgreSQL takes a short ACCESS EXCLUSIVE lock while
--     it validates existing rows, so run the migration in a low-activity
--     window. The pre-check scans the same table, so a big table is the only
--     operational concern.
--   * These are structural limits, not the sport rule: the API keeps applying
--     the effective phase maximum (regular/extra time) and answers with its
--     current error. The database only rejects what no phase can allow.
--   * Deployment order: apply with `MIGRATION_TARGET=022`. It is compatible
--     with the current code, which already limits to 180/30, so it needs no
--     coordinated release. There is no rollback: any defect is fixed by a new
--     migration (forward-fix).
--   * No new tenant table: RLS and the existing policy on `match_events` keep
--     applying untouched.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Pre-check. It aborts the migration when a row is out of range and names
--    both counts. It runs before the first ALTER, so a failure leaves the table
--    exactly as it was, with no constraint partially added.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_bad_minute BIGINT;
    v_bad_added_minute BIGINT;
BEGIN
    SELECT count(*)
    INTO v_bad_minute
    FROM public.match_events
    WHERE minute < 0 OR minute > 180;

    SELECT count(*)
    INTO v_bad_added_minute
    FROM public.match_events
    WHERE added_minute < 0 OR added_minute > 30;

    IF v_bad_minute > 0 OR v_bad_added_minute > 0 THEN
        RAISE EXCEPTION
            'MIGRACION 022 abortada: match_events con minute fuera de 0..180=%; con added_minute fuera de 0..30=%. No se recorta ni se corrige ninguna fila: corrige los datos y aplica una migracion nueva.',
            v_bad_minute, v_bad_added_minute;
    END IF;

    RAISE NOTICE
        'MIGRACION 022: sin filas fuera de rango (minute 0..180 y added_minute 0..30); se anaden las restricciones validadas.';
END
$$;

-- ----------------------------------------------------------------------------
-- 2. Structural bounds. Validated on purpose: step 1 already proved the table
--    is clean, so the constraints are enforced and trusted from the moment they
--    exist. The pre-existing `minute >= 0` / `added_minute >= 0` inline checks
--    stay in place; these two tighten the upper bound.
-- ----------------------------------------------------------------------------
ALTER TABLE public.match_events
    ADD CONSTRAINT chk_match_event_minute_range CHECK (minute BETWEEN 0 AND 180),
    ADD CONSTRAINT chk_match_event_added_minute_range CHECK (added_minute BETWEEN 0 AND 30);

COMMIT;
