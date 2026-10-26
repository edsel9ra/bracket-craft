BEGIN;

-- ============================================================================
-- 027 — Walkover reason (constraint relaxation, no data change)
--
-- `chk_administrative_resolution_reason` (created by `init/01_schema.sql` and
-- by 009) only admitted a reason for `administrative` and forced it to be NULL
-- for every other resolution. The closed walkover code of RF-007 could
-- therefore not be stored: the close would fail with an integrity error and
-- the API would answer a misleading 409. This migration **relaxes** that one
-- constraint and nothing else (RF-007, RNF-004, D-5).
--
--   * Only a relaxation: `resolution_reason` is admitted on `walkover` and
--     keeps being forbidden on `regular`, `extra_time` and `penalties`;
--     `administrative` keeps requiring it with the very same BTRIM window of
--     1..1000 characters.
--   * The obligation and the catalogue are **API authority**: the database
--     never requires a reason on `walkover`, so a historic row with NULL stays
--     valid and a deployment where this migration lands before the code keeps
--     working. Only the four catalogue codes (`no_show`, `withdrawal`,
--     `insufficient_players`, `sanction`) or NULL are accepted; the catalogue
--     membership also rejects the empty, blank and over-long values, so the
--     1..1000 window does not need to be repeated here.
--   * Additive in the sense that matters for data: no column, index, policy,
--     grant, function or row is added, removed or rewritten. The constraint is
--     dropped and recreated **validated** (not NOT VALID), because every stored
--     walkover already has a NULL reason and no row can violate the new
--     predicate. PostgreSQL takes a short lock while it verifies the table once;
--     run it in a low-activity window.
--   * The constraint keeps its name on purpose: it is still the reason fence of
--     the resolution, and the presence check of 009 and the catalogs that look
--     it up by name stay coherent.
--   * `init/01` is **not** touched. On a clean volume `init/01` creates the old
--     predicate and this migration replaces it exactly as on a migrated volume,
--     so both chains end with the same definition.
--   * RLS of `matches` (`tenant_isolation_policy`, `FORCE ROW LEVEL SECURITY`)
--     and the table GRANT for `bracket_app` are untouched: a CHECK is not a
--     privilege.
--   * Deployment order: 027 runs **before** the code that writes a non-null
--     walkover reason. The previous image keeps writing NULL and is unaffected
--     by the relaxation. There is no rollback: any defect is fixed by a new
--     migration (forward-fix). The clean volume (init/00-03 -> 001-027) ends
--     with the same schema as a migrated database.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Informative pre-checks. They only raise NOTICE with counts and must not
--    abort: the migration is a relaxation and there is no legacy row to fix.
--    They run before the ALTER, so they also report whether the constraint
--    already admits walkover (re-run of a manual apply).
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_walkover BIGINT;
    v_walkover_with_reason BIGINT;
    v_administrative_with_reason BIGINT;
    v_admits_walkover BOOLEAN;
BEGIN
    SELECT count(*)
    INTO v_walkover
    FROM public.matches
    WHERE resolution_type = 'walkover';

    SELECT count(*)
    INTO v_walkover_with_reason
    FROM public.matches
    WHERE resolution_type = 'walkover'
      AND resolution_reason IS NOT NULL;

    SELECT count(*)
    INTO v_administrative_with_reason
    FROM public.matches
    WHERE resolution_type = 'administrative'
      AND resolution_reason IS NOT NULL;

    SELECT EXISTS (
        SELECT 1
        FROM pg_constraint con
        WHERE con.conrelid = 'public.matches'::regclass
          AND con.conname = 'chk_administrative_resolution_reason'
          AND pg_get_constraintdef(con.oid) LIKE '%walkover%'
    )
    INTO v_admits_walkover;

    RAISE NOTICE
        'MIGRACION 027: walkover=% (con motivo=%); administrative con motivo=%. No se reescribe ninguna fila.',
        v_walkover, v_walkover_with_reason, v_administrative_with_reason;

    RAISE NOTICE
        'MIGRACION 027: la restricción del motivo ya admite walkover=%.',
        CASE WHEN v_admits_walkover THEN 'true' ELSE 'false' END;
END
$$;

-- ----------------------------------------------------------------------------
-- 2. Replace the reason fence with the relaxed predicate. Dropping first keeps
--    the operation idempotent and lets a re-run converge to the same state.
-- ----------------------------------------------------------------------------
ALTER TABLE public.matches
    DROP CONSTRAINT IF EXISTS chk_administrative_resolution_reason;

ALTER TABLE public.matches
    ADD CONSTRAINT chk_administrative_resolution_reason CHECK (
        (
            resolution_type = 'administrative'
            AND resolution_reason IS NOT NULL
            AND LENGTH(BTRIM(resolution_reason)) BETWEEN 1 AND 1000
        )
        OR (
            resolution_type = 'walkover'
            AND (
                resolution_reason IS NULL
                OR resolution_reason IN (
                    'no_show',
                    'withdrawal',
                    'insufficient_players',
                    'sanction'
                )
            )
        )
        OR (
            resolution_type IS DISTINCT FROM 'administrative'
            AND resolution_type IS DISTINCT FROM 'walkover'
            AND resolution_reason IS NULL
        )
    );

COMMIT;
