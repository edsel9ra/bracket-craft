from redis.asyncio import Redis

from app.core.config import get_settings


_client: Redis | None = None


def get_redis_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis_client() -> None:
    global _client
    client, _client = _client, None
    if client is not None:
        await client.aclose()
