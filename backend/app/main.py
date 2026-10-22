import asyncio
import json
import logging
import tomllib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from http.cookies import SimpleCookie
from pathlib import Path
from uuid import UUID, uuid4

import socketio
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeoutError

from app.core.config import get_settings
from app.core.csrf import (
    CSRF_HEADER_NAME,
    new_csrf_token,
    validate_csrf_token,
    validate_request_origin,
)
from app.core.database import (
    SessionFactory,
    log_database_configuration,
    set_rls_context,
    validate_application_role,
)
from app.core.outbox import OUTBOX_STREAM
from app.core.security import decode_access_token_claims
from app.modules.identity.router import router as identity_router
from app.modules.invitations.errors import InvitationConflict, conflict_body
from app.modules.invitations.router import router as invitations_router
from app.modules.matches.router import router as matches_router
from app.modules.organizations.router import router as organizations_router
from app.modules.platform.router import router as platform_router
from app.modules.tournaments.router import router as tournaments_router


PUBLIC_REALTIME_EVENTS = frozenset({"MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED"})
RESYNC = "RESYNC"
SOCKET_REVALIDATION_SECONDS = 30
RELAY_RETRY_SECONDS = 1
# nginx-style "client closed request": no body, no domain result. A disconnected
# client never receives it, but the connection is closed without running the
# handler or writing anything.
CLIENT_CLOSED_REQUEST = 499
VALIDATION_ERROR_FIELDS = ("type", "loc", "msg")
logger = logging.getLogger(__name__)
settings = get_settings()
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _product_version() -> str:
    """Lee la versión única del producto desde los metadatos del backend.

    Es la única fuente: no se repite como literal ni se toma de
    ``engine_version`` (versión del contrato de reglas, que es otra).
    """

    with PYPROJECT_PATH.open("rb") as pyproject:
        return tomllib.load(pyproject)["project"]["version"]


PRODUCT_VERSION = _product_version()
allowed_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=allowed_origins,
)
connected_socket_sessions: dict[str, dict[str, str]] = {}


async def _load_role_fingerprint(db, organization_id: UUID, user_id: UUID) -> str | None:
    result = await db.execute(
        text("""
            SELECT md5(
                string_agg(
                    effective_roles.scope
                        || ':' || effective_roles.role_id::TEXT
                        || ':' || COALESCE(effective_roles.code, '')
                        || ':' || effective_roles.permissions::TEXT
                        || ':' || COALESCE(effective_roles.system_permissions::TEXT, '[]'),
                    ',' ORDER BY effective_roles.scope, effective_roles.role_id::TEXT
                )
            )
            FROM (
                SELECT
                    'organization'::TEXT AS scope,
                    r.id AS role_id,
                    rd.code,
                    r.permissions,
                    rd.system_permissions
                FROM public.organization_users ou
                JOIN public.organization_user_roles our
                  ON our.organization_user_id = ou.id
                 AND our.organization_id = ou.organization_id
                JOIN public.roles r
                  ON r.id = our.role_id
                 AND r.organization_id = our.organization_id
                LEFT JOIN public.role_definitions rd
                  ON rd.id = r.role_definition_id
                WHERE ou.organization_id = :organization_id
                  AND ou.user_id = :user_id
                  AND ou.is_active = TRUE

            ) AS effective_roles
        """),
        {"organization_id": str(organization_id), "user_id": str(user_id)},
    )
    return result.scalar_one_or_none()


