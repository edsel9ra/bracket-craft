"""Batch signing for responses that mix player photos and team crests (T5).

The resolver makes **one** ``ObjectStorage.signed_urls`` call per response,
deduplicates the keys of every group, replaces each internal key by the signed
link (or ``None``) and removes the key from the row. It never opens a
transaction nor queries the database: the caller must invoke it after its read
transaction closed (the test closes the session first and observes
``in_transaction()`` at signing time).

Failure policy: ``error`` raises 503 ``CREST_STORAGE_UNAVAILABLE`` (Workspace),
``null`` leaves the field at ``None`` and serves the rest (public surfaces). One
stable log entry per response, never per key, without keys, names or
``Content-Type``.
"""

from __future__ import annotations

import inspect
import json
import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import SignedUrls, StorageError
from app.modules.crests.errors import CREST_STORAGE_UNAVAILABLE, CrestError
from app.modules.crests.resolver import (
    MediaGroup,
    sign_crest_rows,
    sign_media_rows,
)

LOGGER_NAME = "tests.crest_resolver"
URL_BASE = "https://signed.test/"


class FakeStorage:
    """Storage double: one batch call, configurable failures, no network."""

    def __init__(
        self,
        *,
        fail_keys=(),
        reason: str | None = None,
        error: Exception | None = None,
        on_sign=None,
    ) -> None:
        self.fail_keys = set(fail_keys)
        self.reason = reason
        self.error = error
        self.on_sign = on_sign
        self.calls: list[tuple[str, ...]] = []

    async def signed_urls(self, keys, expires_seconds=None):
        keys = tuple(keys)
        self.calls.append(keys)
        if self.on_sign is not None:
            self.on_sign(keys)
        if self.error is not None:
            raise self.error
        urls = {key: f"{URL_BASE}{key}" for key in keys if key not in self.fail_keys}
        failed = tuple(key for key in keys if key not in urls)
        return SignedUrls(
            urls=urls,
            failed=failed,
            reason=self.reason if failed else None,
        )


def photo_row(key, consent: bool | None = True) -> dict:
    row: dict = {"player_id": "player", "photo_object_key": key}
    if consent is not None:
        row["photo_consent"] = consent
    return row


def crest_row(key) -> dict:
    return {"team_id": "team", "crest_object_key": key}


def photo_group(rows: list[dict]) -> MediaGroup:
    return MediaGroup(
        rows=rows,
        key_field="photo_object_key",
        value_field="photo_url",
        consent_field="photo_consent",
    )


def crest_group(rows: list[dict]) -> MediaGroup:
    return MediaGroup(rows=rows, key_field="crest_object_key", value_field="crest_url")


def log_records(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER_NAME]


