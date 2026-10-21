"""Migration 021: substitution player columns, composite FKs and deferred CHECK.

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so the additive change is validated both on an
already migrated volume (020 -> 021) and on the clean-volume chain
(init + 001..021). The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and
``DATABASE_ADMIN_URL`` because creating databases and applying DDL require a
role the application role does not have.

Assertions cover the two nullable UUID columns, the composite tenant foreign
keys to ``players (id, organization_id)``, the ``NOT VALID`` ``CHECK`` that is
still enforced on new and modified rows, the preservation of legacy
``substitution`` events, the immutability trigger from 009, the informative
pre-checks and the equality between the clean and the migrated chains.
"""

from __future__ import annotations

import asyncpg
import pytest

from app.modules.rule_contract import FORMATION_CODES
from migration_helpers import apply_migration, throwaway_database

ORG = "21000000-0000-4000-8000-000000000001"
OTHER_ORG = "21000000-0000-4000-8000-000000000002"
USER = "21000000-0000-4000-8000-000000000003"
MEMBER = "21000000-0000-4000-8000-000000000004"
TOURNAMENT = "21000000-0000-4000-8000-000000000010"
VERSION = "21000000-0000-4000-8000-000000000011"
STAGE = "21000000-0000-4000-8000-000000000012"
TEAM = "21000000-0000-4000-8000-000000000013"
TOURNAMENT_TEAM = "21000000-0000-4000-8000-000000000014"
STAGE_TEAM = "21000000-0000-4000-8000-000000000015"
MATCH = "21000000-0000-4000-8000-000000000016"
SEGMENT = "21000000-0000-4000-8000-000000000017"
SEGMENT_STATE = "21000000-0000-4000-8000-000000000018"
PLAYER_OUT = "21000000-0000-4000-8000-000000000020"
PLAYER_IN = "21000000-0000-4000-8000-000000000021"
FOREIGN_PLAYER = "21000000-0000-4000-8000-000000000022"
ROSTER_OUT = "21000000-0000-4000-8000-000000000030"
ROSTER_IN = "21000000-0000-4000-8000-000000000031"
MATCH_ROSTER_OUT = "21000000-0000-4000-8000-000000000040"
MATCH_ROSTER_IN = "21000000-0000-4000-8000-000000000041"
LEGACY_EVENT = "21000000-0000-4000-8000-000000000050"

CHECK_NAME = "chk_match_event_substitution_pair"
FK_OUT = "fk_match_events_player_out_organization"
FK_IN = "fk_match_events_player_in_organization"

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG}', 'Migration 021 Org', 'migration-021-org'),
    ('{OTHER_ORG}', 'Migration 021 Other', 'migration-021-other');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER}', 'migration-021@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.players (
    id, organization_id, first_name, last_name, document_type,
    national_id_encrypted, national_id_hmac, issuing_country,
    birth_date_encrypted, age_at_reference, age_reference_year
) VALUES
    ('{PLAYER_OUT}', '{ORG}', 'Out', 'Player', 'DNI',
     decode('01', 'hex'), repeat('a', 64), 'ARG', decode('10', 'hex'), 25, 2026),
    ('{PLAYER_IN}', '{ORG}', 'In', 'Player', 'DNI',
     decode('02', 'hex'), repeat('b', 64), 'ARG', decode('11', 'hex'), 24, 2026),
    ('{FOREIGN_PLAYER}', '{OTHER_ORG}', 'Foreign', 'Player', 'DNI',
     decode('03', 'hex'), repeat('c', 64), 'ARG', decode('12', 'hex'), 23, 2026);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 021 Cup', '2026', DATE '2026-01-01',
    'draft', '{{}}'::jsonb
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
) VALUES ('{STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Group', 'round_robin', 1);

INSERT INTO public.teams (id, organization_id, name, short_code)
VALUES ('{TEAM}', '{ORG}', 'Migration 021 Team', 'M21');

