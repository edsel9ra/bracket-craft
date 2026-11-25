"""Entrega de webhooks desde el worker (spec 047, RF-006–RF-011, RNF-002)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import text

from app.modules.webhooks.catalog import REQUEST_TIMEOUT_SECONDS, serialize_body, signature_headers
from app.modules.webhooks.network import TargetRejected, resolve_target

TargetResolver = Callable[[str, int], Awaitable[list[str]]]

logger = logging.getLogger(__name__)


def build_client(**options: Any) -> httpx.AsyncClient:
    """Cliente sin redirecciones ni proxies del entorno: la conexión va a la IP comprobada."""

    return httpx.AsyncClient(follow_redirects=False, trust_env=False, **options)


def _ip_url(ip: str, port: int, path: str, query: str) -> str:
    host = f"[{ip}]" if ":" in ip else ip
    return f"https://{host}:{port}{path or '/'}" + (f"?{query}" if query else "")


async def _record(db, event_id: str, outcome: str, status_code: int | None) -> str:
    async with db.begin():
        return (await db.execute(
            text("SELECT record_webhook_attempt(:id, :outcome, :status)"),
            {"id": event_id, "outcome": outcome, "status": status_code},
        )).scalar_one()


async def deliver_webhook(
    db,
    event: Mapping[str, Any],
    *,
    key: str,
    client: httpx.AsyncClient,
    resolve: TargetResolver = resolve_target,
    now: Callable[[], float] = time.time,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Hace un intento y devuelve el estado de la entrega (``discarded`` si ya no procede)."""

    event_id = str(event["id"])
    async with db.begin():
        target = (await db.execute(
            text("SELECT webhook_claimed_delivery(:id, :key)"), {"id": event_id, "key": key}
        )).scalar_one()
    if target is None:
        async with db.begin():
            await db.execute(text("SELECT complete_outbox_event(:id)"), {"id": event_id})
        return "discarded"

    parts = urlsplit(target["url"])
    host = (parts.hostname or "").lower()
    port = parts.port or 443
    try:
        ips = await resolve(host, port)
    except TargetRejected:
        logger.warning("Entrega de webhook %s rechazada: TargetRejected", event_id)
        return await _record(db, event_id, "rejected", None)

    body = serialize_body(target["body"])
    headers = signature_headers(
        target["secret"], event_type=target["event_type"], delivery_id=target["delivery_id"],
        timestamp=int(now()), body=body,
    )
    headers["Host"] = host if port == 443 else f"{host}:{port}"
    status_code: int | None = None
    try:
        async with asyncio.timeout(timeout):
            async with client.stream(
                "POST", _ip_url(ips[0], port, parts.path, parts.query), content=body, headers=headers,
                extensions={"sni_hostname": host},
            ) as response:
                status_code = response.status_code
    except (TimeoutError, httpx.HTTPError, OSError) as error:
        logger.warning("Entrega de webhook %s fallida: %s", event_id, type(error).__name__)
    outcome = "delivered" if status_code is not None and 200 <= status_code < 300 else "failed"
    return await _record(db, event_id, outcome, status_code)
