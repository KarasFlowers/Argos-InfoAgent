from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.url_params import normalize_source_url_or_400
from app.prompts import is_prompt_selectable
from app.services.catchup_service import board_catchup_days


def serialize_source(source) -> dict:
    return {
        "id": source.id,
        "url": source.url,
        "name": source.name or "",
        "site_url": getattr(source, "site_url", "") or "",
        "source_type": source.source_type,
        "credibility_override": getattr(source, "credibility_override", "") or "",
        "enabled": bool(source.enabled),
        "board_id": source.board_id,
        "health_status": getattr(source, "health_status", "unknown") or "unknown",
        "last_error": getattr(source, "last_error", "") or "",
        "last_fetched_at": source.last_fetched_at.isoformat() if getattr(source, "last_fetched_at", None) else None,
        "created_at": source.created_at.isoformat() if getattr(source, "created_at", None) else None,
    }


def build_source_topic(board, source_name: str = "") -> str:
    parts = [
        getattr(board, "name", "") or "",
        getattr(board, "description", "") or "",
        getattr(board, "system_prompt", "") or "",
        source_name or "",
    ]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())[:500] or "通用资讯"


def board_supports_rss_sources(board) -> bool:
    return bool(board and board.source_type in {"rss", "multi"})


def serialize_board(board) -> dict:
    return {
        "id": board.id,
        "slug": board.slug,
        "name": board.name,
        "icon": board.icon,
        "description": board.description,
        "system_prompt": board.system_prompt,
        "source_type": board.source_type,
        "source_config": board.source_config or {},
        "perspectives": board.perspectives or {},
        "prompt_key": board.prompt_key or "daily_briefing",
        "output_language": getattr(board, "output_language", "auto") or "auto",
        "schedule": board.schedule or "",
        "notify_channels": board.notify_channels or "",
        "display_order": board.display_order,
        "is_active": board.is_active,
        "is_default": board.is_default,
        "catchup_days": board_catchup_days(board),
    }


def validate_board_source_payload(source_type: str, source_config: dict | None) -> None:
    from app.models.source_configs import SOURCE_CONFIG_MODELS
    from app.services.source_adapters import VALID_SOURCE_TYPES

    if source_type not in VALID_SOURCE_TYPES:
        raise HTTPException(status_code=400, detail=f"source_type must be one of {VALID_SOURCE_TYPES}.")

    config_model = SOURCE_CONFIG_MODELS.get(source_type)
    if config_model and source_config:
        try:
            config_model.model_validate(source_config)
        except Exception as val_err:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid source_config for type '{source_type}': {val_err}",
            ) from val_err
    validate_rss_feed_urls_in_config(source_type, source_config or {})


def validate_rss_feed_urls_in_config(source_type: str, source_config: dict) -> None:
    """Validate RSS feed URLs embedded in board source_config."""
    if source_type == "rss":
        feeds = source_config.get("feeds") or []
    elif source_type == "multi":
        feeds = ((source_config.get("sources") or {}).get("rss") or {}).get("feeds") or []
    else:
        return

    for feed_url in feeds:
        if not isinstance(feed_url, str):
            raise HTTPException(status_code=400, detail="RSS feed URLs must be strings.")
        normalize_source_url_or_400(feed_url)


def validate_board_prompt_key_or_400(prompt_key: str | None) -> str:
    """Normalize and validate a board summary template key."""
    key = (prompt_key or "").strip() or "daily_briefing"
    if not is_prompt_selectable(key):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Prompt key '{key}' is not a valid board summary template. "
                "Choose a template from GET /boards/prompts/templates."
            ),
        )
    return key


async def run_board_preview_runtime(
    board,
    session: AsyncSession,
    perspective: str = "overview",
):
    from app.services.llm_service import llm_service
    from app.services.source_adapters import UnknownSourceTypeError, get_adapter

    if not board.is_active:
        raise HTTPException(status_code=400, detail="Cannot preview an inactive board.")

    try:
        adapter = get_adapter(board.source_type)
    except UnknownSourceTypeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        summary_resp, _ = await adapter.produce(board, session)
        if not summary_resp:
            raise HTTPException(status_code=500, detail="Adapter returned no content for preview.")

        active_perspectives = None
        if board.perspectives and isinstance(board.perspectives, dict):
            active_perspectives = board.perspectives.get("active")

        if active_perspectives and len(active_perspectives) > 1:
            perspective_results = await llm_service.generate_perspective_summaries(
                content_items=[],
                session=session,
                board=board,
                perspectives=active_perspectives,
                seed_summary=summary_resp,
            )
            requested = None
            for persp_summary, _ in perspective_results:
                if persp_summary and persp_summary.perspective == perspective:
                    requested = persp_summary
                    break
            if not requested:
                requested = next((item for item, _ in perspective_results if item), summary_resp)
            summary_resp = requested

        return summary_resp
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(error)}") from error
