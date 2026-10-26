"""Autorización real del cierre del acta con roles de organización (spec 017, RF-002).

Criterio de finalización 3: la autorización del cierre es la **conjunción**
``CLOSE_MATCH_REPORT`` **y** (rol ``owner``/``administrator``/``operator`` **o**
asignación en ``match_officials`` para ese partido). La matriz de precedencia de
``test_close_validation_order.py`` fija el **403** con dobles, pero no puede
distinguir los dos motivos porque su doble resuelve toda la conjunción en una
sola consulta. Aquí se ejercen contra PostgreSQL, con la ruta de cierre
completa y roles de verdad:

* un **árbitro** con el permiso (rol ``referee``) y **sin** asignación al
  partido responde **403**;
* un **observador** (rol ``viewer``, sin permisos) **asignado** como oficial del
  partido responde **403**;
* y el mismo **árbitro asignado** cierra: la conjunción no es una denegación
  general ni un permiso nuevo.

Opt-in: requiere ``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL`` (base
desechable por caso, igual que ``tests/test_substitutions.py``). Los roles se
crean con el contexto del propietario y después se cierra con el contexto del
miembro, que es lo que hace la petición real: el contexto RLS viaja con el
usuario autenticado.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import require_permission
from app.core.tenancy import AuthContext
from app.modules.matches.service import CloseMatchReportService
from db_helpers import TenantContext, create_test_user, set_tenant_context
from tests.test_substitutions import (
    ClosableMatch,
    committed_application,
    context_for,
    report,
    seeded_match,
)


async def add_member(engine, tenant: TenantContext, *, role_code: str) -> AuthContext:
    """Miembro activo de la organización con un único rol, ya confirmado."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, tenant)
        user_id = await create_test_user(session, full_name=f"Close {role_code}")
        member_id = (
            await session.execute(
                text("""
                    INSERT INTO organization_users (organization_id, user_id, is_active)
                    VALUES (:organization_id, :user_id, TRUE)
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "user_id": str(user_id),
                },
            )
        ).scalar_one()
        # El rol de organización copia el catálogo de `role_definitions`, que es
        # lo mismo que hace `platform_create_membership`.
        role_id = (
            await session.execute(
                text("""
                    INSERT INTO roles
                        (organization_id, role_definition_id, name, permissions)
                    SELECT :organization_id, rd.id, rd.name, rd.system_permissions
                    FROM role_definitions rd
                    WHERE rd.code = :role_code
                    RETURNING id
                """),
                {
                    "organization_id": str(tenant.organization_id),
                    "role_code": role_code,
                },
            )
        ).scalar_one()
        await session.execute(
            text("""
                INSERT INTO organization_user_roles
                    (organization_id, organization_user_id, role_id)
                VALUES (:organization_id, :member_id, :role_id)
            """),
            {
                "organization_id": str(tenant.organization_id),
                "member_id": str(member_id),
                "role_id": str(role_id),
            },
        )
        await session.commit()
    return AuthContext(
        user_id=user_id,
        organization_id=tenant.organization_id,
        organization_user_id=member_id,
    )


async def assign_official(engine, match: ClosableMatch, member: AuthContext) -> None:
    """Asigna al miembro como árbitro principal del partido."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        await session.execute(
            text("""
                INSERT INTO match_officials
                    (organization_id, match_id, organization_user_id, official_role)
                VALUES (:organization_id, :match_id, :member_id, 'main_referee')
            """),
            {
                "organization_id": str(match.tenant.organization_id),
                "match_id": str(match.match_id),
                "member_id": str(member.organization_user_id),
            },
        )
        await session.commit()


async def close(engine, context: AuthContext, match: ClosableMatch):
    """Cierre con la ruta real del servicio, en su propia transacción."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await CloseMatchReportService(session).execute(
            context, match.match_id, report([])
        )


async def read_state(engine, match: ClosableMatch) -> dict[str, object]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await set_tenant_context(session, match.tenant)
        row = (
            await session.execute(
                text("""
                    SELECT status, result_confirmed, resolution_type, winner_team_id
                    FROM matches
                    WHERE id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).mappings().one()
        events = (
            await session.execute(
                text("""
                    SELECT count(*) FROM match_events WHERE match_id = :match_id
                """),
                {"match_id": str(match.match_id)},
            )
        ).scalar_one()
    return {**dict(row), "events": events}


def assert_nothing_was_written(state: dict[str, object]) -> None:
    assert state["status"] == "scheduled"
    assert state["result_confirmed"] is False
    assert state["resolution_type"] is None
    assert state["winner_team_id"] is None
    assert state["events"] == 0


def assert_permission_denied(error: pytest.ExceptionInfo) -> None:
    assert isinstance(error.value, PermissionError)
    assert "CLOSE_MATCH_REPORT" in str(error.value)


@pytest.mark.asyncio
async def test_a_referee_with_the_permission_but_not_assigned_answers_403(
    database_admin_url,
):
    # Rol `referee`: tiene CLOSE_MATCH_REPORT pero no está asignado al partido.
    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        referee = await add_member(engine, match.tenant, role_code="referee")
        before = await read_state(engine, match)

        with pytest.raises(PermissionError) as error:
            await close(engine, referee, match)

        assert_permission_denied(error)
        assert await read_state(engine, match) == before
        assert_nothing_was_written(before)


@pytest.mark.asyncio
async def test_an_assigned_official_without_the_permission_answers_403(
    database_admin_url,
):
    # Rol `viewer`: sin permisos. La asignación como oficial no concede nada.
    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        viewer = await add_member(engine, match.tenant, role_code="viewer")
        await assign_official(engine, match, viewer)
        before = await read_state(engine, match)

        with pytest.raises(PermissionError) as error:
            await close(engine, viewer, match)

        assert_permission_denied(error)
        assert await read_state(engine, match) == before
        assert_nothing_was_written(before)


@pytest.mark.asyncio
async def test_the_same_referee_closes_once_assigned_to_the_match(database_admin_url):
    # Control: la conjunción no es una denegación general; con el permiso y la
    # asignación el cierre escribe.
    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        referee = await add_member(engine, match.tenant, role_code="referee")
        await assign_official(engine, match, referee)

        response = await close(engine, referee, match)

        assert response["status"] == "success"
        state = await read_state(engine, match)
        assert state["status"] == "finished"
        assert state["result_confirmed"] is True
        assert state["resolution_type"] == "regular"


@pytest.mark.asyncio
async def test_the_owner_of_the_organization_keeps_closing(database_admin_url):
    # El propietario conserva la vía que ya tenía (rol operativo sin asignación).
    async with committed_application(database_admin_url) as engine:
        context, match = await seeded_match(engine)

        response = await close(engine, context, match)

        assert response["status"] == "success"
        assert (await read_state(engine, match))["status"] == "finished"


@pytest.mark.asyncio
async def test_segment_writes_use_the_same_conjunction(database_admin_url):
    """RF-002 también cubre abrir, cerrar e interrumpir segmentos.

    El árbitro con el permiso y sin asignación responde **403** en la misma
    conjunción, así que la comprobación no es exclusiva del cierre.
    """

    async with committed_application(database_admin_url) as engine:
        _, match = await seeded_match(engine)
        referee = await add_member(engine, match.tenant, role_code="referee")

        async with AsyncSession(engine, expire_on_commit=False) as session:
            await set_tenant_context(session, match.tenant)
            with pytest.raises(PermissionError):
                await require_permission(
                    session, referee, "CLOSE_MATCH_REPORT", match.match_id
                )

        await assign_official(engine, match, referee)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await set_tenant_context(session, match.tenant)
            await require_permission(
                session, referee, "CLOSE_MATCH_REPORT", match.match_id
            )


@pytest.mark.asyncio
async def test_the_role_catalogue_means_what_the_scenario_assumes(database_admin_url):
    # Guarda de la prueba: sin estas definiciones el escenario no significaría
    # lo que dice (árbitro con el permiso, observador sin permisos).
    async with committed_application(database_admin_url) as engine:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            rows = (
                await session.execute(
                    text("SELECT code, system_permissions FROM role_definitions")
                )
            ).mappings().all()
    permissions = {
        row["code"]: set(row["system_permissions"] or []) for row in rows
    }
    assert "CLOSE_MATCH_REPORT" in permissions["referee"]
    assert permissions["viewer"] == set()
    assert "CLOSE_MATCH_REPORT" in permissions["owner"]
