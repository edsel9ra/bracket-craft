import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import get_auth_context
from app.main import api
from test_migration_031 import MATCH, PLAYER_HOME_FIRST
from test_migration_040 import insert_case, insert_decision
from test_sanction_readers import readers as readers


@pytest.fixture
async def warning_client(readers):
    async def db():
        async with readers.engine.connect() as connection:
            await connection.execute(text("SET ROLE bracket_app"))
            await connection.commit()
            async with AsyncSession(bind=connection) as session:
                yield session

    async def auth():
        return readers.context

    previous = api.dependency_overrides.copy()
    api.dependency_overrides[get_db] = db
    api.dependency_overrides[get_auth_context] = auth
    try:
        async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
            yield client
    finally:
        api.dependency_overrides.clear()
        api.dependency_overrides.update(previous)


@pytest.mark.parametrize("action", [None, "reduce", "annul"])
async def test_private_warning_is_minimal_read_only_and_previews_pending(readers, warning_client, action):
    if action:
        case = await insert_case(readers.admin, readers.suspension, evidence="Private evidence")
        await insert_decision(readers.admin, case, action=action)
    before = await readers.admin.fetchval("SELECT row_to_json(m)::text FROM matches m WHERE id=$1", readers.future)
    response = await warning_client.get(f"/api/v1/matches/{readers.future}/suspension-warnings")
    assert response.status_code == 200, response.text
    assert response.json() == ([] if action == "annul" else [{"player_id": PLAYER_HOME_FIRST, "remaining": 1 if action == "reduce" else 3}])
    assert await readers.admin.fetchval("SELECT row_to_json(m)::text FROM matches m WHERE id=$1", readers.future) == before
    assert await readers.admin.fetchval("SELECT count(*) FROM sanction_effect_applications") == 0
    assert await readers.admin.fetchval("SELECT count(*) FROM sanction_match_eligibility") == 0


async def test_warning_rejects_non_operator_and_foreign_match(readers, warning_client):
    foreign = MATCH.replace("31000000-", "41000000-")
    assert (await warning_client.get(f"/api/v1/matches/{foreign}/suspension-warnings")).status_code == 404
    await readers.admin.execute("UPDATE roles SET permissions='[\"REQUEST_MATCH_REPORT_RECTIFICATION\"]'")
    assert (await warning_client.get(f"/api/v1/matches/{MATCH}/suspension-warnings")).status_code == 403


async def test_warning_empty_after_new_operational_read(readers, warning_client):
    response = await warning_client.get(f"/api/v1/matches/{readers.future}/suspension-warnings")
    assert response.json()
    await readers.admin.execute("UPDATE player_suspensions SET status='served'")
    response = await warning_client.get(f"/api/v1/matches/{readers.future}/suspension-warnings")
    assert response.status_code == 200 and response.json() == []
