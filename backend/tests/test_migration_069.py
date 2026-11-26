"""Migración 069: operador del torneo (spec 049, T1).

Cada test crea una base desechable con los scripts ``init`` y las migraciones
numeradas reales. Se valida la cadena ya migrada (068 -> 069) y la de volumen
limpio (init + 001..069). Requiere ``RUN_DATABASE_TESTS=1`` y
``DATABASE_ADMIN_URL``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MATCH, MEMBER, ORG, SEED_SQL, TEAM_AWAY, TEAM_HOME, TOURNAMENT, USER

USER_VIEWER = "49000000-0000-4000-8000-000000000002"
MEMBER_VIEWER = "49000000-0000-4000-8000-000000000003"
OTHER_ORG = "49000000-0000-4000-8000-000000000010"
OTHER_USER = "49000000-0000-4000-8000-000000000011"
OTHER_MEMBER = "49000000-0000-4000-8000-000000000012"
OTHER_TOURNAMENT = "49000000-0000-4000-8000-000000000013"
TOURNAMENT_B = "49000000-0000-4000-8000-000000000020"
VERSION_B = "49000000-0000-4000-8000-000000000021"
STAGE_B = "49000000-0000-4000-8000-000000000022"
MATCH_B = "49000000-0000-4000-8000-000000000023"
TOURNAMENT_C = "49000000-0000-4000-8000-000000000030"

TABLE = "tournament_member_roles"
ROLE = "tournament_operator"
GRANTED = ("VIEW_MATCH_LIVE_DRAFT", "OPERATE_MATCH_LIVE", "CLOSE_MATCH_REPORT")
NOT_GRANTED = ("MANAGE_TOURNAMENTS", "MANAGE_MEMBERS", "VIEW_SANCTIONS", "VIEW_ORGANIZATION_AUDIT")
FUNCTION = "tournament_operator_allows(uuid,uuid,text)"

EXTRA_SEED = f"""
INSERT INTO public.users (id, email, password_hash, full_name) VALUES
    ('{USER_VIEWER}', 'viewer-049@example.test', 'hash', 'Viewer'),
    ('{OTHER_USER}', 'other-049@example.test', 'hash', 'Other');
INSERT INTO public.organizations (id, name, slug) VALUES ('{OTHER_ORG}', 'Other 049', 'other-049');
INSERT INTO public.organization_users (id, organization_id, user_id, is_active) VALUES
    ('{MEMBER_VIEWER}', '{ORG}', '{USER_VIEWER}', TRUE),
    ('{OTHER_MEMBER}', '{OTHER_ORG}', '{OTHER_USER}', TRUE);
INSERT INTO public.roles (organization_id, role_definition_id, name, permissions)
SELECT o.id, rd.id, rd.name, rd.system_permissions
FROM public.role_definitions rd CROSS JOIN (VALUES ('{ORG}'::uuid), ('{OTHER_ORG}'::uuid)) AS o(id);
INSERT INTO public.organization_user_roles (organization_id, organization_user_id, role_id)
SELECT r.organization_id, m.member, r.id
FROM (VALUES ('{ORG}'::uuid, '{MEMBER}'::uuid, 'owner'), ('{ORG}'::uuid, '{MEMBER_VIEWER}'::uuid, 'viewer'),
             ('{OTHER_ORG}'::uuid, '{OTHER_MEMBER}'::uuid, 'owner')) AS m(org, member, code)
JOIN public.role_definitions rd ON rd.code = m.code
JOIN public.roles r ON r.role_definition_id = rd.id AND r.organization_id = m.org;
INSERT INTO public.tournaments (id, organization_id, name, season, start_date, status, current_draft_config) VALUES
    ('{TOURNAMENT_B}', '{ORG}', 'Cup B', '2026', DATE '2026-01-01', 'draft', '{{}}'::jsonb),
    ('{TOURNAMENT_C}', '{ORG}', 'Cup C', '2026', DATE '2026-01-01', 'draft', '{{}}'::jsonb),
    ('{OTHER_TOURNAMENT}', '{OTHER_ORG}', 'Other Cup', '2026', DATE '2026-01-01', 'draft', '{{}}'::jsonb);
INSERT INTO public.tournament_versions
    (id, organization_id, tournament_id, version_number, rules_config, phase_config, status, created_by_member_id)
VALUES ('{VERSION_B}', '{ORG}', '{TOURNAMENT_B}', 1, '{{}}'::jsonb, '{{}}'::jsonb, 'draft', '{MEMBER}');
INSERT INTO public.stages (id, organization_id, tournament_id, tournament_version_id, name, stage_type, stage_order)
VALUES ('{STAGE_B}', '{ORG}', '{TOURNAMENT_B}', '{VERSION_B}', 'Group', 'round_robin', 1);
INSERT INTO public.tournament_teams (organization_id, tournament_id, team_id, status) VALUES
    ('{ORG}', '{TOURNAMENT_B}', '{TEAM_HOME}', 'registered'), ('{ORG}', '{TOURNAMENT_B}', '{TEAM_AWAY}', 'registered');
