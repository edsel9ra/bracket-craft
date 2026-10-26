"""Opt-in PostgreSQL coverage for assists: persistence, operation and idempotency.

Requires ``RUN_DATABASE_TESTS=1`` and ``DATABASE_ADMIN_URL`` (the database must
also have the application role). Each case builds a throwaway database at the
latest migrations, because the closing service owns the transaction it writes
in: the assertions read the committed state from an independent session.

Scope of T6 (spec 015):

* RF-007/RF-011 — the assist is stored with the rest of the act and returned by
  ``GET /matches/{id}/operation`` as a UUID, never with a name (D-6).
* RF-012/D-10 — the idempotency comparison includes ``metadata`` (normalising
  ``{}`` ↔ ``None``) and ``assist_player_id``; an identical retry reuses the row
  and a different one answers 409 «inmutable».
* RF-013 — an act without an assist, and a historical event with an unknown
  ``metadata`` key and a non-UUID ``client_event_id``, are read without
  revalidation.

Scope of T7 (spec 015), the closing block of 015A:

* RF-010 — two equivalent acts, one with an assist and one without it, produce
  the same score, the same standings, the same sanctions and the same outbox
  payload (the socket relay only forwards those rows, so the notification is the
  same too): the assist counts neither as a goal nor as a disciplinary fact.
* RF-013 — an act written before the 026 (no assist, unknown ``metadata`` key,
  non-UUID ``client_event_id``) is read and closed without being rewritten, the
  ``CHECK`` of the 026 blocks neither reads nor legitimate updates, and
  ``ASSIST_PLAYER_INVALID`` is never raised for it.
* RF-014 — the opt-in cases T5 declared and did not create: an assist from
  another organization or outside the match roster is a **409** with the additive
  ``code`` (never 404), and a segment, a team or a beneficiary team of another
  match or organization is a **404**.

The assist never changes the score, the standings or the suspensions, and
nothing here touches the public projections.
"""

from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.tenancy import AuthContext
from app.modules.matches.errors import ASSIST_PLAYER_INVALID, AssistPlayerInvalid
from app.modules.matches.router import close_match, get_match_operation
from app.modules.matches.schemas import CloseMatchReportDTO, MatchEventPayload
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from db_helpers import (
    TenantContext,
    create_tenant_owner,
    insert_player,
    set_tenant_context,
)
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)
from starlette.requests import Request
from tests.event_ids import event_id


def rules_config() -> dict:
    """Development rules with a single 90-minute regular segment."""

    config = deepcopy(DEFAULT_RULES_CONFIG)
    config["stage_defaults"] = {
        **config["stage_defaults"],
        "regular_time_minutes": 90,
        "extra_time_minutes": 120,
        "extra_time_enabled": False,
        "penalties_enabled": False,
    }
    return config


def context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


@dataclass(frozen=True)
class AssistMatch:
    tenant: TenantContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    match_id: UUID
    segment_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    home_scorer_id: UUID
    home_assist_id: UUID
    away_scorer_id: UUID


@asynccontextmanager
async def committed_application(database_admin_url):
    """Throwaway database at the latest migrations plus a dedicated role."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc015_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    engine = None
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1)
        await admin.execute(
            f"""
            CREATE ROLE "{role_name}" LOGIN PASSWORD '{role_password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            """
        )
        await admin.execute(f'GRANT bracket_app TO "{role_name}"')
        parsed = make_url(database_admin_url)
        app_url = (
            f"postgresql+asyncpg://{role_name}:{role_password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
        engine = create_async_engine(app_url, pool_pre_ping=True)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.close()
        await drop_database(database_admin_url, database)
        cleaner = await connect(database_admin_url)
        try:
            await cleaner.execute(f'DROP ROLE IF EXISTS "{role_name}"')
        finally:
            await cleaner.close()


async def _create_tournament(session, tenant: TenantContext) -> tuple[UUID, UUID, UUID]:
    payload = json.dumps(rules_config())
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments
                    (organization_id, name, season, start_date, status, current_draft_config)
                VALUES
                    (:organization_id, :name, '2026', '2026-01-01', 'draft',
                     CAST(:config AS jsonb))
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T6 assists {uuid4().hex[:8]}",
                "config": payload,
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
                    (:organization_id, :tournament_id, 1, CAST(:config AS jsonb),
                     '{}'::jsonb, 'draft', :member_id)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "member_id": str(tenant.member_id),
                "config": payload,
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
    session, tenant: TenantContext, tournament_id: UUID, version_id: UUID, stage_id: UUID
) -> UUID:
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T6 {uuid4().hex[:8]}",
                "short_code": f"T{uuid4().hex[:5].upper()}",
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


