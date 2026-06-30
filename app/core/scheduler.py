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
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
TASK_RUN_ERROR_MAX_LENGTH = 500
TASK_RUN_STALE_AFTER = timedelta(hours=2)
TASK_STATUS_RUNNING = "running"
TASK_STATUS_DONE = "done"
TASK_STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# TaskRun tracking
# ---------------------------------------------------------------------------


def _truncate_error(error: BaseException | str) -> str:
    return str(error)[:TASK_RUN_ERROR_MAX_LENGTH]


async def _load_task_run(session: AsyncSession, task_id: int):
    from app.models.domain import TaskRun

    result = await session.execute(select(TaskRun).where(TaskRun.id == task_id))
    return result.scalar_one_or_none()


async def _persist_task_progress(session: AsyncSession, task_id: int, ref) -> None:
    task_run = await _load_task_run(session, task_id)
    if not task_run:
        return
    task_run.progress_label = ref.progress_label
    task_run.progress_current = ref.progress_current
    task_run.progress_total = ref.progress_total
    task_run.stage_timings = ref.stage_timings or None
    task_run.ai_call_breakdown = ref.ai_call_breakdown or None
    await session.commit()


async def _finish_task_run(
    session: AsyncSession,
    task_id: int,
    status: str,
    ref=None,
    error_summary: str = "",
) -> None:
    task_run = await _load_task_run(session, task_id)
    if not task_run:
        return
    task_run.status = status
    if ref is not None:
        task_run.progress_label = ref.progress_label
        task_run.progress_current = ref.progress_current
        task_run.progress_total = ref.progress_total
        task_run.stage_timings = ref.stage_timings or None
        task_run.ai_call_breakdown = ref.ai_call_breakdown or None
    task_run.error_summary = error_summary[:TASK_RUN_ERROR_MAX_LENGTH] if error_summary else ""
    task_run.finished_at = datetime.now(UTC)
    await session.commit()


async def mark_stale_task_runs(
    session: AsyncSession,
    cutoff: datetime | None = None,
) -> int:
    """Mark long-running TaskRun rows as failed and return the number updated."""
    from app.models.domain import TaskRun

    stale_cutoff = cutoff or (datetime.now(UTC) - TASK_RUN_STALE_AFTER)
    stale_stmt = select(TaskRun).where(
        TaskRun.status == TASK_STATUS_RUNNING,
        TaskRun.started_at < stale_cutoff,
    )
    stale_result = await session.execute(stale_stmt)
    stale_tasks = stale_result.scalars().all()
    for stale in stale_tasks:
        stale.status = TASK_STATUS_FAILED
        stale.error_summary = "Timed out (stale)"
        stale.finished_at = datetime.now(UTC)
    if stale_tasks:
        await session.commit()
    return len(stale_tasks)


@asynccontextmanager
async def track_task_run(kind: str, trigger_type: str = "scheduled", board_id: int | None = None):
    """Context manager that creates and updates a TaskRun record around an async job.

    Usage::

        async with track_task_run("cleanup") as tr:
            tr.progress_label = "deleting old summaries"
            await do_cleanup()
    """
    from app.models.domain import TaskRun

    task = TaskRun(
        kind=kind,
        trigger_type=trigger_type,
        status=TASK_STATUS_RUNNING,
        started_at=datetime.now(UTC),
        board_id=board_id,
    )

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

        async def save_progress(self) -> None:
            async with AsyncSessionLocal() as session:
                await _persist_task_progress(session, task_id, self)

    ref = _TaskRef()

    try:
        yield ref
    except asyncio.CancelledError:
        async with AsyncSessionLocal() as session:
            await _finish_task_run(
                session,
                task_id,
                TASK_STATUS_FAILED,
                ref=ref,
                error_summary="Cancelled during shutdown",
            )
        raise
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            await _finish_task_run(
                session,
                task_id,
                TASK_STATUS_FAILED,
                ref=ref,
                error_summary=_truncate_error(exc),
            )
        raise
    else:
        async with AsyncSessionLocal() as session:
            await _finish_task_run(session, task_id, TASK_STATUS_DONE, ref=ref)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_hhmm(time_str: str) -> tuple[int, int] | None:
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
    from app.services.db_service import db_service

    async with track_task_run("cleanup") as tr:
        tr.progress_label = "deleting old summaries"
        async with AsyncSessionLocal() as session:
            deleted = await db_service.cleanup_old_data(session, days_to_keep=settings.HISTORY_DAYS_TO_KEEP)
            logger.info("Scheduled cleanup removed %s old summaries", deleted)

            stale_count = await mark_stale_task_runs(session)
            if stale_count:
                logger.info("Marked %d stale TaskRun(s) as failed", stale_count)

            tr.progress_total = 1
            tr.progress_current = 1
            await tr.save_progress()


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


