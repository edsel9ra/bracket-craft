"""Opt-in PostgreSQL coverage of the roster-size block (RF-045, RF-050, BX-1).

Enrolling a team in a stage (``POST /tournaments/{id}/stages/{stage_id}/teams``)
checks the active roster of every team of the batch before inserting a single
row: one team out of range rejects the whole batch with **409**
``ROSTER_SIZE_OUT_OF_RANGE`` and the deterministic ``detail`` of H4-T02. The
effective limits come from the rules configuration of the stage's version; with
no limits (``0`` or absent keys) no check runs and the current ``201``/``200``
behaviour is kept.

``POST /tournaments/{id}/teams`` and ``POST /tournaments/{id}/teams/bulk`` with
a target ``stage_id`` enrol the new team in the stage, so they answer the same
409 before creating anything: a new team has an empty roster, so a minimum
above zero rejects the create. Without ``stage_id`` the create is not affected.

Opening a match is creating its **first** segment (``POST
/matches/{id}/segments`` with the match still without segments, AP-1): both
participant teams are checked with the same limits out of the match's version
and the same 409 detail, and a rejected opening writes nothing and leaves the
match status untouched. Later segments are not an opening and do not revalidate
the size. The validation order of the opening is the one of plan §5.3:
resolution enabled (409) → roster size (409) → minute range (422) → write.

Each case builds a throwaway database at schema 023, because the route owns the
transaction it writes in: a rejected batch must roll back and the assertions
read the committed state from an independent session.

Two closing cases cover the rest of criterion 39 (H-7):

* a **published** version stored before the three keys existed keeps the current
  behaviour (no limit): enrolling in a draft clone and opening a match of the
  published version succeed, and reading it —versions list, limits resolution,
  enrollment— never materializes the defaults into the stored ``rules_config``;
* **editing the roster is never rejected by size**: the individual entry, the
  CSV import, the photo consent and the photo upload succeed with a roster out
  of range, because the size block only acts on enrollment, team creation with
  a target stage and the opening of the match.
"""

from __future__ import annotations

import io
import json
import secrets
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import Response, UploadFile
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from starlette.requests import Request

import app.modules.tournaments.photos as photos_module
import app.modules.tournaments.router as tournaments_router
from app.core.storage import SignedUrls
from app.core.tenancy import AuthContext
from app.main import api
from app.modules.matches.errors import ResolutionNotEnabled
from app.modules.matches.router import create_match_segment
from app.modules.matches.schemas import CreateMatchSegmentRequest
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.tournaments.roster_import import ImportedRosterRow
from app.modules.tournaments.roster_status import (
    ROSTER_SIZE_OUT_OF_RANGE,
    RosterSizeOutOfRange,
)
from app.modules.tournaments.router import (
    assign_stage_teams,
    create_roster_player,
    create_roster_players_bulk,
    create_tournament_team,
    create_tournament_teams_bulk,
    list_versions,
    update_roster_photo_consent,
    upload_roster_player_photo,
)
from app.modules.tournaments.schemas import (
    AssignStageTeamsRequest,
    BulkTournamentTeamItem,
    BulkTournamentTeamRequest,
    CreateRosterPlayerRequest,
    CreateTournamentTeamRequest,
    UpdatePhotoConsentRequest,
)
from db_helpers import (
    TenantContext,
    create_tenant_owner,
    insert_player,
    set_tenant_context,
)
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)

DETAIL_HEADER = "Plantilla fuera de rango: "


def rules_config(*, minimum: int = 0, maximum: int = 0) -> dict:
    """Default rules with the two roster limits declared (``0`` = no limit)."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["min_players_per_team"] = minimum
    config["max_players_per_team"] = maximum
    return config


def rules_config_without_limits() -> dict:
    """Stored configuration written before the keys existed."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    config.pop("min_players_per_team", None)
    config.pop("max_players_per_team", None)
    return config


def context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


@asynccontextmanager
async def committed_application(database_admin_url):
    """Throwaway database at 023 plus a dedicated role that inherits the app role."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc012_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    engine = None
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1, last=23)
        await admin.execute(
            f"""
            CREATE ROLE "{role_name}" LOGIN PASSWORD '{role_password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            """
        )
        await admin.execute(f'GRANT bracket_app TO "{role_name}"')
        parsed = make_url(database_admin_url)
        app_url = (
            f"postgresql+asyncpg://{role_name}:{role_password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
        engine = create_async_engine(app_url, pool_pre_ping=True)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.close()
        await drop_database(database_admin_url, database)
        cleaner = await connect(database_admin_url)
        try:
            await cleaner.execute(f'DROP ROLE IF EXISTS "{role_name}"')
        finally:
            await cleaner.close()


class StageSetup:
    """Committed tournament, draft version, stage and its registered teams."""

    def __init__(self, tenant: TenantContext, tournament_id: UUID, stage_id: UUID, teams):
        self.tenant = tenant
        self.context = context_for(tenant)
        self.tournament_id = tournament_id
        self.stage_id = stage_id
        self.teams: dict[str, UUID] = teams


async def _create_tournament(session, tenant: TenantContext, *, config: dict) -> tuple[UUID, UUID]:
    payload = json.dumps(config)
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
                "name": f"H4T03 {uuid4().hex[:8]}",
                "config": payload,
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
                "config": payload,
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
    return tournament_id, stage_id


async def _register_team(
    session, tenant: TenantContext, tournament_id: UUID, *, name: str
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


async def _add_active_players(
    session,
    tenant: TenantContext,
    tournament_id: UUID,
    team_id: UUID,
    *,
    count: int,
    start: int = 0,
) -> None:
    for index in range(start, start + count):
        player_id = await insert_player(
            session,
            tenant.organization_id,
            first_name=f"H4T03{index}",
            last_name=team_id.hex[:4],
            reference_year=2026,
        )
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id,
                     :dorsal_number, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "dorsal_number": index + 1,
            },
        )


