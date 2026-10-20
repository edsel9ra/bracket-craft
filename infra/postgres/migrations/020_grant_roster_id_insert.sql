BEGIN;

-- ============================================================================
-- 020 — Forward-fix: allow the application role to insert a pre-generated
-- roster id.
--
-- The bulk roster import (N-2) uploads photos before opening the write
-- transaction, so it needs the roster id in advance to build a stable object
-- key and to compensate uploads on failure. PostgreSQL generates the id only
-- inside the INSERT; the application therefore supplies it explicitly.
--
-- `bracket_app` has column-level INSERT grants on `rosters` but no table-wide
-- INSERT, so `INSERT INTO rosters (id, ...)` failed with
-- "permission denied for table rosters". This non-destructive forward-fix adds
-- only the `id` column privilege; `has_table_privilege(..., 'INSERT')` stays
-- false. It is applied after 019. `init/01` includes the same column grant so
-- a clean volume reaches the same state.
-- ============================================================================

GRANT INSERT (id) ON public.rosters TO bracket_app;

COMMIT;
