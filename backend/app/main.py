import asyncio
import json
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from uuid import UUID

import socketio
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.csrf import CSRF_HEADER_NAME, new_csrf_token, validate_csrf_request
from app.core.database import SessionFactory, set_rls_context
from app.core.security import decode_access_token_claims
from app.modules.identity.router import router as identity_router
from app.modules.matches.router import router as matches_router
from app.modules.organizations.router import router as organizations_router
from app.modules.platform.router import router as platform_router
from app.modules.tournaments.router import router as tournaments_router


OUTBOX_CHANNEL = "bracket_craft.events"
PUBLIC_REALTIME_EVENTS = frozenset({"MATCH_CLOSED", "MATCH_UPDATED", "STANDINGS_UPDATED"})
SOCKET_REVALIDATION_SECONDS = 30
settings = get_settings()
allowed_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=allowed_origins,
)
connected_socket_sessions: dict[str, dict[str, str]] = {}


@sio.event
async def connect(sid, environ, auth):
    if not isinstance(auth, dict):
        return False

    organization_value = auth.get("organization_id")
    if organization_value:
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
                role = await db.execute(
                    text("""
                        SELECT 1
                        FROM organization_users ou
                        JOIN organization_user_roles our
                          ON our.organization_user_id = ou.id
                         AND our.organization_id = ou.organization_id
                        WHERE ou.organization_id = :organization_id
                          AND ou.user_id = :user_id
                          AND ou.is_active = TRUE
                        LIMIT 1
                    """),
                    {"organization_id": str(organization_id), "user_id": str(user_id)},
                )
                if role.scalar_one_or_none() is None:
                    return False

        session_metadata = {
            "scope": "organization",
            "user_id": str(user_id),
            "session_id": str(session_id),
            "organization_id": str(organization_id),
        }
        await sio.save_session(sid, session_metadata)
        await sio.enter_room(sid, f"organization:{organization_id}")
        connected_socket_sessions[sid] = session_metadata
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
    return True


@sio.event
async def disconnect(sid):
    connected_socket_sessions.pop(sid, None)


async def _relay_outbox_events():
    while True:
        redis = None
        pubsub = None
        try:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            pubsub = redis.pubsub()
            await pubsub.subscribe(OUTBOX_CHANNEL)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                event = json.loads(message["data"])
                await sio.emit(
                    event["event_type"],
                    event["payload"],
                    room=f"organization:{event['organization_id']}",
                )
                payload = event.get("payload")
                tournament_id = payload.get("tournament_id") if isinstance(payload, dict) else None
                if tournament_id and event["event_type"] in PUBLIC_REALTIME_EVENTS:
                    await sio.emit(
                        event["event_type"],
                        payload,
                        room=f"tournament:{tournament_id}",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(1)
        finally:
            if pubsub is not None:
                await pubsub.aclose()
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
                        else:
                            user_id = UUID(metadata["user_id"])
                            organization_id = UUID(metadata["organization_id"])
                            await set_rls_context(db, organization_id, user_id)
                            result = await db.execute(
                                text("""
                                    SELECT 1
                                    FROM users u
                                    JOIN user_sessions s ON s.user_id = u.id
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
                        is_valid = result.scalar_one_or_none() is not None
                if not is_valid:
                    await sio.disconnect(sid)
            except Exception:
                # A transient database outage must not disconnect every client.
                continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    relay_task = asyncio.create_task(_relay_outbox_events())
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


api = FastAPI(title="Bracket Craft API", version="0.1.0", lifespan=lifespan)


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

    try:
        has_auth_credentials = bool(
            request.headers.get("authorization")
            or request.cookies.get(current_settings.auth_cookie_name)
        )
        is_identity_endpoint = request.url.path.startswith("/api/v1/auth/")
        if has_auth_credentials or is_identity_endpoint or request.method.upper() in {"GET", "HEAD", "OPTIONS", "TRACE"}:
            validate_csrf_request(
                request,
                frozenset(allowed_origins),
                current_settings.csrf_cookie_name,
            )
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
api.include_router(organizations_router, prefix="/api/v1")
api.include_router(platform_router, prefix="/api/v1")
api.include_router(tournaments_router, prefix="/api/v1")
api.include_router(matches_router, prefix="/api/v1")

sio_app = socketio.ASGIApp(sio, other_asgi_app=api)
app = sio_app