async def _register_player(
    session,
    tenant: TenantContext,
    *,
    tournament_id: UUID,
    match_id: UUID,
    team_id: UUID,
    dorsal_number: int,
) -> UUID:
    player_id = await insert_player(
        session,
        tenant.organization_id,
        first_name=f"T6{dorsal_number}",
        last_name=team_id.hex[:4],
        reference_year=2026,
    )
    roster_id = (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id,
                     :dorsal_number, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "tournament_id": str(tournament_id),
                "team_id": str(team_id),
                "player_id": str(player_id),
                "dorsal_number": dorsal_number,
            },
        )
    ).scalar_one()
    await session.execute(
        text("""
            INSERT INTO match_rosters
                (organization_id, match_id, roster_id, player_id, team_id, role, is_valid)
            VALUES
                (:organization_id, :match_id, :roster_id, :player_id, :team_id,
                 'starter', TRUE)
        """),
        {
            "organization_id": str(tenant.organization_id),
            "match_id": str(match_id),
            "roster_id": str(roster_id),
            "player_id": str(player_id),
            "team_id": str(team_id),
        },
    )
    return player_id


async def _create_closable_match(session, tenant: TenantContext) -> AssistMatch:
    """Published match with one active segment and a scorer+assist per side."""

    await set_tenant_context(session, tenant)
    tournament_id, version_id, stage_id = await _create_tournament(session, tenant)
    home_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
    )
    away_team_id = await _register_team(
        session, tenant, tournament_id, version_id, stage_id
    )
    match_id = (
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
    segment_id = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, minute_end, status)
                VALUES
                    (:organization_id, :match_id, 1, 0, 90, 'active')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "match_id": str(match_id),
            },
        )
    ).scalar_one()

    home_scorer_id = await _register_player(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=home_team_id,
        dorsal_number=9,
    )
    home_assist_id = await _register_player(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=home_team_id,
        dorsal_number=7,
    )
    away_scorer_id = await _register_player(
        session,
        tenant,
        tournament_id=tournament_id,
        match_id=match_id,
        team_id=away_team_id,
        dorsal_number=10,
    )

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
    return AssistMatch(
        tenant=tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        match_id=match_id,
        segment_id=segment_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_scorer_id=home_scorer_id,
        home_assist_id=home_assist_id,
        away_scorer_id=away_scorer_id,
    )


async def seeded_match(engine) -> tuple[AuthContext, AssistMatch]:
    """Create and commit one published match visible to independent sessions."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="T6 assists committed")
        match = await _create_closable_match(session, tenant)
        await session.commit()
    return context_for(tenant), match


async def seeded_matches(
    engine, count: int
) -> tuple[AuthContext, tuple[AssistMatch, ...]]:
    """Create ``count`` independent published matches inside one organization.

    Every match lives in its own tournament and stage, so its standings and its
    suspensions are independent and two of them can be compared as two
    equivalent worlds (RF-010). The second one also lends a player of the same
    organization who is **not** on the roster of the first (RF-014).
    """

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="T7 assists worlds")
        matches = tuple(
            [await _create_closable_match(session, tenant) for _ in range(count)]
        )
        await session.commit()
    return context_for(tenant), matches


async def seed_foreign_match(engine) -> AssistMatch:
    """Create one published match in a **different** organization.

    RF-014 needs identifiers that exist but belong to another organization, so
    they must be resolved with 404 (team, beneficiary team, segment) or 409
    with the assist code (player), never with a foreign-key 500.
    """

    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="T7 foreign organization")
        match = await _create_closable_match(session, tenant)
        await session.commit()
    return match


def goal_report(
    match: AssistMatch,
    *,
    client_event_id: str | None = None,
    assist_player_id: UUID | None = None,
    minute: int = 30,
) -> CloseMatchReportDTO:
    """One home goal, optionally with an assist, closing 1-0."""

    return CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=1,
        away_score_regular=0,
        home_score=1,
        away_score=0,
        events=[
            MatchEventPayload(
                client_event_id=client_event_id or event_id("t6-goal"),
                event_type="goal",
                team_id=match.home_team_id,
                player_id=match.home_scorer_id,
                assist_player_id=assist_player_id,
                minute=minute,
                segment_id=match.segment_id,
            )
        ],
    )


def red_card_report(
    match: AssistMatch,
    *,
    red_card_type: str,
    client_event_id: str | None = None,
) -> CloseMatchReportDTO:
    """One red card, closing 0-0; the only type that declares ``metadata``."""

    return CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=0,
        away_score_regular=0,
        home_score=0,
        away_score=0,
        events=[
            MatchEventPayload(
                client_event_id=client_event_id or event_id("t6-red"),
                event_type="red_card",
                team_id=match.home_team_id,
                player_id=match.home_scorer_id,
                minute=30,
                segment_id=match.segment_id,
                metadata={"red_card_type": red_card_type},
            )
        ],
    )


def event_payload(
    match: AssistMatch,
    *,
    label: str,
    event_type: str = "goal",
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    assist_player_id: UUID | None = None,
    beneficiary_team_id: UUID | None = None,
    minute: int = 30,
    segment_id: UUID | None = None,
) -> MatchEventPayload:
    """One event of the request, with every identifier overridable (RF-014)."""

    return MatchEventPayload(
        client_event_id=event_id(label),
        event_type=event_type,
        team_id=team_id or match.home_team_id,
        player_id=player_id or match.home_scorer_id,
        assist_player_id=assist_player_id,
        beneficiary_team_id=beneficiary_team_id,
        minute=minute,
        segment_id=segment_id or match.segment_id,
    )


def report_of(
    *events: MatchEventPayload,
    home_score_regular: int = 1,
    away_score_regular: int = 0,
) -> CloseMatchReportDTO:
    """A regular report around the given events."""

    return CloseMatchReportDTO(
        resolution_type="regular",
        home_score_regular=home_score_regular,
        away_score_regular=away_score_regular,
        home_score=home_score_regular,
        away_score=away_score_regular,
        events=list(events),
    )


def goal_and_red_report(
    match: AssistMatch,
    *,
    assist_player_id: UUID | None = None,
    label: str = "t7-equivalent",
) -> CloseMatchReportDTO:
    """The act both worlds share: one home goal and one away direct red.

    The only difference between the two worlds of RF-010 is the assist of the
    goal; everything that can change a result, a point or a sanction is
    identical.
    """

    return report_of(
        event_payload(
            match,
            label=f"{label}-goal",
            assist_player_id=assist_player_id,
            minute=30,
        ),
        event_payload(
            match,
            label=f"{label}-red",
            event_type="red_card",
            team_id=match.away_team_id,
            player_id=match.away_scorer_id,
            minute=60,
        ),
    )


async def close(engine, context: AuthContext, match_id: UUID, dto: CloseMatchReportDTO):
    """Run the closing route in its own session, exactly as a request does."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await close_match(match_id, dto, context, session)


