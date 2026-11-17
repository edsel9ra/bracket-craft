"""Endpoints de la spec 040 contra PostgreSQL real (opt-in ``RUN_DATABASE_TESTS=1``).

Cada prueba crea una base desechable hasta la 063 con dos grupos de cuatro
equipos en una fase de grupos (orden 1), una llave de eliminación simple
(orden 2) y una de doble eliminación (orden 3), en una versión en borrador.
"""

import asyncio
import json
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import get_db
from app.core.tenancy import AuthContext, get_auth_context
from app.main import api
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from db_helpers import application_database_url
from migration_helpers import throwaway_database

PREFIX = "40000000-0000-4000-8000-"
ORG = f"{PREFIX}000000000001"
USER = f"{PREFIX}000000000002"
MEMBER = f"{PREFIX}000000000003"
TOURNAMENT = f"{PREFIX}000000000004"
VERSION = f"{PREFIX}000000000005"
GROUP_STAGE = f"{PREFIX}000000000006"
KO_STAGE = f"{PREFIX}000000000007"
DE_STAGE = f"{PREFIX}000000000008"
GROUP_A = f"{PREFIX}0000000000a1"
GROUP_B = f"{PREFIX}0000000000b1"
TEAMS = [f"{PREFIX}0000000001{index:02d}" for index in range(8)]
START = "2026-12-01T10:00:00Z"
ENGINES: dict = {}
RULES = json.dumps(DEFAULT_RULES_CONFIG)


def seed_sql() -> str:
    teams = ",".join(f"('{team}', '{ORG}', 'Equipo {index}', 'E{index:02d}')" for index, team in enumerate(TEAMS))
    registered = ",".join(f"('{ORG}', '{TOURNAMENT}', '{team}', 'registered')" for team in TEAMS)
    stage_teams = ",".join(
        f"('{ORG}', '{TOURNAMENT}', '{VERSION}', '{GROUP_STAGE}', '{team}', '{GROUP_A if index < 4 else GROUP_B}')"
        for index, team in enumerate(TEAMS)
    )
    return f"""
    INSERT INTO organizations (id, name, slug) VALUES ('{ORG}', 'Org 040', 'org-040');
    INSERT INTO users (id, email, password_hash, full_name)
    VALUES ('{USER}', 'owner-040@example.test', 'hash', 'Owner 040');
    INSERT INTO organization_users (id, organization_id, user_id, is_active) VALUES ('{MEMBER}', '{ORG}', '{USER}', TRUE);
    WITH role AS (
        INSERT INTO roles (organization_id, role_definition_id, name, permissions)
        SELECT '{ORG}', id, 'Owner 040', system_permissions FROM role_definitions WHERE code = 'owner'
        RETURNING id
    )
    INSERT INTO organization_user_roles (organization_id, organization_user_id, role_id)
    SELECT '{ORG}', '{MEMBER}', id FROM role;
    INSERT INTO teams (id, organization_id, name, short_code) VALUES {teams};
    INSERT INTO tournaments (id, organization_id, name, season, start_date, status, current_draft_config)
    VALUES ('{TOURNAMENT}', '{ORG}', 'Copa 040', '2026', DATE '2026-12-01', 'draft', '{{}}'::jsonb);
    INSERT INTO tournament_versions (id, organization_id, tournament_id, version_number, rules_config,
        phase_config, status, created_by_member_id)
    VALUES ('{VERSION}', '{ORG}', '{TOURNAMENT}', 1, '{RULES}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER}');
    INSERT INTO stages (id, organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order)
    VALUES ('{GROUP_STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Grupos', 'custom_group', 1),
           ('{KO_STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Llave', 'single_elimination', 2),
           ('{DE_STAGE}', '{ORG}', '{TOURNAMENT}', '{VERSION}', 'Doble', 'double_elimination', 3);
    INSERT INTO groups (id, organization_id, tournament_id, tournament_version_id, stage_id, name)
    VALUES ('{GROUP_A}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{GROUP_STAGE}', 'Grupo A'),
           ('{GROUP_B}', '{ORG}', '{TOURNAMENT}', '{VERSION}', '{GROUP_STAGE}', 'Grupo B');
    INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status) VALUES {registered};
    INSERT INTO stage_teams (organization_id, tournament_id, tournament_version_id, stage_id, team_id, group_id)
    VALUES {stage_teams};
    """


