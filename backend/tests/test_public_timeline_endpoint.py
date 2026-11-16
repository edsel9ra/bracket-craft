"""Cronología pública con datos reales (spec 037, T4).

Opt-in con ``RUN_DATABASE_TESTS=1``: dos organizaciones con partido confirmado,
goles, amarilla y plantillas; la respuesta respeta la lista cerrada, no mezcla
organizaciones y responde el mismo 404 ante partido inexistente, cancelado o
de otro torneo.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from db_helpers import clear_rls_context, set_tenant_context
from test_public_access_matrix import _assert_404_indistinguishable
from test_public_field_allowlist import EXPECTED_FIELDS
from test_public_stats_endpoints import (
    _confirm_goalless_match,
    _create_live_match_with_two_segments,
    _public_api,
    _publish_tournament,
    _seed_organization_stats,
    _skip_if_no_db,
)

EVENT_KEYS = EXPECTED_FIELDS["PublicTimelineEventResponse"]
PLAYER_KEYS = EXPECTED_FIELDS["PublicTimelinePlayerResponse"]


async def _match_id(session, tenant, tournament_id):
    await set_tenant_context(session, tenant)
    match_id = (
        await session.execute(
            text("SELECT id FROM matches WHERE tournament_id = :t"), {"t": str(tournament_id)}
        )
    ).scalar_one()
    await clear_rls_context(session)
    return match_id


def _path(tournament_id, match_id):
    return f"/api/v1/tournaments/public/{tournament_id}/matches/{match_id}/timeline"


@pytest.mark.asyncio
async def test_timeline_two_organizations_closed_fields_and_404(db_session, tenant_factory):
    _skip_if_no_db()
    first = await tenant_factory("Timeline A")
    second = await tenant_factory("Timeline B")
    await set_tenant_context(db_session, first)
    seeded_a = await _seed_organization_stats(db_session, first, label="A", scoring_side="home", goals=1)
    await set_tenant_context(db_session, second)
    seeded_b = await _seed_organization_stats(db_session, second, label="B", scoring_side="away", goals=2)
    await clear_rls_context(db_session)
    match_a = await _match_id(db_session, first, seeded_a["tournament_id"])
    match_b = await _match_id(db_session, second, seeded_b["tournament_id"])

    async with _public_api(db_session) as client:
        for seeded, match_id in ((seeded_a, match_a), (seeded_b, match_b)):
            response = await client.get(_path(seeded["tournament_id"], match_id))
            assert response.status_code == 200, response.text
            body = response.json()
            assert set(body) == EXPECTED_FIELDS["PublicMatchTimelineResponse"]
            assert body["availability"] == "available" and body["score_consistent"] is True
            assert body["match_id"] == str(match_id)
            goals = [e for e in body["events"] if e["event_type"] == "goal"]
            cards = [e for e in body["events"] if e["event_type"] == "yellow_card"]
            assert len(goals) == seeded["goals"] and len(cards) == 1
            own_players = {str(p) for p in seeded["player_ids"]}
            own_teams = {str(t) for t in seeded["team_ids"]}
            for item in body["events"]:
                assert set(item) == EVENT_KEYS
                assert set(item["player"]) == PLAYER_KEYS
                assert item["player"]["player_id"] in own_players
                assert item["team_id"] in own_teams
            keys = [(e["segment_number"], e["minute"], e["added_minute"]) for e in body["events"]]
            assert keys == sorted(keys)

        for path in (
            _path(seeded_a["tournament_id"], match_b),
            _path(seeded_b["tournament_id"], match_a),
            _path(seeded_a["tournament_id"], uuid4()),
            _path(uuid4(), match_a),
        ):
            _assert_404_indistinguishable(await client.get(path))

        invalid = await client.get(f"/api/v1/tournaments/public/{seeded_a['tournament_id']}/matches/x/timeline")
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_timeline_live_pending_confirmed_empty_and_cancelled_404(db_session, tenant_factory):
    _skip_if_no_db()
    tenant = await tenant_factory("Timeline states")
    await set_tenant_context(db_session, tenant)
    tournament_id, version_id, match_id, home_team_id, _, _ = await _create_live_match_with_two_segments(
        db_session, tenant
    )
    stage_id, away_team_id = (
        await db_session.execute(
            text("SELECT stage_id, away_team_id FROM matches WHERE id = :m"), {"m": str(match_id)}
        )
    ).one()
    cancelled_id = (
        await db_session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES (:o, :t, :v, :s, :h, :a, 'cancelled', 2)
                RETURNING id
            """),
            {"o": str(tenant.organization_id), "t": str(tournament_id), "v": str(version_id),
             "s": str(stage_id), "h": str(home_team_id), "a": str(away_team_id)},
        )
    ).scalar_one()
    await _publish_tournament(db_session, tournament_id, version_id)
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        live = (await client.get(_path(tournament_id, match_id))).json()
        assert live == {"match_id": str(match_id), "availability": "pending", "score_consistent": True,
                        "segment_numbers": [], "events": []}
        _assert_404_indistinguishable(await client.get(_path(tournament_id, cancelled_id)))

        await set_tenant_context(db_session, tenant)
        await _confirm_goalless_match(db_session, match_id)
        await clear_rls_context(db_session)
        confirmed = (await client.get(_path(tournament_id, match_id))).json()
        assert confirmed == {"match_id": str(match_id), "availability": "available",
                             "score_consistent": True, "segment_numbers": [1, 2], "events": []}


