"""Guardar y publicar formaciones por modalidad (spec 044, T2: RF-002, RF-003, RF-009, RF-010).

Opt-in con ``RUN_DATABASE_TESTS=1``: llama a las rutas reales dentro de
``db_session`` (rol de aplicación, revertido al terminar) reutilizando el
partido de operación de ``test_match_operation_audit``.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from app.core.database import set_rls_context
from app.modules.matches.errors import FORMATION_NOT_SUPPORTED_FOR_FORMAT
from app.modules.matches.formations import FORMATION_SLOTS, FORMATIONS_BY_GAME_FORMAT
from app.modules.matches.router import publish_match_lineup, save_match_lineup
from app.modules.matches.schemas import (
    MatchLineupEntry,
    MatchTeamLineupConfig,
    PublishMatchLineupRequest,
    SaveMatchLineupRequest,
)
from db_helpers import set_tenant_context
from test_match_operation_audit import (
    OperationMatch,
    _create_operation_match,
    _NestedSession,
    context_for,
)


async def _set_game_format(session, match: OperationMatch, game_format: str | None) -> None:
    config = {} if game_format is None else {"game_format": game_format}
    await set_tenant_context(session, match.tenant)
    await session.execute(
        text("UPDATE tournament_versions SET rules_config = CAST(:config AS jsonb) WHERE id = :id"),
        {"config": json.dumps(config), "id": str(match.version_id)},
    )


def _payload(
    match: OperationMatch,
    code: str,
    *,
    home_slots: list[str | None] | None = None,
) -> SaveMatchLineupRequest:
    slots = list(FORMATION_SLOTS[code])
    home = slots if home_slots is None else home_slots
    entries = [
        MatchLineupEntry(roster_id=roster_id, role="starter", position_slot=slot)
        for roster_id, slot in zip(match.home_starters, home)
    ]
    entries += [
        MatchLineupEntry(roster_id=roster_id, role="starter", position_slot=slot)
        for roster_id, slot in zip(match.away_starters, slots)
    ]
    entries += [
        MatchLineupEntry(roster_id=roster_id, role="substitute")
        for roster_id in (*match.home_substitutes, *match.away_substitutes)
    ]
    return SaveMatchLineupRequest(
        segment_id=match.segment_id,
        entries=entries,
        team_lineups=[
            MatchTeamLineupConfig(team_id=match.home_team_id, formation_code=code),
            MatchTeamLineupConfig(team_id=match.away_team_id, formation_code=code),
        ],
    )


def _publish(match: OperationMatch, is_public: bool = True) -> PublishMatchLineupRequest:
    return PublishMatchLineupRequest(segment_id=match.segment_id, team_id=match.home_team_id, is_public=is_public)


async def _stored(session, match: OperationMatch) -> list[tuple]:
    await set_tenant_context(session, match.tenant)
    rows = await session.execute(
        text("""
            SELECT team_id, formation_code, is_public FROM match_team_lineups
            WHERE match_id = :match_id ORDER BY team_id
        """),
        {"match_id": str(match.match_id)},
    )
    return [tuple(row) for row in rows.all()]


async def _snapshot_count(session, match: OperationMatch) -> int:
    await set_tenant_context(session, match.tenant)
    return (
        await session.execute(
            text("SELECT count(*) FROM match_lineup_snapshots WHERE match_id = :match_id"),
            {"match_id": str(match.match_id)},
        )
    ).scalar_one()


async def _match(db_session, tenant_factory, game_format: str | None) -> tuple[OperationMatch, _NestedSession]:
    tenant = await tenant_factory("044 formats")
    match = await _create_operation_match(db_session, tenant)
    await _set_game_format(db_session, match, game_format)
    return match, _NestedSession(db_session)


@pytest.mark.parametrize("code", [code for codes in FORMATIONS_BY_GAME_FORMAT.values() for code in codes])
def test_the_request_accepts_the_thirteen_codes(code):
    assert MatchTeamLineupConfig(team_id=uuid4(), formation_code=code).formation_code == code


@pytest.mark.parametrize("code", ["4-5-1", "1-1-1", "3-3-1", ""])
def test_the_request_rejects_codes_outside_the_catalog(code):
    with pytest.raises(ValidationError):
        MatchTeamLineupConfig(team_id=uuid4(), formation_code=code)


def _all_formats():
    return [(fmt, code) for fmt, codes in FORMATIONS_BY_GAME_FORMAT.items() for code in codes]


@pytest.mark.parametrize(("game_format", "code"), _all_formats())
async def test_each_format_saves_and_publishes_its_own_formations(db_session, tenant_factory, game_format, code):
    match, api = await _match(db_session, tenant_factory, game_format)
    context = context_for(match.tenant)

    await save_match_lineup(match.match_id, _payload(match, code), context, api)
    published = await publish_match_lineup(match.match_id, _publish(match), context, api)

    assert published["is_public"] is True
    assert published["formation_code"] == code
    stored = await _stored(db_session, match)
    assert {row[1] for row in stored} == {code}


async def test_absent_game_format_reads_as_eleven_a_side(db_session, tenant_factory):
    match, api = await _match(db_session, tenant_factory, None)
    context = context_for(match.tenant)
    await save_match_lineup(match.match_id, _payload(match, "4-4-2"), context, api)
    assert (await publish_match_lineup(match.match_id, _publish(match), context, api))["is_public"] is True

    with pytest.raises(HTTPException) as error:
        await save_match_lineup(match.match_id, _payload(match, "2-2"), context, api)
    assert error.value.status_code == 409
    assert getattr(error.value, "code", None) == FORMATION_NOT_SUPPORTED_FOR_FORMAT


@pytest.mark.parametrize(
    ("game_format", "code"),
    [("7v7", "4-3-3"), ("11v11", "2-3-1"), ("5v5", "3-3-2"), ("9v9", "3-2-1")],
)
async def test_a_formation_of_another_format_is_rejected_without_writing(
    db_session, tenant_factory, game_format, code
):
    match, api = await _match(db_session, tenant_factory, game_format)

    with pytest.raises(HTTPException) as error:
        await save_match_lineup(match.match_id, _payload(match, code), context_for(match.tenant), api)

    assert error.value.status_code == 409
    assert getattr(error.value, "code", None) == FORMATION_NOT_SUPPORTED_FOR_FORMAT
    assert await _stored(db_session, match) == []
    assert await _snapshot_count(db_session, match) == 0


@pytest.mark.parametrize(
    "home_slots",
    [
        # One starter too many for 7v7: the eighth has no position.
        ["GK", "LCB", "CB", "RCB", "LCM", "RCM", "ST", None],
        # One starter too few.
        ["GK", "LCB", "CB", "RCB", "LCM", "RCM"],
        # A position that is not in 3-2-1.
        ["GK", "LCB", "CB", "RCB", "LCM", "RCM", "LW"],
        # A repeated position.
        ["GK", "LCB", "CB", "RCB", "LCM", "LCM", "ST"],
    ],
)
async def test_starters_must_match_the_format_and_the_formation(db_session, tenant_factory, home_slots):
    match, api = await _match(db_session, tenant_factory, "7v7")

    with pytest.raises(HTTPException) as error:
        await save_match_lineup(
            match.match_id, _payload(match, "3-2-1", home_slots=home_slots), context_for(match.tenant), api
        )

    assert error.value.status_code == 422
    assert await _stored(db_session, match) == []


async def test_the_starter_count_message_names_the_format_starters(db_session, tenant_factory):
    match, api = await _match(db_session, tenant_factory, "5v5")
    with pytest.raises(HTTPException) as error:
        await save_match_lineup(
            match.match_id,
            _payload(match, "2-2", home_slots=["GK", "LCB", "RCB", "ST_L"]),
            context_for(match.tenant),
            api,
        )
    assert error.value.status_code == 422
    assert "5 titulares" in error.value.detail


async def test_a_stored_formation_of_a_previous_format_cannot_be_published_but_can_be_unpublished(
    db_session, tenant_factory
):
    match, api = await _match(db_session, tenant_factory, "11v11")
    context = context_for(match.tenant)
    await save_match_lineup(match.match_id, _payload(match, "4-3-3"), context, api)
    await publish_match_lineup(match.match_id, _publish(match), context, api)
    await _set_game_format(db_session, match, "7v7")

    unpublished = await publish_match_lineup(match.match_id, _publish(match, False), context, api)
    assert unpublished["is_public"] is False

    with pytest.raises(HTTPException) as error:
        await publish_match_lineup(match.match_id, _publish(match), context, api)
    assert error.value.status_code == 409
    assert getattr(error.value, "code", None) == FORMATION_NOT_SUPPORTED_FOR_FORMAT
    assert all(row[2] is False for row in await _stored(db_session, match))


async def test_publication_requires_the_starters_of_the_format(db_session, tenant_factory):
    match, api = await _match(db_session, tenant_factory, "9v9")
    context = context_for(match.tenant)
    await save_match_lineup(match.match_id, _payload(match, "3-4-1"), context, api)
    await set_tenant_context(db_session, match.tenant)
    await db_session.execute(
        text("""
            DELETE FROM match_lineup_snapshots
            WHERE match_id = :match_id AND team_id = :team_id AND position_slot = 'ST'
        """),
        {"match_id": str(match.match_id), "team_id": str(match.home_team_id)},
    )

    with pytest.raises(HTTPException) as error:
        await publish_match_lineup(match.match_id, _publish(match), context, api)
    assert error.value.status_code == 409
    assert "9 titulares" in error.value.detail
    assert all(row[2] is False for row in await _stored(db_session, match))


async def test_another_organization_cannot_save_or_publish(db_session, tenant_factory):
    match, api = await _match(db_session, tenant_factory, "7v7")
    other = await tenant_factory("044 other")

    with pytest.raises(HTTPException) as error:
        await save_match_lineup(match.match_id, _payload(match, "3-2-1"), context_for(other), api)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        await publish_match_lineup(match.match_id, _publish(match), context_for(other), api)
    assert error.value.status_code == 404
    await set_rls_context(db_session, match.tenant.organization_id, match.tenant.user_id)
    assert await _stored(db_session, match) == []
