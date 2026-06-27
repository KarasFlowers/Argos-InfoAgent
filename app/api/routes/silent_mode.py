from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.services.silent_mode_service import (
    get_idle_seconds,
    get_latest_manifest_entry,
    get_manifest_path,
    read_manifest_entries,
    run_silent_collection,
)

router = APIRouter()


class SilentModeRunRequest(BaseModel):
    force: bool = Field(default=False)


@router.get("/silent-mode/status")
async def get_silent_mode_status():
    manifest_path = get_manifest_path()
    recent_runs = list(reversed(read_manifest_entries(limit=5)))
    return {
        "enabled": settings.SILENT_MODE_ENABLED,
        "output_dir": settings.SILENT_MODE_OUTPUT_DIR,
        "manifest_path": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "last_run": get_latest_manifest_entry(),
        "recent_runs": recent_runs,
        "idle_seconds": get_idle_seconds(),
        "idle_threshold": settings.SILENT_MODE_IDLE_SECONDS,
        "interval_minutes": settings.SILENT_MODE_INTERVAL_MINUTES,
        "lookback_hours": settings.SILENT_MODE_LOOKBACK_HOURS,
        "board_slugs": settings.SILENT_MODE_BOARD_SLUGS,
        "overwrite_today": settings.SILENT_MODE_OVERWRITE_TODAY,
    }


@router.post("/silent-mode/run")
async def run_silent_mode(
    payload: SilentModeRunRequest,
    session: AsyncSession = Depends(get_session),
):
    return await run_silent_collection(session, force=payload.force)