@pytest.fixture
async def stack(database_admin_url):
    async with throwaway_database(database_admin_url, last=63) as admin:
        await admin.execute(seed_sql())
        name = await admin.fetchval("SELECT current_database()")
        engine = create_async_engine(make_url(application_database_url()).set(database=name))
        ENGINES["current"] = engine

        async def database():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        async def auth_context():
            return AuthContext(user_id=UUID(USER), organization_id=UUID(ORG), organization_user_id=UUID(MEMBER))

        api.dependency_overrides[get_db] = database
        api.dependency_overrides[get_auth_context] = auth_context
        try:
            async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
                yield client, admin
        finally:
            api.dependency_overrides.clear()
            await engine.dispose()


def url(stage: str, suffix: str = "") -> str:
    return f"/api/v1/tournaments/{TOURNAMENT}/stages/{stage}/slot-origins{suffix}"


def gp(group: str, position: int) -> dict:
    return {"kind": "group_position", "source_stage_id": GROUP_STAGE, "group_id": group, "position": position}


def best(position: int, ordinal: int) -> dict:
    return {"kind": "best_of_position", "source_stage_id": GROUP_STAGE, "position": position, "ordinal": ordinal}


def body(origins: list[dict], **extra) -> dict:
    return {"origins": origins, "start_date": START, **extra}


CLASSIC_FOUR = [gp(GROUP_A, 1), gp(GROUP_B, 1), gp(GROUP_A, 2), gp(GROUP_B, 2)]


async def slots(admin, stage: str) -> list:
    return await admin.fetch(
        "SELECT slot_code, source_type, source_reference FROM phase_slots WHERE stage_id = $1 ORDER BY slot_code",
        stage,
    )


@pytest.mark.asyncio
async def test_origins_template_proposes_classic_crossings_without_writing(stack):
    client, admin = stack
    response = await client.get(url(KO_STAGE, "/template"), params={"source_stage_id": GROUP_STAGE, "slots_count": 4})

    assert response.status_code == 200, response.text
    origins = [
        {key: item[key] for key in ("kind", "source_stage_id", "group_id", "position")}
        for item in response.json()["origins"]
    ]
    assert origins == CLASSIC_FOUR
    assert [item["seed"] for item in response.json()["origins"]] == [1, 2, 3, 4]
    assert await slots(admin, KO_STAGE) == []

    bad = await client.get(url(KO_STAGE, "/template"), params={"source_stage_id": KO_STAGE, "slots_count": 4})
    assert bad.status_code == 422
    assert bad.json()["detail"] == {"code": "invalid_source_stage"}
    too_many = await client.get(url(KO_STAGE, "/template"), params={"source_stage_id": GROUP_STAGE, "slots_count": 10})
    assert too_many.json()["detail"] == {"code": "not_enough_teams"}


@pytest.mark.asyncio
async def test_origins_put_in_draft_builds_the_bracket_with_empty_slots(stack):
    client, admin = stack
    response = await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "editable"
    assert [item["seed"] for item in payload["origins"]] == [1, 2, 3, 4]
    assert payload["source_stages"][0]["groups"] == [
        {"id": GROUP_A, "name": "Grupo A", "size": 4},
        {"id": GROUP_B, "name": "Grupo B", "size": 4},
    ]
    rows = await slots(admin, KO_STAGE)
    stage_rank = [row for row in rows if row["source_type"] == "stage_rank"]
    assert len(stage_rank) == 4
    matches = await admin.fetch(
        "SELECT bracket_code, home_team_id, away_team_id FROM matches WHERE stage_id = $1 ORDER BY bracket_code",
        KO_STAGE,
    )
    assert [row["bracket_code"] for row in matches] == ["FINAL", "SF1", "SF2"]
    assert all(row["home_team_id"] is None and row["away_team_id"] is None for row in matches)
    assert await admin.fetchval("SELECT count(*) FROM stage_teams WHERE stage_id = $1", KO_STAGE) == 0

    pairs = await admin.fetch(
        """SELECT (h.source_reference->>'seed')::int AS home, (a.source_reference->>'seed')::int AS away
           FROM matches m JOIN phase_slots h ON h.id = m.home_slot_id JOIN phase_slots a ON a.id = m.away_slot_id
           WHERE m.stage_id = $1 AND h.source_type = 'stage_rank' ORDER BY m.bracket_code""",
        KO_STAGE,
    )
    assert [(row["home"], row["away"]) for row in pairs] == [(1, 4), (2, 3)]

    again = await client.get(url(KO_STAGE))
    assert again.status_code == 200
    assert again.json()["origins"] == payload["origins"]


