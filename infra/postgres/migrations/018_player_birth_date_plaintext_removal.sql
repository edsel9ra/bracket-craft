BEGIN;

-- ============================================================================
-- 018 — Player birth date: closed failure and plaintext removal
--
-- Closes the two-phase migration started by 017. This file:
--
--   * fails closed when any player still has a NULL `birth_date_encrypted`
--     (the administrative backfill has not finished), before touching anything;
--   * refuses to continue when a view, materialized view, index or SQL function
--     still depends on `players.birth_date`, with a clear report;
--   * makes the ciphertext mandatory (`NOT NULL`);
--   * drops the plaintext column;
--   * reasserts the final column grants for `bracket_app`.
--
-- Everything runs in a single transaction: any failure leaves the database in
-- the previous state. The pending check and the dependency check happen before
-- the first DDL statement. The file is idempotent on a direct re-run: when the
-- plaintext column no longer exists the closure block is a no-op and only the
-- (idempotent) grants are reasserted.
-- ============================================================================

DO $$
DECLARE
    v_has_plaintext BOOLEAN;
    v_has_ciphertext BOOLEAN;
    v_pending BIGINT;
    v_dependencies TEXT;
    v_birth_attnum INT;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'players'
          AND column_name = 'birth_date'
    ) INTO v_has_plaintext;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'players'
          AND column_name = 'birth_date_encrypted'
    ) INTO v_has_ciphertext;

    -- Guard: after a successful 018 (or any earlier run) there is nothing left
    -- to close. A direct re-run must not fail on existing objects.
    IF NOT v_has_plaintext THEN
        RAISE NOTICE
            'MIGRACION 018: la fecha de nacimiento en claro ya no existe; nada que hacer.';
        RETURN;
    END IF;

    IF NOT v_has_ciphertext THEN
        RAISE EXCEPTION
            'MIGRACION 018: falta la columna birth_date_encrypted. Aplique la migración 017 antes de la 018.';
    END IF;

    -- ------------------------------------------------------------------------
    -- 1. Closed failure: every player must be encrypted before the plaintext
    --    is removed. The report carries the count only, never a date or any
    --    personal value. This check runs before any ALTER or DROP.
    -- ------------------------------------------------------------------------
    SELECT count(*)
    INTO v_pending
    FROM public.players
    WHERE birth_date_encrypted IS NULL;

    IF v_pending > 0 THEN
        RAISE EXCEPTION
            'MIGRACION 018: % jugador(es) sin fecha de nacimiento cifrada. Ejecute python -m scripts.encrypt_birth_dates, verifique que no queden pendientes y reintente.',
            v_pending;
    END IF;

    -- ------------------------------------------------------------------------
    -- 2. Dependencies on the plaintext column. 017 already recreated
    --    `v_public_tournament_players` without it; any other view, index or
    --    function that still references `players.birth_date` blocks the drop
    --    with a clear report instead of an opaque DROP COLUMN error.
    -- ------------------------------------------------------------------------
    SELECT a.attnum
    INTO v_birth_attnum
    FROM pg_attribute a
    WHERE a.attrelid = 'public.players'::regclass
      AND a.attname = 'birth_date'
      AND NOT a.attisdropped;

    SELECT string_agg(DISTINCT dependent.name, ', ' ORDER BY dependent.name)
    INTO v_dependencies
    FROM (
        -- Views and materialized views (dependency tracked through the
        -- rewrite rule of the view).
        SELECT format('%I.%I (vista)', n.nspname, c.relname) AS name
        FROM pg_depend d
        JOIN pg_rewrite rw
          ON rw.oid = d.objid
        JOIN pg_class c
          ON c.oid = rw.ev_class
        JOIN pg_namespace n
          ON n.oid = c.relnamespace
        WHERE d.classid = 'pg_rewrite'::regclass
          AND d.refclassid = 'pg_class'::regclass
          AND d.refobjid = 'public.players'::regclass
          AND d.refobjsubid = v_birth_attnum
          AND c.oid <> 'public.players'::regclass
          AND c.relkind IN ('v', 'm')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')

        UNION ALL

        -- Indexes on the column.
        SELECT format('%I.%I (índice)', n.nspname, c.relname) AS name
        FROM pg_depend d
        JOIN pg_class c
          ON c.oid = d.objid
         AND c.relkind IN ('i', 'I')
        JOIN pg_namespace n
          ON n.oid = c.relnamespace
        WHERE d.classid = 'pg_class'::regclass
          AND d.refclassid = 'pg_class'::regclass
          AND d.refobjid = 'public.players'::regclass
          AND d.refobjsubid = v_birth_attnum
          AND d.deptype IN ('a', 'n')
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')

        UNION ALL

        -- Functions with SQL-standard bodies (parsed dependencies).
        SELECT format('%I.%I (función)', n.nspname, p.proname) AS name
        FROM pg_depend d
        JOIN pg_proc p
          ON p.oid = d.objid
        JOIN pg_namespace n
          ON n.oid = p.pronamespace
        WHERE d.classid = 'pg_proc'::regclass
          AND d.refclassid = 'pg_class'::regclass
          AND d.refobjid = 'public.players'::regclass
          AND d.refobjsubid = v_birth_attnum
          AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    ) AS dependent;

    IF v_dependencies IS NOT NULL THEN
        RAISE EXCEPTION
            'MIGRACION 018: hay objetos que dependen de players.birth_date: %. Elimine o actualice esas dependencias antes de eliminar la fecha en claro.',
            v_dependencies;
    END IF;

    -- ------------------------------------------------------------------------
    -- 3. Closure: the ciphertext becomes mandatory and the plaintext disappears.
    -- ------------------------------------------------------------------------
    ALTER TABLE public.players
        ALTER COLUMN birth_date_encrypted SET NOT NULL;

    ALTER TABLE public.players
        DROP COLUMN birth_date;
END
$$;

-- ----------------------------------------------------------------------------
-- 4. Final grants for `bracket_app` (idempotent).
--
--    The ciphertext stays write-only, the derived age columns are readable and
--    insertable, and the row remains append-only: no UPDATE and no DELETE. The
--    plaintext column no longer exists, so it has no grants left.
-- ----------------------------------------------------------------------------
REVOKE SELECT (birth_date_encrypted) ON public.players FROM bracket_app;
REVOKE SELECT (birth_date_encrypted) ON public.players FROM PUBLIC;
REVOKE UPDATE, DELETE ON public.players FROM bracket_app;

GRANT SELECT (
    id,
    organization_id,
    first_name,
    last_name,
    document_type,
    national_id_hmac,
    issuing_country,
    age_at_reference,
    age_reference_year,
    created_at
) ON public.players TO bracket_app;

GRANT INSERT (
    organization_id,
    first_name,
    last_name,
    document_type,
    national_id_encrypted,
    national_id_hmac,
    issuing_country,
    birth_date_encrypted,
    age_at_reference,
    age_reference_year
) ON public.players TO bracket_app;

COMMIT;