async def operation(engine, context: AuthContext, match_id: UUID) -> dict:
    """Run ``GET /matches/{id}/operation`` in its own read-only transaction."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await get_match_operation(match_id, context, session)


async def read_events(engine, match: AssistMatch) -> list[dict]:
    """Read the persisted act from an independent session."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        rows = (
            await session.execute(
                text("""
                    SELECT id, client_event_id, event_type, team_id, player_id,
                           assist_player_id, minute, added_minute, metadata
                    FROM match_events
                    WHERE organization_id = :organization_id
                      AND match_id = :match_id
                    ORDER BY minute, added_minute, id
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "match_id": str(match.match_id),
                },
            )
        ).mappings().all()
    return [dict(row) for row in rows]


async def read_match_state(engine, match: AssistMatch) -> dict:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        row = (
            await session.execute(
                text("""
                    SELECT status, home_score, away_score, result_confirmed,
                           home_score_regular, away_score_regular, winner_team_id
                    FROM matches
                    WHERE id = :match_id AND organization_id = :organization_id
                """),
                {
                    "match_id": str(match.match_id),
                    "organization_id": str(match.tenant.organization_id),
                },
            )
        ).mappings().one()
    return dict(row)


def team_role(match: AssistMatch, team_id: UUID | None) -> str | None:
    """Name the two participants by role so two worlds can be compared."""

    if team_id is None:
        return None
    if team_id == match.home_team_id:
        return "home"
    if team_id == match.away_team_id:
        return "away"
    return "other"


def result_summary(match: AssistMatch, state: dict) -> dict:
    """The result of one match with the winner named by role, not by id."""

    return {
        "status": state["status"],
        "result_confirmed": state["result_confirmed"],
        "home_score_regular": state["home_score_regular"],
        "away_score_regular": state["away_score_regular"],
        "home_score": state["home_score"],
        "away_score": state["away_score"],
        "winner": team_role(match, state["winner_team_id"]),
    }


STANDING_FIELDS = (
    "played",
    "won",
    "drawn",
    "lost",
    "goals_for",
    "goals_against",
    "goal_difference",
    "points",
    "fair_play_points",
    "rank",
)


async def read_standings(engine, match: AssistMatch) -> dict[str, dict]:
    """The standings of the stage, keyed by the role of each team."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        rows = (
            await session.execute(
                text("""
                    SELECT team_id, played, won, drawn, lost, goals_for,
                           goals_against, goal_difference, points,
                           fair_play_points, rank
                    FROM standings
                    WHERE organization_id = :organization_id
                      AND tournament_id = :tournament_id
                      AND stage_id = :stage_id
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "tournament_id": str(match.tournament_id),
                    "stage_id": str(match.stage_id),
                },
            )
        ).mappings().all()
    by_team = {row["team_id"]: row for row in rows}
    table = {}
    for role, team_id in (
        ("home", match.home_team_id),
        ("away", match.away_team_id),
    ):
        row = by_team.pop(team_id, None)
        table[role] = (
            None if row is None else {field: row[field] for field in STANDING_FIELDS}
        )
    assert not by_team, "la clasificación de la fase solo contiene a sus equipos"
    return table


async def read_suspensions(engine, match: AssistMatch) -> list[dict]:
    """The suspensions created by this match's act, with the player's role."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        rows = (
            await session.execute(
                text("""
                    SELECT ps.player_id, ps.reason, ps.matches_suspended,
                           ps.scope_type, ps.status, r.team_id
                    FROM player_suspensions ps
                    LEFT JOIN rosters r
                      ON r.player_id = ps.player_id
                     AND r.organization_id = ps.organization_id
                     AND r.tournament_id = :tournament_id
                    WHERE ps.organization_id = :organization_id
                      AND ps.origin_match_id = :match_id
                    ORDER BY ps.reason
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "tournament_id": str(match.tournament_id),
                    "match_id": str(match.match_id),
                },
            )
        ).mappings().all()
    return [
        {
            "player_id": row["player_id"],
            "role": team_role(match, row["team_id"]),
            "reason": row["reason"],
            "matches_suspended": row["matches_suspended"],
            "scope_type": row["scope_type"],
            "status": row["status"],
        }
        for row in rows
    ]


def suspension_signature(rows: list[dict]) -> list[dict]:
    """The suspensions without the player id, so two worlds are comparable."""

    return [
        {key: value for key, value in row.items() if key != "player_id"}
        for row in rows
    ]


async def read_outbox(engine, match: AssistMatch) -> list[dict]:
    """The outbox rows of this match, the only input of the socket relay."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        rows = (
            await session.execute(
                text("""
                    SELECT event_type, payload
                    FROM outbox_events
                    WHERE organization_id = :organization_id
                      AND payload ->> 'match_id' = :match_id
                    ORDER BY event_type
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "match_id": str(match.match_id),
                },
            )
        ).mappings().all()
    return [
        {
            "event_type": row["event_type"],
            "payload": (
                json.loads(row["payload"])
                if isinstance(row["payload"], str)
                else dict(row["payload"])
            ),
        }
        for row in rows
    ]


async def read_close_audit(engine, match: AssistMatch) -> dict:
    """The last audit entry the closing service wrote for this match.

    RNF-010: the close keeps registering its own audited action and the assist
    travels inside its content as an identifier, never as a name.
    """

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        row = (
            await session.execute(
                text("""
                    SELECT action, payload
                    FROM administrative_audit_logs
                    WHERE organization_id = :organization_id
                      AND entity_type = 'matches'
                      AND entity_id = :match_id
                    ORDER BY performed_at DESC, id DESC
                    LIMIT 1
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "match_id": str(match.match_id),
                },
            )
        ).mappings().one()
    payload = row["payload"]
    return {
        "action": row["action"],
        "payload": json.loads(payload) if isinstance(payload, str) else dict(payload),
    }


async def read_player_name(
    engine, match: AssistMatch, player_id: UUID
) -> tuple[str, str]:
    """The two text columns of a player, the personal data that must not leak."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        row = (
            await session.execute(
                text("""
                    SELECT first_name, last_name
                    FROM players
                    WHERE id = :player_id AND organization_id = :organization_id
                """),
                {
                    "player_id": str(player_id),
                    "organization_id": str(match.tenant.organization_id),
                },
            )
        ).mappings().one()
    return row["first_name"], row["last_name"]


async def seed_event(
    engine,
    match: AssistMatch,
    *,
    client_event_id: str,
    event_type: str = "goal",
    player_id: UUID | None = None,
    assist_player_id: UUID | None = None,
    metadata: dict | None = None,
    minute: int = 30,
) -> UUID:
    """Insert one act row directly, as an act written before this spec would be.

    ``match_events.metadata`` is ``NOT NULL DEFAULT '{}'``, so an omitted value
    is stored as the empty object, exactly what the closing service writes.
    """

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        event_id_value = (
            await session.execute(
                text("""
                    INSERT INTO match_events
                        (organization_id, match_id, segment_id, team_id, player_id,
                         assist_player_id, event_type, minute, added_minute,
                         client_event_id, metadata)
                    VALUES
                        (:organization_id, :match_id, :segment_id, :team_id, :player_id,
                         :assist_player_id, :event_type, :minute, 0,
                         :client_event_id, CAST(:metadata AS jsonb))
                    RETURNING id
                """),
                {
                    "organization_id": str(match.tenant.organization_id),
                    "match_id": str(match.match_id),
                    "segment_id": str(match.segment_id),
                    "team_id": str(match.home_team_id),
                    "player_id": str(player_id or match.home_scorer_id),
                    "assist_player_id": (
                        str(assist_player_id) if assist_player_id else None
                    ),
                    "event_type": event_type,
                    "minute": minute,
                    "client_event_id": client_event_id,
                    "metadata": json.dumps(metadata or {}),
                },
            )
        ).scalar_one()
        await session.commit()
    return event_id_value


# ---------------------------------------------------------------------------
# Persistence and operation response (RF-007, RF-011)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closing_with_an_assist_persists_the_column(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        # El cliente envía el UUID en mayúsculas: la escritura es canónica.
        request_id = event_id("t6-goal-persisted").upper()

        outcome = await close(
            engine,
            context,
            match.match_id,
            goal_report(
                match,
                client_event_id=request_id,
                assist_player_id=match.home_assist_id,
            ),
        )

        assert outcome["status"] == "success"
        assert outcome["home_score"] == 1
        events = await read_events(engine, match)
        assert len(events) == 1
        assert events[0]["event_type"] == "goal"
        assert events[0]["player_id"] == match.home_scorer_id
        assert events[0]["assist_player_id"] == match.home_assist_id
        # El identificador se guarda en su forma canónica (minúsculas de RFC
        # 4122), no como llegó.
        assert events[0]["client_event_id"] == request_id.lower()


@pytest.mark.asyncio
async def test_the_close_audit_keeps_the_assist_uuid_without_names(
    database_admin_url,
):
    """RNF-010: the audited close stores the assist as an identifier, never names.

    The audit payload carries the closing request, so the assist reaches the
    trail as the same UUID the act stores. No name, document or birth date of
    the player travels with it.
    """

    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        await close(
            engine,
            context,
            match.match_id,
            goal_report(match, assist_player_id=match.home_assist_id),
        )

        audit = await read_close_audit(engine, match)
        assert audit["action"] == "CLOSE_MATCH_REPORT"
        events = audit["payload"]["request"]["events"]
        assert len(events) == 1
        assert events[0]["assist_player_id"] == str(match.home_assist_id)
        # El identificador viaja, el nombre no: ni la clave ni el valor de los
        # campos personales del jugador están en la entrada. El apellido sembrado
        # es un prefijo hexadecimal del id del equipo y puede coincidir con una
        # parte del UUID, así que el valor se comprueba como nombre completo.
        first_name, last_name = await read_player_name(
            engine, match, match.home_assist_id
        )
        serialised = json.dumps(audit["payload"], default=str)
        assert f"{first_name} {last_name}" not in serialised
        assert first_name not in serialised
        for forbidden in (
            "first_name",
            "last_name",
            "full_name",
            "national_id",
            "birth_date",
        ):
            assert forbidden not in serialised


@pytest.mark.asyncio
async def test_the_operation_returns_the_assist_as_a_uuid_without_names(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        await close(
            engine,
            context,
            match.match_id,
            goal_report(match, assist_player_id=match.home_assist_id),
        )

        response = await operation(engine, context, match.match_id)

        goal = next(
            event for event in response["events"] if event["event_type"] == "goal"
        )
        assert goal["assist_player_id"] == match.home_assist_id
        assert isinstance(goal["assist_player_id"], UUID)
        # D-6: el asistente viaja como identificador, sin nombre ni apellidos.
        assert [key for key in goal if "assist" in key] == ["assist_player_id"]
        assert goal["first_name"] is not None and goal["last_name"] is not None
        # Solo se añade la clave nueva: la forma existente no cambia.
        assert set(goal) == {
            "id",
            "client_event_id",
            "event_type",
            "team_id",
            "team_name",
            "beneficiary_team_id",
            "player_id",
            "player_out_id",
            "player_in_id",
            "first_name",
            "last_name",
            "minute",
            "added_minute",
            "segment_id",
            "metadata",
            "is_voided",
            "created_at",
            "assist_player_id",
        }


@pytest.mark.asyncio
async def test_an_act_without_an_assist_still_closes_and_reads(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)

        await close(engine, context, match.match_id, goal_report(match))
        response = await operation(engine, context, match.match_id)

        events = await read_events(engine, match)
        assert [event["assist_player_id"] for event in events] == [None]
        goal = next(
            event for event in response["events"] if event["event_type"] == "goal"
        )
        # Un gol sin asistencia es válido y la operación lo devuelve nulo.
        assert goal["assist_player_id"] is None
        assert (await read_match_state(engine, match))["status"] == "finished"


@pytest.mark.asyncio
async def test_a_historical_event_without_assist_is_read_without_revalidation(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        # Acta escrita antes de esta spec: sin asistencia, con un identificador
        # que hoy no es un UUID y con una clave de `metadata` que hoy no se
        # declara. Al leerla no se revalida nada (RF-013).
        await seed_event(
            engine,
            match,
            client_event_id="legacy-goal-1",
            metadata={"legacy_key": "value"},
        )

        response = await operation(engine, context, match.match_id)

        goal = next(
            event for event in response["events"] if event["event_type"] == "goal"
        )
        assert goal["assist_player_id"] is None
        assert goal["client_event_id"] == "legacy-goal-1"
        assert goal["metadata"] == {"legacy_key": "value"}


# ---------------------------------------------------------------------------
# Idempotency: `metadata` normalised and the assist (RF-012, D-10)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_identical_retry_reuses_the_persisted_event(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        request_id = event_id("t6-retry-identical")
        # La fila guardada tiene la `metadata` vacía y el reintento la omite:
        # son la misma información adicional (D-10).
        seeded_id = await seed_event(engine, match, client_event_id=request_id)

        outcome = await close(
            engine,
            context,
            match.match_id,
            goal_report(match, client_event_id=request_id),
        )

        events = await read_events(engine, match)
        assert outcome["home_score"] == 1
        assert len(events) == 1
        assert events[0]["id"] == seeded_id
        assert events[0]["metadata"] == {}
        assert (await read_match_state(engine, match))["status"] == "finished"


@pytest.mark.asyncio
async def test_a_retry_with_the_same_metadata_is_reused(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        request_id = event_id("t6-retry-same-metadata")
        seeded_id = await seed_event(
            engine,
            match,
            client_event_id=request_id,
            event_type="red_card",
            metadata={"red_card_type": "direct_red"},
        )

        await close(
            engine,
            context,
            match.match_id,
            red_card_report(
                match,
                client_event_id=request_id,
                red_card_type="direct_red",
            ),
        )

        events = await read_events(engine, match)
        assert len(events) == 1
        assert events[0]["id"] == seeded_id
        assert events[0]["metadata"] == {"red_card_type": "direct_red"}


@pytest.mark.asyncio
async def test_a_retry_with_a_different_metadata_is_immutable(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        request_id = event_id("t6-retry-metadata")
        # La fila guardada es una roja histórica marcada como doble amarilla; el
        # reintento la cambia a roja directa. El sentido de la prueba es la
        # diferencia de `metadata`, y la roja **directa** es la que no exige
        # amarillas previas (RF-006 de la 017): así el defecto que se informa
        # sigue siendo el de idempotencia y no el disciplinario del paso 10.
        await seed_event(
            engine,
            match,
            client_event_id=request_id,
            event_type="red_card",
            metadata={"red_card_type": "double_yellow_red"},
        )

        with pytest.raises(HTTPException) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                red_card_report(
                    match,
                    client_event_id=request_id,
                    red_card_type="direct_red",
                ),
            )

        assert rejected.value.status_code == 409
        assert "inmutable" in rejected.value.detail
        events = await read_events(engine, match)
        assert len(events) == 1
        assert events[0]["metadata"] == {"red_card_type": "double_yellow_red"}
        assert (await read_match_state(engine, match))["status"] == "scheduled"


@pytest.mark.asyncio
async def test_a_retry_with_a_different_assist_is_immutable(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        request_id = event_id("t6-retry-assist")
        await seed_event(engine, match, client_event_id=request_id)

        with pytest.raises(HTTPException) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                goal_report(
                    match,
                    client_event_id=request_id,
                    assist_player_id=match.home_assist_id,
                ),
            )

        assert rejected.value.status_code == 409
        assert "inmutable" in rejected.value.detail
        events = await read_events(engine, match)
        assert len(events) == 1
        assert events[0]["assist_player_id"] is None
        assert (await read_match_state(engine, match))["status"] == "scheduled"


@pytest.mark.asyncio
async def test_a_retry_with_a_different_case_is_the_same_event(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        request_id = event_id("t6-retry-case")
        # La fila guardada está en la forma canónica (minúsculas); el reintento
        # llega en mayúsculas. La comparación y la escritura normalizan, así que
        # es el mismo evento y no se duplica la fila.
        seeded_id = await seed_event(engine, match, client_event_id=request_id)

        await close(
            engine,
            context,
            match.match_id,
            goal_report(match, client_event_id=request_id.upper()),
        )

        events = await read_events(engine, match)
        assert len(events) == 1
        assert events[0]["id"] == seeded_id
        assert events[0]["client_event_id"] == request_id


# ---------------------------------------------------------------------------
# The assist changes nothing: result, standings, sanctions and outbox (RF-010)
# ---------------------------------------------------------------------------


def _request() -> Request:
    """A minimal request for the registered coded handler."""

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/matches/00000000-0000-4000-8000-000000000001/close",
            "headers": [],
            "query_string": b"",
        }
    )


async def assert_coded_409(error: AssistPlayerInvalid) -> None:
    """The assist 409 keeps a string ``detail`` and the additive ``code``.

    The body is built by the single handler registered in ``app/main.py`` (D-8),
    so the assertion covers both what the service raises and what the client
    reads.
    """

    from app import main as main_module

    assert error.status_code == 409
    assert error.code == ASSIST_PLAYER_INVALID
    assert isinstance(error.detail, str) and error.detail
    handler = main_module.api.exception_handlers[AssistPlayerInvalid]
    response = await handler(_request(), error)
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["code"] == ASSIST_PLAYER_INVALID
    assert isinstance(body["detail"], str) and body["detail"]


async def assert_nothing_was_written(engine, match: AssistMatch) -> None:
    assert await read_events(engine, match) == []
    state = await read_match_state(engine, match)
    assert state["status"] == "scheduled"
    assert state["result_confirmed"] is False


@pytest.mark.asyncio
async def test_the_assist_never_changes_result_standings_sanctions_or_outbox(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, (with_assist, without_assist) = await seeded_matches(engine, 2)

        await close(
            engine,
            context,
            with_assist.match_id,
            goal_and_red_report(
                with_assist,
                assist_player_id=with_assist.home_assist_id,
            ),
        )
        await close(
            engine,
            context,
            without_assist.match_id,
            goal_and_red_report(without_assist),
        )

        # Precondición: las dos actas solo difieren en la asistencia.
        assisted_events = await read_events(engine, with_assist)
        plain_events = await read_events(engine, without_assist)
        assert [
            event["assist_player_id"]
            for event in assisted_events
            if event["event_type"] == "goal"
        ] == [with_assist.home_assist_id]
        assert [
            event["assist_player_id"]
            for event in plain_events
            if event["event_type"] == "goal"
        ] == [None]

        # El marcador reglamentario, el final y el ganador no cambian.
        assisted_result = result_summary(
            with_assist, await read_match_state(engine, with_assist)
        )
        plain_result = result_summary(
            without_assist, await read_match_state(engine, without_assist)
        )
        assert assisted_result == plain_result
        assert assisted_result == {
            "status": "finished",
            "result_confirmed": True,
            "home_score_regular": 1,
            "away_score_regular": 0,
            "home_score": 1,
            "away_score": 0,
            "winner": "home",
        }

        # La clasificación (puntos, goles, fair play y orden) es la misma. Se
        # fija además el valor concreto: el fair play solo descuenta la roja.
        assisted_standings = await read_standings(engine, with_assist)
        plain_standings = await read_standings(engine, without_assist)
        assert assisted_standings == plain_standings
        assert assisted_standings["home"] == {
            "played": 1,
            "won": 1,
            "drawn": 0,
            "lost": 0,
            "goals_for": 1,
            "goals_against": 0,
            "goal_difference": 1,
            "points": 3,
            "fair_play_points": 0,
            "rank": 1,
        }
        assert assisted_standings["away"] == {
            "played": 1,
            "won": 0,
            "drawn": 0,
            "lost": 1,
            "goals_for": 0,
            "goals_against": 1,
            "goal_difference": -1,
            "points": 0,
            "fair_play_points": -3,
            "rank": 2,
        }

        # Las sanciones son las mismas: solo la roja directa del rival.
        assisted_suspensions = await read_suspensions(engine, with_assist)
        plain_suspensions = await read_suspensions(engine, without_assist)
        assert suspension_signature(assisted_suspensions) == suspension_signature(
            plain_suspensions
        )
        assert suspension_signature(assisted_suspensions) == [
            {
                "role": "away",
                "reason": "direct_red_card",
                "matches_suspended": 1,
                "scope_type": "organization",
                "status": "active",
            }
        ]
        # El asistente no aparece en ninguna sanción ni suma fair play.
        suspended_players = {row["player_id"] for row in assisted_suspensions}
        assert with_assist.home_assist_id not in suspended_players
        assert with_assist.home_scorer_id not in suspended_players

        # El outbox es la única entrada del relay de Socket.IO: si sus filas y
        # su carga son las mismas, la notificación en tiempo real también lo es.
        # La carga solo lleva identificadores, así que la asistencia no puede
        # llegar al flujo.
        assisted_outbox = await read_outbox(engine, with_assist)
        plain_outbox = await read_outbox(engine, without_assist)
        expected_types = ["MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED"]
        assert [row["event_type"] for row in assisted_outbox] == expected_types
        assert [row["event_type"] for row in plain_outbox] == expected_types
        for row in [*assisted_outbox, *plain_outbox]:
            assert set(row["payload"]) == {"match_id", "tournament_id"}
        expected_payload = {
            "match_id": str(with_assist.match_id),
            "tournament_id": str(with_assist.tournament_id),
        }
        assert [row["payload"] for row in assisted_outbox] == [
            expected_payload for _ in expected_types
        ]
        assert "assist" not in json.dumps(
            [row["payload"] for row in assisted_outbox]
        ).lower()


# ---------------------------------------------------------------------------
# Historical acts stay valid and are never rewritten (RF-013)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_legacy_goal_without_assist_is_read_and_updated_legitimately(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        # Acta escrita antes de la 026: sin asistencia, con una clave de
        # `metadata` que hoy no se declara y con un identificador que hoy no es
        # un UUID. Leerla no la revalida (RF-013).
        legacy_id = await seed_event(
            engine,
            match,
            client_event_id="legacy-goal-1",
            metadata={"legacy_key": "value"},
        )

        response = await operation(engine, context, match.match_id)
        goal = next(
            event for event in response["events"] if event["event_type"] == "goal"
        )
        assert goal["id"] == legacy_id
        assert goal["assist_player_id"] is None
        assert goal["client_event_id"] == "legacy-goal-1"
        assert goal["metadata"] == {"legacy_key": "value"}

        # El CHECK de la 026 no bloquea una actualización legítima: la fila
        # sigue sin asistencia y no se revalida su información adicional.
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await set_tenant_context(session, match.tenant)
            await session.execute(
                text("""
                    UPDATE match_events
                    SET minute = 45
                    WHERE id = :event_id AND organization_id = :organization_id
                """),
                {
                    "event_id": str(legacy_id),
                    "organization_id": str(match.tenant.organization_id),
                },
            )
            await session.commit()

        events = await read_events(engine, match)
        assert len(events) == 1
        assert events[0]["id"] == legacy_id
        assert events[0]["minute"] == 45
        assert events[0]["assist_player_id"] is None
        assert events[0]["metadata"] == {"legacy_key": "value"}
        assert events[0]["client_event_id"] == "legacy-goal-1"


@pytest.mark.asyncio
async def test_closing_beside_legacy_events_never_raises_the_assist_error(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        # Una tarjeta histórica, con un `client_event_id` que hoy no es un UUID
        # y una clave de `metadata` que hoy no se declara.
        legacy_id = await seed_event(
            engine,
            match,
            client_event_id="legacy-yellow-1",
            event_type="yellow_card",
            metadata={"legacy_key": "value"},
            minute=20,
        )

        # Cerrar junto a ella no la revalida: ni el catálogo cerrado ni el
        # `CHECK` de la 026 impiden cerrar el acta, y ASSIST_PLAYER_INVALID no
        # se dispara por un evento histórico (RF-013).
        outcome = await close(
            engine,
            context,
            match.match_id,
            goal_report(
                match,
                assist_player_id=match.home_assist_id,
                minute=30,
            ),
        )

        assert outcome["status"] == "success"
        assert outcome["home_score"] == 1
        events = await read_events(engine, match)
        assert len(events) == 2
        legacy = next(event for event in events if event["id"] == legacy_id)
        assert legacy["event_type"] == "yellow_card"
        assert legacy["client_event_id"] == "legacy-yellow-1"
        assert legacy["metadata"] == {"legacy_key": "value"}
        assert legacy["assist_player_id"] is None
        assert legacy["minute"] == 20
        goal = next(event for event in events if event["event_type"] == "goal")
        assert goal["assist_player_id"] == match.home_assist_id

        response = await operation(engine, context, match.match_id)
        assert len(response["events"]) == 2
        assert (await read_match_state(engine, match))["status"] == "finished"


# ---------------------------------------------------------------------------
# The identifier rule of T5 against PostgreSQL (RF-014)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_assist_from_another_organization_is_a_coded_409(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        foreign = await seed_foreign_match(engine)

        with pytest.raises(AssistPlayerInvalid) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                goal_report(match, assist_player_id=foreign.home_assist_id),
            )

        await assert_coded_409(rejected.value)
        await assert_nothing_was_written(engine, match)


@pytest.mark.asyncio
async def test_an_assist_outside_the_match_roster_is_a_coded_409(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, (match, other_match) = await seeded_matches(engine, 2)

        # El jugador existe en la organización, pero en la plantilla de **otro**
        # partido: fuera de la plantilla de este partido.
        with pytest.raises(AssistPlayerInvalid) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                goal_report(match, assist_player_id=other_match.home_assist_id),
            )

        await assert_coded_409(rejected.value)
        await assert_nothing_was_written(engine, match)


@pytest.mark.asyncio
async def test_a_segment_from_another_match_is_404(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, (match, other_match) = await seeded_matches(engine, 2)

        with pytest.raises(HTTPException) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                report_of(
                    event_payload(
                        match,
                        label="t7-segment-other-match",
                        segment_id=other_match.segment_id,
                    )
                ),
            )

        assert rejected.value.status_code == 404
        assert isinstance(rejected.value.detail, str) and rejected.value.detail
        await assert_nothing_was_written(engine, match)


@pytest.mark.asyncio
async def test_a_segment_from_another_organization_is_404(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        foreign = await seed_foreign_match(engine)

        with pytest.raises(HTTPException) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                report_of(
                    event_payload(
                        match,
                        label="t7-segment-foreign-org",
                        segment_id=foreign.segment_id,
                    )
                ),
            )

        assert rejected.value.status_code == 404
        await assert_nothing_was_written(engine, match)


@pytest.mark.asyncio
async def test_a_team_from_another_organization_is_404(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        foreign = await seed_foreign_match(engine)

        with pytest.raises(HTTPException) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                report_of(
                    event_payload(
                        match,
                        label="t7-team-foreign-org",
                        team_id=foreign.home_team_id,
                    )
                ),
            )

        assert rejected.value.status_code == 404
        await assert_nothing_was_written(engine, match)


@pytest.mark.asyncio
async def test_a_beneficiary_team_from_another_organization_is_404(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        foreign = await seed_foreign_match(engine)

        with pytest.raises(HTTPException) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                report_of(
                    event_payload(
                        match,
                        label="t7-beneficiary-foreign-org",
                        event_type="own_goal",
                        beneficiary_team_id=foreign.home_team_id,
                    ),
                    home_score_regular=0,
                    away_score_regular=0,
                ),
            )

        assert rejected.value.status_code == 404
        await assert_nothing_was_written(engine, match)


@pytest.mark.asyncio
async def test_a_scorer_from_another_organization_is_409_not_404(database_admin_url):
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)
        foreign = await seed_foreign_match(engine)

        # RF-014: el goleador de otra organización conserva el 409 de
        # pertenencia (sin `code`), nunca un 404 ni un 500 de clave foránea.
        with pytest.raises(HTTPException) as rejected:
            await close(
                engine,
                context,
                match.match_id,
                report_of(
                    event_payload(
                        match,
                        label="t7-scorer-foreign-org",
                        player_id=foreign.home_scorer_id,
                    )
                ),
            )

        assert rejected.value.status_code == 409
        assert not isinstance(rejected.value, AssistPlayerInvalid)
        assert isinstance(rejected.value.detail, str) and rejected.value.detail
        await assert_nothing_was_written(engine, match)