@pytest.mark.asyncio
async def test_origins_byes_go_to_the_top_seeds(stack):
    client, admin = stack
    six = CLASSIC_FOUR + [gp(GROUP_A, 3), gp(GROUP_B, 3)]
    response = await client.put(url(KO_STAGE), json=body(six))

    assert response.status_code == 200, response.text
    rows = await admin.fetch(
        """SELECT m.bracket_code, (ps.source_reference->>'seed')::int AS seed
           FROM matches m JOIN phase_slots ps ON ps.id IN (m.home_slot_id, m.away_slot_id)
           WHERE m.stage_id = $1 AND ps.source_type = 'stage_rank'""",
        KO_STAGE,
    )
    by_match: dict[str, set[int]] = {}
    for row in rows:
        by_match.setdefault(row["bracket_code"], set()).add(row["seed"])
    assert sorted(by_match.values(), key=min) == [{1}, {2}, {3, 6}, {4, 5}]
    assert {code for code, seeds in by_match.items() if seeds in ({1}, {2})} <= {"SF1", "SF2"}


@pytest.mark.asyncio
async def test_origins_invalid_declarations_are_422_per_slot_without_writes(stack):
    client, admin = stack
    response = await client.put(
        url(KO_STAGE), json=body([gp(GROUP_A, 1), gp(GROUP_A, 1), gp(GROUP_B, 5), best(2, 1)])
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "code": "invalid_slot_origins",
        "errors": [
            {"seed": 2, "code": "duplicate_origin"},
            {"seed": 3, "code": "position_out_of_range"},
        ],
    }
    assert await slots(admin, KO_STAGE) == []

    later_stage = await client.put(
        url(KO_STAGE), json=body([{**gp(GROUP_A, 1), "source_stage_id": DE_STAGE}, gp(GROUP_B, 1)])
    )
    assert later_stage.json()["detail"]["errors"] == [{"seed": 1, "code": "invalid_source_stage"}]

    mixed = await client.put(url(KO_STAGE), json=body([{**best(2, 1), "group_id": GROUP_A}, gp(GROUP_B, 1)]))
    assert mixed.status_code == 422
    assert "input" not in mixed.text


@pytest.mark.asyncio
async def test_origins_double_elimination_needs_a_power_of_two(stack):
    client, admin = stack
    six = CLASSIC_FOUR + [gp(GROUP_A, 3), gp(GROUP_B, 3)]
    rejected = await client.put(url(DE_STAGE), json=body(six))
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "invalid_slots_count"
    assert await slots(admin, DE_STAGE) == []

    accepted = await client.put(url(DE_STAGE), json=body(CLASSIC_FOUR))
    assert accepted.status_code == 200, accepted.text
    rows = await admin.fetch(
        """SELECT m.bracket_code FROM matches m JOIN phase_slots ps ON ps.id IN (m.home_slot_id, m.away_slot_id)
           WHERE m.stage_id = $1 AND ps.source_type = 'stage_rank'""",
        DE_STAGE,
    )
    assert sorted({row["bracket_code"] for row in rows}) == ["W1-1", "W1-2"]
    assert await admin.fetchval(
        "SELECT count(*) FROM phase_slots WHERE stage_id = $1 AND source_type = 'match_result'", DE_STAGE
    ) > 0


@pytest.mark.asyncio
async def test_origins_published_version_is_409(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))).status_code == 200
    await admin.execute("UPDATE tournament_versions SET status = 'published', published_at = now() WHERE id = $1", VERSION)

    response = await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR, replace_existing=True))
    assert response.status_code == 409
    assert (await client.delete(url(KO_STAGE))).status_code == 409
    frozen = await client.get(url(KO_STAGE))
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "frozen"
    assert len(frozen.json()["origins"]) == 4


@pytest.mark.asyncio
async def test_origins_block_manual_assignment_and_random_draw(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))).status_code == 200

    manual = await client.post(
        f"/api/v1/tournaments/{TOURNAMENT}/stages/{KO_STAGE}/teams", json={"team_ids": TEAMS[:2]}
    )
    assert manual.status_code == 409
    assert "orígenes" in manual.json()["detail"]
    draw = await client.post(
        f"/api/v1/tournaments/{TOURNAMENT}/matches/draw",
        json={"version_id": VERSION, "stage_id": KO_STAGE, "start_date": START},
    )
    assert draw.status_code == 409
    assert "orígenes" in draw.json()["detail"]
    created = await client.post(
        f"/api/v1/tournaments/{TOURNAMENT}/teams",
        json={"name": "Equipo nuevo", "short_code": "NEW01", "stage_id": KO_STAGE},
    )
    assert created.status_code == 409
    assert "orígenes" in created.json()["detail"]
    bulk = await client.post(
        f"/api/v1/tournaments/{TOURNAMENT}/teams/bulk",
        json={"teams": [{"name": "Equipo masivo", "short_code": "NEW02"}], "stage_id": KO_STAGE},
    )
    assert bulk.status_code == 409
    assert "orígenes" in bulk.json()["detail"]
    assert await admin.fetchval("SELECT count(*) FROM teams WHERE short_code LIKE 'NEW%'") == 0
    assert await admin.fetchval("SELECT count(*) FROM stage_teams WHERE stage_id = $1", KO_STAGE) == 0