@sio.event
async def connect(sid, environ, auth):
    if not isinstance(auth, dict):
        return False

    organization_value = auth.get("organization_id")
    if organization_value and not auth.get("tournament_id"):
        try:
            token = auth.get("token")
            if not token:
                cookies = SimpleCookie(environ.get("HTTP_COOKIE", ""))
                token_cookie = cookies.get(settings.auth_cookie_name)
                token = token_cookie.value if token_cookie else None
            claims = decode_access_token_claims(token)
            user_id = UUID(claims["sub"])
            session_id = UUID(claims["jti"])
            organization_id = UUID(str(organization_value))
        except Exception:
            return False

        async with SessionFactory() as db:
            async with db.begin():
                await set_rls_context(db, organization_id, user_id)
                session = await db.execute(
                    text("""
                        SELECT 1
                        FROM users u
                        JOIN user_sessions s ON s.user_id = u.id
                        WHERE u.id = :user_id
                          AND u.is_active = TRUE
                          AND s.id = :session_id
                          AND s.revoked_at IS NULL
                          AND s.expires_at > CURRENT_TIMESTAMP
                    """),
                    {"user_id": str(user_id), "session_id": str(session_id)},
                )
                if session.scalar_one_or_none() is None:
                    return False
                membership = await db.execute(
                    text("SELECT fn_verify_user_org_membership(:organization_id)"),
                    {"organization_id": str(organization_id)},
                )
                if not membership.scalar_one():
                    return False
                role_fingerprint = await _load_role_fingerprint(db, organization_id, user_id)
                if role_fingerprint is None:
                    return False

        session_metadata = {
            "scope": "organization",
            "user_id": str(user_id),
            "session_id": str(session_id),
            "organization_id": str(organization_id),
            "role_fingerprint": role_fingerprint,
        }
        await sio.save_session(sid, session_metadata)
        await sio.enter_room(sid, f"organization:{organization_id}")
        connected_socket_sessions[sid] = session_metadata
        await emit_join_resync(sid)
        return True

    tournament_value = auth.get("tournament_id")
    if not tournament_value:
        return False
    try:
        tournament_id = UUID(str(tournament_value))
    except (TypeError, ValueError):
        return False

    async with SessionFactory() as db:
        async with db.begin():
            public_tournament = await db.execute(
                text("SELECT 1 FROM v_public_tournaments WHERE id = :tournament_id"),
                {"tournament_id": str(tournament_id)},
            )
            if public_tournament.scalar_one_or_none() is None:
                return False

    session_metadata = {"scope": "public", "tournament_id": str(tournament_id)}
    await sio.save_session(sid, session_metadata)
    await sio.enter_room(sid, f"tournament:{tournament_id}")
    connected_socket_sessions[sid] = session_metadata
    await emit_join_resync(sid)
    return True


@sio.event
async def disconnect(sid):
    connected_socket_sessions.pop(sid, None)


@dataclass(frozen=True)
class ParsedEvent:
    event_id: str | None
    organization_id: str
    event_type: str
    payload: dict


@dataclass
class RelayState:
    position: str | None = None
    run_id: str | None = None
    started: bool = False


def _stream_id_parts(value: str) -> tuple[int, int]:
    milliseconds, _, sequence = value.partition("-")
    return int(milliseconds), int(sequence or 0)


def stream_id_gt(left: str, right: str) -> bool:
    """Compara ids de stream por ``(ms, seq)``, no como cadenas."""

    return _stream_id_parts(left) > _stream_id_parts(right)


