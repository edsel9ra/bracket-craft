import json
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sanction_appeals.cases import SanctionCaseService
from app.modules.sanction_appeals.schemas import AppealRequest, ProposalRequest
from test_migration_031 import MATCH, ORG, PLAYER_HOME_FIRST, SEGMENT_FIRST, TEAM_HOME, VERSION
from test_sanction_readers import readers as readers


@pytest.fixture
async def cases(readers):
    @asynccontextmanager
    async def session():
        async with readers.engine.connect() as connection:
            await connection.execute(text("SET ROLE bracket_app"))
            await connection.commit()
            async with AsyncSession(bind=connection) as db:
                yield SanctionCaseService(db)
    readers.service = session
    yield readers


async def permissions(f, *values):
    await f.admin.execute("UPDATE roles SET permissions=$1::jsonb WHERE organization_id=$2", json.dumps(values), ORG)


def appeal(f, **changes):
    return AppealRequest.model_validate({"suspension_id": str(f.suspension),
        "represented_player_id": PLAYER_HOME_FIRST, "reason": "Revisar sanción", **changes})


@pytest.mark.parametrize("source", ["competition_rule", "administrative_resolution"])
@pytest.mark.parametrize("scope,status", [("organization", "active"), ("tournament", "served")])
async def test_appeal_minimum_permission_preserves_source_and_serves(cases, source, scope, status):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    f.suspension = await f.admin.fetchval("""INSERT INTO player_suspensions
        (organization_id,source_tournament_id,player_id,source_type,dedupe_key,scope_type,matches_suspended,reason,status,created_at)
        SELECT organization_id,source_tournament_id,player_id,$2,$3,$4,3,'Original',$5,'2020-01-01'
        FROM player_suspensions WHERE id=$1 RETURNING id""", f.suspension, source, str(uuid4()), scope, status)
    before = dict(await f.admin.fetchrow("SELECT * FROM player_suspensions WHERE id=$1", f.suspension))
    async with f.service() as service:
        result = await service.submit_appeal(f.context, appeal(f, evidence_text="Privada"))
    assert set(result) == {"id", "status"} and result["status"] == "pending"
    assert dict(await f.admin.fetchrow("SELECT * FROM player_suspensions WHERE id=$1", f.suspension)) == before
    assert await f.admin.fetchval("SELECT count(*) FROM player_suspension_serves") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_case_events WHERE event_type='submitted'") == 1
    async with f.session() as db:
        assert not (await db.execute(text("SELECT * FROM sanction_cases"))).all()


async def test_appeal_requires_permission_and_valid_representation(cases):
    f = cases
    await permissions(f)
    async with f.service() as service:
        with pytest.raises(PermissionError):
            await service.submit_appeal(f.context, appeal(f))
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    async with f.service() as service:
        with pytest.raises(LookupError):
            await service.submit_appeal(f.context, appeal(f, suspension_id=str(uuid4())))
    async with f.service() as service:
        with pytest.raises(ValueError):
            await service.submit_appeal(f.context, appeal(f, represented_player_id=str(uuid4())))
    async with f.service() as service:
        receipt = await service.submit_appeal(f.context, appeal(f, represented_player_id=None, represented_team_id=TEAM_HOME))
    assert receipt["status"] == "pending"


async def test_appeal_match_origin_in_archived_tournament_has_no_deadline(cases):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    await f.admin.execute("""INSERT INTO match_rosters
        (organization_id,match_id,roster_id,player_id,team_id,tournament_id,role)
        SELECT organization_id,$1,id,player_id,team_id,tournament_id,'starter' FROM rosters""", MATCH)
    event = await f.admin.fetchval("""INSERT INTO match_events
        (organization_id,match_id,segment_id,team_id,player_id,event_type,minute,client_event_id)
        VALUES ($1,$2,$3,$4,$5,'red_card',10,$6) RETURNING id""",
        ORG, MATCH, SEGMENT_FIRST, TEAM_HOME, PLAYER_HOME_FIRST, str(uuid4()))
    f.suspension = await f.admin.fetchval("""INSERT INTO player_suspensions
        (organization_id,source_tournament_id,player_id,source_type,dedupe_key,scope_type,matches_suspended,
         reason,origin_match_id,source_event_id)
        SELECT organization_id,source_tournament_id,player_id,'match_event',$2,'tournament',3,'Original',$3,$4
        FROM player_suspensions WHERE id=$1 RETURNING id""", f.suspension, str(uuid4()), MATCH, event)
    await f.admin.execute("""UPDATE matches SET status='finished',result_confirmed=TRUE,
        resolution_type='regular',home_score_regular=0,away_score_regular=0,home_score=0,away_score=0
        WHERE id=$1""", MATCH)
    await f.admin.execute("UPDATE tournament_versions SET status='archived' WHERE id=$1", VERSION)
    async with f.service() as service:
        assert (await service.submit_appeal(f.context, appeal(f)))["status"] == "pending"


@pytest.mark.parametrize("action,duration", [("annul", None), ("reduce", 1)])
async def test_proposal_only_resolve_permission_is_audited_without_effect(cases, action, duration):
    f = cases
    await permissions(f, "RESOLVE_SANCTION_CASES")
    payload = ProposalRequest(suspension_id=f.suspension, proposed_action=action,
        proposed_duration=duration, reason="Revisión administrativa")
    async with f.service() as service:
        receipt = await service.submit_proposal(f.context, payload)
    assert receipt["status"] == "pending" and set(receipt) == {"id", "status"}
    row = await f.admin.fetchrow("SELECT * FROM sanction_cases WHERE id=$1", receipt["id"])
    assert row["case_type"] == "administrative_proposal" and row["proposed_action"] == action
    assert row["proposed_duration"] == duration and row["submitted_by_user_id"] == f.context.user_id
    assert await f.admin.fetchval("SELECT status FROM player_suspensions WHERE id=$1", f.suspension) == "active"
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_resolutions") == 0
    async with f.session() as db:
        assert not (await db.execute(text("SELECT * FROM sanction_cases"))).all()


async def test_proposal_requires_resolve_and_reduction_cannot_increase(cases):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS")
    payload = ProposalRequest(suspension_id=f.suspension, proposed_action="reduce", proposed_duration=3, reason="Revisar")
    async with f.service() as service:
        with pytest.raises(PermissionError):
            await service.submit_proposal(f.context, payload)
    await permissions(f, "RESOLVE_SANCTION_CASES")
    async with f.service() as service:
        with pytest.raises(ValueError):
            await service.submit_proposal(f.context, payload)
    assert await f.admin.fetchval("SELECT count(*) FROM sanction_cases") == 0
