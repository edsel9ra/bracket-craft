"""Throwaway PostgreSQL databases for numbered-migration tests (RF-003, RF-010).

The helpers build a database from the real ``infra/postgres/init`` scripts plus a
contiguous range of the real numbered migrations, so every test starts from a
deterministic schema state without touching the database used by the rest of the
suite. Everything runs through ``DATABASE_ADMIN_URL``: ``bracket_app`` cannot
create databases or apply DDL.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import asyncpg
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_DIR = REPO_ROOT / "infra" / "postgres" / "init"
MIGRATIONS_DIR = REPO_ROOT / "infra" / "postgres" / "migrations"

INIT_FILES = ("01_schema.sql", "02_public_projections.sql", "03_hardening.sql")
MIGRATION_GLOB = "[0-9][0-9][0-9]_*.sql"

# Fixed identifiers so assertions can reference them literally.
ORG = "e0000000-0000-4000-8000-000000000001"
USER = "e0000000-0000-4000-8000-000000000002"
MEMBER = "e0000000-0000-4000-8000-000000000003"
ROLE = "e0000000-0000-4000-8000-000000000004"
TOURNAMENT = "e0000000-0000-4000-8000-000000000010"
VERSION = "e0000000-0000-4000-8000-000000000011"
STAGE_SOURCE = "e0000000-0000-4000-8000-000000000012"
STAGE_TARGET = "e0000000-0000-4000-8000-000000000013"

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug)
VALUES ('{ORG}', 'Migration 019 Org', 'migration-019-org');

INSERT INTO public.users (id, email, password_hash, full_name)
VALUES ('{USER}', 'migration-019@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.roles (id, organization_id, role_definition_id, name, permissions)
SELECT '{ROLE}', '{ORG}', rd.id, 'Owner', '[]'::jsonb
FROM public.role_definitions rd
WHERE rd.code = 'owner';

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 019 Cup', '2026',
    DATE '2026-01-01', 'draft', '{{}}'::jsonb
);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    '{VERSION}', '{ORG}', '{TOURNAMENT}', 1, '{{}}'::jsonb, '{{}}'::jsonb,
    'draft', '{MEMBER}'
);

INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order
) VALUES
    ('{STAGE_SOURCE}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Source', 'round_robin', 1),
    ('{STAGE_TARGET}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Target', 'single_elimination', 2);
"""


def connection_kwargs(url: str, database: str | None = None) -> dict[str, object]:
    """Translate a SQLAlchemy URL into asyncpg connection arguments."""

    parsed = make_url(url)
    return {
        "host": parsed.host or "127.0.0.1",
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "database": database or parsed.database,
    }


async def connect(url: str, database: str | None = None) -> asyncpg.Connection:
    return await asyncpg.connect(**connection_kwargs(url, database))


async def ensure_application_role(admin_url: str) -> None:
    """Create ``bracket_app`` when the cluster does not have it yet.

    The init scripts grant privileges to that role, so a throwaway cluster needs
    the role to exist before ``01_schema.sql`` runs.
    """

    connection = await connect(admin_url)
    try:
        await connection.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bracket_app') THEN
                    CREATE ROLE bracket_app LOGIN NOSUPERUSER NOCREATEDB
                        NOCREATEROLE NOINHERIT NOBYPASSRLS;
                END IF;
            END
            $$;
            """
        )
    finally:
        await connection.close()


async def create_database(admin_url: str) -> str:
    """Create an empty throwaway database and return its name."""

    database = f"bc_migration_{uuid4().hex[:12]}"
    connection = await connect(admin_url)
    try:
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()
    return database


async def drop_database(admin_url: str, database: str) -> None:
    connection = await connect(admin_url)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await connection.close()


async def apply_init(connection: asyncpg.Connection) -> None:
    for filename in INIT_FILES:
        await connection.execute((INIT_DIR / filename).read_text(encoding="utf-8"))


def migration_files(*, first: int = 1, last: int = 999) -> list[Path]:
    paths = []
    for path in sorted(MIGRATIONS_DIR.glob(MIGRATION_GLOB)):
        version = int(path.name[:3])
        if first <= version <= last:
            paths.append(path)
    return paths


def migration_path(version: int) -> Path:
    """Return the migration file for ``version`` or fail loudly when missing."""

    matches = [
        path
        for path in sorted(MIGRATIONS_DIR.glob(MIGRATION_GLOB))
        if int(path.name[:3]) == version
    ]
    if not matches:
        raise FileNotFoundError(
            f"No existe la migración {version:03d} en {MIGRATIONS_DIR}"
        )
    return matches[0]


async def apply_migrations(
    connection: asyncpg.Connection, *, first: int = 1, last: int = 999
) -> None:
    for path in migration_files(first=first, last=last):
        await connection.execute(path.read_text(encoding="utf-8"))


async def apply_migration(connection: asyncpg.Connection, version: int) -> None:
    """Apply one numbered migration file, including its own transaction."""

    await connection.execute(migration_path(version).read_text(encoding="utf-8"))


async def seed_retired_structures(connection: asyncpg.Connection) -> None:
    """Create the tenant, tournament, version and two stages used by 019."""

    await connection.execute(SEED_SQL)


async def insert_tournament_user_role(connection: asyncpg.Connection) -> None:
    await connection.execute(
        f"""
        INSERT INTO public.tournament_user_roles (
            organization_id, organization_user_id, tournament_id, role_id
        ) VALUES ('{ORG}', '{MEMBER}', '{TOURNAMENT}', '{ROLE}')
        """
    )


async def insert_stage_edge(connection: asyncpg.Connection) -> None:
    await connection.execute(
        f"""
        INSERT INTO public.stage_edges (
            organization_id, tournament_id, tournament_version_id,
            source_stage_id, target_stage_id, selector_type, selector_config
        ) VALUES (
            '{ORG}', '{TOURNAMENT}', '{VERSION}',
            '{STAGE_SOURCE}', '{STAGE_TARGET}', 'manual', '{{}}'::jsonb
        )
        """
    )


async def insert_phase_slot(
    connection: asyncpg.Connection, *, source_type: str, slot_code: str = "S1"
) -> None:
    await connection.execute(
        f"""
        INSERT INTO public.phase_slots (
            organization_id, tournament_id, tournament_version_id, stage_id,
            slot_code, source_type, source_reference
        ) VALUES (
            '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_TARGET}',
            $1, $2, '{{}}'::jsonb
        )
        """,
        slot_code,
        source_type,
    )


async def source_type_check_names(connection: asyncpg.Connection) -> list[str]:
    """Return the CHECK constraint names of ``phase_slots.source_type``."""

    rows = await connection.fetch(
        """
        SELECT con.conname
        FROM pg_constraint con
        WHERE con.conrelid = 'public.phase_slots'::regclass
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) ~ '\\msource_type\\M'
        ORDER BY con.conname
        """
    )
    return [row["conname"] for row in rows]


@asynccontextmanager
async def throwaway_database(admin_url: str, *, last: int = 18):
    """Yield a connection to a fresh database at init + 001..``last``.

    ``last=0`` applies only the init scripts, which is the state of a clean
    volume before the numbered migrations run.
    """

    await ensure_application_role(admin_url)
    database = await create_database(admin_url)
    connection = await connect(admin_url, database)
    try:
        await apply_init(connection)
        if last >= 1:
            await apply_migrations(connection, first=1, last=last)
        yield connection
    finally:
        await connection.close()
        await drop_database(admin_url, database)