# ---------------------------------------------------------------------------
# One batch, mixed groups, deduplication and key removal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sign_media_rows_signs_photos_and_crests_in_one_batch(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    photos = [
        photo_row("photos/one.jpg"),
        photo_row("photos/two.png"),
        photo_row(None),
        photo_row("photos/no-consent.webp", consent=False),
    ]
    crests = [crest_row("crests/a.webp"), crest_row("photos/one.jpg")]
    storage = FakeStorage()

    result = await sign_media_rows(
        [photo_group(photos), crest_group(crests)],
        policy="error",
        storage=storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    assert result is None
    assert len(storage.calls) == 1
    # One batch with the unique keys of both groups, first-seen order preserved.
    assert storage.calls[0] == (
        "photos/one.jpg",
        "photos/two.png",
        "crests/a.webp",
    )

    assert photos[0]["photo_url"] == f"{URL_BASE}photos/one.jpg"
    assert photos[1]["photo_url"] == f"{URL_BASE}photos/two.png"
    assert photos[2]["photo_url"] is None
    assert photos[3]["photo_url"] is None  # no consent: never signed
    assert crests[0]["crest_url"] == f"{URL_BASE}crests/a.webp"
    assert crests[1]["crest_url"] == f"{URL_BASE}photos/one.jpg"  # deduplicated

    for row in photos + crests:
        assert "photo_object_key" not in row
        assert "crest_object_key" not in row
    serialized = json.dumps(photos + crests)
    assert "object_key" not in serialized
    assert "private/" not in serialized
    assert log_records(caplog) == []


@pytest.mark.asyncio
async def test_sign_media_rows_deduplicates_keys_across_groups_in_first_seen_order():
    first = [{"crest_object_key": "k/b.png"}, {"crest_object_key": "k/a.jpg"}]
    second = [{"crest_object_key": "k/b.png"}, {"crest_object_key": "k/c.webp"}]
    third = [{"crest_object_key": "k/a.jpg"}]
    storage = FakeStorage()

    await sign_media_rows(
        [crest_group(first), crest_group(second), crest_group(third)],
        policy="null",
        storage=storage,
    )

    assert storage.calls == [("k/b.png", "k/a.jpg", "k/c.webp")]
    assert first[0]["crest_url"] == f"{URL_BASE}k/b.png"
    assert second[0]["crest_url"] == f"{URL_BASE}k/b.png"


@pytest.mark.asyncio
async def test_sign_media_rows_without_keys_does_not_call_the_storage(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    photos = [photo_row(None), photo_row("", consent=True)]
    crests = [crest_row(None), crest_row("")]
    storage = FakeStorage()

    await sign_media_rows(
        [photo_group(photos), crest_group(crests)],
        policy="error",
        storage=storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    assert storage.calls == []
    assert all(row["photo_url"] is None for row in photos)
    assert all(row["crest_url"] is None for row in crests)
    assert log_records(caplog) == []


# ---------------------------------------------------------------------------
# Failure policy: error raises 503; null degrades to None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_error_raises_storage_unavailable_and_logs_once(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    photos = [photo_row("photos/ok.jpg"), photo_row("photos/broken.jpg")]
    crests = [crest_row("crests/broken.webp")]
    storage = FakeStorage(
        fail_keys={"photos/broken.jpg", "crests/broken.webp"},
        reason="sign_failed",
    )

    with pytest.raises(CrestError) as error:
        await sign_media_rows(
            [photo_group(photos), crest_group(crests)],
            policy="error",
            storage=storage,
            logger=logging.getLogger(LOGGER_NAME),
        )

    assert error.value.code == CREST_STORAGE_UNAVAILABLE
    assert error.value.status_code == 503
    assert isinstance(error.value.detail, str)

    records = log_records(caplog)
    assert len(records) == 1  # one entry per response, not per key
    message = records[0].getMessage()
    assert "2" in message
    assert "sign_failed" in message
    for key in ("photos/broken.jpg", "crests/broken.webp", "private/"):
        assert key not in message


@pytest.mark.asyncio
async def test_policy_error_on_a_total_storage_error_is_sanitized(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    photos = [photo_row("photos/one.jpg")]
    storage = FakeStorage(error=StorageError("backend down at private/bucket"))

    with pytest.raises(CrestError) as error:
        await sign_media_rows(
            [photo_group(photos)],
            policy="error",
            storage=storage,
            logger=logging.getLogger(LOGGER_NAME),
        )

    assert error.value.code == CREST_STORAGE_UNAVAILABLE
    assert "backend down" not in str(error.value.detail)
    assert "private/bucket" not in str(error.value.detail)

    records = log_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert "sign_failed" in message
    assert "backend down" not in message
    assert "private/bucket" not in message


@pytest.mark.asyncio
async def test_policy_null_degrades_only_the_failed_keys_and_logs_once(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    photos = [photo_row("photos/ok.jpg"), photo_row("photos/broken.jpg")]
    crests = [crest_row("crests/ok.webp")]
    storage = FakeStorage(fail_keys={"photos/broken.jpg"}, reason="sign_failed")

    await sign_media_rows(
        [photo_group(photos), crest_group(crests)],
        policy="null",
        storage=storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    assert photos[0]["photo_url"] == f"{URL_BASE}photos/ok.jpg"
    assert photos[1]["photo_url"] is None
    assert crests[0]["crest_url"] == f"{URL_BASE}crests/ok.webp"
    for row in photos + crests:
        assert "photo_object_key" not in row
        assert "crest_object_key" not in row

    records = log_records(caplog)
    assert len(records) == 1
    assert "1" in records[0].getMessage()
    assert "sign_failed" in records[0].getMessage()


@pytest.mark.asyncio
async def test_policy_null_on_a_total_storage_error_serves_none(caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    crests = [crest_row("crests/a.webp"), crest_row("crests/b.webp")]
    storage = FakeStorage(error=StorageError("unreachable"))

    await sign_media_rows(
        [crest_group(crests)],
        policy="null",
        storage=storage,
        logger=logging.getLogger(LOGGER_NAME),
    )

    assert [row["crest_url"] for row in crests] == [None, None]
    assert all("crest_object_key" not in row for row in crests)
    records = log_records(caplog)
    assert len(records) == 1
    assert "2" in records[0].getMessage()


@pytest.mark.asyncio
async def test_an_unknown_policy_is_rejected_before_signing():
    storage = FakeStorage()
    rows = [crest_row("crests/a.webp")]

    with pytest.raises(ValueError):
        await sign_media_rows(
            [crest_group(rows)], policy="ignore", storage=storage
        )

    assert storage.calls == []
    assert rows[0]["crest_object_key"] == "crests/a.webp"


# ---------------------------------------------------------------------------
# No transaction: the caller closes it before signing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sign_media_rows_runs_without_an_open_transaction():
    session = AsyncSession()
    observations: list[bool] = []

    def observe(_keys):
        observations.append(session.in_transaction())

    storage = FakeStorage(on_sign=observe)
    try:
        await sign_media_rows(
            [photo_group([photo_row("photos/one.jpg")])],
            policy="error",
            storage=storage,
        )
    finally:
        await session.close()

    assert storage.calls == [("photos/one.jpg",)]
    assert observations == [False]

    # The resolver cannot even receive a session: the caller owns the
    # transaction and closes it before calling.
    parameters = set(inspect.signature(sign_media_rows).parameters)
    assert parameters.isdisjoint({"session", "db", "database", "connection"})


# ---------------------------------------------------------------------------
# Crest-only wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sign_crest_rows_wraps_a_single_crest_group():
    rows = [crest_row("crests/a.webp"), crest_row(None)]
    storage = FakeStorage()

    result = await sign_crest_rows(rows, policy="error", storage=storage)

    assert result is rows
    assert storage.calls == [("crests/a.webp",)]
    assert rows[0]["crest_url"] == f"{URL_BASE}crests/a.webp"
    assert rows[1]["crest_url"] is None
    assert all("crest_object_key" not in row for row in rows)


@pytest.mark.asyncio
async def test_sign_crest_rows_propagates_the_error_policy():
    storage = FakeStorage(fail_keys={"crests/a.webp"}, reason="sign_failed")

    with pytest.raises(CrestError) as error:
        await sign_crest_rows(
            [crest_row("crests/a.webp")], policy="error", storage=storage
        )

    assert error.value.code == CREST_STORAGE_UNAVAILABLE
