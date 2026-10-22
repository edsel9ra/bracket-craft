"""Public player projections: definition, ownership and anonymous access (RF-005).

The last blocks close RF-019: the public API responses (tournament players are
only exposed through the published lineups) carry no age, document or birth
date, and ``v_public_tournament_players`` stays an **internal** projection that
no endpoint consumes. The projection keeps computing the derived age for the
application role; «público» means an API response, not the application role's
read access.

These tests run as ``bracket_app`` (no superuser, no ``BYPASSRLS``) against a
PostgreSQL instance migrated with 015. Every test builds its own organization,
published tournament version, teams, players, rosters, match, segment and
lineup, so nothing depends on demo data, on the database being empty or on the
execution order; the ``db_session`` fixture rolls the whole tenant back.

The public projections are read without ``app.current_organization_id``: they
must keep working because their owner is exempt from RLS, must not leak another
organization's tournament, must not expose workspace-only player fields and
must never return the unpublished tactical formation. The raw definition that
feeds the wrapper stays inaccessible to the application role.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import api
from db_helpers import clear_rls_context, insert_player, set_tenant_context

TOURNAMENT_PLAYERS_VIEW = "v_public_tournament_players"
MATCH_LINEUPS_VIEW = "v_public_match_lineups"
RAW_LINEUPS_VIEW = "v_public_match_lineups_unpublished"
PUBLIC_VIEWS = (TOURNAMENT_PLAYERS_VIEW, MATCH_LINEUPS_VIEW, RAW_LINEUPS_VIEW)
SENSITIVE_COLUMNS = (
    "document_type",
    "national_id_encrypted",
    "national_id_hmac",
    "birth_date",
)
#: Derived or identifying player data that never belongs to a public response.
FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "age",
        "public_age",
        "birth_date",
        "birth_date_encrypted",
        "national_id",
        "national_id_encrypted",
        "national_id_hmac",
        "document_type",
    }
)
#: The player contract of ``GET /tournaments/public/{id}/matches``: no more keys.
PUBLIC_LINEUP_PLAYER_KEYS = frozenset(
    {
        "player_id",
        "first_name",
        "last_name",
        "dorsal_number",
        "role",
        "position_slot",
        "photo_url",
    }
)
FORBIDDEN_PUBLIC_VIEW_COLUMNS = frozenset(
    {"age", "public_age", *SENSITIVE_COLUMNS}
)
BACKEND_APP_DIR = Path(__file__).resolve().parents[1] / "app"


async def _create_tournament(
    session, tenant, *, label: str, start_date: str = "2026-01-01"
) -> tuple[UUID, UUID, UUID]:
    """Create a draft tournament with its first version and one round-robin stage."""

    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, :season, CAST(:start_date AS DATE),
                     'draft', '{}'::jsonb)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T004 {label} {uuid4().hex[:8]}",
                "season": start_date[:4],
                "start_date": date.fromisoformat(start_date),
            },
        )
    ).scalar_one()

    version_id = (
        await session.execute(
            text("""
                INSERT INTO tournament_versions
                    (organization_id, tournament_id, version_number, rules_config,
                     phase_config, status, created_by_member_id)
                VALUES
                    (:organization_id, :tournament_id, 1, '{}'::jsonb, '{}'::jsonb,
                     'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "member_id": str(tenant.member_id),
            },
        )
    ).scalar_one()

    stage_id = (
        await session.execute(
            text("""
                INSERT INTO stages
                    (organization_id, tournament_id, tournament_version_id, name,
                     stage_type, stage_order)
                VALUES
                    (:organization_id, :tournament_id, :version_id, 'Group stage',
                     'round_robin', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
            },
        )
    ).scalar_one()

    return tournament_id, version_id, stage_id


async def _register_team(
    session,
    tenant,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    *,
    label: str,
) -> UUID:
    """Register a team, enroll it in the tournament and assign it to the stage."""

    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"Team {label} {uuid4().hex[:6]}",
                "short_code": f"{label[:2].upper()}{uuid4().hex[:5].upper()}",
            },
        )
    ).scalar_one()

    await session.execute(
        text("""
            INSERT INTO tournament_teams (organization_id, tournament_id, team_id, status)
            VALUES (:organization_id, :tournament_id, :team_id, 'registered')
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "team_id": str(team_id),
        },
    )
    await session.execute(
        text("""
            INSERT INTO stage_teams
                (organization_id, tournament_id, tournament_version_id, stage_id, team_id)
            VALUES (:organization_id, :tournament_id, :version_id, :stage_id, :team_id)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "tournament_id": str(tournament_id),
            "version_id": str(version_id),
            "stage_id": str(stage_id),
            "team_id": str(team_id),
        },
    )
    return team_id


async def _insert_roster(
    session,
    tenant,
    tournament_id: UUID,
    team_id: UUID,
    player_id: UUID,
    *,
    dorsal_number: int,
    is_active: bool = True,
    photo_consent: bool = False,
) -> tuple[UUID, str | None]:
    """Create a roster row and return ``(roster_id, photo_object_key)``.

    ``is_active`` is updated after the insert and the photo metadata is written
    through the ``SECURITY DEFINER`` helpers, because the application role only
    holds column-scoped grants (``010``). The returned key is the value the
    public projection must expose as ``photo_url`` when there is consent.
    """

    roster_id = (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id, :dorsal_number,
                     :photo_consent, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "dorsal_number": dorsal_number,
                "photo_consent": photo_consent,
            },
        )
    ).scalar_one()

    if not is_active:
        await session.execute(
            text("UPDATE rosters SET is_active = FALSE WHERE id = :roster_id"),
            {"roster_id": str(roster_id)},
        )

    if not photo_consent:
        return roster_id, None

    photo_object_key = (
        f"private/organizations/{tenant.organization_id}/tournaments/{tournament_id}"
        f"/rosters/{roster_id}/photo.jpg"
    )
    await session.execute(
        text("SELECT set_roster_photo_object(:roster_id, :photo_object_key)"),
        {"roster_id": str(roster_id), "photo_object_key": photo_object_key},
    )
    return roster_id, photo_object_key


async def _create_match(
    session,
    tenant,
    tournament_id: UUID,
    version_id: UUID,
    stage_id: UUID,
    home_team_id: UUID,
    away_team_id: UUID,
) -> UUID:
    """Create a scheduled match inside a still-draft version."""

    return (
        await session.execute(
            text("""
                INSERT INTO matches
                    (organization_id, tournament_id, tournament_version_id, stage_id,
                     home_team_id, away_team_id, status, matchday)
                VALUES
                    (:organization_id, :tournament_id, :version_id, :stage_id,
                     :home_team_id, :away_team_id, 'scheduled', 1)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "version_id": str(version_id),
                "stage_id": str(stage_id),
                "home_team_id": str(home_team_id),
                "away_team_id": str(away_team_id),
            },
        )
    ).scalar_one()


