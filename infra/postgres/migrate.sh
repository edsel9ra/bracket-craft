#!/bin/sh
set -eu

if [ -n "${DATABASE_URL:-}" ]; then
    database_target=${DATABASE_URL}
    case "$database_target" in
        postgresql+*://*) database_target="postgresql://${database_target#*://}" ;;
    esac
    db_host=""
    db_port=""
else
    : "${POSTGRES_DB:?POSTGRES_DB is required when DATABASE_URL is not set}"
    : "${POSTGRES_USER:?POSTGRES_USER is required when DATABASE_URL is not set}"
    : "${PGPASSWORD:?PGPASSWORD is required when DATABASE_URL is not set}"
    db_host=${PGHOST:-${DB_HOST:-db}}
    db_port=${PGPORT:-${DB_PORT:-5432}}
    database_target=""
fi

run_psql() {
    if [ -n "$database_target" ]; then
        psql "$database_target" -v ON_ERROR_STOP=1 "$@"
    else
        psql -h "$db_host" -p "$db_port" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 "$@"
    fi
}

run_psql <<'SQL'
SELECT pg_advisory_lock(hashtext('bracket_craft:schema_migrations'));
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version VARCHAR(20) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    checksum CHAR(64),
    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE public.schema_migrations
    ADD COLUMN IF NOT EXISTS checksum CHAR(64);
SELECT pg_advisory_unlock(hashtext('bracket_craft:schema_migrations'));
SQL

MIGRATIONS_DIR=${MIGRATIONS_DIR:-$(dirname "$0")/migrations}
MIGRATION_SQL=$(mktemp "${TMPDIR:-/tmp}/bracket-craft-migration.XXXXXX")
cleanup() {
    rm -f "$MIGRATION_SQL"
}
trap cleanup EXIT HUP INT TERM

for migration in "$MIGRATIONS_DIR"/[0-9]*.sql; do
    [ -f "$migration" ] || continue

    filename=$(basename "$migration")
    version=${filename%%_*}
    name=${filename#*_}
    name=${name%.sql}
    checksum=$(sha256sum "$migration" | awk '{print $1}')
    sed \
        -e '1{/^[[:space:]]*BEGIN;[[:space:]]*$/d;}' \
        -e '${/^[[:space:]]*COMMIT;[[:space:]]*$/d;}' \
        "$migration" > "$MIGRATION_SQL"

    run_psql \
        -v migration_version="$version" \
        -v migration_name="$name" \
        -v migration_checksum="$checksum" \
        -v migration_path="$MIGRATION_SQL" <<'SQL'
BEGIN;
SELECT pg_advisory_lock(hashtext('bracket_craft:schema_migrations'));
SELECT
    COALESCE(
        bool_or(checksum IS NOT NULL AND checksum <> :'migration_checksum'),
        FALSE
    ) AS checksum_mismatch,
    NOT EXISTS (
        SELECT 1
        FROM public.schema_migrations
        WHERE version = :'migration_version'
    ) AS should_apply
FROM public.schema_migrations
WHERE version = :'migration_version';
\gset
\if :checksum_mismatch
SELECT pg_advisory_unlock(hashtext('bracket_craft:schema_migrations'));
ROLLBACK;
\quit 3
\endif
\if :should_apply
\i :migration_path
INSERT INTO public.schema_migrations (version, name, checksum)
VALUES (:'migration_version', :'migration_name', :'migration_checksum');
\else
UPDATE public.schema_migrations
SET checksum = COALESCE(checksum, :'migration_checksum'),
    name = :'migration_name'
WHERE version = :'migration_version';
\endif
SELECT pg_advisory_unlock(hashtext('bracket_craft:schema_migrations'));
COMMIT;
SQL
done

if [ -n "${PLATFORM_ADMIN_EMAIL:-}" ]; then
    run_psql -v platform_admin_email="$PLATFORM_ADMIN_EMAIL" <<'SQL'
INSERT INTO public.platform_admins (user_id, role_code, is_active)
SELECT id, 'platform_admin', TRUE
FROM public.users
WHERE LOWER(email) = LOWER(:'platform_admin_email')
ON CONFLICT (user_id) DO UPDATE
SET role_code = 'platform_admin', is_active = TRUE;
SQL
fi
