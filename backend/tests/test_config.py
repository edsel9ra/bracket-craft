import pytest
from pydantic import ValidationError

from app.core.config import (
    DEVELOPMENT_DATABASE_PASSWORD,
    DEVELOPMENT_JWT_SECRET,
    DEVELOPMENT_PLAYER_DATA_KEY,
    Settings,
)


def test_production_settings_reject_development_secrets():
    with pytest.raises(ValidationError):
        Settings(app_env="production")


def test_production_settings_accept_explicit_secrets():
    settings = Settings(
        app_env="production",
        database_url=f"postgresql+asyncpg://bracket_app:production-password@db:5432/bracket_craft",
        jwt_secret="production-secret-" + "x" * 48,
        player_data_key="production-player-key-" + "x" * 48,
        storage_access_key="production-access-key",
        storage_secret_key="production-storage-secret",
    )

    assert settings.app_env == "production"
    assert DEVELOPMENT_DATABASE_PASSWORD not in settings.database_url
    assert settings.jwt_secret != DEVELOPMENT_JWT_SECRET
    assert settings.player_data_key != DEVELOPMENT_PLAYER_DATA_KEY


def test_jwt_algorithm_is_whitelisted():
    with pytest.raises(ValidationError):
        Settings(jwt_algorithm="none")


def test_production_settings_require_secure_auth_cookies():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            database_url="postgresql+asyncpg://bracket_app:production-password@db:5432/bracket_craft",
            jwt_secret="production-secret-" + "x" * 48,
            player_data_key="production-player-key-" + "x" * 48,
            storage_access_key="production-access-key",
            storage_secret_key="production-storage-secret",
            auth_cookie_secure=False,
        )


def test_production_settings_reject_postgres_database_role():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            database_url="postgresql+asyncpg://postgres:production-password@db:5432/bracket_craft",
            jwt_secret="production-secret-" + "x" * 48,
            player_data_key="production-player-key-" + "x" * 48,
            storage_access_key="production-access-key",
            storage_secret_key="production-storage-secret",
            auth_cookie_secure=True,
        )


def test_google_oauth_requires_a_matching_audience():
    with pytest.raises(ValidationError):
        Settings(
            google_client_id="client-id",
            google_client_secret="client-secret",
            google_audience="another-client-id",
        )
