import hashlib

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings


ATOMIC_RATE_LIMIT_SCRIPT = """
local window = tonumber(ARGV[1])
local exceeded = 0
for index, key in ipairs(KEYS) do
    local current = redis.call('INCR', key)
    if current == 1 or redis.call('TTL', key) < 0 then
        redis.call('EXPIRE', key, window)
    end
    if current > tonumber(ARGV[index + 1]) then
        exceeded = 1
    end
end
return exceeded
"""


def _rate_limit_key(identity: str) -> str:
    return "bracket-craft:rate:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def build_rate_limit_keys(
    request: Request,
    bucket: str,
    account_identifier: str | None = None,
    connection_identifier: str | None = None,
) -> list[str]:
    client_host = request.client.host if request.client else "unknown"
    keys = [_rate_limit_key(f"{bucket}:ip:{client_host}")]
    if account_identifier:
        keys.append(_rate_limit_key(f"{bucket}:account:{account_identifier.strip().casefold()}"))
    if connection_identifier:
        keys.append(_rate_limit_key(f"{bucket}:connection:{connection_identifier}"))
    return keys


def _validate_request_size(request: Request, max_body_bytes: int | None) -> None:
    if max_body_bytes is None:
        return
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is None:
        return
    try:
        content_length = int(raw_content_length)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content-Length inválido") from None
    if content_length < 0 or content_length > max_body_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="La solicitud supera el tamaño máximo permitido")


async def enforce_rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    window_seconds: int,
    *,
    account_identifier: str | None = None,
    connection_identifier: str | None = None,
    max_body_bytes: int | None = None,
) -> None:
    _validate_request_size(request, max_body_bytes)
    keys = build_rate_limit_keys(request, bucket, account_identifier, connection_identifier)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        exceeded = await redis.eval(
            ATOMIC_RATE_LIMIT_SCRIPT,
            len(keys),
            *keys,
            str(window_seconds),
            *(str(limit) for _ in keys),
        )
        if int(exceeded) == 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes. Inténtalo de nuevo más tarde.",
                headers={"Retry-After": str(window_seconds)},
            )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El control de acceso no está disponible temporalmente",
        ) from exc
    finally:
        await redis.aclose()