INSERT INTO public.tournament_teams (
    id, organization_id, tournament_id, team_id, status
) VALUES ('{TOURNAMENT_TEAM}', '{ORG}', '{TOURNAMENT}', '{TEAM}', 'registered');

INSERT INTO public.stage_teams (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, team_id
) VALUES ('{STAGE_TEAM}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL, '{TEAM}');

INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, status, match_date, created_at
) VALUES (
    '{MATCH}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL, '{TEAM}',
    NULL, 'scheduled', '2026-01-05 12:00:00+00', '2026-01-05 00:00:00+00'
);

INSERT INTO public.match_segments (
    id, organization_id, match_id, segment_number, minute_start, minute_end,
    status, created_at
) VALUES (
    '{SEGMENT}', '{ORG}', '{MATCH}', 1, 0, 90, 'active',
    '2026-01-05 00:00:00+00'
);

INSERT INTO public.match_segment_team_state (
    id, organization_id, match_id, segment_id, team_id,
    substitutions_remaining, substitution_windows_remaining
) VALUES ('{SEGMENT_STATE}', '{ORG}', '{MATCH}', '{SEGMENT}', '{TEAM}', 5, 3);

INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    is_active, photo_consent, registered_at, valid_from, valid_to, eligible_from
) VALUES
    ('{ROSTER_OUT}', '{ORG}', '{TOURNAMENT}', '{TEAM}', '{PLAYER_OUT}', 9,
     TRUE, FALSE, '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
     '2026-01-01 00:00:00+00'),
    ('{ROSTER_IN}', '{ORG}', '{TOURNAMENT}', '{TEAM}', '{PLAYER_IN}', 10,
     TRUE, FALSE, '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
     '2026-01-01 00:00:00+00');

INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES
    ('{MATCH_ROSTER_OUT}', '{ORG}', '{MATCH}', '{ROSTER_OUT}', '{PLAYER_OUT}',
     '{TEAM}', '{TOURNAMENT}', NULL, 'starter', TRUE),
    ('{MATCH_ROSTER_IN}', '{ORG}', '{MATCH}', '{ROSTER_IN}', '{PLAYER_IN}',
     '{TEAM}', '{TOURNAMENT}', NULL, 'substitute', TRUE);
"""


async def insert_legacy_event(
    connection: asyncpg.Connection,
    *,
    event_id: str,
    client_event_id: str,
    minute: int = 10,
) -> None:
    """Insert a ``substitution`` row before 021, when the pair columns do not exist."""

    await connection.execute(
        """
        INSERT INTO public.match_events (
            id, organization_id, match_id, segment_id, team_id, player_id,
            event_type, minute, added_minute, client_event_id
        ) VALUES ($1, $2, $3, $4, $5, $6, 'substitution', $7, 0, $8)
        """,
        event_id,
        ORG,
        MATCH,
        SEGMENT,
        TEAM,
        PLAYER_OUT,
        minute,
        client_event_id,
    )


async def insert_event(
    connection: asyncpg.Connection,
    *,
    event_id: str,
    client_event_id: str,
    event_type: str,
    player_id: str,
    minute: int = 10,
    player_out_id: str | None = None,
    player_in_id: str | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO public.match_events (
            id, organization_id, match_id, segment_id, team_id, player_id,
            event_type, minute, added_minute, client_event_id,
            player_out_id, player_in_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 0, $9, $10, $11)
        """,
        event_id,
        ORG,
        MATCH,
        SEGMENT,
        TEAM,
        player_id,
        event_type,
        minute,
        client_event_id,
        player_out_id,
        player_in_id,
    )


async def column_definitions(
    connection: asyncpg.Connection, table: str
) -> list[tuple[str, str, bool]]:
    rows = await connection.fetch(
        """
        SELECT a.attname,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull
        FROM pg_attribute a
        WHERE a.attrelid = $1::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attname
        """,
        f"public.{table}",
    )
    return [(row["attname"], row["data_type"], row["attnotnull"]) for row in rows]


