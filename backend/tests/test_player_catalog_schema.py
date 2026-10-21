"""Schema guarantees for the tenant-owned player catalog (RF-002).

These tests inspect the real PostgreSQL catalog after migration 015 and run as
``bracket_app``. They do not depend on demo data or execution order.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from db_helpers import (
    clear_rls_context,
    insert_player,
    set_tenant_context,
)

PLAYER_TENANT_TABLES = (
    "rosters",
    "match_lineup_snapshots",
    "match_events",
    "player_suspensions",
)


@pytest.mark.asyncio
async def test_players_is_tenant_owned_with_organization_fk(db_session):
    column = (
        await db_session.execute(
            text("""
                SELECT is_nullable, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'players'
                  AND column_name = 'organization_id'
            """)
        )
    ).mappings().one()

    assert column["is_nullable"] == "NO"
    assert column["data_type"] == "uuid"

    foreign_keys = (
        await db_session.execute(
            text("""
                SELECT c.conname,
                       (SELECT array_agg(a.attname ORDER BY k.ord)
                        FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = c.conrelid
                         AND a.attnum = k.attnum) AS columns,
                       c.confrelid::regclass::text AS referenced_table
                FROM pg_constraint c
                WHERE c.contype = 'f'
                  AND c.conrelid = 'public.players'::regclass
            """)
        )
    ).mappings().all()

    organization_fk = [
        row
        for row in foreign_keys
        if row["columns"] == ["organization_id"]
        and row["referenced_table"].rsplit(".", 1)[-1] == "organizations"
    ]
    assert organization_fk, "players.organization_id debe referenciar organizations(id)"


@pytest.mark.asyncio
async def test_players_enables_and_forces_the_tenant_rls_policy(db_session):
    security = (
        await db_session.execute(
            text("""
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = 'public.players'::regclass
            """)
        )
    ).mappings().one()

    assert security["relrowsecurity"] is True
    assert security["relforcerowsecurity"] is True

    policy = (
        await db_session.execute(
            text("""
                SELECT qual, with_check
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = 'players'
                  AND policyname = 'tenant_isolation_policy'
            """)
        )
    ).mappings().one()

    assert "app.current_organization_id" in policy["qual"]
    assert "fn_verify_user_org_membership" in policy["qual"]
    assert "app.current_organization_id" in policy["with_check"]
    assert "fn_verify_user_org_membership" in policy["with_check"]


@pytest.mark.asyncio
async def test_document_uniqueness_is_per_organization_and_global_uniqueness_is_gone(
    db_session,
):
    unique_indexes = (
        await db_session.execute(
            text("""
                SELECT i.indexrelid::regclass::text AS index_name,
                       (SELECT array_agg(a.attname ORDER BY k.ord)
                        FROM unnest(i.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = i.indrelid
                         AND a.attnum = k.attnum) AS columns
                FROM pg_index i
                WHERE i.indrelid = 'public.players'::regclass
                  AND i.indisunique
            """)
        )
    ).mappings().all()

    columns_by_index = {
        row["index_name"].rsplit(".", 1)[-1]: row["columns"] for row in unique_indexes
    }
    per_organization = [
        columns
        for columns in columns_by_index.values()
        if columns
        == ["organization_id", "document_type", "issuing_country", "national_id_hmac"]
    ]

    assert per_organization, (
        "Falta la unicidad por organización de document_type, issuing_country y national_id_hmac"
    )
    global_unique = [
        columns
        for columns in columns_by_index.values()
        if columns == ["document_type", "issuing_country", "national_id_hmac"]
    ]
    assert not global_unique, "La unicidad global del documento debe desaparecer"


@pytest.mark.asyncio
async def test_players_has_id_and_organization_composite_unique_key(db_session):
    unique_indexes = (
        await db_session.execute(
            text("""
                SELECT i.indexrelid::regclass::text AS index_name,
                       (SELECT array_agg(a.attname ORDER BY k.ord)
                        FROM unnest(i.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = i.indrelid
                         AND a.attnum = k.attnum) AS columns
                FROM pg_index i
                WHERE i.indrelid = 'public.players'::regclass
                  AND i.indisunique
            """)
        )
    ).mappings().all()

    assert any(
        row["columns"] == ["id", "organization_id"] for row in unique_indexes
    ), "Falta UNIQUE (id, organization_id) para las claves foráneas compuestas"


@pytest.mark.asyncio
async def test_player_references_use_composite_foreign_keys(db_session):
    rows = (
        await db_session.execute(
            text("""
                SELECT c.conrelid::regclass::text AS table_name,
                       c.conname,
                       (SELECT array_agg(a.attname ORDER BY k.ord)
                        FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = c.conrelid
                         AND a.attnum = k.attnum) AS columns,
                       (SELECT array_agg(a.attname ORDER BY k.ord)
                        FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a
                          ON a.attrelid = c.confrelid
                         AND a.attnum = k.attnum) AS referenced_columns,
                       c.confrelid::regclass::text AS referenced_table
                FROM pg_constraint c
                WHERE c.contype = 'f'
                  AND c.confrelid = 'public.players'::regclass
            """)
        )
    ).mappings().all()

    # Isolation pattern from 015: every tenant-owned reference is a composite
    # FK to players (id, organization_id). Migration 021 adds two more player
    # references to match_events for the substitution pair, so a table may own
    # several composite FKs and each allowed player column is declared here.
    allowed_pairs: dict[str, set[tuple[str, str]]] = {
        table: {("player_id", "organization_id")} for table in PLAYER_TENANT_TABLES
    }
    allowed_pairs["match_events"].update(
        {
            ("player_out_id", "organization_id"),
            ("player_in_id", "organization_id"),
        }
    )

    by_table: dict[str, list] = {table: [] for table in PLAYER_TENANT_TABLES}
    for row in rows:
        table = row["table_name"].rsplit(".", 1)[-1]
        if table in by_table:
            by_table[table].append(row)

    for table, allowed in allowed_pairs.items():
        references = by_table[table]
        assert references, f"{table} no referencia players"

        found: set[tuple[str, str]] = set()
        for reference in references:
            assert reference["referenced_columns"] == ["id", "organization_id"], (
                f"{table}.{reference['conname']} debe referenciar players(id, organization_id)"
            )
            assert reference["referenced_table"].rsplit(".", 1)[-1] == "players"
            found.add(tuple(reference["columns"]))

        missing = allowed - found
        assert not missing, (
            f"{table} no tiene las claves foráneas compuestas esperadas: {sorted(missing)}"
        )
        unexpected = found - allowed
        assert not unexpected, (
            f"{table} tiene claves foráneas a players no previstas: {sorted(unexpected)}"
        )

    # Nothing outside the declared map may reference players: a single-column
    # FK (`player_id` alone) would rely on RLS only and break the 015 pattern.
    unexpected_references = [
        row
        for row in rows
        if row["table_name"].rsplit(".", 1)[-1] not in allowed_pairs
        or tuple(row["columns"])
        not in allowed_pairs[row["table_name"].rsplit(".", 1)[-1]]
    ]
    assert not unexpected_references, (
        "Quedan claves foráneas simples o no previstas a players(id): "
        f"{[(row['table_name'], row['conname'], row['columns']) for row in unexpected_references]}"
    )


@pytest.mark.asyncio
async def test_player_grants_are_column_scoped_and_hide_the_encrypted_document(
    db_session,
):
    columns = (
        await db_session.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'players'
                  AND column_name IN ('birth_date', 'birth_date_encrypted',
                                      'age_at_reference', 'age_reference_year')
            """)
        )
    ).scalars().all()
    assert "birth_date" not in columns, (
        "La fecha de nacimiento en claro debe haberse eliminado"
    )
    assert "birth_date_encrypted" in columns

    grants = (
        await db_session.execute(
            text("""
                SELECT
                    has_column_privilege('bracket_app', 'public.players', 'organization_id', 'SELECT')
                        AS select_organization_id,
                    has_column_privilege('bracket_app', 'public.players', 'organization_id', 'INSERT')
                        AS insert_organization_id,
                    has_column_privilege('bracket_app', 'public.players', 'national_id_encrypted', 'SELECT')
                        AS select_national_id_encrypted,
                    has_column_privilege('bracket_app', 'public.players', 'national_id_encrypted', 'INSERT')
                        AS insert_national_id_encrypted,
                    has_column_privilege('bracket_app', 'public.players', 'birth_date_encrypted', 'SELECT')
                        AS select_birth_date_encrypted,
                    has_column_privilege('bracket_app', 'public.players', 'birth_date_encrypted', 'INSERT')
                        AS insert_birth_date_encrypted,
                    has_column_privilege('bracket_app', 'public.players', 'age_at_reference', 'SELECT')
                        AS select_age_at_reference,
                    has_column_privilege('bracket_app', 'public.players', 'age_at_reference', 'INSERT')
                        AS insert_age_at_reference,
                    has_column_privilege('bracket_app', 'public.players', 'age_reference_year', 'SELECT')
                        AS select_age_reference_year,
                    has_column_privilege('bracket_app', 'public.players', 'age_reference_year', 'INSERT')
                        AS insert_age_reference_year,
                    has_table_privilege('bracket_app', 'public.players', 'UPDATE')
                        AS update_players,
                    has_table_privilege('bracket_app', 'public.players', 'DELETE')
                        AS delete_players
            """)
        )
    ).mappings().one()

    assert grants["select_organization_id"] is True
    assert grants["insert_organization_id"] is True
    assert grants["select_national_id_encrypted"] is False
    assert grants["insert_national_id_encrypted"] is True
    assert grants["select_birth_date_encrypted"] is False
    assert grants["insert_birth_date_encrypted"] is True
    assert grants["select_age_at_reference"] is True
    assert grants["insert_age_at_reference"] is True
    assert grants["select_age_reference_year"] is True
    assert grants["insert_age_reference_year"] is True
    assert grants["update_players"] is False
    assert grants["delete_players"] is False


