BEGIN;

-- ============================================================================
-- 017 — Player birth date encryption: intermediate schema
--
-- Prepares the database for the write-only birth date while the plaintext
-- column still exists for the administrative backfill. After this migration:
--
--   * `birth_date_encrypted` holds the ciphertext written by the application.
--   * `age_at_reference` and `age_reference_year` hold the materialized age of
--     every historical player, so no read path needs to decrypt anything.
--   * `bracket_app` can no longer SELECT or INSERT `birth_date`, cannot SELECT
--     the ciphertext, and can read/write the derived age columns.
--   * `v_public_tournament_players` computes the age from the materialized
--     values and keeps the exact same columns, order and types.
--
-- The plaintext column is removed by migration 018, after the backfill. This
-- migration is transactional and idempotent while that column still exists;
-- after 018 the defensive checks below fail by design.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. New columns. The ciphertext stays nullable until 018; the age columns are
--    filled below and become mandatory.
-- ----------------------------------------------------------------------------
ALTER TABLE public.players
    ADD COLUMN IF NOT EXISTS birth_date_encrypted BYTEA,
    ADD COLUMN IF NOT EXISTS age_at_reference SMALLINT,
    ADD COLUMN IF NOT EXISTS age_reference_year SMALLINT;

-- ----------------------------------------------------------------------------
-- 2. Reject impossible historical dates before writing anything.
--
--    A row without a plaintext source is only acceptable when it already has
--    the ciphertext (a player created by the new application between 017 and
--    018). The report lists the row count and internal identifiers, never the
--    date, the document or any personal value.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_bad_count INT;
    v_bad_ids TEXT;
BEGIN
    SELECT count(*)
    INTO v_bad_count
    FROM public.players p
    WHERE p.birth_date_encrypted IS NULL
      AND (
          p.birth_date IS NULL
          OR p.birth_date > CURRENT_DATE
          OR p.birth_date > (p.created_at AT TIME ZONE 'UTC')::date
      );

    IF v_bad_count > 0 THEN
        SELECT string_agg(invalid.id::text, ', ' ORDER BY invalid.id)
        INTO v_bad_ids
        FROM (
            SELECT p.id
            FROM public.players p
            WHERE p.birth_date_encrypted IS NULL
              AND (
                  p.birth_date IS NULL
                  OR p.birth_date > CURRENT_DATE
                  OR p.birth_date > (p.created_at AT TIME ZONE 'UTC')::date
              )
            ORDER BY p.id
            LIMIT 20
        ) AS invalid;

        RAISE EXCEPTION
            'MIGRACION 017: % jugador(es) con fecha de nacimiento nula, futura o posterior a su creación. Identificadores internos: %. Corrija los datos y reintente.',
            v_bad_count,
            v_bad_ids;
    END IF;
END
$$;

-- ----------------------------------------------------------------------------
-- 3. Materialize the historical age.
--
--    Reference year: the start year of the tournament of the roster registered
--    first (`registered_at`, ties broken by the roster id); without rosters,
--    the year of `players.created_at` in UTC. The age uses calendar years:
--    reference year minus birth year.
-- ----------------------------------------------------------------------------
WITH first_roster AS (
    SELECT DISTINCT ON (r.player_id)
           r.player_id,
           EXTRACT(YEAR FROM t.start_date)::INT AS reference_year
    FROM public.rosters r
    JOIN public.tournaments t
      ON t.id = r.tournament_id
     AND t.organization_id = r.organization_id
    ORDER BY r.player_id, r.registered_at, r.id
), historical_reference AS (
    SELECT p.id,
           COALESCE(
               fr.reference_year,
               EXTRACT(YEAR FROM (p.created_at AT TIME ZONE 'UTC'))::INT
           ) AS reference_year
    FROM public.players p
    LEFT JOIN first_roster fr ON fr.player_id = p.id
)
UPDATE public.players p
SET age_reference_year = reference.reference_year,
    age_at_reference = reference.reference_year - EXTRACT(YEAR FROM p.birth_date)::INT
FROM historical_reference reference
WHERE p.id = reference.id
  AND p.birth_date IS NOT NULL;

-- Rows created by the new application already carry their own reference; the
-- historical backfill must never overwrite them.
ALTER TABLE public.players
    ALTER COLUMN age_at_reference SET NOT NULL,
    ALTER COLUMN age_reference_year SET NOT NULL;

-- The new application inserts players without the plaintext column.
ALTER TABLE public.players
    ALTER COLUMN birth_date DROP NOT NULL;

-- ----------------------------------------------------------------------------
-- 4. Column grants.
--
--    The plaintext becomes unreadable and unwritable for the application and
--    for PUBLIC. The ciphertext is insert-only (write-only pattern, like
--    `national_id_encrypted`) and the derived age columns are readable and
--    insertable. No UPDATE or DELETE is granted: the row stays append-only.
-- ----------------------------------------------------------------------------
REVOKE SELECT (birth_date), INSERT (birth_date)
    ON public.players FROM bracket_app;
REVOKE SELECT (birth_date), INSERT (birth_date)
    ON public.players FROM PUBLIC;

REVOKE SELECT (birth_date_encrypted)
    ON public.players FROM bracket_app;
REVOKE SELECT (birth_date_encrypted)
    ON public.players FROM PUBLIC;

GRANT SELECT (age_at_reference, age_reference_year)
    ON public.players TO bracket_app;
GRANT INSERT (birth_date_encrypted, age_at_reference, age_reference_year)
    ON public.players TO bracket_app;

-- ----------------------------------------------------------------------------
-- 5. Public projection.
--
--    Same columns, order and types as before, with `public_age` still an
--    integer: materialized age plus the tournament year delta. The view owner
--    keeps applying migrations (exempt from RLS) and `security_invoker` is
--    deliberately not enabled, so anonymous readers still get published rows.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.v_public_tournament_players
WITH (security_barrier = true) AS
SELECT
    r.tournament_id,
    p.id AS player_id,
    p.first_name,
    p.last_name,
    r.dorsal_number,
    r.team_id,
    (
        p.age_at_reference
        + (EXTRACT(YEAR FROM t.start_date)::INT - p.age_reference_year)
    )::INT AS public_age,
    CASE WHEN r.photo_consent THEN r.photo_object_key ELSE NULL END AS photo_url
FROM public.rosters r
JOIN public.players p
  ON p.id = r.player_id
 AND p.organization_id = r.organization_id
JOIN public.tournaments t
  ON t.id = r.tournament_id
 AND t.organization_id = r.organization_id
JOIN public.organizations org
  ON org.id = t.organization_id
 AND org.is_active = TRUE
WHERE r.is_active = TRUE
  AND t.status IN ('published', 'live', 'finished');

REVOKE ALL ON public.v_public_tournament_players FROM PUBLIC;
GRANT SELECT ON public.v_public_tournament_players TO bracket_app;

COMMIT;
