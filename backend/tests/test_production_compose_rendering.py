import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("docker") is None, reason="requiere Docker Compose para renderizar el YAML real")
def test_proxy_list_with_spaces_is_one_argument_in_rendered_compose():
    root = Path(__file__).resolve().parents[2]
    proxies = "192.0.2.10, 198.51.100.7"
    environment = os.environ | {
        "POSTGRES_PASSWORD": "dummy-postgres-password",
        "BRACKET_DB_PASSWORD": "dummy-bracket-db-password",
        "PLATFORM_ADMIN_EMAIL": "dummy@example.test",
        "JWT_SECRET": "dummy-jwt-secret-with-at-least-32-characters",
        "PLAYER_DATA_KEY": "dummy-player-key-with-at-least-32-characters",
        "INVITATION_TOKEN_KEY": "dummy-invitation-key-with-at-least-32-characters",
        "DATABASE_URL": "postgresql+asyncpg://dummy:dummy@db:5432/dummy",
        "CORS_ALLOWED_ORIGINS": "http://localhost:3000",
        "STORAGE_PROVIDER": "s3", "STORAGE_BUCKET": "dummy",
        "STORAGE_PUBLIC_BASE_URL": "http://localhost:9000/dummy",
        "FRONTEND_BASE_URL": "http://localhost:3000",
        "SMTP_HOST": "localhost", "SMTP_FROM": "noreply@example.test",
        "NUXT_PUBLIC_API_BASE": "http://localhost:8000/api/v1",
        "NUXT_PUBLIC_SOCKET_BASE": "http://localhost:8000",
        "NUXT_API_INTERNAL_BASE": "http://api:8000/api/v1",
        "PROXY_NETWORK": "edge", "FORWARDED_ALLOW_IPS": proxies,
    }
    rendered = subprocess.run(
        ["docker", "compose", "--env-file", str(root / ".env.example"),
         "-f", "docker-compose.yml", "-f", "docker-compose.production.yml",
         "config", "--format", "json"],
        cwd=root, env=environment, check=True, capture_output=True, text=True,
    )
    config = json.loads(rendered.stdout)
    command = config["services"]["api"]["command"]
    assert isinstance(command, list)
    assert command.count(f"--forwarded-allow-ips={proxies}") == 1
    assert "198.51.100.7" not in command
    subprocess.run(
        [sys.executable, str(root / "infra/scripts/assert_production_compose.py"), "-"],
        input=rendered.stdout, check=True, capture_output=True, text=True,
    )
