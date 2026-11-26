"""«Equipo del torneo» contra PostgreSQL (spec 049, T4; opt-in ``RUN_DATABASE_TESTS=1``)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from migration_helpers import connect
from test_match_assists_db import committed_application, seeded_match
from test_notification_api import add_member

TOURNAMENT_NOT_FOUND = {"detail": "Torneo no encontrado"}
MEMBER_NOT_FOUND = {"detail": "Miembro no encontrado"}
FIELDS = {"organization_user_id", "full_name", "organization_role_code", "role_code", "is_active",
          "adds_permissions", "assigned_at"}


@dataclass
class Team:
    client: AsyncClient
    admin: object
    owner: AuthContext
    viewer: AuthContext
    operator: AuthContext
    inactive: AuthContext
    stranger: AuthContext
    tournament_id: object
    foreign_tournament_id: object
    context: AuthContext | None = None


async def user(admin, email, name):
    return await admin.fetchval(
        "INSERT INTO users (email,password_hash,full_name) VALUES ($1,'hash',$2) RETURNING id", email, name)


@pytest.fixture
async def team(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        owner, match = await seeded_match(engine)
        stranger, foreign = await seeded_match(engine)
        admin = await connect(database_admin_url, engine.url.database)
        try:
            org = owner.organization_id
            viewer = await add_member(admin, org, await user(admin, "vera-049@example.test", "Vera Vista"), "viewer")
            operator = await add_member(admin, org, await user(admin, "oto-049@example.test", "Oto Operador"),
                                        "operator")
            inactive = await add_member(admin, org, await user(admin, "ines-049@example.test", "Inés Inactiva"),
                                        "viewer")
            await admin.execute("UPDATE organization_users SET is_active = FALSE WHERE id = $1",
                                inactive.organization_user_id)

            async def database():
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    yield session

            state = Team(None, admin, owner, viewer, operator, inactive, stranger, match.tournament_id,
                         foreign.tournament_id, owner)

            async def auth_context():
                return state.context

            api.dependency_overrides[get_db] = database
            api.dependency_overrides[get_auth_context] = auth_context
            try:
                async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
                    state.client = client
                    yield state
            finally:
                api.dependency_overrides.clear()
        finally:
            await admin.close()


def path(tournament_id, member=None):
    base = f"/api/v1/tournaments/{tournament_id}/team"
    return f"{base}/{member}" if member else base


async def audits(team, action=None):
    rows = await team.admin.fetch(
        """SELECT action, entity_type, entity_id, payload, performed_by_member_id
           FROM administrative_audit_logs
           WHERE action IN ('ASSIGN_TOURNAMENT_OPERATOR','REMOVE_TOURNAMENT_OPERATOR')
           ORDER BY performed_at, id""")
    return [dict(row, payload=json.loads(row["payload"])) for row in rows if action in (None, row["action"])]


async def rows(team):
    return await team.admin.fetchval("SELECT count(*) FROM tournament_member_roles")


async def test_assign_is_idempotent_audited_once_and_listed_without_email(team):
    member = team.viewer.organization_user_id
    created = await team.client.put(path(team.tournament_id, member))
    assert created.status_code == 201
    body = created.json()
    assert set(body) == FIELDS
    assert body | {"assigned_at": None} == {
        "organization_user_id": str(member), "full_name": "Vera Vista", "organization_role_code": "viewer",
        "role_code": "tournament_operator", "is_active": True, "adds_permissions": True, "assigned_at": None,
    }
    again = await team.client.put(path(team.tournament_id, member))
    assert again.status_code == 200
    assert again.json() == body
    assert await rows(team) == 1
    [audit] = await audits(team)
    assert audit["action"] == "ASSIGN_TOURNAMENT_OPERATOR"
    assert audit["entity_type"] == "tournaments"
    assert audit["entity_id"] == team.tournament_id
    assert audit["payload"] == {"organization_user_id": str(member), "role_code": "tournament_operator"}
    assert audit["performed_by_member_id"] == team.owner.organization_user_id

    team.context = team.viewer
    listed = await team.client.get(path(team.tournament_id))
    assert listed.status_code == 200
    assert listed.json() == [body]
    assert "@" not in listed.text


async def test_operating_roles_are_assigned_with_the_no_added_permissions_flag(team):
    for context in (team.owner, team.operator):
        response = await team.client.put(path(team.tournament_id, context.organization_user_id))
        assert response.status_code == 201
        assert response.json()["adds_permissions"] is False
    listed = (await team.client.get(path(team.tournament_id))).json()
    assert [item["full_name"] for item in listed] == sorted(item["full_name"] for item in listed)


@pytest.mark.parametrize("who", ["viewer", "operator"])
async def test_without_manage_members_writes_are_forbidden_and_change_nothing(team, who):
    await team.client.put(path(team.tournament_id, team.viewer.organization_user_id))
    team.context = getattr(team, who)
    target = team.operator.organization_user_id
    assert (await team.client.put(path(team.tournament_id, target))).status_code == 403
    assert (await team.client.delete(path(team.tournament_id, team.viewer.organization_user_id))).status_code == 403
    assert await rows(team) == 1
    assert len(await audits(team)) == 1


async def test_foreign_or_missing_tournament_gives_the_same_404(team):
    member = team.viewer.organization_user_id
    for tournament in (team.foreign_tournament_id, uuid4()):
        for response in (
            await team.client.get(path(tournament)),
            await team.client.put(path(tournament, member)),
            await team.client.delete(path(tournament, member)),
        ):
            assert response.status_code == 404
            assert response.json() == TOURNAMENT_NOT_FOUND
    team.context = team.viewer
    response = await team.client.put(path(team.foreign_tournament_id, member))
    assert (response.status_code, response.json()) == (404, TOURNAMENT_NOT_FOUND)
    assert await rows(team) == 0


async def test_inactive_foreign_or_missing_member_gives_the_same_404(team):
    await team.admin.execute("UPDATE users SET is_active = FALSE WHERE id = $1", team.operator.user_id)
    for member in (team.inactive.organization_user_id, team.operator.organization_user_id,
                   team.stranger.organization_user_id, uuid4()):
        response = await team.client.put(path(team.tournament_id, member))
        assert (response.status_code, response.json()) == (404, MEMBER_NOT_FOUND)
    assert await rows(team) == 0
    assert await audits(team) == []


async def test_removal_is_audited_and_a_second_removal_is_404(team):
    member = team.viewer.organization_user_id
    await team.client.put(path(team.tournament_id, member))
    removed = await team.client.delete(path(team.tournament_id, member))
    assert removed.status_code == 204
    assert removed.content == b""
    assert await rows(team) == 0
    [audit] = await audits(team, "REMOVE_TOURNAMENT_OPERATOR")
    assert audit["payload"] == {"organization_user_id": str(member), "role_code": "tournament_operator"}
    assert audit["entity_id"] == team.tournament_id
    again = await team.client.delete(path(team.tournament_id, member))
    assert (again.status_code, again.json()) == (404, {"detail": "Asignación no encontrada"})
    assert len(await audits(team, "REMOVE_TOURNAMENT_OPERATOR")) == 1


async def test_access_lists_the_operated_tournaments_of_an_active_member(team):
    member = team.viewer.organization_user_id
    team.context = team.viewer
    assert (await team.client.get("/api/v1/organizations/current/access")).json()["operated_tournament_ids"] == []
    team.context = team.owner
    await team.client.put(path(team.tournament_id, member))
    team.context = team.viewer
    access = (await team.client.get("/api/v1/organizations/current/access")).json()
    assert access["operated_tournament_ids"] == [str(team.tournament_id)]
    assert access["role_code"] == "viewer"
    assert "MANAGE_MEMBERS" not in access["permissions"]
    team.context = team.owner
    assert (await team.client.get("/api/v1/organizations/current/access")).json()["operated_tournament_ids"] == []
    await team.client.delete(path(team.tournament_id, member))
    team.context = team.viewer
    assert (await team.client.get("/api/v1/organizations/current/access")).json()["operated_tournament_ids"] == []


async def test_the_audit_view_shows_member_names_without_email(team):
    await team.client.put(path(team.tournament_id, team.viewer.organization_user_id))
    response = await team.client.get("/api/v1/organization-audit")
    assert response.status_code == 200
    [entry] = [item for item in response.json()["items"] if item["action"] == "ASSIGN_TOURNAMENT_OPERATOR"]
    assert entry["entity_type"] == "tournaments"
    assert {item["key"]: item["value"] for item in entry["details"]} == {
        "member": "Vera Vista", "role_code": "tournament_operator"}
    assert "@" not in json.dumps(entry)
