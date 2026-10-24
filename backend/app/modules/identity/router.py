import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.csrf import CSRF_HEADER_NAME, new_csrf_token
from app.core.database import get_db, set_rls_context
from app.core.rate_limit import enforce_rate_limit
from app.core.security import (
    bearer,
    clear_auth_cookie,
    create_user_session,
    decode_access_token_claims,
    get_current_user_id,
    get_optional_current_user_id,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from app.modules.identity.errors import (
    GOOGLE_ALREADY_LINKED,
    GOOGLE_CANCELLED,
    GOOGLE_IDENTITY_INVALID,
    GOOGLE_STATE_INVALID,
    GOOGLE_UNAVAILABLE,
    RATE_LIMITED,
    GoogleAuthError,
)
from app.modules.identity.google_accounts import (
    LinkRejected,
    LoginRejected,
    SessionAccountInvalid,
    link_identity,
    resolve_login,
)
from app.modules.identity.google_claims import (
    parse_identity_claims,
    validate_return_destination,
)
from app.modules.identity.google_provider import (
    ATTEMPT_BUDGET_SECONDS,
    GoogleIdentityInvalid,
    GoogleUnavailable,
    authorization_url,
    exchange_code,
)
from app.modules.identity.google_state import (
    ATTEMPT_TTL_SECONDS,
    GoogleAttempt,
    attempt_is_valid,
    consume_attempt,
    discard_attempt,
    new_state,
    save_attempt,
)
from app.modules.identity.schemas import (
    GoogleLinkStatusResponse,
    GoogleStartRequest,
    GoogleStartResponse,
    GoogleStatusResponse,
    LoginRequest,
    RegisterRequest,
    SessionResponse,
    TokenResponse,
)
from app.modules.organizations.ordering import ordered_organizations


router = APIRouter(prefix="/auth", tags=["identity"])

#: Enlace del intento al navegador (plan D-2). La cookie solo viaja a la ruta
#: del flujo y caduca con el intento; ``SameSite=Lax`` permite el retorno del
#: proveedor como navegación de nivel superior.
OAUTH_STATE_COOKIE = "bc_oauth_state"
OAUTH_STATE_PATH = "/api/v1/auth/google"
OAUTH_STATE_MAX_AGE_SECONDS = ATTEMPT_TTL_SECONDS

#: Texto del rechazo estable del endpoint anterior (RF-3, RNF-9, D-6). No nombra
#: tokens ni datos de cuenta: el cliente usa ``code`` para traducirlo.
RETIRED_GOOGLE_LOGIN_DETAIL = (
    "El inicio de sesión con Google a través de este endpoint ya no está disponible"
)


def _frontend_redirect(settings, path: str, **params: str) -> RedirectResponse:
    """Redirección al frontend que siempre limpia la cookie de estado.

    La ``Location`` solo lleva una ruta interna y códigos del catálogo: nunca
    correo, nombre, sujeto, ``code`` ni ``state`` (RNF-5).
    """

    url = f"{settings.frontend_base_url.rstrip('/')}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(OAUTH_STATE_COOKIE, path=OAUTH_STATE_PATH)
    response.headers["Cache-Control"] = "no-store"
    # El código/estado no debe viajar por `Referer` si API y web comparten origen.
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _error_redirect(settings, code: str) -> RedirectResponse:
    return _frontend_redirect(settings, "/login", error=code)


def _attempt_error_redirect(
    settings, attempt: GoogleAttempt, code: str
) -> RedirectResponse:
    """Error posterior al consumo: la vinculación responde en su pantalla."""

    path = "/account/google" if attempt.flow == "link" else "/login"
    return _frontend_redirect(settings, path, error=code)


async def _revoke_presented_session(db, request: Request, settings) -> None:
    """Revoca solo la sesión presentada por este navegador (D-13, RF-27).

    Se ejecuta tras resolver la cuenta y antes de entregar la cookie nueva. Un
    token ausente, inválido o ya revocado no es un error: no hay nada que
    revocar y el resto de sesiones no se toca.
    """

    raw_token = request.cookies.get(settings.auth_cookie_name)
    if not raw_token:
        return
    try:
        claims = decode_access_token_claims(raw_token)
    except HTTPException:
        return

    async with db.begin():
        await db.execute(
            text("""
                UPDATE public.user_sessions
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE id = :session_id AND revoked_at IS NULL
            """),
            {"session_id": claims["jti"]},
        )


async def _create_organization(db: AsyncSession, name: str, slug: str, user_id: UUID) -> UUID:
    result = await db.execute(
        text("SELECT create_organization_with_owner(:name, :slug, :user_id)"),
        {"name": name, "slug": slug, "user_id": str(user_id)},
    )
    return result.scalar_one()


@router.get("/csrf")
async def csrf_token(request: Request, response: Response) -> dict[str, str]:
    settings = get_settings()
    token = request.cookies.get(settings.csrf_cookie_name) or new_csrf_token()
    request.state.csrf_token = token
    response.headers[CSRF_HEADER_NAME] = token
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": token}


@router.get("/google/status", response_model=GoogleStatusResponse)
async def google_status(response: Response) -> GoogleStatusResponse:
    """Indica si el acceso con Google está configurado (RF-1).

    Es público y solo devuelve el booleano: ni ``client_id``, ni secreto, ni la
    dirección de retorno llegan al navegador.
    """

    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    return GoogleStatusResponse(enabled=settings.google_oauth_enabled)


@router.get("/session", response_model=SessionResponse)
async def session_status(
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Datos mínimos de la sesión actual (RF-10, D-5).

    Devuelve la cuenta y la primera organización del orden estable (o ``null``)
    para que el frontend rehidrate su estado tras el retorno del flujo. No
    expone correo, nombre, identidad ni vinculación.
    """

    async with db.begin():
        await set_rls_context(db, None, user_id)
        organizations = (
            await db.execute(text("SELECT id, name FROM list_user_organizations()"))
        ).mappings().all()

    ordered = ordered_organizations(organizations)
    organization_id = ordered[0]["id"] if ordered else None

    response.headers["Cache-Control"] = "no-store"
    return SessionResponse(
        user_id=str(user_id),
        organization_id=str(organization_id) if organization_id else None,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    await enforce_rate_limit(
        request,
        "register",
        settings.auth_register_rate_limit,
        3600,
        account_identifier=str(payload.email),
        max_body_bytes=settings.max_request_body_bytes,
    )
    try:
        async with db.begin():
            result = await db.execute(
                text("""
                    INSERT INTO users (email, password_hash, full_name)
                    VALUES (LOWER(:email), :password_hash, :full_name)
                    RETURNING id
                """),
                {
                    "email": payload.email,
                    "password_hash": hash_password(payload.password),
                    "full_name": payload.full_name,
                },
            )
            user_id = result.scalar_one()
            organization_id = await _create_organization(db, payload.organization_name, payload.organization_slug, user_id)
            access_token = await create_user_session(db, user_id)
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El email o slug de organización ya existe") from exc

    set_auth_cookie(response, access_token)
    return TokenResponse(user_id=str(user_id), organization_id=str(organization_id))


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    await enforce_rate_limit(
        request,
        "login",
        settings.auth_login_rate_limit,
        60,
        account_identifier=str(payload.email),
        max_body_bytes=settings.max_request_body_bytes,
    )
    async with db.begin():
        result = await db.execute(
            text("""
                SELECT id, password_hash
                FROM users
                WHERE LOWER(email) = LOWER(:email) AND is_active = TRUE
            """),
            {"email": payload.email},
        )
        user = result.mappings().one_or_none()
        if user is None or user["password_hash"] is None or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")

        await set_rls_context(db, None, user["id"])
        organizations = await db.execute(
            text("""
                SELECT id, name
                FROM list_user_organizations()
            """),
        )
        ordered = ordered_organizations(organizations.mappings().all())
        organization_id = ordered[0]["id"] if ordered else None
        access_token = await create_user_session(db, user["id"])

    set_auth_cookie(response, access_token)
    return TokenResponse(
        user_id=str(user["id"]),
        organization_id=str(organization_id) if organization_id else None,
    )


@router.post("/google/start", response_model=GoogleStartResponse)
async def google_start(
    payload: GoogleStartRequest,
    request: Request,
    response: Response,
    user_id: UUID | None = Depends(get_optional_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> GoogleStartResponse:
    """Inicia el flujo de autorización de Google (RF-1, RF-2, RF-6, RF-9, RF-14).

    Orden de guardas: límite de intentos, Google configurado, sesión y cuenta
    (solo en ``flow="link"``) y Redis. Ninguna escritura ocurre antes de que la
    identidad esté verificada: aquí solo se guarda el intento y se devuelve la
    dirección del proveedor. La respuesta no lleva tokens ni el secreto; el
    destino de retorno vive únicamente en Redis y nunca viaja al proveedor.
    """

    settings = get_settings()

    try:
        await enforce_rate_limit(
            request,
            "google",
            settings.auth_login_rate_limit,
            60,
            max_body_bytes=settings.max_request_body_bytes,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            raise GoogleAuthError(
                status.HTTP_429_TOO_MANY_REQUESTS,
                RATE_LIMITED,
                headers={"Retry-After": "60"},
            ) from exc
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            raise GoogleAuthError(
                status.HTTP_503_SERVICE_UNAVAILABLE, GOOGLE_UNAVAILABLE
            ) from exc
        raise

    if not settings.google_oauth_enabled:
        # Falla cerrada y sin contactar al proveedor ni escribir (RF-1).
        raise GoogleAuthError(
            status.HTTP_503_SERVICE_UNAVAILABLE, GOOGLE_UNAVAILABLE
        )

    if payload.flow == "link":
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Autenticación requerida",
            )
        already_linked = (
            await db.execute(
                text("""
                    SELECT 1
                    FROM public.auth_identities
                    WHERE user_id = :user_id AND provider = 'google'
                    LIMIT 1
                """),
                {"user_id": user_id},
            )
        ).first()
        if already_linked is not None:
            raise GoogleAuthError(
                status.HTTP_409_CONFLICT, GOOGLE_ALREADY_LINKED
            )

    destination = validate_return_destination(payload.redirect)
    state = new_state()
    attempt = GoogleAttempt(
        flow=payload.flow,
        destination=destination,
        user_id=str(user_id) if user_id is not None else None,
        expires_at=datetime.now(UTC) + timedelta(seconds=OAUTH_STATE_MAX_AGE_SECONDS),
    )

    previous_state = request.cookies.get(OAUTH_STATE_COOKIE)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        if previous_state:
            # Un inicio nuevo invalida el intento anterior (RF-6).
            await discard_attempt(redis, previous_state)
        await save_attempt(redis, state, attempt)
    except RedisError as exc:
        raise GoogleAuthError(
            status.HTTP_503_SERVICE_UNAVAILABLE, GOOGLE_UNAVAILABLE
        ) from exc
    finally:
        await redis.aclose()

    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=OAUTH_STATE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"
    return GoogleStartResponse(
        authorization_url=authorization_url(settings, state=state)
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    session_user_id: UUID | None = Depends(get_optional_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Retorno del proveedor para el inicio de sesión y la vinculación.

    Solo se leen ``code``, ``state`` y ``error``; el resto de parámetros se
    ignora. Todo fallo es un ``302`` al ``/login`` (o a ``/account/google`` si el
    intento era de vinculación) con un código del catálogo y sin cookie de
    sesión. El éxito del login entrega la cookie existente y redirige al puente
    del frontend (``/auth/callback?next=…``) con el destino validado o el destino
    por defecto; el éxito de la vinculación **no** emite ni revoca sesión
    (RF-18). La cookie de estado se borra siempre.
    """

    settings = get_settings()
    deadline = time.monotonic() + ATTEMPT_BUDGET_SECONDS
    browser_state = request.cookies.get(OAUTH_STATE_COOKIE)

    try:
        await enforce_rate_limit(
            request,
            "google",
            settings.auth_login_rate_limit,
            60,
            max_body_bytes=settings.max_request_body_bytes,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            return _error_redirect(settings, RATE_LIMITED)
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            return _error_redirect(settings, GOOGLE_UNAVAILABLE)
        raise

    if not settings.google_oauth_enabled:
        # Falla cerrada: ni proveedor ni Redis (RF-1).
        return _error_redirect(settings, GOOGLE_UNAVAILABLE)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        if error is not None:
            # Cancelación del proveedor. Si el estado es el del navegador y el
            # intento existe, se **consume** (nunca se reutiliza) y el aviso se
            # enruta a la pantalla que corresponde al flujo. Con un estado no
            # válido se mantiene `/login`.
            if (
                state
                and browser_state
                and secrets.compare_digest(state, browser_state)
            ):
                try:
                    cancelled = await consume_attempt(redis, state)
                except RedisError:
                    return _error_redirect(settings, GOOGLE_UNAVAILABLE)
                if cancelled is not None and cancelled.flow == "link":
                    return _frontend_redirect(
                        settings, "/account/google", error=GOOGLE_CANCELLED
                    )
            elif state:
                await discard_attempt(redis, state)
            return _error_redirect(settings, GOOGLE_CANCELLED)

        if (
            not state
            or not browser_state
            or not secrets.compare_digest(state, browser_state)
        ):
            return _error_redirect(settings, GOOGLE_STATE_INVALID)

        try:
            attempt = await consume_attempt(redis, state)
        except RedisError:
            return _error_redirect(settings, GOOGLE_UNAVAILABLE)
    finally:
        await redis.aclose()

    if attempt is None or not attempt_is_valid(attempt, now=datetime.now(UTC)):
        return _error_redirect(settings, GOOGLE_STATE_INVALID)

    if not code:
        return _attempt_error_redirect(settings, attempt, GOOGLE_IDENTITY_INVALID)

    try:
        async with httpx.AsyncClient() as client:
            raw = await exchange_code(
                settings, code=code, deadline=deadline, client=client
            )
    except GoogleUnavailable:
        return _attempt_error_redirect(settings, attempt, GOOGLE_UNAVAILABLE)
    except GoogleIdentityInvalid:
        return _attempt_error_redirect(settings, attempt, GOOGLE_IDENTITY_INVALID)

    try:
        identity = parse_identity_claims(
            raw,
            client_id=settings.google_audience,
            now=datetime.now(UTC),
        )
    except GoogleIdentityInvalid:
        return _attempt_error_redirect(settings, attempt, GOOGLE_IDENTITY_INVALID)

    try:
        await enforce_rate_limit(
            request,
            "google-identity",
            settings.auth_login_rate_limit,
            60,
            account_identifier=identity.subject,
            max_body_bytes=settings.max_request_body_bytes,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            return _attempt_error_redirect(settings, attempt, RATE_LIMITED)
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            return _attempt_error_redirect(settings, attempt, GOOGLE_UNAVAILABLE)
        raise

    if attempt.flow == "link":
        # La vinculación exige que el intento pertenezca a la sesión presentada.
        # Si falta o no coincide, falla cerrado sin vincular ni tocar sesiones.
        if (
            not attempt.user_id
            or session_user_id is None
            or str(session_user_id) != attempt.user_id
        ):
            return _attempt_error_redirect(
                settings, attempt, GOOGLE_IDENTITY_INVALID
            )
        try:
            await link_identity(db, user_id=session_user_id, identity=identity)
        except LinkRejected as exc:
            return _attempt_error_redirect(settings, attempt, exc.code)
        except SessionAccountInvalid:
            return _attempt_error_redirect(
                settings, attempt, GOOGLE_IDENTITY_INVALID
            )
        # Sin set_auth_cookie, sin revocación y sin tocar user_sessions (RF-18).
        return _frontend_redirect(
            settings, "/account/google", notice="GOOGLE_LINK_SUCCESS"
        )

    try:
        result = await resolve_login(db, identity)
    except LoginRejected as exc:
        return _attempt_error_redirect(settings, attempt, exc.code)

    await _revoke_presented_session(db, request, settings)

    destination = validate_return_destination(attempt.destination) or (
        "/organization" if result.organization_id is None else "/workspace"
    )
    response = _frontend_redirect(settings, "/auth/callback", next=destination)
    set_auth_cookie(response, result.session_token)
    return response


@router.get("/google/link", response_model=GoogleLinkStatusResponse)
async def google_link_status(
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> GoogleLinkStatusResponse:
    """Estado de la vinculación de la propia cuenta (RF-33).

    Único dato expuesto: si la cuenta de la sesión tiene identidad de Google. No
    devuelve correo, nombre, sujeto ni fechas; sin sesión responde 401.
    """

    linked = (
        await db.execute(
            text("""
                SELECT 1
                FROM public.auth_identities
                WHERE user_id = :user_id AND provider = 'google'
                LIMIT 1
            """),
            {"user_id": user_id},
        )
    ).first()
    response.headers["Cache-Control"] = "no-store"
    return GoogleLinkStatusResponse(linked=linked is not None)


@router.post("/google", status_code=status.HTTP_410_GONE)
async def google_login_retired(response: Response) -> dict[str, str]:
    """Rechazo estable del camino anterior (RF-3, RNF-9, D-6).

    No lee el cuerpo, no depende de sesión, base, rate limit ni proveedor y no
    escribe nada: un cliente antiguo recibe **410** con el código del catálogo
    en lugar de un 404 silencioso.
    """

    response.headers["Cache-Control"] = "no-store"
    return {
        "detail": RETIRED_GOOGLE_LOGIN_DETAIL,
        "code": GOOGLE_IDENTITY_INVALID,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> None:
    settings = get_settings()
    raw_token = credentials.credentials if credentials else request.cookies.get(settings.auth_cookie_name)
    if raw_token:
        try:
            claims = decode_access_token_claims(raw_token)
        except HTTPException:
            claims = None
        if claims:
            async with db.begin():
                await db.execute(
                    text("""
                        UPDATE user_sessions
                        SET revoked_at = CURRENT_TIMESTAMP
                        WHERE id = :session_id AND user_id = :user_id AND revoked_at IS NULL
                    """),
                    {"session_id": claims["jti"], "user_id": claims["sub"]},
                )
    clear_auth_cookie(response)
