import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.modules.tournaments.router import create_match, draw_stage_schedule
from app.modules.tournaments.schemas import (
    CreateMatchRequest,
    GenerateSingleEliminationRequest,
)
from app.modules.tournaments.scheduling import (
    build_double_elimination_bracket,
    build_round_robin_schedule,
    build_single_elimination_bracket,
    build_swiss_pairings,
    distribute_groups,
)
from migration_helpers import throwaway_database


START_DATE = datetime(2026, 9, 18, 18, 0, tzinfo=timezone.utc)


def team_ids(count: int) -> list[UUID]:
    return [UUID(int=index) for index in range(1, count + 1)]


def bracket_signature(bracket):
    return [
        (
            match.code,
            match.round_number,
            match.home.team_id,
            match.home.source_match_code,
            match.away.team_id,
            match.away.source_match_code,
            match.match_date,
        )
        for match in bracket.matches
    ]


def test_single_elimination_builds_complete_eight_team_bracket():
    bracket = build_single_elimination_bracket(
        team_ids(8),
        seed=42,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )

    assert bracket.bracket_size == 8
    assert bracket.round_count == 3
    assert [match.code for match in bracket.matches] == [
        "QF1",
        "QF2",
        "QF3",
        "QF4",
        "SF1",
        "SF2",
        "FINAL",
    ]
    assert len(bracket.advancement_links) == 6
    assert all(match.home.team_id or match.home.source_match_code for match in bracket.matches)
    assert all(match.away.team_id or match.away.source_match_code for match in bracket.matches)


def test_seed_reproduces_draw_and_dates():
    first = build_single_elimination_bracket(
        team_ids(8),
        seed=123,
        start_date=START_DATE,
        round_interval_days=5,
        match_interval_hours=3,
    )
    repeated = build_single_elimination_bracket(
        team_ids(8),
        seed=123,
        start_date=START_DATE,
        round_interval_days=5,
        match_interval_hours=3,
    )
    different = build_single_elimination_bracket(
        team_ids(8),
        seed=124,
        start_date=START_DATE,
        round_interval_days=5,
        match_interval_hours=3,
    )

    assert bracket_signature(first) == bracket_signature(repeated)
    assert bracket_signature(first) != bracket_signature(different)
    assert first.matches[4].match_date == START_DATE.replace(day=23)
    assert first.matches[-1].match_date == START_DATE.replace(day=28)


def test_three_team_bracket_resolves_one_bye_without_creating_one_sided_matches():
    bracket = build_single_elimination_bracket(
        team_ids(3),
        seed=7,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )

    assert bracket.bracket_size == 4
    assert bracket.round_count == 2
    assert len(bracket.matches) == 2
    assert len(bracket.advancement_links) == 1
    assert [match.code for match in bracket.matches] == ["SF1", "FINAL"]
    assert bracket.matches[-1].home.source_match_code == "SF1" or bracket.matches[-1].away.source_match_code == "SF1"
    assert all(match.home.team_id or match.home.source_match_code for match in bracket.matches)
    assert all(match.away.team_id or match.away.source_match_code for match in bracket.matches)


@pytest.mark.parametrize(
    "count, message",
    [
        (0, "dos equipos"),
        (1, "dos equipos"),
    ],
)
def test_bracket_requires_two_teams(count: int, message: str):
    with pytest.raises(ValueError, match=message):
        build_single_elimination_bracket(
            team_ids(count),
            seed=1,
            start_date=START_DATE,
            round_interval_days=7,
            match_interval_hours=2,
        )


def test_bracket_rejects_duplicate_teams():
    ids = team_ids(2)
    with pytest.raises(ValueError, match="repetidos"):
        build_single_elimination_bracket(
            [ids[0], ids[0]],
            seed=1,
            start_date=START_DATE,
            round_interval_days=7,
            match_interval_hours=2,
        )


