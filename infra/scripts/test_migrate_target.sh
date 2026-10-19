#!/bin/sh
# Pruebas del runner de migraciones con MIGRATION_TARGET.
#
# Crea bases desechables en el PostgreSQL indicado por las variables libpq
# (PGHOST, PGPORT, PGUSER, PGPASSWORD), aplica la inicialización real y las
# migraciones 001-016, y usa dos migraciones de prueba (017 y 018) para
# verificar el comportamiento del runner sin depender del contenido de las
# migraciones funcionales de la spec 002.
#
# Uso (desde un contenedor postgres:17-alpine):
#   PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres \
#   PGPASSWORD=... sh /infra/scripts/test_migrate_target.sh
set -eu

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

info() {
    printf '\n== %s\n' "$*"
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INFRA_DIR=${INFRA_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}
MIGRATE_SCRIPT=${MIGRATE_SCRIPT:-"$INFRA_DIR/postgres/migrate.sh"}
INIT_DIR=${INIT_DIR:-"$INFRA_DIR/postgres/init"}
SOURCE_MIGRATIONS=${SOURCE_MIGRATIONS:-"$INFRA_DIR/postgres/migrations"}

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGUSER:=postgres}"
: "${PGPASSWORD:?PGPASSWORD es obligatorio para las pruebas del runner}"
export PGHOST PGPORT PGUSER PGPASSWORD
MAINTENANCE_DB=${PGDATABASE:-postgres}

# El runner elige la conexión administrativa por DATABASE_URL o por
# POSTGRES_*; estas pruebas usan siempre POSTGRES_* para no arrastrar la URL
# del job de CI.
unset DATABASE_URL

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/bc-migrate-target.XXXXXX")
RUN_ID="$$_$(date +%s)"
CREATED_DBS=""

cleanup() {
    status=$?
    trap - EXIT HUP INT TERM
    for db in $CREATED_DBS; do
        psql -X -q -d "$MAINTENANCE_DB" \
            -c "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null 2>&1 || true
    done
    rm -rf "$WORK_DIR"
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

psql_maint() {
    psql -X -q -v ON_ERROR_STOP=1 -d "$MAINTENANCE_DB" "$@"
}

psql_db() {
    db=$1
    shift
    psql -X -q -v ON_ERROR_STOP=1 -d "$db" "$@"
}

create_database() {
    db=$1
    psql_maint -c "CREATE DATABASE \"$db\"" >/dev/null
    CREATED_DBS="$CREATED_DBS $db"
}

initialize_database() {
    db=$1
    psql_db "$db" -f "$INIT_DIR/01_schema.sql" >/dev/null
    psql_db "$db" -f "$INIT_DIR/02_public_projections.sql" >/dev/null
    psql_db "$db" -f "$INIT_DIR/03_hardening.sql" >/dev/null
}

run_migrate() {
    db=$1
    migrations_dir=$2
    target=${3-}
    MIGRATION_TARGET=$target \
        MIGRATIONS_DIR=$migrations_dir \
        POSTGRES_DB=$db \
        POSTGRES_USER=$PGUSER \
        PGPASSWORD=$PGPASSWORD \
        PGHOST=$PGHOST \
        PGPORT=$PGPORT \
        sh "$MIGRATE_SCRIPT"
}

migration_count() {
    db=$1
    version=$2
    psql_db "$db" -tA \
        -c "SELECT count(*) FROM schema_migrations WHERE version = '$version'" \
        | tr -d '[:space:]'
}

assert_applied() {
    db=$1
    version=$2
    [ "$(migration_count "$db" "$version")" = "1" ] ||
        fail "la migración $version debería estar aplicada en $db"
}

assert_not_applied() {
    db=$1
    version=$2
    [ "$(migration_count "$db" "$version")" = "0" ] ||
        fail "la migración $version no debería estar aplicada en $db"
}

assert_table_exists() {
    db=$1
    table=$2
    result=$(psql_db "$db" -tA \
        -c "SELECT to_regclass('public.$table') IS NOT NULL")
    [ "$result" = "t" ] || fail "la tabla $table debería existir en $db"
}

assert_table_absent() {
    db=$1
    table=$2
    result=$(psql_db "$db" -tA \
        -c "SELECT to_regclass('public.$table') IS NOT NULL")
    [ "$result" = "f" ] || fail "la tabla $table no debería existir en $db"
}

info "Preparando bases desechables y migraciones de prueba"

psql_maint <<'SQL' >/dev/null
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bracket_app') THEN
        CREATE ROLE bracket_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOBYPASSRLS;
    END IF;
END
$$;
ALTER ROLE bracket_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOBYPASSRLS PASSWORD 'bracket_app_test_password';
SQL

BASE_DIR="$WORK_DIR/migrations-base"
FULL_DIR="$WORK_DIR/migrations-full"
mkdir -p "$BASE_DIR" "$FULL_DIR"

# Base 001-016 con el contenido real del repositorio. Las migraciones
# posteriores se sustituyen por fixtures deterministas para probar el runner
# antes de que existan la 017 y la 018 funcionales.
for path in "$SOURCE_MIGRATIONS"/[0-9]*.sql; do
    [ -f "$path" ] || continue
    filename=$(basename "$path")
    version=${filename%%_*}
    case "$version" in
        001|002|003|004|005|006|007|008|009|010|011|012|013|014|015|016)
            cp "$path" "$BASE_DIR/$filename"
            ;;
    esac
