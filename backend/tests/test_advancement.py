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