async def constraint_definitions(
    connection: asyncpg.Connection, table: str
) -> list[tuple[str, str, bool, str]]:
    rows = await connection.fetch(
        """
        SELECT con.conname, con.contype, con.convalidated,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = $1::regclass
        ORDER BY con.conname
        """,
        f"public.{table}",
    )
    return [
        (row["conname"], row["contype"], row["convalidated"], row["definition"])
        for row in rows
    ]


async def table_snapshot(
    connection: asyncpg.Connection, table: str
) -> dict[str, object]:
    return {
        "columns": await column_definitions(connection, table),
        "constraints": await constraint_definitions(connection, table),
    }


# ---------------------------------------------------------------------------
# Formation catalog: the CHECK accepts exactly the documented formations
# ---------------------------------------------------------------------------

FORMATION_LINEUP = "21000000-0000-4000-8000-000000000070"


@pytest.mark.asyncio
async def test_formation_check_accepts_exactly_the_closed_catalog(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=21) as connection:
        await connection.execute(SEED_SQL)
        await connection.execute(
            """
            INSERT INTO public.match_team_lineups (
                id, organization_id, match_id, segment_id, team_id, formation_code
            ) VALUES ($1, $2, $3, $4, $5, $6)
            """,
            FORMATION_LINEUP,
            ORG,
            MATCH,
            SEGMENT,
            TEAM,
            FORMATION_CODES[0],
        )

        for code in FORMATION_CODES[1:]:
            await connection.execute(
                """
                UPDATE public.match_team_lineups
                SET formation_code = $1
                WHERE id = $2
                """,
                code,
                FORMATION_LINEUP,
            )

        stored = await connection.fetchval(
            "SELECT formation_code FROM public.match_team_lineups WHERE id = $1",
            FORMATION_LINEUP,
        )
        assert stored == FORMATION_CODES[-1]

        # A fifth formation is outside the closed catalog and the CHECK rejects
        # it even though the API maps that case to 422 before the handler.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await connection.execute(
                """
                UPDATE public.match_team_lineups
                SET formation_code = '4-1-4-1'
                WHERE id = $1
                """,
                FORMATION_LINEUP,
            )


async def foreign_key(
    connection: asyncpg.Connection, name: str
) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        SELECT con.conname,
               con.confrelid = 'public.players'::regclass AS references_players,
               con.confdeltype,
               con.convalidated,
               ARRAY(
                   SELECT a.attname
                   FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                   JOIN pg_attribute a
                     ON a.attrelid = con.conrelid
                    AND a.attnum = k.attnum
                   ORDER BY k.ord
               ) AS columns,
               ARRAY(
                   SELECT a.attname
                   FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                   JOIN pg_attribute a
                     ON a.attrelid = con.confrelid
                    AND a.attnum = k.attnum
                   ORDER BY k.ord
               ) AS referenced_columns
        FROM pg_constraint con
        WHERE con.conrelid = 'public.match_events'::regclass
          AND con.conname = $1
        """,
        name,
    )
    assert row is not None, f"falta la FK {name}"
    return row


async def check_constraint(connection: asyncpg.Connection) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        SELECT con.conname, con.convalidated,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = 'public.match_events'::regclass
          AND con.conname = $1
        """,
        CHECK_NAME,
    )
    assert row is not None, f"falta el CHECK {CHECK_NAME}"
    return row


