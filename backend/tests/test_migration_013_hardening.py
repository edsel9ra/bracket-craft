"""Migración 013: estado final esperado del endurecimiento (R24, RF-007).

La migración **013** no se puede editar (historial append-only). Reescribió cinco
funciones de plataforma y la vista cruda de formación sustituyendo texto sobre su
definición vigente; cuando el texto no coincide no hace nada y no avisa. Esta
comprobación verifica el **estado final** que debe existir tras aplicar la cadena
de migraciones y falla nombrando la función o la vista incumplidora. La corrección
de una base desviada es siempre una migración nueva (*forward-fix*), nunca editar
la 013.

La suite es opt-in: necesita ``RUN_DATABASE_TESTS=1`` y ``DATABASE_ADMIN_URL``
porque crea bases desechables y aplica DDL.
"""

from __future__ import annotations

import re

import asyncpg
import pytest

from migration_helpers import apply_migration, throwaway_database

EXPECTED_FUNCTIONS = (
    "platform_set_user_active",
    "platform_set_organization_active",
    "platform_set_membership_active",
    "platform_create_membership",
    "requeue_outbox_events",
)

VIEW_NAME = "v_public_match_lineups_unpublished"
EXPECTED_VIEW_ORDER = (
    "ORDER BY tl.match_id, tl.team_id, tl.published_at DESC, "
    "ms.segment_number DESC, tl.id DESC"
)
LEGACY_VIEW_ORDER = (
    "ORDER BY tl.match_id, tl.team_id, ms.segment_number, tl.published_at, tl.id"
)

HARDENED_CALL = re.compile(
    r"fn_platform_actor_role\(\)\s+IS\s+DISTINCT\s+FROM\s+'platform_admin'"
)
UNHARDENED_CALL = re.compile(r"fn_platform_actor_role\(\)\s*<>\s*'platform_admin'")


def normalized(sql: str) -> str:
    return " ".join(sql.split())


def function_violation(name: str, definition: str) -> str | None:
    """Describe why ``name`` is not hardened, naming the function."""

    if UNHARDENED_CALL.search(definition):
        return (
            f"Función de plataforma sin endurecer: {name} conserva "
            "fn_platform_actor_role() <> 'platform_admin' "
            "(se espera IS DISTINCT FROM)"
        )
    if HARDENED_CALL.search(definition) is None:
        return (
            f"Función de plataforma sin endurecer: {name} no contiene "
            "fn_platform_actor_role() IS DISTINCT FROM 'platform_admin'"
        )
    return None


def view_violation(definition: str) -> str | None:
    """Describe why the raw lineup view is not in its expected state."""

    if normalized(EXPECTED_VIEW_ORDER) not in normalized(definition):
        return (
            f"Vista sin el orden esperado: {VIEW_NAME} debe ordenar por "
            "tl.match_id, tl.team_id, tl.published_at DESC, "
            "ms.segment_number DESC, tl.id DESC"
        )
    return None


async def function_definitions(connection: asyncpg.Connection) -> dict[str, str]:
    rows = await connection.fetch(
        """
        SELECT p.proname, pg_get_functiondef(p.oid) AS definition
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname = ANY($1::text[])
        ORDER BY p.proname
        """,
        list(EXPECTED_FUNCTIONS),
    )
    return {row["proname"]: row["definition"] for row in rows}


async def view_definition(connection: asyncpg.Connection) -> str:
    return await connection.fetchval(
        f"SELECT pg_get_viewdef('public.{VIEW_NAME}'::regclass, true)"
    )


async def hardening_violations(connection: asyncpg.Connection) -> list[str]:
    """Return one message per function or view that is not in the expected state."""

    violations: list[str] = []
    definitions = await function_definitions(connection)
    for name in EXPECTED_FUNCTIONS:
        definition = definitions.get(name)
        if definition is None:
            violations.append(f"Función de plataforma ausente: {name}")
            continue
        violation = function_violation(name, definition)
        if violation is not None:
            violations.append(violation)

    view = await view_definition(connection)
    violation = view_violation(view)
    if violation is not None:
        violations.append(violation)
    return violations


async def unhardened_function(connection: asyncpg.Connection, name: str) -> None:
    """Simulate a base where migration 013 did not match the function text."""

    definitions = await function_definitions(connection)
    definition = definitions[name]
    modified = definition.replace(
        "IS DISTINCT FROM 'platform_admin'", "<> 'platform_admin'"
    )
    assert modified != definition
    await connection.execute(modified)


async def legacy_view(connection: asyncpg.Connection) -> None:
    """Simulate a base where the view kept the order from before 013."""

    definition = await view_definition(connection)
    modified = re.sub(
        r"ORDER BY\s+tl\.match_id,\s+tl\.team_id,\s+tl\.published_at\s+DESC,"
        r"\s+ms\.segment_number\s+DESC,\s+tl\.id\s+DESC",
        LEGACY_VIEW_ORDER,
        definition,
        count=1,
    )
    assert modified != definition
    await connection.execute(
        f"CREATE OR REPLACE VIEW public.{VIEW_NAME} "
        f"WITH (security_barrier = true) AS {modified}"
    )


# ---------------------------------------------------------------------------
# Estado final esperado
# ---------------------------------------------------------------------------


async def test_013_hardens_the_five_functions_and_the_view(database_admin_url):
    # Estado de una base ya migrada hasta la 012: la 013 debe endurecer las
    # cinco funciones y reordenar la vista.
    async with throwaway_database(database_admin_url, last=12) as connection:
        await apply_migration(connection, 13)

        assert await hardening_violations(connection) == []


async def test_expected_state_holds_in_the_clean_chain(database_admin_url):
    # Volumen limpio: init + 001..023, sin volver a ejecutar la 013.
    async with throwaway_database(database_admin_url, last=23) as connection:
        assert await hardening_violations(connection) == []


# ---------------------------------------------------------------------------
# La comprobación detecta y nombra la función o la vista incumplidora
# ---------------------------------------------------------------------------


async def test_checker_fails_naming_the_unhardened_function(database_admin_url):
    async with throwaway_database(database_admin_url, last=23) as connection:
        await unhardened_function(connection, "platform_set_membership_active")

        violations = await hardening_violations(connection)

        assert len(violations) == 1
        assert "platform_set_membership_active" in violations[0]
        assert "IS DISTINCT FROM" in violations[0]


async def test_checker_fails_naming_the_view_with_the_wrong_order(database_admin_url):
    async with throwaway_database(database_admin_url, last=23) as connection:
        await legacy_view(connection)

        violations = await hardening_violations(connection)

        assert len(violations) == 1
        assert VIEW_NAME in violations[0]
        assert "orden" in violations[0]
