"""Cambio de formato con formaciones publicadas (spec 044, T3: RF-004).

Opt-in con ``RUN_DATABASE_TESTS=1``: llama a la ruta real de reglas dentro de
``db_session`` sobre el partido de operación de ``test_match_operation_audit``.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.matches.errors import (
    FORMATION_NOT_SUPPORTED_FOR_FORMAT,
    PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED,
)
from app.modules.matches.router import publish_match_lineup, save_match_lineup
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.rules_engine.schemas import UpdateRulesConfigRequest
from app.modules.tournaments.routes.versions import _update_version_rules_record
from db_helpers import create_tenant_owner, set_tenant_context
from test_lineup_game_format import _match, _payload, _publish, _set_game_format
from test_match_operation_audit import (
    OperationMatch,
    _create_operation_match,
    committed_application,
    context_for,
)


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


async def test_publication_waits_for_a_concurrent_format_change_and_then_rejects(database_admin_url):
    """RF-004/RF-010: publicar bloquea la versión antes que el partido.

    Si una edición de reglas tiene la versión bloqueada para cambiar a otra
    modalidad, la publicación espera a que termine y valida con el formato nuevo,
    así nunca queda pública una formación de la modalidad sustituida.
    """

    async with committed_application(database_admin_url) as engine:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tenant = await create_tenant_owner(session, full_name="044 concurrent")
            match = await _create_operation_match(session, tenant)
            await _set_game_format(session, match, "7v7")
            await session.commit()
        context = context_for(tenant)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await save_match_lineup(match.match_id, _payload(match, "3-2-1"), context, session)

        async with AsyncSession(engine, expire_on_commit=False) as editor:
            await set_rls_context(editor, tenant.organization_id, tenant.user_id)
            await editor.execute(
                text("SELECT id FROM tournament_versions WHERE id = :id FOR UPDATE"),
                {"id": str(match.version_id)},
            )
            await editor.execute(
                text("""
                    UPDATE tournament_versions
                    SET rules_config = jsonb_set(rules_config, '{game_format}', '"5v5"')
                    WHERE id = :id
                """),
                {"id": str(match.version_id)},
            )

            async with AsyncSession(engine, expire_on_commit=False) as publisher:
                blocked = asyncio.create_task(
                    publish_match_lineup(match.match_id, _publish(match), context, publisher)
                )
                await asyncio.sleep(0.5)
                assert not blocked.done(), "publicar debe esperar al cambio de formato en curso"
                await editor.commit()
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(blocked, timeout=10)

        assert error.value.status_code == 409
        assert getattr(error.value, "code", None) == FORMATION_NOT_SUPPORTED_FOR_FORMAT
        async with AsyncSession(engine, expire_on_commit=False) as reader:
            await set_rls_context(reader, tenant.organization_id, tenant.user_id)
            public = (
                await reader.execute(
                    text("SELECT count(*) FROM match_team_lineups WHERE match_id = :id AND is_public"),
                    {"id": str(match.match_id)},
                )
            ).scalar_one()
        assert public == 0