@pytest.mark.asyncio
async def test_origins_delete_without_origins_keeps_a_manual_bracket(stack):
    client, admin = stack
    await admin.execute(
        """INSERT INTO matches (organization_id, tournament_id, tournament_version_id, stage_id)
           VALUES ($1, $2, $3, $4)""", UUID(ORG), UUID(TOURNAMENT), UUID(VERSION), UUID(KO_STAGE))
    assert (await client.delete(url(KO_STAGE))).status_code == 204
    assert await admin.fetchval("SELECT count(*) FROM matches WHERE stage_id = $1", KO_STAGE) == 1


@pytest.mark.asyncio
async def test_origins_regeneration_requires_replace_and_delete_restores_manual_mode(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))).status_code == 200

    conflict = await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))
    assert conflict.status_code == 409
    replaced = await client.put(
        url(KO_STAGE), json=body([gp(GROUP_A, 1), gp(GROUP_B, 1)], replace_existing=True)
    )
    assert replaced.status_code == 200, replaced.text
    assert len(replaced.json()["origins"]) == 2
    assert await admin.fetchval("SELECT count(*) FROM matches WHERE stage_id = $1", KO_STAGE) == 1

    assert (await client.delete(url(KO_STAGE))).status_code == 204
    assert await slots(admin, KO_STAGE) == []
    assert (await client.get(url(KO_STAGE))).json()["origins"] == []
    manual = await client.post(
        f"/api/v1/tournaments/{TOURNAMENT}/stages/{KO_STAGE}/teams", json={"team_ids": TEAMS[:2]}
    )
    assert manual.status_code == 201, manual.text
    blocked = await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))
    assert blocked.status_code == 409


@pytest.mark.asyncio
async def test_origins_stage_that_is_not_a_bracket_is_422_and_unknown_stage_404(stack):
    client, _ = stack
    assert (await client.get(url(GROUP_STAGE))).status_code == 422
    assert (await client.get(url(f"{PREFIX}0000000000ff"))).status_code == 404


async def play_groups(admin, *, group_a_score: int = 1, group_b_score: int = 2, skip: int | None = None) -> None:
    """Todos contra todos: en cada grupo gana siempre el de menor índice."""

    for offset, group, score in ((0, GROUP_A, group_a_score), (4, GROUP_B, group_b_score)):
        teams = [team for team in TEAMS[offset:offset + 4] if team != (TEAMS[skip] if skip is not None else None)]
        for home_index, home in enumerate(teams):
            for away in teams[home_index + 1:]:
                await admin.execute(
                    """INSERT INTO matches (organization_id, tournament_id, tournament_version_id, stage_id, group_id,
                           home_team_id, away_team_id, status, matchday, home_score_regular, away_score_regular,
                           home_score, away_score, resolution_type, result_confirmed)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, 'finished', 1, $8, 0, $8, 0, 'regular', TRUE)""",
                    ORG, TOURNAMENT, VERSION, GROUP_STAGE, group, home, away, score,
                )


PREVIEW = f"/api/v1/tournaments/{TOURNAMENT}/stages/{KO_STAGE}/resolution/preview"
SIX = CLASSIC_FOUR + [best(3, 1), best(3, 2)]


async def table_counts(admin) -> list:
    return [
        await admin.fetchval(f"SELECT count(*) FROM {table}")
        for table in ("standings", "stage_teams", "stage_slot_resolutions", "match_slot_assignments",
                      "administrative_audit_logs", "outbox_events", "phase_slots", "matches")
    ]


@pytest.mark.asyncio
async def test_preview_proposes_every_slot_without_writes(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(SIX))).status_code == 200
    await play_groups(admin)
    before = await table_counts(admin)

    response = await client.get(PREVIEW)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["resolvable"] is True
    assert len(payload["fingerprint"]) == 64
    assert [(slot["seed"], slot["team_id"], slot["reason"]) for slot in payload["slots"]] == [
        (1, TEAMS[0], None), (2, TEAMS[4], None), (3, TEAMS[1], None),
        (4, TEAMS[5], None), (5, TEAMS[2], None), (6, TEAMS[6], None),
    ]
    assert payload["slots"][0]["team_name"] == "Equipo 0"
    assert payload["source_stages"] == [{"id": GROUP_STAGE, "finished": True}]
    assert await table_counts(admin) == before
    assert (await client.get(PREVIEW)).json()["fingerprint"] == payload["fingerprint"]


