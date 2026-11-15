"""059 adds bracket_code to the internal selection view; the 14-key public view is unchanged."""

from uuid import uuid4

from migration_helpers import apply_migration, throwaway_database
from test_migration_031 import MEMBER, ORG, SEED_SQL, USER, MATCH
from test_migration_056 import app

SELECTION_COLUMNS = {
    "id", "tournament_id", "stage_id", "group_id", "matchday", "match_date",
    "home_team_id", "home_team_name", "away_team_id", "away_team_name",
    "status", "home_score", "away_score", "is_provisional",
    "clock_segment_number", "clock_elapsed_seconds", "clock_state",
    "clock_observed_at", "bracket_code",
}
PUBLIC_COLUMNS = SELECTION_COLUMNS - {
    "stage_id", "group_id", "matchday", "match_date", "bracket_code",
}
FOREIGN = ORG.replace("31000000", "32000000")


def seeded(code="GF1", foreign_code="FK2"):
    """Seed 031 con bracket_code fijado antes de publicar (estructura protegida)."""
    publish = "UPDATE public.tournament_versions"
    sql = SEED_SQL.replace(
        publish,
        f"UPDATE matches SET bracket_code='{code}' WHERE id='{MATCH}'; {publish}",
    )
    other = SEED_SQL.replace(
        publish,
        f"UPDATE matches SET bracket_code='{foreign_code}'"
        f" WHERE id='{MATCH.replace('31000000', '32000000')}'; {publish}",
    ).replace("31000000", "32000000").replace("migration-031", "migration-059-other")
    return sql, other


async def seed_bracket(db, code="GF1", foreign_code="FK2"):
    sql, other = seeded(code, foreign_code)
    await db.execute(sql)
    await db.execute(other)
    foreign_member = MEMBER.replace("31000000", "32000000")
    for org, member in ((ORG, MEMBER), (FOREIGN, foreign_member)):
        role = await db.fetchval(
            """INSERT INTO roles(organization_id,role_definition_id,name,permissions)
            SELECT $1,id,'Live owner',system_permissions FROM role_definitions
            WHERE code='owner' RETURNING id""",
            org,
        )
        await db.execute(
            "INSERT INTO organization_user_roles(organization_id,organization_user_id,role_id) VALUES ($1,$2,$3)",
            org,
            member,
            role,
        )
    session = uuid4()
    await db.execute(
        "INSERT INTO user_sessions(id,user_id,expires_at) VALUES ($1,$2,'2099-01-01')",
        session,
        USER,
    )
    await db.execute(
        "UPDATE matches SET status='live' WHERE id=ANY($1::uuid[])",
        [MATCH, MATCH.replace("31000000", "32000000")],
    )


async def suspend(db, org=ORG, user=USER, match=MATCH, member=MEMBER):
    async with app(db, org=org, user=user):
        await db.execute(
            "INSERT INTO match_live_state(organization_id,match_id,updated_by_member_id) VALUES ($1,$2,$3)",
            org,
            match,
            member,
        )
        await db.execute("UPDATE matches SET status='suspended' WHERE id=$1", match)


async def test_selection_view_orders_suspended_by_bracket_code(database_admin_url):
    async with throwaway_database(database_admin_url, last=59) as db:
        await seed_bracket(db)
        await suspend(db)
        async with app(db):
            row = await db.fetchrow("SELECT * FROM v_match_live_public_selection")
            assert row["bracket_code"] == "GF1" and row["status"] == "suspended"
            assert set(row.keys()) == SELECTION_COLUMNS
            public = await db.fetchrow("SELECT * FROM v_public_match_live")
            assert set(public.keys()) == PUBLIC_COLUMNS
            assert "bracket_code" not in public.keys()


async def test_selection_view_two_tenants_keep_own_codes(database_admin_url):
    async with throwaway_database(database_admin_url, last=59) as db:
        await seed_bracket(db, code="GF1", foreign_code="FK2")
        await suspend(db)
        await suspend(
            db,
            org=FOREIGN,
            user=USER.replace("31000000", "32000000"),
            match=MATCH.replace("31000000", "32000000"),
            member=MEMBER.replace("31000000", "32000000"),
        )
        rows = await db.fetch(
            "SELECT id, tournament_id, bracket_code FROM v_match_live_public_selection"
        )
        codes = {str(row["id"]): row["bracket_code"] for row in rows}
        assert codes == {
            MATCH: "GF1",
            MATCH.replace("31000000", "32000000"): "FK2",
        }


async def test_059_clean_incremental_idempotent_and_privileges(database_admin_url):
    async with throwaway_database(database_admin_url, last=59) as db:
        assert await db.fetchval(
            "SELECT has_table_privilege('bracket_app','v_match_live_public_selection','SELECT')"
        )
        assert not await db.fetchval(
            "SELECT has_table_privilege('public','v_match_live_public_selection','SELECT')"
        )
        barrier = await db.fetchval(
            "SELECT COALESCE((SELECT reloptions FROM pg_class WHERE oid='v_match_live_public_selection'::regclass)::text LIKE '%security_barrier%')"
        )
        assert barrier
    async with throwaway_database(database_admin_url, last=58) as db:
        await seed_bracket(db)
        await suspend(db)
        async with app(db):
            assert "bracket_code" not in (
                await db.fetchrow("SELECT * FROM v_match_live_public_selection")
            ).keys()
        for _ in range(2):
            await apply_migration(db, 59)
        async with app(db):
            row = await db.fetchrow(
                "SELECT * FROM v_match_live_public_selection ORDER BY id"
            )
            assert row["bracket_code"] == "GF1"
            assert set(row.keys()) == SELECTION_COLUMNS
            assert set(
                (
                    await db.fetchrow(
                        "SELECT * FROM v_public_match_live ORDER BY id"
                    )
                ).keys()
            ) == PUBLIC_COLUMNS