async def seeded_stage(
    engine, *, config: dict, rosters: dict[str, int]
) -> StageSetup:
    """Create and commit one draft stage whose teams have the given active rosters."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="H4T03 committed")
        await set_tenant_context(session, tenant)
        tournament_id, stage_id = await _create_tournament(
            session, tenant, config=config
        )
        teams: dict[str, UUID] = {}
        for name, active_players in rosters.items():
            team_id = await _register_team(
                session, tenant, tournament_id, name=name
            )
            await _add_active_players(
                session,
                tenant,
                tournament_id,
                team_id,
                count=active_players,
            )
            teams[name] = team_id
        await session.commit()
    return StageSetup(tenant, tournament_id, stage_id, teams)


async def enroll(
    engine,
    setup: StageSetup,
    team_ids,
    response: Response | None = None,
) -> dict:
    """Run the route in its own session, exactly as a request does."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await assign_stage_teams(
            setup.tournament_id,
            setup.stage_id,
            AssignStageTeamsRequest(team_ids=list(team_ids)),
            response if response is not None else Response(),
            setup.context,
            session,
        )


async def stage_team_ids(engine, setup: StageSetup) -> set[UUID]:
    """Read the committed assignments from an independent session."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        rows = await session.execute(
            text("""
                SELECT team_id
                FROM stage_teams
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
                  AND stage_id = :stage_id
            """),
            {
                "organization_id": str(setup.tenant.organization_id),
                "tournament_id": str(setup.tournament_id),
                "stage_id": str(setup.stage_id),
            },
        )
        return set(rows.scalars().all())


async def pre_assign(engine, setup: StageSetup, team_id: UUID) -> None:
    """Insert one assignment directly so the batch is entirely idempotent."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        await session.execute(
            text("""
                INSERT INTO stage_teams
                    (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
                VALUES (
                    :organization_id, :tournament_id,
                    (SELECT tournament_version_id FROM stages WHERE id = :stage_id),
                    :stage_id, :team_id
                )
            """),
            {
                "organization_id": str(setup.tenant.organization_id),
                "tournament_id": str(setup.tournament_id),
                "stage_id": str(setup.stage_id),
                "team_id": str(team_id),
            },
        )
        await session.commit()


