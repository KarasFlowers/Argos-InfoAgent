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
from sqlalchemy import select

from app.api.routes import summary as summary_routes
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.logging_config import trace_id_ctx
from app.models.domain import Board, TaskRun
from app.models.schemas import DailySummaryResponse, SummaryItem


def _payload_keys(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield key
            yield from _payload_keys(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _payload_keys(item)


class AsyncNoop:
    async def __call__(self, *args, **kwargs):
        return None


class AsyncReturnFirstArg:
    async def __call__(self, first, *args, **kwargs):
        return first


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
async def test_lite_summary_preparation_skips_heavy_enrichments(monkeypatch):
    called = {"rerank": None, "explain": 0}

    async def fake_rerank(items, **kwargs):
        called["rerank"] = kwargs
        return items

    async def fail_heavy(*args, **kwargs):
        raise AssertionError("lite summary should not run heavy enrichments")

    async def fake_explain(summary, session, board_id):
        called["explain"] += 1
        return summary

    monkeypatch.setattr(summary_routes, "rerank_summary_items", fake_rerank)
    monkeypatch.setattr(summary_routes, "_mark_items_read", fail_heavy)
    monkeypatch.setattr(summary_routes, "_attach_auto_catchup", fail_heavy)
    monkeypatch.setattr(summary_routes, "_attach_event_tracks", fail_heavy)
    monkeypatch.setattr(summary_routes, "_attach_source_analysis", fail_heavy)
    monkeypatch.setattr(summary_routes, "enrich_summary_explanations", fake_explain)

    summary = DailySummaryResponse(
        date="2026-06-30",
        overview="Lite",
        top_news=[
            SummaryItem(
                headline="Lite headline",
                category="AI",
                key_points=["Fast path"],
                tags=[],
                original_link="https://example.com/lite",
                source="Example",
            )
        ],
    )

    result = await summary_routes._prepare_summary_response(
        session=object(),
        summary=summary,
        board_obj=object(),
        board_id=1,
        search_date="2026-06-30",
        date=None,
        lite=True,
    )

    assert result is summary
    assert called["rerank"]["use_vectors"] is False
    assert called["explain"] == 1


@pytest.mark.anyio
async def test_summary_force_success_creates_task_run(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", None)

    item = SummaryItem(
        headline="TaskRun headline",
        category="AI",
        key_points=["point"],
        original_link="https://example.com/taskrun",
        source="Example",
    )
    summary = DailySummaryResponse(
        date="2026-06-30",
        overview="Tracked summary",
        top_news=[item],
        source_stats={"Example": 1},
    )

    class Adapter:
        async def produce(self, **kwargs):
            await kwargs["task_ref"].start_stage("generating_summary", current=2, total=4)
            return summary, {}

    monkeypatch.setattr("app.services.source_adapters.get_adapter", lambda source_type: Adapter())
    monkeypatch.setattr("app.api.routes.summary._attach_auto_catchup", AsyncNoop())
    monkeypatch.setattr("app.api.routes.summary._attach_event_tracks", AsyncNoop())
    monkeypatch.setattr("app.api.routes.summary._attach_source_analysis", AsyncNoop())
    monkeypatch.setattr("app.api.routes.summary.enrich_summary_explanations", AsyncNoop())
    monkeypatch.setattr("app.api.routes.summary.rerank_summary_items", AsyncReturnFirstArg())

    response = await client.get("/api/v1/summary?force=true")

    assert response.status_code == 200
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TaskRun).where(TaskRun.kind == "summary_generation").order_by(TaskRun.id))
        task_run = result.scalars().all()[-1]
    assert task_run.status == "done"
    assert task_run.trigger_type == "manual/api"
    assert task_run.progress_label == "done"
    assert task_run.progress_current == 4
    assert task_run.ai_call_breakdown["item_count"] == 1


@pytest.mark.anyio
async def test_summary_force_failure_creates_failed_task_run(client, monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", None)

    class Adapter:
        async def produce(self, **kwargs):
            await kwargs["task_ref"].start_stage("generating_summary", current=2, total=4)
            raise RuntimeError("adapter exploded")

    monkeypatch.setattr("app.services.source_adapters.get_adapter", lambda source_type: Adapter())

    response = await client.get("/api/v1/summary?force=true")

    assert response.status_code == 500
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TaskRun).where(TaskRun.kind == "summary_generation").order_by(TaskRun.id))
        task_run = result.scalars().all()[-1]
    assert task_run.status == "failed"
    assert "adapter exploded" in task_run.error_summary
    assert task_run.progress_label == "generating_summary"


@pytest.mark.anyio
async def test_admin_tasks_filters_by_board_id(client):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Board).where(Board.slug == "tech"))
        board = result.scalar_one()
        session.add(TaskRun(kind="summary_generation", status="done", board_id=board.id))
        session.add(TaskRun(kind="summary_generation", status="done", board_id=None))
        await session.commit()

    response = await client.get(f"/api/v1/admin/tasks?kind=summary_generation&board_id={board.id}&status=done&limit=10")

    assert response.status_code == 200
    data = response.json()
    assert data
    assert {item["board_id"] for item in data} == {board.id}
    assert {item["status"] for item in data} == {"done"}


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
