"""Internal services: real PostgreSQL and no production router registration."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter
from sqlalchemy.engine import make_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.core.database import set_rls_context
from app.modules.matches.live_service import LiveMatchService
from app.modules.matches.live_schemas import LiveCommand
from db_helpers import application_database_url
from migration_helpers import throwaway_database
from test_migration_056 import (
    ORG,
    USER,
    MEMBER,
    MATCH,
    SEGMENT_FIRST,
    TEAM_HOME,
    PLAYER_HOME_FIRST,
)
from test_migration_031 import SEED_SQL, TEAM_AWAY, PLAYER_AWAY, TOURNAMENT, STAGE
from test_substitutions import rules_config


@dataclass
class LiveFixture:
    admin: object
    engine: object
    context: AuthContext
    session_id: UUID

    async def call(self, method, *args):
        from app.modules.matches.live_service import LiveMatchService

        async with AsyncSession(self.engine) as db:
            return await getattr(LiveMatchService(db), method)(
                self.context, UUID(MATCH), self.session_id, *args
            )

    async def permissions(self, permissions):
        await self.admin.execute(
            "UPDATE roles SET permissions=$1::jsonb WHERE organization_id=$2",
            json.dumps(permissions),
            ORG,
        )


@pytest.fixture
async def live_service_db(database_admin_url, request):
    async with throwaway_database(database_admin_url, last=58) as db:
        options = getattr(request, "param", {})
        config = rules_config()
        if options.get("stage_override"):
            config["stage_overrides"][STAGE] = options["stage_override"]
        sql = SEED_SQL.replace(
            "1, '{}'::jsonb, '{}'::jsonb,",
            f"1, '{json.dumps(config)}'::jsonb, '{{}}'::jsonb,",
        )
        if options.get("bracket_code"):
            assert options["bracket_code"] in {"GF1", "GF2"}
            sql = sql.replace(
                "UPDATE public.tournament_versions",
                f"UPDATE public.matches SET bracket_code='{options['bracket_code']}'; UPDATE public.tournament_versions",
            )
        if options.get("extra_match"):
            sql=sql.replace("UPDATE public.tournament_versions", """INSERT INTO public.matches
                (id,organization_id,tournament_id,tournament_version_id,stage_id,home_team_id,away_team_id,status)
                SELECT '31000000-0000-4000-8000-000000000053',organization_id,tournament_id,
                    tournament_version_id,stage_id,home_team_id,away_team_id,'scheduled' FROM public.matches;
                UPDATE public.tournament_versions""")
        if options.get("missing_participant"):
            sql = sql.replace(
                f"'{TEAM_HOME}', '{TEAM_AWAY}', 'scheduled', 1",
                f"NULL, '{TEAM_AWAY}', 'scheduled', 1",
            )
        await db.execute(sql)
        await db.execute(
            SEED_SQL.replace("31000000", "32000000").replace(
                "migration-031", "live-other"
            )
        )
        role = await db.fetchval(
            "INSERT INTO roles(organization_id,role_definition_id,name,permissions) SELECT $1,id,'Live owner',system_permissions FROM role_definitions WHERE code='owner' RETURNING id",
            ORG,
        )
        await db.execute(
            "INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)",
            ORG,
            MEMBER,
            role,
        )
        session_id = uuid4()
        await db.execute(
            "INSERT INTO user_sessions(id,user_id,expires_at) VALUES ($1,$2,'2099-01-01')",
            session_id,
            USER,
        )
        for player, team in ((PLAYER_HOME_FIRST, TEAM_HOME), (PLAYER_AWAY, TEAM_AWAY)):
            roster = await db.fetchval(
                """INSERT INTO rosters(organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
                VALUES ($1,$2,$3,$4,1,now(),now()) RETURNING id""",
                ORG,
                TOURNAMENT,
                team,
                player,
            )
            await db.execute(
                """INSERT INTO match_rosters(organization_id,match_id,roster_id,player_id,team_id,role,is_valid,entered_minute)
                VALUES ($1,$2,$3,$4,$5,'starter',TRUE,0)""",
                ORG,
                MATCH,
                roster,
                player,
                team,
            )
        await db.execute("UPDATE matches SET status='live' WHERE id=$1", MATCH)
        if options.get("archived"):
            await db.execute("UPDATE tournament_versions SET status='archived'")
        await db.execute(
            "UPDATE match_segments SET status='completed',minute_end=90 WHERE match_id=$1",
            MATCH,
        )
        await db.execute(
            "UPDATE match_segments SET status='active',minute_end=NULL WHERE id=$1",
            SEGMENT_FIRST,
        )
        name = await db.fetchval("SELECT current_database()")
        engine = create_async_engine(
            make_url(application_database_url()).set(database=name)
        )
        try:
            yield LiveFixture(
                db,
                engine,
                AuthContext(
                    user_id=UUID(USER),
                    organization_id=UUID(ORG),
                    organization_user_id=UUID(MEMBER),
                ),
                session_id,
            )
        finally:
            await engine.dispose()


def command(kind, revision=0, **values):
    return TypeAdapter(LiveCommand).validate_python(
        dict(type=kind, command_id=uuid4(), expected_revision=revision, **values)
    )


def goal(**values):
    return dict(
        client_event_id=str(uuid4()),
        event_type="goal",
        team_id=TEAM_HOME,
        player_id=PLAYER_HOME_FIRST,
        segment_id=SEGMENT_FIRST,
        minute=1,
        **values,
    )


@pytest.mark.parametrize(
    "permissions,expected",
    [
        ([], (False, False)),
        (["VIEW_MATCH_LIVE_DRAFT"], (True, False)),
        (["OPERATE_MATCH_LIVE"], (False, True)),
        (["CLOSE_MATCH_REPORT"], (False, False)),
    ],
)
async def test_access_independent_capabilities(live_service_db, permissions, expected):
    f = live_service_db
    await f.permissions(permissions)
    result = await f.call("access")
    assert (result.can_view, result.can_operate) == expected
    assert set(result.model_dump()) == {
        "can_view",
        "can_operate",
        "can_close",
        "available",
    }


async def test_access_foreign_context(live_service_db):
    f = live_service_db
    f.context = replace(f.context, organization_id=uuid4())
    with pytest.raises(HTTPException) as error:
        await f.call("access")
    assert error.value.status_code in (403, 404)


def live_headers(f):
    from app.core.security import create_access_token

    token = create_access_token(UUID(USER), f.session_id)
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": ORG}


def mounted_routes(app):
    """(path, método) de cada ruta efectiva, expandiendo `_IncludedRouter` (montaje perezoso)."""

    found = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        candidates = getattr(route, "effective_candidates", None)
        if callable(candidates):
            stack.extend(candidates())
            continue
        methods = getattr(route, "methods", None)
        if methods is None:
            methods = getattr(getattr(route, "original_route", route), "methods", ())
        for method in methods or ():
            found.add((getattr(route, "path", ""), method))
    return found


@asynccontextmanager
async def live_client(f):
    """Cliente HTTP sobre el montaje real con `get_db` apuntando a la base desechable."""

    from app.core.database import get_db
    from app.main import api as production_app

    async def throwaway_db():
        async with AsyncSession(f.engine) as db:
            yield db

    production_app.dependency_overrides[get_db] = throwaway_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=production_app), base_url="http://test"
        ) as client:
            yield client
    finally:
        production_app.dependency_overrides.clear()


async def csrf_headers(client):
    return {
        "X-CSRF-Token": (await client.get("/api/v1/auth/csrf")).headers["X-CSRF-Token"]
    }


async def test_live_routes_registered_on_production_app(live_service_db):
    from app.main import api as production_app

    routes = mounted_routes(production_app)
    base = "/api/v1/matches/{match_id}"
    assert (f"{base}/live", "GET") in routes
    assert (f"{base}/live/access", "GET") in routes
    assert (f"{base}/live/commands", "POST") in routes
    assert (f"{base}/live/reviews", "POST") in routes


async def test_access_http_through_production_mount(live_service_db):
    f = live_service_db
    await f.permissions(["OPERATE_MATCH_LIVE"])
    async with live_client(f) as client:
        assert (
            await client.get(f"/api/v1/matches/{MATCH}/live/access")
        ).status_code == 401
        response = await client.get(
            f"/api/v1/matches/{MATCH}/live/access", headers=live_headers(f)
        )
        assert response.status_code == 200
        assert response.json() == dict(
            can_view=False, can_operate=True, can_close=False, available=True
        )


async def test_live_writes_require_csrf_and_session(live_service_db):
    f = live_service_db
    await f.permissions(["OPERATE_MATCH_LIVE"])
    body = command("start_clock", segment_id=SEGMENT_FIRST).model_dump(mode="json")
    url = f"/api/v1/matches/{MATCH}/live/commands"
    async with live_client(f) as client:
        assert (await client.post(url, json=body)).status_code == 401
        denied = await client.post(url, json=body, headers=live_headers(f))
        assert denied.status_code == 403
        assert denied.json() == {"detail": "Token CSRF inválido"}
        response = await client.post(
            url,
            json=body,
            headers={**live_headers(f), **await csrf_headers(client)},
        )
        assert response.status_code == 200
        assert set(response.json()) == {"command_id", "revision"}
        assert response.json()["command_id"] == body["command_id"]
        snapshot = await client.get(
            f"/api/v1/matches/{MATCH}/live", headers=live_headers(f)
        )
        # Sin VIEW la lectura de detalle sigue denegada tras el comando.
        assert snapshot.status_code == 403


async def test_live_review_through_production_mount(live_service_db):
    f = live_service_db
    await f.permissions(["VIEW_MATCH_LIVE_DRAFT", "CLOSE_MATCH_REPORT"])
    url = f"/api/v1/matches/{MATCH}"
    async with live_client(f) as client:
        headers = {**live_headers(f), **await csrf_headers(client)}
        # Sin estado F1 el partido responde initialized=false sin crear estado.
        snapshot = await client.get(f"{url}/live", headers=headers)
        assert snapshot.status_code == 200
        assert snapshot.json()["initialized"] is False
        # La revisión exige estado inicializado.
        review = await client.post(
            f"{url}/live/reviews",
            headers=headers,
            json={
                "expected_content_revision": 0,
                "result": {
                    "resolution_type": "regular",
                    "home_score_regular": 0,
                    "away_score_regular": 0,
                },
            },
        )
        assert review.status_code == 409
        assert review.json()["detail"] == "LIVE_MATCH_NOT_EDITABLE"
        await f.permissions(["VIEW_MATCH_LIVE_DRAFT", "CLOSE_MATCH_REPORT", "OPERATE_MATCH_LIVE"])
        await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
        review = await client.post(
            f"{url}/live/reviews",
            headers=headers,
            json={
                "expected_content_revision": 0,
                "result": {
                    "resolution_type": "regular",
                    "home_score_regular": 0,
                    "away_score_regular": 0,
                },
            },
        )
        assert review.status_code == 201
        receipt = review.json()
        assert receipt["content_revision"] == 0
        assert set(receipt) == {"live_review_id", "content_revision", "report", "fingerprint"}


async def test_classic_close_route_is_not_a_bypass_of_live_review(live_service_db):
    f = live_service_db
    await f.permissions(
        ["VIEW_MATCH_LIVE_DRAFT", "CLOSE_MATCH_REPORT", "OPERATE_MATCH_LIVE"]
    )
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    url = f"/api/v1/matches/{MATCH}"
    async with live_client(f) as client:
        headers = {**live_headers(f), **await csrf_headers(client)}
        bypass = await client.post(
            f"{url}/close",
            headers=headers,
            json={
                "resolution_type": "regular",
                "home_score_regular": 0,
                "away_score_regular": 0,
            },
        )
        assert bypass.status_code == 409
        assert bypass.json()["detail"] == "LIVE_REVIEW_REQUIRED"
        review = await client.post(
            f"{url}/live/reviews",
            headers=headers,
            json={
                "expected_content_revision": 0,
                "result": {
                    "resolution_type": "regular",
                    "home_score_regular": 0,
                    "away_score_regular": 0,
                },
            },
        )
        closed = await client.post(
            f"{url}/close",
            headers=headers,
            json={
                "resolution_type": "regular",
                "home_score_regular": 0,
                "away_score_regular": 0,
                "live_review_id": review.json()["live_review_id"],
            },
        )
        assert closed.status_code == 200


async def test_snapshot_foreign_or_missing_indistinguishable(live_service_db):
    f = live_service_db
    for match_id in (uuid4(), UUID(MATCH.replace("31000000", "32000000"))):
        async with AsyncSession(f.engine) as db:
            with pytest.raises(HTTPException) as error:
                await LiveMatchService(db).snapshot(f.context, match_id, f.session_id)
            assert error.value.status_code == 404


@pytest.mark.parametrize("target", ["organization_users", "users", "organizations"])
async def test_snapshot_requires_current_membership(live_service_db, target):
    f = live_service_db
    await f.admin.execute(f"UPDATE {target} SET is_active=FALSE")
    with pytest.raises(HTTPException) as error:
        await f.call("snapshot")
    assert error.value.status_code in {403, 404}


async def test_snapshot_empty_non_mutating(live_service_db):
    f = live_service_db
    one, two = await asyncio.gather(f.call("snapshot"), f.call("snapshot"))
    assert not one.initialized and one == two and one.events == []
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0


async def test_snapshot_current_permission_session(live_service_db):
    f = live_service_db
    await f.permissions(["OPERATE_MATCH_LIVE"])
    with pytest.raises(HTTPException) as error:
        await f.call("snapshot")
    assert error.value.status_code == 403
    await f.permissions(["VIEW_MATCH_LIVE_DRAFT"])
    await f.admin.execute(
        "UPDATE user_sessions SET revoked_at=now() WHERE id=$1", f.session_id
    )
    with pytest.raises(HTTPException) as error:
        await f.call("snapshot")
    assert error.value.status_code == 401


async def test_command_identity_retry_conflict_and_permission(live_service_db):
    f = live_service_db
    await f.admin.execute("UPDATE matches SET status='scheduled' WHERE id=$1", MATCH)
    cmd = command("start")
    ack = await f.call("execute", cmd)
    assert ack == await f.call("execute", cmd)
    assert set(ack.model_dump()) == {"command_id", "revision"}
    assert ack.revision == 1
    with pytest.raises(HTTPException) as error:
        await f.call("execute", cmd.model_copy(update={"expected_revision": 1}))
    assert error.value.status_code == 409
    await f.permissions([])
    with pytest.raises(HTTPException) as error:
        await f.call("execute", cmd)
    assert error.value.status_code == 403
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 1


async def test_command_identity_other_session(live_service_db):
    f = live_service_db
    cmd = command("start_clock", segment_id=SEGMENT_FIRST)
    await f.call("execute", cmd)
    other_session = uuid4()
    await f.admin.execute(
        "INSERT INTO user_sessions(id,user_id,expires_at) VALUES ($1,$2,'2099-01-01')",
        other_session,
        USER,
    )
    f.session_id = other_session
    with pytest.raises(HTTPException) as error:
        await f.call("execute", cmd)
    assert error.value.status_code == 409


async def test_start_match_concurrency(live_service_db):
    f = live_service_db
    await f.admin.execute("UPDATE matches SET status='scheduled' WHERE id=$1", MATCH)
    results = await asyncio.gather(
        f.call("execute", command("start")),
        f.call("execute", command("start")),
        return_exceptions=True,
    )
    assert (
        sum(
            isinstance(result, HTTPException) and result.status_code == 409
            for result in results
        )
        == 1
    )
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 1
    assert await f.admin.fetchval("SELECT count(*) FROM match_events") == 0


@pytest.mark.parametrize(
    "live_service_db",
    [{"missing_participant": True}, {"archived": True}],
    indirect=True,
)
async def test_start_match_invalid(live_service_db):
    f = live_service_db
    await f.admin.execute("UPDATE matches SET status='scheduled' WHERE id=$1", MATCH)
    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    assert error.value.status_code == 409
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0


@pytest.mark.parametrize("clock_state", ["running", "paused", "not_started"])
async def test_suspend_resume_clock_and_forbidden_capture(live_service_db, clock_state):
    f = live_service_db
    revision = 0
    if clock_state != "not_started":
        await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
        revision += 1
    if clock_state == "paused":
        await f.call("execute", command("pause_clock", revision))
        revision += 1
    await f.call("execute", command("suspend", revision))
    snapshot = await f.call("snapshot")
    assert (
        snapshot.clock.state
        == ("not_started" if clock_state == "not_started" else "paused")
        and snapshot.status == "suspended"
    )
    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("add_event", revision + 1, event=goal()))
    assert error.value.status_code == 409
    await f.call("execute", command("resume", revision + 1))
    current = await f.call("snapshot")
    assert (
        current.clock.state == snapshot.clock.state
        and current.clock.elapsed_us == snapshot.clock.elapsed_us
    )


@pytest.mark.parametrize(
    "changes", [{"minute": 91}, {"segment_id": str(uuid4())}, {"team_id": TEAM_AWAY}]
)
async def test_add_event_invalid_time_scope_or_participant(live_service_db, changes):
    f = live_service_db
    with pytest.raises(HTTPException):
        await f.call("execute", command("add_event", event={**goal(), **changes}))
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_events") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0


async def test_add_event_limit_501(live_service_db):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    async with AsyncSession(f.engine) as db, db.begin():
        await set_rls_context(db, f.context.organization_id, f.context.user_id)
        await db.execute(
            text("""INSERT INTO match_live_events(organization_id,match_id,client_event_id,event_type,team_id,player_id,segment_id,minute)
            SELECT :org,:match,gen_random_uuid(),'goal',:team,:player,:segment,1 FROM generate_series(1,500)"""),
            dict(
                org=UUID(ORG),
                match=UUID(MATCH),
                team=UUID(TEAM_HOME),
                player=UUID(PLAYER_HOME_FIRST),
                segment=UUID(SEGMENT_FIRST),
            ),
        )
    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("add_event", 1, event=goal()))
    assert error.value.status_code == 409
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_events") == 500


async def test_edit_event_failed_correction_preserves_history(live_service_db):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    before = await f.call("snapshot")
    with pytest.raises(HTTPException):
        await f.call(
            "execute",
            command(
                "correct_event",
                1,
                event_id=event["client_event_id"],
                event={**event, "minute": 91},
            ),
        )
    after = await f.call("snapshot")
    assert (
        after.events == before.events
        and after.content_revision == before.content_revision
    )
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 1


async def test_edit_event_concurrent_revision(live_service_db):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    results = await asyncio.gather(
        *(
            f.call(
                "execute",
                command(
                    "correct_event",
                    1,
                    event_id=event["client_event_id"],
                    event={**event, "minute": minute},
                ),
            )
            for minute in (2, 3)
        ),
        return_exceptions=True,
    )
    assert (
        sum(
            isinstance(result, HTTPException) and result.status_code == 409
            for result in results
        )
        == 1
    )
    assert (await f.call("snapshot")).content_revision == 2


async def test_edit_event_validates_in_persisted_order(live_service_db, monkeypatch):
    from app.modules.matches.service import CloseMatchReportService

    f = live_service_db
    first, second = goal(), goal()
    await f.call("execute", command("add_event", event=first))
    await f.call("execute", command("add_event", 1, event=second))
    validate = CloseMatchReportService._validate_event_participants
    seen = []

    def capture(dto, match, rosters):
        seen.extend(event.client_event_id for event in dto.events)
        return validate(dto, match, rosters)

    monkeypatch.setattr(
        CloseMatchReportService, "_validate_event_participants", staticmethod(capture)
    )
    await f.call(
        "execute",
        command(
            "correct_event",
            2,
            event_id=first["client_event_id"],
            event={**first, "event_type": "foul"},
        ),
    )
    assert seen == [
        event.client_event_id for event in (await f.call("snapshot")).events
    ]


@pytest.mark.parametrize("status", ["completed", "interrupted"])
@pytest.mark.parametrize("kind", ["correct_event", "remove_event"])
async def test_edit_event_previous_segment_respects_status(
    live_service_db, status, kind
):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    await f.admin.execute(
        "UPDATE match_segments SET status=$1,minute_end=5 WHERE id=$2",
        status,
        SEGMENT_FIRST,
    )
    body = dict(event_id=event["client_event_id"])
    if kind == "correct_event":
        body["event"] = {**event, "minute": 2}
    if kind == "correct_event" and status == "interrupted":
        with pytest.raises(HTTPException) as error:
            await f.call("execute", command(kind, 1, **body))
        assert error.value.status_code == 409
        snapshot = await f.call("snapshot")
        assert snapshot.content_revision == 1 and snapshot.events[0].minute == 1
        return
    await f.call("execute", command(kind, 1, **body))
    snapshot = await f.call("snapshot")
    assert snapshot.content_revision == 2
    assert len(snapshot.events) == (1 if kind == "correct_event" else 0)


async def test_clock_correction_revision_and_content(live_service_db):
    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    await f.call(
        "execute",
        command("correct_clock", 1, segment_id=SEGMENT_FIRST, elapsed_us=12_345_678),
    )
    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("pause_clock", 1))
    assert error.value.status_code == 409
    await f.call("execute", command("pause_clock", 2))
    result = await f.call("snapshot")
    assert result.clock.elapsed_us >= 12_345_678 and result.content_revision == 0


async def test_add_event_and_edit_event_score(live_service_db):
    f = live_service_db
    event = goal()
    await f.call("execute", command("add_event", event=event))
    result = await f.call("snapshot")
    assert result.home_score == 1 and result.content_revision == 1
    await f.call(
        "execute",
        command(
            "correct_event",
            1,
            event_id=event["client_event_id"],
            event={**event, "minute": 2},
        ),
    )
    await f.call(
        "execute", command("remove_event", 2, event_id=event["client_event_id"])
    )
    result = await f.call("snapshot")
    assert (
        result.home_score == 0 and result.events == [] and result.content_revision == 3
    )
    assert await f.admin.fetchval("SELECT count(*) FROM match_events") == 0
    with pytest.raises(HTTPException):
        await f.call(
            "execute", command("remove_event", 3, event_id=event["client_event_id"])
        )


async def test_add_event_foreign_player_rollback(live_service_db):
    f = live_service_db
    event = goal()
    event["player_id"] = PLAYER_HOME_FIRST.replace("31000000", "32000000")
    with pytest.raises(HTTPException):
        await f.call("execute", command("add_event", event=event))
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_events") == 0


async def test_segment_clock_close_only_existing_route(live_service_db):
    from app.modules.matches.router import interrupt_match_segment, create_match_segment
    from app.modules.matches.schemas import (
        InterruptMatchSegmentRequest,
        CreateMatchSegmentRequest,
    )

    f = live_service_db
    await f.call("execute", command("start_clock", segment_id=SEGMENT_FIRST))
    await f.permissions(["CLOSE_MATCH_REPORT"])
    async with AsyncSession(f.engine) as db:
        await interrupt_match_segment(
            UUID(MATCH),
            UUID(SEGMENT_FIRST),
            InterruptMatchSegmentRequest(reason="weather", minute=5),
            f.context,
            db,
        )
    assert (
        await f.admin.fetchval("SELECT clock_state FROM match_live_state") == "paused"
    )
    previous = await f.admin.fetchrow(
        "SELECT segment_id,clock_elapsed_us,revision FROM match_live_state"
    )
    async with AsyncSession(f.engine) as db:
        await create_match_segment(
            UUID(MATCH),
            CreateMatchSegmentRequest(segment_number=3, minute_start=90),
            f.context,
            db,
        )
    assert (
        await f.admin.fetchrow(
            "SELECT segment_id,clock_elapsed_us,revision FROM match_live_state"
        )
        == previous
    )


@pytest.mark.parametrize("kind", ["start_clock", "add_event"])
async def test_command_rollback_after_state_before_ack(
    live_service_db, monkeypatch, kind
):
    from app.modules.matches.live_service import LiveMatchService

    f = live_service_db

    async def failure(*args, **kwargs):
        raise RuntimeError("test-only fault")

    monkeypatch.setattr(LiveMatchService, "_record_command", failure)
    tables = (
        "matches",
        "match_events",
        "standings",
        "player_suspensions",
        "player_suspension_serves",
        "advancement_links",
        "outbox_events",
        "administrative_audit_logs",
    )
    before = {
        table: await f.admin.fetch(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id")
        for table in tables
    }
    with pytest.raises(RuntimeError, match="test-only"):
        await f.call(
            "execute",
            command(
                kind,
                **(
                    {"segment_id": SEGMENT_FIRST}
                    if kind == "start_clock"
                    else {"event": goal()}
                ),
            ),
        )
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_events") == 0
    assert before == {
        table: await f.admin.fetch(f"SELECT to_jsonb(t) FROM {table} t ORDER BY id")
        for table in tables
    }


async def test_clock_correction_preserves_accepted_event_minutes(live_service_db):
    f = live_service_db
    await f.call("execute", command("add_event", event=goal()))
    await f.call("execute", command("start_clock", 1, segment_id=SEGMENT_FIRST))
    await f.call("execute", command("pause_clock", 2))
    before = await f.call("snapshot")
    await f.call(
        "execute", command("correct_clock", 3, segment_id=SEGMENT_FIRST, elapsed_us=0)
    )
    after = await f.call("snapshot")
    assert (
        before.events == after.events
        and before.content_revision == after.content_revision
    )
    assert after.clock.elapsed_us == 0 and after.clock.state == "paused"


async def test_command_rejects_terminal_match(live_service_db):
    f = live_service_db
    await f.admin.execute("UPDATE matches SET status='cancelled' WHERE id=$1", MATCH)
    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("add_event", event=goal()))
    assert error.value.status_code == 409
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0
