"""Lecturas públicas para compartir (spec 043, T2–T3).

Opt-in con ``RUN_DATABASE_TESTS=1``. La lectura de un partido por su id debe
devolver exactamente la fila de la lista pública (incluido el suspendido de 14
claves) y el mismo 404 en cualquier otro caso, sin distinguir organizaciones.
"""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tournaments import share_image
from app.modules.tournaments.share_image import BRAND_FALLBACK_PATH
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


# ---------------------------------------------------------------------------
# T3 — imágenes de vista previa
# ---------------------------------------------------------------------------


def _assert_png(response, expected: bytes | None = None):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=600"
    assert "set-cookie" not in response.headers
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG" and image.size == (1200, 630)
    if expected is not None:
        assert response.content == expected


@pytest.mark.asyncio
async def test_share_image_brand_and_tournament(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Share image")
    await set_tenant_context(db_session, tenant)
    seeded = await _seed_organization_stats(db_session, tenant, label="I", scoring_side="home", goals=1)
    await clear_rls_context(db_session)
    tid = seeded["tournament_id"]
    async with _public_api(db_session) as client:
        for lang in ("es", "en"):
            _assert_png(await client.get(f"{PUBLIC}/share-image?lang={lang}"), share_image.brand_card(lang))
            detail = (await client.get(f"{PUBLIC}/{tid}")).json()
            _assert_png(
                await client.get(f"{PUBLIC}/{tid}/share-image?lang={lang}"),
                share_image.tournament_card(
                    name=detail["name"], season=detail["season"], status=detail["status"], lang=lang
                ),
            )
        _assert_png(await client.get(f"{PUBLIC}/{tid}/share-image"), share_image.tournament_card(
            name=detail["name"], season=detail["season"], status=detail["status"], lang="es"))
        for path in (f"{PUBLIC}/share-image?lang=fr", f"{PUBLIC}/{tid}/share-image?lang=xx",
                     f"{PUBLIC}/{tid}/matches/{uuid4()}/share-image?lang=de"):
            assert (await client.get(path)).status_code == 422
        absent = await client.get(f"{PUBLIC}/{uuid4()}/share-image")
        _assert_404_indistinguishable(absent)


@pytest.mark.asyncio
async def test_share_image_result_final_walkover_and_isolation(db_session, tenant_factory):
    _skip_if_no_db()
    first = await tenant_factory("Share result A")
    second = await tenant_factory("Share result B")
    await set_tenant_context(db_session, first)
    seeded_a = await _seed_organization_stats(db_session, first, label="A", scoring_side="home", goals=2)
    await set_tenant_context(db_session, second)
    seeded_b = await _seed_organization_stats(db_session, second, label="B", scoring_side="away", goals=1)
    await clear_rls_context(db_session)
    tid_a, tid_b = seeded_a["tournament_id"], seeded_b["tournament_id"]

    async with _public_api(db_session) as client:
        name_a = (await client.get(f"{PUBLIC}/{tid_a}")).json()["name"]
        rows = (await client.get(f"{PUBLIC}/{tid_a}/matches")).json()
        assert rows and {row["status"] for row in rows} == {"finished"}
        for row in rows:
            for lang in ("es", "en"):
                _assert_png(
                    await client.get(f"{PUBLIC}/{tid_a}/matches/{row['id']}/share-image?lang={lang}"),
                    share_image.result_card(
                        tournament_name=name_a, home_team=row["home_team_name"],
                        away_team=row["away_team_name"], home_score=row["home_score"],
                        away_score=row["away_score"], home_penalties=row["home_penalties"],
                        away_penalties=row["away_penalties"], lang=lang,
                    ),
                )
        foreign = (await client.get(f"{PUBLIC}/{tid_b}/matches")).json()[0]["id"]
        await _assert_same_share_404(
            client,
            f"{PUBLIC}/{tid_a}/matches/{foreign}/share-image",
            f"{PUBLIC}/{tid_b}/matches/{rows[0]['id']}/share-image",
            f"{PUBLIC}/{tid_a}/matches/{uuid4()}/share-image",
            f"{PUBLIC}/{uuid4()}/matches/{rows[0]['id']}/share-image",
        )


async def _assert_same_share_404(client, *paths):
    absent = await client.get(f"{PUBLIC}/{uuid4()}/share-image")
    _assert_404_indistinguishable(absent)
    for path in paths:
        response = await client.get(path)
        _assert_404_indistinguishable(response)
        assert response.json() == absent.json()
        assert response.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_share_image_not_shareable_states_and_hidden(public_live_db):  # noqa: F811
    f = public_live_db
    hidden = TOURNAMENT.replace("31000000", "33000000")
    hidden_match = await f.admin.fetchval("SELECT id FROM matches WHERE tournament_id=$1", hidden)
    cancelled = await f.admin.fetchval(
        "SELECT id FROM matches WHERE tournament_id=$1 AND status='cancelled'", TOURNAMENT
    )
    # La versión publicada es inmutable: el administrador de la base desechable
    # inserta sin disparadores un walkover y un partido con un equipo sin definir.
    await f.admin.execute("SET session_replication_role = replica")
    walkover = await f.admin.fetchval("""
        INSERT INTO matches
            (organization_id, tournament_id, tournament_version_id, stage_id,
             home_team_id, away_team_id, status, matchday,
             home_score_regular, away_score_regular, home_score, away_score,
             winner_team_id, resolution_type, result_confirmed)
        SELECT organization_id, tournament_id, tournament_version_id, stage_id,
               home_team_id, away_team_id, 'administrative_resolution', 8,
               3, 0, 3, 0, home_team_id, 'walkover', TRUE
        FROM matches WHERE id = $1
        RETURNING id
    """, MATCH)
    undefined = await f.admin.fetchval("""
        INSERT INTO matches
            (organization_id, tournament_id, tournament_version_id, stage_id,
             home_team_id, away_team_id, status, matchday)
        SELECT organization_id, tournament_id, tournament_version_id, stage_id,
               home_team_id, NULL, 'scheduled', 9
        FROM matches WHERE id = $1
        RETURNING id
    """, MATCH)
    await f.admin.execute("SET session_replication_role = DEFAULT")
    async with AsyncSession(f.engine) as db, _public_api(db) as client:
        rows = (await client.get(f"{PUBLIC}/{TOURNAMENT}/matches")).json()
        name = (await client.get(f"{PUBLIC}/{TOURNAMENT}")).json()["name"]
        row = next(r for r in rows if r["id"] == str(walkover))
        assert row["status"] == "administrative_resolution"
        _assert_png(
            await client.get(f"{PUBLIC}/{TOURNAMENT}/matches/{walkover}/share-image"),
            share_image.result_card(
                tournament_name=name, home_team=row["home_team_name"],
                away_team=row["away_team_name"], home_score=3, away_score=0,
                home_penalties=None, away_penalties=None, lang="es",
            ),
        )
        scheduled = [row["id"] for row in rows if row["status"] == "scheduled"]
        assert scheduled and str(undefined) in scheduled
        live_paths = [f"{PUBLIC}/{TOURNAMENT}/matches/{MATCH}/share-image"]
        await _assert_same_share_404(
            client,
            *live_paths,
            *(f"{PUBLIC}/{TOURNAMENT}/matches/{mid}/share-image" for mid in scheduled),
            f"{PUBLIC}/{TOURNAMENT}/matches/{cancelled}/share-image",
            f"{PUBLIC}/{hidden}/share-image",
            f"{PUBLIC}/{hidden}/matches/{hidden_match}/share-image",
        )
        await f.call("execute", command("suspend", 2))
        assert next(r for r in (await client.get(f"{PUBLIC}/{TOURNAMENT}/matches")).json()
                    if r["id"] == MATCH)["status"] == "suspended"
        await _assert_same_share_404(client, *live_paths)


@pytest.mark.asyncio
async def test_share_image_render_failure_serves_brand_fallback(db_session, tenant_factory, monkeypatch, caplog):
    _skip_if_no_db()
    tenant = await tenant_factory("Share fallback")
    await set_tenant_context(db_session, tenant)
    seeded = await _seed_organization_stats(db_session, tenant, label="F", scoring_side="home", goals=1)
    await clear_rls_context(db_session)
    tid = seeded["tournament_id"]

    def boom(*args, **kwargs):
        raise RuntimeError("render roto")

    for name in ("brand_card", "tournament_card", "result_card"):
        monkeypatch.setattr(share_image, name, boom)
    fallback = BRAND_FALLBACK_PATH.read_bytes()
    async with _public_api(db_session) as client:
        match_id = (await client.get(f"{PUBLIC}/{tid}/matches")).json()[0]["id"]
        detail = (await client.get(f"{PUBLIC}/{tid}")).json()
        caplog.clear()
        for path in (f"{PUBLIC}/share-image", f"{PUBLIC}/{tid}/share-image",
                     f"{PUBLIC}/{tid}/matches/{match_id}/share-image?lang=en"):
            _assert_png(await client.get(path), fallback)
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in messages
    assert detail["name"] not in messages and "render roto" not in messages
