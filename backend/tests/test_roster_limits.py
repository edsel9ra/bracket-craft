"""Effective roster limits, per-team size state and violations (RF-045, RF-050).

The three functions are pure: no clock, no session and no network. ``0`` (or an
absent key) means "no limit", so a stored configuration without the keys behaves
exactly as before.

``describe_roster_violations`` renders the 409 ``ROSTER_SIZE_OUT_OF_RANGE``
detail: it names the team and shows the minimum, the maximum and the active
count, uses "sin límite" for ``0`` and is deterministic — every row when there
are at most ten, otherwise the first ten by team name (identifier breaks ties)
plus the total.

The last, opt-in test exercises the real counting query against PostgreSQL with
the application role (``RUN_DATABASE_TESTS=1``): only active rows of the given
tournament count and the RLS context keeps organizations apart.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.schemas import TournamentRulesConfig
from app.modules.tournaments.roster_status import (
    ROSTER_SIZE_OUT_OF_RANGE,
    RosterLimits,
    RosterTeamCount,
    count_active_roster_players_by_team,
    describe_roster_violations,
    effective_roster_limits,
    roster_size_state,
    roster_violations,
)
from db_helpers import TenantContext, insert_player, set_tenant_context

DETAIL_HEADER = "Plantilla fuera de rango: "


# ---------------------------------------------------------------------------
# effective_roster_limits
# ---------------------------------------------------------------------------


def test_absent_keys_mean_no_limit() -> None:
    assert effective_roster_limits({}) == RosterLimits(min=0, max=0)
    assert effective_roster_limits({}).has_limits is False


def test_explicit_zero_means_no_limit() -> None:
    assert effective_roster_limits(
        {"min_players_per_team": 0, "max_players_per_team": 0}
    ) == RosterLimits(min=0, max=0)


def test_none_means_no_limit() -> None:
    assert effective_roster_limits(
        {"min_players_per_team": None, "max_players_per_team": None}
    ) == RosterLimits(min=0, max=0)


def test_declared_limits_are_read() -> None:
    limits = effective_roster_limits(
        {"min_players_per_team": 11, "max_players_per_team": 20}
    )
    assert limits == RosterLimits(min=11, max=20)
    assert limits.has_limits is True


def test_one_sided_limits_are_read() -> None:
    assert effective_roster_limits({"min_players_per_team": 7}) == RosterLimits(min=7, max=0)
    assert effective_roster_limits({"max_players_per_team": 18}) == RosterLimits(min=0, max=18)


def test_limits_accept_the_validated_schema() -> None:
    config = TournamentRulesConfig.model_validate(
        {
            **DEFAULT_RULES_CONFIG,
            "min_players_per_team": 9,
            "max_players_per_team": 16,
        }
    )
    assert effective_roster_limits(config) == RosterLimits(min=9, max=16)


# ---------------------------------------------------------------------------
# roster_size_state
# ---------------------------------------------------------------------------


def test_state_inside_the_range() -> None:
    limits = RosterLimits(min=11, max=20)
    assert roster_size_state(11, limits) == "ok"
    assert roster_size_state(15, limits) == "ok"
    assert roster_size_state(20, limits) == "ok"


def test_state_below_the_minimum() -> None:
    assert roster_size_state(10, RosterLimits(min=11, max=20)) == "below"


def test_state_above_the_maximum() -> None:
    assert roster_size_state(21, RosterLimits(min=11, max=20)) == "above"


def test_state_without_limits_never_rejects() -> None:
    no_limits = RosterLimits(min=0, max=0)
    assert roster_size_state(0, no_limits) == "ok"
    assert roster_size_state(999, no_limits) == "ok"


def test_state_with_only_a_maximum() -> None:
    limits = RosterLimits(min=0, max=18)
    assert roster_size_state(0, limits) == "ok"
    assert roster_size_state(18, limits) == "ok"
    assert roster_size_state(19, limits) == "above"


def test_state_with_only_a_minimum() -> None:
    limits = RosterLimits(min=7, max=0)
    assert roster_size_state(7, limits) == "ok"
    assert roster_size_state(200, limits) == "ok"
    assert roster_size_state(6, limits) == "below"


def test_state_when_minimum_equals_maximum() -> None:
    limits = RosterLimits(min=11, max=11)
    assert roster_size_state(11, limits) == "ok"
    assert roster_size_state(10, limits) == "below"
    assert roster_size_state(12, limits) == "above"


def test_violations_only_keep_rows_out_of_range() -> None:
    limits = RosterLimits(min=11, max=20)
    rows = [
        RosterTeamCount(team_id=uuid4(), team_name="Bajo", count=10),
        RosterTeamCount(team_id=uuid4(), team_name="Dentro", count=11),
        RosterTeamCount(team_id=uuid4(), team_name="Alto", count=21),
    ]
    violations = roster_violations(rows, limits)
    assert [row.team_name for row in violations] == ["Alto", "Bajo"]
    assert roster_violations(rows, RosterLimits(min=0, max=0)) == []


# ---------------------------------------------------------------------------
# describe_roster_violations
# ---------------------------------------------------------------------------


def test_detail_names_team_minimum_maximum_and_count() -> None:
    team_id = uuid4()
    rows = [RosterTeamCount(team_id=team_id, team_name="Los Halcones", count=8)]

    detail = describe_roster_violations(rows, RosterLimits(min=11, max=20))

    assert detail == (
        f"{DETAIL_HEADER}«Los Halcones»: 8 jugadores activos "
        "(mínimo: 11, máximo: 20)."
    )


def test_detail_uses_sin_limite_for_zero() -> None:
    above = [RosterTeamCount(team_id=uuid4(), team_name="Sin tope", count=25)]
    below = [RosterTeamCount(team_id=uuid4(), team_name="Sin tope", count=5)]

    assert describe_roster_violations(above, RosterLimits(min=0, max=0)) == ""
    assert describe_roster_violations(above, RosterLimits(min=0, max=20)) == (
        f"{DETAIL_HEADER}«Sin tope»: 25 jugadores activos "
        "(mínimo: sin límite, máximo: 20)."
    )
    assert describe_roster_violations(below, RosterLimits(min=11, max=0)) == (
        f"{DETAIL_HEADER}«Sin tope»: 5 jugadores activos "
        "(mínimo: 11, máximo: sin límite)."
    )


def test_detail_singular_count() -> None:
    rows = [RosterTeamCount(team_id=uuid4(), team_name="Corto", count=1)]

    assert describe_roster_violations(rows, RosterLimits(min=2, max=0)) == (
        f"{DETAIL_HEADER}«Corto»: 1 jugador activo (mínimo: 2, máximo: sin límite)."
    )


def test_detail_lists_every_team_up_to_ten() -> None:
    names = [
        "Alfa",
        "Bravo",
        "Charlie",
        "Delta",
        "Eco",
        "Foxtrot",
        "Golf",
        "Hotel",
        "India",
        "Juliet",
    ]
    rows = [
        RosterTeamCount(team_id=uuid4(), team_name=name, count=10)
        for name in reversed(names)
    ]

    detail = describe_roster_violations(rows, RosterLimits(min=11, max=20))

    assert detail.startswith(DETAIL_HEADER)
    assert detail.endswith(".")
    assert "Se muestran" not in detail
    positions = [detail.index(f"«{name}»") for name in names]
    assert positions == sorted(positions)


def test_detail_truncates_to_ten_by_name_then_identifier() -> None:
    unique_names = [
        "Alfa",
        "Bravo",
        "Charlie",
        "Delta",
        "Echo",
        "Foxtrot",
        "Golf",
        "Hotel",
        "India",
        "Juliet",
    ]
    rows = [
        RosterTeamCount(team_id=uuid4(), team_name=name, count=0)
        for name in reversed(unique_names)
    ]
    # Same name three times: the identifier decides the order and the counts
    # make it observable in the rendered detail.
    for index, team_id in enumerate((UUID(int=3), UUID(int=1), UUID(int=2))):
        rows.append(RosterTeamCount(team_id=team_id, team_name="Empate", count=index))
    rows.append(RosterTeamCount(team_id=uuid4(), team_name="Zulu", count=0))

    detail = describe_roster_violations(rows, RosterLimits(min=3, max=0))

    assert detail.count("«") == 10
    # Sorted by name: Alfa, Bravo, Charlie, Delta, Echo, Empate, Empate, Empate,
    # Foxtrot, Golf; Hotel, India, Juliet and Zulu fall outside the first ten.
    for name in ["Alfa", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf"]:
        assert f"«{name}»" in detail
    for name in ["Hotel", "India", "Juliet", "Zulu"]:
        assert f"«{name}»" not in detail
    # Identifier breaks the name tie: the counts make the UUID order observable
    # (UUID 1 → 1, UUID 2 → 2, UUID 3 → 0).
    tie_positions = [
        detail.index(f"«Empate»: {count} jugador") for count in (1, 2, 0)
    ]
    assert tie_positions == sorted(tie_positions)
    assert (
        "Se muestran los 10 primeros; 14 equipos fuera de rango en total" in detail
    )
    assert detail.endswith("en total.")


def test_detail_truncation_is_deterministic_for_tied_names() -> None:
    rows = [
        RosterTeamCount(team_id=UUID(int=index), team_name="Mismo", count=0)
        for index in range(1, 13)
    ]

    first = describe_roster_violations(rows, RosterLimits(min=1, max=0))
    second = describe_roster_violations(list(reversed(rows)), RosterLimits(min=1, max=0))

    assert first == second
    assert first.count("«Mismo»") == 10
    assert "12 equipos fuera de rango en total" in first


def test_detail_ignores_rows_inside_the_range() -> None:
    rows = [
        RosterTeamCount(team_id=uuid4(), team_name="Dentro", count=15),
        RosterTeamCount(team_id=uuid4(), team_name="Fuera", count=21),
    ]

    detail = describe_roster_violations(rows, RosterLimits(min=11, max=20))

    assert "«Dentro»" not in detail
    assert "«Fuera»" in detail


def test_detail_never_includes_personal_data() -> None:
    detail = describe_roster_violations(
        [RosterTeamCount(team_id=uuid4(), team_name="Equipo", count=3)],
        RosterLimits(min=11, max=20),
    )

    # Only the team name and numbers: no document, email or player name fields.
    assert "DNI" not in detail and "@" not in detail
    assert "documento" not in detail.lower()
    assert ROSTER_SIZE_OUT_OF_RANGE == "ROSTER_SIZE_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# Active roster counting (opt-in)
# ---------------------------------------------------------------------------


async def _create_tournament(session, organization_id: UUID) -> UUID:
    result = await session.execute(
        text("""
            INSERT INTO tournaments
                (organization_id, name, season, start_date, status, current_draft_config)
            VALUES (:organization_id, :name, :season, '2026-01-01', 'draft', '{}'::jsonb)
            RETURNING id
        """),
        {
            "organization_id": str(organization_id),
            "name": f"Roster limits {uuid4().hex[:8]}",
            "season": "2026",
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
            "name": f"Equipo {uuid4().hex[:6]}",
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


async def _insert_roster(
    session,
    tenant: TenantContext,
    tournament_id: UUID,
    team_id: UUID,
    *,
    dorsal_number: int,
    is_active: bool = True,
) -> UUID:
    player_id = await insert_player(session, tenant.organization_id)
    result = await session.execute(
        text("""
            INSERT INTO rosters
                (organization_id, tournament_id, team_id, player_id, dorsal_number,
                 valid_from, eligible_from)
            VALUES (
                :organization_id, :tournament_id, :team_id, :player_id, :dorsal_number,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            RETURNING id
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
            "player_id": str(player_id),
            "dorsal_number": dorsal_number,
        },
    )
    roster_id = result.scalar_one()
    if not is_active:
        # ``is_active`` is only granted for UPDATE, never for INSERT.
        await session.execute(
            text("UPDATE rosters SET is_active = FALSE WHERE id = :id"),
            {"id": str(roster_id)},
        )
    return player_id


