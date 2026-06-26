"""
APScheduler-based background jobs.

Registered jobs
---------------
- **cleanup_old_data** – every 6 hours (+ once on startup): prune expired data.
- **daily_push** – global fallback cron for boards *without* a custom schedule.
- **board_push:<slug>** – per-board cron for boards that define their own schedule.

Per-board scheduling
--------------------
If ``Board.schedule`` is set (e.g. ``"08:00"``, ``"08:30,18:00"``), the board gets
its own dedicated cron job(s) and is excluded from the global daily_push.
Multiple times can be comma-separated to push the same board at different hours.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, UTC
from typing import List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# TaskRun tracking
# ---------------------------------------------------------------------------

@asynccontextmanager
async def track_task_run(kind: str, trigger_type: str = "scheduled", board_id: int | None = None):
    """Context manager that creates and updates a TaskRun record around an async job.

    Usage::

        async with track_task_run("cleanup") as tr:
            tr.progress_label = "deleting old summaries"
            await do_cleanup()
    """
    from app.core.db import AsyncSessionLocal
    from app.models.domain import TaskRun

    task = TaskRun(kind=kind, trigger_type=trigger_type, status="running",
                   started_at=datetime.now(UTC), board_id=board_id)

    async with AsyncSessionLocal() as session:
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    class _TaskRef:
        def __init__(self):
            self.id = task_id
            self.progress_label = ""
            self.progress_current = 0
            self.progress_total = 0
            self.stage_timings = {}
            self.ai_call_breakdown = {}

    ref = _TaskRef()

    try:
        yield ref
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select as _sel
            stmt = _sel(TaskRun).where(TaskRun.id == task_id)
            result = await session.execute(stmt)
            tr = result.scalar_one_or_none()
            if tr:
                tr.status = "failed"
                tr.error_summary = str(exc)[:500]
                tr.finished_at = datetime.now(UTC)
                await session.commit()
        raise
    else:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import select as _sel
            stmt = _sel(TaskRun).where(TaskRun.id == task_id)
            result = await session.execute(stmt)
            tr = result.scalar_one_or_none()
            if tr:
                tr.status = "done"
                tr.progress_label = ref.progress_label
                tr.progress_current = ref.progress_current
                tr.progress_total = ref.progress_total
                tr.stage_timings = ref.stage_timings or None
                tr.ai_call_breakdown = ref.ai_call_breakdown or None
                tr.finished_at = datetime.now(UTC)
                await session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_hhmm(time_str: str) -> Optional[tuple[int, int]]:
    """Parse 'HH:MM' into (hour, minute) or return None on bad format."""
    try:
        parts = time_str.strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
    except (ValueError, IndexError):
        pass
    return None


# ---------------------------------------------------------------------------
# Async work functions
# ---------------------------------------------------------------------------

def _run_cleanup() -> None:
    """Synchronous wrapper executed by APScheduler's thread-pool."""
    try:
        asyncio.run(_async_cleanup())
    except Exception:
        logger.exception("Scheduled cleanup failed")


async def _async_cleanup() -> None:
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service
    from app.models.domain import TaskRun
    from sqlalchemy import select as _sel
    from datetime import timedelta

    async with track_task_run("cleanup") as tr:
        tr.progress_label = "deleting old summaries"
        async with AsyncSessionLocal() as session:
            deleted = await db_service.cleanup_old_data(
                session, days_to_keep=settings.HISTORY_DAYS_TO_KEEP
            )
            logger.info("Scheduled cleanup removed %s old summaries", deleted)

            # Mark stale TaskRun entries that have been "running" for over 2 hours
            stale_cutoff = datetime.now(UTC) - timedelta(hours=2)
            stale_stmt = _sel(TaskRun).where(
                TaskRun.status == "running",
                TaskRun.started_at < stale_cutoff,
            )
            stale_result = await session.execute(stale_stmt)
            stale_tasks = stale_result.scalars().all()
            for stale in stale_tasks:
                stale.status = "failed"
                stale.error_summary = "Timed out (stale)"
                stale.finished_at = datetime.now(UTC)
            if stale_tasks:
                await session.commit()
                logger.info("Marked %d stale TaskRun(s) as failed", len(stale_tasks))

            tr.progress_total = 1
            tr.progress_current = 1


def _make_board_push_runner(board_slug: str):
    """Factory: create a sync runner scoped to a single board slug."""
    def _run() -> None:
        try:
            asyncio.run(_async_push_boards(slugs=[board_slug]))
        except Exception:
            logger.exception("Scheduled push failed for board '%s'", board_slug)
    return _run


def _run_daily_push() -> None:
    """Synchronous wrapper — pushes boards that have NO custom schedule."""
    try:
        asyncio.run(_async_push_boards(only_global=True))
    except Exception:
        logger.exception("Scheduled daily push failed")


