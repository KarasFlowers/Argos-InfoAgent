"""
Unified async LLM client wrapping any OpenAI-compatible API.

All LLM calls across the codebase should go through ``LLMClient.chat``
(non-streaming) or ``LLMClient.chat_stream`` (streaming) so that the
model name, API key, and base URL are configured in exactly one place.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Literal

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion

logger = logging.getLogger(__name__)

TierName = Literal["fast", "smart"]


class CircuitBreaker:
    """Thread-safe circuit breaker for LLM API calls.

    Tracks failures per (base_url, model) key.  When the number of failures
    within the rolling window exceeds *threshold*, the circuit opens for
    *open_duration* seconds.  While open, all calls are rejected immediately.
    After *open_duration* elapses the circuit enters half-open state and
    allows one probe call; if it succeeds the circuit closes, otherwise it
    re-opens.

    Inspired by Infinitum's MODEL_API_CIRCUIT_BREAKER_* pattern.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        window_seconds: float = 60.0,
        open_seconds: float = 180.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._open_seconds = open_seconds
        # key -> list of failure timestamps
        self._failures: dict[str, list[float]] = {}
        # key -> time when circuit was opened
        self._opened_at: dict[str, float] = {}
        # threading.Lock is intentional: the state-machine methods (record_failure,
        # is_open, reset) are synchronous and called from both sync and async
        # contexts.  Switching to asyncio.Lock would require making every
        # call-site await-able, which is not warranted by the current design.
        self._lock = threading.Lock()

    def _key(self, base_url: str, model: str) -> str:
        return f"{base_url}|{model}"

    def is_open(self, base_url: str, model: str) -> bool:
        """Return True if the circuit is currently open (calls should be rejected)."""
        key = self._key(base_url, model)
        with self._lock:
            opened_at = self._opened_at.get(key)
            if opened_at is None:
                return False
            elapsed = time.monotonic() - opened_at
            if elapsed < self._open_seconds:
                return True
            # Half-open: allow one probe call
            return False

    def record_success(self, base_url: str, model: str) -> None:
        """Record a successful call — close the circuit if it was half-open."""
        key = self._key(base_url, model)
        with self._lock:
            self._opened_at.pop(key, None)
            self._failures.pop(key, None)

    def record_failure(self, base_url: str, model: str) -> None:
        """Record a failed call. Opens the circuit if threshold is exceeded."""
        key = self._key(base_url, model)
        now = time.monotonic()
        with self._lock:
            failures = self._failures.setdefault(key, [])
            failures.append(now)
            # Prune failures outside the rolling window
            cutoff = now - self._window_seconds
            self._failures[key] = [t for t in failures if t > cutoff]
            if len(self._failures[key]) >= self._failure_threshold:
                self._opened_at[key] = now
                logger.warning(
                    "CircuitBreaker OPEN for %s (failures=%d in last %.0fs)",
                    key, len(self._failures[key]), self._window_seconds,
                )

    def reset(self, base_url: str | None = None, model: str | None = None) -> None:
        """Manually reset the circuit breaker state."""
        with self._lock:
            if base_url and model:
                key = self._key(base_url, model)
                self._failures.pop(key, None)
                self._opened_at.pop(key, None)
            else:
                self._failures.clear()
                self._opened_at.clear()


from app.core.llm_config import parse_tier_spec

# Backward-compatible alias for any external imports of the private name
_parse_tier_spec = parse_tier_spec


