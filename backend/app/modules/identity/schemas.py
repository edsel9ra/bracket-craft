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


class GoogleLoginRequest(BaseModel):
    access_token: str = Field(min_length=10)
    organization_name: str | None = Field(default=None, max_length=100)
    organization_slug: str | None = Field(default=None, max_length=100, pattern=r"^[a-z0-9-]+$")


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    user_id: str
    organization_id: str | None = None