def _run_auto_extract_interests() -> None:
    """Synchronous wrapper — auto-extract interests from feedback."""
    try:
        asyncio.run(_async_auto_extract_interests())
    except Exception:
        logger.exception("Scheduled auto-extract interests failed")


async def _async_auto_extract_interests() -> None:
    from app.core.db import AsyncSessionLocal
    from app.services.learning_service import auto_extract_interests

    async with track_task_run("auto_extract_interests") as tr:
        tr.progress_label = "extracting interests from feedback"
        async with AsyncSessionLocal() as session:
            count = await auto_extract_interests(session)
            if count > 0:
                logger.info("Auto-extracted %d new interests from feedback", count)
            tr.progress_total = 1
            tr.progress_current = 1


def _run_auto_extract_memories() -> None:
    """Synchronous wrapper — auto-extract user memories from chat history."""
    try:
        asyncio.run(_async_auto_extract_memories())
    except Exception:
        logger.exception("Scheduled auto-extract memories failed")


def _run_silent_mode() -> None:
    """Synchronous wrapper — export Markdown digests when the PC is idle."""
    try:
        asyncio.run(_async_silent_mode())
    except Exception:
        logger.exception("Scheduled silent mode failed")


async def _async_auto_extract_memories() -> None:
    from app.core.db import AsyncSessionLocal
    from app.services.memory_service import auto_extract_memories

    async with track_task_run("auto_extract_memories") as tr:
        tr.progress_label = "extracting memories from chat"
        async with AsyncSessionLocal() as session:
            count = await auto_extract_memories(session)
            if count > 0:
                logger.info("Auto-extracted %d new memories from chat", count)
            tr.progress_total = 1
            tr.progress_current = 1


async def _async_silent_mode() -> None:
    from app.services.silent_mode_service import run_silent_collection

    async with track_task_run("silent_mode_collect") as tr:
        tr.progress_label = "collecting idle-time markdown digests"
        async with AsyncSessionLocal() as session:
            result = await run_silent_collection(session)
            tr.progress_total = len(result.get("results") or [])
            tr.progress_current = tr.progress_total
            if result.get("ok"):
                logger.info("Silent mode export complete: %s", result)
            else:
                logger.info("Silent mode skipped: %s", result.get("reason"))


async def _async_push_boards(
    slugs: Optional[List[str]] = None,
    only_global: bool = False,
) -> None:
    """
    Generate summaries and notify for selected boards.

    Args:
        slugs: If provided, process only these board slugs.
        only_global: If True, process only boards that have NO custom schedule
                     (i.e. boards that rely on the global DAILY_PUSH_TIME).
    """
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service
    from app.services.notification import notify_service
    from app.services.source_adapters import get_adapter, UnknownSourceTypeError

    trigger = "manual" if slugs else "scheduled"
    async with track_task_run("daily_push", trigger_type=trigger) as tr:
        tr.progress_label = "generating summaries and pushing notifications"

        search_date = datetime.now().strftime("%Y-%m-%d")

        async with AsyncSessionLocal() as session:
            boards = await db_service.list_boards(session, active_only=True)
            if not boards:
                logger.warning("No active boards found; skipping push.")
                return

            # Filter boards
            if slugs:
                boards = [b for b in boards if b.slug in slugs]
            elif only_global:
                boards = [b for b in boards if not b.schedule or not b.schedule.strip()]

            tr.progress_total = len(boards)

            for i, board in enumerate(boards):
                tr.progress_current = i + 1
                tr.progress_label = f"processing board '{board.slug}' ({i+1}/{len(boards)})"
                logger.info("Push: processing board '%s'", board.slug)
                existing = await db_service.get_summary_by_date(
                    session, search_date, board_id=board.id
                )
                summary = existing
                if not summary:
                    try:
                        adapter = get_adapter(board.source_type)
                    except UnknownSourceTypeError as error:
                        logger.error("Skipping board '%s': %s", board.slug, error)
                        continue

                    try:
                        summary, content_fallback = await adapter.produce(board=board, session=session)
                    except Exception:
                        logger.exception("Adapter '%s' failed for board '%s'", board.source_type, board.slug)
                        continue

                    if summary:
                        try:
                            await db_service.save_summary(session, summary, board_id=board.id)
                        except Exception:
                            logger.exception(
                                "Failed to save background summary for board '%s'", board.slug
                            )
                            continue

                        # Enqueue URLs for background ingestion (RSS items only).
                        if settings.RAG_ENABLED and settings.RAG_BACKGROUND_INGEST_ENABLED:
                            from app.services.rag_service import enqueue_for_ingest
                            article_urls = [
                                item.original_link
                                for item in summary.top_news
                                if item.original_link and not item.original_link.startswith("llm://")
                            ]
                            if article_urls:
                                fb = {u: content_fallback[u] for u in article_urls if u in content_fallback}
                                enqueue_for_ingest(article_urls, fallback_contents=fb if fb else None)

                if summary:
                    # Determine per-board notification channels (or use global default)
                    board_channels = None
                    if board.notify_channels:
                        board_channels = [
                            ch.strip() for ch in board.notify_channels.split(",") if ch.strip()
                        ]
                    try:
                        await notify_service.send(summary, channels=board_channels)
                    except Exception:
                        logger.exception("Failed to notify for board '%s'", board.slug)
                else:
                    logger.warning("No summary produced for board '%s'", board.slug)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

