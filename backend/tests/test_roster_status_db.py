"""Logical retirement and reactivation of a roster player (RF-051, RL-1, RA-1).

``PATCH /tournaments/{id}/rosters/{roster_id}/status`` changes ``is_active``
only: the row, the player and everything recorded about them stay untouched.
Both directions answer with the **same** model, the one of the roster listing
(``roster_id``, ``player_id``, ``team_id``, ``first_name``, ``last_name``,
``dorsal_number``, ``age``, ``photo_url``, ``photo_consent``, ``is_active``).

The rules of the decision (RC-1, RL-1, RA-1):

* **retire** (``is_active: false``) is always allowed. It is the single
  exception to the roster lock because it only removes players, so it works
  with the matchday lock active, with the team already enrolled and with an
  open match, and it never deletes or rewrites anything;
* **reactivate** (``is_active: true``) behaves like a registration: it answers
  the same ``409`` of the matchday lock, the duplicate conflict of
  ``uq_active_player_tournament`` (the message the API already uses for
  duplicates) and names the dorsal when another active player of the same team
  already holds it (``uq_active_roster_dorsal``);
* the same value is **idempotent** (``200``, no write);
* a roster of another tournament or another organization is **404**;
* there is **no audit entry**: the action is not one of the audited ones.

Every test runs inside the rolled-back ``db_session`` fixture; the route keeps
its ``async with db.begin()`` contract through a savepoint, exactly like the
invitation and match-operation suites.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import AuthContext
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.tournaments.router import (
    ROSTER_LOCK_DETAIL,
    update_roster_player_status,
)
from app.modules.tournaments.schemas import UpdateRosterStatusRequest
from db_helpers import (
    TenantContext,
    create_tenant_owner,
    insert_player,
    set_tenant_context,
)

LIST_KEYS = {
    "roster_id",
    "player_id",
    "team_id",
    "first_name",
    "last_name",
    "dorsal_number",
    "photo_url",
    "photo_consent",
    "is_active",
    "age",
}

# The 409 detail the API already uses for a duplicated roster row (RC-1).
DUPLICATES_DETAIL = "El documento, dorsal o jugador ya está registrado en el torneo"

MATCHDAY = 2


def context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


class _NestedSession:
    """Run a route that opens its own transaction as a savepoint of the test.

    The route keeps its ``async with db.begin()`` contract, the statements land
    in the test transaction and the fixture rollback removes everything. The
    SQL text is recorded so the idempotent path can be proved not to write.
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self.statements: list[str] = []

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def execute(self, statement, params=None):
        self.statements.append(" ".join(str(statement).split()))
        return await self._session.execute(statement, params)

    def writes(self) -> list[str]:
        return [
            sql
            for sql in self.statements
            if sql.upper().startswith(("INSERT", "UPDATE", "DELETE"))
        ]


@dataclass
class Setup:
    tenant: TenantContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    team_id: UUID
    other_team_id: UUID


