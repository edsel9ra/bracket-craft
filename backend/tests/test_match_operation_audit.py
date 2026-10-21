"""Coverage for the operation read without locking and the audit entries (T14).

R23 (RF-006): the match operation query is a consistent read that does not lock
the match row, so it never serialises with a close or with any other write.
R25 (RF-008): saving the lineup, publishing the formation and assigning or
removing an official leave exactly one organisational audit entry per effective
state change, inside the same transaction as the action.

The pure helpers and the query shape run without a database. The opt-in suite
(``RUN_DATABASE_TESTS=1``) exercises the real routes: the bulk runs inside the
``db_session`` fixture (application role, rolled back); the lock, the
``updated_at`` and the "reverted transaction" cases use a dedicated engine.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import set_rls_context
from app.core.tenancy import AuthContext
from app.modules.matches.audit import (
    lineup_audit_action,
    lineup_content_summary,
    lineup_signature,
    publication_audit_action,
)
from app.modules.matches.formations import FORMATION_SLOTS
from app.modules.matches.router import (
    _load_operation_match,
    assign_match_official,
    get_match_operation,
    list_match_officials,
    publish_match_lineup,
    remove_match_official,
    save_match_lineup,
)
from app.modules.matches.schemas import (
    MatchLineupEntry,
    MatchTeamLineupConfig,
    OfficialAssignmentRequest,
    PublishMatchLineupRequest,
    SaveMatchLineupRequest,
)
from db_helpers import (
    TenantContext,
    application_database_url,
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

MATCH_ID = UUID("11111111-1111-4111-8111-111111111111")
TEAM_A = UUID("22222222-2222-4222-8222-222222222222")
TEAM_B = UUID("33333333-3333-4333-8333-333333333333")
PLAYER_A = UUID("44444444-4444-4444-8444-444444444444")
PLAYER_B = UUID("55555555-5555-4555-8555-555555555555")

FORMATION_CODE = "4-4-2"


def context_for(tenant: TenantContext) -> AuthContext:
    return AuthContext(
        user_id=tenant.user_id,
        organization_id=tenant.organization_id,
        organization_user_id=tenant.member_id,
    )


# ---------------------------------------------------------------------------
# Unit: the query shape and the pure audit helpers
# ---------------------------------------------------------------------------


class _FakeMappings:
    def __init__(self, row: dict | None):
        self._row = row

    def one_or_none(self) -> dict | None:
        return self._row


class _RecordingResult:
    def __init__(self, row: dict | None):
        self._row = row

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._row)


class _RecordingSession:
    """Stand-in for ``AsyncSession`` that records the SQL text it receives."""

    def __init__(self, row: dict | None = None):
        self.statements: list[str] = []
        self._row = {"id": MATCH_ID} if row is None else row

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _RecordingResult(self._row)


def _context() -> AuthContext:
    return AuthContext(
        user_id=UUID("66666666-6666-4666-8666-666666666666"),
        organization_id=UUID("77777777-7777-4777-8777-777777777777"),
        organization_user_id=UUID("88888888-8888-4888-8888-888888888888"),
    )


@pytest.mark.asyncio
async def test_operation_read_does_not_lock_the_match_when_lock_is_disabled():
    session = _RecordingSession()

    match = await _load_operation_match(
        session,
        _context(),
        MATCH_ID,
        require_operation_permission=False,
        lock=False,
    )

    assert match["id"] == MATCH_ID
    assert len(session.statements) == 1
    assert "FOR UPDATE" not in session.statements[0].upper()


@pytest.mark.asyncio
async def test_operation_read_keeps_the_match_lock_by_default():
    session = _RecordingSession()

    await _load_operation_match(
        session,
        _context(),
        MATCH_ID,
        require_operation_permission=False,
    )

    assert "FOR UPDATE OF m" in session.statements[0]


def test_lineup_signature_ignores_the_order_of_the_entries():
    formations = [(TEAM_A, FORMATION_CODE)]
    entries = [
        (TEAM_A, PLAYER_A, PLAYER_A, "starter", "GK", None, None),
        (TEAM_A, PLAYER_B, PLAYER_B, "substitute", None, None, None),
    ]

    assert lineup_signature(formations, entries) == lineup_signature(
        list(reversed(formations)), list(reversed(entries))
    )


def test_lineup_signature_changes_with_role_position_formation_or_membership():
    formations = [(TEAM_A, FORMATION_CODE)]
    base = [
        (TEAM_A, PLAYER_A, PLAYER_A, "starter", "GK", None, None),
        (TEAM_A, PLAYER_B, PLAYER_B, "substitute", None, None, None),
    ]

    baseline = lineup_signature(formations, base)
    assert baseline != lineup_signature(formations, [base[0], base[1][:3] + ("starter",) + base[1][4:]])
    assert baseline != lineup_signature(formations, [(TEAM_A, PLAYER_A, PLAYER_A, "starter", "RB", None, None), base[1]])
    assert baseline != lineup_signature([(TEAM_A, "4-3-3")], base)
    assert baseline != lineup_signature(formations, base[:1])
    assert baseline == lineup_signature(formations, base)


def test_lineup_audit_action_only_fires_when_the_content_changes():
    empty = lineup_signature([], [])
    filled = lineup_signature([(TEAM_A, FORMATION_CODE)], [(TEAM_A, PLAYER_A, PLAYER_A, "starter", "GK", None, None)])

    assert lineup_audit_action(empty, filled) == "SAVE_MATCH_LINEUP"
    assert lineup_audit_action(filled, empty) == "SAVE_MATCH_LINEUP"
    assert lineup_audit_action(filled, filled) is None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (False, True, "PUBLISH_MATCH_LINEUP"),
        (True, False, "UNPUBLISH_MATCH_LINEUP"),
        (True, True, None),
        (False, False, None),
    ],
)
def test_publication_audit_only_records_the_state_transition(before, after, expected):
    assert publication_audit_action(before, after) == expected


def test_lineup_audit_payload_keeps_codes_and_counts_only():
    formations = [(TEAM_A, FORMATION_CODE), (TEAM_B, "4-3-3")]
    entries = [
        (TEAM_A, PLAYER_A, PLAYER_A, "starter", "GK", None, None),
        (TEAM_A, PLAYER_B, PLAYER_B, "substitute", None, None, None),
    ]

    summary = lineup_content_summary(formations, entries)

    assert set(summary) == {
        "teams",
        "formations",
        "entries",
        "starters",
        "substitutes",
        "content_digest",
    }
    assert summary["teams"] == 2
    assert summary["formations"] == {str(TEAM_A): FORMATION_CODE, str(TEAM_B): "4-3-3"}
    assert (summary["entries"], summary["starters"], summary["substitutes"]) == (2, 1, 1)
    assert summary["content_digest"] == sha256(
        lineup_signature(formations, entries).encode("utf-8")
    ).hexdigest()
    serialized = json.dumps(summary)
    assert str(PLAYER_A) not in serialized
    assert str(PLAYER_B) not in serialized


# ---------------------------------------------------------------------------
# Opt-in: fixture helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperationMatch:
    tenant: TenantContext
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    match_id: UUID
    segment_id: UUID
    completed_segment_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    home_starters: tuple[UUID, ...]
    away_starters: tuple[UUID, ...]
    home_substitutes: tuple[UUID, ...]
    away_substitutes: tuple[UUID, ...]


async def _insert_team(session, tenant: TenantContext, label: str) -> UUID:
    team_id = (
        await session.execute(
            text("""
                INSERT INTO teams (organization_id, name, short_code)
                VALUES (:organization_id, :name, :short_code)
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T14 {label} {uuid4().hex[:6]}",
                "short_code": f"T{uuid4().hex[:5].upper()}",
            },
        )
    ).scalar_one()
    return team_id


