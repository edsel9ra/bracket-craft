import pytest

from migration_helpers import (
    MEMBER,
    ORG,
    SEED_SQL,
    apply_migration,
    throwaway_database,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_invitation", [False, True])
async def test_remove_reversible_invitation_token(database_admin_url, existing_invitation):
    async with throwaway_database(database_admin_url, last=32) as connection:
        if existing_invitation:
            await connection.execute(SEED_SQL)
            await connection.execute("""
                INSERT INTO public.organization_invitations
                    (organization_id, email, role_code, token_hash, token_encrypted,
                     expires_at, invited_by_member_id)
                VALUES ($1, 'migration-033@example.test', 'viewer', 'stable-token-hash',
                        pgp_sym_encrypt('migration-token', 'test-key'),
                        TIMESTAMPTZ '2099-01-01', $2)
            """, ORG, MEMBER)
            before = await connection.fetchrow("""
                SELECT id, token_hash, status, expires_at FROM public.organization_invitations
            """)
        await apply_migration(connection, 33)
        assert await connection.fetchval("""
            SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'organization_invitations'
              AND column_name = 'token_encrypted'
        """) == 0
        if existing_invitation:
            assert await connection.fetchrow("""
                SELECT id, token_hash, status, expires_at FROM public.organization_invitations
            """) == before