async def _create_tournament(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    config: dict | None = None,
    label: str = "H4T06",
) -> tuple[UUID, UUID, UUID]:
    stored = json.dumps(config or dict(DEFAULT_RULES_CONFIG))
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', '2026-01-01', 'draft',
                     CAST(:config AS jsonb))
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"{label} {tenant.organization_id.hex[:8]}",
                "config": stored,
            },
        )
    ).scalar_one()
    version_id = (
        await session.execute(
            text("""
                INSERT INTO tournament_versions
                    (organization_id, tournament_id, version_number, rules_config,
                     phase_config, status, created_by_member_id)
                VALUES
                    (:organization_id, :tournament_id, 1, CAST(:config AS jsonb),
                     '{}'::jsonb, 'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "member_id": str(tenant.member_id),
                "config": stored,
            },
        )
    ).scalar_one()
    stage_id = (
        await session.execute(
            text("""
                INSERT INTO stages
                    (organization_id, tournament_id, tournament_version_id, name,
                     stage_type, stage_order)
                VALUES
                    (:organization_id, :tournament_id, :version_id, 'Grupo A',
                     'round_robin', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
            },
        )
    ).scalar_one()
    return tournament_id, version_id, stage_id


async def _register_team(
    session: AsyncSession,
    tenant: TenantContext,
    tournament_id: UUID,
    *,
    name: str,
) -> UUID:
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": name,
                "short_code": f"H{uuid4().hex[:5].upper()}",
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    return team_id


async def _insert_roster(
    session: AsyncSession,
    tenant: TenantContext,
    tournament_id: UUID,
    team_id: UUID,
    player_id: UUID,
    *,
    dorsal_number: int,
    is_active: bool = True,
) -> UUID:
    """Insert one roster row; ``is_active`` is set with its own UPDATE grant."""

    roster_id = (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (id, organization_id, tournament_id, team_id, player_id, dorsal_number,
                     valid_from, eligible_from)
                VALUES
                    (:id, :organization_id, :tournament_id, :team_id, :player_id,
                     :dorsal_number, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "id": str(uuid4()),
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "dorsal_number": dorsal_number,
            },
        )
    ).scalar_one()
    if not is_active:
        # ``is_active`` is granted for UPDATE only (init/01).
        await session.execute(
            text("UPDATE rosters SET is_active = FALSE WHERE id = :roster_id"),
            {"roster_id": str(roster_id)},
        )
    return roster_id


