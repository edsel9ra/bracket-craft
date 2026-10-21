BEGIN;

-- ============================================================================
-- 023 — Persisted stage legs (additive)
--
-- Stores the format of a scoring phase (league or group stage) so the manual
-- pairing limit can read how many meetings per pair the format allows: one leg
-- admits one meeting, two legs admit two. Until now the legs were only a draw
-- parameter and the drawn format was not queryable (RF-009, R26).
--
--   * Additive only: one column with its default and one CHECK on
--     `public.stages`. No table, row, policy, grant or index is added, removed
--     or rewritten.
--   * No backfill on purpose: rows that already exist keep one leg, because the
--     legs of an old draw cannot be reconstructed reliably. A historical
--     two-leg league keeps the one-meeting limit until its calendar is drawn
--     again; published versions do not admit manual additions anyway.
--   * `SMALLINT NOT NULL DEFAULT 1 CHECK (schedule_legs IN (1, 2))`: one leg is
--     the only safe default. Two legs are written by the league draw, copied by
--     the version clone, and never inferred from the number of matches.
--   * The existing structure triggers already reject UPDATEs on `stages` of a
--     published or archived version (`ZZ409`), so a published format cannot be
--     rewritten. No new trigger is added.
--   * `stages` is tenant-owned: the column inherits the existing RLS policy and
--     the table GRANT. No new policy is needed.
--   * Deployment order: apply with `MIGRATION_TARGET=023` **before** the backend
--     that reads and writes the column, and after 022. There is no rollback:
--     any defect is fixed by a new migration (forward-fix). The clean volume
--     (`init/00-03` -> 001-023) ends with the same schema as a migrated
--     database.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. The column. Adding it with a default leaves every existing stage at one
--    leg without rewriting rows (PostgreSQL 11+ stores the default in the
--    catalog); there is no UPDATE and no data backfill.
-- ----------------------------------------------------------------------------
ALTER TABLE public.stages
    ADD COLUMN schedule_legs SMALLINT NOT NULL DEFAULT 1;

-- ----------------------------------------------------------------------------
-- 2. The only two supported formats. A validated CHECK is enough because the
--    column is new and step 1 already left every row at 1.
-- ----------------------------------------------------------------------------
ALTER TABLE public.stages
    ADD CONSTRAINT chk_stages_schedule_legs CHECK (schedule_legs IN (1, 2));

COMMIT;
