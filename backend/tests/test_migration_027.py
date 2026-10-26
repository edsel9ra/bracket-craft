"""Migration 027: the walkover reason is finally storable in ``resolution_reason``.

Every test builds a throwaway database from the real ``init`` scripts plus the
real numbered migrations, so the relaxation is validated both on an already
migrated volume (026 -> 027) and on the clean-volume chain (init + 001..027).
The suite is opt-in: it needs ``RUN_DATABASE_TESTS=1`` and ``DATABASE_ADMIN_URL``
because creating databases and applying DDL require a role the application role
does not have.

``chk_administrative_resolution_reason`` (``init/01_schema.sql`` and 009) only
admitted a reason for ``administrative`` and forced it to be NULL for every other
resolution, so the closed walkover code of RF-007 could not be stored. The 027
only **relaxes** the constraint:

* ``walkover`` admits ``NULL`` (historical rows and a deployment where the
  migration lands before the code) or one of the four catalogue codes —
  ``no_show``, ``withdrawal``, ``insufficient_players``, ``sanction``;
* ``administrative`` keeps requiring a reason with 1..1000 non-blank characters;
* ``regular``, ``extra_time`` and ``penalties`` keep forbidding it.

The obligation and the catalogue are API authority (RF-007, D-5): the database
never requires a reason on ``walkover`` and the empty or over-long values fall
out of the catalogue membership itself.

Assertions cover: the reason is rejected before 027 and accepted afterwards, the
four codes and ``NULL`` are accepted on ``walkover``, a code outside the
catalogue and an empty or over-long value are rejected, ``administrative`` keeps
its requirement and its length bounds, the other three resolutions keep
forbidding the field, historical rows (a confirmed administrative result with a
reason and a confirmed walkover with ``NULL``) survive untouched, the constraint
is added **validated**, no other column, constraint, index or row of ``matches``
changes, and the clean and the migrated chains end with the same
``pg_get_constraintdef``.

The ``CHECK`` covers only what storage can prove. ``winner > loser`` on the
configured walkover pair, the winner participation and the score coherence are
API and rules-engine authority (RF-008, RF-011) and are not asserted here.
"""

from __future__ import annotations

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

ORG = "27000000-0000-4000-8000-000000000001"
USER = "27000000-0000-4000-8000-000000000002"
MEMBER = "27000000-0000-4000-8000-000000000003"

TOURNAMENT = "27000000-0000-4000-8000-000000000010"
VERSION = "27000000-0000-4000-8000-000000000011"
STAGE = "27000000-0000-4000-8000-000000000012"
TEAM_HOME = "27000000-0000-4000-8000-000000000013"
TEAM_AWAY = "27000000-0000-4000-8000-000000000014"
TOURNAMENT_TEAM_HOME = "27000000-0000-4000-8000-000000000015"
TOURNAMENT_TEAM_AWAY = "27000000-0000-4000-8000-000000000016"
STAGE_TEAM_HOME = "27000000-0000-4000-8000-000000000017"
STAGE_TEAM_AWAY = "27000000-0000-4000-8000-000000000018"

MATCH = "27000000-0000-4000-8000-000000000050"
MATCH_LEGACY_WALKOVER = "27000000-0000-4000-8000-000000000051"
MATCH_LEGACY_ADMINISTRATIVE = "27000000-0000-4000-8000-000000000052"
MATCH_NEW_WALKOVER = "27000000-0000-4000-8000-000000000053"

CHECK_NAME = "chk_administrative_resolution_reason"
TABLE = "matches"

# The closed catalogue of RF-007: the only four reasons a walkover may carry.
WALKOVER_REASONS = ("no_show", "withdrawal", "insufficient_players", "sanction")

# The three resolutions that keep forbidding the field.
OTHER_RESOLUTIONS = ("regular", "extra_time", "penalties")

LEGACY_ADMINISTRATIVE_REASON = "Legacy administrative resolution; reason not recorded"

SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug) VALUES
    ('{ORG}', 'Migration 027 Org', 'migration-027-org');

INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER}', 'migration-027@example.test', 'hash', 'Migration Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Migration 027 Cup', '2026', DATE '2026-01-01',
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
    ('{TEAM_HOME}', '{ORG}', 'Migration 027 Home', 'H27'),
    ('{TEAM_AWAY}', '{ORG}', 'Migration 027 Away', 'A27');

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

-- Open match used to probe the constraint without pulling the terminal checks.
INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, status, match_date, created_at
) VALUES (
    '{MATCH}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}', NULL,
    '{TEAM_HOME}', '{TEAM_AWAY}', 'scheduled', '2026-01-05 12:00:00+00',
    '2026-01-05 00:00:00+00'
);

-- Historical walkover without a reason: the shape every stored row has today.
INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, home_score_regular, away_score_regular,
    home_score, away_score, winner_team_id, status, resolution_type,
    resolution_reason, result_confirmed, match_date, created_at
) VALUES (
    '{MATCH_LEGACY_WALKOVER}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}',
    NULL, '{TEAM_HOME}', '{TEAM_AWAY}', 3, 0, 3, 0, '{TEAM_HOME}', 'finished',
    'walkover', NULL, TRUE, '2026-01-06 12:00:00+00', '2026-01-06 00:00:00+00'
);

-- Historical administrative resolution with its reason already stored.
INSERT INTO public.matches (
    id, organization_id, tournament_id, tournament_version_id, stage_id,
    group_id, home_team_id, away_team_id, home_score_regular, away_score_regular,
    home_score, away_score, winner_team_id, status, resolution_type,
    resolution_reason, result_confirmed, match_date, created_at
) VALUES (
    '{MATCH_LEGACY_ADMINISTRATIVE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE}',
    NULL, '{TEAM_HOME}', '{TEAM_AWAY}', 1, 0, 1, 0, '{TEAM_HOME}',
    'administrative_resolution', 'administrative', '{LEGACY_ADMINISTRATIVE_REASON}',
    TRUE, '2026-01-07 12:00:00+00', '2026-01-07 00:00:00+00'
);
"""


async def constraint_row(connection: asyncpg.Connection) -> asyncpg.Record:
    """Return the walkover/administrative reason constraint of ``matches``."""

    row = await connection.fetchrow(
        """
        SELECT con.conname,
               con.contype,
               con.convalidated,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = $1::regclass
          AND con.conname = $2
        """,
        f"public.{TABLE}",
        CHECK_NAME,
    )
    assert row is not None, f"falta la restricción {CHECK_NAME} en public.{TABLE}"
    return row


async def constraint_definitions(
    connection: asyncpg.Connection,
) -> list[tuple[str, str, bool, str]]:
    rows = await connection.fetch(
        """
        SELECT con.conname, con.contype, con.convalidated,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        WHERE con.conrelid = $1::regclass
        ORDER BY con.conname
        """,
        f"public.{TABLE}",
    )
    return [
        (row["conname"], row["contype"], row["convalidated"], row["definition"])
        for row in rows
    ]


async def column_definitions(
    connection: asyncpg.Connection,
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
        f"public.{TABLE}",
    )
    return [(row["attname"], row["data_type"], row["attnotnull"]) for row in rows]


async def index_definitions(connection: asyncpg.Connection) -> list[str]:
    rows = await connection.fetch(
        """
        SELECT indexdef
        FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = $1
        ORDER BY indexname
        """,
        TABLE,
    )
    return [row["indexdef"] for row in rows]


async def update_match(
    connection: asyncpg.Connection, match_id: str, **fields: object
) -> None:
    """Update one match; the column names are literals chosen by the test."""

    assignments = ", ".join(
        f"{name} = ${index}" for index, name in enumerate(fields, start=2)
    )
    await connection.execute(
        f"UPDATE public.matches SET {assignments} WHERE id = $1",
        match_id,
        *fields.values(),
    )


async def reset_open_match(connection: asyncpg.Connection) -> None:
    """Return the probe match to a scheduled row without resolution."""

    await connection.execute(
        """
        UPDATE public.matches
        SET resolution_type = NULL,
            resolution_reason = NULL,
            home_score_regular = NULL,
            away_score_regular = NULL,
            home_score = NULL,
            away_score = NULL,
            home_penalties = NULL,
            away_penalties = NULL,
            winner_team_id = NULL,
            result_confirmed = FALSE,
            status = 'scheduled'
        WHERE id = $1
        """,
        MATCH,
    )


async def expect_reason_rejected(
    connection: asyncpg.Connection, match_id: str, **fields: object
) -> None:
    """Assert the database rejects the row through this very constraint."""

    with pytest.raises(asyncpg.exceptions.CheckViolationError) as info:
        await update_match(connection, match_id, **fields)
    assert info.value.constraint_name == CHECK_NAME, (
        "el rechazo debe venir de "
        f"{CHECK_NAME}, no de otra restricción ({info.value.constraint_name})"
    )


async def match_row(connection: asyncpg.Connection, match_id: str) -> asyncpg.Record:
    row = await connection.fetchrow(
        """
        SELECT id, status, resolution_type, resolution_reason, result_confirmed,
               home_score_regular, away_score_regular, home_score, away_score,
               home_penalties, away_penalties, winner_team_id
        FROM public.matches
        WHERE id = $1
        """,
        match_id,
    )
    assert row is not None, f"falta el partido {match_id}"
    return row


# ---------------------------------------------------------------------------
# The blocker: before 027 the walkover reason cannot be stored at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_027_walkover_reason_is_rejected_before_the_migration(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=26) as connection:
        await connection.execute(SEED_SQL)

        before = await constraint_row(connection)
        assert before["convalidated"] is True
        assert "walkover" not in before["definition"], (
            "la restricción de la 009 no debe mencionar walkover antes de la 027"
        )

        # The closed walkover code of RF-007 does not fit: this is the defect
        # the migration fixes (the API would surface it as a misleading 409).
        await expect_reason_rejected(
            connection,
            MATCH,
            resolution_type="walkover",
            resolution_reason="no_show",
        )

        # Without a reason the old constraint is satisfied, and the row stays.
        await update_match(
            connection, MATCH, resolution_type="walkover", resolution_reason=None
        )
        assert (await match_row(connection, MATCH))["resolution_type"] == "walkover"

        # Nothing was rewritten by the failed statement.
        assert (await match_row(connection, MATCH))["resolution_reason"] is None
        assert await connection.fetchval(
            "SELECT count(*) FROM public.matches WHERE resolution_reason IS NOT NULL"
        ) == 1  # only the seeded administrative row


# ---------------------------------------------------------------------------
# Walkover: NULL or one of the four catalogue codes, nothing else
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_027_accepts_catalogue_walkover_reason_and_null(database_admin_url):
    async with throwaway_database(database_admin_url, last=26) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 27)

        after = await constraint_row(connection)
        assert after["convalidated"] is True, (
            "la restricción se recrea validada, no con NOT VALID"
        )
        definition = after["definition"]
        for token in ("walkover", *WALKOVER_REASONS):
            assert token in definition, f"la restricción debe declarar {token}"

        for reason in WALKOVER_REASONS:
            await update_match(
                connection,
                MATCH,
                resolution_type="walkover",
                resolution_reason=reason,
            )
            stored = await match_row(connection, MATCH)
            assert stored["resolution_type"] == "walkover"
            assert stored["resolution_reason"] == reason

        # NULL stays valid: historical rows and a migration that lands before
        # the code (the obligation is API authority, RF-007 / D-5).
        await update_match(
            connection, MATCH, resolution_type="walkover", resolution_reason=None
        )
        assert (await match_row(connection, MATCH))["resolution_reason"] is None

        # A code outside the closed catalogue is a structural violation.
        for index, reason in enumerate(
            ("home_win", "no-show", "No_Show", "walkover", ""), start=1
        ):
            await expect_reason_rejected(
                connection,
                MATCH,
                resolution_type="walkover",
                resolution_reason=reason,
            )

        # Blank and over-long reasons never match the catalogue either: the
        # length language of the old constraint is covered by membership.
        await expect_reason_rejected(
            connection, MATCH, resolution_type="walkover", resolution_reason="   "
        )
        await expect_reason_rejected(
            connection, MATCH, resolution_type="walkover", resolution_reason="x" * 1001
        )

        # The rejected statements wrote nothing: NULL is still the stored value.
        assert (await match_row(connection, MATCH))["resolution_reason"] is None


# ---------------------------------------------------------------------------
# Administrative: the reason is still required, with its length bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_027_keeps_administrative_requirement_and_length_bounds(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=26) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 27)

        await update_match(
            connection,
            MATCH,
            resolution_type="administrative",
            resolution_reason="Árbitro no se presentó",
        )
        assert (await match_row(connection, MATCH))["resolution_reason"] == (
            "Árbitro no se presentó"
        )

        # Still forbidden to omit the reason on an administrative resolution.
        await expect_reason_rejected(
            connection, MATCH, resolution_type="administrative", resolution_reason=None
        )
        # Empty, blank, over-long: the 1..1000 BTRIM window is untouched.
        for reason in ("", "   ", "y" * 1001):
            await expect_reason_rejected(
                connection,
                MATCH,
                resolution_type="administrative",
                resolution_reason=reason,
            )

        # The boundaries still pass: one char and exactly 1000 non-blank chars.
        for reason in ("a", "  " + "z" * 1000 + "  "):
            await update_match(
                connection,
                MATCH,
                resolution_type="administrative",
                resolution_reason=reason,
            )
            assert (await match_row(connection, MATCH))["resolution_reason"] == reason


# ---------------------------------------------------------------------------
# regular / extra_time / penalties keep forbidding the field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_027_keeps_reason_forbidden_in_the_other_resolutions(
    database_admin_url,
):
    async with throwaway_database(database_admin_url, last=26) as connection:
        await connection.execute(SEED_SQL)
        await apply_migration(connection, 27)

        for resolution in OTHER_RESOLUTIONS:
            await reset_open_match(connection)

            # A valid shoot-out row when needed, so the only violation is the
            # reason and never the score shape.
            scores: dict[str, object] = {}
            if resolution == "penalties":
                scores = {
                    "home_score": 1,
                    "away_score": 1,
                    "home_penalties": 4,
                    "away_penalties": 2,
                }

            # A reason in a resolution that does not admit it is rejected.
            await expect_reason_rejected(
                connection,
                MATCH,
                resolution_type=resolution,
                resolution_reason="no_show",
                **scores,
            )

            # The same resolution without a reason is accepted.
            await update_match(
                connection,
                MATCH,
                resolution_type=resolution,
                resolution_reason=None,
                **scores,
            )
            assert (await match_row(connection, MATCH))["resolution_type"] == resolution
            assert (await match_row(connection, MATCH))["resolution_reason"] is None


# ---------------------------------------------------------------------------
# Historical rows are not rewritten and stay valid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_027_keeps_historical_rows_untouched_and_valid(database_admin_url):
    async with throwaway_database(database_admin_url, last=26) as connection:
        await connection.execute(SEED_SQL)

        walkover_before = await match_row(connection, MATCH_LEGACY_WALKOVER)
        administrative_before = await match_row(connection, MATCH_LEGACY_ADMINISTRATIVE)

        await apply_migration(connection, 27)

        # No backfill and no rewrite: the historical rows are byte-identical.
        assert await match_row(connection, MATCH_LEGACY_WALKOVER) == walkover_before
        assert (
            await match_row(connection, MATCH_LEGACY_ADMINISTRATIVE)
            == administrative_before
        )
        assert (await match_row(connection, MATCH_LEGACY_WALKOVER))[
            "resolution_reason"
        ] is None
        assert (await match_row(connection, MATCH_LEGACY_ADMINISTRATIVE))[
            "resolution_reason"
        ] == LEGACY_ADMINISTRATIVE_REASON
        assert await connection.fetchval(
            "SELECT count(*) FROM public.matches"
        ) == 3

        # The recreated CHECK accepts the new shape on the INSERT path too: a
        # walkover that stores the catalogue code coexists with the historical
        # rows that keep NULL and with the administrative reason.
        await connection.execute(
            """
            INSERT INTO public.matches (
                id, organization_id, tournament_id, tournament_version_id,
                stage_id, group_id, home_team_id, away_team_id, status,
                resolution_type, resolution_reason, match_date, created_at
            ) VALUES (
                $1, $2, $3, $4, $5, NULL, $6, $7, 'scheduled',
                'walkover', 'withdrawal', '2026-01-08 12:00:00+00',
                '2026-01-08 00:00:00+00'
            )
            """,
            MATCH_NEW_WALKOVER,
            ORG,
            TOURNAMENT,
            VERSION,
            STAGE,
            TEAM_HOME,
            TEAM_AWAY,
        )
        assert (await match_row(connection, MATCH_NEW_WALKOVER))[
            "resolution_reason"
        ] == "withdrawal"
        # Both historical rows are still exactly what they were.
        assert await match_row(connection, MATCH_LEGACY_WALKOVER) == walkover_before
        assert (
            await match_row(connection, MATCH_LEGACY_ADMINISTRATIVE)
            == administrative_before
        )


# ---------------------------------------------------------------------------
# Informative pre-checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_027_prechecks_report_counts_without_blocking(database_admin_url):
    async with throwaway_database(database_admin_url, last=26) as connection:
        await connection.execute(SEED_SQL)
        await update_match(
            connection, MATCH, resolution_type="walkover", resolution_reason=None
        )

        notices: list[str] = []
        connection.add_log_listener(
            lambda _connection, message: notices.append(message.message)
        )

        await apply_migration(connection, 27)

        combined = "\n".join(notices)
        assert "MIGRACION 027" in combined
        # Two walkovers (the seeded historical one and the probe row) and one
        # administrative reason already stored.
        assert "walkover=2" in combined
        assert "administrative con motivo=1" in combined

        # Informative only: the migration relaxed the constraint and ran on.
        assert "walkover" in (await constraint_row(connection))["definition"]


# ---------------------------------------------------------------------------
# Clean chain versus migrated chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_027_clean_chain_matches_migrated_chain(database_admin_url):
    async with throwaway_database(database_admin_url, last=26) as connection:
        before_constraints = await constraint_definitions(connection)
        before_columns = await column_definitions(connection)
        before_indexes = await index_definitions(connection)
        before_definition = (await constraint_row(connection))["definition"]

        await apply_migration(connection, 27)

        migrated = await constraint_row(connection)
        assert migrated["convalidated"] is True
        assert migrated["definition"] != before_definition

        # Only this constraint changed: every column, the rest of the
        # constraints and every index of `matches` stay identical.
        assert await column_definitions(connection) == before_columns
        assert await index_definitions(connection) == before_indexes
        after_constraints = await constraint_definitions(connection)
        assert [row[0] for row in after_constraints] == [
            row[0] for row in before_constraints
        ]
        for before, after in zip(before_constraints, after_constraints, strict=True):
            if before[0] == CHECK_NAME:
                assert after != before
            else:
                assert after == before, f"la 027 no debe tocar {before[0]}"

        # The reason column itself is untouched (no new column, no type change).
        assert ("resolution_reason", "text", False) in before_columns

    # The clean chain (init + 001..027) ends with the very same definition.
    async with throwaway_database(database_admin_url, last=27) as clean:
        clean_constraint = await constraint_row(clean)
        assert clean_constraint["definition"] == migrated["definition"]
        assert clean_constraint["convalidated"] is True
        assert await constraint_definitions(clean) == after_constraints
        assert await column_definitions(clean) == before_columns
        assert await index_definitions(clean) == before_indexes
