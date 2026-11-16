"""Ficha pública del jugador con datos reales (spec 038, T4).

Opt-in con ``RUN_DATABASE_TESTS=1``: dos organizaciones; solo los torneos con
consentimiento de imagen entran en la ficha, las cifras coinciden con
``player-stats``, el retiro del consentimiento la oculta y cualquier otro caso
devuelve el mismo 404.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from db_helpers import clear_rls_context, set_tenant_context
from test_public_access_matrix import _assert_404_indistinguishable
from test_public_field_allowlist import EXPECTED_FIELDS
from test_public_stats_endpoints import _public_api, _seed_organization_stats, _skip_if_no_db
from test_public_timeline_endpoint import _match_id
from test_public_timeline_endpoint import _path as _timeline_path

NOT_FOUND = "Torneo público no encontrado"  # RF-002: el mismo 404 que el resto de lecturas públicas
STAT_FIELDS = ("matches_played", "goals", "yellow_cards", "red_cards", "clean_sheets")


def _path(player_id):
    return f"/api/v1/tournaments/public/players/{player_id}"


async def _set_consent(session, tenant, player_id, consent: bool, *, active: bool | None = None):
    await set_tenant_context(session, tenant)
    params = {"consent": consent, "active": active, "player_id": str(player_id)}
    roster_ids = (
        await session.execute(text("SELECT id FROM rosters WHERE player_id = :player_id"), params)
    ).scalars().all()
    for roster_id in roster_ids:
        await session.execute(
            text("SELECT set_roster_photo_consent(:roster_id, :consent)"),
            {"roster_id": str(roster_id), "consent": consent},
        )
    if active is not None:
        await session.execute(
            text("UPDATE rosters SET is_active = :active WHERE player_id = :player_id"), params
        )
    await clear_rls_context(session)


async def _seed_two(db_session, tenant_factory):
    first = await tenant_factory("Profile A")
    second = await tenant_factory("Profile B")
    await set_tenant_context(db_session, first)
    seeded_a = await _seed_organization_stats(db_session, first, label="A", scoring_side="home", goals=2)
    await set_tenant_context(db_session, second)
    seeded_b = await _seed_organization_stats(db_session, second, label="B", scoring_side="away", goals=1)
    await clear_rls_context(db_session)
    return first, second, seeded_a, seeded_b


@pytest.mark.asyncio
async def test_profile_closed_fields_and_same_figures_as_player_stats(db_session, tenant_factory):
    _skip_if_no_db()
    first, _second, seeded_a, _seeded_b = await _seed_two(db_session, tenant_factory)
    scorer = seeded_a["scorers"][0]
    keeper = seeded_a["keeper_id"]
    for player in (scorer, keeper):
        await _set_consent(db_session, first, player, True)

    async with _public_api(db_session) as client:
        stats = (await client.get(f"/api/v1/tournaments/public/{seeded_a['tournament_id']}/player-stats")).json()
        by_player = {row["player_id"]: row for row in stats}
        for player in (scorer, keeper):
            response = await client.get(_path(player))
            assert response.status_code == 200, response.text
            body = response.json()
            assert set(body) == EXPECTED_FIELDS["PublicPlayerProfileResponse"]
            assert set(body["totals"]) == EXPECTED_FIELDS["PublicPlayerProfileTotalsResponse"]
            assert body["photo_url"] is None
            assert len(body["tournaments"]) == 1
            row = body["tournaments"][0]
            assert set(row) == EXPECTED_FIELDS["PublicPlayerProfileTournamentResponse"]
            assert row["tournament_id"] == str(seeded_a["tournament_id"])
            assert row["team_id"] == str(seeded_a["winning_team_id"])
            assert row["team_name"] == seeded_a["winning_team_name"]
            public = by_player[str(player)]
            assert (body["first_name"], body["last_name"]) == (public["first_name"], public["last_name"])
            assert {k: row[k] for k in STAT_FIELDS} == {k: public[k] for k in STAT_FIELDS}
            assert body["totals"] == {k: row[k] for k in STAT_FIELDS}
        assert (await client.get(_path(keeper))).json()["totals"]["clean_sheets"] == 1
        assert (await client.get(_path(scorer))).json()["totals"]["goals"] == 1


@pytest.mark.asyncio
async def test_profile_404_without_consent_other_org_unknown_and_after_revocation(db_session, tenant_factory):
    _skip_if_no_db()
    first, second, seeded_a, seeded_b = await _seed_two(db_session, tenant_factory)
    scorer_a = seeded_a["scorers"][0]
    scorer_b = seeded_b["scorers"][0]
    await _set_consent(db_session, first, scorer_a, True)

    async with _public_api(db_session) as client:
        assert (await client.get(_path(scorer_a))).status_code == 200
        for player in (scorer_b, seeded_a["scorers"][1], uuid4()):
            _assert_404_indistinguishable(await client.get(_path(player)), NOT_FOUND)

    await _set_consent(db_session, first, scorer_a, False)
    async with _public_api(db_session) as client:
        _assert_404_indistinguishable(await client.get(_path(scorer_a)), NOT_FOUND)

    await _set_consent(db_session, second, scorer_b, True)
    async with _public_api(db_session) as client:
        body = (await client.get(_path(scorer_b))).json()
        assert [row["tournament_id"] for row in body["tournaments"]] == [str(seeded_b["tournament_id"])]


@pytest.mark.asyncio
async def test_profile_hidden_when_tournament_not_visible(db_session, tenant_factory):
    _skip_if_no_db()
    first, _second, seeded_a, _seeded_b = await _seed_two(db_session, tenant_factory)
    scorer = seeded_a["scorers"][0]
    await _set_consent(db_session, first, scorer, True)
    await set_tenant_context(db_session, first)
    await db_session.execute(
        text("UPDATE tournaments SET status = 'draft' WHERE id = :t"), {"t": str(seeded_a["tournament_id"])}
    )
    await clear_rls_context(db_session)
    async with _public_api(db_session) as client:
        _assert_404_indistinguishable(await client.get(_path(scorer)), NOT_FOUND)


@pytest.mark.asyncio
async def test_profile_retired_inscription_keeps_tournament_without_photo(db_session, tenant_factory):
    _skip_if_no_db()
    first, _second, seeded_a, _seeded_b = await _seed_two(db_session, tenant_factory)
    scorer = seeded_a["scorers"][0]
    await _set_consent(db_session, first, scorer, True, active=False)
    async with _public_api(db_session) as client:
        response = await client.get(_path(scorer))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["photo_url"] is None
        assert body["totals"]["goals"] == 1


@pytest.mark.asyncio
async def test_profile_available_in_player_stats_and_timeline_per_tournament(db_session, tenant_factory):
    """RF-009: el nombre enlaza solo si la inscripción de **ese** torneo tiene consentimiento."""

    _skip_if_no_db()
    first, _second, seeded_a, seeded_b = await _seed_two(db_session, tenant_factory)
    authorized = seeded_a["scorers"][0]
    await _set_consent(db_session, first, authorized, True)
    match_a = await _match_id(db_session, first, seeded_a["tournament_id"])

    async with _public_api(db_session) as client:
        stats = (await client.get(f"/api/v1/tournaments/public/{seeded_a['tournament_id']}/player-stats")).json()
        flags = {row["player_id"]: row["profile_available"] for row in stats}
        assert flags.pop(str(authorized)) is True
        assert flags and not any(flags.values())

        timeline = (await client.get(_timeline_path(seeded_a["tournament_id"], match_a))).json()
        players = [e["player"] for e in timeline["events"]]
        assert {p["player_id"]: p["profile_available"] for p in players if p["player_id"] == str(authorized)} == {
            str(authorized): True
        }
        assert not any(p["profile_available"] for p in players if p["player_id"] != str(authorized))

        other = (await client.get(f"/api/v1/tournaments/public/{seeded_b['tournament_id']}/player-stats")).json()
        assert not any(row["profile_available"] for row in other)

    await _set_consent(db_session, first, authorized, False)
    async with _public_api(db_session) as client:
        stats = (await client.get(f"/api/v1/tournaments/public/{seeded_a['tournament_id']}/player-stats")).json()
        assert not any(row["profile_available"] for row in stats)


async def _enroll(session, tenant, *, player_id, tournament_id, team_id, consent: bool):
    await set_tenant_context(session, tenant)
    await session.execute(
        text("""
            INSERT INTO rosters
                (organization_id, tournament_id, team_id, player_id, dorsal_number,
                 photo_consent, valid_from, eligible_from)
            VALUES (:organization_id, :tournament_id, :team_id, :player_id, 99,
                    :consent, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
            "player_id": str(player_id),
            "consent": consent,
        },
    )
    await clear_rls_context(session)


