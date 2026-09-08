from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEVELOPMENT_DATABASE_PASSWORD = "bracket_app_dev_password"
DEVELOPMENT_JWT_SECRET = "replace-this-development-secret-with-at-least-32-characters"
DEVELOPMENT_PLAYER_DATA_KEY = "replace-this-development-player-key-with-at-least-32-characters"
DEVELOPMENT_DATABASE_URL = (
    "postgresql+asyncpg://bracket_app:bracket_app_dev_password@localhost:5432/bracket_craft"
)
DEVELOPMENT_REDIS_URL = "redis://localhost:6379/0"
DEVELOPMENT_STORAGE_ACCESS_KEY = "minioadmin"
DEVELOPMENT_STORAGE_SECRET_KEY = "minioadmin"

JWT_ALGORITHMS = Literal["HS256", "HS384", "HS512"]
DEVELOPMENT_ENVS = {"development", "dev", "local"}


class Settings(BaseSettings):
    database_url: str = DEVELOPMENT_DATABASE_URL
    redis_url: str = DEVELOPMENT_REDIS_URL
    jwt_secret: str = Field(default=DEVELOPMENT_JWT_SECRET, min_length=32)
    jwt_algorithm: JWT_ALGORITHMS = "HS256"
    jwt_expire_minutes: int = Field(default=30, ge=5, le=1440)
    app_env: str = "development"
    cors_allowed_origins: str = "http://localhost:3000"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_audience: str | None = None
    jwt_issuer: str = "bracket-craft-api"
    jwt_audience: str = "bracket-craft-web"
    player_data_key: str = Field(default=DEVELOPMENT_PLAYER_DATA_KEY, min_length=32)
    auth_cookie_name: str = "bc_access_token"
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_cookie_secure: bool | None = None
    csrf_cookie_name: str = "bc_csrf_token"
    csrf_token_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    auth_login_rate_limit: int = Field(default=10, ge=1, le=1000)
    auth_register_rate_limit: int = Field(default=5, ge=1, le=1000)
    storage_provider: Literal["s3", "gcs"] = "s3"
    storage_endpoint_url: str | None = None
    storage_signing_endpoint_url: str | None = None
    storage_region: str = "us-east-1"
    storage_bucket: str = "bracket-craft-media"
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    storage_public_base_url: str | None = None
    storage_presign_seconds: int = Field(default=300, ge=60, le=3600)
    storage_max_image_bytes: int = Field(default=5 * 1024 * 1024, ge=1, le=25 * 1024 * 1024)
    storage_max_archive_bytes: int = Field(default=25 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    storage_max_archive_files: int = Field(default=200, ge=1, le=1000)
    max_request_body_bytes: int = Field(default=32 * 1024 * 1024, ge=1, le=200 * 1024 * 1024)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        environment = self.app_env.lower().strip()
        if environment not in DEVELOPMENT_ENVS:
            if self.jwt_secret == DEVELOPMENT_JWT_SECRET:
                raise ValueError("JWT_SECRET debe cambiarse antes de ejecutar fuera de desarrollo")
            if self.player_data_key == DEVELOPMENT_PLAYER_DATA_KEY:
                raise ValueError("PLAYER_DATA_KEY debe cambiarse antes de ejecutar fuera de desarrollo")
            if self.database_url == DEVELOPMENT_DATABASE_URL or DEVELOPMENT_DATABASE_PASSWORD in self.database_url:
                raise ValueError("DATABASE_URL no puede usar la contraseña de desarrollo fuera de desarrollo")
            if self.storage_access_key == DEVELOPMENT_STORAGE_ACCESS_KEY:
                raise ValueError("STORAGE_ACCESS_KEY no puede usar las credenciales de MinIO fuera de desarrollo")
            if self.storage_secret_key == DEVELOPMENT_STORAGE_SECRET_KEY:
                raise ValueError("STORAGE_SECRET_KEY no puede usar las credenciales de MinIO fuera de desarrollo")
            if self.auth_cookie_secure is not True and self.cookie_secure is not True:
                raise ValueError("AUTH_COOKIE_SECURE debe estar activo fuera de desarrollo")
            if self.auth_cookie_samesite == "none" and self.cookie_secure is not True:
                raise ValueError("AUTH_COOKIE_SECURE debe estar activo con SameSite=None")

        if self.auth_cookie_samesite == "none" and self.cookie_secure is not True:
            raise ValueError("AUTH_COOKIE_SECURE debe estar activo con SameSite=None")

        if "*" in {origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()}:
            raise ValueError("CORS_ALLOWED_ORIGINS no puede usar '*' con credenciales")

        if self.google_oauth_enabled:
            if not self.google_client_id or not self.google_client_secret:
                raise ValueError("Google OAuth requiere GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET")
            if self.google_audience is None:
                self.google_audience = self.google_client_id
            if self.google_audience != self.google_client_id:
                raise ValueError("GOOGLE_AUDIENCE debe coincidir con GOOGLE_CLIENT_ID")
        return self

    @property
    def cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.app_env.lower().strip() not in DEVELOPMENT_ENVS

    @property
    def google_oauth_enabled(self) -> bool:
        return any(
            value not in (None, "")
            for value in (self.google_client_id, self.google_client_secret, self.google_audience)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
