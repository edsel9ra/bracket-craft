"""Lecturas públicas para compartir (spec 043, T2–T3).

Opt-in con ``RUN_DATABASE_TESTS=1``. La lectura de un partido por su id debe
devolver exactamente la fila de la lista pública (incluido el suspendido de 14
claves) y el mismo 404 en cualquier otro caso, sin distinguir organizaciones.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db_helpers import clear_rls_context, set_tenant_context
from test_match_live_db import command
from test_match_live_public import public_live_db  # noqa: F401  (fixture)
from test_migration_031 import MATCH, TOURNAMENT
from test_public_access_matrix import _assert_404_indistinguishable, _public_api
from test_public_stats_endpoints import _seed_organization_stats, _skip_if_no_db

PUBLIC = "/api/v1/tournaments/public"


def _match_path(tournament_id, match_id):
    return f"{PUBLIC}/{tournament_id}/matches/{match_id}"


async def _assert_same_404(client, *paths):
    absent = await client.get(_match_path(uuid4(), uuid4()))
    _assert_404_indistinguishable(absent)
    for path in paths:
        response = await client.get(path)
        _assert_404_indistinguishable(response)
        assert response.json() == absent.json()


@pytest.mark.asyncio
async def test_match_read_equals_list_row_live_scheduled_and_suspended(public_live_db):  # noqa: F811
    f = public_live_db
    async with AsyncSession(f.engine) as db, _public_api(db) as client:
        for suspend in (False, True):
            if suspend:
                await f.call("execute", command("suspend", 2))
            rows = (await client.get(f"{PUBLIC}/{TOURNAMENT}/matches")).json()
            assert len(rows) == 4
            for row in rows:
                response = await client.get(_match_path(TOURNAMENT, row["id"]))
                assert response.status_code == 200, response.text
                assert response.json() == row
            target = next(row for row in rows if row["id"] == MATCH)
            assert target["status"] == ("suspended" if suspend else "live")
            if suspend:
                assert len(target) == 14

        cancelled = await f.admin.fetchval(
            "SELECT id FROM matches WHERE tournament_id=$1 AND status='cancelled'", TOURNAMENT
        )
        other = TOURNAMENT.replace("31000000", "32000000")
        hidden = TOURNAMENT.replace("31000000", "33000000")
        foreign_match = (await client.get(f"{PUBLIC}/{other}/matches")).json()[0]["id"]
        hidden_match = await f.admin.fetchval("SELECT id FROM matches WHERE tournament_id=$1", hidden)
        await _assert_same_404(
            client,
            _match_path(TOURNAMENT, cancelled),
            _match_path(TOURNAMENT, uuid4()),
            _match_path(TOURNAMENT, foreign_match),
            _match_path(other, MATCH),
            _match_path(hidden, hidden_match),
            _match_path(uuid4(), MATCH),
        )


@pytest.mark.asyncio
async def test_match_read_finished_row_and_organization_isolation(db_session, tenant_factory):
    _skip_if_no_db()
    first = await tenant_factory("Share A")
    second = await tenant_factory("Share B")
    await set_tenant_context(db_session, first)
    seeded_a = await _seed_organization_stats(db_session, first, label="A", scoring_side="home", goals=1)
    await set_tenant_context(db_session, second)
    seeded_b = await _seed_organization_stats(db_session, second, label="B", scoring_side="away", goals=2)
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        listed = {}
        for seeded in (seeded_a, seeded_b):
            rows = (await client.get(f"{PUBLIC}/{seeded['tournament_id']}/matches")).json()
            assert rows and all(row["status"] == "finished" for row in rows)
            for row in rows:
                response = await client.get(_match_path(seeded["tournament_id"], row["id"]))
                assert response.status_code == 200, response.text
                assert response.json() == row
            listed[seeded["tournament_id"]] = rows[0]["id"]
        await _assert_same_404(
            client,
            _match_path(seeded_a["tournament_id"], listed[seeded_b["tournament_id"]]),
            _match_path(seeded_b["tournament_id"], listed[seeded_a["tournament_id"]]),
        )


@pytest.mark.asyncio
async def test_match_read_rejects_malformed_ids(db_session):
    _skip_if_no_db()
    async with _public_api(db_session) as client:
        response = await client.get(f"{PUBLIC}/{uuid4()}/matches/not-a-uuid")
        assert response.status_code == 422