def test_round_robin_supports_single_and_double_legs_without_duplicate_pairings():
    ids = team_ids(4)
    single = build_round_robin_schedule(
        ids,
        seed=9,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
        legs=1,
    )
    double = build_round_robin_schedule(
        ids,
        seed=9,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
        legs=2,
    )

    single_pairs = {frozenset((match.home_team_id, match.away_team_id)) for match in single.matches}
    double_pairs = [frozenset((match.home_team_id, match.away_team_id)) for match in double.matches]
    assert len(single.matches) == 6
    assert len(single_pairs) == 6
    assert len(double.matches) == 12
    assert all(double_pairs.count(pair) == 2 for pair in single_pairs)


def test_group_draw_places_one_selected_head_in_each_group():
    ids = team_ids(8)
    draw = distribute_groups(ids, group_count=2, seed=10, head_team_ids=ids[:2])

    assert len(draw.groups) == 2
    assert all(len(group) == 4 for group in draw.groups)
    assert {group[0] for group in draw.groups} == set(ids[:2])
    assert set().union(*draw.groups) == set(ids)


def test_swiss_pairings_do_not_repeat_rivals_across_rounds():
    ids = team_ids(8)
    prior_pairs = set()
    home_counts = {}
    away_counts = {}
    for round_number in range(1, 5):
        pairings = build_swiss_pairings(
            ids,
            standings=[],
            prior_pairs=prior_pairs,
            seed=round_number,
            round_number=round_number,
            home_counts=home_counts,
            away_counts=away_counts,
            home_target=2,
            away_target=2,
        )
        for pairing in pairings:
            if pairing.home_team_id is None:
                continue
            pair = frozenset((pairing.home_team_id, pairing.away_team_id))
            assert pair not in prior_pairs
            prior_pairs.add(pair)
            home_counts[pairing.home_team_id] = home_counts.get(pairing.home_team_id, 0) + 1
            away_counts[pairing.away_team_id] = away_counts.get(pairing.away_team_id, 0) + 1

    assert len(prior_pairs) == 16
    assert set(home_counts.values()) == {2}
    assert set(away_counts.values()) == {2}


def test_swiss_36_team_format_balances_four_home_and_four_away_matches():
    ids = team_ids(36)
    prior_pairs = set()
    home_counts = {}
    away_counts = {}

    for round_number in range(1, 9):
        pairings = build_swiss_pairings(
            ids,
            standings=[],
            prior_pairs=prior_pairs,
            seed=round_number,
            round_number=round_number,
            home_counts=home_counts,
            away_counts=away_counts,
            home_target=4,
            away_target=4,
        )
        for pairing in pairings:
            pair = frozenset((pairing.home_team_id, pairing.away_team_id))
            assert pair not in prior_pairs
            prior_pairs.add(pair)
            home_counts[pairing.home_team_id] = home_counts.get(pairing.home_team_id, 0) + 1
            away_counts[pairing.away_team_id] = away_counts.get(pairing.away_team_id, 0) + 1

    assert len(prior_pairs) == 144
    assert set(home_counts.values()) == {4}
    assert set(away_counts.values()) == {4}


def test_swiss_gives_an_odd_field_bye_to_the_lowest_ranked_team_first():
    ids = team_ids(5)
    standings = [
        {"team_id": team_id, "points": 10 - index, "won": 3 - index % 2, "rank": index + 1}
        for index, team_id in enumerate(ids)
    ]

    pairings = build_swiss_pairings(
        ids,
        standings=standings,
        prior_pairs=set(),
        seed=4,
        round_number=1,
        bye_counts={},
    )

    assert next(pairing.bye_team_id for pairing in pairings if pairing.bye_team_id) == ids[-1]


def test_double_elimination_builds_losers_bracket_and_reset_marker():
    bracket = build_double_elimination_bracket(
        team_ids(8),
        seed=12,
        start_date=START_DATE,
        round_interval_days=7,
        match_interval_hours=2,
    )

    assert bracket.reset_code == "GF2"
    assert bracket.matches[-1].code == "GF1"
    assert bracket.matches[-1].lane == "final"
    assert any(link.outcome == "loser" for link in bracket.advancement_links)
    assert len(bracket.matches) == 14


