"""
test_llm_client.py - Unit tests for the LLMClient abstraction layer.

Tests:
  - Config fallback: LLM_API_KEY falls back to DEEPSEEK_API_KEY
  - Config fallback: LLM_BASE_URL falls back to DEEPSEEK_BASE_URL
  - Model name is correctly propagated from settings
  - LLMClient.chat() injects model automatically
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Settings fallback logic
# ---------------------------------------------------------------------------

class TestSettingsFallback:
    """Verify ``effective_llm_*`` properties fall back to legacy values."""

    def test_llm_api_key_preferred_over_deepseek(self):
        from app.core.config import Settings

        s = Settings(
            LLM_API_KEY="new-key",
            DEEPSEEK_API_KEY="old-key",
            _env_file=None,
        )
        assert s.effective_llm_api_key == "new-key"

    def test_llm_api_key_falls_back_to_deepseek(self):
        from app.core.config import Settings

        s = Settings(
            LLM_API_KEY=None,
            DEEPSEEK_API_KEY="old-key",
            _env_file=None,
        )
        assert s.effective_llm_api_key == "old-key"

    def test_llm_base_url_preferred_over_deepseek(self):
        from app.core.config import Settings

        s = Settings(
            LLM_BASE_URL="https://api.openai.com/v1",
            DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
            _env_file=None,
        )
        assert s.effective_llm_base_url == "https://api.openai.com/v1"

    def test_llm_base_url_falls_back_to_deepseek(self):
        from app.core.config import Settings

        s = Settings(
            LLM_BASE_URL=None,
            DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
            _env_file=None,
        )
        assert s.effective_llm_base_url == "https://api.deepseek.com/v1"

    def test_default_model_name(self):
        from app.core.config import Settings

        s = Settings(_env_file=None)
        assert s.LLM_MODEL == "deepseek-chat"


# ---------------------------------------------------------------------------
# LLMClient initialisation
# ---------------------------------------------------------------------------

class TestLLMClientInit:
    """Verify ``LLMClient`` wires settings into the underlying OpenAI client."""

    def test_model_attribute_matches_settings(self):
        from app.services.llm.client import LLMClient

        fake_settings = MagicMock()
        fake_settings.LLM_MODEL = "gpt-4o-mini"
        fake_settings.effective_llm_api_key = "sk-test"
        fake_settings.effective_llm_base_url = "https://api.openai.com/v1"
        fake_settings.LLM_TIMEOUT = 60
        fake_settings.LLM_MAX_RETRIES = 2

        client = LLMClient(fake_settings)
        assert client.model == "gpt-4o-mini"

    def test_raw_returns_async_openai_instance(self):
        from openai import AsyncOpenAI

        from app.services.llm.client import LLMClient

        fake_settings = MagicMock()
        fake_settings.LLM_MODEL = "deepseek-chat"
        fake_settings.effective_llm_api_key = "sk-test"
        fake_settings.effective_llm_base_url = "https://api.deepseek.com/v1"
        fake_settings.LLM_TIMEOUT = 180
        fake_settings.LLM_MAX_RETRIES = 1

        client = LLMClient(fake_settings)
        assert isinstance(client.raw, AsyncOpenAI)


# ---------------------------------------------------------------------------
# LLMClient.chat() auto-injects model
# ---------------------------------------------------------------------------

class TestLLMClientChat:
    """Verify ``chat()`` delegates correctly to the underlying OpenAI client."""

    @pytest.mark.anyio
    async def test_chat_injects_model(self):
        from app.services.llm.client import LLMClient

        fake_settings = MagicMock()
        fake_settings.LLM_MODEL = "test-model"
        fake_settings.effective_llm_api_key = "sk-test"
        fake_settings.effective_llm_base_url = "https://example.com/v1"
        fake_settings.LLM_TIMEOUT = 30
        fake_settings.LLM_MAX_RETRIES = 0

        client = LLMClient(fake_settings)

        # Mock the inner openai client
        mock_response = MagicMock()
        mock_response.usage = None
        client._client.chat.completions.create = AsyncMock(return_value=mock_response)

        # Patch metrics to avoid Redis dependency
        with patch("app.services.metrics_service.metrics_service") as mock_metrics:
            mock_metrics.record_tokens = AsyncMock()
            mock_metrics.record_latency = AsyncMock()

            await client.chat(messages=[{"role": "user", "content": "hi"}])

        # Assert model was passed through
        call_kwargs = client._client.chat.completions.create.call_args
        assert call_kwargs.kwargs.get("model") == "test-model"


# ---------------------------------------------------------------------------
# Adaptive parameter fallback (temperature rejection, max_tokens variants)
# ---------------------------------------------------------------------------

def _fake_settings(model="test-model", base_url="https://example.com/v1"):
    s = MagicMock()
    s.LLM_MODEL = model
    s.effective_llm_api_key = "sk-test"
    s.effective_llm_base_url = base_url
    s.LLM_TIMEOUT = 30
    s.LLM_MAX_RETRIES = 0
    s.FAST_LLM = ""
    s.SMART_LLM = ""
    return s


class TestAdaptiveParameterFallback:
    """Verify ``chat()`` recovers from provider parameter rejections."""

    @pytest.mark.anyio
    async def test_retries_without_temperature_and_does_not_trip_breaker(self):
        from app.services.llm.client import LLMClient

        client = LLMClient(_fake_settings())

        ok = MagicMock()
        ok.usage = None
        # First call raises a temperature-rejection error, second succeeds.
        client._client.chat.completions.create = AsyncMock(
            side_effect=[
                Exception("temperature is not supported with this model"),
                ok,
            ]
        )

        with patch("app.services.metrics_service.metrics_service") as m:
            m.record_tokens = AsyncMock()
            m.record_latency = AsyncMock()
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.7,
            )

        # Retried exactly once (two create() calls total).
        assert client._client.chat.completions.create.call_count == 2
        # Second call dropped temperature.
        second = client._client.chat.completions.create.call_args_list[1]
        assert "temperature" not in second.kwargs
        # Capability learned, and the absorbed error did NOT open the breaker.
        key = client._cap_key("example.com", "test-model")
        assert key in client._unsupported_temperature
        assert not client.circuit_breaker.is_open("example.com", "test-model")

    @pytest.mark.anyio
    async def test_strips_temperature_upfront_on_known_endpoint(self):
        from app.services.llm.client import LLMClient

        client = LLMClient(_fake_settings())
        client._unsupported_temperature.add(client._cap_key("example.com", "test-model"))

        ok = MagicMock()
        ok.usage = None
        client._client.chat.completions.create = AsyncMock(return_value=ok)

        with patch("app.services.metrics_service.metrics_service") as m:
            m.record_tokens = AsyncMock()
            m.record_latency = AsyncMock()
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.7,
            )

        # No retry needed; temperature stripped before the first call.
        assert client._client.chat.completions.create.call_count == 1
        first = client._client.chat.completions.create.call_args_list[0]
        assert "temperature" not in first.kwargs

    @pytest.mark.anyio
    async def test_renames_max_tokens_to_max_completion_tokens(self):
        from app.services.llm.client import LLMClient

        client = LLMClient(_fake_settings())

        ok = MagicMock()
        ok.usage = None
        client._client.chat.completions.create = AsyncMock(
            side_effect=[
                Exception(
                    "Use 'max_completion_tokens' instead of 'max_tokens'"
                ),
                ok,
            ]
        )

        with patch("app.services.metrics_service.metrics_service") as m:
            m.record_tokens = AsyncMock()
            m.record_latency = AsyncMock()
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1000,
            )

        second = client._client.chat.completions.create.call_args_list[1]
        assert "max_tokens" not in second.kwargs
        assert second.kwargs.get("max_completion_tokens") == 1000

    @pytest.mark.anyio
    async def test_unrecoverable_error_records_failure_and_raises(self):
        from app.services.llm.client import LLMClient

        client = LLMClient(_fake_settings())
        client._client.chat.completions.create = AsyncMock(
            side_effect=Exception("503 service unavailable")
        )

        with patch("app.services.metrics_service.metrics_service") as m:
            m.record_tokens = AsyncMock()
            m.record_latency = AsyncMock()
            with pytest.raises(Exception, match="service unavailable"):
                await client.chat(messages=[{"role": "user", "content": "hi"}])

        # No retry for unrecoverable errors; failure recorded once.
        assert client._client.chat.completions.create.call_count == 1