async def create_team(
    engine,
    setup: StageSetup,
    *,
    name: str,
    short_code: str,
    stage_id: UUID | None = None,
):
    """Run ``POST /teams`` in its own session, exactly as a request does."""

    payload = CreateTournamentTeamRequest(
        name=name, short_code=short_code, stage_id=stage_id
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await create_tournament_team(
            setup.tournament_id, payload, setup.context, session
        )


async def create_teams_bulk(
    engine,
    setup: StageSetup,
    teams: list[tuple[str, str]],
    *,
    stage_id: UUID | None = None,
):
    """Run ``POST /teams/bulk`` in its own session, exactly as a request does."""

    payload = BulkTournamentTeamRequest(
        teams=[
            BulkTournamentTeamItem(name=name, short_code=short_code)
            for name, short_code in teams
        ],
        stage_id=stage_id,
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await create_tournament_teams_bulk(
            setup.tournament_id, payload, setup.context, session
        )


async def team_names(engine, setup: StageSetup) -> set[str]:
    """Read the committed teams of the organization from an independent session."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        rows = await session.execute(
            text("""
                SELECT name
                FROM teams
                WHERE organization_id = :organization_id
            """),
            {"organization_id": str(setup.tenant.organization_id)},
        )
        return set(rows.scalars().all())


def assert_coded_conflict(error: pytest.ExceptionInfo) -> None:
    assert error.value.status_code == 409
    assert error.value.code == ROSTER_SIZE_OUT_OF_RANGE


# ---------------------------------------------------------------------------
# Inside the range and without limits: the current behaviour is kept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrolling_within_the_range_returns_201_and_enrolls_every_team(
    database_admin_url,
):
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(
            engine, config=config, rosters={"Alfa": 11, "Bravo": 20}
        )
        response = Response()

        result = await enroll(
            engine,
            setup,
            [setup.teams["Alfa"], setup.teams["Bravo"]],
            response,
        )

        assert response.status_code == 201
        assert result["assigned"] == [setup.teams["Alfa"], setup.teams["Bravo"]]
        assert result["already_assigned"] == []
        assert await stage_team_ids(engine, setup) == {
            setup.teams["Alfa"],
            setup.teams["Bravo"],
        }


@pytest.mark.asyncio
async def test_without_limits_the_current_behaviour_is_kept(database_admin_url):
    # A configuration stored before the keys existed: no check at all.
    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(
            engine,
            config=rules_config_without_limits(),
            rosters={"Vacío": 0, "Lleno": 50},
        )
        response = Response()

        result = await enroll(
            engine, setup, [setup.teams["Vacío"], setup.teams["Lleno"]], response
        )

        assert response.status_code == 201
        assert len(result["assigned"]) == 2
        assert len(await stage_team_ids(engine, setup)) == 2


@pytest.mark.asyncio
async def test_explicit_zero_limits_do_not_block(database_admin_url):
    config = rules_config(minimum=0, maximum=0)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(
            engine, config=config, rosters={"Vacío": 0, "Lleno": 50}
        )
        response = Response()

        await enroll(
            engine, setup, [setup.teams["Vacío"], setup.teams["Lleno"]], response
        )

        assert response.status_code == 201
        assert len(await stage_team_ids(engine, setup)) == 2


@pytest.mark.asyncio
async def test_an_entirely_already_assigned_batch_is_still_200(database_admin_url):
    # Over the maximum, but already enrolled: nothing new is written, so the
    # idempotent 200 is kept (RF-045 only blocks new enrolments).
    config = rules_config(minimum=0, maximum=10)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={"Lleno": 15})
        team_id = setup.teams["Lleno"]
        await pre_assign(engine, setup, team_id)
        response = Response()

        result = await enroll(engine, setup, [team_id], response)

        assert response.status_code == 200
        assert result["assigned"] == []
        assert result["already_assigned"] == [team_id]
        assert await stage_team_ids(engine, setup) == {team_id}


# ---------------------------------------------------------------------------
# Out of range: 409 with the code and the deterministic detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrolling_below_the_minimum_returns_the_coded_409(database_admin_url):
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={"Corto": 5})

        with pytest.raises(RosterSizeOutOfRange) as error:
            await enroll(engine, setup, [setup.teams["Corto"]])

        assert_coded_conflict(error)
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Corto»: 5 jugadores activos "
            "(mínimo: 11, máximo: 20)."
        )
        assert await stage_team_ids(engine, setup) == set()


@pytest.mark.asyncio
async def test_enrolling_above_the_maximum_returns_the_coded_409(database_admin_url):
    config = rules_config(minimum=0, maximum=10)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={"Largo": 11})

        with pytest.raises(RosterSizeOutOfRange) as error:
            await enroll(engine, setup, [setup.teams["Largo"]])

        assert_coded_conflict(error)
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Largo»: 11 jugadores activos "
            "(mínimo: sin límite, máximo: 10)."
        )
        assert await stage_team_ids(engine, setup) == set()


@pytest.mark.asyncio
async def test_a_batch_with_one_team_out_of_range_enrolls_nobody(database_admin_url):
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(
            engine, config=config, rosters={"Dentro": 15, "Bajo": 4}
        )

        with pytest.raises(RosterSizeOutOfRange) as error:
            await enroll(
                engine, setup, [setup.teams["Dentro"], setup.teams["Bajo"]]
            )

        assert_coded_conflict(error)
        # Only the violating team is named and the order is deterministic.
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Bajo»: 4 jugadores activos "
            "(mínimo: 11, máximo: 20)."
        )
        # All-or-nothing: the team inside the range is not enrolled either.
        assert await stage_team_ids(engine, setup) == set()


@pytest.mark.asyncio
async def test_the_detail_names_the_violating_teams_by_name(database_admin_url):
    config = rules_config(minimum=11, maximum=0)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(
            engine,
            config=config,
            rosters={"Zulu": 2, "Alfa": 1, "Dentro": 11},
        )

        with pytest.raises(RosterSizeOutOfRange) as error:
            await enroll(
                engine,
                setup,
                [
                    setup.teams["Zulu"],
                    setup.teams["Alfa"],
                    setup.teams["Dentro"],
                ],
            )

        assert_coded_conflict(error)
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Alfa»: 1 jugador activo (mínimo: 11, máximo: sin límite); "
            "«Zulu»: 2 jugadores activos (mínimo: 11, máximo: sin límite)."
        )
        assert await stage_team_ids(engine, setup) == set()


# ---------------------------------------------------------------------------
# Team creation with a target stage: same 409 before creating anything (BX-1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creating_a_team_with_a_target_stage_below_the_minimum_is_rejected(
    database_admin_url,
):
    # A new team starts with an empty roster: with a minimum above zero the
    # create with a target stage cannot satisfy it, so it is rejected before
    # any insert (RF-045, BX-1).
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={})

        with pytest.raises(RosterSizeOutOfRange) as error:
            await create_team(
                engine,
                setup,
                name="Nuevo",
                short_code="NUEVO",
                stage_id=setup.stage_id,
            )

        assert_coded_conflict(error)
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Nuevo»: 0 jugadores activos "
            "(mínimo: 11, máximo: 20)."
        )
        # No team, no tournament team and no stage assignment were written.
        assert await team_names(engine, setup) == set()
        assert await stage_team_ids(engine, setup) == set()


@pytest.mark.asyncio
async def test_creating_a_team_without_a_target_stage_is_not_blocked(
    database_admin_url,
):
    # Without stage_id the team is only registered in the tournament, so the
    # current behaviour is kept even with a minimum above zero (RF-046).
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={})

        result = await create_team(
            engine, setup, name="Suelto", short_code="SUELTO"
        )

        assert result["tournament_id"] == str(setup.tournament_id)
        assert await team_names(engine, setup) == {"Suelto"}
        assert await stage_team_ids(engine, setup) == set()


@pytest.mark.asyncio
async def test_creating_a_team_without_limits_and_a_target_stage_is_created(
    database_admin_url,
):
    config = rules_config(minimum=0, maximum=0)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={})

        result = await create_team(
            engine,
            setup,
            name="Directo",
            short_code="DIRECTO",
            stage_id=setup.stage_id,
        )

        assert await team_names(engine, setup) == {"Directo"}
        assert await stage_team_ids(engine, setup) == {UUID(result["team_id"])}


@pytest.mark.asyncio
async def test_bulk_creation_with_a_target_stage_below_the_minimum_creates_nothing(
    database_admin_url,
):
    config = rules_config(minimum=11, maximum=0)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={})

        with pytest.raises(RosterSizeOutOfRange) as error:
            await create_teams_bulk(
                engine,
                setup,
                [("Zulu", "ZULU"), ("Alfa", "ALFA")],
                stage_id=setup.stage_id,
            )

        assert_coded_conflict(error)
        # The detail is deterministic: sorted by name, whatever the order of
        # the request.
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Alfa»: 0 jugadores activos (mínimo: 11, máximo: sin límite); "
            "«Zulu»: 0 jugadores activos (mínimo: 11, máximo: sin límite)."
        )
        # All-or-nothing: not a single team of the batch was created.
        assert await team_names(engine, setup) == set()
        assert await stage_team_ids(engine, setup) == set()


@pytest.mark.asyncio
async def test_bulk_creation_with_a_target_stage_and_no_minimum_is_created(
    database_admin_url,
):
    # Only a maximum is configured: an empty roster can never exceed it.
    config = rules_config(minimum=0, maximum=10)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(engine, config=config, rosters={})

        result = await create_teams_bulk(
            engine,
            setup,
            [("Alfa", "ALFA"), ("Bravo", "BRAVO")],
            stage_id=setup.stage_id,
        )

        assert result["count"] == 2
        assert await team_names(engine, setup) == {"Alfa", "Bravo"}
        assert await stage_team_ids(engine, setup) == {
            UUID(team["team_id"]) for team in result["teams"]
        }


# ---------------------------------------------------------------------------
# HTTP body: ``detail`` stays a string and ``code`` is additive
# ---------------------------------------------------------------------------


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/tournaments",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
async def test_the_409_body_keeps_detail_and_adds_the_code():
    handler = api.exception_handlers.get(RosterSizeOutOfRange)
    assert handler is not None
    detail = (
        f"{DETAIL_HEADER}«Corto»: 5 jugadores activos (mínimo: 11, máximo: 20)."
    )

    response = await handler(_request(), RosterSizeOutOfRange(detail))

    assert response.status_code == 409
    assert json.loads(response.body) == {
        "detail": detail,
        "code": ROSTER_SIZE_OUT_OF_RANGE,
    }


# ---------------------------------------------------------------------------
# Opening the match: the first segment checks both participants (RF-050, AP-1)
# ---------------------------------------------------------------------------


class MatchSetup:
    """Committed match of a draft version whose two participants have rosters."""

    def __init__(
        self,
        tenant: TenantContext,
        tournament_id: UUID,
        stage_id: UUID,
        match_id: UUID,
        home_team_id: UUID,
        away_team_id: UUID,
    ):
        self.tenant = tenant
        self.context = context_for(tenant)
        self.tournament_id = tournament_id
        self.stage_id = stage_id
        self.match_id = match_id
        self.home_team_id = home_team_id
        self.away_team_id = away_team_id


async def _create_match(
    session,
    tenant: TenantContext,
    tournament_id: UUID,
    stage_id: UUID,
    home_team_id: UUID,
    away_team_id: UUID,
) -> UUID:
    for team_id in (home_team_id, away_team_id):
        await session.execute(
            text("""
                INSERT INTO stage_teams
                    (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
                VALUES
                    (:organization_id, :tournament_id,
                     (SELECT tournament_version_id FROM stages WHERE id = :stage_id),
                     :stage_id, :team_id)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
                "team_id": str(team_id),
            },
        )
    return (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id,
                     (SELECT tournament_version_id FROM stages WHERE id = :stage_id),
                     :stage_id, :home_team_id, :away_team_id, 'scheduled', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "stage_id": str(stage_id),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
            },
        )
    ).scalar_one()


