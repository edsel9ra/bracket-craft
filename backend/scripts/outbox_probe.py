"""Sonda de outbox para la verificación operativa del worker (spec 011, RF-003).

Utilidad **operativa**, no de producto: inserta un evento de outbox inocuo con
un marcador único por corrida, informa de su estado y lo borra. La orquesta
``infra/scripts/verify_worker_loop_health.sh`` dentro del contenedor del worker
y solo funciona en desarrollo/local (``APP_ENV`` de la configuración efectiva
del propio worker).

Propiedades deliberadas:

- Usa el **rol de aplicación** (``SessionFactory`` con ``DATABASE_URL``) y fija
  el contexto de aislamiento (RLS) con ``set_rls_context`` en la misma
  transacción; nunca importa ni usa ``DATABASE_ADMIN_URL``.
- Resuelve la organización y el usuario demo por su clave de negocio —correo del
  dueño y ``slug`` de la organización— recorriendo ``list_user_organizations()``,
  el mismo camino que la API.
- El evento ``VERIFICATION_OUTBOX_PROBE`` no tiene handler de dominio ni
  consumidor que lo interprete: el worker lo publica en el stream y lo marca
  como ``processed``, que es el efecto observable.
- Las funciones puras reciben el instante por parámetro y no leen el reloj; el
  borde (``current_probe_marker`` y el script) toma la hora y el azar.

Códigos de salida: ``0`` éxito, ``1`` fallo (escritura, fila ausente o no
borrada) y ``2`` no ejecutable (entorno distinto de desarrollo/local o datos
demo ausentes). No existe ninguna opción para forzar el paso.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEVELOPMENT_ENVS, get_settings
from app.core.database import SessionFactory, set_rls_context
from app.core.outbox import OUTBOX_STREAM

DEMO_USER_EMAIL = "demo.owner@bracketcraft.dev"
DEMO_ORGANIZATION_SLUG = "demo-federation"

PROBE_EVENT_TYPE = "VERIFICATION_OUTBOX_PROBE"
PROBE_VERIFICATION = "spec-011"
PROBE_RETRYING = "retrying"
PROBE_PROCESSED = "processed"
PROBE_FAILED = "failed"
PROBE_MISSING = "missing"

STREAM_LOOKBACK_ENTRIES = 1000
ERROR_DETAIL_LIMIT = 200

DEMO_USER_SQL = "SELECT id FROM users WHERE LOWER(email) = :email"
DEMO_ORGANIZATIONS_SQL = "SELECT id, slug, organization_user_id FROM list_user_organizations()"
INSERT_PROBE_SQL = """
    INSERT INTO outbox_events (organization_id, event_type, payload)
    VALUES (:organization_id, :event_type, CAST(:payload AS JSONB))
    RETURNING id
"""
SELECT_PROBE_SQL = """
    SELECT id, status, attempts, processed_at, last_error
    FROM outbox_events
    WHERE id = :id AND payload->>'marker' = :marker
"""
DELETE_PROBE_SQL = """
    DELETE FROM outbox_events
    WHERE id = :id AND payload->>'marker' = :marker
    RETURNING id