def _run_weekly_auto_report() -> None:
    """Synchronous wrapper — generate the configured weekly report."""
    try:
        asyncio.run(_async_weekly_auto_report())
    except Exception as exc:
        try:
            from app.services.automation_settings import record_weekly_auto_report_run

            record_weekly_auto_report_run(
                {
                    "ok": False,
                    "reason": str(exc) or exc.__class__.__name__,
                    "board": "unknown",
                    "generated_at": datetime.now(UTC).isoformat(),
                }
            )
        except Exception:
            logger.exception("Failed to record weekly auto report failure")
        logger.exception("Scheduled weekly auto report failed")


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


async def _async_weekly_auto_report() -> None:
    from app.api.boards import resolve_active_board
    from app.services.automation_settings import (
        get_automation_settings,
        record_weekly_auto_report_run,
        weekly_report_output_path,
    )
    from app.services.db_service import db_service
    from app.services.llm_service import llm_service

    cfg = get_automation_settings()
    if not cfg.get("weekly_auto_report_enabled"):
        logger.info("Weekly auto report skipped: disabled")
        return

    async with track_task_run("weekly_report", trigger_type="scheduled") as tr:
        tr.progress_label = "generating weekly report"
        async with AsyncSessionLocal() as session:
            board_slug = cfg.get("weekly_auto_report_board") or None
            board = await resolve_active_board(session, board_slug)
            board_id = board.id if board else None
            board_label = getattr(board, "slug", None) or "default"

            history = await db_service.get_summary_history(session, limit=7, board_id=board_id)
            if not history.archive_items:
                result = {
                    "ok": False,
                    "reason": "No history found to summarize.",
                    "board": board_label,
                    "generated_at": datetime.now(UTC).isoformat(),
                }
                record_weekly_auto_report_run(result)
                logger.info("Weekly auto report skipped: %s", result["reason"])
                return

            summaries_data = []
            for item in history.archive_items:
                full = await db_service.get_summary_by_date(session, item.date, board_id=board_id)
                if full:
                    summaries_data.append(full.model_dump())

            if not summaries_data:
                result = {
                    "ok": False,
                    "reason": "Failed to retrieve history content.",
                    "board": board_label,
                    "generated_at": datetime.now(UTC).isoformat(),
                }
                record_weekly_auto_report_run(result)
                logger.info("Weekly auto report skipped: %s", result["reason"])
                return

            tr.progress_total = 1
            await tr.save_progress()
            report = await llm_service.generate_weekly_consolidation(
                summaries_data,
                output_language=getattr(board, "output_language", None),
            )
            if not report:
                raise RuntimeError("Failed to generate weekly report.")

            generated_at = datetime.now(UTC)
            output_path = weekly_report_output_path(board_label, generated_at=generated_at)
            output_path.write_text(report, encoding="utf-8")
            tr.progress_current = 1
            await tr.save_progress()

            result = {
                "ok": True,
                "board": board_label,
                "generated_at": generated_at.isoformat(),
                "output_path": str(output_path),
                "summary_count": len(summaries_data),
            }
            record_weekly_auto_report_run(result)
            logger.info("Weekly auto report generated: %s", output_path)


async def _async_push_boards(
    slugs: list[str] | None = None,
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
    from app.services.source_adapters import UnknownSourceTypeError, get_adapter

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
                await tr.save_progress()
                logger.info("Push: processing board '%s'", board.slug)
                existing = await db_service.get_summary_by_date(session, search_date, board_id=board.id)
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
                            logger.exception("Failed to save background summary for board '%s'", board.slug)
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
                        board_channels = [ch.strip() for ch in board.notify_channels.split(",") if ch.strip()]
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


def _register_weekly_auto_report_schedule() -> None:
    if _scheduler is None:
        return
    try:
        from app.services.automation_settings import get_automation_settings

        cfg = get_automation_settings()
        if not cfg.get("weekly_auto_report_enabled"):
            logger.info("Weekly auto report schedule disabled")
            return
        parsed = _parse_hhmm(cfg.get("weekly_auto_report_time", "18:00"))
        if not parsed:
            logger.error("Invalid weekly auto report time: %s", cfg.get("weekly_auto_report_time"))
            return
        hour, minute = parsed
        day = int(cfg.get("weekly_auto_report_day", 6))
        _scheduler.add_job(
            _run_weekly_auto_report,
            trigger=CronTrigger(day_of_week=day, hour=hour, minute=minute),
            id="weekly_auto_report",
            name="Weekly auto report",
            replace_existing=True,
        )
        logger.info("Scheduled weekly auto report for day %s at %02d:%02d", day, hour, minute)
    except Exception:
        logger.exception("Failed to register weekly auto report schedule")


def refresh_weekly_auto_report_schedule() -> None:
    """Re-register the weekly auto-report job after runtime settings change."""
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job("weekly_auto_report")
    except Exception:
        pass
    _register_weekly_auto_report_schedule()


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
                    board.slug,
                    time_str,
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
            logger.info("Registered per-board push: '%s' at %02d:%02d", board.slug, hour, minute)


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

    # 6. Weekly local report generation
    _register_weekly_auto_report_schedule()

    # 7. Silent mode background exports, gated by PC idle time
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
