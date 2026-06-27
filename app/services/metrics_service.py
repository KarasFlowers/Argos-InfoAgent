import logging
import statistics
from collections import defaultdict
from datetime import datetime

from app.services.redis_service import redis_service

logger = logging.getLogger(__name__)


class MetricsService:
    """Service to track and report daily LLM usage metrics.

    Uses Redis when available; falls back to an in-memory dict so that
    metrics still work (within the current process lifetime) even when
    Redis is not running.
    """

    def __init__(self):
        # In-memory fallback: {date_str: {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}}
        self._mem_tokens: dict[str, dict[str, int]] = defaultdict(
            lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )
        # In-memory fallback: {date_str: [float]}
        self._mem_latencies: dict[str, list[float]] = defaultdict(list)
        # Labeled cost tracking: {date_str: {label: {"prompt": int, "completion": int, "calls": int}}}
        self._mem_label_usage: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: {"prompt": 0, "completion": 0, "calls": 0})
        )

    @property
    def today_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    async def _get_client(self):
        return await redis_service.get_client()

    async def record_tokens(self, prompt: int, completion: int, label: str = "") -> None:
        """Increment the daily token count, optionally tagged by label."""
        date_str = self.today_str

        # Track per-label usage
        if label:
            self._mem_label_usage[date_str][label]["prompt"] += prompt
            self._mem_label_usage[date_str][label]["completion"] += completion
            self._mem_label_usage[date_str][label]["calls"] += 1

        # Always record in-memory (zero cost)
        self._mem_tokens[date_str]["prompt_tokens"] += prompt
        self._mem_tokens[date_str]["completion_tokens"] += completion
        self._mem_tokens[date_str]["total_tokens"] += prompt + completion

        client = await self._get_client()
        if not client:
            return

        key = f"metrics:tokens:{date_str}"
        try:
            # We use a pipeline for atomic increments
            async with client.pipeline(transaction=True) as pipe:
                pipe.hincrby(key, "prompt_tokens", prompt)
                pipe.hincrby(key, "completion_tokens", completion)
                pipe.hincrby(key, "total_tokens", prompt + completion)
                pipe.expire(key, 86400 * 7)  # keep for 7 days
                await pipe.execute()
        except Exception as e:
            logger.warning("Failed to record tokens in Redis: %s", e)

    async def record_latency(self, duration_sec: float) -> None:
        """Record a summary generation latency (in seconds) to a daily list."""
        date_str = self.today_str

        # Always record in-memory
        self._mem_latencies[date_str].append(duration_sec)

        client = await self._get_client()
        if not client:
            return

        key = f"metrics:latency:summary:{date_str}"
        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.rpush(key, str(duration_sec))
                pipe.expire(key, 86400 * 7)
                await pipe.execute()
        except Exception as e:
            logger.warning("Failed to record latency in Redis: %s", e)

    async def get_daily_metrics(self, date_str: str | None = None) -> dict:
        """Get aggregated metrics for the given date (default: today)."""
        if not date_str:
            date_str = self.today_str

        client = await self._get_client()
        if not client:
            return self._get_memory_metrics(date_str)

        token_key = f"metrics:tokens:{date_str}"
        latency_key = f"metrics:latency:summary:{date_str}"

        try:
            tokens = await client.hgetall(token_key)
            latency_strs = await client.lrange(latency_key, 0, -1)

            latencies = [float(x) for x in latency_strs if x]

            p50 = statistics.median(latencies) if latencies else 0.0
            p99 = (
                statistics.quantiles(latencies, n=100)[-1]
                if len(latencies) >= 2
                else (latencies[0] if latencies else 0.0)
            )

            return {
                "date": date_str,
                "tokens": {
                    "prompt": int(tokens.get("prompt_tokens", 0)),
                    "completion": int(tokens.get("completion_tokens", 0)),
                    "total": int(tokens.get("total_tokens", 0)),
                },
                "latency": {"count": len(latencies), "p50_sec": round(p50, 2), "p99_sec": round(p99, 2)},
            }
        except Exception as e:
            logger.warning("Failed to fetch metrics from Redis: %s", e)
            return self._get_memory_metrics(date_str)

    def _get_memory_metrics(self, date_str: str) -> dict:
        """Return metrics from in-memory fallback."""
        mem = self._mem_tokens.get(date_str, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        latencies = self._mem_latencies.get(date_str, [])

        p50 = statistics.median(latencies) if latencies else 0.0
        p99 = (
            statistics.quantiles(latencies, n=100)[-1] if len(latencies) >= 2 else (latencies[0] if latencies else 0.0)
        )

        return {
            "date": date_str,
            "tokens": {
                "prompt": mem["prompt_tokens"],
                "completion": mem["completion_tokens"],
                "total": mem["total_tokens"],
            },
            "latency": {
                "count": len(latencies),
                "p50_sec": round(p50, 2),
                "p99_sec": round(p99, 2),
            },
        }

    async def get_cost_breakdown(self, date_str: str | None = None) -> dict:
        """Get per-label token usage breakdown for a given date."""
        if not date_str:
            date_str = self.today_str

        label_data = self._mem_label_usage.get(date_str, {})
        breakdown = []
        for label, usage in sorted(label_data.items(), key=lambda x: x[1]["prompt"] + x[1]["completion"], reverse=True):
            breakdown.append(
                {
                    "label": label,
                    "prompt_tokens": usage["prompt"],
                    "completion_tokens": usage["completion"],
                    "total_tokens": usage["prompt"] + usage["completion"],
                    "calls": usage["calls"],
                }
            )

        return {
            "date": date_str,
            "breakdown": breakdown,
            "total_calls": sum(item["calls"] for item in breakdown),
            "total_tokens": sum(item["total_tokens"] for item in breakdown),
        }


metrics_service = MetricsService()
