from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.automation_settings import get_automation_settings, update_automation_settings

router = APIRouter()


class AutomationSettingsPatch(BaseModel):
    weekly_auto_report_enabled: bool | None = None
    weekly_auto_report_day: int | None = Field(default=None, ge=0, le=6)
    weekly_auto_report_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    weekly_auto_report_board: str | None = Field(default=None, max_length=64)


@router.get("/settings/automation")
async def get_automation_settings_endpoint() -> dict[str, Any]:
    return get_automation_settings()


@router.patch("/settings/automation")
async def update_automation_settings_endpoint(payload: AutomationSettingsPatch) -> dict[str, Any]:
    patch = payload.model_dump(exclude_unset=True)
    try:
        updated = update_automation_settings(patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from app.core.scheduler import refresh_weekly_auto_report_schedule

    refresh_weekly_auto_report_schedule()
    return updated