async def _register_board_schedules() -> None:
    """
    Read active boards from DB and register per-board cron jobs for those
    that have a custom schedule. Must be called after DB is ready.

    This is now an async function so it can be awaited from an already-running
    event loop (e.g. FastAPI lifespan) without creating a nested loop.
    """
    await _async_register_board_schedules()


async def _async_register_board_schedules() -> None:
    from app.core.db import AsyncSessionLocal
    from app.services.db_service import db_service

    async with AsyncSessionLocal() as session:
        boards = await db_service.list_boards(session, active_only=True)

    for board in boards:
        if not board.schedule or not board.schedule.strip():
            continue

        # Support comma-separated multiple times: "08:00,18:00"
        times = [t.strip() for t in board.schedule.split(",") if t.strip()]
        for idx, time_str in enumerate(times):
            parsed = _parse_hhmm(time_str)
            if not parsed:
                logger.error(
                    "Board '%s' has invalid schedule time '%s', skipping.",
                    board.slug, time_str,
                )
                continue

            hour, minute = parsed
            job_id = f"board_push:{board.slug}:{idx}"
            _scheduler.add_job(
                _make_board_push_runner(board.slug),
                trigger=CronTrigger(hour=hour, minute=minute),
                id=job_id,
                name=f"Push [{board.slug}] at {hour:02d}:{minute:02d}",
                replace_existing=True,
            )
            logger.info(
                "Registered per-board push: '%s' at %02d:%02d", board.slug, hour, minute
            )


async def start_scheduler() -> None:
    """Initialise APScheduler, register global jobs, then per-board schedules.

    Must be awaited from an async context (e.g. FastAPI lifespan).
    """
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(daemon=True)

    # 1. Cleanup Job
    _scheduler.add_job(
        _run_cleanup,
        trigger=IntervalTrigger(hours=6),
        id="cleanup_old_data",
        name="Prune expired summaries & RAG collections",
        replace_existing=True,
        next_run_time=None,  # skip immediate run; we'll fire once below
    )

    # 2. Global Daily Push (fallback for boards without custom schedule)
    try:
        hour, minute = map(int, settings.DAILY_PUSH_TIME.split(":"))
        _scheduler.add_job(
            _run_daily_push,
            trigger=CronTrigger(hour=hour, minute=minute),
            id="daily_push",
            name="Daily Notification Push (global)",
            replace_existing=True,
        )
        logger.info("Scheduled global daily push for %02d:%02d", hour, minute)
    except ValueError:
        logger.error("Invalid DAILY_PUSH_TIME format: %s. Expected HH:MM.", settings.DAILY_PUSH_TIME)

    # 3. Auto Interest Extraction (every 12 hours)
    _scheduler.add_job(
        _run_auto_extract_interests,
        trigger=IntervalTrigger(hours=12),
        id="auto_extract_interests",
        name="Auto-extract long-term interests from feedback",
        replace_existing=True,
    )

    # 4. Auto Memory Extraction (every 6 hours)
    _scheduler.add_job(
        _run_auto_extract_memories,
        trigger=IntervalTrigger(hours=6),
        id="auto_extract_memories",
        name="Auto-extract user memories from chat history",
        replace_existing=True,
    )

    # 5. Per-board schedules (async — reads from DB)
    await _register_board_schedules()

    # 6. Silent mode background exports, gated by PC idle time
    if settings.SILENT_MODE_ENABLED:
        _scheduler.add_job(
            _run_silent_mode,
            trigger=IntervalTrigger(minutes=settings.SILENT_MODE_INTERVAL_MINUTES),
            id="silent_mode_collect",
            name="Idle-time Markdown export",
            replace_existing=True,
        )
        logger.info(
            "Scheduled silent mode export every %s minutes",
            settings.SILENT_MODE_INTERVAL_MINUTES,
        )

    _scheduler.start()
    logger.info("APScheduler started")

    # Fire the first cleanup in a background thread so startup isn't blocked.
    _scheduler.add_job(
        _run_cleanup,
        id="cleanup_startup",
        name="One-shot startup cleanup",
        replace_existing=True,
    )


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped")
