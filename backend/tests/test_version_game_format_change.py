"""Cambio de formato con formaciones publicadas (spec 044, T3: RF-004).

Opt-in con ``RUN_DATABASE_TESTS=1``: llama a la ruta real de reglas dentro de
``db_session`` sobre el partido de operación de ``test_match_operation_audit``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.modules.matches.errors import PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED
from app.modules.matches.router import publish_match_lineup, save_match_lineup
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.schemas import UpdateRulesConfigRequest
from app.modules.tournaments.routes.versions import _update_version_rules_record
from db_helpers import set_tenant_context
from test_lineup_game_format import _match, _payload, _publish
from test_match_operation_audit import OperationMatch, context_for


def _rules(game_format: str) -> UpdateRulesConfigRequest:
    return UpdateRulesConfigRequest(rules_config={**DEFAULT_RULES_CONFIG, "game_format": game_format})


async def _stored_format(session, match: OperationMatch) -> str | None:
    await set_tenant_context(session, match.tenant)
    return (
        await session.execute(
            text("SELECT rules_config ->> 'game_format' FROM tournament_versions WHERE id = :id"),
            {"id": str(match.version_id)},
        )
    ).scalar_one()


async def _prepare(db_session, tenant_factory, game_format: str, code: str, *, publish: bool):
    match, api = await _match(db_session, tenant_factory, game_format)
    context = context_for(match.tenant)
    await save_match_lineup(match.match_id, _payload(match, code), context, api)
    if publish:
        await publish_match_lineup(match.match_id, _publish(match), context, api)
    return match, api


@pytest.mark.parametrize(
    ("current", "code", "target"),
    [("7v7", "3-2-1", "5v5"), ("7v7", "2-3-1", "11v11"), ("11v11", "4-3-3", "9v9"), ("5v5", "2-2", "7v7")],
)
async def test_a_public_formation_of_another_format_blocks_the_change(
    db_session, tenant_factory, current, code, target
):
    match, api = await _prepare(db_session, tenant_factory, current, code, publish=True)

    with pytest.raises(HTTPException) as error:
        await _update_version_rules_record(
            api, context_for(match.tenant), match.tournament_id, match.version_id, _rules(target)
        )

    assert error.value.status_code == 409
    assert getattr(error.value, "code", None) == PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED
    assert await _stored_format(db_session, match) == current


@pytest.mark.parametrize(("game_format", "code"), [("9v9", "3-4-1"), ("7v7", "3-1-2"), ("11v11", "4-4-2")])
async def test_keeping_the_format_of_the_public_formation_is_allowed(db_session, tenant_factory, game_format, code):
    match, api = await _prepare(db_session, tenant_factory, game_format, code, publish=True)

    result = await _update_version_rules_record(
        api, context_for(match.tenant), match.tournament_id, match.version_id, _rules(game_format)
    )

    assert result["rules_config"]["game_format"] == game_format


@pytest.mark.parametrize(("current", "code", "target"), [("7v7", "3-2-1", "5v5"), ("9v9", "3-3-2", "11v11")])
async def test_private_formations_do_not_block_the_change(db_session, tenant_factory, current, code, target):
    match, api = await _prepare(db_session, tenant_factory, current, code, publish=False)

    result = await _update_version_rules_record(
        api, context_for(match.tenant), match.tournament_id, match.version_id, _rules(target)
    )

    assert result["rules_config"]["game_format"] == target
    assert await _stored_format(db_session, match) == target
