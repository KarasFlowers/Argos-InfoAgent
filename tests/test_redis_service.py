import pytest

from app.services import redis_service as redis_module
from app.services.redis_service import RedisService


@pytest.mark.anyio
async def test_redis_failure_cooldown_skips_reconnect_then_recovers(monkeypatch):
    service = RedisService()
    now = 1000.0
    connection_attempts = 0

    monkeypatch.setattr(redis_module.time, "monotonic", lambda: now)

    class FailingRedis:
        async def ping(self):
            raise TimeoutError("redis unavailable")

        async def aclose(self):
            pass

    def failing_from_url(*args, **kwargs):
        nonlocal connection_attempts
        connection_attempts += 1
        return FailingRedis()

    monkeypatch.setattr(redis_module.Redis, "from_url", staticmethod(failing_from_url))

    assert await service.get_cache("rss_feed_test") is None
    assert connection_attempts == 1

    assert await service.set_cache("rss_feed_test", {"ok": True}) is False
    assert connection_attempts == 1

    class HealthyRedis:
        def __init__(self):
            self.saved = None

        async def ping(self):
            return True

        async def get(self, key):
            return '{"ok": true}'

        async def setex(self, key, expire_seconds, value):
            self.saved = (key, expire_seconds, value)

        async def aclose(self):
            pass

    healthy = HealthyRedis()

    def healthy_from_url(*args, **kwargs):
        nonlocal connection_attempts
        connection_attempts += 1
        return healthy

    now = 1061.0
    monkeypatch.setattr(redis_module.Redis, "from_url", staticmethod(healthy_from_url))

    assert await service.get_cache("rss_feed_test") == {"ok": True}
    assert connection_attempts == 2
    assert await service.set_cache("rss_feed_test", {"ok": True}) is True
    assert healthy.saved is not None