@pytest.mark.asyncio
async def test_players_rls_hides_rows_from_other_organizations(
    db_session, tenant_factory
):
    first = await tenant_factory("Catalog Owner A")
    second = await tenant_factory("Catalog Owner B")

    await set_tenant_context(db_session, first)
    first_player = await insert_player(db_session, first.organization_id)
    assert await _count_players(db_session) == 1

    await clear_rls_context(db_session)
    assert await _count_players(db_session) == 0

    await set_tenant_context(db_session, second)
    assert await _count_players(db_session) == 0

    second_player = await insert_player(db_session, second.organization_id)
    assert await _count_players(db_session) == 1
    visible = (
        await db_session.execute(text("SELECT id FROM players"))
    ).scalars().all()
    assert visible == [second_player]
    assert first_player not in visible


@pytest.mark.asyncio
async def test_players_rejects_inserts_for_another_organization(db_session, tenant_factory):
    first = await tenant_factory("Catalog Owner A")
    second = await tenant_factory("Catalog Owner B")

    await set_tenant_context(db_session, first)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await insert_player(db_session, second.organization_id)


@pytest.mark.asyncio
async def test_public_player_view_grants_match_the_public_contract(db_session):
    grants = (
        await db_session.execute(
            text("""
                SELECT
                    has_table_privilege(
                        'bracket_app', 'public.v_public_tournament_players', 'SELECT'
                    ) AS tournament_players,
                    has_table_privilege(
                        'bracket_app', 'public.v_public_match_lineups', 'SELECT'
                    ) AS match_lineups,
                    has_table_privilege(
                        'bracket_app',
                        'public.v_public_match_lineups_unpublished',
                        'SELECT'
                    ) AS unpublished_lineups
            """)
        )
    ).mappings().one()

    assert grants["tournament_players"] is True
    assert grants["match_lineups"] is True
    assert grants["unpublished_lineups"] is False


