import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_rls_context
from app.modules.matches.router import create_match_segment
from app.modules.matches.schemas import CreateMatchSegmentRequest
from app.modules.matches.service import CloseMatchReportService
from app.modules.sanction_appeals.application import record_opening
from app.modules.sanction_appeals.repository import load_effective_sanctions
from db_helpers import set_tenant_context
from test_close_authorization_db import add_member, assign_official, close, read_state
from test_substitutions import committed_application, context_for, report, seeded_match
from test_sanction_readers import readers as readers
from test_migration_031 import MATCH, MEMBER, ORG


async def member_with_permissions(engine, match, role_code, permissions):
    member = context_for(match.tenant) if role_code == "owner" else await add_member(engine, match.tenant, role_code=role_code)
    async with AsyncSession(engine) as session:
        await set_tenant_context(session, match.tenant)
        await session.execute(text("""UPDATE roles r SET permissions=CAST(:permissions AS jsonb)
            FROM organization_user_roles our WHERE our.role_id=r.id
            AND our.organization_id=r.organization_id AND our.organization_user_id=:member"""),
            {"member": member.organization_user_id, "permissions": json.dumps(permissions)})
        await session.commit()
    return member


def administrative_report(match):
    return report([], home=3).model_copy(update={"resolution_type": "administrative",
        "winner_team_id": match.home_team_id, "reason": "Resolución administrativa"})


@pytest.mark.parametrize("role", ["owner", "administrator"])
async def test_administrative_only_permission_closes_without_sanctions(database_admin_url, role):
    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        member = await member_with_permissions(engine, match, role, ["RESOLVE_MATCH_ADMINISTRATIVELY"])
        async with AsyncSession(engine) as session:
            result = await CloseMatchReportService(session).execute(member, match.match_id, administrative_report(match))
        assert result["status"] == "success"
        state = await read_state(engine, match)
        assert state["status"] == "administrative_resolution"
        assert state["result_confirmed"] is True


async def test_administrative_permission_does_not_allow_opening_or_walkover(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        member = await member_with_permissions(engine, match, "owner", ["RESOLVE_MATCH_ADMINISTRATIVELY"])
        before = await read_state(engine, match)
        async with AsyncSession(engine) as session:
            with pytest.raises(HTTPException) as error:
                await create_match_segment(match.match_id, CreateMatchSegmentRequest(segment_number=3, minute_start=90), member, session)
            assert error.value.status_code == 403
        async with AsyncSession(engine) as session:
            await set_rls_context(session, member.organization_id, member.user_id)
            with pytest.raises(DBAPIError, match="SANCTION_OPERATION_DENIED"):
                await record_opening(session, match.match_id, match.segment_1)
        async with AsyncSession(engine) as session:
            with pytest.raises(PermissionError, match="CLOSE_MATCH_REPORT"):
                await CloseMatchReportService(session).execute(member, match.match_id,
                    administrative_report(match).model_copy(update={"resolution_type": "walkover", "reason": "no_show"}))
        assert await read_state(engine, match) == before


async def test_administrative_permission_requires_owner_or_administrator(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        member = await member_with_permissions(engine, match, "operator", ["RESOLVE_MATCH_ADMINISTRATIVELY"])
        async with AsyncSession(engine) as session:
            await set_rls_context(session, member.organization_id, member.user_id)
            with pytest.raises(DBAPIError, match="SANCTION_OPERATION_DENIED"):
                await load_effective_sanctions(session, match.match_id, as_of=datetime.now(timezone.utc))
        async with AsyncSession(engine) as session:
            with pytest.raises(PermissionError, match="RESOLVE_MATCH_ADMINISTRATIVELY"):
                await CloseMatchReportService(session).execute(member, match.match_id, administrative_report(match))


async def test_requester_read_permission_does_not_allow_served_writes(readers):
    await readers.admin.execute("UPDATE roles SET permissions='[\"REQUEST_MATCH_REPORT_RECTIFICATION\"]'")
    async with readers.session() as session:
        assert await load_effective_sanctions(session, readers.future, as_of=datetime.now(timezone.utc))
    with pytest.raises(DBAPIError, match="SANCTION_OPERATION_DENIED"):
        async with readers.session() as session:
            await session.execute(text("SELECT refresh_served_sanctions(:match,:now)"),
                {"match": readers.future, "now": datetime.now(timezone.utc)})
    assert not await readers.admin.fetchval("SELECT has_function_privilege('bracket_app','sanction_can_close_match(uuid,uuid)','EXECUTE')")


@pytest.mark.parametrize("resolution", ["regular", "walkover"])
async def test_assigned_official_with_only_close_permission_still_closes(database_admin_url, resolution):
    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        member = await member_with_permissions(engine, match, "referee", ["CLOSE_MATCH_REPORT"])
        await assign_official(engine, match, member)
        if resolution == "regular":
            assert (await close(engine, member, match))["status"] == "success"
        else:
            async with AsyncSession(engine) as session:
                result = await CloseMatchReportService(session).execute(member, match.match_id,
                    administrative_report(match).model_copy(update={"resolution_type": "walkover", "reason": "no_show"}))
            assert result["status"] == "success"


@pytest.mark.parametrize("assignment,permission", [("target", True), ("other", True), ("none", True), ("target", False)])
async def test_official_opening_and_reader_are_limited_to_assigned_match(readers, assignment, permission):
    await readers.admin.execute("""UPDATE roles SET role_definition_id=(SELECT id FROM role_definitions WHERE code='referee'),
        permissions=$1::jsonb""", json.dumps(["CLOSE_MATCH_REPORT"] if permission else []))
    if assignment != "none":
        await readers.admin.execute("""INSERT INTO match_officials(organization_id,match_id,organization_user_id,official_role)
            VALUES ($1,$2,$3,'main_referee')""", ORG, readers.future if assignment == "target" else UUID(MATCH), MEMBER)
    if assignment == "target" and permission:
        async with readers.engine.connect() as connection:
            await connection.execute(text("SET ROLE bracket_app"))
            await connection.commit()
            async with AsyncSession(bind=connection) as session:
                result = await create_match_segment(readers.future, CreateMatchSegmentRequest(segment_number=1, minute_start=0), readers.context, session)
                assert result["segment_number"] == 1
        async with readers.session() as session:
            assert len(await load_effective_sanctions(session, readers.future, as_of=datetime.now(timezone.utc))) == 1
        assert await readers.admin.fetchval("SELECT count(*) FROM sanction_match_eligibility") == 1
    else:
        with pytest.raises(DBAPIError, match="SANCTION_OPERATION_DENIED"):
            async with readers.session() as session:
                await load_effective_sanctions(session, readers.future, as_of=datetime.now(timezone.utc))
        async with readers.engine.connect() as connection:
            await connection.execute(text("SET ROLE bracket_app"))
            await connection.commit()
            async with AsyncSession(bind=connection) as session:
                with pytest.raises(HTTPException) as error:
                    await create_match_segment(readers.future, CreateMatchSegmentRequest(segment_number=1, minute_start=0), readers.context, session)
                assert error.value.status_code == 403
