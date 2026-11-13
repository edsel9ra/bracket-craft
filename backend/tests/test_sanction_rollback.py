import pytest
from sqlalchemy.exc import DBAPIError

from app.modules.sanction_appeals.platform import SanctionPlatformService
from app.modules.sanction_appeals.schemas import DecisionRequest
from test_sanction_cases import cases as cases
from test_sanction_cases import second_member
from test_sanction_platform import authorized_case
from test_sanction_readers import readers as readers


@pytest.mark.parametrize("table", ["sanction_case_decisions", "sanction_resolutions", "administrative_audit_logs", "outbox_events"])
async def test_failure_at_each_decision_stage_rolls_back_everything_and_consumption(cases, table):
    f = cases
    case, platform, _ = await authorized_case(f)
    await second_member(f, "RESOLVE_SANCTION_CASES")
    tables = ["sanction_cases", "sanction_case_events", "sanction_case_decisions", "sanction_resolutions",
        "sanction_effect_applications", "sanction_match_eligibility", "sanction_notifications", "outbox_events",
        "platform_audit_logs", "administrative_audit_logs", "sanction_platform_authorizations", "player_suspensions"]
    before = {name: [dict(row) for row in await f.admin.fetch(f'SELECT * FROM "{name}" ORDER BY id')] for name in tables}
    await f.admin.execute("""CREATE FUNCTION fail_decision_probe() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'INJECTED_FAILURE'; END; $$""")
    await f.admin.execute(f'CREATE TRIGGER zz_failure_probe AFTER INSERT ON "{table}" FOR EACH ROW EXECUTE FUNCTION fail_decision_probe()')
    async with f.service() as base:
        with pytest.raises(DBAPIError, match="INJECTED_FAILURE"):
            await SanctionPlatformService(base.db).decide(platform, case["id"], DecisionRequest(
                decision="annul", expected_base_duration=3, reason="Resolución"))
    for name in tables:
        assert [dict(row) for row in await f.admin.fetch(f'SELECT * FROM "{name}" ORDER BY id')] == before[name], name