done

[ -f "$BASE_DIR"/016_*.sql ] ||
    fail "no se encontraron las migraciones 001-016 en $SOURCE_MIGRATIONS"

cp "$BASE_DIR"/*.sql "$FULL_DIR"/
cat > "$FULL_DIR/017_migration_target_fixture.sql" <<'SQL'
CREATE TABLE IF NOT EXISTS migration_target_probe_017 (
    id INTEGER PRIMARY KEY
);
SQL
cat > "$FULL_DIR/018_migration_target_fixture.sql" <<'SQL'
CREATE TABLE IF NOT EXISTS migration_target_probe_018 (
    id INTEGER PRIMARY KEY
);
SQL

info "Caso 1: target 017, reejecución, target 018 y no-op con target anterior"

DB1="bc_target_${RUN_ID}_1"
create_database "$DB1"
initialize_database "$DB1"
run_migrate "$DB1" "$BASE_DIR" >/dev/null
assert_applied "$DB1" 016
assert_not_applied "$DB1" 017
assert_not_applied "$DB1" 018

run_migrate "$DB1" "$FULL_DIR" 017 >/dev/null
assert_applied "$DB1" 016
assert_applied "$DB1" 017
assert_not_applied "$DB1" 018
assert_table_exists "$DB1" migration_target_probe_017
assert_table_absent "$DB1" migration_target_probe_018

# Reejecutar el mismo target no duplica ni falla.
run_migrate "$DB1" "$FULL_DIR" 017 >/dev/null
assert_applied "$DB1" 017
assert_not_applied "$DB1" 018
[ "$(migration_count "$DB1" 017)" = "1" ] ||
    fail "reejecutar el target 017 duplicó la fila de schema_migrations"

run_migrate "$DB1" "$FULL_DIR" 018 >/dev/null
assert_applied "$DB1" 017
assert_applied "$DB1" 018
assert_table_exists "$DB1" migration_target_probe_018

# Un target anterior al último aplicado no desaplica nada.
run_migrate "$DB1" "$FULL_DIR" 005 >/dev/null
assert_applied "$DB1" 017
assert_applied "$DB1" 018
assert_table_exists "$DB1" migration_target_probe_017
assert_table_exists "$DB1" migration_target_probe_018

info "Caso 2: targets inválidos, inexistentes y --target"

DB2="bc_target_${RUN_ID}_2"
create_database "$DB2"
initialize_database "$DB2"
run_migrate "$DB2" "$BASE_DIR" >/dev/null
assert_applied "$DB2" 016

for target in 999 ABC 17; do
    if run_migrate "$DB2" "$FULL_DIR" "$target" \
        >"$WORK_DIR/out-$target.log" 2>&1; then
        fail "MIGRATION_TARGET=$target debió fallar"
    fi
    assert_applied "$DB2" 016
    assert_not_applied "$DB2" 017
    assert_not_applied "$DB2" 018
done

# Solo se admite la variable de entorno: una bandera --target no vale.
if MIGRATION_TARGET= \
    MIGRATIONS_DIR="$FULL_DIR" \
    POSTGRES_DB="$DB2" \
    POSTGRES_USER="$PGUSER" \
    PGPASSWORD="$PGPASSWORD" \
    PGHOST="$PGHOST" \
    PGPORT="$PGPORT" \
    sh "$MIGRATE_SCRIPT" --target 017 >"$WORK_DIR/out-flag.log" 2>&1; then
    fail "migrate.sh debió rechazar la bandera --target"
fi
assert_not_applied "$DB2" 017
assert_not_applied "$DB2" 018

info "Caso 3: sin variable aplica todas y checksum posterior alterado"

DB3="bc_target_${RUN_ID}_3"
create_database "$DB3"
initialize_database "$DB3"
run_migrate "$DB3" "$BASE_DIR" >/dev/null
assert_applied "$DB3" 016
assert_not_applied "$DB3" 017

# Sin MIGRATION_TARGET se aplican todas las pendientes (comportamiento actual).
run_migrate "$DB3" "$FULL_DIR" >/dev/null
assert_applied "$DB3" 017
assert_applied "$DB3" 018
assert_table_exists "$DB3" migration_target_probe_017
assert_table_exists "$DB3" migration_target_probe_018

# Alterar un archivo posterior al target debe fallar aunque no se aplique:
# el runner valida los checksums de todos los archivos.
printf '\n-- alterado para probar el checksum\n' \
    >>"$FULL_DIR/018_migration_target_fixture.sql"
if run_migrate "$DB3" "$FULL_DIR" 017 \
    >"$WORK_DIR/out-checksum.log" 2>&1; then
    fail "un checksum alterado posterior al target debió hacer fallar el runner"
fi
grep -q "checksum" "$WORK_DIR/out-checksum.log" ||
    fail "el fallo por checksum alterado debe informar el motivo"

printf '\nOK: todas las pruebas de MIGRATION_TARGET pasaron\n'
