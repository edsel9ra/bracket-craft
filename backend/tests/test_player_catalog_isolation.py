"""Tenant isolation for the player catalog in the Workspace flows (RF-001/RF-003).

These tests exercise the real registration and bulk-import helpers against a
PostgreSQL instance migrated with 015. They run as ``bracket_app`` (no
superuser, no ``BYPASSRLS``), create their own organizations and tournaments and
never depend on demo data or execution order.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.core.tenancy import AuthContext
from app.modules.tournaments import router as tournaments_router
from app.modules.tournaments.roster_import import parse_roster_csv
from app.modules.tournaments.router import (
    _create_roster_player_record,
    _load_roster_player,
)
from app.modules.tournaments.schemas import CreateRosterPlayerRequest
from db_helpers import TenantContext, insert_player, set_tenant_context
from scripts import seed_demo


def _context(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


def _document_hmac(national_id: str, player_data_key: str) -> str:
    return hmac.new(
        player_data_key.encode("utf-8"),
        national_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _payload(
    team_id: UUID,
    *,
    first_name: str,
    last_name: str,
    national_id: str,
    dorsal_number: int,
    document_type: str = "internal",
    issuing_country: str = "COL",
    birth_date: str = "1990-01-01",
) -> CreateRosterPlayerRequest:
    return CreateRosterPlayerRequest(
        team_id=team_id,
        first_name=first_name,
        last_name=last_name,
        document_type=document_type,
        national_id=national_id,
        issuing_country=issuing_country,
        birth_date=date.fromisoformat(birth_date),
        dorsal_number=dorsal_number,
    )


async def _create_tournament(session, organization_id: UUID) -> UUID:
    result = await session.execute(
        text("""
            INSERT INTO tournaments
                (organization_id, name, season, start_date, status, current_draft_config)
            VALUES (:organization_id, :name, '2026', '2026-01-01', 'draft', '{}'::jsonb)
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "name": f"T003 {uuid4().hex[:8]}",
        },
    )
    return result.scalar_one()


