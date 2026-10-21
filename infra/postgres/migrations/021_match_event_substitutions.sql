BEGIN;

-- ============================================================================
-- 021 — Substitution players on match events (additive)
--
-- Adds the two nullable player references a substitution needs, ties them to
-- the tenant-owned player catalog with composite foreign keys and enforces the
-- event contract with a CHECK that stays NOT VALID.
--
--   * Additive only: two nullable UUID columns, two foreign keys and one CHECK.
--     No existing column, table, row, policy or grant is removed or rewritten.
--   * No data rollback: there is no backfill. Legacy `substitution` events keep
--     both columns NULL; they stay readable and are only tolerated inside the
--     already stored rows. `VALIDATE CONSTRAINT` is deliberately out of scope.
--   * The CHECK is added as NOT VALID so the deployment does not fail on legacy
--     rows, but PostgreSQL still enforces it on every INSERT and every UPDATE.
--     Because trigger `trg_validate_match_event_context` (009) rejects event
--     writes on finished, cancelled and administrative-resolution matches,
--     legacy events are immutable in practice and the migration stays viable.
--   * Deployment order: this migration runs **before** the application code
--     that writes `player_out_id`/`player_in_id`. Reverting the code with 021
--     applied is safe (the columns stay unused). The migration is never
--     unapplied; any defect is fixed by a later forward-fix migration.
--   * `match_segment_team_state` is preserved untouched: it already has RLS,
--     its tenant policy and its grants from `init/01`, 011 and 019.
--   * The foreign keys reference `players (id, organization_id)`, the unique
--     index `uq_player_organization_context` created by 015, and replicate
--     `fk_match_events_player_organization` so isolation never relies on RLS
--     alone.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Informative pre-checks. They only raise NOTICE with row counts: the change
--    is additive and must not abort because of legacy rows. They run before the
--    first ALTER, so they also report whether the columns already exist.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_substitutions BIGINT;
    v_segment_state BIGINT;
    v_has_player_out BOOLEAN;
    v_has_player_in BOOLEAN;
    v_pair BIGINT := 0;
    v_legacy BIGINT := 0;
    v_context_key BOOLEAN;
BEGIN
    SELECT count(*)
    INTO v_substitutions
    FROM public.match_events
    WHERE event_type = 'substitution';

    SELECT count(*)
    INTO v_segment_state
    FROM public.match_segment_team_state;

    SELECT EXISTS (
        SELECT 1
        FROM pg_attribute
        WHERE attrelid = 'public.match_events'::regclass
          AND attname = 'player_out_id'
          AND NOT attisdropped
    )
    INTO v_has_player_out;

    SELECT EXISTS (
        SELECT 1
        FROM pg_attribute
        WHERE attrelid = 'public.match_events'::regclass
          AND attname = 'player_in_id'
          AND NOT attisdropped
    )
    INTO v_has_player_in;

    IF v_has_player_out AND v_has_player_in THEN
        EXECUTE $query$
            SELECT count(*)
            FROM public.match_events
            WHERE player_out_id IS NOT NULL AND player_in_id IS NOT NULL
        $query$ INTO v_pair;

        EXECUTE $query$
            SELECT count(*)
            FROM public.match_events
            WHERE player_out_id IS NULL AND player_in_id IS NULL
        $query$ INTO v_legacy;
    ELSE
        v_legacy := v_substitutions;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass('public.uq_player_organization_context')
    )
    INTO v_context_key;

    RAISE NOTICE
        'MIGRACION 021: eventos substitution=% (con par salida/entrada=%, legados sin par=%); match_segment_team_state=% fila(s).',
        v_substitutions, v_pair, v_legacy, v_segment_state;

    RAISE NOTICE
        'MIGRACION 021: columnas player_out_id/player_in_id ya presentes=%/%; indice unico players(id, organization_id) presente=%.',
        v_has_player_out, v_has_player_in, v_context_key;
END
$$;

-- ----------------------------------------------------------------------------
-- 2. Nullable player references. A legacy event keeps both values NULL.
-- ----------------------------------------------------------------------------
ALTER TABLE public.match_events
    ADD COLUMN IF NOT EXISTS player_out_id UUID,
    ADD COLUMN IF NOT EXISTS player_in_id UUID;

-- ----------------------------------------------------------------------------
-- 3. Composite tenant foreign keys, following the 015 pattern.
-- ----------------------------------------------------------------------------
ALTER TABLE public.match_events
    ADD CONSTRAINT fk_match_events_player_out_organization
        FOREIGN KEY (player_out_id, organization_id)
        REFERENCES public.players (id, organization_id) ON DELETE RESTRICT,
    ADD CONSTRAINT fk_match_events_player_in_organization
        FOREIGN KEY (player_in_id, organization_id)
        REFERENCES public.players (id, organization_id) ON DELETE RESTRICT;

-- ----------------------------------------------------------------------------
-- 4. Event contract, enforced on new and modified rows but not validated
--    against legacy rows. It is not removed by this migration.
-- ----------------------------------------------------------------------------
ALTER TABLE public.match_events
    ADD CONSTRAINT chk_match_event_substitution_pair CHECK (
        (event_type = 'substitution'
         AND player_out_id IS NOT NULL
         AND player_in_id IS NOT NULL
         AND player_out_id <> player_in_id
         AND player_id = player_out_id)
        OR (event_type <> 'substitution'
            AND player_out_id IS NULL
            AND player_in_id IS NULL)
    ) NOT VALID;

COMMIT;