class LLMClient:
    """Provider-agnostic async LLM client with multi-tier routing.

    Wraps ``AsyncOpenAI`` and injects the configured model name so that
    callers never have to pass ``model=`` themselves.

    Supports ``tier="fast"`` or ``tier="smart"`` to route to different
    models. When a tier is not configured, falls back to the default model.

    Parameters are read from ``Settings.effective_llm_*`` properties,
    which fall back to the legacy ``DEEPSEEK_*`` variables when the new
    ``LLM_*`` variables are not set.
    """

    def __init__(self, settings: Any) -> None:
        self.model: str = settings.LLM_MODEL
        self._default_base_url: str = settings.effective_llm_base_url
        self._default_api_key: str | None = settings.effective_llm_api_key
        self._timeout: float = float(settings.LLM_TIMEOUT)
        self._max_retries: int = settings.LLM_MAX_RETRIES

        # Default client (used for "smart" tier and as fallback)
        self._client = AsyncOpenAI(
            api_key=self._default_api_key,
            base_url=self._default_base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )

        # Tier-specific clients and models (lazily populated)
        self._tier_clients: dict[str, AsyncOpenAI] = {}
        self._tier_models: dict[str, str] = {}

        # Parse tier specs
        self._tier_specs: dict[str, str] = {
            "fast": getattr(settings, "FAST_LLM", ""),
            "smart": getattr(settings, "SMART_LLM", ""),
        }

        # Circuit breaker shared across all tiers
        self._circuit_breaker = CircuitBreaker()

        # Learned per-endpoint capability caches, keyed by "base_url|model".
        # Populated lazily when a provider rejects a parameter, so subsequent
        # calls to the same endpoint skip the offending parameter up-front.
        self._unsupported_temperature: set[str] = set()
        self._needs_max_completion_tokens: set[str] = set()

        logger.info(
            "LLMClient initialised  model=%s  base_url=%s  fast=%s  smart=%s",
            self.model,
            self._default_base_url,
            self._tier_specs["fast"] or "(default)",
            self._tier_specs["smart"] or "(default)",
        )

    def _get_tier(self, tier: TierName | None) -> tuple[AsyncOpenAI, str]:
        """Resolve a tier to (client, model_name). Falls back to default."""
        if not tier:
            return self._client, self.model

        # Check cache
        if tier in self._tier_clients:
            return self._tier_clients[tier], self._tier_models[tier]

        # Parse spec
        spec = self._tier_specs.get(tier, "")
        parsed = parse_tier_spec(spec, self._default_base_url, self._default_api_key)
        if parsed is None:
            # No config for this tier — use default
            self._tier_clients[tier] = self._client
            self._tier_models[tier] = self.model
            return self._client, self.model

        base_url, api_key, model = parsed

        # Reuse default client if endpoint matches
        if base_url == self._default_base_url and api_key == self._default_api_key:
            self._tier_clients[tier] = self._client
            self._tier_models[tier] = model
        else:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
            self._tier_clients[tier] = client
            self._tier_models[tier] = model
            logger.info(
                "LLMClient tier '%s' → model=%s base_url=%s", tier, model, base_url
            )

        return self._tier_clients[tier], self._tier_models[tier]

    # ------------------------------------------------------------------
    # Adaptive parameter fallback
    # ------------------------------------------------------------------
    #
    # Some OpenAI-compatible providers reject parameters that DeepSeek and
    # most chat models accept: newer reasoning models reject ``temperature``
    # outright, and some require ``max_completion_tokens`` in place of the
    # legacy ``max_tokens``. We learn this lazily per endpoint on the first
    # rejection, then strip/rename the offending parameter on later calls so
    # the same endpoint never trips twice. Ported from Horizon's OpenAIClient.

    @staticmethod
    def _cap_key(base_url: str, model: str) -> str:
        return f"{base_url}|{model}"

    def _apply_capability_adjustments(self, key: str, kwargs: dict[str, Any]) -> None:
        """Strip/rename parameters this endpoint is already known to reject."""
        if key in self._unsupported_temperature:
            kwargs.pop("temperature", None)
        if key in self._needs_max_completion_tokens and "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

    @staticmethod
    def _is_temperature_unsupported(message: str) -> bool:
        lowered = message.lower()
        return "temperature" in lowered and (
            "deprecated" in lowered
            or "not support" in lowered
            or "unsupported" in lowered
            or "does not support" in lowered
        )

    @staticmethod
    def _needs_max_completion_tokens_param(message: str) -> bool:
        lowered = message.lower()
        return "max_completion_tokens" in lowered and "max_tokens" in lowered

    def _learn_from_error(self, key: str, kwargs: dict[str, Any], exc: Exception) -> bool:
        """Inspect an error; if it is a known recoverable parameter rejection,
        record the capability, mutate *kwargs* in place, and return True so the
        caller retries once. Return False for any other error (re-raise)."""
        message = str(exc)
        if "temperature" in kwargs and self._is_temperature_unsupported(message):
            self._unsupported_temperature.add(key)
            kwargs.pop("temperature", None)
            logger.info("LLM endpoint %s rejected temperature — retrying without it", key)
            return True
        if "max_tokens" in kwargs and self._needs_max_completion_tokens_param(message):
            self._needs_max_completion_tokens.add(key)
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
            logger.info("LLM endpoint %s requires max_completion_tokens — retrying", key)
            return True
        return False

    async def _create_with_fallback(
        self, client: AsyncOpenAI, cap_key: str, messages: list, kwargs: dict[str, Any]
    ):
        """Call ``chat.completions.create``; on a recoverable parameter
        rejection, adjust kwargs and retry. The absorbed error is not a circuit
        failure — only an unrecoverable error (or a still-failing call after all
        adjustments) is.

        The loop is provably bounded: ``_learn_from_error`` returns True only
        when it strips ``temperature`` or renames ``max_tokens``, and each of
        those can fire at most once (the param is then gone from kwargs), so at
        most two adjustments — three create() calls total — can occur.
        """
        while True:
            try:
                return await client.chat.completions.create(messages=messages, **kwargs)
            except Exception as exc:
                if not self._learn_from_error(cap_key, kwargs, exc):
                    raise

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tier: TierName | None = None,
        label: str = "",
        **kwargs: Any,
    ) -> "ChatCompletion":
        """Non-streaming chat completion.

        Automatically injects ``model`` and records token metrics.
        Callers may pass any extra ``openai`` kwargs (``temperature``,
        ``max_tokens``, ``response_format``, etc.).

        Args:
            tier: Route to "fast" or "smart" model. None uses default.
            label: Optional label for cost tracking (e.g. "scoring", "summary").
        """
        from app.services.metrics_service import metrics_service

        client, model = self._get_tier(tier)
        base_url = client.base_url.host if client.base_url else self._default_base_url

        # Check circuit breaker before attempting the call
        if self._circuit_breaker.is_open(base_url, model):
            raise CircuitOpenError(
                f"Circuit breaker is OPEN for {base_url}/{model} — "
                f"too many recent failures. Try again later or use a different tier."
            )

        kwargs.setdefault("model", model)
        cap_key = self._cap_key(base_url, model)
        self._apply_capability_adjustments(cap_key, kwargs)
        start = time.time()
        try:
            response = await self._create_with_fallback(
                client, cap_key, messages, kwargs
            )
        except Exception:
            self._circuit_breaker.record_failure(base_url, model)
            raise
        duration = time.time() - start

        self._circuit_breaker.record_success(base_url, model)

        if response.usage:
            await metrics_service.record_tokens(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                label=label,
            )
        await metrics_service.record_latency(duration)
        return response

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        tier: TierName | None = None,
        **kwargs: Any,
    ):
        """Streaming chat completion.

        Returns an async iterator of ``ChatCompletionChunk`` objects.
        The caller is responsible for extracting deltas and recording
        usage from the final chunk (when ``chunk.usage`` is set).

        ``stream=True`` and ``stream_options`` are injected automatically.
        """
        client, model = self._get_tier(tier)
        base_url = client.base_url.host if client.base_url else self._default_base_url

        if self._circuit_breaker.is_open(base_url, model):
            raise CircuitOpenError(
                f"Circuit breaker is OPEN for {base_url}/{model} — "
                f"too many recent failures. Try again later or use a different tier."
            )

        kwargs.setdefault("model", model)
        kwargs["stream"] = True
        kwargs.setdefault("stream_options", {"include_usage": True})
        cap_key = self._cap_key(base_url, model)
        self._apply_capability_adjustments(cap_key, kwargs)
        try:
            return await self._create_with_fallback(
                client, cap_key, messages, kwargs
            )
        except Exception:
            self._circuit_breaker.record_failure(base_url, model)
            raise

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Access the shared circuit breaker for inspection or manual reset."""
        return self._circuit_breaker

    @property
    def raw(self) -> AsyncOpenAI:
        """Escape-hatch for call-sites that still need the raw client."""
        return self._client


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is OPEN and the call is rejected."""
    pass
