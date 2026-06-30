"""
test_api.py - Integration tests for core Argos API endpoints.

Tests:
  - Health check (GET /api/v1/ping)
  - Summary endpoint (GET /api/v1/summary)
  - RAG ingest (POST /api/v1/rag/ingest)
  - RAG history (GET /api/v1/rag/history)
  - RAG feedback (POST /api/v1/rag/feedback)
"""

import pytest

from app.core.config import settings
from app.core.logging_config import trace_id_ctx


def _payload_keys(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield key
            yield from _payload_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _payload_keys(item)


@pytest.mark.anyio
async def test_ping(client):
    """Health check should return status=ok."""
    response = await client.get("/api/v1/ping")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["message"] == "pong"


@pytest.mark.anyio
async def test_trace_id_header_does_not_leak_context(client):
    token = trace_id_ctx.set("outer-trace")
    try:
        response = await client.get("/api/v1/ping")
        assert response.status_code == 200
        assert response.headers["X-Trace-ID"]
        assert trace_id_ctx.get() == "outer-trace"
    finally:
        trace_id_ctx.reset(token)


@pytest.mark.anyio
async def test_security_headers_are_set(client):
    response = await client.get("/api/v1/ping")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


@pytest.mark.anyio
async def test_status_endpoint_reports_private_diagnostics_without_secrets(client):
    """Private diagnostics should expose readiness booleans, not raw secrets."""
    response = await client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] in {"ok", "degraded"}
    assert data["project"] == "Argos"
    assert data["database"]["ok"] is True
    assert isinstance(data["features"]["api_key_auth"], bool)
    assert isinstance(data["features"]["llm_configured"], bool)

    keys = {key.lower() for key in _payload_keys(data)}
    assert not {"api_key", "token", "password", "secret"} & keys


@pytest.mark.anyio
async def test_summary_endpoint_responds(client, monkeypatch):
    """Summary endpoint should return a controlled response without hitting external LLMs."""
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", None)

    response = await client.get("/api/v1/summary?force=true")

    assert response.status_code == 503
    assert "LLM API key 未配置" in response.json()["detail"]


@pytest.mark.anyio
async def test_summary_missing_llm_key_returns_503_before_adapter(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", None)

    def fail_get_adapter(source_type):
        raise AssertionError(f"adapter should not be loaded without LLM key: {source_type}")

    monkeypatch.setattr("app.services.source_adapters.get_adapter", fail_get_adapter)

    response = await client.get("/api/v1/summary?force=true")

    assert response.status_code == 503
    assert "LLM API key 未配置" in response.json()["detail"]


@pytest.mark.anyio
async def test_rag_disabled_by_default_returns_503(client):
    """RAG endpoints should be explicitly disabled in the lightweight default profile."""
    response = await client.post(
        "/api/v1/rag/query", json={"url": "https://example.com/never-ingested", "question": "test?"}
    )

    assert response.status_code == 503
    assert "RAG feature is disabled" in response.json()["detail"]


@pytest.mark.anyio
async def test_rag_ingest_rejects_empty(client, monkeypatch):
    """Ingest should reject an empty URL."""
    monkeypatch.setattr("app.core.config.settings.RAG_ENABLED", True)

    response = await client.post("/api/v1/rag/ingest", json={"url": ""})
    # Should fail validation or return error
    assert response.status_code in (422, 500)


@pytest.mark.anyio
async def test_rag_query_requires_ingest(client, monkeypatch):
    """Query should fail if URL hasn't been ingested."""
    monkeypatch.setattr("app.core.config.settings.RAG_ENABLED", True)

    response = await client.post(
        "/api/v1/rag/query", json={"url": "https://example.com/never-ingested", "question": "test?"}
    )
    assert response.status_code == 400


@pytest.mark.anyio
async def test_rag_history_returns_empty(client, monkeypatch):
    """History for an unknown URL should return empty list."""
    monkeypatch.setattr("app.core.config.settings.RAG_ENABLED", True)

    response = await client.get("/api/v1/rag/history", params={"url": "https://example.com/no-history"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["history"] == []


@pytest.mark.anyio
async def test_feedback_rejects_invalid_sentiment(client, monkeypatch):
    """Feedback should reject invalid sentiment values at the schema level."""
    monkeypatch.setattr("app.core.config.settings.RAG_ENABLED", True)

    response = await client.post("/api/v1/rag/feedback", json={"url": "https://example.com", "sentiment": 5})
    # Pydantic's Literal[1, -1, 0] validation triggers a 422 Unprocessable Entity.
    assert response.status_code == 422


@pytest.mark.anyio
async def test_feedback_accepts_valid_like(client, monkeypatch):
    """Feedback should accept a valid Like (+1)."""
    monkeypatch.setattr("app.core.config.settings.RAG_ENABLED", True)

    response = await client.post(
        "/api/v1/rag/feedback", json={"url": "https://example.com/test-article", "sentiment": 1}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
