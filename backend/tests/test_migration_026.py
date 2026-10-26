"""Migration 026: goal assists column, composite FK and validated CHECK (RF-007/RF-013).

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so the additive change is validated both on an
already migrated volume (025 -> 026) and on the clean-volume chain
(init + 001..026). The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and
``DATABASE_ADMIN_URL`` because creating databases and applying DDL require a
role the application role does not have.

Assertions cover the shape of ``match_events.assist_player_id`` (nullable
``UUID`` with no default), the composite tenant foreign key to
``players (id, organization_id)`` with ``ON DELETE RESTRICT``, the ``CHECK``
``chk_match_event_assist`` **validated** (D-2: no historical row justifies
``NOT VALID``), the absence of any index over the new column (D-3), the
inheritance of the table grants (no column-level grant is added), the
preservation of rows written before 026 (they keep a NULL assist, stay
readable and stay valid), the rejection of an assist on a type that does not
admit it or on the scorer himself, the isolation of the composite key (another
organization's player is a foreign key violation, not a silent success) and the
equality between the clean and the migrated chains.

The ``CHECK`` covers only the structure the storage can prove: the assist exists
on ``goal`` alone and never repeats the scorer. Team membership and presence on
the pitch at that minute are API authority (RF-008) and are not asserted here.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG = "26000000-0000-4000-8000-000000000001"
OTHER_ORG = "26000000-0000-4000-8000-000000000002"
USER = "26000000-0000-4000-8000-000000000003"
MEMBER = "26000000-0000-4000-8000-000000000004"

TOURNAMENT = "26000000-0000-4000-8000-000000000010"
VERSION = "26000000-0000-4000-8000-000000000011"
STAGE = "26000000-0000-4000-8000-000000000012"
TEAM_HOME = "26000000-0000-4000-8000-000000000013"
TEAM_AWAY = "26000000-0000-4000-8000-000000000014"
TOURNAMENT_TEAM_HOME = "26000000-0000-4000-8000-000000000015"
TOURNAMENT_TEAM_AWAY = "26000000-0000-4000-8000-000000000016"
STAGE_TEAM_HOME = "26000000-0000-4000-8000-000000000017"
STAGE_TEAM_AWAY = "26000000-0000-4000-8000-000000000018"

PLAYER_SCORER = "26000000-0000-4000-8000-000000000020"
PLAYER_ASSIST = "26000000-0000-4000-8000-000000000021"
PLAYER_IN = "26000000-0000-4000-8000-000000000022"
PLAYER_AWAY = "26000000-0000-4000-8000-000000000023"
FOREIGN_PLAYER = "26000000-0000-4000-8000-000000000024"

ROSTER_SCORER = "26000000-0000-4000-8000-000000000030"
ROSTER_ASSIST = "26000000-0000-4000-8000-000000000031"
ROSTER_IN = "26000000-0000-4000-8000-000000000032"
ROSTER_AWAY = "26000000-0000-4000-8000-000000000033"

MATCH_ROSTER_SCORER = "26000000-0000-4000-8000-000000000040"
MATCH_ROSTER_ASSIST = "26000000-0000-4000-8000-000000000041"
MATCH_ROSTER_IN = "26000000-0000-4000-8000-000000000042"
MATCH_ROSTER_AWAY = "26000000-0000-4000-8000-000000000043"

MATCH = "26000000-0000-4000-8000-000000000050"
SEGMENT = "26000000-0000-4000-8000-000000000051"

LEGACY_GOAL = "26000000-0000-4000-8000-000000000060"

COLUMN = "assist_player_id"
FK_NAME = "fk_match_events_assist_player_organization"
CHECK_NAME = "chk_match_event_assist"
LEGACY_PLAYER_FK = "fk_match_events_player_organization"

# The six types that do not admit an assist (RF-009); ``goal`` is the only one.
NON_GOAL_TYPES = (
    "penalty_goal",
    "own_goal",
    "yellow_card",
    "red_card",
    "substitution",
    "foul",
)

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG}', 'Migration 026 Org', 'migration-026-org'),
    ('{OTHER_ORG}', 'Migration 026 Other', 'migration-026-other');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER}', 'migration-026@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.players (
    id, organization_id, first_name, last_name, document_type,
    national_id_encrypted, national_id_hmac, issuing_country,
    birth_date_encrypted, age_at_reference, age_reference_year
) VALUES
    ('{PLAYER_SCORER}', '{ORG}', 'Scorer', 'Player', 'DNI',
     decode('01', 'hex'), repeat('a', 64), 'ARG', decode('10', 'hex'), 25, 2026),
    ('{PLAYER_ASSIST}', '{ORG}', 'Assist', 'Player', 'DNI',
     decode('02', 'hex'), repeat('b', 64), 'ARG', decode('11', 'hex'), 24, 2026),
    ('{PLAYER_IN}', '{ORG}', 'Entering', 'Player', 'DNI',
     decode('03', 'hex'), repeat('c', 64), 'ARG', decode('12', 'hex'), 23, 2026),
    ('{PLAYER_AWAY}', '{ORG}', 'Away', 'Player', 'DNI',
     decode('04', 'hex'), repeat('d', 64), 'ARG', decode('13', 'hex'), 22, 2026),
    ('{FOREIGN_PLAYER}', '{OTHER_ORG}', 'Foreign', 'Player', 'DNI',
     decode('05', 'hex'), repeat('e', 64), 'ARG', decode('14', 'hex'), 21, 2026);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 026 Cup', '2026', DATE '2026-01-01',
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

INSERT INTO public.teams (id, organization_id, name, short_code) VALUES
    ('{TEAM_HOME}', '{ORG}', 'Migration 026 Home', 'H26'),
    ('{TEAM_AWAY}', '{ORG}', 'Migration 026 Away', 'A26');

INSERT INTO public.tournament_teams (
    id, organization_id, tournament_id, team_id, status
) VALUES
    ('{TOURNAMENT_TEAM_HOME}', '{ORG}', '{TOURNAMENT}', '{TEAM_HOME}', 'registered'),
    ('{TOURNAMENT_TEAM_AWAY}', '{ORG}', '{TOURNAMENT}', '{TEAM_AWAY}', 'registered');

INSERT INTO public.stage_teams (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, team_id
) VALUES
    ('{STAGE_TEAM_HOME}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL,
     '{TEAM_HOME}'),
    ('{STAGE_TEAM_AWAY}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL,
     '{TEAM_AWAY}');

INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, status, match_date, created_at
) VALUES (
    '{MATCH}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL,
    '{TEAM_HOME}', '{TEAM_AWAY}', 'scheduled', '2026-01-05 12:00:00+00',
    '2026-01-05 00:00:00+00'
);

INSERT INTO public.match_segments (
    id, organization_id, match_id, segment_number, minute_start, minute_end,
    status, created_at
) VALUES (
    '{SEGMENT}', '{ORG}', '{MATCH}', 1, 0, 90, 'active',
    '2026-01-05 00:00:00+00'
);

INSERT INTO public.rosters (
    id, organization_id, tournament_id, team_id, player_id, dorsal_number,
    is_active, photo_consent, registered_at, valid_from, valid_to, eligible_from
) VALUES
    ('{ROSTER_SCORER}', '{ORG}', '{TOURNAMENT}', '{TEAM_HOME}', '{PLAYER_SCORER}',
     9, TRUE, FALSE, '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
     '2026-01-01 00:00:00+00'),
    ('{ROSTER_ASSIST}', '{ORG}', '{TOURNAMENT}', '{TEAM_HOME}', '{PLAYER_ASSIST}',
     10, TRUE, FALSE, '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
     '2026-01-01 00:00:00+00'),
    ('{ROSTER_IN}', '{ORG}', '{TOURNAMENT}', '{TEAM_HOME}', '{PLAYER_IN}',
     11, TRUE, FALSE, '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
     '2026-01-01 00:00:00+00'),
    ('{ROSTER_AWAY}', '{ORG}', '{TOURNAMENT}', '{TEAM_AWAY}', '{PLAYER_AWAY}',
     1, TRUE, FALSE, '2026-01-01 00:00:00+00', '2026-01-01 00:00:00+00', NULL,
     '2026-01-01 00:00:00+00');

INSERT INTO public.match_rosters (
    id, organization_id, match_id, roster_id, player_id, team_id,
    tournament_id, matchday, role, is_valid
) VALUES
    ('{MATCH_ROSTER_SCORER}', '{ORG}', '{MATCH}', '{ROSTER_SCORER}',
     '{PLAYER_SCORER}', '{TEAM_HOME}', '{TOURNAMENT}', NULL, 'starter', TRUE),
    ('{MATCH_ROSTER_ASSIST}', '{ORG}', '{MATCH}', '{ROSTER_ASSIST}',
     '{PLAYER_ASSIST}', '{TEAM_HOME}', '{TOURNAMENT}', NULL, 'starter', TRUE),
    ('{MATCH_ROSTER_IN}', '{ORG}', '{MATCH}', '{ROSTER_IN}',
     '{PLAYER_IN}', '{TEAM_HOME}', '{TOURNAMENT}', NULL, 'substitute', TRUE),
    ('{MATCH_ROSTER_AWAY}', '{ORG}', '{MATCH}', '{ROSTER_AWAY}',
     '{PLAYER_AWAY}', '{TEAM_AWAY}', '{TOURNAMENT}', NULL, 'starter', TRUE);
"""


