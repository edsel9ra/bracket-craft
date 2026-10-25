"""Batch signing for responses that mix player photos and team crests (RF-44).

Each response gets **one** ``ObjectStorage.signed_urls`` call with every unique
key of every group, whatever their type: player photos (``photo_object_key`` →
``photo_url``, only with image consent) and team crests (``crest_object_key`` →
``crest_url``, no consent involved). The internal key is removed from the row so
it can never be serialized by accident.

Failure policy:

- ``policy="error"`` (Workspace surfaces): a failed signature raises 503
  ``CREST_STORAGE_UNAVAILABLE``.
- ``policy="null"`` (public surfaces): the failed field stays ``None`` and the
  rest of the response is served.

Exactly one stable log entry is written per response —never per key— with the
failure count and a stable reason, and without keys, file names, sizes or
``Content-Type``. The resolver never opens a transaction nor queries the
database: callers must invoke it after their read transaction has closed (N-2).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Sequence

from app.core.storage import (
    ObjectStorage,
    SignedUrls,
    StorageError,
    get_object_storage,
)
from app.modules.crests.errors import CREST_STORAGE_UNAVAILABLE, CrestError

MediaPolicy = Literal["null", "error"]

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaGroup:
    """A set of response rows that share one key field and one value field.

    ``consent_field`` is ``None`` for content that needs no consent (team
    crests); the player photos pass ``"photo_consent"`` so a photo without
    consent is never signed and its field stays ``None``.
    """

    rows: list[dict]
    key_field: str
    value_field: str
    consent_field: str | None = None


async def sign_media_rows(
    groups: Sequence[MediaGroup],
    *,
    policy: MediaPolicy = "error",
    storage: ObjectStorage | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Resolve every media key of every group with one batch, in place.

    The caller owns the transaction: this function must run after it closed.
    """

    if policy not in {"null", "error"}:
        raise ValueError(f"Política de medios desconocida: {policy}")
    log = logger or _LOGGER

    keys: list[str] = []
    pending: list[tuple[MediaGroup, dict, str | None]] = []
    for group in groups:
        for row in group.rows:
            key = row.get(group.key_field)
            consent = group.consent_field is None or bool(
                row.get(group.consent_field)
            )
            usable = consent and isinstance(key, str) and bool(key)
            if usable:
                keys.append(key)
            pending.append((group, row, key if usable else None))

    unique_keys = tuple(dict.fromkeys(keys))
    urls: dict[str, str] = {}
    failed: tuple[str, ...] = ()
    reason: str | None = None
    if unique_keys:
        resolved = await _sign_batch(unique_keys, storage)
        urls = resolved.urls
        failed = resolved.failed
        reason = resolved.reason

    for group, row, key in pending:
        if group.key_field != group.value_field:
            row.pop(group.key_field, None)
        row[group.value_field] = urls.get(key) if key else None

    if failed:
        log.warning(
            "No se pudieron firmar %d enlaces de imagen (%s)",
            len(failed),
            reason or "sign_failed",
        )
        if policy == "error":
            raise CrestError(CREST_STORAGE_UNAVAILABLE)


async def sign_crest_rows(
    rows: list[dict],
    *,
    policy: MediaPolicy = "error",
    storage: ObjectStorage | None = None,
    logger: logging.Logger | None = None,
    key_field: str = "crest_object_key",
    value_field: str = "crest_url",
) -> list[dict]:
    """Sign a response that only carries crest keys (``crest_url``)."""

    await sign_media_rows(
        [
            MediaGroup(
                rows=rows,
                key_field=key_field,
                value_field=value_field,
            )
        ],
        policy=policy,
        storage=storage,
        logger=logger,
    )
    return rows


async def _sign_batch(
    keys: tuple[str, ...],
    storage: ObjectStorage | None,
) -> SignedUrls:
    try:
        return await (storage or get_object_storage()).signed_urls(keys)
    except StorageError:
        return SignedUrls(urls={}, failed=keys, reason="sign_failed")
