"""
RAG API Router

Endpoints:
  POST /api/v1/rag/ingest  - scrape and index a URL into the vector store
  POST /api/v1/rag/query   - run the RAG pipeline and stream the answer via SSE
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from app.core.config import settings
from app.core.url_safety import validate_public_url
from app.services.chat_history_service import get_chat_history
from app.services.learning_service import record_feedback
from app.services.rag_service import (
    is_rag_available,
    _ingested_urls,
    _prepare_overview_context,
    get_ingest_status,
    get_db_cached_overview,
    ingest,
    query_stream,
    query_cross_article,
    stream_article_overview,
)

logger = logging.getLogger(__name__)


def _require_rag_enabled():
    """FastAPI dependency: reject requests with 503 when RAG is disabled."""
    if not settings.RAG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="RAG feature is disabled. Set RAG_ENABLED=true to enable.",
        )


rag_router = APIRouter(prefix="/rag", tags=["RAG"])



def _format_sse_data(message: str) -> str:
    normalized = message.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        f"data: {line}\n" if line else "data:\n"
        for line in normalized.split("\n")
    ) + "\n"


def _validate_public_url(value: AnyHttpUrl) -> AnyHttpUrl:
    return validate_public_url(value)


class PublicUrlRequest(BaseModel):
    url: AnyHttpUrl

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        return _validate_public_url(value)


class IngestRequest(PublicUrlRequest):
    pass


class QueryRequest(PublicUrlRequest):
    question: str = Field(min_length=1)
    history: list[dict] | None = Field(default=None, description="Optional chat history [{role,content}] to avoid DB round-trip")


class FeedbackRequest(PublicUrlRequest):
    sentiment: Literal[1, -1, 0]


class GlobalQueryRequest(BaseModel):
    question: str = Field(min_length=1)
    max_results: int = Field(default=10, ge=1, le=30)


@rag_router.get("/enabled")
async def rag_enabled_status():
    """Check whether RAG feature is enabled and available."""
    available = is_rag_available()
    return {
        "enabled": settings.RAG_ENABLED,
        "available": available,
        "message": (
            "RAG is ready." if available
            else "RAG is disabled." if not settings.RAG_ENABLED
            else "RAG dependencies not installed. Run: pip install -r requirements-rag.txt"
        ),
    }


@rag_router.get("/ingest_status", dependencies=[Depends(_require_rag_enabled)])
async def check_ingest_status(url: AnyHttpUrl = Query(...)):
    """Return the background ingestion status for a URL."""
    status = get_ingest_status(str(url))
    if status is None:
        return {"status": "unknown"}
    return status


@rag_router.post("/ingest", dependencies=[Depends(_require_rag_enabled)])
async def ingest_article(req: IngestRequest):
    """
    Smart ingest endpoint (fallback for background pipeline).

    * If the URL is already ingested → return instantly.
    * If background status is 'pending' or 'running' → poll until done
      (up to ~30 s) then return the result.
    * If background status is 'failed' or unknown → synchronous ingest.
    """
    import asyncio
    url = str(req.url)

    # Fast path: already indexed
    bg = get_ingest_status(url)
    if bg and bg["status"] == "done":
        quality = {"score": 1.0, "verdict": "good", "details": ""}
        return {"status": "ok", "chunks": bg["chunks"], "quality": quality}

    # Wait for background worker if it's in progress
    if bg and bg["status"] in ("pending", "running"):
        for _ in range(60):          # ~30 seconds max
            await asyncio.sleep(0.5)
            bg = get_ingest_status(url)
            if bg and bg["status"] == "done":
                quality = {"score": 1.0, "verdict": "good", "details": ""}
                return {"status": "ok", "chunks": bg["chunks"], "quality": quality}
            if bg and bg["status"] == "failed":
                break  # fall through to synchronous retry

    # Synchronous fallback (background was not running, or failed)
    try:
        result = await ingest(url)
        chunk_count = result["chunks"]
        quality = result["quality"]
        if chunk_count == 0:
            raise HTTPException(status_code=422, detail="Could not extract text from the URL.")
        return {"status": "ok", "chunks": chunk_count, "quality": quality}
    except HTTPException:
        raise
    except ValueError as exc:
        detail = str(exc)
        if "private network" in detail or "blocklist" in detail:
            raise HTTPException(status_code=422, detail=f"安全预检失败：{detail}")
        raise HTTPException(status_code=422, detail=f"内容提取失败：{detail}")
    except Exception:
        logger.exception("Failed to ingest article: %s", url)
        raise HTTPException(status_code=500, detail="Failed to ingest article.")


@rag_router.post("/overview", dependencies=[Depends(_require_rag_enabled)])
async def fetch_article_overview(req: PublicUrlRequest):
    """Generate a richer overview for the article before interactive questioning."""
    url = str(req.url)

    # --- FAST PATH: DB cached overview (instant return) ---
    cached_overview = await get_db_cached_overview(url)
    if cached_overview:
        async def cached_event_generator():
            yield _format_sse_data(cached_overview)
            yield _format_sse_data("[DONE]")
        return StreamingResponse(
            cached_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    async def event_generator():
        async for token in stream_article_overview(url):
            yield _format_sse_data(token)
        yield _format_sse_data("[DONE]")

    try:
        await _prepare_overview_context(url)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except ValueError as exc:
        detail = str(exc)
        if "private network" in detail or "blocklist" in detail:
            raise HTTPException(status_code=422, detail=f"安全预检失败：{detail}")
        raise HTTPException(status_code=422, detail=f"概要提取失败：{detail}")
    except Exception:
        logger.exception("Failed to generate article overview for %s", url)
        raise HTTPException(status_code=500, detail="Failed to generate article overview.")


@rag_router.post("/query", dependencies=[Depends(_require_rag_enabled)])
async def query_article(req: QueryRequest):
    """
    Run the two-stage RAG pipeline (Bi-Encoder recall -> Cross-Encoder rerank -> DeepSeek stream).
    Returns an SSE stream of text tokens.
    """
    url = str(req.url)

    if url not in _ingested_urls:
        raise HTTPException(
            status_code=400,
            detail="This URL has not been ingested yet. Please call /ingest first.",
        )

    async def event_generator():
        async for token in query_stream(req.question, url, history=req.history):
            yield _format_sse_data(token)
        yield _format_sse_data("[DONE]")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@rag_router.get("/history", dependencies=[Depends(_require_rag_enabled)])
async def fetch_chat_history(url: AnyHttpUrl = Query(...)):
    """
    Retrieve existing chat history for a URL.
    """
    try:
        public_url = str(_validate_public_url(url))
        history = await get_chat_history(public_url)
        return {
            "status": "ok",
            "history": [
                {
                    "role": "ai" if m.role == "assistant" else m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in history
            ],
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Failed to fetch chat history for %s", url)
        raise HTTPException(status_code=500, detail="Failed to fetch chat history.")


@rag_router.post("/feedback", dependencies=[Depends(_require_rag_enabled)])
async def submit_feedback(req: FeedbackRequest):
    """
    Record explicit user feedback (Like/Dislike) for an article.
    This builds the user's semantic profile for personalized reranking.
    """
    url = str(req.url)

    try:
        await record_feedback(url, req.sentiment)
        return {"status": "ok", "message": "Feedback recorded successfully."}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception("Failed to record feedback for %s", url)
        raise HTTPException(status_code=500, detail="Failed to record feedback.")


@rag_router.post("/query/global", dependencies=[Depends(_require_rag_enabled)])
async def query_global(req: GlobalQueryRequest):
    """
    Cross-article RAG query: search all ingested articles and stream an answer.
    Returns an SSE stream of text tokens with multi-source citations.
    """
    async def event_generator():
        async for token in query_cross_article(
            req.question,
            top_k_final=min(req.max_results, 10),
        ):
            yield _format_sse_data(token)
        yield _format_sse_data("[DONE]")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
