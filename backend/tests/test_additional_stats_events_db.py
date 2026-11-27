"""Penal atajado y posición de entrada en los tres flujos del acta (spec 052, T3).

Opt-in (``RUN_DATABASE_TESTS=1``): cierre clásico, partido en vivo y
rectificación guardan y devuelven ``penalty_saved`` y ``player_in_position``
(RF-007, RF-009); una posición fuera del catálogo de la modalidad es un 422 sin
escritura (RF-008); el marcador, la clasificación, el fair play y las sanciones
no cambian (RF-010).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.matches.errors import ENTRY_POSITION_INVALID
from app.modules.matches.schemas import MatchEventPayload
from db_helpers import set_tenant_context
from test_match_assists_db import (
    AssistMatch,
    _register_player,
    close,
    committed_application,
    event_payload,
    operation,
    read_match_state,
    read_standings,
    read_suspensions,
    report_of,
    result_summary,
    seeded_match,
    seeded_matches,
    suspension_signature,
)
from test_match_live_close_db import close_live, request as live_review_request
from test_match_live_db import command, live_service_db as live_service_db
from test_migration_031 import PLAYER_AWAY, PLAYER_HOME_SECOND, TEAM_AWAY, TOURNAMENT
from test_migration_056 import MATCH, ORG, PLAYER_HOME_FIRST, SEGMENT_FIRST, TEAM_HOME
from test_rectification_flow import add_approver, assert_empty, create, decide, flow as flow, proposal
from tests.event_ids import event_id


# ---------------------------------------------------------------------------
# Cierre clásico
# ---------------------------------------------------------------------------


async def register_substitute(engine, match: AssistMatch, dorsal_number: int = 14) -> UUID:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        player_id = await _register_player(
            session, match.tenant, tournament_id=match.tournament_id, match_id=match.match_id,
            team_id=match.home_team_id, dorsal_number=dorsal_number,
        )
        await session.execute(
            text("UPDATE match_rosters SET role = 'substitute' WHERE match_id = :match AND player_id = :player"),
            {"match": str(match.match_id), "player": str(player_id)},
        )
        await session.commit()
    return player_id


def substitution(match: AssistMatch, player_in_id: UUID, *, label: str, position: str | None) -> MatchEventPayload:
    return MatchEventPayload(
        client_event_id=event_id(label), event_type="substitution", team_id=match.home_team_id,
        player_id=match.home_assist_id, player_out_id=match.home_assist_id, player_in_id=player_in_id,
        player_in_position=position, minute=60, segment_id=match.segment_id,
    )


def penalty_saved(match: AssistMatch, *, label: str) -> MatchEventPayload:
    return event_payload(
        match, label=label, event_type="penalty_saved", team_id=match.away_team_id,
        player_id=match.away_scorer_id, minute=70,
    )


def full_report(match: AssistMatch, substitute: UUID, *, label: str, position: str | None, saved: bool):
    events = [
        event_payload(match, label=f"{label}-goal", minute=30),
        substitution(match, substitute, label=f"{label}-sub", position=position),
    ]
    if saved:
        events.append(penalty_saved(match, label=f"{label}-saved"))
    return report_of(*events)


async def read_new_columns(engine, match: AssistMatch) -> list[tuple[str, str | None]]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        rows = (await session.execute(
            text("""SELECT event_type, player_in_position FROM match_events
                    WHERE organization_id = :org AND match_id = :match ORDER BY minute, id"""),
            {"org": str(match.tenant.organization_id), "match": str(match.match_id)},
        )).all()
    return [tuple(row) for row in rows]


async def test_classic_close_persists_and_returns_both_facts(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        substitute = await register_substitute(engine, match)

        await close(engine, context, match.match_id,
                    full_report(match, substitute, label="t3-classic", position="ST", saved=True))

        assert await read_new_columns(engine, match) == [
            ("goal", None), ("substitution", "ST"), ("penalty_saved", None),
        ]
        events = (await operation(engine, context, match.match_id))["events"]
        assert {(event["event_type"], event["player_in_position"]) for event in events} == {
            ("goal", None), ("substitution", "ST"), ("penalty_saved", None),
        }
        state = await read_match_state(engine, match)
        assert (state["home_score"], state["away_score"]) == (1, 0)


@pytest.mark.parametrize("position", ["SW", "XX"])
async def test_classic_close_rejects_a_position_outside_the_catalog_without_writing(database_admin_url, position):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        substitute = await register_substitute(engine, match)

        with pytest.raises(HTTPException) as rejected:
            await close(engine, context, match.match_id,
                        full_report(match, substitute, label="t3-invalid", position=position, saved=True))

        assert rejected.value.status_code == 422
        assert rejected.value.code == ENTRY_POSITION_INVALID
        assert await read_new_columns(engine, match) == []
        assert (await read_match_state(engine, match))["status"] == "scheduled"


async def test_classic_retry_with_a_different_position_is_immutable(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        substitute = await register_substitute(engine, match)
        seeded = event_id("t3-retry-sub")
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await set_tenant_context(session, match.tenant)
            await session.execute(
                text("""INSERT INTO match_events
                        (organization_id, match_id, segment_id, team_id, player_id, player_out_id,
                         player_in_id, player_in_position, event_type, minute, client_event_id)
                        VALUES (:org, :match, :segment, :team, :player, :player, :player_in, 'ST',
                                'substitution', 60, :client)"""),
                {"org": str(match.tenant.organization_id), "match": str(match.match_id),
                 "segment": str(match.segment_id), "team": str(match.home_team_id),
                 "player": str(match.home_assist_id), "player_in": str(substitute), "client": seeded},
            )
            await session.commit()
        dto = report_of(
            event_payload(match, label="t3-retry-goal", minute=30),
            substitution(match, substitute, label="t3-retry-sub", position="CB"),
        )

        with pytest.raises(HTTPException) as rejected:
            await close(engine, context, match.match_id, dto)

        assert rejected.value.status_code == 409 and "inmutable" in rejected.value.detail
        assert await read_new_columns(engine, match) == [("substitution", "ST")]


async def test_the_new_facts_change_no_score_standing_fair_play_or_sanction(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, (plain, enriched) = await seeded_matches(engine, 2)
        worlds = []
        for match, position, saved in ((plain, None, False), (enriched, "ST", True)):
            substitute = await register_substitute(engine, match)
            dto = full_report(match, substitute, label=f"t3-world-{position}", position=position, saved=saved)
            dto.events.append(event_payload(match, label=f"t3-world-{position}-red", event_type="red_card",
                                            team_id=match.away_team_id, player_id=match.away_scorer_id, minute=80))
            await close(engine, context, match.match_id, dto)
            worlds.append((
                result_summary(match, await read_match_state(engine, match)),
                await read_standings(engine, match),
                suspension_signature(await read_suspensions(engine, match)),
            ))

        assert worlds[0] == worlds[1]
        assert worlds[0][2], "la roja genera la misma sanción en los dos mundos"


# ---------------------------------------------------------------------------
# Partido en vivo
# ---------------------------------------------------------------------------


async def add_live_substitute(f) -> None:
    roster = await f.admin.fetchval(
        """INSERT INTO rosters(organization_id,tournament_id,team_id,player_id,dorsal_number,valid_from,eligible_from)
        VALUES ($1,$2,$3,$4,2,now(),now()) RETURNING id""",
        ORG, TOURNAMENT, TEAM_HOME, PLAYER_HOME_SECOND,
    )
    await f.admin.execute(
        """INSERT INTO match_rosters(organization_id,match_id,roster_id,player_id,team_id,role,is_valid)
        VALUES ($1,$2,$3,$4,$5,'substitute',TRUE)""",
        ORG, MATCH, roster, PLAYER_HOME_SECOND, TEAM_HOME,
    )


def live_substitution(position: str | None) -> dict:
    return dict(
        client_event_id=str(uuid4()), event_type="substitution", team_id=TEAM_HOME,
        player_id=PLAYER_HOME_FIRST, player_out_id=PLAYER_HOME_FIRST, player_in_id=PLAYER_HOME_SECOND,
        player_in_position=position, segment_id=SEGMENT_FIRST, minute=20,
    )


def live_penalty_saved() -> dict:
    return dict(
        client_event_id=str(uuid4()), event_type="penalty_saved", team_id=TEAM_AWAY,
        player_id=PLAYER_AWAY, segment_id=SEGMENT_FIRST, minute=10,
    )


async def test_live_draft_keeps_and_corrects_the_position_and_closes_with_it(live_service_db):
    f = live_service_db
    await add_live_substitute(f)
    sub = live_substitution("LCB")
    await f.call("execute", command("add_event", event=live_penalty_saved()))
    await f.call("execute", command("add_event", 1, event=sub))

    snapshot = await f.call("snapshot")
    assert (snapshot.home_score, snapshot.away_score) == (0, 0)
    assert [(e.event_type, e.player_in_position) for e in snapshot.events] == [
        ("penalty_saved", None), ("substitution", "LCB"),
    ]
    await f.call("execute", command("correct_event", 2, event_id=sub["client_event_id"],
                                    event={**sub, "player_in_position": "GK"}))
    assert await f.admin.fetchval(
        "SELECT player_in_position FROM match_live_events WHERE event_type='substitution' AND removed_at IS NULL"
    ) == "GK"

    receipt = await f.call("create_review", live_review_request(3))
    await f.permissions(["VIEW_MATCH_LIVE_DRAFT", "CLOSE_MATCH_REPORT"])
    await close_live(f, receipt["live_review_id"], result=live_review_request(3).result)
    rows = await f.admin.fetch("SELECT event_type, player_in_position FROM match_events ORDER BY minute")
    assert [tuple(row) for row in rows] == [("penalty_saved", None), ("substitution", "GK")]
    assert await f.admin.fetchval("SELECT home_score + away_score FROM matches WHERE id=$1", MATCH) == 0


async def test_live_rejects_a_position_outside_the_catalog_without_writing(live_service_db):
    f = live_service_db
    await add_live_substitute(f)

    with pytest.raises(HTTPException) as rejected:
        await f.call("execute", command("add_event", event=live_substitution("SW")))

    assert rejected.value.status_code == 422
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_events") == 0
    assert await f.admin.fetchval("SELECT count(*) FROM match_live_state") == 0


# ---------------------------------------------------------------------------
# Rectificación
# ---------------------------------------------------------------------------

RECTIFICATION = {"schema": 999}


async def make_substitute(flow) -> None:
    await flow.admin.execute(
        "UPDATE match_rosters SET role = 'substitute' WHERE match_id = $1 AND player_id = $2",
        MATCH, PLAYER_HOME_SECOND,
    )


def rectified(position: str) -> dict:
    payload = proposal()
    payload["proposed_report"]["events"] += [
        live_substitution(position) | {"minute": 30},
        live_penalty_saved() | {"minute": 40},
    ]
    return payload


@pytest.mark.parametrize("flow", [RECTIFICATION], indirect=True)
async def test_rectification_publishes_both_facts_in_the_version(flow):
    await make_substitute(flow)
    created = await create(flow, rectified("CB"))
    assert created.status_code == 201, created.text
    flow.context = await add_approver(flow)

    decided = await decide(flow, created.json()["id"])

    assert decided.status_code == 200, decided.text
    rows = await flow.admin.fetch(
        "SELECT event_type, player_in_position FROM match_report_version_events ORDER BY minute"
    )
    assert [tuple(row) for row in rows] == [("goal", None), ("substitution", "CB"), ("penalty_saved", None)]
    version = (await flow.client.get(f"/api/v1/matches/{MATCH}/report-versions/2")).json()
    assert {(e["event_type"], e["player_in_position"]) for e in version["report"]["events"]} == {
        ("goal", None), ("substitution", "CB"), ("penalty_saved", None),
    }
    current = await flow.admin.fetch(
        "SELECT event_type, player_in_position FROM v_match_current_events WHERE match_id = $1 ORDER BY minute", MATCH
    )
    assert [tuple(row) for row in current] == [tuple(row) for row in rows]
    assert await flow.admin.fetchval("SELECT home_score FROM v_match_current_report WHERE match_id = $1", MATCH) == 1


@pytest.mark.parametrize("flow", [RECTIFICATION], indirect=True)
async def test_rectification_rejects_a_position_outside_the_catalog_without_writing(flow):
    await make_substitute(flow)

    response = await create(flow, rectified("SW"))

    assert response.status_code == 422, response.text
    assert response.json()["code"] == ENTRY_POSITION_INVALID
    await assert_empty(flow)