# ---------------------------------------------------------------------------
# Shape: columns and composite tenant foreign keys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_021_adds_nullable_columns_and_composite_foreign_keys(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=20) as connection:
        before = {
            row["attname"]
            for row in await connection.fetch(
                """
                SELECT attname
                FROM pg_attribute
                WHERE attrelid = 'public.match_events'::regclass
                  AND attnum > 0
                  AND NOT attisdropped
                """
            )
        }
        assert "player_out_id" not in before
        assert "player_in_id" not in before

        await apply_migration(connection, 21)

        columns = {
            row["attname"]: row
            for row in await connection.fetch(
                """
                SELECT attname, format_type(atttypid, atttypmod) AS data_type,
                       attnotnull
                FROM pg_attribute
                WHERE attrelid = 'public.match_events'::regclass
                  AND attname IN ('player_out_id', 'player_in_id')
                """
            )
        }
        assert set(columns) == {"player_out_id", "player_in_id"}
        for column in columns.values():
            assert column["data_type"] == "uuid"
            assert column["attnotnull"] is False

        for name, local_column in ((FK_OUT, "player_out_id"), (FK_IN, "player_in_id")):
            fk = await foreign_key(connection, name)
            assert fk["references_players"] is True
            assert fk["columns"] == [local_column, "organization_id"]
            assert fk["referenced_columns"] == ["id", "organization_id"]
            # RESTRICT, not NO ACTION.
            assert fk["confdeltype"] == b"r"
            assert fk["convalidated"] is True

        # The pre-existing single-column tenant FK is untouched.
        legacy = await foreign_key(connection, "fk_match_events_player_organization")
        assert legacy["columns"] == ["player_id", "organization_id"]
        assert legacy["referenced_columns"] == ["id", "organization_id"]


# ---------------------------------------------------------------------------
# CHECK: NOT VALID but enforced on new and modified rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_021_check_is_not_valid_and_rejects_invalid_new_rows(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=20) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 21)

        check = await check_constraint(connection)
        assert check["convalidated"] is False
        definition = check["definition"]
        for token in (
            "substitution",
            "player_out_id",
            "player_in_id",
            "player_id",
            "<>",
        ):
            assert token in definition

        # A substitution needs both players; the trigger 009 is satisfied.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                connection,
                event_id="21000000-0000-4000-8000-000000000051",
                client_event_id="invalid-missing-in",
                event_type="substitution",
                player_id=PLAYER_OUT,
                player_out_id=PLAYER_OUT,
            )

        # player_id must be the player who leaves.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                connection,
                event_id="21000000-0000-4000-8000-000000000052",
                client_event_id="invalid-player-id",
                event_type="substitution",
                player_id=PLAYER_IN,
                player_out_id=PLAYER_OUT,
                player_in_id=PLAYER_IN,
            )

        # The same player cannot leave and enter.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                connection,
                event_id="21000000-0000-4000-8000-000000000053",
                client_event_id="invalid-same-player",
                event_type="substitution",
                player_id=PLAYER_OUT,
                player_out_id=PLAYER_OUT,
                player_in_id=PLAYER_OUT,
            )

        # Non-substitution events carry no substitution pair.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                connection,
                event_id="21000000-0000-4000-8000-000000000054",
                client_event_id="invalid-goal-pair",
                event_type="goal",
                player_id=PLAYER_OUT,
                player_out_id=PLAYER_OUT,
                player_in_id=PLAYER_IN,
            )

        # Valid rows are accepted: a coherent substitution and a plain event.
        await insert_event(
            connection,
            event_id="21000000-0000-4000-8000-000000000055",
            client_event_id="valid-substitution",
            event_type="substitution",
            player_id=PLAYER_OUT,
            minute=30,
            player_out_id=PLAYER_OUT,
            player_in_id=PLAYER_IN,
        )
        await insert_event(
            connection,
            event_id="21000000-0000-4000-8000-000000000056",
            client_event_id="valid-goal",
            event_type="goal",
            player_id=PLAYER_IN,
            minute=40,
        )

        stored = await connection.fetchval(
            """
            SELECT count(*)
            FROM public.match_events
            WHERE client_event_id IN ('valid-substitution', 'valid-goal')
            """
        )
        assert stored == 2


