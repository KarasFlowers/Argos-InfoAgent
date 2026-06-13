"""Source health monitoring service.

Records health-check results for each RSS/data source fetch and
auto-updates Source.health_status based on consecutive failures.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Source, SourceHealthLog

logger = logging.getLogger(__name__)

_CONSECUTIVE_FAILURES_THRESHOLD = 3


async def log_source_health(
    session: AsyncSession,
    source_id: int,
    *,
    status: str = "ok",
    status_code: int | None = None,
    error_message: str = "",
    response_time_ms: int | None = None,
) -> None:
    """Record a health-check result and update the source's health_status."""
    checked_at = datetime.now(UTC)
    log = SourceHealthLog(
        source_id=source_id,
        status=status,
        status_code=status_code,
        error_message=error_message[:500] if error_message else "",
        response_time_ms=response_time_ms,
        checked_at=checked_at,
    )
    session.add(log)

    # Determine consecutive recent failures
    recent_stmt = (
        select(SourceHealthLog)
        .where(SourceHealthLog.source_id == source_id)
        .order_by(SourceHealthLog.checked_at.desc())
        .limit(_CONSECUTIVE_FAILURES_THRESHOLD)
    )
    result = await session.execute(recent_stmt)
    recent_logs = list(result.scalars().all())

    # Include the one we just added (not yet flushed)
    all_recent = [log] + recent_logs
    consecutive_failures = 0
    for entry in all_recent[:_CONSECUTIVE_FAILURES_THRESHOLD]:
        if entry.status != "ok":
            consecutive_failures += 1
        else:
            break

    # Update source health_status
    src_stmt = select(Source).where(Source.id == source_id)
    src_result = await session.execute(src_stmt)
    source = src_result.scalar_one_or_none()
    if source:
        source.last_fetched_at = checked_at if status == "ok" else source.last_fetched_at
        source.last_error = "" if status == "ok" else (error_message[:500] if error_message else source.last_error)
        if consecutive_failures >= _CONSECUTIVE_FAILURES_THRESHOLD:
            if source.health_status != "unhealthy":
                source.health_status = "unhealthy"
                logger.warning(
                    "Source '%s' (id=%d) marked unhealthy after %d consecutive failures",
                    source.name, source.id, consecutive_failures,
                )
        elif consecutive_failures > 0:
            if source.health_status != "degraded":
                source.health_status = "degraded"
                logger.info(
                    "Source '%s' (id=%d) marked degraded after %d recent failure(s)",
                    source.name, source.id, consecutive_failures,
                )
        else:
            if source.health_status != "healthy":
                source.health_status = "healthy"
                logger.info("Source '%s' (id=%d) recovered to healthy", source.name, source.id)

    await session.commit()


async def get_all_source_health(session: AsyncSession) -> list[dict]:
    """Return all sources with their current health status and last check info."""
    from sqlalchemy import desc

    # Load all sources
    stmt = select(Source).order_by(Source.id)
    result = await session.execute(stmt)
    sources = list(result.scalars().all())

    if not sources:
        return []

    # Batch-load latest health log per source (single query)
    source_ids = [s.id for s in sources if s.id]
    # Get the most recent log for each source_id
    log_stmt = (
        select(SourceHealthLog)
        .where(SourceHealthLog.source_id.in_(source_ids))
        .order_by(SourceHealthLog.source_id, desc(SourceHealthLog.checked_at))
    )
    log_result = await session.execute(log_stmt)
    all_logs = list(log_result.scalars().all())

    # Build {source_id: latest_log} — first occurrence per source_id is the latest
    latest_by_source: dict[int, SourceHealthLog] = {}
    for log in all_logs:
        if log.source_id not in latest_by_source:
            latest_by_source[log.source_id] = log

    out = []
    for src in sources:
        latest_log = latest_by_source.get(src.id) if src.id else None

        out.append({
            "id": src.id,
            "name": src.name,
            "url": src.url,
            "source_type": src.source_type,
            "enabled": src.enabled,
            "health_status": src.health_status,
            "last_fetched_at": src.last_fetched_at.isoformat() if src.last_fetched_at else None,
            "last_check": {
                "status": latest_log.status if latest_log else None,
                "status_code": latest_log.status_code if latest_log else None,
                "error_message": latest_log.error_message if latest_log else "",
                "response_time_ms": latest_log.response_time_ms if latest_log else None,
                "checked_at": latest_log.checked_at.isoformat() if latest_log else None,
            } if latest_log else None,
        })

    return out


async def get_source_health_log(
    session: AsyncSession,
    source_id: int,
    limit: int = 20,
) -> list[dict]:
    """Return recent health log entries for a specific source."""
    stmt = (
        select(SourceHealthLog)
        .where(SourceHealthLog.source_id == source_id)
        .order_by(SourceHealthLog.checked_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    logs = list(result.scalars().all())

    return [
        {
            "id": log.id,
            "status": log.status,
            "status_code": log.status_code,
            "error_message": log.error_message,
            "response_time_ms": log.response_time_ms,
            "checked_at": log.checked_at.isoformat(),
        }
        for log in logs
    ]