async def _insert_roster(
    session,
    tenant: TenantContext,
    *,
    tournament_id: UUID,
    team_id: UUID,
    dorsal_number: int,
    label: str,
) -> UUID:
    player_id = await insert_player(
        session,
        tenant.organization_id,
        first_name=f"T14{label}{dorsal_number}",
        last_name=team_id.hex[:4],
        reference_year=2026,
    )
    return (
        await session.execute(
            text("""
                INSERT INTO rosters
                    (organization_id, tournament_id, team_id, player_id, dorsal_number,
                     photo_consent, valid_from, eligible_from)
                VALUES
                    (:organization_id, :tournament_id, :team_id, :player_id, :dorsal_number,
                     FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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


async def _create_operation_match(session, tenant: TenantContext) -> OperationMatch:
    """Create a scheduled match with an active second segment and two rosters."""

    await set_tenant_context(session, tenant)
    suffix = uuid4().hex[:8]
    tournament_id = (
        await session.execute(
            text("""
                INSERT INTO tournaments (organization_id, name, season, start_date, status)
                VALUES (:organization_id, :name, '2026', '2026-01-01', 'draft')
                RETURNING id
            """),
            {
                "organization_id": str(tenant.organization_id),
                "name": f"T14 Cup {suffix}",
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
                    (:organization_id, :tournament_id, :version_id, 'T14 stage',
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

    team_ids = []
    for label in ("home", "away"):
        team_id = await _insert_team(session, tenant, label)
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
        team_ids.append(team_id)
    home_team_id, away_team_id = team_ids

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
    completed_segment_id = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, minute_end, status)
                VALUES (:organization_id, :match_id, 1, 0, 45, 'completed')
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "match_id": str(match_id)},
        )
    ).scalar_one()
    segment_id = (
        await session.execute(
            text("""
                INSERT INTO match_segments
                    (organization_id, match_id, segment_number, minute_start, status)
                VALUES (:organization_id, :match_id, 2, 45, 'active')
                RETURNING id
            """),
            {"organization_id": str(tenant.organization_id), "match_id": str(match_id)},
        )
    ).scalar_one()

    rosters: dict[str, tuple[list[UUID], list[UUID]]] = {}
    for label, team_id in (("home", home_team_id), ("away", away_team_id)):
        starters: list[UUID] = []
        substitutes: list[UUID] = []
        for index in range(1, 12):
            starters.append(
                await _insert_roster(
                    session,
                    tenant,
                    tournament_id=tournament_id,
                    team_id=team_id,
                    dorsal_number=index,
                    label=label,
                )
            )
        for index in range(12, 15):
            substitutes.append(
                await _insert_roster(
                    session,
                    tenant,
                    tournament_id=tournament_id,
                    team_id=team_id,
                    dorsal_number=index,
                    label=label,
                )
            )
        rosters[label] = (starters, substitutes)

    return OperationMatch(
        tenant=tenant,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        match_id=match_id,
        segment_id=segment_id,
        completed_segment_id=completed_segment_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_starters=tuple(rosters["home"][0]),
        away_starters=tuple(rosters["away"][0]),
        home_substitutes=tuple(rosters["home"][1]),
        away_substitutes=tuple(rosters["away"][1]),
    )


def _lineup_payload(match: OperationMatch, *, swapped: bool = False) -> SaveMatchLineupRequest:
    home_slots = list(FORMATION_SLOTS[FORMATION_CODE])
    if swapped:
        home_slots[0], home_slots[-1] = home_slots[-1], home_slots[0]
    entries = [
        MatchLineupEntry(roster_id=roster_id, role="starter", position_slot=slot)
        for roster_id, slot in zip(match.home_starters, home_slots)
    ]
    entries += [
        MatchLineupEntry(roster_id=roster_id, role="starter", position_slot=slot)
        for roster_id, slot in zip(match.away_starters, FORMATION_SLOTS[FORMATION_CODE])
    ]
    entries += [
        MatchLineupEntry(roster_id=roster_id, role="substitute")
        for roster_id in (*match.home_substitutes, *match.away_substitutes)
    ]
    return SaveMatchLineupRequest(
        segment_id=match.segment_id,
        entries=entries,
        team_lineups=[
            MatchTeamLineupConfig(team_id=match.home_team_id, formation_code=FORMATION_CODE),
            MatchTeamLineupConfig(team_id=match.away_team_id, formation_code=FORMATION_CODE),
        ],
    )


async def _audit_rows(session, match_id: UUID) -> list[dict]:
    rows = (
        await session.execute(
            text("""
                SELECT action, entity_type, entity_id, payload, performed_by_member_id,
                       organization_id
                FROM administrative_audit_logs
                WHERE entity_type = 'matches' AND entity_id = :match_id
                ORDER BY performed_at, ctid
            """),
            {"match_id": str(match_id)},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def _audit_rows_with_engine(engine, tenant: TenantContext, match_id: UUID) -> list[dict]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_rls_context(session, tenant.organization_id, tenant.user_id)
        return await _audit_rows(session, match_id)


class _NestedSession:
    """Run a route that opens its own transaction as a savepoint of the test.

    This mirrors the fixtures of the invitation suite: the route keeps its
    ``async with db.begin()`` contract, the statements land in the test
    transaction and the fixture rollback removes everything. The SQL text is
    recorded so a read can be proved not to write.
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self.statements: list[str] = []

    def begin(self):
        return self._session.begin_nested()

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return await self._session.execute(statement, params)


def _write_statements(statements: list[str]) -> list[str]:
    return [
        sql
        for sql in statements
        if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]


# ---------------------------------------------------------------------------
# Opt-in: reads do not write, do not lock and do not audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reads_do_not_write_lock_or_audit(db_session, tenant_factory):
    tenant = await tenant_factory("T14 reads")
    match = await _create_operation_match(db_session, tenant)
    await db_session.commit()

    api = _NestedSession(db_session)
    response = await get_match_operation(match.match_id, context_for(tenant), api)
    await list_match_officials(match.match_id, context_for(tenant), api)

    assert str(response["match"]["id"]) == str(match.match_id)
    assert _write_statements(api.statements) == []
    assert all("FOR UPDATE" not in sql.upper() for sql in api.statements)
    assert await _audit_rows(db_session, match.match_id) == []


# ---------------------------------------------------------------------------
# Opt-in: saving the lineup audits one entry per effective change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saving_the_lineup_audits_only_effective_changes(db_session, tenant_factory):
    tenant = await tenant_factory("T14 lineup")
    match = await _create_operation_match(db_session, tenant)
    payload = _lineup_payload(match)
    api = _NestedSession(db_session)

    await save_match_lineup(match.match_id, payload, context_for(tenant), api)
    entries = await _audit_rows(db_session, match.match_id)
    assert [entry["action"] for entry in entries] == ["SAVE_MATCH_LINEUP"]
    assert entries[0]["entity_type"] == "matches"
    assert str(entries[0]["performed_by_member_id"]) == str(tenant.member_id)
    assert str(entries[0]["organization_id"]) == str(tenant.organization_id)
    assert str(entries[0]["payload"]["segment_id"]) == str(match.segment_id)
    assert entries[0]["payload"]["entries"] == 28
    assert entries[0]["payload"]["formations"][str(match.home_team_id)] == FORMATION_CODE

    await save_match_lineup(match.match_id, payload, context_for(tenant), api)
    assert len(await _audit_rows(db_session, match.match_id)) == 1

    await save_match_lineup(
        match.match_id, _lineup_payload(match, swapped=True), context_for(tenant), api
    )
    entries = await _audit_rows(db_session, match.match_id)
    assert [entry["action"] for entry in entries] == ["SAVE_MATCH_LINEUP", "SAVE_MATCH_LINEUP"]
    assert entries[0]["payload"]["content_digest"] != entries[1]["payload"]["content_digest"]


@pytest.mark.asyncio
async def test_a_rejected_lineup_save_leaves_no_audit_entry(db_session, tenant_factory):
    tenant = await tenant_factory("T14 rejected lineup")
    match = await _create_operation_match(db_session, tenant)
    payload = _lineup_payload(match)
    payload.entries.append(MatchLineupEntry(roster_id=uuid4(), role="substitute"))

    with pytest.raises(HTTPException) as rejected:
        await save_match_lineup(
            match.match_id, payload, context_for(tenant), _NestedSession(db_session)
        )

    assert rejected.value.status_code == 422
    assert await _audit_rows(db_session, match.match_id) == []


# ---------------------------------------------------------------------------
# Opt-in: publication audits the transition, never the repetition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publication_audits_only_the_state_transition(db_session, tenant_factory):
    tenant = await tenant_factory("T14 publication")
    match = await _create_operation_match(db_session, tenant)
    api = _NestedSession(db_session)
    await save_match_lineup(
        match.match_id, _lineup_payload(match), context_for(tenant), api
    )
    await db_session.execute(
        text("""
            DELETE FROM administrative_audit_logs
            WHERE entity_type = 'matches' AND entity_id = :match_id
        """),
        {"match_id": str(match.match_id)},
    )
    publish = PublishMatchLineupRequest(
        segment_id=match.segment_id, team_id=match.home_team_id, is_public=True
    )

    await publish_match_lineup(match.match_id, publish, context_for(tenant), api)
    entries = await _audit_rows(db_session, match.match_id)
    assert [entry["action"] for entry in entries] == ["PUBLISH_MATCH_LINEUP"]
    assert set(entries[0]["payload"]) == {"segment_id", "team_id", "is_public", "formation_code"}
    assert entries[0]["payload"]["is_public"] is True

    await publish_match_lineup(match.match_id, publish, context_for(tenant), api)
    assert [entry["action"] for entry in await _audit_rows(db_session, match.match_id)] == [
        "PUBLISH_MATCH_LINEUP"
    ]

    await publish_match_lineup(
        match.match_id,
        PublishMatchLineupRequest(
            segment_id=match.segment_id, team_id=match.home_team_id, is_public=False
        ),
        context_for(tenant),
        api,
    )
    assert [
        entry["action"] for entry in await _audit_rows(db_session, match.match_id)
    ] == ["PUBLISH_MATCH_LINEUP", "UNPUBLISH_MATCH_LINEUP"]


# ---------------------------------------------------------------------------
# Opt-in: officials audit the effective assignment and removal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_officials_audit_one_entry_per_effective_change(db_session, tenant_factory):
    tenant = await tenant_factory("T14 officials")
    match = await _create_operation_match(db_session, tenant)
    api = _NestedSession(db_session)
    assignment = OfficialAssignmentRequest(
        organization_user_id=tenant.member_id, official_role="main_referee"
    )

    assigned = await assign_match_official(match.match_id, assignment, context_for(tenant), api)
    entries = await _audit_rows(db_session, match.match_id)
    assert [entry["action"] for entry in entries] == ["ASSIGN_MATCH_OFFICIAL"]
    assert entries[0]["payload"] == {
        "organization_user_id": str(tenant.member_id),
        "official_role": "main_referee",
    }

    await assign_match_official(match.match_id, assignment, context_for(tenant), api)
    assert len(await _audit_rows(db_session, match.match_id)) == 1

    await list_match_officials(match.match_id, context_for(tenant), api)
    assert len(await _audit_rows(db_session, match.match_id)) == 1

    await remove_match_official(
        match.match_id, tenant.member_id, "main_referee", context_for(tenant), api
    )
    entries = await _audit_rows(db_session, match.match_id)
    assert [entry["action"] for entry in entries] == [
        "ASSIGN_MATCH_OFFICIAL",
        "REMOVE_MATCH_OFFICIAL",
    ]
    assert entries[1]["payload"] == {
        "organization_user_id": str(tenant.member_id),
        "official_role": "main_referee",
    }

    with pytest.raises(HTTPException) as missing:
        await remove_match_official(
            match.match_id, tenant.member_id, "main_referee", context_for(tenant), api
        )
    assert missing.value.status_code == 404
    assert len(await _audit_rows(db_session, match.match_id)) == 2
    assert assigned["official_role"] == "main_referee"


# ---------------------------------------------------------------------------
# Opt-in: isolation and no personal data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_entries_stay_under_rls_and_carry_no_personal_data(
    db_session, tenant_factory
):
    tenant = await tenant_factory("T14 audit payload")
    match = await _create_operation_match(db_session, tenant)
    api = _NestedSession(db_session)
    await save_match_lineup(
        match.match_id, _lineup_payload(match), context_for(tenant), api
    )
    await publish_match_lineup(
        match.match_id,
        PublishMatchLineupRequest(
            segment_id=match.segment_id, team_id=match.home_team_id, is_public=True
        ),
        context_for(tenant),
        api,
    )
    await assign_match_official(
        match.match_id,
        OfficialAssignmentRequest(
            organization_user_id=tenant.member_id, official_role="assistant_referee_1"
        ),
        context_for(tenant),
        api,
    )

    entries = await _audit_rows(db_session, match.match_id)
    assert {entry["action"] for entry in entries} == {
        "SAVE_MATCH_LINEUP",
        "PUBLISH_MATCH_LINEUP",
        "ASSIGN_MATCH_OFFICIAL",
    }
    allowed_keys = {
        "SAVE_MATCH_LINEUP": {
            "segment_id",
            "teams",
            "formations",
            "entries",
            "starters",
            "substitutes",
            "content_digest",
        },
        "PUBLISH_MATCH_LINEUP": {"segment_id", "team_id", "is_public", "formation_code"},
        "UNPUBLISH_MATCH_LINEUP": {"segment_id", "team_id", "is_public", "formation_code"},
        "ASSIGN_MATCH_OFFICIAL": {"organization_user_id", "official_role"},
        "REMOVE_MATCH_OFFICIAL": {"organization_user_id", "official_role"},
    }
    for entry in entries:
        assert set(entry["payload"]) == allowed_keys[entry["action"]]
        serialized = json.dumps(entry["payload"]).lower()
        for forbidden in ("@", "email", "full_name", "first_name", "last_name", "national_id", "birth"):
            assert forbidden not in serialized
        # The seeded players are named "T14<label><dorsal>"; no name reaches the entry.
        assert "t14" not in serialized

    other = await tenant_factory("T14 other org")
    assert await _audit_rows(db_session, match.match_id) == []
    await set_rls_context(db_session, None, None)
    assert await _audit_rows(db_session, match.match_id) == []
    await set_tenant_context(db_session, tenant)
    assert len(await _audit_rows(db_session, match.match_id)) == 3
    # The other tenant must not see the entries even with its own context.
    await set_tenant_context(db_session, other)
    assert await _audit_rows(db_session, match.match_id) == []


# ---------------------------------------------------------------------------
# Opt-in: a reverted transaction leaves no entry behind
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reverted_action_leaves_no_audit_entry(database_admin_url):
    engine = create_async_engine(application_database_url(), pool_pre_ping=True)
    admin = await connect(database_admin_url)
    match_id = None
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            session = AsyncSession(bind=connection, expire_on_commit=False)
            try:
                tenant = await create_tenant_owner(session, full_name="T14 reverted")
                match = await _create_operation_match(session, tenant)
                match_id = match.match_id
                await save_match_lineup(
                    match.match_id,
                    _lineup_payload(match),
                    context_for(tenant),
                    _NestedSession(session),
                )
                await set_tenant_context(session, tenant)
                assert len(await _audit_rows(session, match.match_id)) == 1

                await outer.rollback()
            finally:
                await session.close()

        survivors = await admin.fetchval(
            """
            SELECT count(*)
            FROM public.administrative_audit_logs
            WHERE entity_type = 'matches' AND entity_id = $1
            """,
            match_id,
        )
        assert survivors == 0
    finally:
        if match_id is not None:
            await admin.execute(
                "DELETE FROM public.administrative_audit_logs WHERE entity_id = $1",
                match_id,
            )
        await admin.close()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Opt-in: committed database for the lock and the repeated publication
# ---------------------------------------------------------------------------


@asynccontextmanager
async def committed_application(database_admin_url):
    """Throwaway database at migration 023 plus a dedicated application role."""

    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    role_name = f"bc014_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    engine = None
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1, last=23)
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


async def _seeded_match(engine, *, with_lineup: bool = True):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        tenant = await create_tenant_owner(session, full_name="T14 committed")
        match = await _create_operation_match(session, tenant)
        await session.commit()
    context = context_for(tenant)
    if with_lineup:
        # Saving the lineup is setup here, not the subject: its audit entry is
        # removed so the assertion only sees the action under test.
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await save_match_lineup(match.match_id, _lineup_payload(match), context, session)
            await set_rls_context(session, tenant.organization_id, tenant.user_id)
            await session.execute(
                text("""
                    DELETE FROM administrative_audit_logs
                    WHERE entity_type = 'matches' AND entity_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
            await session.commit()
    return context, match


@pytest.mark.asyncio
async def test_operation_responds_while_another_transaction_holds_the_match_lock(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await _seeded_match(engine, with_lineup=False)

        async with AsyncSession(engine, expire_on_commit=False) as blocker:
            await set_rls_context(blocker, context.organization_id, context.user_id)
            await blocker.execute(
                text("SELECT id FROM matches WHERE id = :match_id FOR UPDATE"),
                {"match_id": str(match.match_id)},
            )

            async with AsyncSession(engine, expire_on_commit=False) as reader:
                response = await asyncio.wait_for(
                    get_match_operation(match.match_id, context, reader), timeout=10
                )
            assert str(response["match"]["id"]) == str(match.match_id)

            # The write path keeps the lock and waits for it, as today.
            async with AsyncSession(engine, expire_on_commit=False) as writer:
                async def load_locked():
                    async with writer.begin():
                        await set_rls_context(
                            writer, context.organization_id, context.user_id
                        )
                        return await _load_operation_match(
                            writer,
                            context,
                            match.match_id,
                            require_operation_permission=False,
                        )

                blocked = asyncio.create_task(load_locked())
                await asyncio.sleep(0.5)
                assert not blocked.done(), "la ruta de escritura debe esperar el bloqueo"
                await blocker.rollback()
                locked = await asyncio.wait_for(blocked, timeout=10)
                assert str(locked["id"]) == str(match.match_id)

        assert await _audit_rows_with_engine(engine, match.tenant, match.match_id) == []


@pytest.mark.asyncio
async def test_an_identical_publication_updates_the_timestamp_without_a_new_entry(
    database_admin_url,
):
    async with committed_application(database_admin_url) as engine:
        context, match = await _seeded_match(engine)
        publish = PublishMatchLineupRequest(
            segment_id=match.segment_id, team_id=match.home_team_id, is_public=True
        )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            first = await publish_match_lineup(match.match_id, publish, context, session)
        first_updated_at = await _lineup_updated_at(engine, context, match)

        await asyncio.sleep(0.01)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            second = await publish_match_lineup(match.match_id, publish, context, session)
        second_updated_at = await _lineup_updated_at(engine, context, match)

        assert first["published_at"] is not None
        assert second["published_at"] is not None
        assert second_updated_at > first_updated_at
        entries = await _audit_rows_with_engine(engine, match.tenant, match.match_id)
        assert [entry["action"] for entry in entries] == ["PUBLISH_MATCH_LINEUP"]


async def _lineup_updated_at(engine, context: AuthContext, match: OperationMatch):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_rls_context(session, context.organization_id, context.user_id)
        return (
            await session.execute(
                text("""
                    SELECT updated_at
                    FROM match_team_lineups
                    WHERE match_id = :match_id
                      AND segment_id = :segment_id
                      AND team_id = :team_id
                """),
                {
                    "match_id": str(match.match_id),
                    "segment_id": str(match.segment_id),
                    "team_id": str(match.home_team_id),
                },
            )
        ).scalar_one()