async def test_count_only_counts_active_rows_of_the_tournament(
    db_session, tenant_factory
) -> None:
    tenant = await tenant_factory("Límites A")
    tournament_id = await _create_tournament(db_session, tenant.organization_id)
    other_tournament_id = await _create_tournament(db_session, tenant.organization_id)
    team_id = await _register_team(db_session, tenant.organization_id, tournament_id)
    other_team_id = await _register_team(
        db_session, tenant.organization_id, tournament_id
    )
    other_tournament_team_id = await _register_team(
        db_session, tenant.organization_id, other_tournament_id
    )

    await _insert_roster(
        db_session, tenant, tournament_id, team_id, dorsal_number=1
    )
    await _insert_roster(
        db_session, tenant, tournament_id, team_id, dorsal_number=2
    )
    await _insert_roster(
        db_session,
        tenant,
        tournament_id,
        team_id,
        dorsal_number=3,
        is_active=False,
    )
    await _insert_roster(
        db_session, tenant, other_tournament_id, other_tournament_team_id, dorsal_number=4
    )

    await set_tenant_context(db_session, tenant)
    counts = await count_active_roster_players_by_team(
        db_session,
        tenant.organization_id,
        tournament_id,
        [team_id, other_team_id],
    )

    by_team = {row.team_id: row.count for row in counts}
    assert by_team == {team_id: 2, other_team_id: 0}
    assert all(isinstance(row.team_name, str) and row.team_name for row in counts)