async def insert_event(
    connection: asyncpg.Connection,
    *,
    event_id: str,
    client_event_id: str,
    event_type: str,
    player_id: str,
    minute: int = 10,
    team_id: str = TEAM_HOME,
    beneficiary_team_id: str | None = None,
    player_out_id: str | None = None,
    player_in_id: str | None = None,
    assist_player_id: str | None = None,
    metadata: str = "{}",
) -> None:
    """Insert one event; ``assist_player_id`` only exists after 026."""

    await connection.execute(
        """
        INSERT INTO public.match_events (
            id, organization_id, match_id, segment_id, team_id, player_id,
            event_type, minute, added_minute, client_event_id,
            player_out_id, player_in_id, assist_player_id, metadata,
            beneficiary_team_id
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, 0, $9, $10, $11, $12, $13::jsonb, $14
        )
        """,
        event_id,
        ORG,
        MATCH,
        SEGMENT,
        team_id,
        player_id,
        event_type,
        minute,
        client_event_id,
        player_out_id,
        player_in_id,
        assist_player_id,
        metadata,
        beneficiary_team_id,
    )


async def insert_event_before_026(
    connection: asyncpg.Connection,
    *,
    event_id: str,
    client_event_id: str,
    event_type: str = "goal",
    player_id: str = PLAYER_SCORER,
    minute: int = 10,
    metadata: str = "{}",
) -> None:
    """Insert a row before 026, when the assist column does not exist yet."""

    await connection.execute(
        """
        INSERT INTO public.match_events (
            id, organization_id, match_id, segment_id, team_id, player_id,
            event_type, minute, added_minute, client_event_id, metadata
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 0, $9, $10::jsonb)
        """,
        event_id,
        ORG,
        MATCH,
        SEGMENT,
        TEAM_HOME,
        player_id,
        event_type,
        minute,
        client_event_id,
        metadata,
    )


