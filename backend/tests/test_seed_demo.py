from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import date
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.modules.matches.formations import FORMATION_SLOTS
from db_helpers import create_tenant_owner
from scripts import seed_demo
from scripts.seed_demo import (
    ADVANCEMENT_SPECS,
    MATCH_SPECS,
    PLAYER_SPECS,
    RosterRecord,
    TEAM_SPECS,
    _goal_events,
    validate_demo_definition,
)


def test_demo_definition_has_a_complete_eight_team_bracket():
    validate_demo_definition()

    assert len(TEAM_SPECS) == 8
    assert len(MATCH_SPECS) == 7
    assert len(ADVANCEMENT_SPECS) == 6
    assert [match.code for match in MATCH_SPECS[:4]] == ["QF1", "QF2", "QF3", "QF4"]
    assert [match.code for match in MATCH_SPECS[4:]] == ["SF1", "SF2", "FINAL"]


def test_demo_has_twelve_players_and_valid_formations_per_team():
    players_by_team = Counter(player.team_code for player in PLAYER_SPECS)

    assert players_by_team == {team.code: 12 for team in TEAM_SPECS}
    assert all(
        formation in FORMATION_SLOTS
        for match in MATCH_SPECS[:4]
        for formation in (match.home_formation, match.away_formation)
    )
    assert all(
        sorted(player.dorsal_number for player in PLAYER_SPECS if player.team_code == team.code)
        == list(range(1, 13))
        for team in TEAM_SPECS
    )


def test_demo_goal_events_match_the_declared_quarterfinal_score():
    match = MATCH_SPECS[3]
    home_team_id = uuid4()
    away_team_id = uuid4()
    home_players = tuple(
        RosterRecord(roster_id=uuid4(), player_id=uuid4(), dorsal_number=index + 1)
        for index in range(12)
    )
    away_players = tuple(
        RosterRecord(roster_id=uuid4(), player_id=uuid4(), dorsal_number=index + 1)
        for index in range(12)
    )

    events = _goal_events(
        match,
        uuid4(),
        home_team_id,
        away_team_id,
        home_players,
        away_players,
    )

    assert len(events) == 5
    assert Counter(event.team_id for event in events) == {
        home_team_id: match.home_score,
        away_team_id: match.away_score,
    }


class _NoQueriesSession:
    """Session double that fails if the seed attempts any database access."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("el seed no debe ejecutar consultas con una fecha imposible")


@pytest.mark.asyncio
async def test_seed_rejects_an_impossible_birth_date_before_inserting(monkeypatch):
    """RF-010: the seed validates dates and aborts without writing a single row."""

    session = _NoQueriesSession()
    impossible = replace(PLAYER_SPECS[0], birth_date=date(9999, 12, 31))
    monkeypatch.setattr(seed_demo, "PLAYER_SPECS", (impossible,))
    team_ids = {team.code: uuid4() for team in TEAM_SPECS}

    with pytest.raises(ValueError) as error:
        await seed_demo._ensure_rosters(
            session,
            uuid4(),
            uuid4(),
            team_ids,
            date(2026, 1, 1),
            "test-player-data-key-with-at-least-32-characters",
        )

    message = str(error.value)
    assert "Seed abortado" in message
    assert "1 jugador" in message
    # The identifier is internal (team/dorsal) and the rejected date never leaks.
    assert "AUR-01" in message
    assert "9999-12-31" not in message
    assert session.calls == 0


@asynccontextmanager
async def _administrator_transaction(database_admin_url: str):
    """Yield one admin transaction that can impersonate the application role."""

    engine = create_async_engine(database_admin_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
                await transaction.rollback()
    finally:
        await engine.dispose()


async def _create_tournament_with_team(
    session: AsyncSession, organization_id: UUID
) -> tuple[UUID, UUID]:
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
                "organization_id": str(organization_id),
                "name": f"Seed {suffix}",
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
                "organization_id": str(organization_id),
                "name": f"Seed Team {suffix}",
                "short_code": f"SD{suffix[:5].upper()}",
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
            "organization_id": str(organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    return tournament_id, team_id


@pytest.mark.asyncio
async def test_seed_demo_encrypts_the_birth_date_and_materializes_the_age(
    database_admin_url, monkeypatch
):
    """RF-001/RF-007: the seed writes ciphertext and the reference age only."""

    settings = get_settings()
    team_spec = seed_demo.TEAM_SPECS[0]
    player_specs = tuple(
        player for player in seed_demo.PLAYER_SPECS if player.team_code == team_spec.code
    )
    monkeypatch.setattr(seed_demo, "TEAM_SPECS", (team_spec,))
    monkeypatch.setattr(seed_demo, "PLAYER_SPECS", player_specs)

    start_date = date(2026, 1, 1)
    async with _administrator_transaction(database_admin_url) as session:
        await session.execute(text("SET LOCAL ROLE bracket_app"))
        tenant = await create_tenant_owner(session, full_name="Seed Encryption Owner")
        tournament_id, team_id = await _create_tournament_with_team(
            session, tenant.organization_id
        )

        rosters = await seed_demo._ensure_rosters(
            session,
            tenant.organization_id,
            tournament_id,
            {team_spec.code: team_id},
            start_date,
            settings.player_data_key,
        )
        assert len(rosters[team_spec.code]) == len(player_specs)

        rows = (
            await session.execute(
                text("""
                    SELECT first_name, last_name, age_at_reference,
                           age_reference_year,
                           (SELECT count(*) FROM rosters r
                            WHERE r.player_id = p.id
                              AND r.organization_id = p.organization_id) AS roster_count
                    FROM players p
                """)
            )
        ).mappings().all()
        assert len(rows) == len(player_specs)
        expected_ages = {
            (player.first_name, player.last_name): start_date.year - player.birth_date.year
            for player in player_specs
        }
        for row in rows:
            assert row["roster_count"] == 1
            assert row["age_reference_year"] == start_date.year
            assert row["age_at_reference"] == expected_ages[
                (row["first_name"], row["last_name"])
            ]

        # The seed is idempotent: it reuses players and rosters.
        repeated = await seed_demo._ensure_rosters(
            session,
            tenant.organization_id,
            tournament_id,
            {team_spec.code: team_id},
            start_date,
            settings.player_data_key,
        )
        assert {record.roster_id for record in repeated[team_spec.code]} == {
            record.roster_id for record in rosters[team_spec.code]
        }
        assert (
            await session.execute(text("SELECT count(*) FROM players"))
        ).scalar_one() == len(player_specs)

        # The birth date is stored encrypted; the administrator can verify the
        # round trip after dropping the application role.
        await session.execute(text("RESET ROLE"))
        decrypted = (
            await session.execute(
                text("""
                    SELECT pgp_sym_decrypt(birth_date_encrypted, :player_data_key)::date::text
                    FROM players
                    WHERE organization_id = :organization_id
                """),
                {
                    "player_data_key": settings.player_data_key,
                    "organization_id": str(tenant.organization_id),
                },
            )
        ).scalars().all()
        assert sorted(decrypted) == sorted(
            player.birth_date.isoformat() for player in player_specs
        )