async def seeded_match(
    engine, *, config: dict, home: int, away: int
) -> MatchSetup:
    """Create and commit one match with the given active rosters per team."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="H4T05 committed")
        await set_tenant_context(session, tenant)
        tournament_id, stage_id = await _create_tournament(
            session, tenant, config=config
        )
        home_team_id = await _register_team(session, tenant, tournament_id, name="Alfa")
        away_team_id = await _register_team(session, tenant, tournament_id, name="Bravo")
        await _add_active_players(
            session, tenant, tournament_id, home_team_id, count=home
        )
        await _add_active_players(
            session, tenant, tournament_id, away_team_id, count=away
        )
        match_id = await _create_match(
            session, tenant, tournament_id, stage_id, home_team_id, away_team_id
        )
        await session.commit()
    return MatchSetup(
        tenant, tournament_id, stage_id, match_id, home_team_id, away_team_id
    )


async def open_match(
    engine,
    setup: MatchSetup,
    *,
    segment_number: int = 1,
    minute_start: int = 0,
    resolution_type: str | None = None,
):
    """Run ``POST /matches/{id}/segments`` in its own session, as a request does."""

    payload = CreateMatchSegmentRequest(
        segment_number=segment_number,
        minute_start=minute_start,
        resolution_type=resolution_type,
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await create_match_segment(setup.match_id, payload, setup.context, session)


async def opening_state(engine, setup: MatchSetup) -> dict[str, object]:
    """Match status, segments and counter rows, from an independent session."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        status_value = (
            await session.execute(
                text("SELECT status FROM matches WHERE id = :match_id"),
                {"match_id": str(setup.match_id)},
            )
        ).scalar_one()
        segments = (
            await session.execute(
                text("""
                    SELECT segment_number, minute_start, status
                    FROM match_segments
                    WHERE match_id = :match_id
                    ORDER BY segment_number
                """),
                {"match_id": str(setup.match_id)},
            )
        ).mappings().all()
        team_state = (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM match_segment_team_state
                    WHERE match_id = :match_id
                """),
                {"match_id": str(setup.match_id)},
            )
        ).scalar_one()
    return {
        "status": status_value,
        "segments": [dict(row) for row in segments],
        "team_state": int(team_state),
    }


async def deactivate_players(
    engine, setup: MatchSetup, team_id: UUID, *, count: int
) -> None:
    """Deactivate the last ``count`` active rows of a team (logical retirement)."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        await session.execute(
            text("""
                UPDATE rosters
                SET is_active = FALSE
                WHERE id IN (
                    SELECT id
                    FROM rosters
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND team_id = :team_id
                      AND is_active = TRUE
                    ORDER BY dorsal_number DESC
                    LIMIT :count
                )
            """),
            {
                "organization_id": str(setup.tenant.organization_id),
                "tournament_id": str(setup.tournament_id),
                "team_id": str(team_id),
                "count": count,
            },
        )
        await session.commit()