async def column_shape(connection: asyncpg.Connection) -> dict[str, object] | None:
    return await connection.fetchrow(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS data_type,
               a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid) AS default_expr
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d
          ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = 'public.match_events'::regclass
          AND a.attname = $1
          AND a.attnum > 0
          AND NOT a.attisdropped
        """,
        COLUMN,
    )


async def foreign_key(connection: asyncpg.Connection, name: str) -> asyncpg.Record:
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


async def index_definitions(connection: asyncpg.Connection) -> list[str]:
    rows = await connection.fetch(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = 'match_events'
        ORDER BY indexname
        """
    )
    return [row["indexdef"] for row in rows]


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


async def table_security(connection: asyncpg.Connection, table: str) -> dict[str, object]:
    """Return RLS, table ACL, policies and column ACLs of one table."""

    row = await connection.fetchrow(
        """
        SELECT c.relrowsecurity,
               c.relforcerowsecurity,
               COALESCE(c.relacl::text, '') AS table_acl,
               (
                   SELECT count(*)
                   FROM pg_policy p
                   WHERE p.polrelid = c.oid
               ) AS policies,
               (
                   SELECT array_to_string(array_agg(p.polname ORDER BY p.polname), ',')
                   FROM pg_policy p
                   WHERE p.polrelid = c.oid
               ) AS policy_names,
               has_table_privilege('bracket_app', c.oid, 'SELECT') AS app_select,
               has_table_privilege('bracket_app', c.oid, 'INSERT') AS app_insert,
               has_table_privilege('bracket_app', c.oid, 'UPDATE') AS app_update,
               has_table_privilege('bracket_app', c.oid, 'DELETE') AS app_delete
        FROM pg_class c
        WHERE c.oid = $1::regclass
        """,
        f"public.{table}",
    )
    assert row is not None, f"falta la tabla public.{table}"
    column_acls = await connection.fetch(
        """
        SELECT a.attname, a.attacl::text AS column_acl
        FROM pg_attribute a
        WHERE a.attrelid = $1::regclass
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND a.attacl IS NOT NULL
        ORDER BY a.attname
        """,
        f"public.{table}",
    )
    return {
        "rls": row["relrowsecurity"],
        "force_rls": row["relforcerowsecurity"],
        "table_acl": row["table_acl"],
        "policies": row["policies"],
        "policy_names": row["policy_names"],
        "app_privileges": {
            "select": row["app_select"],
            "insert": row["app_insert"],
            "update": row["app_update"],
            "delete": row["app_delete"],
        },
        "column_acls": [
            (acl["attname"], acl["column_acl"]) for acl in column_acls
        ],
    }


