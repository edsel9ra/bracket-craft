from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.advancement.service import AdvancementService


class EmptyLinksResult:
    def __init__(self, rows=()):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class EmptyLinksSession:
    async def execute(self, *args, **kwargs):
        return EmptyLinksResult()


class ResetResult:
    def __init__(self, value):
        self.value = value
        self.rowcount = 1

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class ResetSession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))
        if "SELECT id" in str(statement):
            return ResetResult({"id": uuid4()})
        return ResetResult(None)


@pytest.mark.asyncio
async def test_draw_without_advancement_links_can_close():
    context = SimpleNamespace(organization_id=uuid4())
    match = {"home_team_id": uuid4(), "away_team_id": uuid4()}
    outcome = SimpleNamespace(winner_team_id=None)

    await AdvancementService(EmptyLinksSession()).advance_from_match(
        context,
        uuid4(),
        match,
        outcome,
    )


@pytest.mark.asyncio
async def test_losers_bracket_winner_activates_double_elimination_reset():
    context = SimpleNamespace(organization_id=uuid4())
    home_team_id = uuid4()
    away_team_id = uuid4()
    match = {
        "tournament_id": uuid4(),
        "tournament_version_id": uuid4(),
        "stage_id": uuid4(),
        "bracket_code": "GF1",
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
    }
    session = ResetSession()

    await AdvancementService(session).activate_double_elimination_reset(
        context,
        match,
        SimpleNamespace(winner_team_id=away_team_id),
    )

    assert any("UPDATE matches" in statement for statement in session.statements)
    assert any("INSERT INTO outbox_events" in statement for statement in session.statements)
    assert any("INSERT INTO match_slot_assignments" in statement for statement in session.statements)


class AdvancingSession:
    def __init__(self, link, *, available=True):
        self.link = link
        self.available = available
        self.calls = []

    async def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "FROM advancement_links" in sql:
            return EmptyLinksResult([self.link])
        result = ResetResult(None)
        result.rowcount = int(self.available)
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome_name,side", [("winner", "home"), ("loser", "away")])
async def test_advancement_records_the_assigned_side_and_link(outcome_name, side):
    link = {"id": uuid4(), "target_match_id": uuid4(), "target_side": side, "outcome": outcome_name}
    session = AdvancingSession(link)
    context = SimpleNamespace(organization_id=uuid4())
    home, away = uuid4(), uuid4()
    await AdvancementService(session).advance_from_match(
        context, uuid4(), {"home_team_id": home, "away_team_id": away},
        SimpleNamespace(winner_team_id=away),
    )
    update = next(params for sql, params in session.calls if "UPDATE matches" in sql)
    assert update["team_id"] == str(away if outcome_name == "winner" else home)
    assignment = next(params for sql, params in session.calls if "INSERT INTO match_slot_assignments" in sql)
    assert assignment["match_id"] == str(link["target_match_id"])
    assert assignment["side"] == side
    assert assignment["origin"] == "advancement_link"
    assert assignment["advancement_link_id"] == str(link["id"])


@pytest.mark.asyncio
async def test_an_unavailable_destination_does_not_record_an_assignment():
    link = {"id": uuid4(), "target_match_id": uuid4(), "target_side": "home", "outcome": "winner"}
    session = AdvancingSession(link, available=False)
    home, away = uuid4(), uuid4()
    with pytest.raises(ValueError, match="no está disponible"):
        await AdvancementService(session).advance_from_match(
            SimpleNamespace(organization_id=uuid4()), uuid4(),
            {"home_team_id": home, "away_team_id": away}, SimpleNamespace(winner_team_id=home),
        )
    assert not any("INSERT INTO match_slot_assignments" in sql for sql, _ in session.calls)