INSERT INTO public.stage_teams (organization_id, tournament_id, tournament_version_id, stage_id, team_id) VALUES
    ('{ORG}', '{TOURNAMENT_B}', '{VERSION_B}', '{STAGE_B}', '{TEAM_HOME}'),
    ('{ORG}', '{TOURNAMENT_B}', '{VERSION_B}', '{STAGE_B}', '{TEAM_AWAY}');
INSERT INTO public.matches
    (id, organization_id, tournament_id, tournament_version_id, stage_id, home_team_id, away_team_id, status, matchday)
VALUES ('{MATCH_B}', '{ORG}', '{TOURNAMENT_B}', '{VERSION_B}', '{STAGE_B}', '{TEAM_HOME}', '{TEAM_AWAY}', 'scheduled', 1);
"""  # nosec B608 - SQL de semilla con constantes UUID fijas del test


@pytest.fixture
async def db(database_admin_url):
    async with throwaway_database(database_admin_url, last=68) as connection:
        await connection.execute(SEED_SQL)
        await connection.execute(EXTRA_SEED)
        await apply_migration(connection, 69)
        yield connection


@asynccontextmanager
async def as_app(db, org=ORG, user=USER_VIEWER):
    async with db.transaction():
        await db.execute("SET LOCAL ROLE bracket_app")
        await db.execute("SELECT set_config('app.current_organization_id',$1,true)", org)
        await db.execute("SELECT set_config('app.current_user_id',$1,true)", user)
        yield


async def assign(db, tournament=TOURNAMENT, member=MEMBER_VIEWER, *, org=ORG, user=USER, created_by=MEMBER):
    async with as_app(db, org=org, user=user):
        return await db.fetchval(
            "INSERT INTO public.tournament_member_roles (organization_id, tournament_id, organization_user_id, role_code,"
            " created_by_member_id) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            org, tournament, member, ROLE, created_by,
        )


async def allows(db, match=MATCH, permission="OPERATE_MATCH_LIVE", *, org=ORG, user=USER_VIEWER, function="tournament_operator_allows"):
    async with as_app(db, org=org, user=user):
        return await db.fetchval(f"SELECT public.{function}($1, $2, $3)", org, match, permission)  # noqa: S608


async def can_operate_sanction(db, match=MATCH, *, user=USER_VIEWER):
    async with as_app(db, user=user):
        return await db.fetchval("SELECT public.sanction_can_operate_match($1, $2)", ORG, match)


async def test_069_clean_volume_creates_table_with_forced_rls_and_minimal_grants(database_admin_url):
    async with throwaway_database(database_admin_url, last=69) as db:
        rls = await db.fetchrow(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = 'public.tournament_member_roles'::regclass"
        )
        assert tuple(rls) == (True, True)
        policies = await db.fetch(
            "SELECT policyname, cmd, roles FROM pg_policies WHERE tablename = $1", TABLE
        )
        assert [(p["policyname"], p["cmd"], list(p["roles"])) for p in policies] == [
            ("tournament_member_roles_tenant", "ALL", ["bracket_app"])
        ]
        for privilege, expected in (("SELECT", True), ("INSERT", True), ("DELETE", True), ("UPDATE", False), ("TRUNCATE", False)):
            granted = await db.fetchval(
                "SELECT has_table_privilege('bracket_app', 'public.tournament_member_roles', $1)", privilege
            )
            assert granted is expected
        assert await db.fetchval(f"SELECT has_function_privilege('bracket_app', 'public.{FUNCTION}', 'EXECUTE')")
        assert not await db.fetchval(f"SELECT has_function_privilege('public', 'public.{FUNCTION}', 'EXECUTE')")
        assert not await db.fetchval("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'bracket_app'")
        security = await db.fetchval("SELECT prosecdef FROM pg_proc WHERE oid = $1::regprocedure", f"public.{FUNCTION}")
        assert security is False
        assert await db.fetchval("SELECT to_regclass('public.tournament_user_roles')") is None


async def test_069_reapply_is_idempotent_and_keeps_assignments(db):
    assignment = await assign(db)
    before = await db.fetch("SELECT * FROM public.tournament_member_roles ORDER BY id")
    await apply_migration(db, 69)
    assert await db.fetch("SELECT * FROM public.tournament_member_roles ORDER BY id") == before
    assert [str(row["id"]) for row in before] == [str(assignment)]
    assert await allows(db) is True


async def test_rls_hides_and_rejects_other_organization_rows(db):
    await assign(db)
    await assign(db, OTHER_TOURNAMENT, OTHER_MEMBER, org=OTHER_ORG, user=OTHER_USER, created_by=OTHER_MEMBER)
    async with as_app(db, user=USER):
        rows = await db.fetch("SELECT organization_id::text FROM public.tournament_member_roles")
    assert [row["organization_id"] for row in rows] == [ORG]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await _insert_foreign_org_row(db)


async def _insert_foreign_org_row(db):
    async with as_app(db, user=USER):
        await db.execute(
            "INSERT INTO public.tournament_member_roles (organization_id, tournament_id, organization_user_id, role_code,"
            " created_by_member_id) VALUES ($1, $2, $3, $4, $5)",
            OTHER_ORG, OTHER_TOURNAMENT, OTHER_MEMBER, ROLE, OTHER_MEMBER,
        )


@pytest.mark.parametrize(
    ("tournament", "member"),
    [(OTHER_TOURNAMENT, MEMBER_VIEWER), (TOURNAMENT, OTHER_MEMBER)],
    ids=["torneo-ajeno", "miembro-ajeno"],
)
async def test_cross_organization_tournament_or_member_is_rejected(db, tournament, member):
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await assign(db, tournament, member)


async def test_duplicate_assignment_and_unknown_role_are_rejected(db):
    await assign(db)
    with pytest.raises(asyncpg.UniqueViolationError):
        await assign(db)
    with pytest.raises(asyncpg.CheckViolationError):
        async with as_app(db, user=USER):
            await db.execute(
                "INSERT INTO public.tournament_member_roles (organization_id, tournament_id, organization_user_id, role_code,"
                " created_by_member_id) VALUES ($1, $2, $3, 'tournament_admin', $4)",
                ORG, TOURNAMENT_B, MEMBER_VIEWER, MEMBER,
            )


async def test_app_cannot_update_assignments(db):
    await assign(db)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(db, user=USER):
            await db.execute("UPDATE public.tournament_member_roles SET tournament_id = $1", TOURNAMENT_B)


async def test_assignments_cascade_with_membership_and_tournament(db):
    await assign(db)
    await assign(db, TOURNAMENT_B)
    await assign(db, TOURNAMENT_C)
    await db.execute("DELETE FROM public.tournaments WHERE id = $1", TOURNAMENT_C)
    assert await db.fetchval("SELECT count(*) FROM public.tournament_member_roles") == 2
    await db.execute("DELETE FROM public.organization_users WHERE id = $1", MEMBER_VIEWER)
    assert await db.fetchval("SELECT count(*) FROM public.tournament_member_roles") == 0


async def test_operator_allows_exactly_the_three_permissions_in_assigned_tournament(db):
    for permission in (*GRANTED, *NOT_GRANTED):
        assert await allows(db, permission=permission) is False
    await assign(db)
    for permission in GRANTED:
        assert await allows(db, permission=permission) is True
        assert await allows(db, MATCH_B, permission) is False
    for permission in NOT_GRANTED:
        assert await allows(db, permission=permission) is False


async def test_operator_is_ignored_for_other_users_and_wrong_context(db):
    await assign(db)
    assert await allows(db, user=OTHER_USER) is False
    assert await allows(db, org=OTHER_ORG) is False
    async with as_app(db):
        assert await db.fetchval("SELECT public.tournament_operator_allows($1, $2, $3)", OTHER_ORG, MATCH, GRANTED[0]) is False


SET_ACTIVE = {
    "organization_users": "UPDATE public.organization_users SET is_active = $1 WHERE id = $2",
    "users": "UPDATE public.users SET is_active = $1 WHERE id = $2",
    "organizations": "UPDATE public.organizations SET is_active = $1 WHERE id = $2",
}


@pytest.mark.parametrize("table", list(SET_ACTIVE))
async def test_inactive_member_user_or_organization_loses_and_recovers_the_role(db, table):
    await assign(db)
    target = {"organization_users": MEMBER_VIEWER, "users": USER_VIEWER, "organizations": ORG}[table]
    await db.execute(SET_ACTIVE[table], False, target)
    assert await allows(db) is False
    assert await allows(db, function="match_live_has_permission") is False
    await db.execute(SET_ACTIVE[table], True, target)
    assert await allows(db) is True


async def test_live_permission_includes_tournament_operator(db):
    for permission in ("VIEW_MATCH_LIVE_DRAFT", "OPERATE_MATCH_LIVE"):
        assert await allows(db, permission=permission, function="match_live_has_permission") is False
    await assign(db)
    for permission in ("VIEW_MATCH_LIVE_DRAFT", "OPERATE_MATCH_LIVE", "CLOSE_MATCH_REPORT"):
        assert await allows(db, permission=permission, function="match_live_has_permission") is True
        assert await allows(db, MATCH_B, permission, function="match_live_has_permission") is False
    assert await allows(db, permission="MANAGE_TOURNAMENTS", function="match_live_has_permission") is False


async def test_live_permission_keeps_organization_roles(db):
    assert await allows(db, user=USER, function="match_live_has_permission") is True
    assert await allows(db, MATCH_B, user=USER, function="match_live_has_permission") is True


async def test_sanction_operation_includes_tournament_operator(db):
    assert await can_operate_sanction(db) is False
    assert await can_operate_sanction(db, user=USER) is True
    await assign(db)
    assert await can_operate_sanction(db) is True
    assert await can_operate_sanction(db, MATCH_B) is False
    async with db.transaction():
        await db.execute("DELETE FROM public.tournament_member_roles")
    assert await can_operate_sanction(db) is False