# ---------------------------------------------------------------------------
# Opt-in PostgreSQL: manual meeting limit per stage format (RF-009, R26)
# ---------------------------------------------------------------------------

ORG = "8e000000-0000-4000-8000-000000000001"
USER = "8e000000-0000-4000-8000-000000000002"
MEMBER = "8e000000-0000-4000-8000-000000000003"
ROLE = "8e000000-0000-4000-8000-000000000004"
TOURNAMENT = "8e000000-0000-4000-8000-000000000010"
VERSION = "8e000000-0000-4000-8000-000000000011"
STAGE_ONE_LEG = "8e000000-0000-4000-8000-000000000012"
STAGE_TWO_LEG = "8e000000-0000-4000-8000-000000000013"
STAGE_SWISS = "8e000000-0000-4000-8000-000000000014"
STAGE_CUP = "8e000000-0000-4000-8000-000000000015"
STAGE_OTHER = "8e000000-0000-4000-8000-000000000016"
STAGE_GROUP = "8e000000-0000-4000-8000-000000000017"
GROUP_A = "8e000000-0000-4000-8000-000000000021"
GROUP_B = "8e000000-0000-4000-8000-000000000022"
TEAM_ONE = "8e000000-0000-4000-8000-000000000031"
TEAM_TWO = "8e000000-0000-4000-8000-000000000032"
TEAM_THREE = "8e000000-0000-4000-8000-000000000033"
TEAM_FOUR = "8e000000-0000-4000-8000-000000000034"