# ---------------------------------------------------------------------------
# Legacy events and the 009 trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_021_preserves_legacy_substitution_and_rejects_its_update(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=20) as connection:
        await connection.execute(SEED_SQL)
        await insert_legacy_event(
            connection,
            event_id=LEGACY_EVENT,
            client_event_id="legacy-substitution",
        )

        await apply_migration(connection, 21)

        legacy = await connection.fetchrow(
            """
            SELECT event_type, player_out_id, player_in_id
            FROM public.match_events
            WHERE id = $1
            """,
            LEGACY_EVENT,
        )
        assert legacy["event_type"] == "substitution"
        assert legacy["player_out_id"] is None
        assert legacy["player_in_id"] is None
        assert (await check_constraint(connection))["convalidated"] is False

        # On an open match the deferred CHECK is evaluated on UPDATE: no
        # write-time tolerance for legacy rows.
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await connection.execute(
                "UPDATE public.match_events SET minute = 11 WHERE id = $1",
                LEGACY_EVENT,
            )
        assert await connection.fetchval(
            "SELECT minute FROM public.match_events WHERE id = $1", LEGACY_EVENT
        ) == 10

        # Once the match is finished, trigger 009 rejects any event write.
        await connection.execute(
            """
            UPDATE public.matches
            SET status = 'finished',
                result_confirmed = TRUE,
                resolution_type = 'regular',
                home_score_regular = 0,
                away_score_regular = 0,
                home_score = 0,
                away_score = 0
            WHERE id = $1
            """,
            MATCH,
        )

        with pytest.raises(asyncpg.exceptions.PostgresError) as error:
            await connection.execute(
                "UPDATE public.match_events SET minute = 12 WHERE id = $1",
                LEGACY_EVENT,
            )
        assert error.value.sqlstate == "P0001"
        assert "El partido no admite nuevos eventos" in str(error.value)

        assert await connection.fetchval(
            "SELECT minute FROM public.match_events WHERE id = $1", LEGACY_EVENT
        ) == 10


# ---------------------------------------------------------------------------
# Composite foreign key isolation across organizations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_021_composite_foreign_key_rejects_cross_organization_player(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=20) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 21)

        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await insert_event(
                connection,
                event_id="21000000-0000-4000-8000-000000000057",
                client_event_id="cross-org-substitution",
                event_type="substitution",
                player_id=PLAYER_OUT,
                player_out_id=PLAYER_OUT,
                player_in_id=FOREIGN_PLAYER,
            )


# ---------------------------------------------------------------------------
# Informative pre-checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_021_prechecks_report_counts_without_blocking(database_admin_url):
    async with throwaway_database(database_admin_url, last=20) as connection:
        await connection.execute(SEED_SQL)
        for index, minute in enumerate((10, 20), start=1):
            await insert_legacy_event(
                connection,
                event_id=f"21000000-0000-4000-8000-00000000006{index}",
                client_event_id=f"legacy-{index}",
                minute=minute,
            )

        notices: list[str] = []
        connection.add_log_listener(
            lambda _connection, message: notices.append(message.message)
        )

        await apply_migration(connection, 21)

        combined = "\n".join(notices)
        assert "MIGRACION 021" in combined
        assert "eventos substitution=2" in combined
        assert "match_segment_team_state=1" in combined

        # Informative only: the additive migration ran to completion.
        assert await connection.fetchval(
            """
            SELECT count(*)
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'match_events'
              AND column_name IN ('player_out_id', 'player_in_id')
            """
        ) == 2


# ---------------------------------------------------------------------------
# Clean chain versus migrated chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_021_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=20) as connection:
        state_before = await table_snapshot(connection, "match_segment_team_state")
        await apply_migration(connection, 21)
        state_after = await table_snapshot(connection, "match_segment_team_state")
        assert state_after == state_before

        migrated_events = await table_snapshot(connection, "match_events")
        migrated_state = await table_snapshot(connection, "match_segment_team_state")

        async with throwaway_database(database_admin_url, last=21) as clean:
            clean_events = await table_snapshot(clean, "match_events")
            clean_state = await table_snapshot(clean, "match_segment_team_state")

            assert clean_events == migrated_events
            assert clean_state == migrated_state

            column_names = {column[0] for column in clean_events["columns"]}
            assert {"player_out_id", "player_in_id"} <= column_names
            check = await check_constraint(clean)
            assert check["convalidated"] is False
            await foreign_key(clean, FK_OUT)
            await foreign_key(clean, FK_IN)