@pytest.mark.asyncio
async def test_public_lineup_views_work_without_an_organization_context(db_session):
    await clear_rls_context(db_session)

    # The accessible projections keep their grant and must resolve without a
    # tenant context. The suite may run over a database that already holds
    # published data (for example after the demo seed), so this test asserts
    # that the views answer and stay free of sensitive columns instead of
    # requiring an empty catalog; the exact rows are covered by
    # tests/test_public_player_views.py.
    assert isinstance(
        (
            await db_session.execute(text("SELECT count(*) FROM v_public_match_lineups"))
        ).scalar_one(),
        int,
    )
    assert isinstance(
        (
            await db_session.execute(text("SELECT count(*) FROM v_public_tournament_players"))
        ).scalar_one(),
        int,
    )

    exposed_columns = (
        await db_session.execute(
            text("""
                SELECT a.attname
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname IN ('v_public_match_lineups', 'v_public_tournament_players')
                  AND a.attnum > 0
                  AND NOT a.attisdropped
            """)
        )
    ).scalars().all()
    assert set(exposed_columns).isdisjoint(
        {"document_type", "national_id_encrypted", "national_id_hmac", "birth_date"}
    )

    # The raw unpublished view must remain inaccessible to the application role.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("SELECT count(*) FROM v_public_match_lineups_unpublished")
            )