@pytest.mark.asyncio
async def test_profile_lists_only_authorized_tournaments_of_same_organization(db_session, tenant_factory):
    """DA-1/RF-005: varios torneos de una organización; solo los autorizados, con totales."""

    _skip_if_no_db()
    first = await tenant_factory("Profile multi")
    await set_tenant_context(db_session, first)
    one = await _seed_organization_stats(db_session, first, label="M1", scoring_side="home", goals=1)
    two = await _seed_organization_stats(db_session, first, label="M2", scoring_side="away", goals=1)
    three = await _seed_organization_stats(db_session, first, label="M3", scoring_side="home", goals=1)
    await clear_rls_context(db_session)
    player = one["scorers"][0]
    await _set_consent(db_session, first, player, True)
    await _enroll(db_session, first, player_id=player, tournament_id=two["tournament_id"],
                  team_id=two["winning_team_id"], consent=True)
    await _enroll(db_session, first, player_id=player, tournament_id=three["tournament_id"],
                  team_id=three["winning_team_id"], consent=False)

    async with _public_api(db_session) as client:
        response = await client.get(_path(player))
        assert response.status_code == 200, response.text
        body = response.json()
        listed = {row["tournament_id"]: row for row in body["tournaments"]}
        assert set(listed) == {str(one["tournament_id"]), str(two["tournament_id"])}
        assert listed[str(one["tournament_id"])]["goals"] == 1
        assert listed[str(two["tournament_id"])]["goals"] == 0
        assert listed[str(two["tournament_id"])]["team_name"] == two["winning_team_name"]
        for field in STAT_FIELDS:
            assert body["totals"][field] == sum(row[field] for row in body["tournaments"])

        stats_three = (await client.get(f"/api/v1/tournaments/public/{three['tournament_id']}/player-stats")).json()
        assert not any(row["profile_available"] for row in stats_three)


@pytest.mark.asyncio
async def test_profile_uses_current_rectified_version_like_player_stats(db_session, tenant_factory):
    """RF-004: tras una rectificación, las cifras de la versión vigente, iguales a `player-stats`."""

    _skip_if_no_db()
    tenant = await tenant_factory("Profile rectified")
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
    await _set_consent(db_session, tenant, player_id, True)

    async with _public_api(db_session) as client:
        stats = (await client.get(f"/api/v1/tournaments/public/{seeded['tournament_id']}/player-stats")).json()
        public = next(row for row in stats if row["player_id"] == str(player_id))
        body = (await client.get(_path(player_id))).json()
    assert public["goals"] == 2
    assert body["totals"] == {k: public[k] for k in STAT_FIELDS}
