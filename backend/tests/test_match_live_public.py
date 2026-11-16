"""Unión pública F1: contratos exactos y ruta anónima con PostgreSQL."""

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from db_helpers import application_database_url
from migration_helpers import throwaway_database
from test_match_live_db import LiveFixture, command, goal
from test_migration_031 import (
    TOURNAMENT, STAGE, MATCH, ORG, USER, MEMBER, SEED_SQL,
    TEAM_HOME, TEAM_AWAY, PLAYER_HOME_FIRST, PLAYER_AWAY, SEGMENT_FIRST,
)
from test_public_access_matrix import _public_api
from test_substitutions import rules_config

GROUP = "31000000-0000-4000-8000-000000000060"
OTHER_STAGE = "31000000-0000-4000-8000-000000000061"


@pytest.fixture
async def public_live_db(database_admin_url):
    async with throwaway_database(database_admin_url, last=61) as admin:
        sql = SEED_SQL.replace(
            "1, '{}'::jsonb, '{}'::jsonb,",
            f"1, '{json.dumps(rules_config())}'::jsonb, '{{}}'::jsonb,",
        )
        setup = f"""
            INSERT INTO groups(id,organization_id,tournament_id,tournament_version_id,stage_id,name)
            SELECT '{GROUP}',organization_id,tournament_id,tournament_version_id,stage_id,'Grupo F1'
            FROM matches WHERE id='{MATCH}';
            INSERT INTO stage_teams(organization_id,tournament_id,tournament_version_id,stage_id,group_id,team_id)
            SELECT organization_id,tournament_id,tournament_version_id,stage_id,'{GROUP}',team_id
            FROM stage_teams WHERE stage_id='{STAGE}';
            UPDATE matches SET group_id='{GROUP}',matchday=2 WHERE id='{MATCH}';
            INSERT INTO stages(id,organization_id,tournament_id,tournament_version_id,name,stage_type,stage_order)
            SELECT '{OTHER_STAGE}',organization_id,tournament_id,tournament_version_id,'Otra fase','round_robin',2
            FROM matches WHERE id='{MATCH}';
            INSERT INTO stage_teams(organization_id,tournament_id,tournament_version_id,stage_id,team_id)
            SELECT organization_id,tournament_id,tournament_version_id,'{OTHER_STAGE}',team_id
            FROM stage_teams WHERE stage_id='{STAGE}' AND group_id IS NULL;
            INSERT INTO matches
                (organization_id,tournament_id,tournament_version_id,stage_id,home_team_id,away_team_id,status,matchday)
            SELECT organization_id,tournament_id,tournament_version_id,
                CASE WHEN n=4 THEN '{OTHER_STAGE}'::uuid ELSE stage_id END,home_team_id,away_team_id,
                CASE WHEN n=3 THEN 'cancelled' ELSE 'scheduled' END,n
            FROM matches CROSS JOIN generate_series(1,4) n WHERE id='{MATCH}';
        """
        await admin.execute(sql.replace("UPDATE public.tournament_versions", setup + "UPDATE public.tournament_versions"))
        await admin.execute(SEED_SQL.replace("31000000", "32000000").replace("migration-031", "publica-ajena"))
        await admin.execute(SEED_SQL.split("UPDATE public.tournament_versions")[0].replace("31000000", "33000000").replace("migration-031", "publica-oculta"))
        role = await admin.fetchval("""INSERT INTO roles(organization_id,role_definition_id,name,permissions)
            SELECT $1,id,'Operador F1',system_permissions FROM role_definitions WHERE code='owner' RETURNING id""", ORG)
        await admin.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)", ORG, MEMBER, role)
        session_id = uuid4()
        await admin.execute("INSERT INTO user_sessions(id,user_id,expires_at) VALUES ($1,$2,'2099-01-01')", session_id, USER)
        for player, team in ((PLAYER_HOME_FIRST, TEAM_HOME), (PLAYER_AWAY, TEAM_AWAY)):
            roster = await admin.fetchval("""INSERT INTO rosters
                (organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
                VALUES ($1,$2,$3,$4,1,now(),now()) RETURNING id""", ORG, TOURNAMENT, team, player)
            await admin.execute("""INSERT INTO match_rosters
                (organization_id,match_id,roster_id,player_id,team_id,role,is_valid,entered_minute)
                VALUES ($1,$2,$3,$4,$5,'starter',TRUE,0)""", ORG, MATCH, roster, player, team)
        await admin.execute("UPDATE match_segments SET status='active',minute_end=NULL WHERE id=$1", SEGMENT_FIRST)
        name = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(make_url(application_database_url()).set(database=name))
        try:
            fixture = LiveFixture(admin, engine, AuthContext(
                user_id=UUID(USER), organization_id=UUID(ORG), organization_user_id=UUID(MEMBER)
            ), session_id)
            await fixture.call("execute", command("start"))
            await fixture.call("execute", command("add_event", 1, event=goal()))
            yield fixture
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_route_suspendido_paginacion_filtros_y_estadisticas(public_live_db):
    f = public_live_db
    await f.call("execute", command("suspend", 2))
    async with AsyncSession(f.engine) as db, _public_api(db) as client:
        path = f"/api/v1/tournaments/public/{TOURNAMENT}"
        response = await client.get(path + "/matches")
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 4
        suspended = next(row for row in rows if row["id"] == MATCH)
        assert set(suspended) == set(suspended_payload())
        assert suspended["home_score"] == 1 and suspended["is_provisional"]
        assert suspended["clock_state"] == "not_started"
        pages = [(await client.get(path + f"/matches?limit=1&offset={n}")).json()[0] for n in range(4)]
        assert pages == rows
        assert (await client.get(path + f"/matches?stage_id={STAGE}")).json() == rows[:3]
        assert (await client.get(path + f"/matches?group_id={GROUP}&limit=1")).json() == [suspended]
        for query in (f"stage_id={uuid4()}", f"group_id={uuid4()}", "offset=4"):
            assert (await client.get(path + "/matches?" + query)).json() == []
        for endpoint in ("standings", "player-stats"):
            assert (await client.get(path + "/" + endpoint)).json() == []
        stats = (await client.get(path + "/team-stats")).json()
        assert all(row["goals_for"] == 0 for row in stats)
    assert await f.admin.fetchval("SELECT count(*) FROM match_events WHERE match_id=$1", MATCH) == 0
    assert not await f.admin.fetchval("SELECT result_confirmed FROM matches WHERE id=$1", MATCH)


