"""Autorización por partido del operador del torneo (spec 049, RF-001, RF-001a, RF-002, RF-008, RF-009).

Contra PostgreSQL real: un observador (rol ``viewer``, sin permisos de
organización) asignado como operador del torneo A opera y cierra los partidos de
A, incluida la apertura de la sanción por roja al cerrar; en el torneo B, en la
resolución administrativa y en ``MANAGE_TOURNAMENTS`` sigue recibiendo 403.
Desactivar al miembro corta el acceso y reactivarlo lo devuelve (RF-007).

Opt-in: ``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.core.permissions import require_administrative_resolution, require_permission
from app.modules.matches.router import (
    assign_match_official,
    get_suspension_warnings,
    interrupt_match_segment,
    save_match_lineup,
)
from app.modules.matches.schemas import (
    InterruptMatchSegmentRequest,
    MatchEventPayload,
    OfficialAssignmentRequest,
    SaveMatchLineupRequest,
)
from app.modules.matches.service import CloseMatchReportService
from db_helpers import set_tenant_context
from tests.event_ids import event_id
from test_close_authorization_db import add_member, close, read_state
from test_substitutions import committed_application, create_closable_match, report, seeded_match

GRANTED = ("VIEW_MATCH_LIVE_DRAFT", "OPERATE_MATCH_LIVE", "CLOSE_MATCH_REPORT")


async def scenario(engine):
    owner, match_a = await seeded_match(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        match_b = await create_closable_match(session, match_a.tenant)
        await session.commit()
    viewer = await add_member(engine, match_a.tenant, role_code="viewer")
    async with AsyncSession(engine) as session:
        await set_tenant_context(session, match_a.tenant)
        await session.execute(
            text("""
                INSERT INTO tournament_member_roles
                    (organization_id, tournament_id, organization_user_id, role_code, created_by_member_id)
                VALUES (:org, :tournament, :member, 'tournament_operator', :creator)
            """),
            {"org": match_a.tenant.organization_id, "tournament": match_a.tournament_id,
             "member": viewer.organization_user_id, "creator": match_a.tenant.member_id},
        )
        await session.commit()
    return owner, viewer, match_a, match_b


async def allowed(engine, context, permission, match_id) -> bool:
    async with AsyncSession(engine) as session:
        async with session.begin():
            await set_rls_context(session, context.organization_id, context.user_id)
            try:
                await require_permission(session, context, permission, match_id)
            except PermissionError:
                return False
    return True


async def set_active(engine, tenant, member, active: bool) -> None:
    async with AsyncSession(engine) as session:
        await set_tenant_context(session, tenant)
        await session.execute(
            text("UPDATE organization_users SET is_active = :active WHERE id = :member"),
            {"active": active, "member": member.organization_user_id},
        )
        await session.commit()


async def warnings(engine, context, match_id):
    async with AsyncSession(engine) as session:
        return await get_suspension_warnings(match_id, context, session)


def red_card(match) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=event_id("049-red"), event_type="red_card", team_id=match.home_team_id,
        player_id=match.home_starters[0], minute=20, segment_id=match.segment_1,
        metadata={"red_card_type": "direct_red"},
    )


async def suspensions(engine, match) -> int:
    async with AsyncSession(engine) as session:
        await set_tenant_context(session, match.tenant)
        return (await session.execute(
            text("SELECT count(*) FROM player_suspensions WHERE origin_match_id = :match"),
            {"match": match.match_id},
        )).scalar_one()


async def test_operator_gets_the_three_match_permissions_only_in_its_tournament(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, match_b = await scenario(engine)
        for permission in GRANTED:
            assert await allowed(engine, viewer, permission, match_a.match_id) is True
            assert await allowed(engine, viewer, permission, match_b.match_id) is False
        for permission in ("MANAGE_TOURNAMENTS", "RESOLVE_MATCH_ADMINISTRATIVELY", "VIEW_SANCTIONS"):
            assert await allowed(engine, viewer, permission, match_a.match_id) is False
        assert await allowed(engine, viewer, "CLOSE_MATCH_REPORT", None) is False


async def test_operator_operates_in_a_and_gets_403_in_b(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, match_b = await scenario(engine)
        assert await warnings(engine, viewer, match_a.match_id) == []
        with pytest.raises(HTTPException) as error:
            await warnings(engine, viewer, match_b.match_id)
        assert error.value.status_code == 403


async def test_operator_closes_in_a_and_opens_the_red_card_sanction(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, match_b = await scenario(engine)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await CloseMatchReportService(session).execute(
                viewer, match_a.match_id, report([red_card(match_a)])
            )
        assert result["status"] == "success"
        assert (await read_state(engine, match_a))["status"] == "finished"
        assert await suspensions(engine, match_a) == 1

        before = await read_state(engine, match_b)
        with pytest.raises(PermissionError, match="CLOSE_MATCH_REPORT"):
            await close(engine, viewer, match_b)
        assert await read_state(engine, match_b) == before


async def test_operator_cannot_resolve_administratively_nor_manage_the_tournament(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, _ = await scenario(engine)
        administrative = report([], home=3).model_copy(update={
            "resolution_type": "administrative", "winner_team_id": match_a.home_team_id,
            "reason": "Resolución administrativa"})
        before = await read_state(engine, match_a)
        async with AsyncSession(engine) as session:
            with pytest.raises(PermissionError, match="RESOLVE_MATCH_ADMINISTRATIVELY"):
                await CloseMatchReportService(session).execute(viewer, match_a.match_id, administrative)
        async with AsyncSession(engine) as session:
            async with session.begin():
                await set_rls_context(session, viewer.organization_id, viewer.user_id)
                with pytest.raises(PermissionError, match="RESOLVE_MATCH_ADMINISTRATIVELY"):
                    await require_administrative_resolution(session, viewer, match_a.match_id)
        async with AsyncSession(engine) as session:
            with pytest.raises(HTTPException) as error:
                await assign_match_official(
                    match_a.match_id,
                    OfficialAssignmentRequest(organization_user_id=viewer.organization_user_id,
                                              official_role="main_referee"),
                    viewer, session,
                )
            assert error.value.status_code == 403
        assert await read_state(engine, match_a) == before


async def test_deactivated_operator_loses_access_and_recovers_it(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, _ = await scenario(engine)
        await set_active(engine, match_a.tenant, viewer, False)
        for permission in GRANTED:
            assert await allowed(engine, viewer, permission, match_a.match_id) is False
        await set_active(engine, match_a.tenant, viewer, True)
        assert await warnings(engine, viewer, match_a.match_id) == []
        assert (await close(engine, viewer, match_a))["status"] == "success"


async def test_removing_the_assignment_cuts_the_next_request(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, _ = await scenario(engine)
        assert await allowed(engine, viewer, "CLOSE_MATCH_REPORT", match_a.match_id) is True
        async with AsyncSession(engine) as session:
            await set_tenant_context(session, match_a.tenant)
            await session.execute(text("DELETE FROM tournament_member_roles"))
            await session.commit()
        with pytest.raises(HTTPException) as error:
            await warnings(engine, viewer, match_a.match_id)
        assert error.value.status_code == 403


async def save_lineup(engine, context, match) -> int | None:
    async with AsyncSession(engine) as session:
        try:
            await save_match_lineup(
                match.match_id, SaveMatchLineupRequest(segment_id=match.segment_2, entries=[]), context, session
            )
        except HTTPException as error:
            return error.status_code
    return None


async def test_operator_saves_the_lineup_in_a_and_gets_403_in_b(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, match_b = await scenario(engine)
        assert await save_lineup(engine, viewer, match_a) != 403
        assert await save_lineup(engine, viewer, match_b) == 403


async def test_operator_interrupts_the_segment_in_a_and_gets_403_in_b(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, viewer, match_a, match_b = await scenario(engine)
        payload = InterruptMatchSegmentRequest(reason="weather", minute=60)
        async with AsyncSession(engine) as session:
            interrupted = await interrupt_match_segment(match_a.match_id, match_a.segment_2, payload, viewer, session)
        assert str(interrupted["segment_id"]) == str(match_a.segment_2)
        async with AsyncSession(engine) as session:
            with pytest.raises(HTTPException) as error:
                await interrupt_match_segment(match_b.match_id, match_b.segment_2, payload, viewer, session)
        assert error.value.status_code == 403