async def _create_segment(session, tenant, match_id: UUID) -> UUID:
    return (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 45, 'active')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one()


async def _publish_lineup(
    session,
    tenant,
    match_id: UUID,
    segment_id: UUID,
    team_id: UUID,
    player_ids: list[UUID],
    *,
    is_public: bool,
    formation_code: str = "4-3-3",
) -> None:
    """Take a lineup snapshot and publish (or keep private) its tactical formation."""

    for index, player_id in enumerate(player_ids, start=1):
        await session.execute(
            text("""
                INSERT INTO match_lineup_snapshots
                    (organization_id, match_id, segment_id, team_id, player_id,
                     is_starter, position_slot)
                VALUES
                    (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                     TRUE, :position_slot)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "segment_id": str(segment_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "position_slot": f"P{index}",
            },
        )

    await session.execute(
        text("""
            INSERT INTO match_team_lineups
                (organization_id, match_id, segment_id, team_id, formation_code,
                 is_public, published_at)
            VALUES
                (:organization_id, :match_id, :segment_id, :team_id, :formation_code,
                 :is_public, CASE WHEN :is_public THEN CURRENT_TIMESTAMP ELSE NULL END)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "segment_id": str(segment_id),
            "team_id": str(team_id),
            "formation_code": formation_code,
            "is_public": is_public,
        },
    )