async def _register_team(session, organization_id: UUID, tournament_id: UUID) -> UUID:
    result = await session.execute(
        text("""
            INSERT INTO teams (organization_id, name, short_code)
            VALUES (:organization_id, :name, :short_code)
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "name": f"Team {uuid4().hex[:6]}",
            "short_code": f"T{uuid4().hex[:6].upper()}",
        },
    )
    team_id = result.scalar_one()
    await session.execute(
        text("""
            INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    return team_id


async def _count(session, table: str) -> int:
    return (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()


@pytest.mark.asyncio
async def test_same_document_in_two_organizations_stays_isolated(db_session, tenant_factory):
    settings = get_settings()
    first = await tenant_factory("Isolation A")
    second = await tenant_factory("Isolation B")

    await set_tenant_context(db_session, first)
    first_tournament = await _create_tournament(db_session, first.organization_id)
    first_team = await _register_team(db_session, first.organization_id, first_tournament)
    first_roster_id, first_player_id = await _create_roster_player_record(
        db_session,
        _context(first),
        first_tournament,
        _payload(
            first_team,
            first_name="Alice",
            last_name="Alpha",
            national_id="ISO-1",
            dorsal_number=1,
        ),
        settings,
    )

    await set_tenant_context(db_session, second)
    second_tournament = await _create_tournament(db_session, second.organization_id)
    second_team = await _register_team(db_session, second.organization_id, second_tournament)
    second_roster_id, second_player_id = await _create_roster_player_record(
        db_session,
        _context(second),
        second_tournament,
        _payload(
            second_team,
            first_name="Bruno",
            last_name="Beta",
            national_id="ISO-1",
            dorsal_number=7,
        ),
        settings,
    )

    # The same document produces two independent records, one per organization.
    assert first_player_id != second_player_id

    # B sees only its own catalog and its own data.
    assert (await db_session.execute(text("SELECT id FROM players"))).scalars().all() == [
        second_player_id
    ]
    second_roster = await _load_roster_player(db_session, second.organization_id, second_roster_id)
    assert second_roster["player_id"] == second_player_id
    assert second_roster["first_name"] == "Bruno"
    assert second_roster["last_name"] == "Beta"

    # A keeps its own data and cannot even count B's row.
    await set_tenant_context(db_session, first)
    assert (await db_session.execute(text("SELECT id FROM players"))).scalars().all() == [
        first_player_id
    ]
    first_roster = await _load_roster_player(db_session, first.organization_id, first_roster_id)
    assert first_roster["player_id"] == first_player_id
    assert first_roster["first_name"] == "Alice"
    assert first_roster["last_name"] == "Alpha"
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM players WHERE id = :player_id"),
            {"player_id": str(second_player_id)},
        )
    ).scalar_one() == 0

    # B's record still exists for B; it was not replaced by A's.
    await set_tenant_context(db_session, second)
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM players WHERE id = :player_id"),
            {"player_id": str(second_player_id)},
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_same_document_in_the_same_organization_reuses_the_player(db_session, tenant_factory):
    settings = get_settings()
    tenant = await tenant_factory("Reuse Owner")

    await set_tenant_context(db_session, tenant)
    first_tournament = await _create_tournament(db_session, tenant.organization_id)
    first_team = await _register_team(db_session, tenant.organization_id, first_tournament)
    second_tournament = await _create_tournament(db_session, tenant.organization_id)
    second_team = await _register_team(db_session, tenant.organization_id, second_tournament)

    first_roster_id, first_player_id = await _create_roster_player_record(
        db_session,
        _context(tenant),
        first_tournament,
        _payload(
            first_team, first_name="Carla", last_name="Gamma", national_id="REUSE-1", dorsal_number=4
        ),
        settings,
    )
    second_roster_id, second_player_id = await _create_roster_player_record(
        db_session,
        _context(tenant),
        second_tournament,
        _payload(
            second_team, first_name="Carla", last_name="Gamma", national_id="REUSE-1", dorsal_number=4
        ),
        settings,
    )

    assert first_player_id == second_player_id
    assert first_roster_id != second_roster_id
    assert await _count(db_session, "players") == 1
    assert (
        await db_session.execute(text("SELECT DISTINCT player_id FROM rosters"))
    ).scalars().all() == [first_player_id]
    assert await _count(db_session, "rosters") == 2


@pytest.mark.asyncio
async def test_bulk_import_keeps_the_catalog_tenant_scoped(db_session, tenant_factory):
    settings = get_settings()
    first = await tenant_factory("Import A")
    second = await tenant_factory("Import B")

    # Organization B already owns IMPORT-1 in its own catalog.
    await set_tenant_context(db_session, second)
    second_tournament = await _create_tournament(db_session, second.organization_id)
    second_team = await _register_team(db_session, second.organization_id, second_tournament)
    _, second_player_id = await _create_roster_player_record(
        db_session,
        _context(second),
        second_tournament,
        _payload(
            second_team,
            first_name="Owned",
            last_name="Elsewhere",
            national_id="IMPORT-1",
            dorsal_number=2,
        ),
        settings,
    )

    csv_raw = (
        "first_name,last_name,national_id,birth_date,dorsal_number\n"
        "Diego,Delta,IMPORT-1,1995-03-04,9\n"
        "Elena,Epsilon,IMPORT-2,1996-05-06,10\n"
    ).encode("utf-8")

    await set_tenant_context(db_session, first)
    first_tournament = await _create_tournament(db_session, first.organization_id)
    first_team = await _register_team(db_session, first.organization_id, first_tournament)

    imported_rows = parse_roster_csv(csv_raw, first_team)
    created = [
        await _create_roster_player_record(
            db_session, _context(first), first_tournament, row.payload, settings
        )
        for row in imported_rows
    ]
    imported_player_ids = [player_id for _, player_id in created]

    # The import never reuses the catalog of another organization.
    assert second_player_id not in imported_player_ids
    assert len(set(imported_player_ids)) == 2
    assert await _count(db_session, "players") == 2

    # Re-importing the same documents into another tournament of the same
    # organization keeps reusing this organization's players.
    repeated_tournament = await _create_tournament(db_session, first.organization_id)
    repeated_team = await _register_team(db_session, first.organization_id, repeated_tournament)
    repeated = [
        await _create_roster_player_record(
            db_session,
            _context(first),
            repeated_tournament,
            row.payload,
            settings,
        )
        for row in parse_roster_csv(csv_raw, repeated_team)
    ]
    assert [player_id for _, player_id in repeated] == imported_player_ids
    assert await _count(db_session, "players") == 2


@pytest.mark.asyncio
async def test_concurrent_duplicate_reuses_the_winner_without_partial_data(
    db_session, tenant_factory
):
    settings = get_settings()
    tenant = await tenant_factory("Race Owner")

    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_tournament(db_session, tenant.organization_id)
    team_id = await _register_team(db_session, tenant.organization_id, tournament_id)

    # A concurrent transaction already committed the winning row.
    winner_id = await insert_player(
        db_session,
        tenant.organization_id,
        first_name="Winner",
        last_name="Row",
        document_type="internal",
        issuing_country="COL",
        national_id_hmac=_document_hmac("RACE-1", settings.player_data_key),
    )

    roster_id, player_id = await _create_roster_player_record(
        db_session,
        _context(tenant),
        tournament_id,
        _payload(
            team_id,
            first_name="Loser",
            last_name="Attempt",
            national_id="RACE-1",
            dorsal_number=3,
        ),
        settings,
    )

    assert player_id == winner_id
    assert roster_id is not None
    assert await _count(db_session, "players") == 1
    assert await _count(db_session, "rosters") == 1

    # A direct duplicate insert is rejected by the per-organization unique key
    # and leaves no partial data behind.
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("""
                    INSERT INTO players
                        (organization_id, first_name, last_name, document_type,
                         national_id_encrypted, national_id_hmac, issuing_country, birth_date)
                    VALUES
                        (:organization_id, 'Ghost', 'Row', 'internal', decode('00', 'hex'),
                         :national_id_hmac, 'COL', '2000-01-01')
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "national_id_hmac": _document_hmac("RACE-1", settings.player_data_key),
                },
            )

    assert await _count(db_session, "players") == 1
    assert await _count(db_session, "rosters") == 1


@pytest.mark.asyncio
async def test_race_conflict_falls_back_to_the_winning_row(db_session, tenant_factory, monkeypatch):
    """Simulate the interleaving where the lookup misses but the unique index wins."""

    settings = get_settings()
    tenant = await tenant_factory("Race Fallback")

    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_tournament(db_session, tenant.organization_id)
    team_id = await _register_team(db_session, tenant.organization_id, tournament_id)

    winner_id = await insert_player(
        db_session,
        tenant.organization_id,
        first_name="Committed",
        last_name="Winner",
        document_type="internal",
        issuing_country="COL",
        national_id_hmac=_document_hmac("RACE-2", settings.player_data_key),
    )

    original_lookup = tournaments_router._find_player_by_document
    lookups = {"count": 0}

    async def lookup_with_one_miss(session, organization_id, payload, settings_):
        lookups["count"] += 1
        if lookups["count"] == 1:
            # The concurrent winner was not visible to the first lookup yet.
            return None
        return await original_lookup(session, organization_id, payload, settings_)

    monkeypatch.setattr(tournaments_router, "_find_player_by_document", lookup_with_one_miss)

    roster_id, player_id = await _create_roster_player_record(
        db_session,
        _context(tenant),
        tournament_id,
        _payload(
            team_id,
            first_name="Loser",
            last_name="Attempt",
            national_id="RACE-2",
            dorsal_number=6,
        ),
        settings,
    )

    assert lookups["count"] == 2
    assert player_id == winner_id
    assert roster_id is not None
    assert await _count(db_session, "players") == 1
    assert await _count(db_session, "rosters") == 1


@pytest.mark.asyncio
async def test_seed_demo_players_are_tenant_scoped_and_always_have_a_roster(
    db_session, tenant_factory, monkeypatch
):
    settings = get_settings()
    tenant = await tenant_factory("Seed Owner")

    team_spec = seed_demo.TEAM_SPECS[0]
    player_specs = tuple(
        player for player in seed_demo.PLAYER_SPECS if player.team_code == team_spec.code
    )
    monkeypatch.setattr(seed_demo, "TEAM_SPECS", (team_spec,))
    monkeypatch.setattr(seed_demo, "PLAYER_SPECS", player_specs)

    await set_tenant_context(db_session, tenant)
    tournament_id = await _create_tournament(db_session, tenant.organization_id)
    team_id = await _register_team(db_session, tenant.organization_id, tournament_id)
    start_date = date(2026, 1, 1)

    rosters = await seed_demo._ensure_rosters(
        db_session,
        tenant.organization_id,
        tournament_id,
        {team_spec.code: team_id},
        start_date,
        settings.player_data_key,
    )

    assert len(rosters[team_spec.code]) == len(player_specs)
    players = (
        await db_session.execute(
            text("""
                SELECT p.id, p.organization_id,
                       (SELECT count(*) FROM rosters r
                        WHERE r.player_id = p.id
                          AND r.organization_id = p.organization_id) AS roster_count
                FROM players p
            """)
        )
    ).mappings().all()
    assert len(players) == len(player_specs)
    assert all(row["organization_id"] == tenant.organization_id for row in players)
    assert all(row["roster_count"] == 1 for row in players)

    # The seed is idempotent: it reuses players and rosters.
    repeated = await seed_demo._ensure_rosters(
        db_session,
        tenant.organization_id,
        tournament_id,
        {team_spec.code: team_id},
        start_date,
        settings.player_data_key,
    )
    assert {record.roster_id for record in repeated[team_spec.code]} == {
        record.roster_id for record in rosters[team_spec.code]
    }
    assert await _count(db_session, "players") == len(player_specs)
    assert await _count(db_session, "rosters") == len(player_specs)


@pytest.mark.asyncio
async def test_seed_demo_player_lookup_does_not_reuse_another_organization(
    db_session, tenant_factory, monkeypatch
):
    settings = get_settings()
    first = await tenant_factory("Seed A")
    second = await tenant_factory("Seed B")

    team_spec = seed_demo.TEAM_SPECS[0]
    player_specs = tuple(
        player for player in seed_demo.PLAYER_SPECS if player.team_code == team_spec.code
    )
    monkeypatch.setattr(seed_demo, "TEAM_SPECS", (team_spec,))
    monkeypatch.setattr(seed_demo, "PLAYER_SPECS", player_specs)

    shared_document = player_specs[0].national_id
    shared_hmac = _document_hmac(shared_document, settings.player_data_key)

    # Organization B owns the same document in its own catalog.
    await set_tenant_context(db_session, second)
    foreign_player_id = await insert_player(
        db_session,
        second.organization_id,
        document_type="internal",
        issuing_country="COL",
        national_id_hmac=shared_hmac,
    )

    await set_tenant_context(db_session, first)
    tournament_id = await _create_tournament(db_session, first.organization_id)
    team_id = await _register_team(db_session, first.organization_id, tournament_id)
    rosters = await seed_demo._ensure_rosters(
        db_session,
        first.organization_id,
        tournament_id,
        {team_spec.code: team_id},
        date(2026, 1, 1),
        settings.player_data_key,
    )

    # Under A's context only A's own player with that document is visible.
    visible = (
        await db_session.execute(
            text("""
                SELECT id FROM players
                WHERE organization_id = :organization_id
                  AND national_id_hmac = :national_id_hmac
            """),
            {"organization_id": str(first.organization_id), "national_id_hmac": shared_hmac},
        )
    ).scalars().all()
    assert len(visible) == 1
    organization_player_id = visible[0]
    assert organization_player_id != foreign_player_id

    # A's rosters point at A's player, never at B's.
    assert any(record.player_id == organization_player_id for record in rosters[team_spec.code])
    assert all(record.player_id != foreign_player_id for record in rosters[team_spec.code])

    # B's record is untouched and has no roster in A.
    await set_tenant_context(db_session, second)
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM players WHERE id = :player_id"),
            {"player_id": str(foreign_player_id)},
        )
    ).scalar_one() == 1
    assert await _count(db_session, "rosters") == 0
