from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models.domain import TaskRun
from app.services.metrics_service import metrics_service

router = APIRouter()


@router.get("/metrics")
async def get_system_metrics(date: str | None = None):
    """
    Get system metrics (token usage and latency) for a specific date (defaults to today).
    """
    return await metrics_service.get_daily_metrics(date)


@router.get("/metrics/cost")
async def get_cost_breakdown(date: str | None = None):
    """
    Get per-label LLM cost breakdown (token usage per label) for a given date.
    """
    return await metrics_service.get_cost_breakdown(date)


@router.get("/ping")
async def ping():
    """
    Health check endpoint.
    """
    return {"status": "ok", "message": "pong"}


@router.get("/status")
async def get_system_status(session: AsyncSession = Depends(get_session)):
    """Private readiness/diagnostic status without exposing secrets."""
    database_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "project": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "database": {"ok": database_ok},
        "features": {
            "api_key_auth": bool(settings.API_KEY),
            "rag_enabled": settings.RAG_ENABLED,
            "rag_background_ingest": settings.RAG_BACKGROUND_INGEST_ENABLED,
            "wizard_pipeline": settings.WIZARD_PIPELINE_ENABLED,
            "llm_configured": bool(settings.effective_llm_api_key),
            "notifications_configured": bool(settings.NOTIFY_CHANNELS.strip()),
        },
        "public_base_url": settings.PUBLIC_BASE_URL,
    }


@router.get("/admin/tasks")
async def list_task_runs(
    kind: str | None = None,
    status: str | None = None,
    board_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List recent background task runs for observability."""
    stmt = select(TaskRun).order_by(desc(TaskRun.id))
    if kind:
        stmt = stmt.where(TaskRun.kind == kind)
    if status:
        stmt = stmt.where(TaskRun.status == status)
    if board_id is not None:
        stmt = stmt.where(TaskRun.board_id == board_id)
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    tasks = result.scalars().all()

    return [
        {
            "id": task.id,
            "kind": task.kind,
            "trigger_type": task.trigger_type,
            "status": task.status,
            "progress_label": task.progress_label,
            "progress_current": task.progress_current,
            "progress_total": task.progress_total,
            "stage_timings": task.stage_timings,
            "ai_call_breakdown": task.ai_call_breakdown,
            "error_summary": task.error_summary,
            "board_id": task.board_id,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }
        for task in tasks
    ]