async def test_count_is_isolated_by_organization(db_session, tenant_factory) -> None:
    first = await tenant_factory("Aislamiento A")
    first_tournament = await _create_tournament(db_session, first.organization_id)
    first_team = await _register_team(
        db_session, first.organization_id, first_tournament
    )
    await _insert_roster(
        db_session, first, first_tournament, first_team, dorsal_number=1
    )

    second = await tenant_factory("Aislamiento B")
    second_tournament = await _create_tournament(db_session, second.organization_id)
    second_team = await _register_team(
        db_session, second.organization_id, second_tournament
    )
    await _insert_roster(
        db_session, second, second_tournament, second_team, dorsal_number=1
    )

    # The RLS context belongs to the second organization: the first one's rows
    # are not visible even when they are asked for explicitly.
    await set_tenant_context(db_session, second)
    foreign = await count_active_roster_players_by_team(
        db_session, first.organization_id, first_tournament, [first_team]
    )
    assert foreign == []

    own = await count_active_roster_players_by_team(
        db_session, second.organization_id, second_tournament, [second_team]
    )
    assert [(row.team_id, row.count) for row in own] == [(second_team, 1)]

    # And the other way around once the context returns to the first tenant.
    await set_tenant_context(db_session, first)
    back = await count_active_roster_players_by_team(
        db_session, first.organization_id, first_tournament, [first_team, second_team]
    )
    assert [(row.team_id, row.count) for row in back] == [(first_team, 1)]