async def _add_player(
    session: AsyncSession,
    setup: Setup,
    *,
    first_name: str = "Jugador",
    dorsal_number: int,
    team_id: UUID | None = None,
    is_active: bool = True,
    player_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    """Insert one player and one roster row; return ``(player_id, roster_id)``."""

    if player_id is None:
        player_id = await insert_player(
            session,
            setup.tenant.organization_id,
            first_name=first_name,
            last_name="H4T06",
            reference_year=2026,
        )
    roster_id = await _insert_roster(
        session,
        setup.tenant,
        setup.tournament_id,
        team_id or setup.team_id,
        player_id,
        dorsal_number=dorsal_number,
        is_active=is_active,
    )
    return player_id, roster_id


async def _seeded_setup(
    session: AsyncSession, tenant: TenantContext, *, label: str = "H4T06"
) -> Setup:
    tournament_id, version_id, stage_id = await _create_tournament(
        session, tenant, label=label
    )
    team_id = await _register_team(
        session, tenant, tournament_id, name=f"Alfa {label}"
    )
    other_team_id = await _register_team(
        session, tenant, tournament_id, name=f"Bravo {label}"
    )
    return Setup(tenant, tournament_id, version_id, stage_id, team_id, other_team_id)


async def _assign_to_stage(
    session: AsyncSession, setup: Setup, team_id: UUID
) -> None:
    await session.execute(
        text("""
            INSERT INTO stage_teams
                (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
            VALUES
                (:organization_id, :tournament_id, :version_id, :stage_id, :team_id)
        """),
        {
            "organization_id": str(setup.tenant.organization_id),
            "tournament_id": str(setup.tournament_id),
            "version_id": str(setup.version_id),
            "stage_id": str(setup.stage_id),
            "team_id": str(team_id),
        },
    )


async def _activate_roster_lock(session: AsyncSession, setup: Setup) -> None:
    """Publish the version with the matchday lock and confirm its first matchday."""

    config = dict(DEFAULT_RULES_CONFIG)
    config["roster_lock_matchday"] = MATCHDAY
    await _assign_to_stage(session, setup, setup.team_id)
    await _assign_to_stage(session, setup, setup.other_team_id)
    # One confirmed match of the reference matchday in the first stage: the
    # lock is active (RF-023/RF-028), the same rule the registration uses.
    # The calendar is written while the version is still a draft: the structure
    # of a published version is immutable.
    await session.execute(
        text("""
            INSERT INTO matches
                (organization_id, tournament_id, tournament_version_id, stage_id,
                 home_team_id, away_team_id, matchday, status, resolution_type,
                 result_confirmed, home_score_regular, away_score_regular,
                 home_score, away_score)
            VALUES
                (:organization_id, :tournament_id, :version_id, :stage_id,
                 :home_team_id, :away_team_id, :matchday, 'finished', 'regular',
                 TRUE, 0, 0, 0, 0)
        """),
        {
            "organization_id": str(setup.tenant.organization_id),
            "tournament_id": str(setup.tournament_id),
            "version_id": str(setup.version_id),
            "stage_id": str(setup.stage_id),
            "home_team_id": str(setup.team_id),
            "away_team_id": str(setup.other_team_id),
            "matchday": MATCHDAY,
        },
    )
    await session.execute(
        text("""
            UPDATE tournament_versions
            SET rules_config = CAST(:config AS jsonb), status = 'published'
            WHERE id = :version_id
        """),
        {"version_id": str(setup.version_id), "config": json.dumps(config)},
    )


async def _status(
    session: AsyncSession,
    setup: Setup,
    roster_id: UUID,
    is_active: bool,
    *,
    tournament_id: UUID | None = None,
    tenant: TenantContext | None = None,
) -> tuple[dict, _NestedSession]:
    api = _NestedSession(session)
    response = await update_roster_player_status(
        tournament_id or setup.tournament_id,
        roster_id,
        UpdateRosterStatusRequest(is_active=is_active),
        context_for(tenant or setup.tenant),
        api,
    )
    return response, api


async def _roster_state(session: AsyncSession, roster_id: UUID) -> dict:
    row = (
        await session.execute(
            text("SELECT is_active FROM rosters WHERE id = :roster_id"),
            {"roster_id": str(roster_id)},
        )
    ).mappings().one_or_none()
    assert row is not None, "la fila del roster no debe borrarse"
    return dict(row)


async def _audit_count(session: AsyncSession, tenant: TenantContext) -> int:
    return (
        await session.execute(
            text("""
                SELECT count(*) FROM administrative_audit_logs
                WHERE organization_id = :organization_id
            """),
            {"organization_id": str(tenant.organization_id)},
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Retire: the list model, the row is kept and the exception to the lock (RL-1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retiring_a_player_returns_the_list_model_and_keeps_the_row(
    db_session, tenant_factory
):
    tenant = await tenant_factory("H4T06 retire")
    setup = await _seeded_setup(db_session, tenant)
    player_id, roster_id = await _add_player(db_session, setup, dorsal_number=10)
    # The retirement is allowed with the team already enrolled in a stage.
    await _assign_to_stage(db_session, setup, setup.team_id)
    await db_session.commit()

    response, _ = await _status(db_session, setup, roster_id, False)

    assert set(response) == LIST_KEYS
    assert UUID(str(response["roster_id"])) == roster_id
    assert UUID(str(response["player_id"])) == player_id
    assert UUID(str(response["team_id"])) == setup.team_id
    assert response["dorsal_number"] == 10
    assert response["is_active"] is False
    assert isinstance(response["age"], int)
    # The row is not deleted and the player and the enrolment stay.
    assert (await _roster_state(db_session, roster_id))["is_active"] is False
    assert (
        await db_session.execute(
            text("SELECT 1 FROM players WHERE id = :player_id"),
            {"player_id": str(player_id)},
        )
    ).scalar_one_or_none() == 1
    assert (
        await db_session.execute(
            text("""
                SELECT 1 FROM tournament_teams
                WHERE tournament_id = :tournament_id AND team_id = :team_id
            """),
            {
                "tournament_id": str(setup.tournament_id),
                "team_id": str(setup.team_id),
            },
        )
    ).scalar_one_or_none() == 1


@pytest.mark.asyncio
async def test_retiring_with_the_roster_lock_active_is_the_single_exception(
    db_session, tenant_factory
):
    tenant = await tenant_factory("H4T06 retire locked")
    setup = await _seeded_setup(db_session, tenant)
    _, roster_id = await _add_player(db_session, setup, dorsal_number=4)
    await _activate_roster_lock(db_session, setup)
    await db_session.commit()

    response, api = await _status(db_session, setup, roster_id, False)

    assert response["is_active"] is False
    assert (await _roster_state(db_session, roster_id))["is_active"] is False
    # RL-1: the retirement writes the activity, nothing else.
    assert all("administrative_audit_logs" not in sql for sql in api.statements)


# ---------------------------------------------------------------------------
# Reactivate: the same list model and a write like a registration (RA-1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactivating_a_player_returns_the_list_model(db_session, tenant_factory):
    tenant = await tenant_factory("H4T06 reactivate")
    setup = await _seeded_setup(db_session, tenant)
    player_id, roster_id = await _add_player(
        db_session, setup, dorsal_number=7, is_active=False
    )
    await db_session.commit()

    response, _ = await _status(db_session, setup, roster_id, True)

    assert set(response) == LIST_KEYS
    assert UUID(str(response["player_id"])) == player_id
    assert response["dorsal_number"] == 7
    assert response["is_active"] is True
    assert (await _roster_state(db_session, roster_id))["is_active"] is True


@pytest.mark.asyncio
async def test_reactivating_with_the_roster_lock_active_is_the_registration_409(
    db_session, tenant_factory
):
    tenant = await tenant_factory("H4T06 reactivate locked")
    setup = await _seeded_setup(db_session, tenant)
    _, roster_id = await _add_player(
        db_session, setup, dorsal_number=5, is_active=False
    )
    await _activate_roster_lock(db_session, setup)
    await db_session.commit()

    with pytest.raises(Exception) as error:
        await _status(db_session, setup, roster_id, True)

    assert getattr(error.value, "status_code", None) == 409
    # The exact 409 of the registration: same text, without new fields.
    assert error.value.detail == ROSTER_LOCK_DETAIL.format(matchday=MATCHDAY)
    assert (await _roster_state(db_session, roster_id))["is_active"] is False


# ---------------------------------------------------------------------------
# Idempotency: the same value answers 200 without writing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_same_value_is_idempotent_and_writes_nothing(db_session, tenant_factory):
    tenant = await tenant_factory("H4T06 idempotent")
    setup = await _seeded_setup(db_session, tenant)
    _, roster_id = await _add_player(db_session, setup, dorsal_number=9)
    await db_session.commit()

    first, _ = await _status(db_session, setup, roster_id, False)
    second, api = await _status(db_session, setup, roster_id, False)

    assert first["is_active"] is False
    assert second["is_active"] is False
    assert api.writes() == []
    assert (await _roster_state(db_session, roster_id))["is_active"] is False

    first, _ = await _status(db_session, setup, roster_id, True)
    second, api = await _status(db_session, setup, roster_id, True)

    assert first["is_active"] is True
    assert second["is_active"] is True
    assert api.writes() == []
    assert (await _roster_state(db_session, roster_id))["is_active"] is True


# ---------------------------------------------------------------------------
# Isolation: another tournament or another organization is 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_roster_of_another_organization_or_tournament_is_404(
    db_session, tenant_factory
):
    first = await tenant_factory("H4T06 isolation first")
    first_setup = await _seeded_setup(db_session, first, label="Uno")
    _, first_roster = await _add_player(db_session, first_setup, dorsal_number=3)

    second = await tenant_factory("H4T06 isolation second")
    second_setup = await _seeded_setup(db_session, second, label="Dos")
    _, second_roster = await _add_player(db_session, second_setup, dorsal_number=3)
    await db_session.commit()

    # First organization asks for the roster of the second one, through its own
    # tournament: no row is visible and nothing is written.
    with pytest.raises(Exception) as error:
        await _status(db_session, first_setup, second_roster, False)
    assert getattr(error.value, "status_code", None) == 404
    assert (await _roster_state(db_session, second_roster))["is_active"] is True

    # … and through the tournament of the other organization.
    with pytest.raises(Exception) as error:
        await _status(db_session, first_setup, second_roster, False, tournament_id=second_setup.tournament_id)
    assert getattr(error.value, "status_code", None) == 404

    # A roster of this organization but of another tournament is also 404.
    third = await tenant_factory("H4T06 isolation third")
    third_setup = await _seeded_setup(db_session, third, label="Tres")
    _, third_roster = await _add_player(db_session, third_setup, dorsal_number=3)
    await db_session.commit()
    with pytest.raises(Exception) as error:
        await _status(db_session, first_setup, third_roster, False)
    assert getattr(error.value, "status_code", None) == 404
    assert (await _roster_state(db_session, third_roster))["is_active"] is True

    # The own roster still works: the isolation is on the row, not on the route.
    response, _ = await _status(db_session, first_setup, first_roster, False)
    assert response["is_active"] is False


# ---------------------------------------------------------------------------
# Reactivation conflicts: an active row of the same player, a busy dorsal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reactivating_a_player_with_another_active_row_is_the_duplicates_409(
    db_session, tenant_factory
):
    tenant = await tenant_factory("H4T06 duplicate player")
    setup = await _seeded_setup(db_session, tenant)
    player_id, retired_roster = await _add_player(
        db_session, setup, dorsal_number=8, is_active=False
    )
    # The same player already has an active row in the tournament (another team).
    _, active_roster = await _add_player(
        db_session,
        setup,
        dorsal_number=11,
        team_id=setup.other_team_id,
        player_id=player_id,
    )
    await db_session.commit()

    with pytest.raises(Exception) as error:
        await _status(db_session, setup, retired_roster, True)

    assert getattr(error.value, "status_code", None) == 409
    # RC-1: the conflict error the API already uses for duplicates, unchanged.
    assert error.value.detail == DUPLICATES_DETAIL
    assert (await _roster_state(db_session, retired_roster))["is_active"] is False
    assert (await _roster_state(db_session, active_roster))["is_active"] is True


@pytest.mark.asyncio
async def test_reactivating_a_busy_dorsal_names_the_dorsal(db_session, tenant_factory):
    tenant = await tenant_factory("H4T06 busy dorsal")
    setup = await _seeded_setup(db_session, tenant)
    _, retired_roster = await _add_player(
        db_session, setup, dorsal_number=9, is_active=False
    )
    # Another player of the same team holds the dorsal while active.
    _, active_roster = await _add_player(db_session, setup, dorsal_number=9)
    await db_session.commit()

    with pytest.raises(Exception) as error:
        await _status(db_session, setup, retired_roster, True)

    assert getattr(error.value, "status_code", None) == 409
    assert "9" in error.value.detail
    assert (await _roster_state(db_session, retired_roster))["is_active"] is False
    assert (await _roster_state(db_session, active_roster))["is_active"] is True


# ---------------------------------------------------------------------------
# History: lineups and events are not rewritten, no audit, internal projection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_retirement_keeps_lineups_and_events_untouched(
    db_session, tenant_factory
):
    tenant = await tenant_factory("H4T06 history")
    setup = await _seeded_setup(db_session, tenant)
    player_id, roster_id = await _add_player(db_session, setup, dorsal_number=6)
    await _assign_to_stage(db_session, setup, setup.team_id)
    await _assign_to_stage(db_session, setup, setup.other_team_id)
    match_id = (
        await db_session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'scheduled', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(setup.tournament_id),
                "version_id": str(setup.version_id),
                "stage_id": str(setup.stage_id),
                "home_team_id": str(setup.team_id),
                "away_team_id": str(setup.other_team_id),
            },
        )
    ).scalar_one()
    segment_id = (
        await db_session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start)
                VALUES (:organization_id, :match_id, 1, 0)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one()
    await db_session.execute(
        text("""
            INSERT INTO match_rosters
                (organization_id, match_id, roster_id, player_id, team_id,
                 tournament_id, role, is_valid)
            VALUES
                (:organization_id, :match_id, :roster_id, :player_id, :team_id,
                 :tournament_id, 'starter', TRUE)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "roster_id": str(roster_id),
            "player_id": str(player_id),
            "team_id": str(setup.team_id),
            "tournament_id": str(setup.tournament_id),
        },
    )
    await db_session.execute(
        text("""
            INSERT INTO match_events
                (organization_id, match_id, segment_id, team_id, player_id,
                 event_type, minute, client_event_id)
            VALUES
                (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                 'goal', 12, :client_event_id)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "segment_id": str(segment_id),
            "team_id": str(setup.team_id),
            "player_id": str(player_id),
            "client_event_id": f"h4t06-{roster_id.hex[:12]}",
        },
    )
    await db_session.commit()

    lineup_before = (
        await db_session.execute(
            text("SELECT to_jsonb(mr) FROM match_rosters mr WHERE match_id = :match_id"),
            {"match_id": str(match_id)},
        )
    ).scalar_one()
    events_before = (
        await db_session.execute(
            text("SELECT to_jsonb(me) FROM match_events me WHERE match_id = :match_id"),
            {"match_id": str(match_id)},
        )
    ).scalar_one()

    response, _ = await _status(db_session, setup, roster_id, False)

    assert response["is_active"] is False
    assert (
        await db_session.execute(
            text("SELECT to_jsonb(mr) FROM match_rosters mr WHERE match_id = :match_id"),
            {"match_id": str(match_id)},
        )
    ).scalar_one() == lineup_before
    assert (
        await db_session.execute(
            text("SELECT to_jsonb(me) FROM match_events me WHERE match_id = :match_id"),
            {"match_id": str(match_id)},
        )
    ).scalar_one() == events_before


