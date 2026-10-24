BEGIN;

-- ============================================================================
-- 024 — One identity per account and provider (additive)
--
-- Guarantees in storage, not in the application, that an account has at most
-- one identity per provider (RF-13, RF-22, RNF-11). Together with the existing
-- `uq_auth_provider_subject`, the pair closes both directions: an identity
-- belongs to exactly one account and an account has at most one Google
-- identity, so two simultaneous attempts cannot leave two accounts or two
-- identities and no decision depends on "check and then write".
--
--   * Additive only: one UNIQUE constraint on `public.auth_identities`. No
--     column, table, row, policy, grant or index is added, removed or
--     rewritten. PostgreSQL builds the backing index while it validates.
--   * No automatic repair: the pre-check aborts the whole migration when an
--     account already has more than one identity of the same provider, naming
--     the count of duplicated accounts. It never deletes, merges or rewrites
--     rows; the anomaly is reviewed by hand (RNF-11).
--   * No grants and no RLS: `auth_identities` is a platform table, not
--     tenant-owned. The application role already holds the column privileges
--     it needs (SELECT/INSERT on user_id, provider, provider_subject); the new
--     flow only inserts and never updates or deletes.
--   * `init/01` is untouched: a clean volume runs init/00-03 and then
--     001..024, ending with the same schema as a migrated database.
--   * Deployment order: apply with `MIGRATION_TARGET=024` **before** the code
--     that writes Google identities. The code works against the previous
--     schema, but without this constraint two simultaneous attempts could
--     leave two identities on one account: the constraint is the guarantee,
--     not a redundant defence. There is no rollback: any defect is fixed by a
--     new migration (forward-fix).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. Pre-check. It aborts the migration when an account already has more than
--    one identity of the same provider and names the count of duplicated
--    accounts (not of duplicated rows). It runs before the ALTER, so a failure
--    leaves the table exactly as it was, with no constraint partially added.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_duplicated_accounts BIGINT;
BEGIN
    SELECT count(*)
    INTO v_duplicated_accounts
    FROM (
        SELECT user_id, provider
        FROM public.auth_identities
        GROUP BY user_id, provider
        HAVING count(*) > 1
    ) duplicated;

    IF v_duplicated_accounts > 0 THEN
        RAISE EXCEPTION
            'MIGRACION 024 abortada: auth_identities incumple la identidad unica: cuentas con mas de una identidad del mismo proveedor=%. No se borra, fusiona ni reescribe ninguna fila (RNF-11): revisa los datos a mano y aplica la migracion de nuevo.',
            v_duplicated_accounts;
    END IF;

    RAISE NOTICE
        'MIGRACION 024: sin cuentas con mas de una identidad por proveedor; se anade la restriccion uq_auth_identity_user_provider.';
END
$$;

-- ----------------------------------------------------------------------------
-- 2. The invariant. A unique constraint (not a unique index) so the catalog is
--    the same on a clean volume and on a migrated one, and clients can rely on
--    the constraint name in error messages. Validated on purpose: step 1 has
--    already proven there are no duplicates.
-- ----------------------------------------------------------------------------
ALTER TABLE public.auth_identities
    ADD CONSTRAINT uq_auth_identity_user_provider UNIQUE (user_id, provider);

COMMIT;