PAIRING_SEED_SQL = f"""
INSERT INTO public.organizations (id, name, slug)
VALUES ('{ORG}', 'Pairing Limit Org', 'pairing-limit-org');

INSERT INTO public.users (id, email, password_hash, full_name)
VALUES ('{USER}', 'pairing-limit@example.test', 'hash', 'Pairing Owner');

INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);

INSERT INTO public.roles (id, organization_id, role_definition_id, name, permissions)
SELECT '{ROLE}', '{ORG}', rd.id, 'Owner', '["MANAGE_TOURNAMENTS"]'::jsonb
FROM public.role_definitions rd
WHERE rd.code = 'owner';

INSERT INTO public.organization_user_roles (
    organization_id, organization_user_id, role_id
) VALUES ('{ORG}', '{MEMBER}', '{ROLE}');

INSERT INTO public.tournaments (
    id, organization_id, name, season, start_date, status, current_draft_config
) VALUES (
    '{TOURNAMENT}', '{ORG}', 'Pairing Limit Cup', '2026', DATE '2026-01-01',
    'draft', '{{}}'::jsonb
);

INSERT INTO public.tournament_versions (
    id, organization_id, tournament_id, version_number, rules_config,
    phase_config, status, created_by_member_id
) VALUES (
    '{VERSION}', '{ORG}', '{TOURNAMENT}', 1, '{{}}'::jsonb, '{{}}'::jsonb,
    'draft', '{MEMBER}'
);

INSERT INTO public.stages (
    id, organization_id, tournament_id, tournament_version_id, name,
    stage_type, stage_order, schedule_legs
) VALUES
    ('{STAGE_ONE_LEG}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Liga una vuelta', 'round_robin', 1, 1),
    ('{STAGE_TWO_LEG}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Liga dos vueltas', 'round_robin', 2, 2),
    ('{STAGE_SWISS}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Fase suiza', 'swiss', 3, 2),
    ('{STAGE_CUP}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Copa', 'single_elimination', 4, 1),
    ('{STAGE_OTHER}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Otra liga', 'round_robin', 5, 1),
    ('{STAGE_GROUP}', '{ORG}', '{TOURNAMENT}', '{VERSION}',
     'Fase de grupos', 'custom_group', 6, 1);

INSERT INTO public.groups (
    id, organization_id, tournament_id, tournament_version_id, stage_id, name
) VALUES
    ('{GROUP_A}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_GROUP}', 'A'),
    ('{GROUP_B}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_GROUP}', 'B');

INSERT INTO public.teams (id, organization_id, name, short_code)
VALUES
    ('{TEAM_ONE}', '{ORG}', 'Equipo Uno', 'EQ1'),
    ('{TEAM_TWO}', '{ORG}', 'Equipo Dos', 'EQ2'),
    ('{TEAM_THREE}', '{ORG}', 'Equipo Tres', 'EQ3'),
    ('{TEAM_FOUR}', '{ORG}', 'Equipo Cuatro', 'EQ4');

INSERT INTO public.tournament_teams (
    organization_id, tournament_id, team_id, status
) VALUES
    ('{ORG}', '{TOURNAMENT}', '{TEAM_ONE}', 'registered'),
    ('{ORG}', '{TOURNAMENT}', '{TEAM_TWO}', 'registered'),
    ('{ORG}', '{TOURNAMENT}', '{TEAM_THREE}', 'registered'),
    ('{ORG}', '{TOURNAMENT}', '{TEAM_FOUR}', 'registered');

INSERT INTO public.stage_teams (
    organization_id, tournament_id, tournament_version_id, stage_id, group_id, team_id
) VALUES
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_ONE_LEG}', NULL, '{TEAM_ONE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_ONE_LEG}', NULL, '{TEAM_TWO}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_ONE_LEG}', NULL, '{TEAM_THREE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_ONE_LEG}', NULL, '{TEAM_FOUR}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_TWO_LEG}', NULL, '{TEAM_ONE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_TWO_LEG}', NULL, '{TEAM_TWO}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_TWO_LEG}', NULL, '{TEAM_THREE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_TWO_LEG}', NULL, '{TEAM_FOUR}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_SWISS}', NULL, '{TEAM_ONE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_SWISS}', NULL, '{TEAM_TWO}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_CUP}', NULL, '{TEAM_ONE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_CUP}', NULL, '{TEAM_TWO}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_OTHER}', NULL, '{TEAM_ONE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_OTHER}', NULL, '{TEAM_TWO}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_GROUP}', '{GROUP_A}', '{TEAM_ONE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_GROUP}', '{GROUP_A}', '{TEAM_TWO}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_GROUP}', '{GROUP_B}', '{TEAM_ONE}'),
    ('{ORG}', '{TOURNAMENT}', '{VERSION}', '{STAGE_GROUP}', '{GROUP_B}', '{TEAM_TWO}');
"""


@dataclass
class PairingHarness:
    admin: object
    engine: object


def async_database_url(admin_url: str, database: str) -> str:
    url = make_url(admin_url)
    if "asyncpg" not in url.drivername:
        url = url.set(drivername="postgresql+asyncpg")
    return url.set(database=database).render_as_string(hide_password=False)


def pairing_context() -> AuthContext:
    return AuthContext(
        user_id=UUID(USER),
        organization_id=UUID(ORG),
        organization_user_id=UUID(MEMBER),
    )


@pytest.fixture
async def pairing_harness(database_admin_url):
    async with throwaway_database(database_admin_url, last=23) as admin:
        await admin.execute(PAIRING_SEED_SQL)
        database = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(
            async_database_url(database_admin_url, database), pool_pre_ping=True
        )
        try:
            yield PairingHarness(admin=admin, engine=engine)
        finally:
            await engine.dispose()


async def attempt_manual_match(
    harness: PairingHarness,
    *,
    stage_id: str,
    home_team_id: str | None,
    away_team_id: str | None,
    group_id: str | None = None,
) -> HTTPException | None:
    """Create one manual match and return the HTTP error, if any."""

    payload = CreateMatchRequest(
        version_id=UUID(VERSION),
        stage_id=UUID(stage_id),
        group_id=UUID(group_id) if group_id else None,
        home_team_id=UUID(home_team_id) if home_team_id else None,
        away_team_id=UUID(away_team_id) if away_team_id else None,
        match_date=START_DATE,
    )
    async with AsyncSession(harness.engine, expire_on_commit=False) as session:
        try:
            await create_match(UUID(TOURNAMENT), payload, pairing_context(), session)
        except HTTPException as exc:
            return exc
    return None


