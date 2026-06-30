import json
import logging
import time
from asyncio import Lock

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

REDIS_FAILURE_COOLDOWN_SECONDS = 60.0
REDIS_SOCKET_TIMEOUT_SECONDS = 0.5
REDIS_CONNECT_TIMEOUT_SECONDS = 0.5


class RedisService:
    def __init__(self):
        self._redis: Redis | None = None
        self._disabled_until: float = 0.0
        self._connect_lock = Lock()

    def _cooldown_active(self) -> bool:
        return time.monotonic() < self._disabled_until

    def _start_cooldown(self) -> None:
        self._disabled_until = time.monotonic() + REDIS_FAILURE_COOLDOWN_SECONDS

    def _clear_cooldown(self) -> None:
        self._disabled_until = 0.0

    async def get_client(self) -> Redis | None:
        if self._cooldown_active():
            return None

        if self._redis is not None:
            # Verify existing connection is still alive
            try:
                await self._redis.ping()
                self._clear_cooldown()
                return self._redis
            except Exception:
                # Connection lost — reset and fall through to reconnect
                logger.info("Redis connection lost, attempting reconnect...")
                try:
                    await self._redis.aclose()
                except Exception:
                    pass
                self._redis = None

        async with self._connect_lock:
            if self._cooldown_active():
                return None
            if self._redis is not None:
                try:
                    await self._redis.ping()
                    self._clear_cooldown()
                    return self._redis
                except Exception:
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
                    socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
                    socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
                    retry_on_timeout=False,
                )
                await self._redis.ping()
                self._clear_cooldown()
                logger.info("Successfully connected to Redis.")
            except Exception as e:
                logger.warning("Failed to connect to Redis at %s: %s", settings.REDIS_URL, e)
                self._redis = None
                self._start_cooldown()

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
        self._clear_cooldown()


# Singleton instance
redis_service = RedisService()