async def table_snapshot(
    connection: asyncpg.Connection, table: str
) -> dict[str, object]:
    return {
        "columns": await column_definitions(connection, table),
        "constraints": await constraint_definitions(connection, table),
        "indexes": await index_definitions(connection),
        "security": await table_security(connection, table),
    }


# ---------------------------------------------------------------------------
# Shape: nullable UUID column, composite tenant FK, validated CHECK, no index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_026_adds_nullable_column_composite_fk_and_validated_check(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=25) as connection:
        assert await column_shape(connection) is None, (
            "match_events.assist_player_id no debe existir antes de la 026"
        )

        await apply_migration(connection, 26)

        shape = await column_shape(connection)
        assert shape is not None, f"falta la columna match_events.{COLUMN}"
        assert shape["data_type"] == "uuid"
        assert shape["attnotnull"] is False, "la asistencia es opcional siempre"
        assert shape["default_expr"] is None

        fk = await foreign_key(connection, FK_NAME)
        assert fk["references_players"] is True
        assert fk["columns"] == [COLUMN, "organization_id"]
        assert fk["referenced_columns"] == ["id", "organization_id"]
        # RESTRICT, not NO ACTION: the isolation fence is the same as 021.
        assert fk["confdeltype"] == b"r"
        assert fk["convalidated"] is True

        # The pre-existing single-column tenant FK of the scorer is untouched.
        legacy = await foreign_key(connection, LEGACY_PLAYER_FK)
        assert legacy["columns"] == ["player_id", "organization_id"]
        assert legacy["referenced_columns"] == ["id", "organization_id"]

        check = await check_constraint(connection)
        assert check["convalidated"] is True, (
            "D-2: el CHECK se añade validado, no con NOT VALID"
        )
        definition = check["definition"]
        for token in ("goal", COLUMN, "player_id", "<>"):
            assert token in definition, f"el CHECK debe declarar {token}"

        # D-3: no index over the new column, in any form (plain or partial).
        assert all(
            COLUMN not in definition for definition in await index_definitions(connection)
        ), "la 026 no debe añadir ningún índice sobre assist_player_id"

        # Privileges: the table GRANT of ``match_events`` covers the new column,
        # so the migration adds no column-level grant (unlike the 020 case).
        column_privileges = await connection.fetch(
            """
            SELECT a.attname, a.attacl::text AS column_acl
            FROM pg_attribute a
            WHERE a.attrelid = 'public.match_events'::regclass
              AND a.attnum > 0
              AND NOT a.attisdropped
              AND a.attacl IS NOT NULL
            """
        )
        assert column_privileges == [], "la 026 no debe añadir privilegios por columna"
        assert await connection.fetchval(
            "SELECT has_column_privilege('bracket_app', 'public.match_events', $1, 'INSERT')",
            COLUMN,
        ) is True
        assert await connection.fetchval(
            "SELECT has_column_privilege('bracket_app', 'public.match_events', $1, 'SELECT')",
            COLUMN,
        ) is True


