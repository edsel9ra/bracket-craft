#!/usr/bin/env bash
set -euo pipefail

case "${APP_ENV:-development}" in
    production|prod)
        if [[ "$POSTGRES_PASSWORD" == "postgres_dev_password" ]] ||
           [[ "$BRACKET_DB_PASSWORD" == "bracket_app_dev_password" ]]; then
            printf '%s\n' 'No se permiten credenciales de desarrollo en producción.' >&2
            exit 1
        fi
        ;;
esac

psql \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 \
    --set=bracket_db_password="$BRACKET_DB_PASSWORD" <<'SQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bracket_app') THEN
        CREATE ROLE bracket_app;
    END IF;
END
$$;

SELECT format(
    'ALTER ROLE bracket_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD %L',
    :'bracket_db_password'
)
\gexec
SQL