"""


class ProbeError(Exception):
    """Fallo de la sonda: se informa y termina con código 1."""


class ProbeNotExecutableError(ProbeError):
    """Entorno distinto de desarrollo/local o datos demo ausentes: código 2."""


class ProbeRowMissingError(ProbeError):
    """La fila de la sonda no existe para su identificador y marcador."""


@dataclass(frozen=True)
class DemoTenant:
    """Organización y usuario demo ya sembrados, con su membresía activa."""

    organization_id: UUID
    user_id: UUID
    member_id: UUID


def environment_allows_probe(app_env: str | None) -> bool:
    """Return whether ``app_env`` is one of the development environments.

    ``DEVELOPMENT_ENVS`` is the single source of truth; ``None``, an empty value
    or anything unknown is rejected.
    """

    if app_env is None:
        return False
    return app_env.lower().strip() in DEVELOPMENT_ENVS


def probe_marker(epoch_seconds: int, pid: int, random_hex: str) -> str:
    """Build the unique per-run marker from its three inputs."""

    return f"worker-probe-{epoch_seconds}-{pid}-{random_hex}"


def current_probe_marker() -> str:
    """Take the clock, the process id and the randomness at the edge."""

    return probe_marker(int(time.time()), os.getpid(), os.urandom(4).hex())


def classify_probe(row: Mapping[str, Any] | None) -> str:
    """Classify a probe row without reading the clock.

    ``pending`` and ``processing`` mean the worker can still take or retry the
    event, so the verification keeps waiting; only ``processed`` is success and
    ``failed`` is an immediate failure. A missing row is ``missing``.
    """

    if row is None:
        return PROBE_MISSING
    status = row.get("status")
    if status == PROBE_PROCESSED:
        return PROBE_PROCESSED
    if status == PROBE_FAILED:
        return PROBE_FAILED
    # ``pending``, ``processing`` y cualquier estado inesperado: sin evidencia de
    # éxito ni de fallo se sigue esperando, y el presupuesto acota la espera.
    return PROBE_RETRYING


def probe_deadline(inserted_at: float, timeout_seconds: float) -> float:
    """Return the instant at which the probe budget is consumed."""

    return inserted_at + timeout_seconds


def probe_exhausted(now: float, deadline: float) -> bool:
    """Return whether the injected instant reached the deadline."""

    return now >= deadline


def one_line(value: Any, limit: int = ERROR_DETAIL_LIMIT) -> str:
    """Flatten a value into a single bounded line for diagnostics."""

    if value is None:
        return "-"
    flattened = " ".join(str(value).split())
    return flattened[:limit] or "-"


def run_guard(app_env: str | None) -> str:
    """Return the ``APP_ENV`` line or reject with a typed error.

    It is the environment gate: outside development/local it raises before any
    session, statement or file is opened.
    """

    effective = (app_env or "").strip()
    if not environment_allows_probe(effective):
        shown = effective or "<vacío>"
        raise ProbeNotExecutableError(
            f"APP_ENV={shown} no es desarrollo/local; no ejecutable"
        )
    return f"APP_ENV={effective.lower()}"


def current_app_env() -> str | None:
    """Read ``APP_ENV`` from the effective configuration of the process."""

    return get_settings().app_env


def _require_environment(app_env: str | None) -> None:
    """Repeat the guard before every command (defence in depth)."""

    run_guard(app_env)


def _validate_marker(marker: str) -> str:
    stripped = marker.strip()
    if not stripped:
        raise ProbeError("el marcador de la sonda no puede estar vacío")
    return stripped


async def resolve_demo_tenant(session: AsyncSession) -> DemoTenant:
    """Resolve the demo organization and owner by business key.

    The path mirrors the API: read the owner's ``users`` row (the only granted
    column set), set the RLS context with the user only, list the user's
    organizations and pick the demo ``slug``, then fix the full context so the
    tenant policies accept the probe.
    """

    result = await session.execute(text(DEMO_USER_SQL), {"email": DEMO_USER_EMAIL})
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise ProbeNotExecutableError(
            f"no existe el usuario demo {DEMO_USER_EMAIL}; no ejecutable"
        )

    await set_rls_context(session, None, user_id)
    organizations = (
        await session.execute(text(DEMO_ORGANIZATIONS_SQL))
    ).mappings().all()
    demo = next(
        (row for row in organizations if row["slug"] == DEMO_ORGANIZATION_SLUG), None
    )
    if demo is None:
        raise ProbeNotExecutableError(
            "el usuario demo no es miembro activo de la organización demo; no ejecutable"
        )

    await set_rls_context(session, demo["id"], user_id)
    return DemoTenant(
        organization_id=demo["id"],
        user_id=user_id,
        member_id=demo["organization_user_id"],
    )


async def insert_probe(marker: str) -> UUID:
    """Insert the probe event and return its identifier."""

    payload = json.dumps({"marker": marker, "verification": PROBE_VERIFICATION})
    async with SessionFactory() as session:
        async with session.begin():
            tenant = await resolve_demo_tenant(session)
            result = await session.execute(
                text(INSERT_PROBE_SQL),
                {
                    "organization_id": str(tenant.organization_id),
                    "event_type": PROBE_EVENT_TYPE,
                    "payload": payload,
                },
            )
            return result.scalar_one()


async def read_probe(probe_id: UUID, marker: str) -> Mapping[str, Any] | None:
    """Read the probe row by identifier and marker under the tenant context."""

    async with SessionFactory() as session:
        async with session.begin():
            await resolve_demo_tenant(session)
            result = await session.execute(
                text(SELECT_PROBE_SQL), {"id": str(probe_id), "marker": marker}
            )
            return result.mappings().one_or_none()


async def delete_probe(probe_id: UUID, marker: str) -> bool:
    """Delete the probe row by identifier and marker; report whether it existed."""

    async with SessionFactory() as session:
        async with session.begin():
            await resolve_demo_tenant(session)
            result = await session.execute(
                text(DELETE_PROBE_SQL), {"id": str(probe_id), "marker": marker}
            )
            return result.scalar_one_or_none() is not None


async def stream_contains(probe_id: UUID) -> bool | None:
    """Look for the event at the tail of the stream; ``None`` when unreachable.

    The stream is best effort: the corroboration is informative and never
    decides the verdict.
    """

    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        entries = await redis.xrevrange(
            OUTBOX_STREAM, count=STREAM_LOOKBACK_ENTRIES
        )
    except (RedisError, OSError):
        return None
    finally:
        await redis.aclose()

    expected = str(probe_id)
    for _entry_id, fields in entries:
        raw = fields.get("event")
        if not raw:
            continue
        try:
            published = json.loads(raw)
        except ValueError:
            continue
        if isinstance(published, dict) and published.get("event_id") == expected:
            return True
    return False


def _format_status(row: Mapping[str, Any] | None, stream: str) -> str:
    state = classify_probe(row)
    if row is None:
        return f"status={state} attempts=0 processed_at=- stream={stream}"
    processed_at = row.get("processed_at")
    processed = processed_at.isoformat() if processed_at is not None else "-"
    line = (
        f"status={state} attempts={row.get('attempts', 0)} "
        f"processed_at={processed} stream={stream}"
    )
    if row.get("last_error") is not None:
        line = f"{line} last_error={one_line(row.get('last_error'))}"
    return line


async def _run_insert(marker: str) -> int:
    probe_id = await insert_probe(marker)
    print(f"{probe_id} {marker}")
    return 0


async def _run_status(probe_id: UUID, marker: str) -> int:
    row = await read_probe(probe_id, marker)
    stream: str
    if row is None:
        stream = "not-found"
    else:
        found = await stream_contains(probe_id)
        stream = "unknown" if found is None else ("found" if found else "not-found")
    print(_format_status(row, stream))
    return 0 if row is not None else 1


async def _run_delete(probe_id: UUID, marker: str) -> int:
    deleted = await delete_probe(probe_id, marker)
    print(f"deleted={1 if deleted else 0}")
    if not deleted:
        raise ProbeRowMissingError(
            f"no se pudo borrar la sonda id={probe_id} marcador={marker}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.outbox_probe",
        description=(
            "Sonda de outbox de la verificación operativa del worker (solo "
            "desarrollo/local)."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("guard", help="comprueba APP_ENV sin escribir nada")

    insert = subcommands.add_parser("insert", help="inserta la sonda y devuelve su id")
    insert.add_argument("--marker", required=True)

    status = subcommands.add_parser("status", help="informa del estado de la sonda")
    status.add_argument("--id", required=True, type=UUID)
    status.add_argument("--marker", required=True)

    delete = subcommands.add_parser("delete", help="borra la sonda")
    delete.add_argument("--id", required=True, type=UUID)
    delete.add_argument("--marker", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "guard":
            print(run_guard(current_app_env()))
            return 0

        _require_environment(current_app_env())
        marker = _validate_marker(args.marker)
        if args.command == "insert":
            return asyncio.run(_run_insert(marker))
        if args.command == "status":
            return asyncio.run(_run_status(args.id, marker))
        return asyncio.run(_run_delete(args.id, marker))
    except ProbeNotExecutableError as exc:
        print(f"no ejecutable: {exc}", file=sys.stderr)
        return 2
    except ProbeError as exc:
        print(f"fallo: {exc}", file=sys.stderr)
        return 1
    except (SQLAlchemyError, RedisError, OSError) as exc:
        print(f"fallo: {one_line(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
