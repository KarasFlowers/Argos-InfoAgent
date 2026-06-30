import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.core.scheduler as scheduler
from app.models.domain import TaskRun


@pytest.fixture
async def task_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _task_runs(session_factory):
    async with session_factory() as session:
        result = await session.execute(select(TaskRun).order_by(TaskRun.id))
        return result.scalars().all()


@pytest.mark.asyncio
async def test_track_task_run_marks_success_and_persists_progress(task_session_factory):
    with patch.object(scheduler, "AsyncSessionLocal", task_session_factory):
        async with scheduler.track_task_run("unit_test", trigger_type="manual") as task:
            task.progress_label = "halfway"
            task.progress_current = 1
            task.progress_total = 2
            await task.save_progress()

    [task_run] = await _task_runs(task_session_factory)
    assert task_run.kind == "unit_test"
    assert task_run.trigger_type == "manual"
    assert task_run.status == "done"
    assert task_run.progress_label == "halfway"
    assert task_run.progress_current == 1
    assert task_run.progress_total == 2
    assert task_run.finished_at is not None


@pytest.mark.asyncio
async def test_track_task_run_marks_failure_and_truncates_error(task_session_factory):
    long_message = "x" * (scheduler.TASK_RUN_ERROR_MAX_LENGTH + 20)

    with patch.object(scheduler, "AsyncSessionLocal", task_session_factory):
        with pytest.raises(RuntimeError):
            async with scheduler.track_task_run("unit_test"):
                raise RuntimeError(long_message)

    [task_run] = await _task_runs(task_session_factory)
    assert task_run.status == "failed"
    assert len(task_run.error_summary) == scheduler.TASK_RUN_ERROR_MAX_LENGTH
    assert task_run.finished_at is not None


@pytest.mark.asyncio
async def test_track_task_run_marks_cancelled_tasks_failed(task_session_factory):
    with patch.object(scheduler, "AsyncSessionLocal", task_session_factory):
        with pytest.raises(asyncio.CancelledError):
            async with scheduler.track_task_run("unit_test"):
                raise asyncio.CancelledError

    [task_run] = await _task_runs(task_session_factory)
    assert task_run.status == "failed"
    assert task_run.error_summary == "Cancelled during shutdown"
    assert task_run.finished_at is not None


@pytest.mark.asyncio
async def test_mark_stale_task_runs_marks_only_expired_running_rows(task_session_factory):
    now = datetime.now(UTC)
    async with task_session_factory() as session:
        session.add(
            TaskRun(
                kind="old",
                status="running",
                started_at=now - timedelta(hours=3),
            )
        )
        session.add(
            TaskRun(
                kind="fresh",
                status="running",
                started_at=now,
            )
        )
        session.add(
            TaskRun(
                kind="done",
                status="done",
                started_at=now - timedelta(hours=3),
            )
        )
        await session.commit()

        updated = await scheduler.mark_stale_task_runs(session, cutoff=now - timedelta(hours=2))
        assert updated == 1

    runs = {task_run.kind: task_run for task_run in await _task_runs(task_session_factory)}
    assert runs["old"].status == "failed"
    assert runs["old"].error_summary == "Timed out (stale)"
    assert runs["old"].finished_at is not None
    assert runs["fresh"].status == "running"
    assert runs["done"].status == "done"


def test_weekly_auto_report_wrapper_records_unhandled_failure(monkeypatch):
    recorded = {}

    async def fail_weekly_report():
        raise RuntimeError("boom")

    def fake_record(result):
        recorded.update(result)

    monkeypatch.setattr(scheduler, "_async_weekly_auto_report", fail_weekly_report)
    monkeypatch.setattr("app.services.automation_settings.record_weekly_auto_report_run", fake_record)

    scheduler._run_weekly_auto_report()

    assert recorded["ok"] is False
    assert recorded["reason"] == "boom"
