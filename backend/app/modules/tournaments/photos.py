"""Photo presentation for responses that include player photos (RF-002 to RF-004).

The consent decision is made upstream by the SQL projection (``photo_url`` is
already ``null`` without consent), so this resolver only signs object keys and
applies the per-path failure policy:

- ``policy="null"`` (public endpoints): a failed signature leaves
  ``photo_url`` as ``null`` and the rest of the response is served.
- ``policy="error"`` (Workspace): a failed signature raises 503.

It signs a whole response with a single batch call, removes the object key from
the row so it cannot be serialized by accident, and logs one stable entry per
response without keys, names, documents or dates. It never opens a transaction
nor queries the database: callers must invoke it after their read transaction
has closed (N-2).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import HTTPException

from app.core.storage import ObjectStorage, SignedUrls, StorageError, get_object_storage

STORAGE_UNAVAILABLE_DETAIL = "El almacenamiento de fotos no está disponible"

_logger = logging.getLogger(__name__)


async def sign_photo_rows(
    rows: list[dict],
    *,
    key_field: str,
    value_field: str = "photo_url",
    consent_field: str | None = "photo_consent",
    policy: Literal["null", "error"] = "error",
    storage: ObjectStorage | None = None,
    logger: logging.Logger | None = None,
) -> list[dict]:
    """Resolve every photo in ``rows`` with one batch and apply the policy."""

    if policy not in {"null", "error"}:
        raise ValueError(f"Política de fotos desconocida: {policy}")
    log = logger or _logger

    keys: list[str] = []
    pending: list[tuple[dict, str | None]] = []
    for row in rows:
        key = row.get(key_field)
        consent = consent_field is None or bool(row.get(consent_field))
        usable = consent and isinstance(key, str) and bool(key)
        if usable:
            keys.append(key)
        pending.append((row, key if usable else None))

    unique_keys = tuple(dict.fromkeys(keys))
    urls: dict[str, str] = {}
    failed: tuple[str, ...] = ()
    reason: str | None = None
    if unique_keys:
        resolved = await _sign_batch(unique_keys, storage)
        urls = resolved.urls
        failed = resolved.failed
        reason = resolved.reason

    for row, key in pending:
        if key_field != value_field:
            row.pop(key_field, None)
        row[value_field] = urls.get(key) if key else None

    if failed:
        log.warning(
            "No se pudieron firmar %d fotos (%s)",
            len(failed),
            reason or "sign_failed",
        )
        if policy == "error":
            raise HTTPException(status_code=503, detail=STORAGE_UNAVAILABLE_DETAIL)
    return rows


async def _sign_batch(
    keys: tuple[str, ...],
    storage: ObjectStorage | None,
) -> SignedUrls:
    try:
        return await (storage or get_object_storage()).signed_urls(keys)
    except StorageError:
        return SignedUrls(urls={}, failed=keys, reason="sign_failed")