async def count_stage_matches(harness: PairingHarness, stage_id: str) -> int:
    return await harness.admin.fetchval(
        "SELECT count(*) FROM public.matches WHERE stage_id = $1", UUID(stage_id)
    )


async def count_pair_matches(harness: PairingHarness, stage_id: str) -> int:
    return await harness.admin.fetchval(
        """
        SELECT count(*)
        FROM public.matches
        WHERE stage_id = $1
          AND home_team_id IS NOT NULL
          AND away_team_id IS NOT NULL
          AND (
                (home_team_id = $2 AND away_team_id = $3)
             OR (home_team_id = $3 AND away_team_id = $2)
          )
        """,
        UUID(stage_id),
        UUID(TEAM_ONE),
        UUID(TEAM_TWO),
    )


async def draw_league(
    harness: PairingHarness, *, stage_id: str, legs: int
) -> object:
    payload = GenerateSingleEliminationRequest(
        version_id=UUID(VERSION),
        stage_id=UUID(stage_id),
        start_date=START_DATE,
        seed=13,
        legs=legs,
    )
    async with AsyncSession(harness.engine, expire_on_commit=False) as session:
        return await draw_stage_schedule(
            UUID(TOURNAMENT), payload, pairing_context(), session
        )


async def insert_cancelled_meeting(harness: PairingHarness, *, stage_id: str) -> None:
    await harness.admin.execute(
        """
        INSERT INTO public.matches (
            organization_id, tournament_id, tournament_version_id, stage_id,
            home_team_id, away_team_id, match_date, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'cancelled')
        """,
        UUID(ORG),
        UUID(TOURNAMENT),
        UUID(VERSION),
        UUID(stage_id),
        UUID(TEAM_ONE),
        UUID(TEAM_TWO),
        START_DATE,
    )


@pytest.mark.asyncio
async def test_duplicate_manual_meeting_is_rejected_without_writing_rows(
    pairing_harness,
):
    harness = pairing_harness
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_ONE_LEG,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )
    rows_before_rejection = await count_stage_matches(harness, STAGE_ONE_LEG)

    # The pair is order-insensitive: swapping home and away is the same pairing.
    error = await attempt_manual_match(
        harness,
        stage_id=STAGE_ONE_LEG,
        home_team_id=TEAM_TWO,
        away_team_id=TEAM_ONE,
    )

    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    detail = error.detail
    assert "Liga una vuelta" in detail  # names the stage
    assert "Equipo Uno" in detail and "Equipo Dos" in detail  # names the pair
    assert "máximo de 1 enfrentamiento" in detail  # names the limit
    # The rejection wrote nothing, not even a partial row.
    assert await count_stage_matches(harness, STAGE_ONE_LEG) == rows_before_rejection == 1


@pytest.mark.asyncio
async def test_generated_matches_count_as_existing_meetings(pairing_harness):
    harness = pairing_harness
    drawn = await draw_league(harness, stage_id=STAGE_ONE_LEG, legs=1)
    assert drawn.match_count == 6

    error = await attempt_manual_match(
        harness,
        stage_id=STAGE_ONE_LEG,
        home_team_id=TEAM_ONE,
        away_team_id=TEAM_TWO,
    )

    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    assert "Liga una vuelta" in error.detail
    assert await count_stage_matches(harness, STAGE_ONE_LEG) == 6