async def _insert_match_roster(
    session,
    tenant,
    match_id: UUID,
    roster_id: UUID,
    player_id: UUID,
    team_id: UUID,
    *,
    role: str = "substitute",
) -> UUID:
    """Register a player in the classic match planilla."""

    return (
        await session.execute(
            text("""
                INSERT INTO match_rosters
                    (organization_id, match_id, roster_id, player_id, team_id, role, is_valid)
                VALUES
                    (:organization_id, :match_id, :roster_id, :player_id, :team_id, :role, TRUE)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
                "roster_id": str(roster_id),
                "player_id": str(player_id),
                "team_id": str(team_id),
                "role": role,
            },
        )
    ).scalar_one()


async def _publish_tournament(session, tournament_id: UUID, version_id: UUID) -> None:
    """Make the version and the tournament public, in the order the app does."""

    await session.execute(
        text("""
            UPDATE tournament_versions
            SET status = 'published', published_at = CURRENT_TIMESTAMP
            WHERE id = :version_id
        """),
        {"version_id": str(version_id)},
    )
    await session.execute(
        text("""
            UPDATE tournaments
            SET status = 'published', published_version_id = :version_id
            WHERE id = :tournament_id
        """),
        {"tournament_id": str(tournament_id), "version_id": str(version_id)},
    )


@pytest.mark.asyncio
async def test_public_tournament_players_projects_published_rosters_without_context(
    db_session, tenant_factory
):
    owner = await tenant_factory("Public Projection Owner")
    other = await tenant_factory("Public Projection Other")

    await set_tenant_context(db_session, owner)
    tournament_id, version_id, stage_id = await _create_tournament(
        db_session, owner, label="published"
    )
    team_id = await _register_team(
        db_session, owner, tournament_id, version_id, stage_id, label="A"
    )

    visible_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Public",
        last_name="Visible",
        reference_year=2026,
    )
    consenting_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="With",
        last_name="Consent",
        reference_year=2026,
    )
    inactive_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Inactive",
        last_name="Roster",
        reference_year=2026,
    )

    await _insert_roster(
        db_session, owner, tournament_id, team_id, visible_player, dorsal_number=10
    )
    _, photo_object_key = await _insert_roster(
        db_session,
        owner,
        tournament_id,
        team_id,
        consenting_player,
        dorsal_number=7,
        photo_consent=True,
    )
    assert photo_object_key is not None
    await _insert_roster(
        db_session,
        owner,
        tournament_id,
        team_id,
        inactive_player,
        dorsal_number=9,
        is_active=False,
    )
    await _publish_tournament(db_session, tournament_id, version_id)

    # Another organization keeps its own tournament unpublished.
    await set_tenant_context(db_session, other)
    other_tournament_id, other_version_id, other_stage_id = await _create_tournament(
        db_session, other, label="draft"
    )
    other_team_id = await _register_team(
        db_session, other, other_tournament_id, other_version_id, other_stage_id, label="B"
    )
    other_player_id = await insert_player(
        db_session,
        other.organization_id,
        first_name="Other",
        last_name="Organization",
        reference_year=2026,
    )
    await _insert_roster(
        db_session,
        other,
        other_tournament_id,
        other_team_id,
        other_player_id,
        dorsal_number=1,
    )

    # Anonymous public request: neither RLS context nor a workspace session.
    await clear_rls_context(db_session)

    # The application role sees no player row directly without a tenant context,
    # so the rows below can only come from the RLS-exempt view owner.
    assert (
        await db_session.execute(
            text("SELECT count(*) FROM players WHERE id IN (:visible, :consenting)"),
            {"visible": str(visible_player), "consenting": str(consenting_player)},
        )
    ).scalar_one() == 0

    rows = (
        await db_session.execute(
            text("""
                SELECT tournament_id, player_id, first_name, last_name, dorsal_number,
                       team_id, public_age, photo_url
                FROM v_public_tournament_players
                WHERE tournament_id IN (:published, :draft)
                ORDER BY dorsal_number
            """),
            {"published": str(tournament_id), "draft": str(other_tournament_id)},
        )
    ).mappings().all()

    assert {row["player_id"] for row in rows} == {visible_player, consenting_player}
    assert {row["dorsal_number"] for row in rows} == {7, 10}
    assert all(row["tournament_id"] == tournament_id for row in rows)
    assert all(row["team_id"] == team_id for row in rows)
    assert all(row["first_name"] in {"Public", "With"} for row in rows)
    assert all(row["public_age"] == 26 for row in rows)

    # The unpublished tournament of the other organization is not projected.
    assert other_tournament_id not in {row["tournament_id"] for row in rows}
    assert other_player_id not in {row["player_id"] for row in rows}

    # photo_url only when the roster has image consent.
    photo_by_player = {row["player_id"]: row["photo_url"] for row in rows}
    assert photo_by_player[consenting_player] == photo_object_key
    assert photo_by_player[visible_player] is None


@pytest.mark.asyncio
async def test_public_match_lineups_returns_only_the_published_formation_without_context(
    db_session, tenant_factory
):
    owner = await tenant_factory("Public Lineups Owner")

    await set_tenant_context(db_session, owner)
    tournament_id, version_id, stage_id = await _create_tournament(
        db_session, owner, label="lineups"
    )
    home_team_id = await _register_team(
        db_session, owner, tournament_id, version_id, stage_id, label="home"
    )
    away_team_id = await _register_team(
        db_session, owner, tournament_id, version_id, stage_id, label="away"
    )

    home_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Home",
        last_name="Starter",
        reference_year=2026,
    )
    consenting_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Home",
        last_name="Consent",
        reference_year=2026,
    )
    away_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Away",
        last_name="Hidden",
        reference_year=2026,
    )

    await _insert_roster(
        db_session, owner, tournament_id, home_team_id, home_player, dorsal_number=4
    )
    _, photo_object_key = await _insert_roster(
        db_session,
        owner,
        tournament_id,
        home_team_id,
        consenting_player,
        dorsal_number=9,
        photo_consent=True,
    )
    assert photo_object_key is not None
    await _insert_roster(
        db_session, owner, tournament_id, away_team_id, away_player, dorsal_number=5
    )

    match_id = await _create_match(
        db_session, owner, tournament_id, version_id, stage_id, home_team_id, away_team_id
    )
    segment_id = await _create_segment(db_session, owner, match_id)

    # The away player is also part of the classic planilla: an unpublished
    # tactical formation must not surface it either.
    away_roster_id = (
        await db_session.execute(
            text("""
                SELECT id FROM rosters
                WHERE tournament_id = :tournament_id AND player_id = :player_id
            """),
            {"tournament_id": str(tournament_id), "player_id": str(away_player)},
        )
    ).scalar_one()
    await _insert_match_roster(
        db_session, owner, match_id, away_roster_id, away_player, away_team_id
    )

    # The home formation is published explicitly; the away one stays private.
    await _publish_lineup(
        db_session,
        owner,
        match_id,
        segment_id,
        home_team_id,
        [home_player, consenting_player],
        is_public=True,
    )
    await _publish_lineup(
        db_session,
        owner,
        match_id,
        segment_id,
        away_team_id,
        [away_player],
        is_public=False,
        formation_code="4-4-2",
    )
    await _publish_tournament(db_session, tournament_id, version_id)

    await clear_rls_context(db_session)

    rows = (
        await db_session.execute(
            text("""
                SELECT match_id, tournament_id, team_id, formation_code, player_id,
                       first_name, last_name, dorsal_number, role, position_slot, photo_url
                FROM v_public_match_lineups
                WHERE match_id = :match_id
                ORDER BY dorsal_number
            """),
            {"match_id": str(match_id)},
        )
    ).mappings().all()

    assert rows, "la formación publicada debe estar disponible sin contexto de organización"
    assert {row["player_id"] for row in rows} == {home_player, consenting_player}
    assert {row["team_id"] for row in rows} == {home_team_id}
    assert {row["formation_code"] for row in rows} == {"4-3-3"}
    assert all(row["role"] == "starter" for row in rows)
    assert all(row["tournament_id"] == tournament_id for row in rows)

    # The unpublished formation of the away team is never returned.
    assert away_player not in {row["player_id"] for row in rows}
    assert away_team_id not in {row["team_id"] for row in rows}

    photo_by_player = {row["player_id"]: row["photo_url"] for row in rows}
    assert photo_by_player[consenting_player] == photo_object_key
    assert photo_by_player[home_player] is None


@pytest.mark.asyncio
async def test_raw_unpublished_lineups_view_is_inaccessible_to_the_application_role(db_session):
    await clear_rls_context(db_session)

    with pytest.raises(DBAPIError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                text("SELECT count(*) FROM v_public_match_lineups_unpublished")
            )

    assert "permission denied" in str(error.value).lower()


@pytest.mark.asyncio
async def test_public_view_grants_hide_the_raw_definition_and_keep_the_wrapper(db_session):
    rows = (
        await db_session.execute(
            text("""
                SELECT c.relname,
                       has_table_privilege('bracket_app', c.oid, 'SELECT') AS app_select,
                       EXISTS (
                           SELECT 1
                           FROM aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) acl
                           WHERE acl.grantee = 0
                             AND acl.privilege_type = 'SELECT'
                       ) AS public_select
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = ANY(:views)
            """),
            {"views": list(PUBLIC_VIEWS)},
        )
    ).mappings().all()

    grants = {row["relname"]: row for row in rows}
    assert set(grants) == set(PUBLIC_VIEWS)

    assert grants[TOURNAMENT_PLAYERS_VIEW]["app_select"] is True
    assert grants[MATCH_LINEUPS_VIEW]["app_select"] is True
    assert grants[RAW_LINEUPS_VIEW]["app_select"] is False

    for view, grant in grants.items():
        assert grant["public_select"] is False, f"{view} no debe ser accesible a PUBLIC"


@pytest.mark.asyncio
async def test_public_views_are_owned_by_an_rls_exempt_role_without_security_invoker(db_session):
    rows = (
        await db_session.execute(
            text("""
                SELECT c.relname,
                       pg_get_userbyid(c.relowner) AS owner_name,
                       r.rolsuper,
                       r.rolbypassrls,
                       COALESCE(array_to_string(c.reloptions, ','), '') AS options
                FROM pg_class c
                JOIN pg_roles r ON r.oid = c.relowner
                WHERE c.relname = ANY(:views)
            """),
            {"views": list(PUBLIC_VIEWS)},
        )
    ).mappings().all()

    definitions = {row["relname"]: row for row in rows}
    assert set(definitions) == set(PUBLIC_VIEWS)

    for view, definition in definitions.items():
        assert definition["owner_name"] != "bracket_app", (
            f"{view} no debe pertenecer al rol de aplicación"
        )
        assert definition["rolsuper"] or definition["rolbypassrls"], (
            f"el propietario de {view} debe estar exento de RLS"
        )
        options = definition["options"]
        assert "security_barrier=true" in options, f"{view} debe declarar security_barrier"
        assert "security_invoker" not in options, (
            f"{view} no debe usar security_invoker: la lectura anónima depende del "
            "propietario exento de RLS"
        )


@pytest.mark.asyncio
async def test_public_views_do_not_expose_sensitive_player_columns(db_session):
    columns = (
        await db_session.execute(
            text("""
                SELECT c.relname AS table_name, a.attname AS column_name
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = ANY(:views)
                  AND a.attnum > 0
                  AND NOT a.attisdropped
            """),
            {"views": list(PUBLIC_VIEWS)},
        )
    ).mappings().all()

    exposed = {row["column_name"] for row in columns}
    assert exposed.isdisjoint(SENSITIVE_COLUMNS)
    assert "photo_url" in exposed

    by_view = {}
    for row in columns:
        by_view.setdefault(row["table_name"], set()).add(row["column_name"])
    assert set(by_view) == set(PUBLIC_VIEWS)
    for view, view_columns in by_view.items():
        assert view_columns.isdisjoint(SENSITIVE_COLUMNS), f"{view} expone columnas sensibles"


@pytest.mark.asyncio
async def test_public_player_definitions_join_players_by_organization(db_session):
    definitions = {
        row["relname"]: " ".join(row["definition"].split())
        for row in (
            await db_session.execute(
                text("""
                    SELECT c.relname,
                           pg_get_viewdef(c.oid, true) AS definition
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = ANY(:views)
                """),
                {"views": list(PUBLIC_VIEWS)},
            )
        ).mappings().all()
    }
    assert set(definitions) == set(PUBLIC_VIEWS)

    tournament_players = definitions[TOURNAMENT_PLAYERS_VIEW]
    assert re.search(r"\bp\.organization_id = r\.organization_id\b", tournament_players), (
        "v_public_tournament_players debe unir players por (id, organization_id)"
    )
    assert "p.id = r.player_id" in tournament_players

    raw_lineups = definitions[RAW_LINEUPS_VIEW]
    assert re.search(r"\bp\.organization_id = ls\.organization_id\b", raw_lineups), (
        "la planilla táctica debe unir players por organización"
    )
    assert re.search(r"\bp\.organization_id = mr\.organization_id\b", raw_lineups), (
        "la planilla clásica debe unir players por organización"
    )
    assert "p.id = ls.player_id" in raw_lineups
    assert "p.id = mr.player_id" in raw_lineups

    # The wrapper consumes the raw definition: it must not add a players join
    # without the organization filter (today it adds none).
    wrapper = definitions[MATCH_LINEUPS_VIEW]
    assert RAW_LINEUPS_VIEW in wrapper
    for view in (TOURNAMENT_PLAYERS_VIEW, RAW_LINEUPS_VIEW):
        assert _players_join_conditions(definitions[view]), f"{view} debe unir players"
    for view, definition in definitions.items():
        for condition in _players_join_conditions(definition):
            assert re.search(r"\bp\.organization_id = \w+\.organization_id\b", condition), (
                f"{view} une players sin filtrar por organización: {condition}"
            )


@pytest.mark.asyncio
async def test_public_age_follows_the_start_year_delta_and_not_the_day(
    db_session, tenant_factory
):
    """RF-008: the public age is the materialized age plus the year delta."""

    owner = await tenant_factory("Public Age Delta")
    await set_tenant_context(db_session, owner)
    tournament_id, version_id, stage_id = await _create_tournament(
        db_session, owner, label="age-delta", start_date="2026-01-01"
    )
    team_id = await _register_team(
        db_session, owner, tournament_id, version_id, stage_id, label="age"
    )
    player_id = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Delta",
        last_name="Age",
        birth_date="2000-01-01",
        reference_year=2026,
    )
    await _insert_roster(
        db_session, owner, tournament_id, team_id, player_id, dorsal_number=8
    )
    await _publish_tournament(db_session, tournament_id, version_id)
    await clear_rls_context(db_session)

    async def _public_age() -> int:
        return (
            await db_session.execute(
                text(
                    "SELECT public_age FROM v_public_tournament_players "
                    "WHERE tournament_id = :tournament_id"
                ),
                {"tournament_id": str(tournament_id)},
            )
        ).scalar_one()

    # age = age_at_reference + (tournament year - reference year).
    assert await _public_age() == 26

    await set_tenant_context(db_session, owner)
    await db_session.execute(
        text("UPDATE tournaments SET start_date = DATE '2029-06-01' WHERE id = :id"),
        {"id": str(tournament_id)},
    )
    await clear_rls_context(db_session)
    assert await _public_age() == 29

    # A different day inside the same year does not change the age.
    await set_tenant_context(db_session, owner)
    await db_session.execute(
        text("UPDATE tournaments SET start_date = DATE '2029-12-31' WHERE id = :id"),
        {"id": str(tournament_id)},
    )
    await clear_rls_context(db_session)
    assert await _public_age() == 29


@pytest.mark.asyncio
async def test_public_player_projection_does_not_decrypt_or_use_per_row_queries(
    db_session,
):
    """RNF-003/RF-008: one join, no decryption and no per-player subquery."""

    definition = (
        await db_session.execute(
            text(
                "SELECT pg_get_viewdef(c.oid, true) "
                "FROM pg_class c WHERE c.oid = CAST(:view AS regclass)"
            ),
            {"view": f"public.{TOURNAMENT_PLAYERS_VIEW}"},
        )
    ).scalar_one()
    normalized = " ".join(definition.split()).lower()

    assert "pgp_sym_decrypt" not in normalized
    assert "birth_date" not in normalized
    assert "national_id" not in normalized
    # The projection is a single SELECT over joins: no scalar/exists subquery
    # that could run once per player.
    assert normalized.count("select") == 1
    assert "(select" not in normalized
    assert " exists " not in normalized

    plan = (
        await db_session.execute(
            text(f"EXPLAIN (FORMAT JSON) SELECT * FROM {TOURNAMENT_PLAYERS_VIEW}")
        )
    ).scalar_one()
    assert "SubPlan" not in str(plan)


def _players_join_conditions(definition: str) -> list[str]:
    """Return the ON condition of every ``JOIN players`` clause of a view."""

    conditions = []
    for segment in definition.split(" JOIN players ")[1:]:
        condition = segment.split(" ON ", 1)[1]
        conditions.append(re.split(r" (?:JOIN|LEFT|WHERE|GROUP|ORDER|UNION)\b", condition)[0])
    return conditions


@asynccontextmanager
async def _public_api(session):
    """Run the real public endpoints against the test transaction.

    The endpoints open their own ``db.begin()``, so every request gets a fresh
    API session joined to the fixture's connection: it reads the rows the test
    just created without committing them.
    """

    connection = await session.connection()

    async def database():
        request_session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield request_session
        finally:
            await request_session.close()

    api.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            yield client
    finally:
        api.dependency_overrides.pop(get_db, None)


def _json_keys(value) -> set[str]:
    """Collect every object key of a JSON document, at any depth."""

    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _json_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _json_keys(item)
    return keys


def test_no_backend_endpoint_consumes_the_internal_tournament_players_projection():
    """RF-019: the projection is internal; no endpoint query references it.

    A static scan of the backend application package is the contract check: a
    new endpoint that reads it has to add the view name and fails here.
    """

    offenders = sorted(
        str(path.relative_to(BACKEND_APP_DIR))
        for path in BACKEND_APP_DIR.rglob("*.py")
        if TOURNAMENT_PLAYERS_VIEW in path.read_text(encoding="utf-8")
    )
    assert offenders == [], (
        "ningún endpoint debe consumir la proyección interna "
        f"{TOURNAMENT_PLAYERS_VIEW}; referencias en: {offenders}"
    )


@pytest.mark.asyncio
async def test_public_view_sql_never_reads_documents_or_birth_dates(db_session):
    """RF-019: the SQL behind the public views exposes no sensitive source.

    Checking the JSON keys is not enough: the definitions must not even select
    or decrypt the document or the birth date.
    """

    definitions = {
        row["relname"]: " ".join(row["definition"].split()).lower()
        for row in (
            await db_session.execute(
                text("""
                    SELECT c.relname, pg_get_viewdef(c.oid, true) AS definition
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = ANY(:views)
                """),
                {"views": list(PUBLIC_VIEWS)},
            )
        ).mappings().all()
    }
    assert set(definitions) == set(PUBLIC_VIEWS)

    for view, definition in definitions.items():
        for forbidden in ("birth_date", "national_id", "pgp_sym_decrypt"):
            assert forbidden not in definition, f"{view} lee {forbidden}"


@pytest.mark.asyncio
async def test_tournament_players_projection_is_internal_and_keeps_the_derived_age(db_session):
    """RF-019: the projection still computes ``public_age`` for ``bracket_app``.

    «Público» means an API response: the tournament players projection keeps
    the derived age for the application role, is never returned by an endpoint
    and is not part of the published lineup contract.
    """

    rows = (
        await db_session.execute(
            text("""
                SELECT c.relname AS view_name, a.attname AS column_name
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = ANY(:views)
                  AND a.attnum > 0
                  AND NOT a.attisdropped
            """),
            {"views": list(PUBLIC_VIEWS)},
        )
    ).mappings().all()

    columns: dict[str, set[str]] = {}
    for row in rows:
        columns.setdefault(row["view_name"], set()).add(row["column_name"])
    assert set(columns) == set(PUBLIC_VIEWS)

    # Internal projection: the derived age is available to the application role.
    assert "public_age" in columns[TOURNAMENT_PLAYERS_VIEW]
    # Neither the published lineup nor its raw definition exposes it.
    for view in (MATCH_LINEUPS_VIEW, RAW_LINEUPS_VIEW):
        assert columns[view].isdisjoint(FORBIDDEN_PUBLIC_VIEW_COLUMNS), (
            f"{view} no puede exponer edad, documento ni fecha de nacimiento"
        )


@pytest.mark.asyncio
async def test_public_api_responses_never_expose_age_document_or_birth_date(
    db_session, tenant_factory
):
    """RF-019: the real public endpoints keep the minimal player contract."""

    owner = await tenant_factory("Public Contract Owner")
    await set_tenant_context(db_session, owner)
    tournament_id, version_id, stage_id = await _create_tournament(
        db_session, owner, label="contract"
    )
    home_team_id = await _register_team(
        db_session, owner, tournament_id, version_id, stage_id, label="home"
    )
    away_team_id = await _register_team(
        db_session, owner, tournament_id, version_id, stage_id, label="away"
    )

    # The players carry real documents and birth dates: they are stored
    # encrypted or derived and must not reach any public response.
    home_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Contract",
        last_name="Home",
        national_id_hmac="hmac-contract-home",
        birth_date="2001-04-12",
        reference_year=2026,
    )
    away_player = await insert_player(
        db_session,
        owner.organization_id,
        first_name="Contract",
        last_name="Away",
        national_id_hmac="hmac-contract-away",
        birth_date="1999-09-30",
        reference_year=2026,
    )
    await _insert_roster(
        db_session, owner, tournament_id, home_team_id, home_player, dorsal_number=6
    )
    await _insert_roster(
        db_session, owner, tournament_id, away_team_id, away_player, dorsal_number=2
    )

    match_id = await _create_match(
        db_session, owner, tournament_id, version_id, stage_id, home_team_id, away_team_id
    )
    segment_id = await _create_segment(db_session, owner, match_id)
    await _publish_lineup(
        db_session, owner, match_id, segment_id, home_team_id, [home_player], is_public=True
    )
    await _publish_tournament(db_session, tournament_id, version_id)

    await clear_rls_context(db_session)

    async with _public_api(db_session) as client:
        responses = {
            "listado": await client.get("/api/v1/tournaments/public"),
            "torneo": await client.get(f"/api/v1/tournaments/public/{tournament_id}"),
            "clasificación": await client.get(
                f"/api/v1/tournaments/public/{tournament_id}/standings"
            ),
            "partidos": await client.get(
                f"/api/v1/tournaments/public/{tournament_id}/matches"
            ),
        }

    for name, response in responses.items():
        assert response.status_code == 200, f"{name}: {response.text}"
        exposed = _json_keys(response.json())
        assert exposed.isdisjoint(FORBIDDEN_PUBLIC_KEYS), (
            f"{name} expone claves no públicas: {sorted(exposed & FORBIDDEN_PUBLIC_KEYS)}"
        )
        # The internal projection is not part of any public payload.
        assert "public_age" not in response.text
        assert TOURNAMENT_PLAYERS_VIEW not in response.text

    players = [
        player
        for match in responses["partidos"].json()
        for lineup in (match.get("lineup") or {}).values()
        if lineup
        for player in lineup["starters"] + lineup["substitutes"]
    ]
    assert players, "la formación publicada debe devolver jugadores"
    for player in players:
        assert set(player) == set(PUBLIC_LINEUP_PLAYER_KEYS), (
            f"el contrato público del jugador cambió: {sorted(player)}"
        )