async def add_players(
    engine, setup: MatchSetup, team_id: UUID, *, count: int, start: int
) -> None:
    """Register more active players on a team (an individual or imported entry)."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = setup.tenant
        await set_tenant_context(session, tenant)
        await _add_active_players(
            session,
            tenant,
            setup.tournament_id,
            team_id,
            count=count,
            start=start,
        )
        await session.commit()


@pytest.mark.asyncio
async def test_opening_below_the_minimum_returns_the_coded_409(database_admin_url):
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=11, away=5)
        before = await opening_state(engine, setup)

        with pytest.raises(RosterSizeOutOfRange) as error:
            await open_match(engine, setup)

        assert_coded_conflict(error)
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Bravo»: 5 jugadores activos "
            "(mínimo: 11, máximo: 20)."
        )
        # No segment, no counter row and the match status is untouched.
        assert await opening_state(engine, setup) == before
        assert before["status"] == "scheduled"
        assert before["segments"] == []
        assert before["team_state"] == 0


@pytest.mark.asyncio
async def test_opening_above_the_maximum_returns_the_coded_409(database_admin_url):
    config = rules_config(minimum=0, maximum=10)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=11, away=10)
        before = await opening_state(engine, setup)

        with pytest.raises(RosterSizeOutOfRange) as error:
            await open_match(engine, setup)

        assert_coded_conflict(error)
        assert error.value.detail == (
            f"{DETAIL_HEADER}«Alfa»: 11 jugadores activos "
            "(mínimo: sin límite, máximo: 10)."
        )
        assert await opening_state(engine, setup) == before
        assert before["status"] == "scheduled"
        assert before["segments"] == []


@pytest.mark.asyncio
async def test_opening_is_allowed_after_adding_players(database_admin_url):
    # Below the minimum: an entry (or an import) fixes the roster and the
    # opening then needs no extra step (RF-050).
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=11, away=5)
        await add_players(engine, setup, setup.away_team_id, count=6, start=5)

        segment = await open_match(engine, setup)

        assert segment["segment_number"] == 1
        assert segment["minute_start"] == 0
        state = await opening_state(engine, setup)
        assert state["status"] == "scheduled"
        assert state["segments"] == [
            {"segment_number": 1, "minute_start": 0, "status": "active"}
        ]
        assert state["team_state"] == 2


@pytest.mark.asyncio
async def test_opening_is_allowed_after_logically_retiring_players(database_admin_url):
    # Above the maximum: logical retirement (the data effect of H4-T06) lowers
    # the active count and the opening is allowed.
    config = rules_config(minimum=0, maximum=10)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=13, away=10)
        await deactivate_players(engine, setup, setup.home_team_id, count=3)

        segment = await open_match(engine, setup)

        assert segment["segment_number"] == 1
        state = await opening_state(engine, setup)
        assert state["segments"] == [
            {"segment_number": 1, "minute_start": 0, "status": "active"}
        ]


@pytest.mark.asyncio
async def test_a_later_segment_does_not_revalidate_the_roster_size(database_admin_url):
    # The opening succeeded inside the range; a later roster change does not
    # stop nor revalidate the match that is already open (RF-050).
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=15, away=15)
        await open_match(engine, setup)
        await add_players(engine, setup, setup.home_team_id, count=6, start=15)

        segment = await open_match(
            engine, setup, segment_number=2, minute_start=45
        )

        assert segment["segment_number"] == 2
        state = await opening_state(engine, setup)
        assert state["segments"] == [
            {"segment_number": 1, "minute_start": 0, "status": "completed"},
            {"segment_number": 2, "minute_start": 45, "status": "active"},
        ]


@pytest.mark.asyncio
async def test_without_roster_limits_the_opening_is_unchanged(database_admin_url):
    # A configuration stored before the keys existed: no check at all.
    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(
            engine, config=rules_config_without_limits(), home=0, away=50
        )

        segment = await open_match(engine, setup)

        assert segment["segment_number"] == 1
        assert len((await opening_state(engine, setup))["segments"]) == 1


@pytest.mark.asyncio
async def test_explicit_zero_limits_do_not_block_the_opening(database_admin_url):
    config = rules_config(minimum=0, maximum=0)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=0, away=50)

        segment = await open_match(engine, setup)

        assert segment["segment_number"] == 1


@pytest.mark.asyncio
async def test_the_resolution_check_comes_before_the_roster_size(database_admin_url):
    # Plan §5.3: an unenabled resolution is the unified 409 even when the
    # roster is also out of range and the minute is out of its range.
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=11, away=5)
        before = await opening_state(engine, setup)

        with pytest.raises(ResolutionNotEnabled) as error:
            await open_match(
                engine, setup, minute_start=200, resolution_type="extra_time"
            )

        assert error.value.status_code == 409
        assert error.value.code == "RESOLUTION_NOT_ENABLED"
        assert await opening_state(engine, setup) == before
        assert before["status"] == "scheduled"
        assert before["segments"] == []


@pytest.mark.asyncio
async def test_the_roster_size_check_comes_before_the_minute(database_admin_url):
    # Plan §5.3: the roster size is a 409 that comes before the 422 of range.
    config = rules_config(minimum=11, maximum=20)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_match(engine, config=config, home=11, away=5)
        before = await opening_state(engine, setup)

        with pytest.raises(RosterSizeOutOfRange) as error:
            await open_match(engine, setup, minute_start=200)

        assert_coded_conflict(error)
        assert await opening_state(engine, setup) == before
        assert before["segments"] == []


# ---------------------------------------------------------------------------
# H-7: a published version stored before the three keys existed (criterion 39)
# ---------------------------------------------------------------------------

LEGACY_KEYS = ("game_format", "min_players_per_team", "max_players_per_team")


def rules_config_before_the_three_keys() -> dict:
    """Configuration written before the format and roster limits existed."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    for key in LEGACY_KEYS:
        config.pop(key, None)
    return config


