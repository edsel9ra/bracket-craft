"""Opt-in PostgreSQL coverage for the spec 006 concurrency and access rules.

Requires ``RUN_DATABASE_TESTS=1`` and ``DATABASE_ADMIN_URL``. Every test builds
a throwaway database from the real ``init`` scripts and migrations 1..23, seeds
its own tenants and runs the real route functions through a **dedicated role**
that inherits the application role privileges (the shared ``bracket_app`` role
is never altered).

Covered: simultaneous POST/POST, POST/DELETE, POST/publication,
DELETE/publication and DELETE/match creation; cross-tenant 404; two DELETEs;
standings guard; direct 409 on a published version; real ``ZZ409`` through the
API; clone isolation; and role permissions for the new endpoints.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.database import set_rls_context
from app.core.tenancy import AuthContext
from app.main import api
from app.modules.rules_engine.defaults import DEFAULT_RULES_CONFIG
from app.modules.tournaments.router import (
    assign_stage_teams,
    create_draft_version,
    create_match,
    list_stage_teams,
    publish_version,
    remove_stage_team,
)
from app.modules.tournaments.schemas import (
    AssignStageTeamsRequest,
    CreateDraftVersionRequest,
    CreateMatchRequest,
)
from migration_helpers import (
    apply_init,
    apply_migrations,
    connect,
    create_database,
    drop_database,
    ensure_application_role,
)

MATCH_DATE = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


@dataclass
class Harness:
    admin: object
    engine: object
    organization_id: UUID
    user_id: UUID
    member_id: UUID
    tournament_id: UUID
    version_id: UUID
    stage_id: UUID
    teams: list[UUID]
    member_contexts: dict[str, AuthContext] = field(default_factory=dict)

    @property
    def context(self) -> AuthContext:
        return AuthContext(
            user_id=self.user_id,
            organization_id=self.organization_id,
            organization_user_id=self.member_id,
        )

    def context_for(self, role: str) -> AuthContext:
        return self.member_contexts[role]

    # -- setup -----------------------------------------------------------
    async def add_stage_team(
        self,
        team_id: UUID,
        *,
        tournament_id: UUID | None = None,
        version_id: UUID | None = None,
        stage_id: UUID | None = None,
    ) -> None:
        await self.admin.execute(
            """
            INSERT INTO public.stage_teams (
                organization_id, tournament_id, tournament_version_id,
                stage_id, group_id, team_id
            ) VALUES ($1, $2, $3, $4, NULL, $5)
            """,
            self.organization_id,
            tournament_id or self.tournament_id,
            version_id or self.version_id,
            stage_id or self.stage_id,
            team_id,
        )

    async def add_stage_teams(self, team_ids) -> None:
        for team_id in team_ids:
            await self.add_stage_team(team_id)

    async def add_match(self, home_team_id: UUID, away_team_id: UUID) -> UUID:
        match_id = uuid4()
        await self.admin.execute(
            """
            INSERT INTO public.matches (
                id, organization_id, tournament_id, tournament_version_id,
                stage_id, home_team_id, away_team_id, match_date, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'scheduled')
            """,
            match_id,
            self.organization_id,
            self.tournament_id,
            self.version_id,
            self.stage_id,
            home_team_id,
            away_team_id,
            MATCH_DATE,
        )
        return match_id

    async def add_standings(self, team_id: UUID) -> None:
        await self.admin.execute(
            """
            INSERT INTO public.standings (
                organization_id, tournament_id, stage_id, group_id, team_id, rank
            ) VALUES ($1, $2, $3, NULL, $4, 1)
            """,
            self.organization_id,
            self.tournament_id,
            self.stage_id,
            team_id,
        )

    # -- assertions ------------------------------------------------------
    async def stage_team_counts(
        self,
        *,
        organization_id: UUID | None = None,
        tournament_id: UUID | None = None,
        stage_id: UUID | None = None,
    ) -> dict[UUID, int]:
        rows = await self.admin.fetch(
            """
            SELECT team_id, count(*) AS total
            FROM public.stage_teams
            WHERE organization_id = $1 AND tournament_id = $2 AND stage_id = $3
            GROUP BY team_id
            """,
            organization_id or self.organization_id,
            tournament_id or self.tournament_id,
            stage_id or self.stage_id,
        )
        return {row["team_id"]: row["total"] for row in rows}

    async def match_count(self) -> int:
        return await self.admin.fetchval(
            """
            SELECT count(*)
            FROM public.matches
            WHERE organization_id = $1 AND stage_id = $2
            """,
            self.organization_id,
            self.stage_id,
        )

    async def version_status(self, version_id: UUID | None = None) -> str:
        return await self.admin.fetchval(
            "SELECT status FROM public.tournament_versions WHERE id = $1",
            version_id or self.version_id,
        )

    # -- route calls -----------------------------------------------------
    async def assign(
        self,
        team_ids,
        *,
        tournament_id: UUID | None = None,
        stage_id: UUID | None = None,
        context: AuthContext | None = None,
    ) -> int:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            response = Response()
            try:
                await assign_stage_teams(
                    tournament_id or self.tournament_id,
                    stage_id or self.stage_id,
                    AssignStageTeamsRequest(team_ids=list(team_ids)),
                    response,
                    context or self.context,
                    session,
                )
            except HTTPException as exc:
                return exc.status_code
            return response.status_code

    async def remove(
        self,
        team_id: UUID,
        *,
        tournament_id: UUID | None = None,
        stage_id: UUID | None = None,
        context: AuthContext | None = None,
    ) -> int:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            try:
                await remove_stage_team(
                    tournament_id or self.tournament_id,
                    stage_id or self.stage_id,
                    team_id,
                    context or self.context,
                    session,
                )
            except HTTPException as exc:
                return exc.status_code
            return 204

    async def publish(
        self,
        *,
        version_id: UUID | None = None,
        context: AuthContext | None = None,
    ) -> int:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            try:
                await publish_version(
                    version_id or self.version_id,
                    context or self.context,
                    session,
                )
            except HTTPException as exc:
                return exc.status_code
            return 200

    async def create_match(self, home_team_id: UUID, away_team_id: UUID) -> int:
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            try:
                await create_match(
                    self.tournament_id,
                    CreateMatchRequest(
                        version_id=self.version_id,
                        stage_id=self.stage_id,
                        home_team_id=home_team_id,
                        away_team_id=away_team_id,
                        match_date=MATCH_DATE,
                    ),
                    self.context,
                    session,
                )
            except HTTPException as exc:
                return exc.status_code
            return 201

    async def get_stage_teams(
        self,
        *,
        tournament_id: UUID | None = None,
        stage_id: UUID | None = None,
        context: AuthContext | None = None,
    ):
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            try:
                result = await list_stage_teams(
                    tournament_id or self.tournament_id,
                    stage_id or self.stage_id,
                    context or self.context,
                    session,
                )
            except HTTPException as exc:
                return exc.status_code, None
            return 200, result

    async def clone(self, tournament_id: UUID, source_version_id: UUID, context=None):
        async with AsyncSession(self.engine, expire_on_commit=False) as session:
            return await create_draft_version(
                tournament_id,
                CreateDraftVersionRequest(source_version_id=source_version_id),
                context or self.context,
                session,
            )


async def _add_member(
    admin,
    organization_id: UUID,
    role_code: str,
    permissions: list[str],
) -> AuthContext:
    user_id = uuid4()
    member_id = uuid4()
    role_id = uuid4()
    await admin.execute(
        """
        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES ($1, $2, 'hash', $3)
        """,
        user_id,
        f"concurrency-{role_code}-{user_id.hex}@example.test",
        f"Concurrency {role_code}",
    )
    await admin.execute(
        """
        INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
        VALUES ($1, $2, $3, TRUE)
        """,
        member_id,
        organization_id,
        user_id,
    )
    await admin.execute(
        """
        INSERT INTO public.roles (id, organization_id, role_definition_id, name, permissions)
        SELECT $1, $2, rd.id, $3, $4::jsonb
        FROM public.role_definitions rd
        WHERE rd.code = $5
        """,
        role_id,
        organization_id,
        role_code,
        json.dumps(permissions),
        role_code,
    )
    await admin.execute(
        """
        INSERT INTO public.organization_user_roles (
            organization_id, organization_user_id, role_id
        ) VALUES ($1, $2, $3)
        """,
        organization_id,
        member_id,
        role_id,
    )
    return AuthContext(
        user_id=user_id,
        organization_id=organization_id,
        organization_user_id=member_id,
    )


async def _seed(admin) -> Harness:
    organization_id = uuid4()
    tournament_id = uuid4()
    version_id = uuid4()
    stage_id = uuid4()
    teams = [uuid4() for _ in range(3)]

    await admin.execute(
        "INSERT INTO public.organizations (id, name, slug) VALUES ($1, $2, $3)",
        organization_id,
        "Concurrency 006",
        f"concurrency-006-{organization_id.hex}",
    )
    owner = await _add_member(
        admin, organization_id, "owner", ["MANAGE_TOURNAMENTS"]
    )
    contexts = {"owner": owner}
    for role, permissions in (
        ("administrator", ["MANAGE_TOURNAMENTS"]),
        ("operator", ["CLOSE_MATCH_REPORT"]),
        ("referee", ["CLOSE_MATCH_REPORT"]),
    ):
        contexts[role] = await _add_member(
            admin, organization_id, role, permissions
        )

    await admin.execute(
        """
        INSERT INTO public.tournaments (
            id, organization_id, name, season, start_date, status
        ) VALUES ($1, $2, 'Concurrency Cup', '2026', DATE '2026-01-01', 'draft')
        """,
        tournament_id,
        organization_id,
    )
    await admin.execute(
        """
        INSERT INTO public.tournament_versions (
            id, organization_id, tournament_id, version_number, rules_config,
            phase_config, status, created_by_member_id
        ) VALUES ($1, $2, $3, 1, $4::jsonb, '{}'::jsonb, 'draft', $5)
        """,
        version_id,
        organization_id,
        tournament_id,
        json.dumps(DEFAULT_RULES_CONFIG),
        owner.organization_user_id,
    )
    await admin.execute(
        """
        INSERT INTO public.stages (
            id, organization_id, tournament_id, tournament_version_id,
            name, stage_type, stage_order
        ) VALUES ($1, $2, $3, $4, 'Group', 'round_robin', 1)
        """,
        stage_id,
        organization_id,
        tournament_id,
        version_id,
    )
    for index, team_id in enumerate(teams, start=1):
        await admin.execute(
            """
            INSERT INTO public.teams (id, organization_id, name, short_code)
            VALUES ($1, $2, $3, $4)
            """,
            team_id,
            organization_id,
            f"Concurrency Team {index}",
            f"C{index:02d}",
        )
        await admin.execute(
            """
            INSERT INTO public.tournament_teams (
                organization_id, tournament_id, team_id, status
            ) VALUES ($1, $2, $3, 'registered')
            """,
            organization_id,
            tournament_id,
            team_id,
        )

    return Harness(
        admin=admin,
        engine=None,
        organization_id=organization_id,
        user_id=owner.user_id,
        member_id=owner.organization_user_id,
        tournament_id=tournament_id,
        version_id=version_id,
        stage_id=stage_id,
        teams=teams,
        member_contexts=contexts,
    )


async def _seed_published_tournament(
    admin,
    organization_id: UUID,
    member_id: UUID,
    teams: list[UUID],
    assigned: list[UUID],
) -> dict:
    tournament_id = uuid4()
    version_id = uuid4()
    stage_id = uuid4()
    await admin.execute(
        """
        INSERT INTO public.tournaments (
            id, organization_id, name, season, start_date, status
        ) VALUES ($1, $2, 'Published Cup', '2026', DATE '2026-01-01', 'draft')
        """,
        tournament_id,
        organization_id,
    )
    await admin.execute(
        """
        INSERT INTO public.tournament_versions (
            id, organization_id, tournament_id, version_number, rules_config,
            phase_config, status, created_by_member_id
        ) VALUES ($1, $2, $3, 1, $4::jsonb, '{}'::jsonb, 'draft', $5)
        """,
        version_id,
        organization_id,
        tournament_id,
        json.dumps(DEFAULT_RULES_CONFIG),
        member_id,
    )
    await admin.execute(
        """
        INSERT INTO public.stages (
            id, organization_id, tournament_id, tournament_version_id,
            name, stage_type, stage_order
        ) VALUES ($1, $2, $3, $4, 'Bracket', 'single_elimination', 1)
        """,
        stage_id,
        organization_id,
        tournament_id,
        version_id,
    )
    for team_id in teams:
        await admin.execute(
            """
            INSERT INTO public.tournament_teams (
                organization_id, tournament_id, team_id, status
            ) VALUES ($1, $2, $3, 'registered')
            ON CONFLICT (tournament_id, team_id) DO NOTHING
            """,
            organization_id,
            tournament_id,
            team_id,
        )
    for team_id in assigned:
        await admin.execute(
            """
            INSERT INTO public.stage_teams (
                organization_id, tournament_id, tournament_version_id,
                stage_id, group_id, team_id
            ) VALUES ($1, $2, $3, $4, NULL, $5)
            """,
            organization_id,
            tournament_id,
            version_id,
            stage_id,
            team_id,
        )
    # Publish only after the draft structure exists: the immutability trigger
    # rejects inserts on a published version.
    await admin.execute(
        "UPDATE public.tournament_versions SET status = 'published' WHERE id = $1",
        version_id,
    )
    await admin.execute(
        """
        UPDATE public.tournaments
        SET status = 'published', published_version_id = $2
        WHERE id = $1
        """,
        tournament_id,
        version_id,
    )
    return {
        "tournament_id": tournament_id,
        "version_id": version_id,
        "stage_id": stage_id,
    }


async def _seed_other_tenant(admin) -> dict:
    organization_id = uuid4()
    user_id = uuid4()
    member_id = uuid4()
    role_id = uuid4()
    tournament_id = uuid4()
    version_id = uuid4()
    stage_id = uuid4()
    team_id = uuid4()
    await admin.execute(
        "INSERT INTO public.organizations (id, name, slug) VALUES ($1, $2, $3)",
        organization_id,
        "Other Concurrency Org",
        f"other-concurrency-{organization_id.hex}",
    )
    await admin.execute(
        """
        INSERT INTO public.users (id, email, password_hash, full_name)
        VALUES ($1, $2, 'hash', 'Other Owner')
        """,
        user_id,
        f"other-{user_id.hex}@example.test",
    )
    await admin.execute(
        """
        INSERT INTO public.organization_users (id, organization_id, user_id, is_active)
        VALUES ($1, $2, $3, TRUE)
        """,
        member_id,
        organization_id,
        user_id,
    )
    await admin.execute(
        """
        INSERT INTO public.roles (id, organization_id, role_definition_id, name, permissions)
        SELECT $1, $2, rd.id, 'owner', '["MANAGE_TOURNAMENTS"]'::jsonb
        FROM public.role_definitions rd WHERE rd.code = 'owner'
        """,
        role_id,
        organization_id,
    )
    await admin.execute(
        """
        INSERT INTO public.organization_user_roles (
            organization_id, organization_user_id, role_id
        ) VALUES ($1, $2, $3)
        """,
        organization_id,
        member_id,
        role_id,
    )
    await admin.execute(
        """
        INSERT INTO public.tournaments (
            id, organization_id, name, season, start_date, status
        ) VALUES ($1, $2, 'Other Cup', '2026', DATE '2026-01-01', 'draft')
        """,
        tournament_id,
        organization_id,
    )
    await admin.execute(
        """
        INSERT INTO public.tournament_versions (
            id, organization_id, tournament_id, version_number, rules_config,
            phase_config, status, created_by_member_id
        ) VALUES ($1, $2, $3, 1, $4::jsonb, '{}'::jsonb, 'draft', $5)
        """,
        version_id,
        organization_id,
        tournament_id,
        json.dumps(DEFAULT_RULES_CONFIG),
        member_id,
    )
    await admin.execute(
        """
        INSERT INTO public.stages (
            id, organization_id, tournament_id, tournament_version_id,
            name, stage_type, stage_order
        ) VALUES ($1, $2, $3, $4, 'Other Stage', 'round_robin', 1)
        """,
        stage_id,
        organization_id,
        tournament_id,
        version_id,
    )
    await admin.execute(
        """
        INSERT INTO public.teams (id, organization_id, name, short_code)
        VALUES ($1, $2, 'Other Team', 'OTH')
        """,
        team_id,
        organization_id,
    )
    await admin.execute(
        """
        INSERT INTO public.tournament_teams (
            organization_id, tournament_id, team_id, status
        ) VALUES ($1, $2, $3, 'registered')
        """,
        organization_id,
        tournament_id,
        team_id,
    )
    await admin.execute(
        """
        INSERT INTO public.stage_teams (
            organization_id, tournament_id, tournament_version_id,
            stage_id, group_id, team_id
        ) VALUES ($1, $2, $3, $4, NULL, $5)
        """,
        organization_id,
        tournament_id,
        version_id,
        stage_id,
        team_id,
    )
    return {
        "organization_id": organization_id,
        "tournament_id": tournament_id,
        "version_id": version_id,
        "stage_id": stage_id,
        "team_id": team_id,
    }


@pytest.fixture
async def harness(database_admin_url):
    await ensure_application_role(database_admin_url)
    database = await create_database(database_admin_url)
    admin = await connect(database_admin_url, database)
    engine = None
    role_name = f"bc006_{secrets.token_hex(8)}"
    role_password = secrets.token_hex(16)
    try:
        await apply_init(admin)
        await apply_migrations(admin, first=1, last=23)
        # Dedicated role per throwaway database: it inherits bracket_app
        # privileges but the shared role is never altered.
        await admin.execute(
            f"""
            CREATE ROLE "{role_name}" LOGIN PASSWORD '{role_password}'
            NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOBYPASSRLS
            """
        )
        await admin.execute(f'GRANT bracket_app TO "{role_name}"')
        data = await _seed(admin)

        parsed = make_url(database_admin_url)
        app_url = (
            f"postgresql+asyncpg://{role_name}:{role_password}"
            f"@{parsed.host or '127.0.0.1'}:{parsed.port or 5432}/{database}"
        )
        engine = create_async_engine(app_url, pool_pre_ping=True)
        data.engine = engine
        yield data
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


# ---------------------------------------------------------------------------
# Two POSTs on the same stage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_simultaneous_posts_do_not_duplicate_rows(harness):
    first, second = await asyncio.gather(
        harness.assign([harness.teams[0], harness.teams[1]]),
        harness.assign([harness.teams[0], harness.teams[1]]),
    )

    assert sorted([first, second]) == [200, 201]
    counts = await harness.stage_team_counts()
    assert counts == {harness.teams[0]: 1, harness.teams[1]: 1}


# ---------------------------------------------------------------------------
# POST and DELETE of the same team
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simultaneous_post_and_delete_leave_a_coherent_state(harness):
    await harness.add_stage_teams([harness.teams[0]])

    assign_status, delete_status = await asyncio.gather(
        harness.assign([harness.teams[0]]),
        harness.remove(harness.teams[0]),
    )

    assert assign_status in {200, 201}
    assert delete_status == 204
    counts = await harness.stage_team_counts()
    remaining = counts.get(harness.teams[0], 0)
    # If the POST inserted first, the DELETE removes it; if the DELETE ran
    # first, the POST re-inserts it. Both are serialized and coherent.
    assert remaining in {0, 1}
    assert remaining == (1 if assign_status == 201 else 0)


# ---------------------------------------------------------------------------
# Assignment/removal against publication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simultaneous_post_and_publication(harness):
    await harness.add_stage_teams([harness.teams[0], harness.teams[1]])
    await harness.add_match(harness.teams[0], harness.teams[1])

    assign_status, publish_status = await asyncio.gather(
        harness.assign([harness.teams[2]]),
        harness.publish(),
    )

    assert publish_status == 200
    assert assign_status in {201, 409}
    counts = await harness.stage_team_counts()
    assert counts.get(harness.teams[2], 0) == (1 if assign_status == 201 else 0)
    assert await harness.version_status() == "published"
    assert await harness.match_count() == 1


@pytest.mark.asyncio
async def test_simultaneous_delete_and_publication(harness):
    await harness.add_stage_teams(
        [harness.teams[0], harness.teams[1], harness.teams[2]]
    )
    await harness.add_match(harness.teams[0], harness.teams[1])

    delete_status, publish_status = await asyncio.gather(
        harness.remove(harness.teams[2]),
        harness.publish(),
    )

    assert publish_status == 200
    assert delete_status in {204, 409}
    counts = await harness.stage_team_counts()
    assert counts.get(harness.teams[2], 0) == (0 if delete_status == 204 else 1)
    assert await harness.version_status() == "published"
    assert await harness.match_count() == 1


# ---------------------------------------------------------------------------
# DELETE against match creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simultaneous_delete_and_match_creation(harness):
    await harness.add_stage_teams([harness.teams[0], harness.teams[1]])

    delete_status, create_status = await asyncio.gather(
        harness.remove(harness.teams[0]),
        harness.create_match(harness.teams[0], harness.teams[1]),
    )

    assert (delete_status, create_status) in {(204, 409), (409, 201)}
    counts = await harness.stage_team_counts()
    matches = await harness.match_count()
    if create_status == 201:
        assert matches == 1
        assert counts.get(harness.teams[0], 0) == 1
    else:
        assert matches == 0
        assert counts.get(harness.teams[0], 0) == 0


# ---------------------------------------------------------------------------
# H1a — cross-tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_tenant_stage_is_404_and_never_written(harness):
    other = await _seed_other_tenant(harness.admin)

    get_status, payload = await harness.get_stage_teams(
        tournament_id=other["tournament_id"],
        stage_id=other["stage_id"],
    )
    assign_status = await harness.assign(
        [other["team_id"]],
        tournament_id=other["tournament_id"],
        stage_id=other["stage_id"],
    )
    remove_status = await harness.remove(
        other["team_id"],
        tournament_id=other["tournament_id"],
        stage_id=other["stage_id"],
    )
    # A team from another organization is not registered in this tournament:
    # the same-organization stage answers 409 and writes nothing.
    cross_status = await harness.assign([other["team_id"]])

    assert get_status == 404 and payload is None
    assert assign_status == 404
    assert remove_status == 404
    assert cross_status == 409
    assert await harness.stage_team_counts() == {}
    counts = await harness.stage_team_counts(
        organization_id=other["organization_id"],
        tournament_id=other["tournament_id"],
        stage_id=other["stage_id"],
    )
    assert counts == {other["team_id"]: 1}


# ---------------------------------------------------------------------------
# H1b — two simultaneous DELETEs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_simultaneous_deletes_leave_no_inconsistent_state(harness):
    await harness.add_stage_teams([harness.teams[0]])

    first, second = await asyncio.gather(
        harness.remove(harness.teams[0]),
        harness.remove(harness.teams[0]),
    )

    assert first == 204 and second == 204
    counts = await harness.stage_team_counts()
    assert harness.teams[0] not in counts


# ---------------------------------------------------------------------------
# H1c — real standings guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_with_standings_and_no_match_is_409(harness):
    await harness.add_stage_teams([harness.teams[0]])
    await harness.add_standings(harness.teams[0])

    status = await harness.remove(harness.teams[0])

    assert status == 409
    counts = await harness.stage_team_counts()
    assert counts == {harness.teams[0]: 1}
    assert await harness.match_count() == 0
    assert await harness.admin.fetchval(
        "SELECT count(*) FROM public.standings WHERE stage_id = $1 AND team_id = $2",
        harness.stage_id,
        harness.teams[0],
    ) == 1


# ---------------------------------------------------------------------------
# H1d — published version returns 409 before any idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_published_version_returns_409_for_assigned_and_unassigned(harness):
    published = await _seed_published_tournament(
        harness.admin,
        harness.organization_id,
        harness.member_id,
        teams=[harness.teams[0], harness.teams[1]],
        assigned=[harness.teams[0]],
    )

    assign_assigned = await harness.assign(
        [harness.teams[0]],
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )
    assign_unassigned = await harness.assign(
        [harness.teams[1]],
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )
    remove_assigned = await harness.remove(
        harness.teams[0],
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )
    remove_unassigned = await harness.remove(
        harness.teams[1],
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )

    assert assign_assigned == 409
    assert assign_unassigned == 409
    assert remove_assigned == 409
    assert remove_unassigned == 409
    counts = await harness.stage_team_counts(
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )
    assert counts == {harness.teams[0]: 1}


# ---------------------------------------------------------------------------
# H1e — real ZZ409 through the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_zz409_trigger_is_mapped_to_409_by_the_api(harness):
    published = await _seed_published_tournament(
        harness.admin,
        harness.organization_id,
        harness.member_id,
        teams=[harness.teams[0], harness.teams[1]],
        assigned=[harness.teams[0]],
    )

    async def insert_into_published_stage() -> dict:
        async with AsyncSession(harness.engine) as session:
            async with session.begin():
                await set_rls_context(
                    session, harness.organization_id, harness.user_id
                )
                await session.execute(
                    text("""
                        INSERT INTO stage_teams (
                            organization_id, tournament_id, tournament_version_id,
                            stage_id, group_id, team_id
                        ) VALUES (
                            :organization_id, :tournament_id, :version_id,
                            :stage_id, NULL, :team_id
                        )
                    """),
                    {
                        "organization_id": str(harness.organization_id),
                        "tournament_id": str(published["tournament_id"]),
                        "version_id": str(published["version_id"]),
                        "stage_id": str(published["stage_id"]),
                        "team_id": str(harness.teams[1]),
                    },
                )
        return {"ok": True}

    route = APIRoute(
        "/__test__/zz409-real", insert_into_published_stage, methods=["POST"]
    )
    api.router.routes.append(route)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=api), base_url="http://test"
        ) as client:
            response = await client.post("/__test__/zz409-real")
    finally:
        api.router.routes.remove(route)

    assert response.status_code == 409
    assert response.json() == {"detail": "La versión publicada es inmutable"}
    counts = await harness.stage_team_counts(
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )
    assert counts == {harness.teams[0]: 1}


# ---------------------------------------------------------------------------
# H1f — GET after cloning does not mix versions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_after_clone_does_not_mix_versions(harness):
    published = await _seed_published_tournament(
        harness.admin,
        harness.organization_id,
        harness.member_id,
        teams=[harness.teams[0], harness.teams[1]],
        assigned=[harness.teams[0], harness.teams[1]],
    )

    created = await harness.clone(
        published["tournament_id"], published["version_id"]
    )
    new_version_id = created["id"]
    new_stage_id = await harness.admin.fetchval(
        """
        SELECT id FROM public.stages
        WHERE tournament_id = $1 AND tournament_version_id = $2
        """,
        published["tournament_id"],
        new_version_id,
    )

    old_status, old_payload = await harness.get_stage_teams(
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )
    new_status, new_payload = await harness.get_stage_teams(
        tournament_id=published["tournament_id"],
        stage_id=new_stage_id,
    )
    assert old_status == 200 and new_status == 200
    old_ids = {team["team_id"] for team in old_payload["assigned"]}
    new_ids = {team["team_id"] for team in new_payload["assigned"]}
    assert old_ids == {harness.teams[0], harness.teams[1]}
    assert new_ids == old_ids

    # Removing from the new draft must not touch the published version.
    assert await harness.remove(
        harness.teams[0],
        tournament_id=published["tournament_id"],
        stage_id=new_stage_id,
    ) == 204
    _, new_after = await harness.get_stage_teams(
        tournament_id=published["tournament_id"],
        stage_id=new_stage_id,
    )
    _, old_after = await harness.get_stage_teams(
        tournament_id=published["tournament_id"],
        stage_id=published["stage_id"],
    )
    assert {team["team_id"] for team in new_after["assigned"]} == {harness.teams[1]}
    assert {team["team_id"] for team in old_after["assigned"]} == {
        harness.teams[0],
        harness.teams[1],
    }


# ---------------------------------------------------------------------------
# H1g — endpoint permissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_team_permissions_follow_organization_roles(harness):
    administrator = harness.context_for("administrator")
    operator = harness.context_for("operator")
    referee = harness.context_for("referee")

    assert await harness.assign([harness.teams[0]], context=administrator) == 201
    assert await harness.assign([harness.teams[1]], context=operator) == 403
    assert await harness.assign([harness.teams[1]], context=referee) == 403

    assert await harness.remove(harness.teams[0], context=operator) == 403
    assert await harness.remove(harness.teams[0], context=referee) == 403
    counts = await harness.stage_team_counts()
    assert counts == {harness.teams[0]: 1}
