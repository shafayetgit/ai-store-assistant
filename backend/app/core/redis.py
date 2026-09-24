from collections.abc import AsyncGenerator
import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings

# Global connection pool
redis_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=20,
    decode_responses=True,
)


def get_redis_client() -> Redis:
    """Returns a standalone async Redis client instance from the pool."""
    return aioredis.Redis(connection_pool=redis_pool)


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI Dependency providing an async Redis client."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def close_redis_pool() -> None:
    """Closes the Redis connection pool cleanly on shutdown."""
    await redis_pool.disconnect()