@pytest.mark.asyncio
async def test_cancelled_meeting_does_not_count(pairing_harness):
    harness = pairing_harness
    await insert_cancelled_meeting(harness, stage_id=STAGE_ONE_LEG)

    # The cancelled meeting is ignored, so the substitute can be created...
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_ONE_LEG,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )
    # ...but from then on the pair already reached the format limit.
    error = await attempt_manual_match(
        harness,
        stage_id=STAGE_ONE_LEG,
        home_team_id=TEAM_ONE,
        away_team_id=TEAM_TWO,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    assert await count_stage_matches(harness, STAGE_ONE_LEG) == 2


@pytest.mark.asyncio
async def test_a_match_with_one_empty_side_does_not_count(pairing_harness):
    harness = pairing_harness

    # Creating a one-sided match is not blocked by the pairing rule.
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_ONE_LEG,
            home_team_id=TEAM_ONE,
            away_team_id=None,
        )
        is None
    )
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_ONE_LEG,
            home_team_id=TEAM_ONE,
            away_team_id=None,
        )
        is None
    )

    # The one-sided rows are not an existing meeting of the pair.
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_ONE_LEG,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )
    error = await attempt_manual_match(
        harness,
        stage_id=STAGE_ONE_LEG,
        home_team_id=TEAM_ONE,
        away_team_id=TEAM_TWO,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    assert await count_stage_matches(harness, STAGE_ONE_LEG) == 3


@pytest.mark.asyncio
async def test_another_stage_or_group_accepts_the_same_pair(pairing_harness):
    harness = pairing_harness

    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_ONE_LEG,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )
    # Another stage of the same version is a different scope.
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_OTHER,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )
    # Group A accepts it once...
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_GROUP,
            group_id=GROUP_A,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )
    error = await attempt_manual_match(
        harness,
        stage_id=STAGE_GROUP,
        group_id=GROUP_A,
        home_team_id=TEAM_ONE,
        away_team_id=TEAM_TWO,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    assert "Fase de grupos" in error.detail
    # ...and group B is a different scope.
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_GROUP,
            group_id=GROUP_B,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )


@pytest.mark.asyncio
async def test_swiss_keeps_one_meeting_regardless_of_the_persisted_legs(
    pairing_harness,
):
    harness = pairing_harness
    # The stage row says two legs, but Swiss never admits a second meeting.
    assert (
        await attempt_manual_match(
            harness,
            stage_id=STAGE_SWISS,
            home_team_id=TEAM_ONE,
            away_team_id=TEAM_TWO,
        )
        is None
    )
    error = await attempt_manual_match(
        harness,
        stage_id=STAGE_SWISS,
        home_team_id=TEAM_ONE,
        away_team_id=TEAM_TWO,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    assert "Fase suiza" in error.detail
    assert "máximo de 1 enfrentamiento" in error.detail
    assert await count_stage_matches(harness, STAGE_SWISS) == 1


@pytest.mark.asyncio
async def test_elimination_stage_allows_repeated_meetings(pairing_harness):
    harness = pairing_harness

    for _ in range(3):
        assert (
            await attempt_manual_match(
                harness,
                stage_id=STAGE_CUP,
                home_team_id=TEAM_ONE,
                away_team_id=TEAM_TWO,
            )
            is None
        )

    assert await count_stage_matches(harness, STAGE_CUP) == 3


@pytest.mark.asyncio
async def test_two_leg_generated_calendar_is_created_complete_and_limits_to_two(
    pairing_harness,
):
    harness = pairing_harness
    drawn = await draw_league(harness, stage_id=STAGE_TWO_LEG, legs=2)

    # Four teams and two legs: six pairs, each one played twice.
    assert drawn.match_count == 12
    assert await count_stage_matches(harness, STAGE_TWO_LEG) == 12
    assert await count_pair_matches(harness, STAGE_TWO_LEG) == 2

    # The generated calendar itself was not validated...
    error = await attempt_manual_match(
        harness,
        stage_id=STAGE_TWO_LEG,
        home_team_id=TEAM_ONE,
        away_team_id=TEAM_TWO,
    )
    assert isinstance(error, HTTPException)
    assert error.status_code == 409
    assert "Liga dos vueltas" in error.detail
    assert "máximo de 2 enfrentamientos" in error.detail
    # ...and the rejection left the complete calendar untouched.
    assert await count_stage_matches(harness, STAGE_TWO_LEG) == 12
