from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=100)
    organization_name: str = Field(min_length=2, max_length=100)
    organization_slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    user_id: str
    organization_id: str | None = None


class GoogleStartRequest(BaseModel):
    """Inicio del flujo: ``redirect`` inválido se normaliza a ``None``, no es 422."""

    flow: Literal["login", "link"] = "login"
    redirect: str | None = None


class GoogleStartResponse(BaseModel):
    authorization_url: str


class GoogleLinkStatusResponse(BaseModel):
    """Único dato que se expone de la vinculación (RF-33): ni correo ni sujeto."""

    linked: bool


class GoogleStatusResponse(BaseModel):
    """Solo si el flujo de Google está configurado (sin secretos ni URI)."""

    enabled: bool


class SessionResponse(BaseModel):
    """Sesión resuelta: la cuenta y su primera organización del orden estable."""

    user_id: str
    organization_id: str | None = None
