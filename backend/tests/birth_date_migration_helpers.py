"""Throwaway PostgreSQL databases for the birth-date encryption migrations.

The helpers build a database from ``infra/postgres/init`` plus a contiguous
range of the real numbered migrations, so every test starts from a
deterministic schema state (for example init + 001-016) without touching the
database used by the rest of the suite.

Everything runs through the administrator URL: ``bracket_app`` cannot create
databases or apply DDL. The seed scenario below is shared by the tests of the
017 intermediate state, the backfill command and the 018 closure, so all three
tasks describe the same historical data.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_DIR = REPO_ROOT / "infra" / "postgres" / "init"
MIGRATIONS_DIR = REPO_ROOT / "infra" / "postgres" / "migrations"

INIT_FILES = ("01_schema.sql", "02_public_projections.sql", "03_hardening.sql")
MIGRATION_GLOB = "[0-9][0-9][0-9]_*.sql"


# Fixed identifiers so assertions can reference them literally and the seed is
# stable across runs.
ORG_A = "a0000000-0000-4000-8000-000000000001"
ORG_B = "b0000000-0000-4000-8000-000000000001"
USER_A = "a0000000-0000-4000-8000-000000000002"
USER_B = "b0000000-0000-4000-8000-000000000002"
MEMBER_A = "a0000000-0000-4000-8000-000000000003"
MEMBER_B = "b0000000-0000-4000-8000-000000000003"
TEAM_A = "a0000000-0000-4000-8000-000000000004"
TEAM_B = "b0000000-0000-4000-8000-000000000004"

TOURNAMENT_A_2024 = "a0000000-0000-4000-8000-000000000010"
TOURNAMENT_A_2026 = "a0000000-0000-4000-8000-000000000011"
TOURNAMENT_A_2029 = "a0000000-0000-4000-8000-000000000012"
TOURNAMENT_B_2028 = "b0000000-0000-4000-8000-000000000010"
VERSION_A_2026 = "a0000000-0000-4000-8000-000000000013"
STAGE_A_2026 = "a0000000-0000-4000-8000-000000000014"
MATCH_A = "a0000000-0000-4000-8000-000000000015"
MATCH_ROSTER_A = "a0000000-0000-4000-8000-000000000016"

ROSTER_P1_2024 = "a0000000-0000-4000-8000-000000000021"
ROSTER_P1_2026 = "a0000000-0000-4000-8000-000000000022"
ROSTER_P2_2024 = "a0000000-0000-4000-8000-000000000023"
ROSTER_P2_2029 = "a0000000-0000-4000-8000-000000000024"
ROSTER_P4_2028 = "b0000000-0000-4000-8000-000000000021"

PLAYER_OLDEST_ROSTER = "c0000000-0000-4000-8000-000000000001"
PLAYER_TIE_BREAK = "c0000000-0000-4000-8000-000000000002"
PLAYER_WITHOUT_ROSTER = "c0000000-0000-4000-8000-000000000003"
PLAYER_OTHER_ORGANIZATION = "c0000000-0000-4000-8000-000000000004"

# ``created_at`` of PLAYER_WITHOUT_ROSTER is 2028-01-01 in UTC but still
# 2027-12-31 in America/New_York: the historical reference must use UTC.
WITHOUT_ROSTER_CREATED_AT = "2028-01-01 02:00:00+00"
WITHOUT_ROSTER_SESSION_TIMEZONE = "America/New_York"


@dataclass(frozen=True)
class BirthDateScenario:
    """Identifiers and expected historical ages of the seeded catalog."""

    organization_a: str = ORG_A
    organization_b: str = ORG_B
    user_a: str = USER_A
    user_b: str = USER_B
    tournament_a_2024: str = TOURNAMENT_A_2024
    tournament_a_2026: str = TOURNAMENT_A_2026
    tournament_a_2029: str = TOURNAMENT_A_2029
    tournament_b_2028: str = TOURNAMENT_B_2028
    player_oldest_roster: str = PLAYER_OLDEST_ROSTER
    player_tie_break: str = PLAYER_TIE_BREAK
    player_without_roster: str = PLAYER_WITHOUT_ROSTER
    player_other_organization: str = PLAYER_OTHER_ORGANIZATION
    match_a: str = MATCH_A
    # reference year and materialized age per player
    expected_reference_year: dict[str, int] = field(default_factory=dict)
    expected_age_at_reference: dict[str, int] = field(default_factory=dict)


SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG_A}', 'Birth Date Org A', 't002-birth-a'),
    ('{ORG_B}', 'Birth Date Org B', 't002-birth-b');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER_A}', 't002-birth-a@example.test', 'hash', 'Owner A'),
    ('{USER_B}', 't002-birth-b@example.test', 'hash', 'Owner B');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active) VALUES
    ('{MEMBER_A}', '{ORG_A}', '{USER_A}', TRUE),
    ('{MEMBER_B}', '{ORG_B}', '{USER_B}', TRUE);

INSERT INTO public.teams (id, organization_id, name, short_code) VALUES
    ('{TEAM_A}', '{ORG_A}', 'Birth Team A', 'BTA'),
    ('{TEAM_B}', '{ORG_B}', 'Birth Team B', 'BTB');

-- Tournaments: 2024 (oldest roster), 2026 (published, shows the public age),
-- 2029 (same registration instant as the 2024 roster) and 2028 in tenant B.
INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES
    ('{TOURNAMENT_A_2024}', '{ORG_A}', 'Birth Cup 2024', '2024',
     '2024-03-01', 'draft', '{{}}'),
    ('{TOURNAMENT_A_2026}', '{ORG_A}', 'Birth Cup 2026', '2026',
     '2026-01-01', 'draft', '{{}}'),
    ('{TOURNAMENT_A_2029}', '{ORG_A}', 'Birth Cup 2029', '2029',
     '2029-06-01', 'draft', '{{}}'),
    ('{TOURNAMENT_B_2028}', '{ORG_B}', 'Birth Cup B 2028', '2028',
     '2028-02-01', 'draft', '{{}}');

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    '{VERSION_A_2026}', '{ORG_A}', '{TOURNAMENT_A_2026}', 1, '{{}}', '{{}}',
    'draft', '{MEMBER_A}'
);

INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order
) VALUES (
    '{STAGE_A_2026}', '{ORG_A}', '{TOURNAMENT_A_2026}', '{VERSION_A_2026}',
    'Group', 'round_robin', 1
);

INSERT INTO public.tournament_teams (
    organization_id, tournament_id, team_id, status
) VALUES
    ('{ORG_A}', '{TOURNAMENT_A_2024}', '{TEAM_A}', 'registered'),
    ('{ORG_A}', '{TOURNAMENT_A_2026}', '{TEAM_A}', 'registered'),
    ('{ORG_A}', '{TOURNAMENT_A_2029}', '{TEAM_A}', 'registered'),
    ('{ORG_B}', '{TOURNAMENT_B_2028}', '{TEAM_B}', 'registered');

INSERT INTO public.stage_teams (
    organization_id, tournament_id, tournament_version_id, stage_id, group_id,
    team_id
) VALUES (
    '{ORG_A}', '{TOURNAMENT_A_2026}', '{VERSION_A_2026}', '{STAGE_A_2026}',
    NULL, '{TEAM_A}'
);

-- Historical players. Dates, creation instants and rosters are chosen so the
-- reference year is only correct with registered_at ordering and UTC.
INSERT INTO public.players (
    id, organization_id, first_name, last_name, document_type,
    national_id_encrypted, national_id_hmac, issuing_country, birth_date,
    created_at
) VALUES
    ('{PLAYER_OLDEST_ROSTER}', '{ORG_A}', 'Oldest', 'Roster', 'DNI',
     decode('0101', 'hex'), repeat('1', 64), 'ARG', '2000-05-15',
     '2025-01-01 00:00:00+00'),
    ('{PLAYER_TIE_BREAK}', '{ORG_A}', 'Tie', 'Break', 'DNI',
     decode('0202', 'hex'), repeat('2', 64), 'ARG', '1990-12-31',
     '2025-06-01 00:00:00+00'),
    ('{PLAYER_WITHOUT_ROSTER}', '{ORG_A}', 'No', 'Roster', 'DNI',
     decode('0303', 'hex'), repeat('3', 64), 'ARG', '2001-07-04',
     '{WITHOUT_ROSTER_CREATED_AT}'),
    ('{PLAYER_OTHER_ORGANIZATION}', '{ORG_B}', 'Other', 'Tenant', 'DNI',
     decode('0404', 'hex'), repeat('4', 64), 'ARG', '2010-02-28',
     '2026-05-05 00:00:00+00');

INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    is_active, photo_consent, registered_at, valid_from, eligible_from
) VALUES
    ('{ROSTER_P1_2026}', '{ORG_A}', '{TOURNAMENT_A_2026}', '{TEAM_A}',
     '{PLAYER_OLDEST_ROSTER}', 1, TRUE, FALSE,
     '2026-02-01 00:00:00+00', '2026-02-01 00:00:00+00',
     '2026-02-01 00:00:00+00'),
    ('{ROSTER_P1_2024}', '{ORG_A}', '{TOURNAMENT_A_2024}', '{TEAM_A}',
     '{PLAYER_OLDEST_ROSTER}', 2, TRUE, FALSE,
     '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00',
     '2026-01-01 00:00:00+00'),
    ('{ROSTER_P2_2024}', '{ORG_A}', '{TOURNAMENT_A_2024}', '{TEAM_A}',
     '{PLAYER_TIE_BREAK}', 3, TRUE, FALSE,
     '2026-03-01 12:00:00+00', '2026-03-01 12:00:00+00',
     '2026-03-01 12:00:00+00'),
    ('{ROSTER_P2_2029}', '{ORG_A}', '{TOURNAMENT_A_2029}', '{TEAM_A}',
     '{PLAYER_TIE_BREAK}', 4, TRUE, FALSE,
     '2026-03-01 12:00:00+00', '2026-03-01 12:00:00+00',
     '2026-03-01 12:00:00+00'),
    ('{ROSTER_P4_2028}', '{ORG_B}', '{TOURNAMENT_B_2028}', '{TEAM_B}',
     '{PLAYER_OTHER_ORGANIZATION}', 1, TRUE, FALSE,
     '2028-01-01 00:00:00+00', '2028-01-01 00:00:00+00',
     '2028-01-01 00:00:00+00');

-- Published match and classic lineup so ``v_public_match_lineups`` has a row.
INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    home_team_id, status, match_date, created_at
) VALUES (
    '{MATCH_A}', '{ORG_A}', '{TOURNAMENT_A_2026}', '{VERSION_A_2026}',
    '{STAGE_A_2026}', '{TEAM_A}', 'scheduled', '2026-01-05 12:00:00+00',
    '2026-01-05 00:00:00+00'
);

INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES (
    '{MATCH_ROSTER_A}', '{ORG_A}', '{MATCH_A}', '{ROSTER_P1_2026}',
    '{PLAYER_OLDEST_ROSTER}', '{TEAM_A}', '{TOURNAMENT_A_2026}', NULL,
    'starter', TRUE
);

-- Publish only after the draft structure exists: matches cannot be inserted
-- into a published version.
UPDATE public.tournament_versions
SET status = 'published'
WHERE id = '{VERSION_A_2026}';

UPDATE public.tournaments
SET status = 'published',
    published_version_id = '{VERSION_A_2026}'
WHERE id = '{TOURNAMENT_A_2026}';
"""


