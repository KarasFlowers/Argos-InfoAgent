import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import app.core.scheduler as scheduler
from app.models.domain import Board, TaskRun
from app.models.schemas import DailySummaryResponse, SummaryItem


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
            await task.start_stage("fetching", current=1, total=2)
            await asyncio.sleep(0)
            await task.start_stage("saving_summary", current=2, total=2)

    [task_run] = await _task_runs(task_session_factory)
    assert task_run.kind == "unit_test"
    assert task_run.trigger_type == "manual"
    assert task_run.status == "done"
    assert task_run.progress_label == "saving_summary"
    assert task_run.progress_current == 2
    assert task_run.progress_total == 2
    assert "fetching" in task_run.stage_timings
    assert "saving_summary" in task_run.stage_timings
    assert task_run.finished_at is not None


@pytest.mark.asyncio
async def test_produce_summary_with_task_tracking_persists_summary_stats(task_session_factory):
    item = SummaryItem(
        headline="Test headline",
        category="AI",
        key_points=["point"],
        original_link="https://example.com/a",
        source="Example",
    )
    summary = DailySummaryResponse(
        date="2026-06-30",
        overview="Overview",
        top_news=[item],
        source_stats={"Example": 1},
        recommendation_report={"final_recommended_count": 1},
    )

    class Adapter:
        async def produce(self, **kwargs):
            await kwargs["task_ref"].start_stage("generating_summary", current=2, total=4)
            return summary, {}

    with patch.object(scheduler, "AsyncSessionLocal", task_session_factory):
        async with scheduler.track_task_run("summary_generation", trigger_type="manual/api", board_id=7) as task:
            await scheduler.produce_summary_with_task_tracking(
                adapter=Adapter(),
                board=SimpleNamespace(id=7, slug="tech"),
                session=object(),
                task_ref=task,
            )

    [task_run] = await _task_runs(task_session_factory)
    assert task_run.status == "done"
    assert task_run.board_id == 7
    assert {"fetching", "generating_summary"}.issubset(task_run.stage_timings)
    assert task_run.ai_call_breakdown["item_count"] == 1
    assert task_run.ai_call_breakdown["source_stats"] == {"Example": 1}


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


@pytest.mark.asyncio
async def test_async_push_boards_creates_batch_and_board_summary_runs(task_session_factory, monkeypatch):
    board = Board(
        id=7,
        slug="tech",
        name="Tech",
        source_type="rss",
        source_config={"feeds": []},
        is_default=True,
    )
    item = SummaryItem(
        headline="Scheduled headline",
        category="AI",
        key_points=["point"],
        original_link="https://example.com/scheduled",
        source="Example",
    )
    summary = DailySummaryResponse(
        date=datetime.now().strftime("%Y-%m-%d"),
        overview="Scheduled summary",
        top_news=[item],
        source_stats={"Example": 1},
    )

    class Adapter:
        async def produce(self, **kwargs):
            await kwargs["task_ref"].start_stage("generating_summary", current=2, total=4)
            return summary, {}

    class Notify:
        async def send(self, *args, **kwargs):
            return None

    class FakeDbService:
        def __init__(self):
            self.saved = []

        async def list_boards(self, session, active_only=True):
            return [board]

        async def get_summary_by_date(self, session, date, board_id=None, perspective="overview"):
            return None

        async def save_summary(self, session, summary_obj, board_id=None):
            self.saved.append((summary_obj, board_id))

    monkeypatch.setattr(scheduler.settings, "LLM_API_KEY", "sk-test")
    monkeypatch.setattr(scheduler.settings, "DEEPSEEK_API_KEY", None)
    monkeypatch.setattr("app.services.source_adapters.get_adapter", lambda source_type: Adapter())
    monkeypatch.setattr("app.services.notification.notify_service", Notify())
    fake_db = FakeDbService()
    monkeypatch.setattr("app.services.db_service.db_service", fake_db)

    with patch.object(scheduler, "AsyncSessionLocal", task_session_factory):
        await scheduler._async_push_boards(slugs=["tech"])

    runs = await _task_runs(task_session_factory)
    kinds = [task_run.kind for task_run in runs]
    assert kinds == ["daily_push", "summary_generation"]
    summary_run = next(task_run for task_run in runs if task_run.kind == "summary_generation")
    assert summary_run.status == "done"
    assert summary_run.board_id == board.id
    assert "generating_summary" in summary_run.stage_timings
    assert fake_db.saved == [(summary, board.id)]