class PublishedSetup:
    """Published version (legacy config) plus a draft clone and a match."""

    def __init__(
        self,
        tenant: TenantContext,
        tournament_id: UUID,
        published_version_id: UUID,
        published_stage_id: UUID,
        draft_version_id: UUID,
        draft_stage_id: UUID,
        match_id: UUID,
        teams: dict[str, UUID],
    ):
        self.tenant = tenant
        self.context = context_for(tenant)
        self.tournament_id = tournament_id
        self.published_version_id = published_version_id
        self.published_stage_id = published_stage_id
        self.draft_version_id = draft_version_id
        self.draft_stage_id = draft_stage_id
        self.match_id = match_id
        self.teams = teams


async def seeded_published_tournament(engine, *, config: dict) -> PublishedSetup:
    """Publish a version whose stored config lacks the three keys.

    The stage and the match are created while the version is still a draft (the
    structure triggers forbid writing them afterwards) and then the version is
    published, exactly like the publish route does. A draft version is cloned
    from it with the same legacy configuration, because enrollment requires a
    draft version.
    """

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="H7 published")
        await set_tenant_context(session, tenant)
        tournament_id, published_stage_id = await _create_tournament(
            session, tenant, config=config
        )
        published_version_id = (
            await session.execute(
                text("""
                    SELECT id
                    FROM tournament_versions
                    WHERE tournament_id = :tournament_id
                      AND organization_id = :organization_id
                """),
                {
                    "tournament_id": str(tournament_id),
                    "organization_id": str(tenant.organization_id),
                },
            )
        ).scalar_one()
        teams = {
            name: await _register_team(session, tenant, tournament_id, name=name)
            for name in ("Alfa", "Bravo")
        }
        # One team without players and one far above any plausible maximum: with
        # no configured limits neither side is checked.
        await _add_active_players(
            session, tenant, tournament_id, teams["Bravo"], count=50
        )
        match_id = await _create_match(
            session,
            tenant,
            tournament_id,
            published_stage_id,
            teams["Alfa"],
            teams["Bravo"],
        )
        await session.execute(
            text("""
                UPDATE tournament_versions
                SET status = 'published', published_at = CURRENT_TIMESTAMP
                WHERE id = :version_id
            """),
            {"version_id": str(published_version_id)},
        )
        await session.execute(
            text("""
                UPDATE tournaments
                SET status = 'published', published_version_id = :version_id
                WHERE id = :tournament_id
            """),
            {
                "version_id": str(published_version_id),
                "tournament_id": str(tournament_id),
            },
        )
        draft_version_id = (
            await session.execute(
                text("""
                    INSERT INTO tournament_versions
                        (organization_id, tournament_id, version_number, rules_config,
                         phase_config, status, created_by_member_id)
                    VALUES
                        (:organization_id, :tournament_id, 2, CAST(:config AS jsonb),
                         '{}'::jsonb, 'draft', :member_id)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "tournament_id": str(tournament_id),
                    "member_id": str(tenant.member_id),
                    "config": json.dumps(config),
                },
            )
        ).scalar_one()
        draft_stage_id = (
            await session.execute(
                text("""
                    INSERT INTO stages
                        (organization_id, tournament_id, tournament_version_id, name,
                         stage_type, stage_order)
                    VALUES
                        (:organization_id, :tournament_id, :version_id, 'Grupo B',
                         'round_robin', 2)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "tournament_id": str(tournament_id),
                    "version_id": str(draft_version_id),
                },
            )
        ).scalar_one()
        await session.commit()
    return PublishedSetup(
        tenant,
        tournament_id,
        published_version_id,
        published_stage_id,
        draft_version_id,
        draft_stage_id,
        match_id,
        teams,
    )


