"""Cached signing client and batch signing (RF-001, RF-002, RF-010).

The storage adapter must build at most one signing client per process and
effective signing endpoint, sign each distinct key once and resolve a whole
batch with a single off-thread dispatch. Every test uses fakes: no S3 client,
no network and no real storage are involved.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.core import storage as storage_module
from app.core.storage import ObjectStorage, SignedUrls, StorageError

PHOTO_ENDPOINT = "http://photos.example:9000"
UPLOAD_ENDPOINT = "http://upload.example:9000"
SECOND_SIGNING_ENDPOINT = "https://cdn.example:9443"


def storage_settings(**overrides):
    values = {
        "storage_provider": "s3",
        "storage_endpoint_url": UPLOAD_ENDPOINT,
        "storage_signing_endpoint_url": None,
        "storage_public_base_url": f"{PHOTO_ENDPOINT}/bracket-craft-media",
        "storage_region": "us-east-1",
        "storage_bucket": "bracket-craft-media",
        "storage_access_key": "access-key",
        "storage_secret_key": "secret-key",
        "storage_presign_seconds": 300,
        "storage_max_image_bytes": 5 * 1024 * 1024,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSigningClient:
    def __init__(self, endpoint, failing_keys=()):
        self.endpoint = endpoint
        self.failing_keys = set(failing_keys)
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.calls.append(
            {"operation": operation, "key": Params["Key"], "expires": ExpiresIn}
        )
        if Params["Key"] in self.failing_keys:
            raise RuntimeError("signing failed")
        return f"{self.endpoint}/signed/{Params['Key']}"


class FakeClientFactory:
    """Counts signing client constructions and the endpoint used for each one."""

    def __init__(self, failing_keys=(), fail_build=False):
        self.failing_keys = failing_keys
        self.fail_build = fail_build
        self.endpoints = []
        self.clients = []

    def __call__(self, endpoint):
        self.endpoints.append(endpoint)
        if self.fail_build:
            raise RuntimeError("client construction failed")
        client = FakeSigningClient(endpoint, self.failing_keys)
        self.clients.append(client)
        return client


class BlockingClientFactory(FakeClientFactory):
    """Blocks the first construction until the test releases it."""

    def __init__(self):
        super().__init__()
        self.build_started = threading.Event()
        self.release = threading.Event()

    def __call__(self, endpoint):
        self.build_started.set()
        if not self.release.wait(5):
            raise AssertionError("la prueba no liberó la construcción del cliente")
        return super().__call__(endpoint)


def build_storage(monkeypatch, factory=None, **settings_overrides):
    settings = storage_settings(**settings_overrides)
    monkeypatch.setattr(storage_module, "get_settings", lambda: settings)
    return ObjectStorage(client_factory=factory), settings


@pytest.fixture
def dispatches(monkeypatch):
    """Record every off-thread dispatch made by the storage adapter."""

    calls = []
    original = asyncio.to_thread

    def counting_to_thread(func, *args, **kwargs):
        calls.append(func)
        return original(func, *args, **kwargs)

    monkeypatch.setattr(storage_module.asyncio, "to_thread", counting_to_thread)
    return calls


async def test_empty_batch_builds_no_client_and_dispatches_no_work(
    monkeypatch, dispatches
):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)

    result = await storage.signed_urls([])

    assert result == SignedUrls(urls={}, failed=(), reason=None)
    assert factory.endpoints == []
    assert dispatches == []


async def test_cold_cache_builds_one_client_and_resolves_a_batch_with_one_dispatch(
    monkeypatch, dispatches
):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)
    keys = [f"private/photo-{index}.jpg" for index in range(100)]

    result = await storage.signed_urls(keys)

    assert result.failed == ()
    assert result.reason is None
    assert list(result.urls) == keys
    assert factory.endpoints == [PHOTO_ENDPOINT]
    assert len(dispatches) == 1
    assert [call["key"] for call in factory.clients[0].calls] == keys


async def test_warm_cache_builds_no_client_and_still_uses_one_dispatch(
    monkeypatch, dispatches
):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)
    keys = [f"private/photo-{index}.jpg" for index in range(100)]

    await storage.signed_urls(keys)
    result = await storage.signed_urls(keys)

    assert factory.endpoints == [PHOTO_ENDPOINT]
    assert len(dispatches) == 2
    assert result.failed == ()
    assert list(result.urls) == keys


async def test_each_signing_endpoint_gets_its_own_client(monkeypatch):
    factory = FakeClientFactory()
    storage, settings = build_storage(monkeypatch, factory)

    first = await storage.signed_urls(["private/one.jpg"])
    settings.storage_signing_endpoint_url = SECOND_SIGNING_ENDPOINT
    second = await storage.signed_urls(["private/two.jpg"])

    assert factory.endpoints == [PHOTO_ENDPOINT, SECOND_SIGNING_ENDPOINT]
    assert first.urls["private/one.jpg"] == f"{PHOTO_ENDPOINT}/signed/private/one.jpg"
    assert (
        second.urls["private/two.jpg"]
        == f"{SECOND_SIGNING_ENDPOINT}/signed/private/two.jpg"
    )
    assert UPLOAD_ENDPOINT not in factory.endpoints


async def test_concurrent_cold_requests_build_exactly_one_client(monkeypatch):
    factory = BlockingClientFactory()
    storage, _ = build_storage(monkeypatch, factory)
    arrivals = []
    both_in_flight = threading.Event()
    original_sign_many = storage._sign_many

    def tracking_sign_many(endpoint, keys, ttl):
        arrivals.append(keys)
        if len(arrivals) == 2:
            both_in_flight.set()
        return original_sign_many(endpoint, keys, ttl)

    monkeypatch.setattr(storage, "_sign_many", tracking_sign_many)

    first = asyncio.create_task(storage.signed_urls(["private/first.jpg"]))
    assert await asyncio.to_thread(factory.build_started.wait, 5), (
        "el constructor no se invocó"
    )

    second = asyncio.create_task(storage.signed_urls(["private/second.jpg"]))
    assert await asyncio.to_thread(both_in_flight.wait, 5), (
        "la segunda firma no llegó al almacenamiento"
    )
    # La construcción sigue bloqueada y la segunda petición espera en la caché.
    assert factory.clients == []

    factory.release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert factory.endpoints == [PHOTO_ENDPOINT]
    assert len(factory.clients) == 1
    assert first_result.urls["private/first.jpg"] == (
        f"{PHOTO_ENDPOINT}/signed/private/first.jpg"
    )
    assert second_result.urls["private/second.jpg"] == (
        f"{PHOTO_ENDPOINT}/signed/private/second.jpg"
    )


async def test_repeated_key_is_signed_once(monkeypatch):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)

    result = await storage.signed_urls(
        ["private/a.jpg", "private/a.jpg", "private/b.jpg", "private/a.jpg"]
    )

    assert list(result.urls) == ["private/a.jpg", "private/b.jpg"]
    assert result.failed == ()
    assert [call["key"] for call in factory.clients[0].calls] == [
        "private/a.jpg",
        "private/b.jpg",
    ]


async def test_invalid_keys_are_reported_without_reaching_the_client(monkeypatch):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)
    invalid_keys = ("", "/absolute/photo.jpg", "private/../other/photo.jpg")

    result = await storage.signed_urls([*invalid_keys, "private/valid.jpg"])

    assert set(result.failed) == set(invalid_keys)
    assert result.reason == "sign_failed"
    assert list(result.urls) == ["private/valid.jpg"]
    assert [call["key"] for call in factory.clients[0].calls] == ["private/valid.jpg"]


async def test_only_invalid_keys_build_no_client_and_dispatch_no_work(
    monkeypatch, dispatches
):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)

    result = await storage.signed_urls(["", "/absolute/photo.jpg", "../escape.jpg"])

    assert result.urls == {}
    assert set(result.failed) == {"", "/absolute/photo.jpg", "../escape.jpg"}
    assert result.reason == "sign_failed"
    assert factory.endpoints == []
    assert dispatches == []


async def test_one_failing_key_does_not_block_the_rest(monkeypatch):
    factory = FakeClientFactory(failing_keys={"private/broken.jpg"})
    storage, _ = build_storage(monkeypatch, factory)

    result = await storage.signed_urls(
        ["private/ok.jpg", "private/broken.jpg", "private/other.jpg"]
    )

    assert list(result.urls) == ["private/ok.jpg", "private/other.jpg"]
    assert result.failed == ("private/broken.jpg",)
    assert result.reason == "sign_failed"


async def test_build_failure_marks_every_key_and_the_next_call_retries(monkeypatch):
    factory = FakeClientFactory(fail_build=True)
    storage, _ = build_storage(monkeypatch, factory)

    failed = await storage.signed_urls(["private/a.jpg", "private/b.jpg"])

    assert failed.urls == {}
    assert failed.failed == ("private/a.jpg", "private/b.jpg")
    assert failed.reason == "build_failed"

    factory.fail_build = False
    retried = await storage.signed_urls(["private/a.jpg"])

    assert retried.urls == {
        "private/a.jpg": f"{PHOTO_ENDPOINT}/signed/private/a.jpg"
    }
    assert retried.failed == ()
    assert len(factory.endpoints) == 2


async def test_unsupported_provider_is_a_build_failure(monkeypatch):
    storage, _ = build_storage(monkeypatch, None, storage_provider="local")

    result = await storage.signed_urls(["private/a.jpg"])

    assert result.urls == {}
    assert result.failed == ("private/a.jpg",)
    assert result.reason == "build_failed"
    with pytest.raises(StorageError):
        await storage.signed_url("private/a.jpg")


async def test_signed_url_keeps_its_contract_and_uses_the_cached_client(monkeypatch):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)

    url = await storage.signed_url("private/photo.jpg")
    explicit_ttl = await storage.signed_url("private/photo.jpg", 600)

    assert url == f"{PHOTO_ENDPOINT}/signed/private/photo.jpg"
    assert explicit_ttl == url
    assert [call["expires"] for call in factory.clients[0].calls] == [300, 600]
    assert factory.endpoints == [PHOTO_ENDPOINT]


async def test_signed_url_raises_storage_error_for_invalid_keys(monkeypatch):
    factory = FakeClientFactory()
    storage, _ = build_storage(monkeypatch, factory)

    for key in ("", "/absolute/photo.jpg", "private/../other/photo.jpg"):
        with pytest.raises(StorageError, match="La clave del objeto no es válida"):
            await storage.signed_url(key)

    assert factory.endpoints == []


async def test_signed_url_raises_storage_error_when_the_signing_fails(monkeypatch):
    factory = FakeClientFactory(failing_keys={"private/photo.jpg"})
    storage, _ = build_storage(monkeypatch, factory)

    with pytest.raises(StorageError, match="No se pudo generar el enlace de la foto"):
        await storage.signed_url("private/photo.jpg")
