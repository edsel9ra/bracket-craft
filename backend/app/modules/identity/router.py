from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
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
    hash_password,
    set_auth_cookie,
    verify_password,
)
from app.modules.identity.schemas import GoogleLoginRequest, LoginRequest, RegisterRequest, TokenResponse


router = APIRouter(prefix="/auth", tags=["identity"])


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
                SELECT id
                FROM list_user_organizations()
                LIMIT 1
            """),
        )
        organization_id = organizations.scalar_one_or_none()
        access_token = await create_user_session(db, user["id"])

    set_auth_cookie(response, access_token)
    return TokenResponse(
        user_id=str(user["id"]),
        organization_id=str(organization_id) if organization_id else None,
    )


@router.post("/google", response_model=TokenResponse)
async def google_login(
    payload: GoogleLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    await enforce_rate_limit(
        request,
        "google",
        settings.auth_login_rate_limit,
        60,
        max_body_bytes=settings.max_request_body_bytes,
    )
    if not settings.google_oauth_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google OAuth no está configurado")
    async with httpx.AsyncClient(timeout=10) as client:
        token_info = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": payload.access_token},
        )
        if token_info.status_code != 200 or token_info.json().get("aud") != settings.google_audience:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de Google inválido")
        api_response = await client.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {payload.access_token}"},
        )
    if api_response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de Google inválido")

    profile = api_response.json()
    provider_subject = profile.get("sub")
    email = profile.get("email")
    if not provider_subject or not email or profile.get("email_verified") is not True:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Perfil de Google no verificado")

    async with db.begin():
        identity_result = await db.execute(
            text("""
                SELECT u.id, u.is_active
                FROM auth_identities ai
                JOIN users u ON u.id = ai.user_id
                WHERE ai.provider = 'google' AND ai.provider_subject = :subject
            """),
            {"subject": provider_subject},
        )
        identity = identity_result.mappings().one_or_none()
        user_id = identity["id"] if identity else None
        if identity and not identity["is_active"]:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La cuenta está desactivada")

        organization_id = None
        if user_id is None:
            try:
                user_result = await db.execute(
                    text("""
                        INSERT INTO users (email, password_hash, full_name)
                        VALUES (LOWER(:email), NULL, :full_name)
                        RETURNING id
                    """),
                    {"email": email, "full_name": profile.get("name") or email.split("@", 1)[0]},
                )
                user_id = user_result.scalar_one()
                await db.execute(
                    text("""
                        INSERT INTO auth_identities (user_id, provider, provider_subject)
                        VALUES (:user_id, 'google', :subject)
                    """),
                    {"user_id": str(user_id), "subject": provider_subject},
                )
                if payload.organization_name and payload.organization_slug:
                    organization_id = await _create_organization(
                        db, payload.organization_name, payload.organization_slug, user_id
                    )
            except IntegrityError as exc:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La cuenta o organización ya existe") from exc
        else:
            await set_rls_context(db, None, user_id)
            organization_id = (await db.execute(
                text("""
                    SELECT id
                    FROM list_user_organizations()
                    LIMIT 1
                """),
            )).scalar_one_or_none()

        access_token = await create_user_session(db, user_id)

    set_auth_cookie(response, access_token)
    return TokenResponse(
        user_id=str(user_id),
        organization_id=str(organization_id) if organization_id else None,
    )


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
