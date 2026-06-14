# First-run bootstrap: ensure .env + data dirs exist before anything reads config.
# Guarded so that importing this module from tests/MCP doesn't trigger interactive prompts.
import sys as _sys
if _sys.argv and "uvicorn" in _sys.argv[0].lower() or __name__ == "__main__":
    from app.core.first_run import run_first_time_checks
    run_first_time_checks()

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.api.rag_router import rag_router
from app.core.auth import APIKeyMiddleware
from app.core.config import settings
from app.core.db import init_db
from app.core.logging_config import setup_logging, new_trace_id

# ---- Initialise structured logging BEFORE anything else logs ----
setup_logging()
logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_ROOT = PROJECT_ROOT / "app" / "web"
STATIC_DIR = WEB_ROOT / "static"
TEMPLATES_DIR = WEB_ROOT / "templates"



@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from app.services import rag_service
    from app.core.scheduler import start_scheduler, shutdown_scheduler

    # Ensure data directories exist (covers cases where first_run was skipped)
    from app.core.first_run import ensure_data_dirs
    ensure_data_dirs()

    # This runs when the server starts up
    await init_db()

    # Start APScheduler (handles periodic cleanup + future jobs)
    await start_scheduler()

    # Pre-warm ChromaDB + embedding models in the background so the server
    # becomes ready immediately instead of blocking startup on model loading
    # (~25s cold). The first RAG request still benefits from the warm cache if
    # it arrives after warm-up completes; otherwise it pays the load cost once.
    async def _warmup_rag() -> None:
        try:
            await asyncio.to_thread(rag_service.init_chroma)
            if settings.RAG_ENABLED:
                await asyncio.to_thread(rag_service.prewarm_models)
            logger.info("rag_warmup_complete")
        except Exception:
            logger.exception("rag_warmup_failed")

    warmup_task: asyncio.Task | None = None
    if settings.RAG_ENABLED:
        warmup_task = asyncio.create_task(_warmup_rag())
    else:
        # Still load existing collections (cheap no-op when RAG disabled)
        rag_service.init_chroma()

    # Start background ingest workers (they block on an empty queue until
    # warm-up finishes and URLs are enqueued, so launching them now is safe)
    worker_tasks: list[asyncio.Task] = []
    if settings.RAG_ENABLED and settings.RAG_BACKGROUND_INGEST_ENABLED:
        for i in range(settings.RAG_BACKGROUND_INGEST_WORKERS):
            task = asyncio.create_task(rag_service.ingest_worker_loop(worker_id=i))
            worker_tasks.append(task)

    logger.info("application_started")
    yield

    # Cancel all tracked background tasks (e.g. catchup backfill)
    from app.core.background import cancel_all_background_tasks
    await cancel_all_background_tasks()

    # Shutdown scheduler
    shutdown_scheduler()

    # Cancel warm-up if still running
    if warmup_task and not warmup_task.done():
        warmup_task.cancel()
        try:
            await warmup_task
        except (asyncio.CancelledError, Exception):
            pass

    # Close shared httpx client
    from app.core.http_client import close_http_client
    await close_http_client()

    # Close Redis connection
    from app.services.redis_service import redis_service
    await redis_service.close()

    # Shutdown: send sentinel per worker, then wait
    for _ in worker_tasks:
        try:
            rag_service._ingest_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
    for task in worker_tasks:
        task.cancel()
    if worker_tasks:
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    # Release the ChromaDB sqlite handle last, after all ingest workers have
    # stopped touching it. On Windows a leaked lock would otherwise break the
    # next run's client construction.
    rag_service.close_chroma_client()
    logger.info("application_stopped")

app = FastAPI(
    title="Argos API",
    description="Backend for the daily LLM information aggregation agent.",
    version="0.1.0",
    lifespan=lifespan
)

# ---- TraceID Middleware ----
class TraceIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tid = new_trace_id()
        response = await call_next(request)
        response.headers["X-Trace-ID"] = tid
        return response

app.add_middleware(TraceIDMiddleware)

# API Key authentication (inert when API_KEY is not set)
if settings.API_KEY:
    app.add_middleware(APIKeyMiddleware, api_key=settings.API_KEY)
    logger.info("api_key_auth_enabled")

# Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS and "*" not in settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(api_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")  # RAG endpoints return 503 when disabled

# Mount Static Files and Templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    # Updated signature for Starlette/FastAPI 0.111.0+ compatibility
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={}
    )


@app.get("/feed", response_class=HTMLResponse)
async def public_feed(request: Request, date: str = "", board: str = ""):
    """Public SEO-friendly HTML feed page — no auth required."""
    from datetime import datetime as _dt
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    search_date = date or _dt.now().strftime("%Y-%m-%d")
    async with AsyncSessionLocal() as session:
        board_obj = None
        if board:
            board_obj = await db_service.get_board_by_slug(session, board)
        if not board_obj:
            board_obj = await db_service.get_default_board(session)

        board_id = board_obj.id if board_obj else None
        board_name = board_obj.name if board_obj else "Argos"

        summary = await db_service.get_summary_by_date(session, search_date, board_id=board_id)

    if not summary:
        return templates.TemplateResponse(
            request=request,
            name="feed.html",
            context={
                "title": f"Argos Daily Briefing — {search_date}",
                "description": "No briefing available for this date.",
                "canonical_url": f"/feed?date={search_date}",
                "date": search_date,
                "board_name": board_name,
                "overview": "该日期暂无简报。",
                "sections": {},
            },
        )

    # Group items by category
    sections: dict[str, list] = {}
    for item in summary.top_news:
        cat = item.category or "general"
        sections.setdefault(cat, []).append(item)

    title = f"{board_name} · {search_date}"
    desc = summary.overview[:160] if summary.overview else f"Argos AI daily briefing for {search_date}"

    return templates.TemplateResponse(
        request=request,
        name="feed.html",
        context={
            "title": title,
            "description": desc,
            "canonical_url": f"/feed?date={search_date}&board={board_obj.slug if board_obj else ''}",
            "date": search_date,
            "board_name": board_name,
            "overview": summary.overview,
            "sections": sections,
        },
    )
