"""Guardar la alineación sin despublicar al rival (spec 045, T2).

RF-001–RF-008 y RNF-003: al guardar un segmento, el equipo cuya alineación no
cambia conserva ``is_public`` y ``published_at``; el que cambia queda privado y
se registra una entrada ``UNPUBLISH_MATCH_LINEUP`` por cada formación retirada.

Opt-in con ``RUN_DATABASE_TESTS=1``: las rutas reales corren dentro de
``db_session`` (rol de aplicación, revertido al terminar); la concurrencia usa
una base temporal confirmada.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.matches.formations import FORMATION_SLOTS
from app.modules.matches.router import publish_match_lineup, save_match_lineup
from app.modules.matches.schemas import (
    MatchLineupEntry,
    MatchTeamLineupConfig,
    PublishMatchLineupRequest,
    SaveMatchLineupRequest,
)
from db_helpers import create_tenant_owner, set_tenant_context
from test_lineup_game_format import _match, _set_game_format
from test_match_operation_audit import (
    OperationMatch,
    _create_operation_match,
    committed_application,
    context_for,
)

FORMATS = [("11v11", "4-4-2", "4-3-3"), ("7v7", "3-2-1", "2-3-1")]


def _payload(
    match: OperationMatch,
    code: str,
    *,
    away_code: str | None = None,
    home_code: str | None = None,
    swap_home_positions: bool = False,
    swap_home_roles: bool = False,
    substitute_minute: int | None = None,
    classic: bool = False,
) -> SaveMatchLineupRequest:
    home_code = home_code or code
    away_code = away_code or code
    home_slots = list(FORMATION_SLOTS[home_code])
    away_slots = list(FORMATION_SLOTS[away_code])
    if swap_home_positions:
        home_slots[1], home_slots[2] = home_slots[2], home_slots[1]
    home_starters = list(match.home_starters[: len(home_slots)])
    home_substitutes = list(match.home_substitutes)
    if swap_home_roles:
        home_starters[-1], home_substitutes[0] = home_substitutes[0], home_starters[-1]
    entries = [
        MatchLineupEntry(roster_id=roster_id, role="starter", position_slot=None if classic else slot)
        for roster_id, slot in zip(home_starters, home_slots)
    ]
    entries += [
        MatchLineupEntry(roster_id=roster_id, role="starter", position_slot=None if classic else slot)
        for roster_id, slot in zip(match.away_starters, away_slots)
    ]
    entries += [
        MatchLineupEntry(roster_id=roster_id, role="substitute", entered_minute=substitute_minute)
        for roster_id in (*home_substitutes, *match.away_substitutes)
    ]
    return SaveMatchLineupRequest(
        segment_id=match.segment_id,
        entries=entries,
        team_lineups=[]
        if classic
        else [
            MatchTeamLineupConfig(team_id=match.home_team_id, formation_code=home_code),
            MatchTeamLineupConfig(team_id=match.away_team_id, formation_code=away_code),
        ],
    )


def _publish(match: OperationMatch, team_id: UUID, is_public: bool = True) -> PublishMatchLineupRequest:
    return PublishMatchLineupRequest(segment_id=match.segment_id, team_id=team_id, is_public=is_public)


async def _publications(session, match: OperationMatch) -> dict[UUID, tuple[bool, object]]:
    await set_tenant_context(session, match.tenant)
    rows = await session.execute(
        text("""
            SELECT team_id, is_public, published_at FROM match_team_lineups
            WHERE match_id = :match_id AND segment_id = :segment_id
        """),
        {"match_id": str(match.match_id), "segment_id": str(match.segment_id)},
    )
    return {UUID(str(row.team_id)): (row.is_public, row.published_at) for row in rows}


async def _published_match(db_session, tenant_factory, game_format: str, code: str, teams=None):
    match, api = await _match(db_session, tenant_factory, game_format)
    context = context_for(match.tenant)
    await save_match_lineup(match.match_id, _payload(match, code), context, api)
    for team_id in teams or (match.home_team_id, match.away_team_id):
        await publish_match_lineup(match.match_id, _publish(match, team_id), context, api)
    before = await _publications(db_session, match)
    return match, api, context, before, await _audit_ids(db_session, match)


async def _audit_rows_by_id(session, match: OperationMatch) -> dict[str, dict]:
    await set_tenant_context(session, match.tenant)
    rows = await session.execute(
        text("""
            SELECT id, action, payload FROM administrative_audit_logs
            WHERE entity_type = 'matches' AND entity_id = :match_id
        """),
        {"match_id": str(match.match_id)},
    )
    return {str(row.id): {"action": row.action, "payload": row.payload} for row in rows}


async def _audit_ids(session, match: OperationMatch) -> set[str]:
    return set(await _audit_rows_by_id(session, match))


async def _new_audit(db_session, match: OperationMatch, seen: set[str]) -> list[dict]:
    """Entries added after ``seen``, the save first and then by team.

    Every entry shares the transaction timestamp, so the physical order is not
    a reliable insertion order once the shared database reuses space.
    """

    rows = await _audit_rows_by_id(db_session, match)
    new = [row for row_id, row in rows.items() if row_id not in seen]
    return sorted(new, key=lambda row: (row["action"], str(row["payload"].get("team_id", ""))))


def _unpublish_entry(match: OperationMatch, team_id: UUID, code: str) -> dict:
    return {
        "segment_id": str(match.segment_id),
        "team_id": str(team_id),
        "is_public": False,
        "formation_code": code,
    }


@pytest.mark.parametrize(("game_format", "code", "_other"), FORMATS)
async def test_saving_without_changes_keeps_both_publications(db_session, tenant_factory, game_format, code, _other):
    match, api, context, before, seen = await _published_match(db_session, tenant_factory, game_format, code)

    await save_match_lineup(match.match_id, _payload(match, code), context, api)

    assert await _publications(db_session, match) == before
    assert all(is_public for is_public, _ in before.values())
    assert await _new_audit(db_session, match, seen) == []


@pytest.mark.parametrize(("game_format", "code", "_other"), FORMATS)
@pytest.mark.parametrize("change", ["swap_home_positions", "swap_home_roles"])
async def test_changing_one_team_keeps_the_rival_publication(
    db_session, tenant_factory, game_format, code, _other, change
):
    match, api, context, before, seen = await _published_match(db_session, tenant_factory, game_format, code)

    await save_match_lineup(match.match_id, _payload(match, code, **{change: True}), context, api)

    after = await _publications(db_session, match)
    assert after[match.away_team_id] == before[match.away_team_id]
    assert after[match.home_team_id] == (False, None)
    entries = await _new_audit(db_session, match, seen)
    assert [entry["action"] for entry in entries] == ["SAVE_MATCH_LINEUP", "UNPUBLISH_MATCH_LINEUP"]
    assert entries[1]["payload"] == _unpublish_entry(match, match.home_team_id, code)


@pytest.mark.parametrize(("game_format", "code", "other"), FORMATS)
async def test_changing_both_teams_withdraws_both(db_session, tenant_factory, game_format, code, other):
    match, api, context, _before, seen = await _published_match(db_session, tenant_factory, game_format, code)

    await save_match_lineup(match.match_id, _payload(match, other), context, api)

    after = await _publications(db_session, match)
    assert set(after.values()) == {(False, None)}
    entries = await _new_audit(db_session, match, seen)
    teams = sorted([match.home_team_id, match.away_team_id], key=str)
    assert [entry["action"] for entry in entries] == ["SAVE_MATCH_LINEUP"] + ["UNPUBLISH_MATCH_LINEUP"] * 2
    assert [entry["payload"] for entry in entries[1:]] == [_unpublish_entry(match, team, code) for team in teams]


@pytest.mark.parametrize(("game_format", "code", "_other"), FORMATS)
async def test_the_classic_planilla_withdraws_both_publications(db_session, tenant_factory, game_format, code, _other):
    match, api, context, _before, seen = await _published_match(db_session, tenant_factory, game_format, code)

    await save_match_lineup(match.match_id, _payload(match, code, classic=True), context, api)

    assert await _publications(db_session, match) == {}
    entries = await _new_audit(db_session, match, seen)
    assert [entry["action"] for entry in entries] == ["SAVE_MATCH_LINEUP"] + ["UNPUBLISH_MATCH_LINEUP"] * 2


@pytest.mark.parametrize(("game_format", "code", "_other"), FORMATS)
async def test_minutes_only_keep_the_publications_but_audit_the_save(
    db_session, tenant_factory, game_format, code, _other
):
    match, api, context, before, seen = await _published_match(db_session, tenant_factory, game_format, code)

    await save_match_lineup(match.match_id, _payload(match, code, substitute_minute=60), context, api)

    assert await _publications(db_session, match) == before
    assert [entry["action"] for entry in await _new_audit(db_session, match, seen)] == ["SAVE_MATCH_LINEUP"]


async def test_a_private_team_that_changes_leaves_no_unpublish_entry(db_session, tenant_factory):
    match, api, context, before, seen = await _published_match(
        db_session, tenant_factory, "7v7", "3-2-1", teams=None
    )
    await publish_match_lineup(match.match_id, _publish(match, match.home_team_id, False), context, api)
    seen = await _audit_ids(db_session, match)

    await save_match_lineup(match.match_id, _payload(match, "3-2-1", swap_home_positions=True), context, api)

    after = await _publications(db_session, match)
    assert after[match.away_team_id] == before[match.away_team_id]
    assert after[match.home_team_id] == (False, None)
    assert [entry["action"] for entry in await _new_audit(db_session, match, seen)] == ["SAVE_MATCH_LINEUP"]


async def test_a_formation_of_another_format_must_change_and_is_withdrawn(db_session, tenant_factory):
    """Caso límite 5: la formación ajena hay que cambiarla, así que ese equipo cambia."""

    match, api, context, before, seen = await _published_match(db_session, tenant_factory, "11v11", "4-4-2")
    await publish_match_lineup(match.match_id, _publish(match, match.home_team_id, False), context, api)
    await _set_game_format(db_session, match, "7v7")
    seen = await _audit_ids(db_session, match)

    await save_match_lineup(match.match_id, _payload(match, "3-2-1"), context, api)

    after = await _publications(db_session, match)
    assert set(after.values()) == {(False, None)}
    entries = await _new_audit(db_session, match, seen)
    assert [entry["payload"]["team_id"] for entry in entries if entry["action"] == "UNPUBLISH_MATCH_LINEUP"] == [
        str(match.away_team_id)
    ]


async def test_an_inactive_segment_still_rejects_without_touching_publications(db_session, tenant_factory):
    match, api, context, before, seen = await _published_match(db_session, tenant_factory, "11v11", "4-4-2")
    payload = _payload(match, "4-4-2", swap_home_positions=True).model_copy(
        update={"segment_id": match.completed_segment_id}
    )

    with pytest.raises(HTTPException) as error:
        await save_match_lineup(match.match_id, payload, context, api)

    assert error.value.status_code == 409
    assert await _publications(db_session, match) == before
    assert await _new_audit(db_session, match, seen) == []


async def test_another_organization_cannot_save_or_unpublish(db_session, tenant_factory):
    match, api, _context, before, seen = await _published_match(db_session, tenant_factory, "11v11", "4-4-2")
    intruder = await tenant_factory("045 intruder")

    with pytest.raises(HTTPException) as error:
        await save_match_lineup(
            match.match_id, _payload(match, "4-4-2", swap_home_positions=True), context_for(intruder), api
        )

    assert error.value.status_code == 404
    assert await _publications(db_session, match) == before
    assert await _new_audit(db_session, match, seen) == []


async def test_a_publication_waits_for_a_concurrent_save_and_sees_its_result(database_admin_url):
    """RNF-003: guardar y publicar se serializan sobre el partido."""

    async with committed_application(database_admin_url) as engine:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tenant = await create_tenant_owner(session, full_name="045 concurrent")
            match = await _create_operation_match(session, tenant)
            await _set_game_format(session, match, "7v7")
            await session.commit()
        context = context_for(tenant)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await save_match_lineup(match.match_id, _payload(match, "3-2-1"), context, session)
        for team_id in (match.home_team_id, match.away_team_id):
            async with AsyncSession(engine, expire_on_commit=False) as session:
                await publish_match_lineup(match.match_id, _publish(match, team_id), context, session)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = await _publications(session, match)

        async with engine.connect() as connection:
            outer = await connection.begin()
            saver = AsyncSession(bind=connection, expire_on_commit=False)

            class _Nested:
                def begin(self):
                    return saver.begin_nested()

                def __getattr__(self, name):
                    return getattr(saver, name)

            await save_match_lineup(
                match.match_id, _payload(match, "3-2-1", swap_home_positions=True), context, _Nested()
            )
            async with AsyncSession(engine, expire_on_commit=False) as publisher:
                blocked = asyncio.create_task(
                    publish_match_lineup(match.match_id, _publish(match, match.home_team_id), context, publisher)
                )
                await asyncio.sleep(0.5)
                assert not blocked.done(), "publicar debe esperar al guardado en curso"
                await outer.commit()
                published = await asyncio.wait_for(blocked, timeout=10)
            await saver.close()

        assert published["is_public"] is True
        async with AsyncSession(engine, expire_on_commit=False) as reader:
            await set_rls_context(reader, tenant.organization_id, tenant.user_id)
            after = await _publications(reader, match)
        assert after[match.away_team_id] == before[match.away_team_id]
        assert after[match.home_team_id][0] is True