def scenario() -> BirthDateScenario:
    """Return the seeded scenario with its expected historical ages."""

    return BirthDateScenario(
        expected_reference_year={
            PLAYER_OLDEST_ROSTER: 2024,
            PLAYER_TIE_BREAK: 2024,
            PLAYER_WITHOUT_ROSTER: 2028,
            PLAYER_OTHER_ORGANIZATION: 2028,
        },
        expected_age_at_reference={
            PLAYER_OLDEST_ROSTER: 24,
            PLAYER_TIE_BREAK: 34,
            PLAYER_WITHOUT_ROSTER: 27,
            PLAYER_OTHER_ORGANIZATION: 18,
        },
    )


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


async def create_database(admin_url: str) -> str:
    """Create an empty throwaway database and return its name."""

    database = f"bc_birth_{uuid4().hex[:12]}"
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


async def seed_birth_date_scenario(connection: asyncpg.Connection) -> BirthDateScenario:
    """Seed two tenants with historical players and rosters."""

    await connection.execute(SEED_SQL)
    return scenario()


@asynccontextmanager
async def throwaway_database(admin_url: str, *, last: int = 16):
    """Yield a connection to a fresh database at init + 001..``last``."""

    database = await create_database(admin_url)
    connection = await connect(admin_url, database)
    try:
        await apply_init(connection)
        await apply_migrations(connection, first=1, last=last)
        yield connection
    finally:
        await connection.close()
        await drop_database(admin_url, database)


def migration_environment(admin_url: str, database: str) -> dict[str, str]:
    """Environment needed by the backfill command against a throwaway database.

    Kept here so T003 and T004 can reuse the same URL shape without importing
    the application settings.
    """

    parsed = make_url(admin_url)
    driver = "postgresql+asyncpg"
    environment = {
        "DATABASE_ADMIN_URL": (
            f"{driver}://{parsed.username}:{parsed.password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
    }
    if "PLAYER_DATA_KEY" in os.environ:
        environment["PLAYER_DATA_KEY"] = os.environ["PLAYER_DATA_KEY"]
    return environment