async def stored_config(engine, setup: PublishedSetup) -> tuple[dict[str, str], str]:
    """Canonical ``jsonb`` text of every version and of the draft config."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        rows = await session.execute(
            text("""
                SELECT id::text AS id, rules_config::text AS rules
                FROM tournament_versions
                WHERE organization_id = :organization_id
                  AND tournament_id = :tournament_id
            """),
            {
                "organization_id": str(setup.tenant.organization_id),
                "tournament_id": str(setup.tournament_id),
            },
        )
        versions = {row["id"]: row["rules"] for row in rows.mappings().all()}
        draft = (
            await session.execute(
                text("""
                    SELECT COALESCE(current_draft_config::text, '')
                    FROM tournaments
                    WHERE id = :tournament_id
                """),
                {"tournament_id": str(setup.tournament_id)},
            )
        ).scalar_one()
    return versions, draft


@pytest.mark.asyncio
async def test_a_published_version_before_the_keys_has_no_limit_and_is_never_rewritten(
    database_admin_url,
):
    config = rules_config_before_the_three_keys()

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_published_tournament(engine, config=config)
        before = await stored_config(engine, setup)

        # The versions list, which the rosters screen uses to compute the lock
        # notice and the limits, only reads: no default is materialized.
        async with AsyncSession(engine, expire_on_commit=False) as session:
            versions = await list_versions(
                setup.tournament_id, setup.context, session, 100, 0
            )
        published = next(
            row for row in versions if row["id"] == setup.published_version_id
        )
        for key in LEGACY_KEYS:
            assert key not in published["rules_config"]

        # Enrollment in the draft clone (same legacy config) is not blocked.
        draft = StageSetup(
            setup.tenant, setup.tournament_id, setup.draft_stage_id, setup.teams
        )
        response = Response()
        enrolled = await enroll(
            engine, draft, [setup.teams["Alfa"], setup.teams["Bravo"]], response
        )

        assert response.status_code == 201
        assert len(enrolled["assigned"]) == 2
        assert await stage_team_ids(engine, draft) == {
            setup.teams["Alfa"],
            setup.teams["Bravo"],
        }

        # Opening a match of the published version reads its own legacy config:
        # 0 and 50 active players are both inside "no limit".
        match = MatchSetup(
            setup.tenant,
            setup.tournament_id,
            setup.published_stage_id,
            setup.match_id,
            setup.teams["Alfa"],
            setup.teams["Bravo"],
        )
        segment = await open_match(engine, match)

        assert segment["segment_number"] == 1
        assert len((await opening_state(engine, match))["segments"]) == 1

        assert await stored_config(engine, setup) == before
        for rules in (await stored_config(engine, setup))[0].values():
            for key in LEGACY_KEYS:
                assert key not in json.loads(rules)


# ---------------------------------------------------------------------------
# H-7: editing the roster is never rejected by size (criterion 39)
# ---------------------------------------------------------------------------

# Minimal PNG header: enough for the image signature validation.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


class FakeStorage:
    """Records the objects of the photo routes without contacting S3."""

    def __init__(self) -> None:
        self.puts: list[tuple[str, bytes, str]] = []
        self.deleted: list[str] = []

    async def put_bytes(self, key: str, content: bytes, content_type: str) -> str:
        self.puts.append((key, content, content_type))
        return key

    async def delete_key(self, key: str) -> None:
        self.deleted.append(key)

    async def signed_urls(self, keys, expires_seconds: int | None = None):
        return SignedUrls(urls={key: f"https://example.test/{key}" for key in keys})


async def first_roster_id(engine, setup: StageSetup, team_id: UUID) -> UUID:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        return (
            await session.execute(
                text("""
                    SELECT id
                    FROM rosters
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND team_id = :team_id
                    ORDER BY dorsal_number
                    LIMIT 1
                """),
                {
                    "organization_id": str(setup.tenant.organization_id),
                    "tournament_id": str(setup.tournament_id),
                    "team_id": str(team_id),
                },
            )
        ).scalar_one()


async def active_roster_count(engine, setup: StageSetup, team_id: UUID) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, setup.tenant)
        return (
            await session.execute(
                text("""
                    SELECT count(*)
                    FROM rosters
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND team_id = :team_id
                      AND is_active = TRUE
                """),
                {
                    "organization_id": str(setup.tenant.organization_id),
                    "tournament_id": str(setup.tournament_id),
                    "team_id": str(team_id),
                },
            )
        ).scalar_one()


def roster_payload(team_id: UUID, *, dorsal: int, document: str):
    return CreateRosterPlayerRequest(
        team_id=team_id,
        first_name="H7",
        last_name=f"Jugador {dorsal}",
        national_id=document,
        birth_date=date(2000, 1, 1),
        dorsal_number=dorsal,
    )


async def create_roster(engine, setup: StageSetup, *, team_id: UUID, dorsal: int):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await create_roster_player(
            setup.tournament_id,
            roster_payload(team_id, dorsal=dorsal, document=f"H7-{dorsal}-{uuid4().hex[:6]}"),
            setup.context,
            session,
        )


def imported_rows(team_id: UUID, *, start: int) -> list[ImportedRosterRow]:
    rows = []
    for offset in range(2):
        dorsal = start + offset
        rows.append(
            ImportedRosterRow(
                offset + 2,
                CreateRosterPlayerRequest(
                    team_id=team_id,
                    first_name="Importado",
                    last_name=f"Jugador {dorsal}",
                    national_id=f"H7-IMP-{dorsal}",
                    birth_date=date(2000, 1, 1),
                    dorsal_number=dorsal,
                ),
                None,
            )
        )
    return rows


async def import_roster(engine, setup: StageSetup, *, team_id: UUID):
    csv_file = UploadFile(file=io.BytesIO(b"first_name\n"), filename="roster.csv")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await create_roster_players_bulk(
            setup.tournament_id,
            team_id=team_id,
            csv_file=csv_file,
            photos_zip=None,
            context=setup.context,
            db=session,
        )


async def set_photo_consent(engine, setup: StageSetup, roster_id: UUID):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await update_roster_photo_consent(
            setup.tournament_id,
            roster_id,
            UpdatePhotoConsentRequest(photo_consent=True),
            setup.context,
            session,
        )


async def upload_photo(engine, setup: StageSetup, roster_id: UUID):
    photo = UploadFile(file=io.BytesIO(PNG_BYTES), filename="player.png")
    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await upload_roster_player_photo(
            setup.tournament_id, roster_id, photo, setup.context, session
        )


@pytest.mark.asyncio
async def test_editing_the_roster_is_never_rejected_by_size(
    database_admin_url, monkeypatch
):
    # Minimum and maximum of two: the team is above the maximum from the start
    # and every editing path keeps growing it, which must never be blocked.
    config = rules_config(minimum=2, maximum=2)
    storage = FakeStorage()
    monkeypatch.setattr(tournaments_router, "get_object_storage", lambda: storage)
    monkeypatch.setattr(photos_module, "get_object_storage", lambda: storage)

    async with committed_application(database_admin_url) as engine:
        setup = await seeded_stage(
            engine, config=config, rosters={"Lleno": 3, "Corto": 1}
        )
        team_id = setup.teams["Lleno"]
        roster_id = await first_roster_id(engine, setup, team_id)
        assert await active_roster_count(engine, setup, team_id) == 3

        # Individual entry: no 409, the row is created.
        player = await create_roster(engine, setup, team_id=team_id, dorsal=9)
        assert player["roster_id"] is not None
        assert player["dorsal_number"] == 9
        assert await active_roster_count(engine, setup, team_id) == 4

        # CSV import: no 409, both rows are created.
        monkeypatch.setattr(
            tournaments_router,
            "parse_roster_csv",
            lambda raw, target: imported_rows(target, start=20),
        )
        imported = await import_roster(engine, setup, team_id=team_id)
        assert imported["count"] == 2
        assert {row["dorsal_number"] for row in imported["players"]} == {20, 21}
        assert await active_roster_count(engine, setup, team_id) == 6

        # Photo consent and photo upload: no 409 either.
        consent = await set_photo_consent(engine, setup, roster_id)
        assert consent["photo_consent"] is True
        photo = await upload_photo(engine, setup, roster_id)
        assert len(storage.puts) == 1
        assert photo["photo_url"] == f"https://example.test/{storage.puts[0][0]}"
        assert await active_roster_count(engine, setup, team_id) == 6
