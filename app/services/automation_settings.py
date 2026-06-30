from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, settings

AUTOMATION_SETTINGS_PATH = PROJECT_ROOT / "data" / "automation_settings.json"


def _default_settings() -> dict[str, Any]:
    return {
        "weekly_auto_report_enabled": settings.WEEKLY_AUTO_REPORT_ENABLED,
        "weekly_auto_report_day": settings.WEEKLY_AUTO_REPORT_DAY,
        "weekly_auto_report_time": settings.WEEKLY_AUTO_REPORT_TIME,
        "weekly_auto_report_board": settings.WEEKLY_AUTO_REPORT_BOARD,
        "weekly_auto_report_output_dir": settings.WEEKLY_AUTO_REPORT_OUTPUT_DIR,
        "weekly_auto_report_last_run": None,
    }


def _parse_hhmm(value: str) -> str:
    raw = (value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2 or not all(part.isdigit() and len(part) == 2 for part in parts):
        raise ValueError("weekly_auto_report_time must use HH:MM format")
    hour, minute = (int(part) for part in parts)
    if hour > 23 or minute > 59:
        raise ValueError("weekly_auto_report_time must be a valid 24-hour time")
    return raw


def _normalize_settings(payload: dict[str, Any]) -> dict[str, Any]:
    merged = _default_settings()
    merged.update(payload or {})

    day = int(merged.get("weekly_auto_report_day", 6))
    if day < 0 or day > 6:
        raise ValueError("weekly_auto_report_day must be between 0 and 6")

    output_dir = str(merged.get("weekly_auto_report_output_dir") or settings.WEEKLY_AUTO_REPORT_OUTPUT_DIR)
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = (PROJECT_ROOT / output_path).resolve()

    return {
        "weekly_auto_report_enabled": bool(merged.get("weekly_auto_report_enabled")),
        "weekly_auto_report_day": day,
        "weekly_auto_report_time": _parse_hhmm(str(merged.get("weekly_auto_report_time") or "18:00")),
        "weekly_auto_report_board": str(merged.get("weekly_auto_report_board") or "").strip(),
        "weekly_auto_report_output_dir": str(output_path),
        "weekly_auto_report_last_run": merged.get("weekly_auto_report_last_run") or None,
    }


def get_automation_settings() -> dict[str, Any]:
    if not AUTOMATION_SETTINGS_PATH.exists():
        return _normalize_settings({})
    try:
        data = json.loads(AUTOMATION_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return _normalize_settings(data)


def update_automation_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = get_automation_settings()
    current.update(patch or {})
    normalized = _normalize_settings(current)
    AUTOMATION_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTOMATION_SETTINGS_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized


def record_weekly_auto_report_run(result: dict[str, Any]) -> dict[str, Any]:
    return update_automation_settings(
        {
            "weekly_auto_report_last_run": {
                **(result or {}),
                "recorded_at": datetime.now(UTC).isoformat(),
            }
        }
    )


def weekly_report_output_path(board_slug: str, generated_at: datetime | None = None) -> Path:
    cfg = get_automation_settings()
    root = Path(cfg["weekly_auto_report_output_dir"])
    root.mkdir(parents=True, exist_ok=True)
    stamp = (generated_at or datetime.now()).strftime("%Y-%m-%d")
    safe_slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in (board_slug or "default"))
    return root / f"{stamp}_{safe_slug}_weekly.md"
