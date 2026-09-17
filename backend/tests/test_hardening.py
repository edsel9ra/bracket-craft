import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import rate_limit as rate_limit_module
from app.core import storage as storage_module
from app.core.csrf import validate_csrf_request
from app.core.rate_limit import enforce_rate_limit
from app.core.storage import ObjectStorage, StorageError
from app.main import _buffer_request_body, _relay_outbox_messages, sio


ALLOWED_ORIGINS = {"http://localhost:3000"}


def make_request(method: str = "POST", headers: dict[str, str] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": "/api/v1/test",
        "raw_path": b"/api/v1/test",
        "query_string": b"",
        "headers": [
            (name.lower().encode(), value.encode())
            for name, value in (headers or {}).items()
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_csrf_accepts_an_allowed_origin_and_matching_token():
    request = make_request(
        headers={
            "Origin": "http://localhost:3000",
            "Cookie": "bc_csrf_token=token-value",
            "X-CSRF-Token": "token-value",
        }
    )

    validate_csrf_request(request, ALLOWED_ORIGINS, "bc_csrf_token")


def test_csrf_rejects_untrusted_origin():
    request = make_request(headers={"Origin": "https://attacker.example"})

    with pytest.raises(HTTPException) as failure:
        validate_csrf_request(request, ALLOWED_ORIGINS, "bc_csrf_token")

    assert failure.value.status_code == 403


def test_csrf_rejects_a_missing_double_submit_copy():
    request = make_request(headers={"Cookie": "bc_csrf_token=token-value"})

    with pytest.raises(HTTPException) as failure:
        validate_csrf_request(request, ALLOWED_ORIGINS, "bc_csrf_token")

    assert failure.value.status_code == 403


def test_csrf_rejects_an_unsafe_request_without_tokens():
    request = make_request()

    with pytest.raises(HTTPException) as failure:
        validate_csrf_request(request, ALLOWED_ORIGINS, "bc_csrf_token")

    assert failure.value.status_code == 403


def test_csrf_does_not_require_tokens_for_safe_methods():
    request = make_request("GET", headers={"Origin": "https://attacker.example"})

    validate_csrf_request(request, ALLOWED_ORIGINS, "bc_csrf_token")


class FakeRedis:
    def __init__(self, result: int = 0):
        self.result = result
        self.eval_args = None
        self.closed = False

    async def eval(self, *args):
        self.eval_args = args
        return self.result

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_rate_limit_uses_ip_account_and_connection_keys(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(rate_limit_module.Redis, "from_url", lambda *args, **kwargs: redis)
    request = make_request()

    await enforce_rate_limit(
        request,
        "login",
        10,
        60,
        account_identifier=" User@Example.COM ",
        connection_identifier="connection-1",
        max_body_bytes=100,
    )

    assert redis.closed is True
    assert redis.eval_args[1] == 3
    keys = redis.eval_args[2:5]
    assert all("User@Example.COM" not in key for key in keys)
    assert redis.eval_args[5:] == ("60", "10", "10", "10")


@pytest.mark.asyncio
async def test_rate_limit_returns_429_when_atomic_script_reports_exceeded(monkeypatch):
    redis = FakeRedis(result=1)
    monkeypatch.setattr(rate_limit_module.Redis, "from_url", lambda *args, **kwargs: redis)

    with pytest.raises(HTTPException) as failure:
        await enforce_rate_limit(make_request(), "login", 1, 60)

    assert failure.value.status_code == 429
    assert redis.closed is True


def storage_settings():
    return SimpleNamespace(
        storage_provider="s3",
        storage_endpoint_url="http://minio:9000",
        storage_signing_endpoint_url=None,
        storage_public_base_url="http://localhost:9000/bracket-craft-media",
        storage_region="us-east-1",
        storage_bucket="bracket-craft-media",
        storage_access_key="minioadmin",
        storage_secret_key="minioadmin",
        storage_presign_seconds=300,
        storage_max_image_bytes=5 * 1024 * 1024,
    )


@pytest.mark.asyncio
async def test_storage_signs_private_keys_using_the_browser_endpoint(monkeypatch):
    settings = storage_settings()
    monkeypatch.setattr(storage_module, "get_settings", lambda: settings)
    storage = ObjectStorage()
    captured = {}

    class FakeClient:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            captured.update(operation=operation, params=Params, expires=ExpiresIn)
            return "https://signed.example/photo"

    monkeypatch.setattr(storage, "_client", lambda endpoint=None: (captured.update(endpoint=endpoint) or FakeClient()))

    result = await storage.signed_url("private/organizations/org/rosters/roster/photo.jpg")

    assert result == "https://signed.example/photo"
    assert captured["endpoint"] == "http://localhost:9000"
    assert captured["params"]["Key"].startswith("private/")
    assert captured["expires"] == 300


@pytest.mark.asyncio
async def test_storage_rejects_path_traversal_before_signing(monkeypatch):
    settings = storage_settings()
    monkeypatch.setattr(storage_module, "get_settings", lambda: settings)
    storage = ObjectStorage()

    with pytest.raises(StorageError):
        await storage.signed_url("private/organizations/../other/photo.jpg")


@pytest.mark.asyncio
async def test_request_body_limit_counts_chunked_messages_and_replays_small_bodies():
    messages = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    request = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": []},
        receive,
    )

    assert await _buffer_request_body(request, 6) is True
    downstream = Request(request.scope, request.receive)
    assert await downstream.body() == b"abcdef"


@pytest.mark.asyncio
async def test_request_body_limit_rejects_chunked_messages_over_limit():
    messages = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    request = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": []},
        receive,
    )

    assert await _buffer_request_body(request, 5) is False


@pytest.mark.asyncio
async def test_outbox_relay_skips_malformed_stream_entries(monkeypatch):
    emitted = []

    async def fake_emit(*args, **kwargs):
        emitted.append((args, kwargs))

    monkeypatch.setattr(sio, "emit", fake_emit)
    messages = [
        (
            "bracket_craft.events",
            [
                ("1-0", {"event": "{}"}),
                (
                    "2-0",
                    {
                        "event": json.dumps(
                            {
                                "event_type": "MATCH_UPDATED",
                                "organization_id": "org-1",
                                "payload": {"tournament_id": "tournament-1"},
                            }
                        )
                    },
                ),
            ],
        )
    ]

    assert await _relay_outbox_messages(messages) == "2-0"
    assert len(emitted) == 2


def test_storage_hardens_an_endpoint_bucket_only_once(monkeypatch):
    settings = storage_settings()
    monkeypatch.setattr(storage_module, "get_settings", lambda: settings)
    storage = ObjectStorage()
    calls = {"head": 0, "delete_policy": 0}

    class FakeClient:
        def head_bucket(self, **kwargs):
            calls["head"] += 1

        def delete_bucket_policy(self, **kwargs):
            calls["delete_policy"] += 1

    client = FakeClient()
    storage._ensure_bucket(client)
    storage._ensure_bucket(client)

    assert calls == {"head": 1, "delete_policy": 1}


def test_sql_hardening_keeps_migrations_immutable_and_guards_sensitive_writes():
    root = Path(__file__).resolve().parents[2]
    migration = (root / "infra/postgres/migrations/010_outbox_and_sensitive_grants.sql").read_text()
    baseline = (root / "infra/postgres/init/01_schema.sql").read_text()

    assert "IS DISTINCT FROM 'platform_admin'" in migration
    assert "REVOKE INSERT ON public.rosters FROM bracket_app" in migration
    assert "REVOKE INSERT (photo_url) ON public.players FROM bracket_app" in migration
    assert "GRANT UPDATE (dorsal_number, is_active, valid_from, valid_to, eligible_from)" in migration
    assert "teams, tournament_teams, stage_teams, matches" in baseline