@pytest.mark.asyncio
async def test_roster_rejects_a_player_from_another_organization(
    db_session, tenant_factory
):
    """The composite FK stops a roster from mixing two organizations (RF-002)."""

    first = await tenant_factory("FK Owner A")
    second = await tenant_factory("FK Owner B")

    await set_tenant_context(db_session, second)
    foreign_player_id = await insert_player(
        db_session, second.organization_id, first_name="Foreign"
    )

    await set_tenant_context(db_session, first)
    tournament_id, team_id = await _create_tournament_with_team(db_session, first)

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("""
                    INSERT INTO rosters
                        (organization_id, tournament_id, team_id, player_id,
                         dorsal_number, valid_from, eligible_from)
                    VALUES
                        (:organization_id, :tournament_id, :team_id, :player_id,
                         1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "organization_id": str(first.organization_id),
                    "tournament_id": str(tournament_id),
                    "team_id": str(team_id),
                    "player_id": str(foreign_player_id),
                },
            )

    assert _sqlstate(error.value) == "23503"
    assert "fk_rosters_player_organization" in str(error.value.orig)
    assert await _count_rows(db_session, "rosters") == 0


@pytest.mark.asyncio
async def test_suspension_rejects_a_player_from_another_organization(
    db_session, tenant_factory
):
    """A suspension cannot reference a player from another organization."""

    first = await tenant_factory("FK Owner A")
    second = await tenant_factory("FK Owner B")

    await set_tenant_context(db_session, second)
    foreign_player_id = await insert_player(
        db_session, second.organization_id, first_name="Foreign"
    )

    await set_tenant_context(db_session, first)
    tournament_id, _ = await _create_tournament_with_team(db_session, first)

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("""
                    INSERT INTO player_suspensions
                        (organization_id, source_tournament_id, player_id,
                         source_type, dedupe_key, scope_type, matches_suspended,
                         reason)
                    VALUES
                        (:organization_id, :tournament_id, :player_id,
                         'administrative_resolution', :dedupe_key, 'tournament', 1,
                         'Cross-tenant rejection')
                """),
                {
                    "organization_id": str(first.organization_id),
                    "tournament_id": str(tournament_id),
                    "player_id": str(foreign_player_id),
                    "dedupe_key": f"fk-{uuid4().hex}",
                },
            )

    assert _sqlstate(error.value) == "23503"
    assert "fk_player_suspensions_player_organization" in str(error.value.orig)
    assert await _count_rows(db_session, "player_suspensions") == 0


def _sqlstate(error: DBAPIError) -> str | None:
    """Return the PostgreSQL SQLSTATE carried by a SQLAlchemy DBAPI error."""

    return getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)


async def _create_tournament_with_team(session, tenant) -> tuple[UUID, UUID]:
    """Create a tournament with one registered team in the active tenant."""

    suffix = uuid4().hex[:8]
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status,
                     current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', '2026-01-01', 'draft',
                     '{}'::jsonb)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"FK {suffix}",
            },
        )
    ).scalar_one()
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"FK Team {suffix}",
                "short_code": f"FK{suffix[:5].upper()}",
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO tournament_teams
                (organization_id, tournament_id, team_id, status)
            VALUES
                (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    return tournament_id, team_id


async def _count_rows(session, table: str) -> int:
    return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


async def _count_players(session) -> int:
    return (await session.execute(text("SELECT count(*) FROM players"))).scalar_one()


@pytest.mark.asyncio
async def test_bracket_app_can_insert_a_pre_generated_roster_id_by_column(db_session):
    """Migration 020: column-level INSERT(id) without table-wide INSERT."""

    privileges = (
        await db_session.execute(
            text("""
                SELECT
                    has_column_privilege(
                        'bracket_app', 'public.rosters', 'id', 'INSERT'
                    ) AS id_insert,
                    has_table_privilege(
                        'bracket_app', 'public.rosters', 'INSERT'
                    ) AS table_insert
            """)
        )
    ).mappings().one()

    assert privileges["id_insert"] is True
    assert privileges["table_insert"] is False
