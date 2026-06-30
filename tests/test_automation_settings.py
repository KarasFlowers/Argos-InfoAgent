import pytest

import app.core.scheduler as scheduler
import app.services.automation_settings as automation_settings
from app.api.routes.settings import (
    AutomationSettingsPatch,
    get_automation_settings_endpoint,
    update_automation_settings_endpoint,
)


def test_automation_settings_get_patch_roundtrip(tmp_path, monkeypatch):
    settings_path = tmp_path / "automation_settings.json"
    output_dir = tmp_path / "weekly_reports"
    monkeypatch.setattr(automation_settings, "AUTOMATION_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(
        automation_settings.settings,
        "WEEKLY_AUTO_REPORT_OUTPUT_DIR",
        str(output_dir),
    )

    initial = automation_settings.get_automation_settings()
    assert initial["weekly_auto_report_enabled"] is False
    assert initial["weekly_auto_report_day"] == 6

    updated = automation_settings.update_automation_settings(
        {
            "weekly_auto_report_enabled": True,
            "weekly_auto_report_day": 1,
            "weekly_auto_report_time": "09:30",
            "weekly_auto_report_board": "ai",
        }
    )

    assert updated["weekly_auto_report_enabled"] is True
    assert updated["weekly_auto_report_day"] == 1
    assert updated["weekly_auto_report_time"] == "09:30"
    assert updated["weekly_auto_report_board"] == "ai"
    assert settings_path.exists()


def test_automation_settings_rejects_invalid_time(tmp_path, monkeypatch):
    monkeypatch.setattr(automation_settings, "AUTOMATION_SETTINGS_PATH", tmp_path / "automation_settings.json")

    with pytest.raises(ValueError, match="weekly_auto_report_time"):
        automation_settings.update_automation_settings({"weekly_auto_report_time": "24:00"})


@pytest.mark.asyncio
async def test_automation_settings_endpoint_refreshes_scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(automation_settings, "AUTOMATION_SETTINGS_PATH", tmp_path / "automation_settings.json")

    called = {"value": False}

    def fake_refresh():
        called["value"] = True

    monkeypatch.setattr(scheduler, "refresh_weekly_auto_report_schedule", fake_refresh)

    result = await update_automation_settings_endpoint(
        AutomationSettingsPatch(
            weekly_auto_report_enabled=True,
            weekly_auto_report_day=5,
            weekly_auto_report_time="20:15",
            weekly_auto_report_board="tech",
        )
    )

    assert result["weekly_auto_report_enabled"] is True
    assert result["weekly_auto_report_day"] == 5
    assert result["weekly_auto_report_time"] == "20:15"
    assert result["weekly_auto_report_board"] == "tech"
    assert called["value"] is True

    read_back = await get_automation_settings_endpoint()
    assert read_back["weekly_auto_report_board"] == "tech"


def test_scheduler_registers_weekly_job_only_when_enabled(monkeypatch):
    class FakeScheduler:
        def __init__(self):
            self.jobs = []

        def add_job(self, *args, **kwargs):
            self.jobs.append((args, kwargs))

    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(scheduler, "_scheduler", fake_scheduler)
    monkeypatch.setattr(
        automation_settings,
        "get_automation_settings",
        lambda: {
            "weekly_auto_report_enabled": True,
            "weekly_auto_report_day": 2,
            "weekly_auto_report_time": "08:45",
        },
    )

    scheduler._register_weekly_auto_report_schedule()

    assert len(fake_scheduler.jobs) == 1
    assert fake_scheduler.jobs[0][1]["id"] == "weekly_auto_report"

    fake_scheduler.jobs.clear()
    monkeypatch.setattr(
        automation_settings,
        "get_automation_settings",
        lambda: {
            "weekly_auto_report_enabled": False,
            "weekly_auto_report_day": 2,
            "weekly_auto_report_time": "08:45",
        },
    )

    scheduler._register_weekly_auto_report_schedule()

    assert fake_scheduler.jobs == []