@pytest.mark.asyncio
async def test_preview_blocks_every_slot_while_the_source_stage_is_unfinished(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))).status_code == 200
    await play_groups(admin)
    first = (await client.get(PREVIEW)).json()["fingerprint"]
    await admin.execute(
        """INSERT INTO matches (organization_id, tournament_id, tournament_version_id, stage_id, group_id,
               home_team_id, away_team_id, status, matchday)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'scheduled', 2)""",
        ORG, TOURNAMENT, VERSION, GROUP_STAGE, GROUP_A, TEAMS[0], TEAMS[1],
    )

    payload = (await client.get(PREVIEW)).json()
    assert payload["resolvable"] is False
    assert {slot["reason"] for slot in payload["slots"]} == {"source_stage_unfinished"}
    assert all(slot["team_id"] is None for slot in payload["slots"])
    assert payload["source_stages"] == [{"id": GROUP_STAGE, "finished": False}]
    assert payload["fingerprint"] != first


@pytest.mark.asyncio
async def test_preview_reports_unresolved_ties_per_slot(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(SIX))).status_code == 200
    await play_groups(admin, group_a_score=0)

    payload = (await client.get(PREVIEW)).json()
    reasons = {slot["seed"]: slot["reason"] for slot in payload["slots"]}
    assert payload["resolvable"] is False
    assert reasons == {1: "unresolved_tie", 2: None, 3: "unresolved_tie", 4: None,
                       5: "unresolved_tie", 6: "unresolved_tie"}


@pytest.mark.asyncio
async def test_preview_best_of_rejects_groups_that_became_unequal(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(SIX))).status_code == 200
    await admin.execute("DELETE FROM stage_teams WHERE stage_id = $1 AND team_id = $2", GROUP_STAGE, TEAMS[7])
    await play_groups(admin, skip=7)

    payload = (await client.get(PREVIEW)).json()
    reasons = {slot["seed"]: slot["reason"] for slot in payload["slots"]}
    assert reasons == {1: None, 2: None, 3: None, 4: None, 5: "unequal_groups", 6: "unequal_groups"}


@pytest.mark.asyncio
async def test_preview_marks_a_withdrawn_team_as_ineligible(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))).status_code == 200
    await play_groups(admin)
    await admin.execute(
        "UPDATE tournament_teams SET status = 'withdrawn' WHERE tournament_id = $1 AND team_id = $2",
        TOURNAMENT, TEAMS[0],
    )

    payload = (await client.get(PREVIEW)).json()
    assert payload["resolvable"] is False
    assert payload["slots"][0]["reason"] == "team_ineligible"
    assert payload["slots"][0]["team_id"] == TEAMS[0]
    assert [slot["reason"] for slot in payload["slots"][1:]] == [None, None, None]


@pytest.mark.asyncio
async def test_preview_query_count_does_not_grow_with_the_slots(stack):
    client, admin = stack
    await play_groups(admin)
    statements: list[str] = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    sync_engine = ENGINES["current"].sync_engine
    counts = []
    for origins in ([gp(GROUP_A, 1), gp(GROUP_B, 1)], SIX):
        assert (await client.put(url(KO_STAGE), json=body(origins, replace_existing=True))).status_code == 200
        statements.clear()
        event.listen(sync_engine, "before_cursor_execute", record)
        try:
            assert (await client.get(PREVIEW)).status_code == 200
        finally:
            event.remove(sync_engine, "before_cursor_execute", record)
        counts.append(len(statements))
    assert counts[0] == counts[1]


@pytest.mark.asyncio
async def test_preview_without_origins_is_422_and_not_a_bracket_422(stack):
    client, _ = stack
    response = await client.get(PREVIEW)
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "no_slot_origins"}
    other = await client.get(f"/api/v1/tournaments/{TOURNAMENT}/stages/{GROUP_STAGE}/resolution/preview")
    assert other.status_code == 422


RESOLUTION = f"/api/v1/tournaments/{TOURNAMENT}/stages/{KO_STAGE}/resolution"


async def published_bracket(client, admin, origins=CLASSIC_FOUR) -> str:
    assert (await client.put(url(KO_STAGE), json=body(origins))).status_code == 200
    await play_groups(admin)
    await admin.execute("UPDATE tournament_versions SET status = 'published', published_at = now() WHERE id = $1", VERSION)
    preview = (await client.get(PREVIEW)).json()
    assert preview["resolvable"] is True
    return preview["fingerprint"]