@pytest.mark.asyncio
async def test_route_invisible_cancelado_y_organizacion_ajena(public_live_db):
    f = public_live_db
    await f.call("execute", command("suspend", 2))
    async with AsyncSession(f.engine) as db, _public_api(db) as client:
        path = f"/api/v1/tournaments/public/{TOURNAMENT}/matches"
        other = TOURNAMENT.replace("31000000", "32000000")
        foreign = (await client.get(f"/api/v1/tournaments/public/{other}/matches")).json()
        assert all(row["id"] != MATCH for row in foreign)
        cancelled = await f.admin.fetchval("SELECT id FROM matches WHERE tournament_id=$1 AND status='cancelled'", TOURNAMENT)
        assert all(row["id"] != str(cancelled) for row in (await client.get(path)).json())
        hidden = await client.get(path.replace("31000000", "33000000"))
        absent = await client.get(f"/api/v1/tournaments/public/{uuid4()}/matches")
        assert hidden.status_code == absent.status_code == 404
        assert hidden.json() == absent.json()


def suspended_payload():
    return dict(
        id=uuid4(),
        tournament_id=uuid4(),
        home_team_id=uuid4(),
        home_team_name="Home",
        away_team_id=uuid4(),
        away_team_name="Away",
        status="suspended",
        home_score=0,
        away_score=0,
        is_provisional=True,
        clock_segment_number=None,
        clock_elapsed_seconds=None,
        clock_state="not_started",
        clock_observed_at=datetime.now(timezone.utc),
    )


def test_serialization_suspended_exact_fourteen_keys_including_nulls():
    from app.modules.matches.live_public import PublicMatchStateResponse

    payload = suspended_payload()
    result = (
        TypeAdapter(PublicMatchStateResponse)
        .validate_python(payload)
        .model_dump(mode="json")
    )
    assert len(result) == 14 and set(result) == set(payload)
    assert (
        result["clock_segment_number"] is None
        and result["clock_elapsed_seconds"] is None
    )


@pytest.mark.parametrize(
    "extra", ["lineup", "stage_id", "actor_user_id", "home_team_crest_url"]
)
def test_serialization_suspended_forbids_other_fields(extra):
    from app.modules.matches.live_public import PublicMatchStateResponse

    with pytest.raises(ValidationError):
        TypeAdapter(PublicMatchStateResponse).validate_python(
            {**suspended_payload(), extra: None}
        )


def test_serialization_live_extends_classic_other_states_keep_original_defaults():
    from app.modules.matches.live_public import PublicMatchStateResponse
    from app.modules.tournaments.schemas import PublicMatchResponse

    classic = dict(
        id=uuid4(),
        tournament_id=uuid4(),
        stage_id=uuid4(),
        stage_name="Stage",
        stage_order=1,
        status="scheduled",
    )
    adapter = TypeAdapter(PublicMatchStateResponse)
    assert (
        adapter.validate_python(classic).model_dump()
        == PublicMatchResponse(**classic).model_dump()
    )
    live = {
        **classic,
        "status": "live",
        **{k: v for k, v in suspended_payload().items() if k.startswith("clock_")},
        "is_provisional": True,
    }
    result = adapter.validate_python(live).model_dump()
    assert result["is_provisional"] and result["clock_elapsed_seconds"] is None
    assert result["stage_name"] == "Stage"
