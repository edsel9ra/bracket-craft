BEGIN;

-- ============================================================================
-- 019 — Retire tournament-scoped roles and between-stage selectors
--
-- DESTRUCTIVE MIGRATION, NO DOWN/ROLLBACK. It runs once in a single
-- transaction (schema_migrations and the checksum prevent a second
-- application); `IF EXISTS` below is only a safety net, not a promise that the
-- file can be replayed. After it is applied the only path is forward-fix with a
-- new numbered migration.
--
-- It performs, in this order:
--
--   1. Three closed pre-checks, all before the first DDL statement:
--        * `tournament_user_roles` has no rows (nothing ever created them);
--        * `stage_edges` has no rows (only the old version clone wrote them);
--        * `phase_slots.source_type` has no value outside the two real
--          provenance values (`direct_team`, `match_result`).
--      They abort with the structure name, the per-value counts and no
--      identifiers or personal data. Nothing is deleted or rewritten.
--   2. Drops `stage_edges` and `tournament_user_roles` (policies, grants,
--      triggers and indexes go with the tables). No CASCADE: an incoming
--      dependency makes the migration fail and the runbook detects it first.
--   3. Discovers the CHECK constraint of `phase_slots.source_type` in
--      `pg_constraint`; aborts unless exactly one matches and then replaces it
--      with the narrowed `direct_team`/`match_result` version. `phase_slots`,
--      `source_reference` and `matches.home_slot_id`/`away_slot_id` remain as
--      stored provenance.
--   4. Recreates `prevent_published_structure_mutation()` with the same
--      messages and the stable, user-class SQLSTATE `ZZ409`, so the API can map
--      published-structure violations to 409 by code instead of by text.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Pre-checks. They must finish before any DROP or constraint replacement.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_rows BIGINT;
    v_matches INT;
    v_invalid TEXT;
BEGIN
    IF to_regclass('public.tournament_user_roles') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.tournament_user_roles'
        INTO v_rows;

        IF v_rows > 0 THEN
            RAISE EXCEPTION
                'MIGRACION 019: la tabla tournament_user_roles no está vacía (% fila(s)). Revise el runbook y resuelva las asignaciones antes de aplicar la migración; no se borran datos en silencio.',
                v_rows;
        END IF;
    END IF;

    IF to_regclass('public.stage_edges') IS NOT NULL THEN
        EXECUTE 'SELECT count(*) FROM public.stage_edges'
        INTO v_rows;

        IF v_rows > 0 THEN
            RAISE EXCEPTION
                'MIGRACION 019: la tabla stage_edges no está vacía (% fila(s)). Revise el runbook y resuelva las aristas antes de aplicar la migración; no se borran datos en silencio.',
                v_rows;
        END IF;
    END IF;

    -- Per-value report; the message carries only structure names and counts.
    SELECT string_agg(
               format('%s=%s', invalid.source_type, invalid.total),
               ', ' ORDER BY invalid.source_type
           )
    INTO v_invalid
    FROM (
        SELECT ps.source_type, count(*) AS total
        FROM public.phase_slots ps
        WHERE ps.source_type NOT IN ('direct_team', 'match_result')
        GROUP BY ps.source_type
    ) AS invalid;

    IF v_invalid IS NOT NULL THEN
        RAISE EXCEPTION
            'MIGRACION 019: phase_slots.source_type contiene valores retirados o desconocidos (%). No se reescriben filas: el operador debe decidir antes de aplicar la migración.',
            v_invalid;
    END IF;

    SELECT count(*)
    INTO v_matches
    FROM pg_constraint con
    WHERE con.conrelid = to_regclass('public.phase_slots')
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ~ '\msource_type\M';

    IF v_matches <> 1 THEN
        RAISE EXCEPTION
            'MIGRACION 019: se esperaba exactamente una constraint CHECK sobre phase_slots.source_type y se encontraron %. Corrija el esquema y reintente.',
            v_matches;
    END IF;
END
$$;

-- ----------------------------------------------------------------------------
-- 2. Drops. No CASCADE: a dependency must stop the migration.
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS public.stage_edges;
DROP TABLE IF EXISTS public.tournament_user_roles;

-- ----------------------------------------------------------------------------
-- 3. Narrow the CHECK using the name discovered in the catalog, then create
--    the constraint with a deterministic name.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_matches INT;
    v_constraint TEXT;
BEGIN
    SELECT count(*)
    INTO v_matches
    FROM pg_constraint con
    WHERE con.conrelid = 'public.phase_slots'::regclass
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ~ '\msource_type\M';

    IF v_matches <> 1 THEN
        RAISE EXCEPTION
            'MIGRACION 019: se esperaba exactamente una constraint CHECK sobre phase_slots.source_type y se encontraron %. Corrija el esquema y reintente.',
            v_matches;
    END IF;

    SELECT con.conname
    INTO v_constraint
    FROM pg_constraint con
    WHERE con.conrelid = 'public.phase_slots'::regclass
      AND con.contype = 'c'
      AND pg_get_constraintdef(con.oid) ~ '\msource_type\M';

    EXECUTE format(
        'ALTER TABLE public.phase_slots DROP CONSTRAINT IF EXISTS %I',
        v_constraint
    );

    EXECUTE 'ALTER TABLE public.phase_slots
             ADD CONSTRAINT phase_slots_source_type_check
             CHECK (source_type IN (''direct_team'', ''match_result''))';
END
$$;

-- ----------------------------------------------------------------------------
-- 4. Same function body and messages, stable SQLSTATE for the API mapping.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.prevent_published_structure_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_version_id UUID;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        v_version_id := OLD.tournament_version_id;
        IF EXISTS (
            SELECT 1
            FROM tournament_versions tv
            WHERE tv.id = v_version_id
              AND tv.status IN ('published', 'archived')
        ) THEN
            RAISE EXCEPTION 'La versión publicada o archivada no puede modificarse'
                USING ERRCODE = 'ZZ409';
        END IF;
    END IF;

    IF TG_OP <> 'DELETE' THEN
        v_version_id := NEW.tournament_version_id;
        IF EXISTS (
            SELECT 1
            FROM tournament_versions tv
            WHERE tv.id = v_version_id
              AND tv.status IN ('published', 'archived')
        ) THEN
            RAISE EXCEPTION 'No se pueden insertar estructuras en una versión publicada'
                USING ERRCODE = 'ZZ409';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

COMMIT;