async def bracket_teams(admin) -> list:
    rows = await admin.fetch(
        "SELECT bracket_code, home_team_id, away_team_id FROM matches WHERE stage_id = $1 ORDER BY bracket_code",
        KO_STAGE,
    )
    return [(row["bracket_code"], str(row["home_team_id"] or ""), str(row["away_team_id"] or "")) for row in rows]


@pytest.mark.asyncio
async def test_resolution_confirm_fills_every_slot_with_audit_and_events(stack):
    client, admin = stack
    fingerprint = await published_bracket(client, admin)
    before = await bracket_teams(admin)

    response = await client.post(RESOLUTION, json={"fingerprint": fingerprint})

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["fingerprint"] == fingerprint
    assert [(slot["seed"], slot["team_id"]) for slot in payload["slots"]] == [
        (1, TEAMS[0]), (2, TEAMS[4]), (3, TEAMS[1]), (4, TEAMS[5]),
    ]
    first_round = {(home, away) for _, home, away in await bracket_teams(admin) if home and away}
    assert first_round == {(TEAMS[0], TEAMS[5]), (TEAMS[4], TEAMS[1])}
    assert all(not home and not away for _, home, away in before)
    assert sorted(str(row["team_id"]) for row in await admin.fetch(
        "SELECT team_id FROM stage_teams WHERE stage_id = $1", KO_STAGE)) == sorted([TEAMS[0], TEAMS[1], TEAMS[4], TEAMS[5]])
    assignments = await admin.fetch(
        "SELECT origin, stage_slot_resolution_id FROM match_slot_assignments msa "
        "JOIN matches m ON m.id = msa.match_id WHERE m.stage_id = $1", KO_STAGE)
    assert {(row["origin"], str(row["stage_slot_resolution_id"])) for row in assignments} == {
        ("stage_rank", payload["resolution_id"])}
    assert len(assignments) == 4
    resolution = await admin.fetchrow("SELECT resolved_by_member_id, standings_fingerprint FROM stage_slot_resolutions")
    assert (str(resolution["resolved_by_member_id"]), resolution["standings_fingerprint"]) == (MEMBER, fingerprint)
    audit = await admin.fetch("SELECT entity_id, payload FROM administrative_audit_logs WHERE action = 'STAGE_SLOTS_RESOLVED'")
    assert len(audit) == 1 and str(audit[0]["entity_id"]) == payload["resolution_id"]
    assert set(json.loads(audit[0]["payload"])) == {"tournament_id", "version_id", "stage_id"}
    events = await admin.fetch("SELECT payload FROM outbox_events WHERE event_type = 'MATCH_UPDATED'")
    assert len(events) == 2
    assert {json.loads(row["payload"])["tournament_id"] for row in events} == {TOURNAMENT}

    assert (await client.get(url(KO_STAGE))).json()["status"] == "resolved"
    again = await client.post(RESOLUTION, json={"fingerprint": fingerprint})
    assert again.status_code == 409 and again.json()["detail"] == {"code": "already_resolved"}
    assert (await client.get(PREVIEW)).status_code == 409


@pytest.mark.asyncio
async def test_resolution_with_byes_fills_the_second_round(stack):
    client, admin = stack
    fingerprint = await published_bracket(client, admin, SIX)

    assert (await client.post(RESOLUTION, json={"fingerprint": fingerprint})).status_code == 201

    placed = [team for _, home, away in await bracket_teams(admin) for team in (home, away) if team]
    assert sorted(placed) == sorted([TEAMS[0], TEAMS[4], TEAMS[1], TEAMS[5], TEAMS[2], TEAMS[6]])
    assert await admin.fetchval("SELECT count(*) FROM outbox_events WHERE event_type = 'MATCH_UPDATED'") == 4


