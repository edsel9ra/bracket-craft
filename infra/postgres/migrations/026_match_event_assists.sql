BEGIN;

-- ============================================================================
-- 026 — Goal assists on match events (additive)
--
-- Formalises the assist as a field of the goal event: `assist_player_id` is the
-- optional companion of `goal`, never an event of its own and never more than
-- one per goal (RF-007, RF-009, RNF-004).
--
--   * Additive only: one nullable UUID column, one composite foreign key and one
--     CHECK on `public.match_events`. No existing column, table, row, policy,
--     index or grant is removed or rewritten, and `init/01` is not touched.
--   * No backfill: every historical row keeps a NULL assist and stays valid
--     (RF-013). A goal without an assist is never invalid, before or after this
--     migration, and nothing is inferred or filled in.
--   * The CHECK is added **validated** (not NOT VALID). The column is born NULL,
--     so no stored row can violate it: there is no legacy exception to defer, no
--     extra `VALIDATE CONSTRAINT` step, and the migrated volume ends in the same
--     catalog state as a clean one (D-2). PostgreSQL takes a short lock while it
--     verifies the existing rows; run it in a low-activity window.
--   * The CHECK covers only what storage can prove: the assist exists on `goal`
--     alone and never repeats the scorer. Team membership, the valid match
--     roster and presence on the pitch at that minute are API authority
--     (RF-008), answered as 409 `ASSIST_PLAYER_INVALID`, and are deliberately
--     not modelled here.
--   * The composite foreign key `(assist_player_id, organization_id)` to
--     `players (id, organization_id)` replicates the 021 pattern so isolation
--     never relies on RLS alone; `ON DELETE RESTRICT` matches the scorer key,
--     because players are never deleted. It uses the unique index
--     `uq_player_organization_context` created by 015.
--   * No index over `assist_player_id` (D-3): no query filters by it in this
--     scope, players are not deleted, and an index would only add migration
--     surface.
--   * RLS: `match_events` keeps its `tenant_isolation_policy` and `FORCE ROW
--     LEVEL SECURITY`; no policy is added or modified.
--   * Privileges: `match_events` grants SELECT, INSERT, UPDATE and DELETE to
--     `bracket_app` at table level (`init/01_schema.sql`), so the new column
--     inherits them. No column-level grant is added (the `rosters` case of 020 is
--     different: there the grants are per column).
--   * Deployment order: 026 runs **before** the code that writes
--     `assist_player_id`. The previous image ignores the nullable column and
--     keeps working. There is no rollback: any defect is fixed by a new
--     migration (forward-fix). The clean volume (init/00-03 -> 001-026) ends
--     with the same schema as a migrated database.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Informative pre-checks. They only raise NOTICE with counts: the change is
--    additive and must not abort because of historical rows, which never carry
--    an assist. They run before the ALTER, so they also report the current state
--    of the column and of the context key the foreign key needs.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_goals BIGINT;
    v_has_assist BOOLEAN;
    v_with_assist BIGINT := 0;
    v_context_key BOOLEAN;
BEGIN
    SELECT count(*)
    INTO v_goals
    FROM public.match_events
    WHERE event_type = 'goal';

    SELECT EXISTS (
        SELECT 1
        FROM pg_attribute
        WHERE attrelid = 'public.match_events'::regclass
          AND attname = 'assist_player_id'
          AND NOT attisdropped
    )
    INTO v_has_assist;

    IF v_has_assist THEN
        EXECUTE $query$
            SELECT count(*)
            FROM public.match_events
            WHERE assist_player_id IS NOT NULL
        $query$ INTO v_with_assist;
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM pg_index
        WHERE indexrelid = to_regclass('public.uq_player_organization_context')
    )
    INTO v_context_key;

    RAISE NOTICE
        'MIGRACION 026: eventos goal=% (con asistente=%); la columna nace nula y no se reescribe ninguna fila.',
        v_goals, v_with_assist;

    RAISE NOTICE
        'MIGRACION 026: columna assist_player_id ya presente=%; indice unico players(id, organization_id) presente=%.',
        CASE WHEN v_has_assist THEN 'true' ELSE 'false' END,
        CASE WHEN v_context_key THEN 'true' ELSE 'false' END;
END
$$;

-- ----------------------------------------------------------------------------
-- 2. The optional assist. Nullable, no default: «no assist» is NULL and a goal
--    admits at most one because it is a single column.
-- ----------------------------------------------------------------------------
ALTER TABLE public.match_events
    ADD COLUMN IF NOT EXISTS assist_player_id UUID;

-- ----------------------------------------------------------------------------
-- 3. Composite tenant foreign key, following the 015/021 pattern.
-- ----------------------------------------------------------------------------
ALTER TABLE public.match_events
    ADD CONSTRAINT fk_match_events_assist_player_organization
        FOREIGN KEY (assist_player_id, organization_id)
        REFERENCES public.players (id, organization_id) ON DELETE RESTRICT;

-- ----------------------------------------------------------------------------
-- 4. Assist contract, validated on every existing row and enforced on every
--    INSERT and UPDATE afterwards: an assist exists only on `goal` and never
--    repeats the scorer of that same goal.
-- ----------------------------------------------------------------------------
ALTER TABLE public.match_events
    ADD CONSTRAINT chk_match_event_assist CHECK (
        (event_type = 'goal'
         AND (assist_player_id IS NULL OR assist_player_id <> player_id))
        OR (event_type <> 'goal' AND assist_player_id IS NULL)
    );

COMMIT;
