import json
import logging

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self):
        self._redis: Redis | None = None

    async def get_client(self) -> Redis | None:
        if self._redis is not None:
            # Verify existing connection is still alive
            try:
                await self._redis.ping()
                return self._redis
            except Exception:
                # Connection lost — reset and fall through to reconnect
                logger.info("Redis connection lost, attempting reconnect...")
                try:
                    await self._redis.aclose()
                except Exception:
                    pass
                self._redis = None

        # Attempt (re)connection
        try:
            self._redis = Redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=2.0,
                retry_on_timeout=True,
            )
            await self._redis.ping()
            logger.info("Successfully connected to Redis.")
        except Exception as e:
            logger.warning("Failed to connect to Redis at %s: %s", settings.REDIS_URL, e)
            self._redis = None

        return self._redis

    async def get_cache(self, key: str) -> dict | None:
        """Retrieve and parse JSON data from Redis cache."""
        client = await self.get_client()
        if not client:
            return None

        try:
            cached_data = await client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.error("Error reading from Redis cache (%s): %s", key, e)

        return None

    async def set_cache(self, key: str, value: dict, expire_seconds: int = 900) -> bool:
        """Serialize and save data to Redis cache with expiration."""
        client = await self.get_client()
        if not client:
            return False

        try:
            serialized_value = json.dumps(value, ensure_ascii=False)
            await client.setex(key, expire_seconds, serialized_value)
            return True
        except Exception as e:
            logger.error("Error writing to Redis cache (%s): %s", key, e)
            return False

    async def close(self) -> None:
        """Gracefully close the Redis connection (call on app shutdown)."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
                logger.debug("Redis connection closed")
            except Exception:
                pass
            self._redis = None


# Singleton instance
redis_service = RedisService()
