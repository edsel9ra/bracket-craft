BEGIN;

-- ============================================================================
-- 029 — organization_id in the public tournament projection
--
-- Recreates `public.v_public_tournaments` adding `organization_id` (aditivo) so
-- the backend can fix the RLS context of the application role when serving
-- public reads for a tournament (spec 022, D2). The column is internal to the
-- backend and is never included in any public response model (lista cerrada).
--
-- Additive: no table, column of a base table, row, policy, grant or index is
-- added or removed. The only change is a new output column of a read-only
-- projection. `engine_version` stays 2026.1.
--
-- `CREATE OR REPLACE VIEW` is enough because the new column is appended at the
-- end and keeps the existing column names and types. Grants, ownership, RLS
-- exemption and `security_barrier` are preserved by the replacement.
-- ============================================================================

CREATE OR REPLACE VIEW public.v_public_tournaments
WITH (security_barrier = true) AS
SELECT tr.id, tr.name, tr.season, tr.start_date, tr.status, tr.organization_id
FROM public.tournaments tr
JOIN public.organizations org
  ON org.id = tr.organization_id
 AND org.is_active = TRUE
JOIN public.tournament_versions tv
  ON tv.id = tr.published_version_id
 AND tv.organization_id = tr.organization_id
 AND tv.tournament_id = tr.id
 AND tv.status = 'published'
WHERE tr.status IN ('published', 'live', 'finished');

COMMIT;