@pytest.mark.asyncio
async def test_the_retirement_and_the_reactivation_write_no_audit_entry(
    db_session, tenant_factory
):
    tenant = await tenant_factory("H4T06 no audit")
    setup = await _seeded_setup(db_session, tenant)
    _, roster_id = await _add_player(db_session, setup, dorsal_number=2)
    await db_session.commit()

    assert await _audit_count(db_session, tenant) == 0

    await _status(db_session, setup, roster_id, False)
    assert await _audit_count(db_session, tenant) == 0

    await _status(db_session, setup, roster_id, True)
    assert await _audit_count(db_session, tenant) == 0


@pytest.mark.asyncio
async def test_the_internal_projection_stops_listing_the_retired_player(
    db_session, tenant_factory
):
    tenant = await tenant_factory("H4T06 projection")
    setup = await _seeded_setup(db_session, tenant)
    player_id, roster_id = await _add_player(db_session, setup, dorsal_number=1)
    # The internal projection only covers public tournaments.
    await db_session.execute(
        text("""
            UPDATE tournament_versions
            SET status = 'published', published_at = CURRENT_TIMESTAMP
            WHERE id = :version_id
        """),
        {"version_id": str(setup.version_id)},
    )
    await db_session.execute(
        text("""
            UPDATE tournaments
            SET status = 'published', published_version_id = :version_id
            WHERE id = :tournament_id
        """),
        {
            "tournament_id": str(setup.tournament_id),
            "version_id": str(setup.version_id),
        },
    )
    await db_session.commit()

    async def projected() -> bool:
        return bool(
            (
                await db_session.execute(
                    text("""
                        SELECT 1 FROM v_public_tournament_players
                        WHERE tournament_id = :tournament_id
                          AND player_id = :player_id
                    """),
                    {
                        "tournament_id": str(setup.tournament_id),
                        "player_id": str(player_id),
                    },
                )
            ).scalar_one_or_none()
        )

    assert await projected() is True

    await _status(db_session, setup, roster_id, False)
    assert await projected() is False

    await _status(db_session, setup, roster_id, True)
    assert await projected() is True


# ---------------------------------------------------------------------------
# Contract: one new PATCH route with the list model
# ---------------------------------------------------------------------------


def test_the_status_route_is_registered_as_a_patch_with_the_list_model():
    from app.main import api

    schema = api.openapi()
    path = "/api/v1/tournaments/{tournament_id}/rosters/{roster_id}/status"
    assert path in schema["paths"]
    operation = schema["paths"][path]["patch"]

    request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request = schema["components"]["schemas"][request_ref.rsplit("/", 1)[1]]
    assert request["required"] == ["is_active"]
    assert request["properties"]["is_active"]["type"] == "boolean"

    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert response_ref.endswith("/RosterPlayerListResponse")
    listed = schema["components"]["schemas"]["RosterPlayerListResponse"]
    # The one and only model of the answer: the roster listing.
    assert set(listed["properties"]) == LIST_KEYS
    assert "age" in listed["required"]
