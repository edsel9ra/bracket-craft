import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_active_session_revocation_has_a_user_index(db_session):
    result = await db_session.execute(text("""
        SELECT pg_get_indexdef(i.indexrelid) AS definition,
               pg_get_expr(i.indpred, i.indrelid) AS predicate
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        WHERE i.indrelid = 'public.user_sessions'::regclass
          AND c.relname = 'idx_user_sessions_active'
          AND i.indisvalid AND i.indisready
    """))
    index = result.mappings().one()
    assert "(user_id, expires_at)" in index["definition"]
    assert index["predicate"] == "(revoked_at IS NULL)"
