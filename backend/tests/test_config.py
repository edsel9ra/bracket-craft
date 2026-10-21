import pytest
from pydantic import ValidationError

from app.core.config import (
    DEVELOPMENT_DATABASE_PASSWORD,
    DEVELOPMENT_INVITATION_TOKEN_KEY,
    DEVELOPMENT_JWT_SECRET,
    DEVELOPMENT_PLAYER_DATA_KEY,
    DEVELOPMENT_STORAGE_ACCESS_KEY,
    DEVELOPMENT_STORAGE_SECRET_KEY,
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
        invitation_token_key="production-invitation-key-" + "x" * 48,
        storage_access_key="production-access-key",
        storage_secret_key="production-storage-secret",
        auth_cookie_secure=True,
    )

    assert settings.app_env == "production"
    assert DEVELOPMENT_DATABASE_PASSWORD not in settings.database_url
    assert settings.jwt_secret != DEVELOPMENT_JWT_SECRET
    assert settings.player_data_key != DEVELOPMENT_PLAYER_DATA_KEY
    assert settings.invitation_token_key != DEVELOPMENT_INVITATION_TOKEN_KEY


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


def test_empty_google_audience_falls_back_to_client_id():
    settings = Settings(
        google_client_id="client-id",
        google_client_secret="client-secret",
        google_audience="",
    )

    assert settings.google_oauth_enabled is True
    assert settings.google_audience == "client-id"


def test_missing_google_audience_falls_back_to_client_id():
    settings = Settings(
        google_client_id="client-id",
        google_client_secret="client-secret",
    )

    assert settings.google_oauth_enabled is True
    assert settings.google_audience == "client-id"


def test_empty_google_audience_without_oauth_stays_disabled():
    settings = Settings(google_audience="")

    assert settings.google_audience is None
    assert settings.google_oauth_enabled is False


def test_empty_storage_signing_endpoint_url_is_treated_as_absent():
    settings = Settings(storage_signing_endpoint_url="")

    assert settings.storage_signing_endpoint_url is None


def production_settings(**overrides):
    values = {
        "app_env": "production",
        "database_url": "postgresql+asyncpg://bracket_app:production-password@db:5432/bracket_craft",
        "jwt_secret": "production-secret-" + "x" * 48,
        "player_data_key": "production-player-key-" + "x" * 48,
        "invitation_token_key": "production-invitation-key-" + "x" * 48,
        "storage_access_key": "production-access-key",
        "storage_secret_key": "production-storage-secret",
        "auth_cookie_secure": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_development_storage_credentials_are_preserved_for_local_storage():
    # R32g: los valores de desarrollo se conservan para no invalidar un
    # almacenamiento local ya inicializado; solo se excluyen del perfil de
    # producción.
    assert DEVELOPMENT_STORAGE_ACCESS_KEY == "minioadmin"
    assert DEVELOPMENT_STORAGE_SECRET_KEY == "minioadmin"


def test_production_rejects_development_storage_access_key_without_the_old_brand():
    with pytest.raises(ValidationError) as error:
        production_settings(storage_access_key=DEVELOPMENT_STORAGE_ACCESS_KEY)

    message = str(error.value)
    assert "credenciales de desarrollo del almacenamiento" in message
    assert "STORAGE_ACCESS_KEY" in message
    assert "minio" not in message.casefold()


def test_production_rejects_development_storage_secret_key_without_the_old_brand():
    with pytest.raises(ValidationError) as error:
        production_settings(storage_secret_key=DEVELOPMENT_STORAGE_SECRET_KEY)

    message = str(error.value)
    assert "credenciales de desarrollo del almacenamiento" in message
    assert "STORAGE_SECRET_KEY" in message
    assert "minio" not in message.casefold()


def test_settings_read_the_seven_recovered_variables_from_the_environment(monkeypatch):
    # R20: las cinco variables de comportamiento y las dos opcionales llegan a
    # ``Settings`` desde el entorno, no solo desde el uso que hace el código.
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    monkeypatch.setenv("CSRF_COOKIE_NAME", "custom_csrf_token")
    monkeypatch.setenv("CSRF_TOKEN_TTL_SECONDS", "7200")
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "1048576")
    monkeypatch.setenv("STORAGE_PRESIGN_SECONDS", "600")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-from-env")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-from-env")
    monkeypatch.setenv("GOOGLE_AUDIENCE", "client-from-env")
    monkeypatch.setenv("STORAGE_SIGNING_ENDPOINT_URL", "https://signing.example.test")

    settings = Settings(_env_file=None)

    assert settings.jwt_algorithm == "HS512"
    assert settings.csrf_cookie_name == "custom_csrf_token"
    assert settings.csrf_token_ttl_seconds == 7200
    assert settings.max_request_body_bytes == 1048576
    assert settings.storage_presign_seconds == 600
    assert settings.google_audience == "client-from-env"
    assert settings.storage_signing_endpoint_url == "https://signing.example.test"
