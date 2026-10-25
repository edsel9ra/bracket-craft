from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_rls_context
from app.core.security import get_current_user_id
from app.core.tenancy import AuthContext, get_auth_context
from app.modules.organizations.errors import OrganizationSlugTaken
from app.modules.organizations.ordering import ordered_organizations
from app.modules.organizations.schemas import (
    CurrentOrganizationResponse,
    OrganizationCreateRequest,
    OrganizationSummaryResponse,
)


router = APIRouter(prefix="/organizations", tags=["organizations"])

#: Unicidad funcional del identificador (``LOWER(slug)``), definida en el init.
SLUG_UNIQUE_CONSTRAINT = "uq_organizations_slug_ci"


def _is_slug_conflict(error: IntegrityError) -> bool:
    """Distingue el choque del slug de cualquier otro error de integridad.

    La única unicidad que puede violar el alta es ``uq_organizations_slug_ci``;
    si el controlador no expone el nombre de la restricción, se acepta el
    SQLSTATE ``23505``. Cualquier otro error se relanza sin traducir.
    """

    original = error.orig
    constraint = getattr(original, "constraint_name", None)
    if constraint is not None:
        return constraint == SLUG_UNIQUE_CONSTRAINT
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate == "23505"


@router.get("")
async def list_organizations(
    user_id=Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[OrganizationSummaryResponse]:
    async with db.begin():
        await set_rls_context(db, None, user_id)
        result = await db.execute(
            text("""
                SELECT id, name, slug, organization_user_id
                FROM list_user_organizations()
            """),
        )
        rows = [dict(row) for row in result.mappings().all()]
        return ordered_organizations(rows)


@router.post(
    "",
    response_model=OrganizationSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    payload: OrganizationCreateRequest,
    response: Response,
    user_id: UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> OrganizationSummaryResponse:
    """Crea la organización explícita de una sesión que aún no tiene ninguna.

    Guarda de RF-25: si la cuenta ya pertenece a una organización responde
    **409 sin ``code``** y no escribe nada. El alta usa la función atómica
    ``create_organization_with_owner`` (dueño + membresía + rol) dentro de la
    misma transacción, con el contexto RLS fijado. La respuesta se lee de
    ``list_user_organizations()`` (``SECURITY DEFINER``): el rol de aplicación no
    tiene privilegios directos sobre ``organizations``. Un identificador ocupado
    responde 409 con el código aditivo ``ORGANIZATION_SLUG_TAKEN``.
    """

    async with db.begin():
        await set_rls_context(db, None, user_id)

        existing = (
            await db.execute(text("SELECT 1 FROM list_user_organizations() LIMIT 1"))
        ).first()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La cuenta ya tiene una organización",
            )

        try:
            organization_id = (
                await db.execute(
                    text(
                        "SELECT create_organization_with_owner(:name, :slug, :user_id)"
                    ),
                    {
                        "name": payload.name,
                        "slug": payload.slug,
                        "user_id": str(user_id),
                    },
                )
            ).scalar_one()
        except IntegrityError as exc:
            if not _is_slug_conflict(exc):
                raise
            raise OrganizationSlugTaken() from exc

        await set_rls_context(db, organization_id, user_id)
        organizations = (
            await db.execute(
                text("""
                    SELECT id, name, slug, organization_user_id
                    FROM list_user_organizations()
                """)
            )
        ).mappings().all()
        organization = next(
            (dict(row) for row in organizations if row["id"] == organization_id),
            None,
        )
        if organization is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo leer la organización creada",
            )

    response.headers["Cache-Control"] = "no-store"
    return organization


@router.get("/current", response_model=CurrentOrganizationResponse)
async def current_organization(
    context: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> CurrentOrganizationResponse:
    async with db.begin():
        await set_rls_context(db, context.organization_id, context.user_id)
        result = await db.execute(text("SELECT id, name, slug FROM get_current_organization()"))
        organization = result.mappings().one_or_none()
        if organization is None:
            raise HTTPException(status_code=404, detail="Organización no encontrada")
        return dict(organization)