def _delivery_identifier(value) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_envelope(fields) -> ParsedEvent | None:
    """Valida el sobre del stream y resuelve el identificador de entrega.

    Precedencia: ``event_id`` válido, luego ``id`` legado, luego ausente.
    Un sobre malformado devuelve ``None`` y el relay lo omite.
    """

    if not isinstance(fields, dict):
        return None
    try:
        event = json.loads(fields["event"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(event, dict):
        return None

    event_type = event.get("event_type")
    organization_id = event.get("organization_id")
    payload = event.get("payload")
    if not isinstance(event_type, str) or not event_type:
        return None
    if not isinstance(organization_id, str) or not organization_id:
        return None
    if not isinstance(payload, dict):
        return None

    event_id = _delivery_identifier(event.get("event_id"))
    legacy_id = _delivery_identifier(event.get("id"))
    if event_id is None:
        event_id = legacy_id
        if event_id is None:
            # Compatibilidad: sin identificador el evento se reenvía igual.
            logger.warning(
                "Sobre del outbox sin event_id válido; se reenvía sin identificador"
            )
    elif legacy_id is not None and legacy_id != event_id:
        # La anomalía no incluye el sobre ni el payload.
        logger.warning("Sobre del outbox con event_id e id distintos; se usa event_id")

    return ParsedEvent(
        event_id=event_id,
        organization_id=organization_id,
        event_type=event_type,
        payload=payload,
    )


def build_realtime_payload(payload: dict, event_id: str | None) -> dict:
    """Copia el payload de dominio y fija el ``event_id`` del servidor."""

    realtime_payload = {
        key: value for key, value in payload.items() if key != "event_id"
    }
    if event_id is not None:
        realtime_payload["event_id"] = event_id
    return realtime_payload


async def emit_domain_event(event: ParsedEvent) -> None:
    payload = build_realtime_payload(event.payload, event.event_id)
    await sio.emit(
        event.event_type,
        payload,
        room=f"organization:{event.organization_id}",
    )
    tournament_id = event.payload.get("tournament_id")
    if tournament_id and event.event_type in PUBLIC_REALTIME_EVENTS:
        await sio.emit(
            event.event_type,
            payload,
            room=f"tournament:{tournament_id}",
        )


def new_resync_event_id() -> str:
    return f"resync:{uuid4()}"


def resync_rooms(sessions: dict[str, dict]) -> list[str]:
    """Deriva y deduplica las salas con sockets conectados y alcance conocido."""

    rooms: list[str] = []
    seen: set[str] = set()
    for metadata in sessions.values():
        if not isinstance(metadata, dict):
            continue
        scope = metadata.get("scope")
        if scope == "organization":
            scope_id = metadata.get("organization_id")
            room = f"organization:{scope_id}" if scope_id else None
        elif scope == "public":
            scope_id = metadata.get("tournament_id")
            room = f"tournament:{scope_id}" if scope_id else None
        else:
            room = None
        if room and room not in seen:
            seen.add(room)
            rooms.append(room)
    return rooms


async def emit_gap_resync(reason: str, sessions: dict[str, dict] | None = None) -> None:
    """Emite ``RESYNC`` a cada sala conectada; sin salas no emite nada."""

    current_sessions = connected_socket_sessions if sessions is None else sessions
    rooms = resync_rooms(current_sessions)
    if not rooms:
        return
    payload = {"event_id": new_resync_event_id(), "reason": reason}
    for room in rooms:
        try:
            await sio.emit(RESYNC, payload, room=room)
        except Exception:
            logger.exception("No se pudo emitir RESYNC %s en %s", reason, room)


async def emit_join_resync(sid: str) -> None:
    """Emite ``RESYNC`` ``JOIN`` solo al socket que acaba de entrar en su sala."""

    if sid not in connected_socket_sessions:
        return
    payload = {"event_id": new_resync_event_id(), "reason": "JOIN"}
    try:
        await sio.emit(RESYNC, payload, to=sid)
    except Exception:
        logger.exception("No se pudo emitir RESYNC JOIN al socket %s", sid)


def parse_run_id(info) -> str | None:
    if isinstance(info, dict):
        run_id = info.get("run_id")
        return run_id if isinstance(run_id, str) and run_id else None
    if isinstance(info, str):
        for line in info.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() == "run_id":
                run_id = value.strip()
                return run_id or None
    return None


async def read_run_id(redis) -> str | None:
    try:
        info = await redis.info("server")
    except Exception:
        logger.warning(
            "INFO server no disponible; se usan solo las comprobaciones de posición"
        )
        return None
    run_id = parse_run_id(info)
    if run_id is None:
        logger.warning(
            "INFO server sin run_id; se usan solo las comprobaciones de posición"
        )
    return run_id


async def resolve_first(redis) -> str | None:
    entries = await redis.xrange(OUTBOX_STREAM, count=1)
    if not entries:
        return None
    return entries[0][0]


async def resolve_tail(redis) -> str | None:
    entries = await redis.xrevrange(OUTBOX_STREAM, count=1)
    if not entries:
        return None
    return entries[0][0]


async def relay_cycle(
    redis,
    state: RelayState,
    emit,
    emit_resync=None,
    current_run_id: str | None = None,
) -> RelayState:
    """Una iteración del relay: comprueba continuidad y lee entradas.

    El arranque de un proceso nuevo fija la posición en el último id y no
    reemite el histórico ni emite ``RESYNC`` por el mero arranque. En los
    ciclos posteriores y tras reconectar detecta recorte, reinicio de datos de
    Redis y una posición inalcanzable; en ese caso emite ``RESYNC`` y salta al
    final sin reemitir el backlog retenido.
    """

    if not state.started:
        state.run_id = current_run_id
        state.position = await resolve_tail(redis)
        state.started = True
    else:
        if current_run_id is None:
            # ``INFO server`` no disponible: solo comprobaciones de posición.
            pass
        elif state.run_id is None:
            state.run_id = current_run_id
        elif current_run_id != state.run_id:
            state.run_id = current_run_id
            state.position = await resolve_tail(redis)
            if emit_resync is not None:
                await emit_resync("REDIS_RESET")
            return state

        first = await resolve_first(redis)
        last = await resolve_tail(redis)
        if state.position is not None:
            reason = None
            if first is None:
                # Redis perdió los datos: había una posición y ya no hay stream.
                reason = "REDIS_RESET"
            elif stream_id_gt(first, state.position):
                # El recorte eliminó entradas que el relay aún no había leído.
                reason = "STREAM_TRIMMED"
            elif last is None or stream_id_gt(state.position, last):
                reason = "REDIS_RESET"
            if reason is not None:
                state.position = last
                if emit_resync is not None:
                    await emit_resync(reason)
                return state

    messages = await redis.xread(
        {OUTBOX_STREAM: state.position or "0-0"},
        count=100,
        block=1000,
    )
    if not messages:
        return state

    for _, entries in messages:
        for entry_id, fields in entries:
            if state.position is not None and not stream_id_gt(entry_id, state.position):
                continue
            event = parse_envelope(fields)
            if event is not None:
                await emit(event)
            # Avance por entrada: si ``emit`` falla, la relectura repite como
            # máximo esta última entrada.
            state.position = entry_id
    return state


async def relay_loop(redis_factory=Redis.from_url, stop: asyncio.Event | None = None) -> None:
    # Cada réplica de la API lee el stream para sus propios clientes.
    state = RelayState()
    if connected_socket_sessions:
        # Reinicio de la tarea con clientes ya conectados: cubre la ventana
        # en la que el relay no estuvo leyendo.
        await emit_gap_resync("RELAY_START", connected_socket_sessions)
    while stop is None or not stop.is_set():
        redis = None
        try:
            redis = redis_factory(settings.redis_url, decode_responses=True)
            current_run_id = await read_run_id(redis)
            while stop is None or not stop.is_set():
                await relay_cycle(
                    redis,
                    state,
                    emit_domain_event,
                    emit_gap_resync,
                    current_run_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            if stop is not None and stop.is_set():
                break
            await asyncio.sleep(RELAY_RETRY_SECONDS)
        finally:
            if redis is not None:
                await redis.aclose()


async def _revalidate_socket_sessions():
    while True:
        await asyncio.sleep(SOCKET_REVALIDATION_SECONDS)
        for sid, metadata in list(connected_socket_sessions.items()):
            try:
                async with SessionFactory() as db:
                    async with db.begin():
                        if metadata["scope"] == "public":
                            result = await db.execute(
                                text("SELECT 1 FROM v_public_tournaments WHERE id = :tournament_id"),
                                {"tournament_id": metadata["tournament_id"]},
                            )
                            is_valid = result.scalar_one_or_none() is not None
                        else:
                            user_id = UUID(metadata["user_id"])
                            organization_id = UUID(metadata["organization_id"])
                            await set_rls_context(db, organization_id, user_id)
                            session = await db.execute(
                                text("""
                                    SELECT 1
                                    FROM public.users u
                                    JOIN public.user_sessions s ON s.user_id = u.id
                                    WHERE u.id = :user_id
                                      AND u.is_active = TRUE
                                      AND s.id = :session_id
                                      AND s.revoked_at IS NULL
                                      AND s.expires_at > CURRENT_TIMESTAMP
                                      AND fn_verify_user_org_membership(:organization_id)
                                """),
                                {
                                    "user_id": metadata["user_id"],
                                    "session_id": metadata["session_id"],
                                    "organization_id": metadata["organization_id"],
                                },
                            )
                            if session.scalar_one_or_none() is None:
                                is_valid = False
                            else:
                                role_fingerprint = await _load_role_fingerprint(db, organization_id, user_id)
                                is_valid = role_fingerprint == metadata.get("role_fingerprint")
                if not is_valid:
                    await sio.disconnect(sid)
            except Exception:
                # A transient database outage must not disconnect every client.
                continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    log_database_configuration()
    if settings.app_env.lower().strip() not in {"development", "dev", "local"}:
        await validate_application_role()
    relay_task = asyncio.create_task(relay_loop())
    revalidation_task = asyncio.create_task(_revalidate_socket_sessions())
    try:
        yield
    finally:
        relay_task.cancel()
        revalidation_task.cancel()
        try:
            await relay_task
        except asyncio.CancelledError:
            pass
        try:
            await revalidation_task
        except asyncio.CancelledError:
            pass


api = FastAPI(title="Bracket Craft API", version=PRODUCT_VERSION, lifespan=lifespan)


async def _request_validation_exception_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Reject invalid payloads without echoing the rejected input.

    FastAPI's default 422 includes ``input`` and ``ctx``; both can carry the
    date of birth or the national document. Only ``type``, ``loc`` and ``msg``
    are kept so clients can still map the error to a field.
    """

    errors = [
        {field: error[field] for field in VALIDATION_ERROR_FIELDS if field in error}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": errors},
    )


def _dbapi_sqlstate(exc: DBAPIError) -> str:
    code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    return str(code) if code else "desconocido"


async def _dbapi_exception_handler(_request: Request, exc: DBAPIError) -> JSONResponse:
    """Answer an unhandled database error without leaking the failing row.

    Only the SQLSTATE is logged. Neither ``str(exc)`` (which contains the SQL
    statement and parameters) nor the driver message (which may contain the
    failing row) is written to logs or to the response.

    The published-structure trigger raises the stable, user-class SQLSTATE
    ``ZZ409``. It is mapped to 409 by that code only; other database errors
    keep the generic 500 response.
    """

    sqlstate = _dbapi_sqlstate(exc)
    if sqlstate == "ZZ409":
        logger.warning("Conflicto de estructura publicada (SQLSTATE ZZ409)")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "La versión publicada es inmutable"},
        )

    logger.error("Error de base de datos no controlado (SQLSTATE %s)", sqlstate)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Error interno del servidor"},
    )


async def _pool_timeout_exception_handler(
    _request: Request, exc: PoolTimeoutError
) -> JSONResponse:
    """Answer pool exhaustion as a transient capacity error.

    One stable warning is emitted per failed request; the exception message can
    contain the pool size or the SQL, so it is never logged or returned.
    """

    del exc
    logger.warning("Pool de conexiones agotado")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Servicio temporalmente no disponible"},
    )


async def _invitation_conflict_exception_handler(
    _request: Request, exc: InvitationConflict
) -> JSONResponse:
    """Answer an invitation 409 with the stable ``code`` next to ``detail``.

    The handler is registered once for the ``InvitationConflict`` subclass;
    every route keeps raising the domain exception. ``detail`` stays a string
    so existing clients and ``errorMessage`` keep working, and ``code`` is the
    additive identifier the frontend translates.
    """

    return JSONResponse(status_code=exc.status_code, content=conflict_body(exc))


api.add_exception_handler(RequestValidationError, _request_validation_exception_handler)
api.add_exception_handler(InvitationConflict, _invitation_conflict_exception_handler)
api.add_exception_handler(DBAPIError, _dbapi_exception_handler)
api.add_exception_handler(PoolTimeoutError, _pool_timeout_exception_handler)


class BodyBufferResult(Enum):
    """Resultado de leer el cuerpo completo antes de ejecutar el manejador."""

    COMPLETE = "complete"
    TOO_LARGE = "too_large"
    DISCONNECTED = "disconnected"


async def _buffer_request_body(request: Request, max_bytes: int) -> BodyBufferResult:
    """Lee todo el cuerpo y lo deja disponible para el manejador.

    Un cuerpo incompleto por desconexión del cliente no se procesa como
    completo: se devuelve ``DISCONNECTED`` y no se instala un cuerpo parcial.
    """

    body = bytearray()
    while True:
        message = await request.receive()
        message_type = message.get("type")
        if message_type == "http.disconnect":
            return BodyBufferResult.DISCONNECTED
        if message_type != "http.request":
            continue
        body.extend(message.get("body", b""))
        if len(body) > max_bytes:
            return BodyBufferResult.TOO_LARGE
        if not message.get("more_body", False):
            break
    buffered_body = bytes(body)
    # BaseHTTPMiddleware creates a second Request object downstream, so replay
    # the buffered ASGI message instead of relying only on Request._body.
    request._body = buffered_body
    body_sent = False

    async def replay_body():
        nonlocal body_sent
        if body_sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        body_sent = True
        return {"type": "http.request", "body": buffered_body, "more_body": False}

    request._receive = replay_body
    return BodyBufferResult.COMPLETE


@api.middleware("http")
async def csrf_and_request_size_middleware(request: Request, call_next):
    current_settings = get_settings()
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is not None:
        try:
            content_length = int(raw_content_length)
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Content-Length inválido"},
            )
        if content_length < 0 or content_length > current_settings.max_request_body_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"detail": "La solicitud supera el tamaño máximo permitido"},
            )
    body_result = await _buffer_request_body(request, current_settings.max_request_body_bytes)
    if body_result is BodyBufferResult.TOO_LARGE:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"detail": "La solicitud supera el tamaño máximo permitido"},
        )
    if body_result is BodyBufferResult.DISCONNECTED:
        # El cliente abortó a mitad del cuerpo: no se ejecuta el manejador, no
        # se escribe nada y la respuesta de cierre no es un resultado de dominio.
        return Response(status_code=CLIENT_CLOSED_REQUEST)

    try:
        has_auth_credentials = bool(
            request.headers.get("authorization")
            or request.cookies.get(current_settings.auth_cookie_name)
        )
        is_identity_endpoint = request.url.path.startswith("/api/v1/auth/")
        # El origen se valida en toda escritura; el token doble solo cuando la
        # petición lleva credenciales o va a una ruta de identidad.
        validate_request_origin(request, frozenset(allowed_origins))
        if has_auth_credentials or is_identity_endpoint:
            validate_csrf_token(request, current_settings.csrf_cookie_name)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    response = await call_next(request)
    if request.method.upper() != "OPTIONS" and not request.cookies.get(current_settings.csrf_cookie_name):
        response.set_cookie(
            key=current_settings.csrf_cookie_name,
            value=getattr(request.state, "csrf_token", None) or new_csrf_token(),
            max_age=current_settings.csrf_token_ttl_seconds,
            httponly=False,
            secure=current_settings.cookie_secure,
            samesite=current_settings.auth_cookie_samesite,
            path="/",
        )
    return response


api.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Organization-ID", "X-CSRF-Token"],
)


@api.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@api.get("/health/ready")
@api.get("/ready")
async def readiness() -> dict[str, object]:
    checks: dict[str, str] = {}
    try:
        async with SessionFactory() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
    finally:
        await redis.aclose()

    if any(value != "ok" for value in checks.values()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks},
        )
    return {"status": "ready", "checks": checks}


api.include_router(identity_router, prefix="/api/v1")
api.include_router(invitations_router, prefix="/api/v1")
api.include_router(organizations_router, prefix="/api/v1")
api.include_router(platform_router, prefix="/api/v1")
api.include_router(tournaments_router, prefix="/api/v1")
api.include_router(matches_router, prefix="/api/v1")

sio_app = socketio.ASGIApp(sio, other_asgi_app=api)
app = sio_app