@pytest.mark.asyncio
async def test_resolution_stale_fingerprint_is_409_without_writes(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))).status_code == 200
    await play_groups(admin)
    extra = await admin.fetchval(
        """INSERT INTO matches (organization_id, tournament_id, tournament_version_id, stage_id, group_id,
               home_team_id, away_team_id, status, matchday)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'scheduled', 2) RETURNING id""",
        ORG, TOURNAMENT, VERSION, GROUP_STAGE, GROUP_A, TEAMS[2], TEAMS[3],
    )
    await admin.execute("UPDATE tournament_versions SET status = 'published', published_at = now() WHERE id = $1", VERSION)
    seen = (await client.get(PREVIEW)).json()
    assert seen["resolvable"] is False
    blocked = await client.post(RESOLUTION, json={"fingerprint": seen["fingerprint"]})
    assert blocked.status_code == 422
    assert {slot["reason"] for slot in blocked.json()["detail"]["slots"]} == {"source_stage_unfinished"}
    await admin.execute(
        "UPDATE matches SET status = 'finished', home_score_regular = 0, away_score_regular = 0, home_score = 0, "
        "away_score = 0, resolution_type = 'regular', result_confirmed = TRUE WHERE id = $1",
        extra,
    )
    before = await table_counts(admin)

    response = await client.post(RESOLUTION, json={"fingerprint": seen["fingerprint"]})

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "stale_fingerprint"}
    assert await table_counts(admin) == before
    assert await bracket_teams(admin) == [(code, "", "") for code, _, _ in await bracket_teams(admin)]


@pytest.mark.asyncio
async def test_resolution_needs_a_published_version(stack):
    client, admin = stack
    assert (await client.put(url(KO_STAGE), json=body(CLASSIC_FOUR))).status_code == 200
    await play_groups(admin)
    fingerprint = (await client.get(PREVIEW)).json()["fingerprint"]

    response = await client.post(RESOLUTION, json={"fingerprint": fingerprint})

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "version_not_published"}
    assert await admin.fetchval("SELECT count(*) FROM stage_slot_resolutions") == 0


@pytest.mark.asyncio
async def test_resolution_two_simultaneous_confirmations_fill_once(stack):
    client, admin = stack
    fingerprint = await published_bracket(client, admin)

    responses = await asyncio.gather(
        client.post(RESOLUTION, json={"fingerprint": fingerprint}),
        client.post(RESOLUTION, json={"fingerprint": fingerprint}),
    )

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert await admin.fetchval("SELECT count(*) FROM stage_slot_resolutions") == 1
    assert await admin.fetchval("SELECT count(*) FROM stage_teams WHERE stage_id = $1", KO_STAGE) == 4
    assert await admin.fetchval("SELECT count(*) FROM outbox_events WHERE event_type = 'MATCH_UPDATED'") == 2


@pytest.mark.asyncio
async def test_resolution_from_another_organization_is_404_without_writes(stack):
    client, admin = stack
    fingerprint = await published_bracket(client, admin)
    before = await table_counts(admin)

    async def outsider():
        return AuthContext(user_id=UUID(int=7), organization_id=UUID(int=8), organization_user_id=UUID(int=9))

    api.dependency_overrides[get_auth_context] = outsider
    response = await client.post(RESOLUTION, json={"fingerprint": fingerprint})
    preview = await client.get(PREVIEW)

    assert (response.status_code, preview.status_code) == (404, 404)
    assert await table_counts(admin) == before


@pytest.mark.asyncio
async def test_resolution_body_is_strict_and_does_not_echo_input(stack):
    client, admin = stack
    await published_bracket(client, admin)
    for payload in ({"fingerprint": "secreto"}, {"fingerprint": "a" * 64, "extra": 1}, {}):
        response = await client.post(RESOLUTION, json=payload)
        assert response.status_code == 422
        assert "secreto" not in response.text
    assert await admin.fetchval("SELECT count(*) FROM stage_slot_resolutions") == 0


async def publish_tournament(admin) -> None:
    await admin.execute(
        "UPDATE tournaments SET status = 'published', published_version_id = $1 WHERE id = $2", VERSION, TOURNAMENT,
    )


PUBLIC_KO = f"/api/v1/tournaments/public/{TOURNAMENT}/matches?stage_id={KO_STAGE}"


def origin(kind: str, group_name: str | None, position: int, ordinal: int | None) -> dict:
    return {"kind": kind, "group_name": group_name, "position": position, "ordinal": ordinal}


@pytest.mark.asyncio
async def test_public_bracket_labels_only_unresolved_slots(stack):
    client, admin = stack
    fingerprint = await published_bracket(client, admin, SIX)
    await publish_tournament(admin)
    response = await client.get(PUBLIC_KO)
    assert response.status_code == 200, response.text
    labels = [match[f"{side}_origin"] for match in response.json() for side in ("home", "away")]
    assert sorted((label for label in labels if label), key=json.dumps) == sorted([
        origin("group_position", "Grupo A", 1, None), origin("group_position", "Grupo B", 1, None),
        origin("group_position", "Grupo A", 2, None), origin("group_position", "Grupo B", 2, None),
        origin("best_of_position", None, 3, 1), origin("best_of_position", None, 3, 2),
    ], key=json.dumps)
    groups = (await client.get(f"/api/v1/tournaments/public/{TOURNAMENT}/matches?stage_id={GROUP_STAGE}")).json()
    assert groups and all(match["home_origin"] is None and match["away_origin"] is None for match in groups)

    assert (await client.post(RESOLUTION, json={"fingerprint": fingerprint})).status_code == 201
    filled = (await client.get(PUBLIC_KO)).json()
    first_round = [match for match in filled if match["home_team_id"] or match["away_team_id"]]
    assert len(first_round) >= 3
    assert all(match["home_origin"] is None and match["away_origin"] is None for match in filled)