# ---------------------------------------------------------------------------
# CHECK: the assist exists on ``goal`` alone and never repeats the scorer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_026_check_rejects_assist_on_other_types_and_same_as_scorer(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=25) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 26)

        # A goal with an assist of the same team is accepted.
        await insert_event(
            connection,
            event_id="26000000-0000-4000-8000-000000000070",
            client_event_id="goal-with-assist",
            event_type="goal",
            player_id=PLAYER_SCORER,
            assist_player_id=PLAYER_ASSIST,
        )

        # The same player may assist two different goals of the match: the
        # structural limit is one assist per goal, not per player.
        await insert_event(
            connection,
            event_id="26000000-0000-4000-8000-000000000071",
            client_event_id="second-goal-same-assist",
            event_type="goal",
            player_id=PLAYER_SCORER,
            minute=20,
            assist_player_id=PLAYER_ASSIST,
        )

        # A goal without an assist stays valid (RF-013: it is never required).
        await insert_event(
            connection,
            event_id="26000000-0000-4000-8000-000000000072",
            client_event_id="goal-without-assist",
            event_type="goal",
            player_id=PLAYER_ASSIST,
            minute=30,
        )

        assert await connection.fetchval(
            "SELECT count(*) FROM public.match_events WHERE assist_player_id IS NOT NULL"
        ) == 2

        # An assist on any other type is a structural violation (RF-009).
        for index, event_type in enumerate(NON_GOAL_TYPES, start=1):
            payload: dict[str, object] = {}
            if event_type == "own_goal":
                payload["beneficiary_team_id"] = TEAM_AWAY
            if event_type == "substitution":
                payload["player_out_id"] = PLAYER_SCORER
                payload["player_in_id"] = PLAYER_IN
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await insert_event(
                    connection,
                    event_id=f"26000000-0000-4000-8000-00000000008{index}",
                    client_event_id=f"assist-on-{event_type}",
                    event_type=event_type,
                    player_id=PLAYER_SCORER,
                    assist_player_id=PLAYER_ASSIST,
                    **payload,
                )

        # The assist must differ from the scorer (RF-008 asks 422 in the API;
        # the structure forbids storing it at all).
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await insert_event(
                connection,
                event_id="26000000-0000-4000-8000-000000000090",
                client_event_id="assist-equals-scorer",
                event_type="goal",
                player_id=PLAYER_SCORER,
                assist_player_id=PLAYER_SCORER,
            )

        assert await connection.fetchval(
            "SELECT count(*) FROM public.match_events WHERE assist_player_id IS NOT NULL"
        ) == 2


# ---------------------------------------------------------------------------
# RF-013: rows written before 026 keep a NULL assist and stay valid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_026_keeps_legacy_goals_without_assist_and_accepts_new_ones(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=25) as connection:
        await connection.execute(SEED_SQL)
        await insert_event_before_026(
            connection,
            event_id=LEGACY_GOAL,
            client_event_id="legacy-goal-without-assist",
            metadata='{"legacy_free_text": "kept"}',
        )

        await apply_migration(connection, 26)

        legacy = await connection.fetchrow(
            """
            SELECT event_type, assist_player_id,
                   metadata ->> 'legacy_free_text' AS legacy_free_text
            FROM public.match_events
            WHERE id = $1
            """,
            LEGACY_GOAL,
        )
        assert legacy["event_type"] == "goal"
        assert legacy["assist_player_id"] is None, "la 026 no hace backfill"
        assert legacy["legacy_free_text"] == "kept"

        # No backfill and no rewrite: the historical row keeps its free-form
        # metadata and remains writable on an open match, so the validated
        # CHECK does not invalidate it.
        await connection.execute(
            "UPDATE public.match_events SET minute = 11 WHERE id = $1", LEGACY_GOAL
        )
        assert await connection.fetchval(
            "SELECT minute FROM public.match_events WHERE id = $1", LEGACY_GOAL
        ) == 11

        # A new goal arrives with its assist and coexists with the legacy row.
        await insert_event(
            connection,
            event_id="26000000-0000-4000-8000-000000000061",
            client_event_id="new-goal-with-assist",
            event_type="goal",
            player_id=PLAYER_SCORER,
            minute=40,
            assist_player_id=PLAYER_ASSIST,
        )

        rows = await connection.fetch(
            """
            SELECT client_event_id, assist_player_id
            FROM public.match_events
            ORDER BY client_event_id
            """
        )
        assert [
            (
                row["client_event_id"],
                str(row["assist_player_id"]) if row["assist_player_id"] else None,
            )
            for row in rows
        ] == [
            ("legacy-goal-without-assist", None),
            ("new-goal-with-assist", PLAYER_ASSIST),
        ]


