"""Operador del torneo en el partido en vivo y el tiempo real (spec 049, RF-004, RF-008, RF-010).

Contra PostgreSQL real con todas las migraciones: un observador sin permisos
de organización asignado como operador del torneo del partido ve, opera y
cierra el borrador en vivo y recibe ``MATCH_LIVE_UPDATED``. Asignado a otro
torneo no recibe nada; al retirarle el rol o desactivarlo, el comando
siguiente da 403 y ``authorize_realtime_recipients`` pasa de ``ALLOW`` a ``DENY``.

Opt-in: ``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from test_match_live_db import command, live_service_db as live_service_db
from test_migration_031 import TOURNAMENT
from test_migration_056 import MATCH, MEMBER, ORG, app, decisions


async def as_viewer(f) -> None:
    await f.admin.execute(
        """UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='viewer'),
           permissions='[]'::jsonb WHERE organization_id=$1""",
        ORG,
    )


async def assign(f, tournament=TOURNAMENT) -> None:
    await f.admin.execute(
        """INSERT INTO tournament_member_roles
           (organization_id, tournament_id, organization_user_id, role_code, created_by_member_id)
           VALUES ($1, $2, $3, 'tournament_operator', $3)""",
        ORG, tournament, MEMBER,
    )


async def other_tournament(f) -> str:
    return str(await f.admin.fetchval(
        """INSERT INTO tournaments (organization_id, name, season, start_date, status)
           VALUES ($1, '049 B', '2026', '2026-01-01', 'draft') RETURNING id""",
        ORG,
    ))


async def realtime(f) -> str:
    async with app(f.admin):
        return (await decisions(f.admin, f.session_id))[0]["decision"]


async def capabilities(f) -> tuple[bool, bool, bool]:
    access = await f.call("access")
    return access.can_view, access.can_operate, access.can_close


async def test_operator_of_the_tournament_views_operates_and_closes(live_service_db):
    f = live_service_db
    await as_viewer(f)
    assert await capabilities(f) == (False, False, False)
    assert await realtime(f) == "DENY"
    await assign(f)
    assert await capabilities(f) == (True, True, True)
    assert await realtime(f) == "ALLOW"


async def test_operator_of_another_tournament_gets_nothing(live_service_db):
    f = live_service_db
    await as_viewer(f)
    await assign(f, await other_tournament(f))
    assert await capabilities(f) == (False, False, False)
    assert await realtime(f) == "DENY"
    await f.admin.execute("UPDATE matches SET status='scheduled' WHERE id=$1", MATCH)
    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("start"))
    assert error.value.status_code == 403


async def test_command_is_accepted_and_removal_cuts_the_next_one(live_service_db):
    f = live_service_db
    await as_viewer(f)
    await assign(f)
    await f.admin.execute("UPDATE matches SET status='scheduled' WHERE id=$1", MATCH)
    ack = await f.call("execute", command("start"))
    assert ack.revision == 1
    assert await realtime(f) == "ALLOW"

    await f.admin.execute("DELETE FROM tournament_member_roles WHERE organization_user_id=$1", MEMBER)

    with pytest.raises(HTTPException) as error:
        await f.call("execute", command("start", revision=1))
    assert error.value.status_code == 403
    assert await realtime(f) == "DENY"
    assert await capabilities(f) == (False, False, False)
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_commands") == 1


async def test_deactivation_cuts_the_draft_and_reactivation_restores_it(live_service_db):
    f = live_service_db
    await as_viewer(f)
    await assign(f)
    await f.admin.execute("UPDATE organization_users SET is_active=false WHERE id=$1", MEMBER)
    assert await realtime(f) == "DENY"
    await f.admin.execute("UPDATE organization_users SET is_active=true WHERE id=$1", MEMBER)
    assert await realtime(f) == "ALLOW"
    assert await capabilities(f) == (True, True, True)