@pytest.mark.asyncio
async def test_clone_remaps_origin_references_and_leaves_slots_unresolved(stack):
    client, admin = stack
    fingerprint = await published_bracket(client, admin)
    assert (await client.post(RESOLUTION, json={"fingerprint": fingerprint})).status_code == 201
    advanced = await admin.fetchval(
        "SELECT home_team_id FROM matches WHERE stage_id = $1 AND home_team_id IS NOT NULL LIMIT 1", KO_STAGE)
    await admin.execute(
        "UPDATE matches SET home_team_id = $2 WHERE stage_id = $1 AND home_team_id IS NULL AND away_team_id IS NULL",
        KO_STAGE, advanced)
    await publish_tournament(admin)
    response = await client.post(f"/api/v1/tournaments/{TOURNAMENT}/versions")
    assert response.status_code == 201, response.text
    new_version = response.json()["id"]
    stages = {row["name"]: str(row["id"]) for row in await admin.fetch(
        "SELECT id, name FROM stages WHERE tournament_version_id = $1", new_version)}
    groups = {str(row["id"]) for row in await admin.fetch(
        "SELECT id FROM groups WHERE tournament_version_id = $1", new_version)}
    references = [json.loads(row["source_reference"]) for row in await admin.fetch(
        """SELECT ps.source_reference::text FROM phase_slots ps
           WHERE ps.tournament_version_id = $1 AND ps.source_type = 'stage_rank'""", new_version)]
    assert len(references) == 4
    assert all(reference["source_stage_id"] == stages["Grupos"] for reference in references)
    assert {reference["group_id"] for reference in references} == groups
    assert await admin.fetchval(
        "SELECT count(*) FROM stage_teams WHERE stage_id = $1", UUID(stages["Llave"])) == 0
    assert await admin.fetchval(
        """SELECT count(*) FROM matches WHERE stage_id = $1
           AND (home_team_id IS NOT NULL OR away_team_id IS NOT NULL)""", UUID(stages["Llave"])) == 0
    assert await admin.fetchval(
        "SELECT count(*) FROM stage_teams WHERE stage_id = $1", UUID(stages["Grupos"])) == len(TEAMS)


@pytest.mark.asyncio
async def test_rectification_after_resolution_opens_later_phase_without_moving_slots(stack):
    from uuid import uuid4

    from app.core.database import set_rls_context
    from app.modules.rectifications.advancement import advancement_changes

    client, admin = stack
    fingerprint = await published_bracket(client, admin)
    assert (await client.post(RESOLUTION, json={"fingerprint": fingerprint})).status_code == 201
    before = await bracket_teams(admin)
    source = await admin.fetchrow(
        "SELECT id, home_team_id, away_team_id FROM matches WHERE stage_id = $1 ORDER BY id LIMIT 1", GROUP_STAGE)
    context = AuthContext(user_id=UUID(USER), organization_id=UUID(ORG), organization_user_id=UUID(MEMBER))
    version = {
        "id": uuid4(), "match_id": source["id"], "stage_id": UUID(GROUP_STAGE),
        "winner_team_id": source["home_team_id"],
        "advancement_before": {"tournament_version_id": UUID(VERSION), "bracket_code": None,
                               "winner_team_id": source["home_team_id"], "home_team_id": source["home_team_id"],
                               "away_team_id": source["away_team_id"]},
        "standings_before": {"rows": [{"group_id": GROUP_A, "team_id": TEAMS[0], "rank": 1},
                                      {"group_id": GROUP_A, "team_id": TEAMS[1], "rank": 2}]},
    }
    rows = [{"group_id": GROUP_A, "team_id": TEAMS[1], "rank": 1}, {"group_id": GROUP_A, "team_id": TEAMS[0], "rank": 2}]
    async with AsyncSession(ENGINES["current"], expire_on_commit=False) as db, db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        effects, candidates = await advancement_changes(db, context, version, rows)
    assert effects == []
    assert [(item.reason, item.stage_id, item.match_id) for item in candidates] == [("later_phase", UUID(KO_STAGE), None)]
    assert await bracket_teams(admin) == before
