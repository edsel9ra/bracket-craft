"""B2 prepares state serialization without changing the public route."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError


def suspended_payload():
    return dict(
        id=uuid4(),
        tournament_id=uuid4(),
        home_team_id=uuid4(),
        home_team_name="Home",
        away_team_id=uuid4(),
        away_team_name="Away",
        status="suspended",
        home_score=0,
        away_score=0,
        is_provisional=True,
        clock_segment_number=None,
        clock_elapsed_seconds=None,
        clock_state="not_started",
        clock_observed_at=datetime.now(timezone.utc),
    )


def test_serialization_suspended_exact_fourteen_keys_including_nulls():
    from app.modules.matches.live_public import PublicMatchStateResponse

    payload = suspended_payload()
    result = (
        TypeAdapter(PublicMatchStateResponse)
        .validate_python(payload)
        .model_dump(mode="json")
    )
    assert len(result) == 14 and set(result) == set(payload)
    assert (
        result["clock_segment_number"] is None
        and result["clock_elapsed_seconds"] is None
    )


@pytest.mark.parametrize(
    "extra", ["lineup", "stage_id", "actor_user_id", "home_team_crest_url"]
)
def test_serialization_suspended_forbids_other_fields(extra):
    from app.modules.matches.live_public import PublicMatchStateResponse

    with pytest.raises(ValidationError):
        TypeAdapter(PublicMatchStateResponse).validate_python(
            {**suspended_payload(), extra: None}
        )


def test_serialization_live_extends_classic_other_states_keep_original_defaults():
    from app.modules.matches.live_public import PublicMatchStateResponse
    from app.modules.tournaments.schemas import PublicMatchResponse

    classic = dict(
        id=uuid4(),
        tournament_id=uuid4(),
        stage_id=uuid4(),
        stage_name="Stage",
        stage_order=1,
        status="scheduled",
    )
    adapter = TypeAdapter(PublicMatchStateResponse)
    assert (
        adapter.validate_python(classic).model_dump()
        == PublicMatchResponse(**classic).model_dump()
    )
    live = {
        **classic,
        "status": "live",
        **{k: v for k, v in suspended_payload().items() if k.startswith("clock_")},
        "is_provisional": True,
    }
    result = adapter.validate_python(live).model_dump()
    assert result["is_provisional"] and result["clock_elapsed_seconds"] is None
    assert result["stage_name"] == "Stage"