@pytest.mark.asyncio
async def test_timeline_uses_current_rectified_version_without_voided(db_session, tenant_factory):
    """RF-005: solo la versión vigente del acta; los hechos anulados no aparecen."""

    _skip_if_no_db()
    tenant = await tenant_factory("Timeline rectified")
    await set_tenant_context(db_session, tenant)
    seeded = await _seed_organization_stats(db_session, tenant, label="R", scoring_side="home", goals=1)
    match_id, segment_id, team_id, player_id = (
        await db_session.execute(
            text("""
                SELECT me.match_id, me.segment_id, me.team_id, me.player_id
                FROM match_events me JOIN matches m ON m.id = me.match_id
                WHERE m.tournament_id = :t AND me.event_type = 'goal'
            """),
            {"t": str(seeded["tournament_id"])},
        )
    ).one()
    org = str(tenant.organization_id)
    request_id = (
        await db_session.execute(
            text("""
                INSERT INTO match_report_rectification_requests
                    (organization_id, match_id, base_version_number, proposed_report, reason,
                     requested_by_user_id, requested_by_member_id)
                VALUES (:org, :match, 1, '{}', 'Correction', :user, :member) RETURNING id
            """),
            {"org": org, "match": str(match_id), "user": str(tenant.user_id), "member": str(tenant.member_id)},
        )
    ).scalar_one()
    version = (
        await db_session.execute(
            text("""
                INSERT INTO match_report_versions
                    (organization_id, match_id, version_number, supersedes_version_number,
                     resolution_type, home_score_regular, away_score_regular, home_score,
                     away_score, request_id, published_by_user_id)
                VALUES (:org, :match, 2, 1, 'regular', 2, 0, 2, 0, :request, :user) RETURNING id
            """),
            {"org": org, "match": str(match_id), "request": str(request_id), "user": str(tenant.user_id)},
        )
    ).scalar_one()
    await db_session.execute(
        text("""
            INSERT INTO match_report_version_events
                (organization_id, version_id, match_id, segment_id, team_id, player_id,
                 event_type, minute, client_event_id, is_voided)
            SELECT :org, :version, :match, :segment, :team, :player, 'goal', e.minute, e.client_id, e.voided
            FROM (VALUES (70, 'late', FALSE), (20, 'early', FALSE), (80, 'voided', TRUE))
                AS e(minute, client_id, voided)
        """),
        {"org": org, "version": str(version), "match": str(match_id), "segment": str(segment_id),
         "team": str(team_id), "player": str(player_id)},
    )
    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        body = (await client.get(_path(seeded["tournament_id"], match_id))).json()
    assert body["availability"] == "available" and body["score_consistent"] is True
    assert [(e["event_type"], e["minute"]) for e in body["events"]] == [("goal", 20), ("goal", 70)]
    assert {e["player"]["player_id"] for e in body["events"]} == {str(player_id)}