# ---------------------------------------------------------------------------
# Composite foreign key isolation across organizations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_026_composite_fk_rejects_cross_organization_and_missing_player(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=25) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 26)

        # A player of another organization is not reachable: the isolation does
        # not rely on RLS alone.
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await insert_event(
                connection,
                event_id="26000000-0000-4000-8000-0000000000a1",
                client_event_id="cross-org-assist",
                event_type="goal",
                player_id=PLAYER_SCORER,
                assist_player_id=FOREIGN_PLAYER,
            )

        # A player that does not exist is a foreign key violation, never a 500.
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await insert_event(
                connection,
                event_id="26000000-0000-4000-8000-0000000000a2",
                client_event_id="unknown-assist",
                event_type="goal",
                player_id=PLAYER_SCORER,
                assist_player_id="26000000-0000-4000-8000-0000000000ff",
            )

        assert await connection.fetchval(
            "SELECT count(*) FROM public.match_events"
        ) == 0

        # ON DELETE RESTRICT: a player who assisted a stored goal cannot be
        # removed from the catalog.
        await insert_event(
            connection,
            event_id="26000000-0000-4000-8000-0000000000a3",
            client_event_id="stored-assist",
            event_type="goal",
            player_id=PLAYER_SCORER,
            assist_player_id=PLAYER_ASSIST,
        )
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await connection.execute(
                "DELETE FROM public.players WHERE id = $1", PLAYER_ASSIST
            )


# ---------------------------------------------------------------------------
# Informative pre-checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_026_prechecks_report_counts_without_blocking(database_admin_url):
    async with throwaway_database(database_admin_url, last=25) as connection:
        await connection.execute(SEED_SQL)
        await insert_event_before_026(
            connection,
            event_id=LEGACY_GOAL,
            client_event_id="legacy-goal-without-assist",
        )
        await insert_event_before_026(
            connection,
            event_id="26000000-0000-4000-8000-0000000000b1",
            client_event_id="legacy-card",
            event_type="yellow_card",
            player_id=PLAYER_ASSIST,
            minute=15,
        )

        notices: list[str] = []
        connection.add_log_listener(
            lambda _connection, message: notices.append(message.message)
        )

        await apply_migration(connection, 26)

        combined = "\n".join(notices)
        assert "MIGRACION 026" in combined
        assert "eventos goal=1" in combined
        # The context key the composite FK needs is reported as present.
        assert "indice unico players(id, organization_id) presente=true" in combined

        # Informative only: the additive migration ran to completion.
        assert await column_shape(connection) is not None


# ---------------------------------------------------------------------------
# Clean chain versus migrated chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_026_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=25) as connection:
        columns_before = await column_definitions(connection, "match_events")
        assert COLUMN not in {column[0] for column in columns_before}

        await apply_migration(connection, 26)
        migrated = await table_snapshot(connection, "match_events")

        # The migrated chain really applied 026.
        shape = await column_shape(connection)
        assert shape is not None
        assert shape["data_type"] == "uuid"

    async with throwaway_database(database_admin_url, last=26) as clean:
        assert await table_snapshot(clean, "match_events") == migrated

        # Both chains end with the same validated CHECK and the same FK.
        assert (await check_constraint(clean))["convalidated"] is True
        fk = await foreign_key(clean, FK_NAME)
        assert fk["columns"] == [COLUMN, "organization_id"]
        assert fk["referenced_columns"] == ["id", "organization_id"]
        assert fk["confdeltype"] == b"r"
        assert all(
            COLUMN not in definition for definition in await index_definitions(clean)
        )

        # RLS, policy and grants are untouched by the migration.
        security = await table_security(clean, "match_events")
        assert security["rls"] is True
        assert security["force_rls"] is True
        assert security["policy_names"] == "tenant_isolation_policy"
        assert security["column_acls"] == []
        assert set(security["app_privileges"].values()) == {True}
