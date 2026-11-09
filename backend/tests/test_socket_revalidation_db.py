import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.database import set_rls_context
from app.main import _load_role_fingerprint
from test_public_access_matrix import _create_tournament, _publish_tournament


async def batch(db, sessions):
    result = await db.execute(
        text("SELECT sid, is_valid FROM public.revalidate_socket_sessions(CAST(:sockets AS JSONB))"),
        {"sockets": json.dumps(sessions)},
    )
    return {row.sid: row.is_valid for row in result}


async def socket(db, tenant, sid):
    session_id = uuid4()
    await set_rls_context(db, tenant.organization_id, tenant.user_id)
    await db.execute(text("""
        INSERT INTO public.user_sessions (id, user_id, expires_at)
        VALUES (:id, :user_id, CURRENT_TIMESTAMP + INTERVAL '1 hour')
    """), {"id": session_id, "user_id": tenant.user_id})
    return {
        "sid": sid, "scope": "organization", "user_id": str(tenant.user_id),
        "organization_id": str(tenant.organization_id), "session_id": str(session_id),
        "role_fingerprint": await _load_role_fingerprint(db, tenant.organization_id, tenant.user_id),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["revoked", "expired", "session_owner", "membership", "roles", "fingerprint"])
async def test_batch_keeps_tenant_isolation_and_session_semantics(db_session, tenant_factory, invalid):
    first = await tenant_factory()
    a = await socket(db_session, first, "a")
    second = await tenant_factory()
    b = await socket(db_session, second, "b")
    assert await batch(db_session, [a, b]) == {"a": True, "b": True}
    assert await batch(db_session, []) == {}
    if invalid == "revoked":
        await db_session.execute(text("UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE id = :id"), {"id": a["session_id"]})
    elif invalid == "expired":
        # El rol de aplicación solo puede insertar la fecha, no actualizarla.
        a["session_id"] = str(uuid4())
        await db_session.execute(text("""
            INSERT INTO user_sessions (id, user_id, expires_at)
            VALUES (:id, :user_id, CURRENT_TIMESTAMP - INTERVAL '1 hour')
        """), {"id": a["session_id"], "user_id": first.user_id})
    elif invalid == "session_owner":
        a["session_id"] = b["session_id"]
    elif invalid == "fingerprint":
        a["role_fingerprint"] = "changed"
    else:
        await set_rls_context(db_session, first.organization_id, first.user_id)
        if invalid == "membership":
            await db_session.execute(text("UPDATE organization_users SET is_active = FALSE WHERE id = :id"), {"id": first.member_id})
        else:
            await db_session.execute(text("UPDATE roles SET permissions = '[]'::JSONB WHERE organization_id = :id"), {"id": first.organization_id})
    await set_rls_context(db_session, second.organization_id, second.user_id)
    assert await batch(db_session, [a, b]) == {"a": False, "b": True}
    assert (await db_session.execute(text("SELECT current_setting('app.current_organization_id')"))).scalar_one() == str(second.organization_id)


@pytest.mark.asyncio
async def test_public_missing_tournament_and_malformed_socket_do_not_affect_others(db_session, tenant_factory):
    tenant = await tenant_factory()
    valid = await socket(db_session, tenant, "valid")
    assert await batch(db_session, [
        valid,
        {"sid": "public", "scope": "public", "tournament_id": str(uuid4())},
        {"sid": "malformed", "scope": "organization", "user_id": "not-a-uuid"},
    ]) == {"valid": True, "public": False}


@pytest.mark.asyncio
async def test_public_visibility_is_rechecked_independently_of_private_context(db_session, tenant_factory):
    tenant = await tenant_factory()
    tournament_id, version_id, _ = await _create_tournament(db_session, tenant)
    public = {"sid": "public", "scope": "public", "tournament_id": str(tournament_id)}
    private = await socket(db_session, tenant, "private")
    assert await batch(db_session, [private, public]) == {"private": True, "public": False}
    await _publish_tournament(db_session, tournament_id, version_id)
    assert await batch(db_session, [private, public]) == {"private": True, "public": True}
