from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.tenancy import AuthContext
from app.modules.sanction_appeals.schemas import CaseFilters, DecisionRequest
from test_migration_031 import SEED_SQL
from test_sanction_cases import appeal, permissions
from test_sanction_cases import cases as cases
from test_sanction_readers import readers as readers


async def test_foreign_case_reads_writes_and_pooled_context_are_isolated(cases):
    f = cases
    await permissions(f, "SUBMIT_SANCTION_APPEALS", "VIEW_SANCTION_CASES", "RESOLVE_SANCTION_CASES")
    async with f.service() as service:
        case = await service.submit_appeal(f.context, appeal(f, evidence_text="TENANT_A_ONLY"))
    await f.admin.execute(SEED_SQL.replace("31000000", "32000000").replace("migration-031", "foreign-031"))
    foreign = AuthContext(UUID(str(f.context.user_id).replace("31000000","32000000")),
        UUID(str(f.context.organization_id).replace("31000000","32000000")),
        UUID(str(f.context.organization_user_id).replace("31000000","32000000")))
    role = await f.admin.fetchval("""INSERT INTO roles(organization_id,name,permissions,role_definition_id)
        SELECT $1,'Foreign reviewer','["VIEW_SANCTION_CASES","RESOLVE_SANCTION_CASES"]',id
        FROM role_definitions WHERE code='operator' RETURNING id""", foreign.organization_id)
    await f.admin.execute("INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)",
        foreign.organization_id,foreign.organization_user_id,role)
    async with f.service() as service:
        assert (await service.list_cases(foreign, CaseFilters()))["items"] == []
    async with f.service() as service:
        with pytest.raises(LookupError):
            await service.detail(foreign, case["id"])
    async with f.service() as service:
        with pytest.raises(LookupError):
            await service.decide(foreign, case["id"], DecisionRequest(decision="annul", expected_base_duration=3, reason="Ajena"))
    async with f.service() as service:
        async with service.db.begin():
            for key in ("app.current_organization_id", "app.current_user_id", "app.sanction_authorization_id"):
                value = (await service.db.execute(text("SELECT current_setting(:key,true)"), {"key":key})).scalar_one()
                assert value in (None, "")
    async with f.service() as service:
        assert (await service.detail(f.context, case["id"]))["case"]["evidence_text"] == "TENANT_A_ONLY"
    with pytest.raises(DBAPIError):
        async with f.session() as db:
            await db.execute(text("""INSERT INTO sanction_case_events(organization_id,case_id,event_type,actor_user_id,reason)
                VALUES (:org,:case,'withdrawn',:actor,'Cruce')"""),
                {"org":foreign.organization_id,"case":case["id"],"actor":f.context.user_id})
