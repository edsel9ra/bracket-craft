from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.advancement.service import AdvancementService


class EmptyLinksResult:
    def mappings(self):
        return self

    def all(self):
        return []


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
