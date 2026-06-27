from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.api.schemas import (
    BoardCreateRequest,
    BoardPreviewRequest,
    BoardSourceCreateRequest,
    BoardSourceUpdateRequest,
    BoardUpdateRequest,
)
from app.api.url_params import normalize_source_url_or_400
from app.core.db import get_session
from app.prompts import list_prompt_templates as get_prompt_templates
from app.services.board_api_service import (
    board_supports_rss_sources,
    run_board_preview_runtime,
    serialize_board,
    serialize_source,
    validate_board_prompt_key_or_400,
    validate_board_source_payload,
)
from app.services.db_service import db_service

router = APIRouter()
dynamic_router = APIRouter()


@router.get("/boards")
async def list_boards(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """List all boards, ordered by display_order."""
    boards = await db_service.list_boards(session, active_only=not include_inactive)
    return [serialize_board(board) for board in boards]


@router.post("/boards")
async def create_board(
    payload: BoardCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new custom board."""
    existing = await db_service.get_board_by_slug(session, payload.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Board '{payload.slug}' already exists.")
    validate_board_source_payload(payload.source_type, payload.source_config)
    payload.prompt_key = validate_board_prompt_key_or_400(payload.prompt_key)
    board = await db_service.create_board(
        session,
        slug=payload.slug,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        system_prompt=payload.system_prompt,
        source_type=payload.source_type,
        source_config=payload.source_config,
        display_order=payload.display_order,
        schedule=payload.schedule,
        notify_channels=payload.notify_channels,
        perspectives=payload.perspectives,
        prompt_key=payload.prompt_key,
        output_language=payload.output_language,
        catchup_days=payload.catchup_days,
    )
    if board_supports_rss_sources(board):
        board = await db_service.sync_board_rss_sources(session, board)
    return serialize_board(board)


@router.post("/boards/preview")
async def preview_board_from_payload(
    payload: BoardPreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Run preview directly from the current board form payload without saving."""
    validate_board_source_payload(payload.source_type, payload.source_config)
    payload.prompt_key = validate_board_prompt_key_or_400(payload.prompt_key)

    from app.models.domain import Board

    base_board = None
    if payload.original_slug:
        base_board = await db_service.get_board_by_slug(session, payload.original_slug)
        if not base_board:
            raise HTTPException(status_code=404, detail=f"Board '{payload.original_slug}' not found.")

    runtime_board = Board(
        id=base_board.id if base_board else None,
        slug=payload.slug,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        system_prompt=payload.system_prompt,
        source_type=payload.source_type,
        source_config=payload.source_config,
        display_order=base_board.display_order if base_board else 0,
        is_active=base_board.is_active if base_board else True,
        is_default=base_board.is_default if base_board else False,
        schedule=payload.schedule,
        notify_channels=payload.notify_channels,
        perspectives=payload.perspectives,
        prompt_key=payload.prompt_key,
        output_language=payload.output_language,
    )

    return await run_board_preview_runtime(runtime_board, session, perspective=payload.perspective)


@router.get("/boards/prompts/templates")
async def list_prompt_templates():
    """List prompt templates available for board summary generation."""
    selectable = get_prompt_templates(
        template_type="board_summary",
        user_selectable=True,
    )
    return {
        "templates": [m["key"] for m in selectable],
        "items": [
            {
                "key": m["key"],
                "name": m.get("name", m["key"]),
                "description": m.get("description", ""),
                "version": m.get("version", ""),
                "type": m.get("type", "board_summary"),
            }
            for m in selectable
        ],
    }


@router.post("/boards/prompts/render")
async def render_prompt_preview(
    payload: BoardPreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Render the resolved system prompt for a board configuration without calling the LLM."""
    from app.models.domain import Board
    from app.prompts import get_prompt_metadata
    from app.services.llm.summary import build_summary_prompt_preview

    runtime_board = Board(
        slug=payload.slug,
        name=payload.name,
        icon=payload.icon,
        description=payload.description,
        system_prompt=payload.system_prompt,
        source_type=payload.source_type,
        source_config=payload.source_config,
        schedule=payload.schedule,
        notify_channels=payload.notify_channels,
        perspectives=payload.perspectives,
        prompt_key=validate_board_prompt_key_or_400(payload.prompt_key),
        output_language=payload.output_language,
    )

    persona_preview = ""
    if payload.original_slug:
        try:
            board_obj = await db_service.get_board_by_slug(session, payload.original_slug)
            if board_obj:
                personas = await db_service.get_active_personas(session, board_id=board_obj.id)
                if personas:
                    lines = [f"- [{p.category}] {p.content}" for p in personas]
                    persona_preview = "USER PERSONALITY & PREFERENCE GUIDELINES:\n" + "\n".join(lines)
        except Exception:
            pass

    preview = build_summary_prompt_preview(
        runtime_board,
        persona_context=persona_preview,
    )
    meta = get_prompt_metadata(runtime_board.prompt_key or "daily_briefing")

    return {
        "prompt_key": runtime_board.prompt_key,
        "template": {
            "key": meta.get("key", runtime_board.prompt_key),
            "name": meta.get("name", ""),
            "version": meta.get("version", ""),
        },
        "messages": [
            {"role": "system", "content": preview["system_prompt"]},
            {"role": "user", "content": preview["user_prompt_template"]},
        ],
        "warnings": [],
        "estimated_chars": len(preview["system_prompt"]),
    }


@dynamic_router.get("/boards/{slug}")
async def get_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Get a single board by slug."""
    board = await db_service.get_board_by_slug(session, slug)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return serialize_board(board)


@dynamic_router.get("/boards/{slug}/perspectives")
async def get_board_perspectives(slug: str, session: AsyncSession = Depends(get_session)):
    """List available perspectives for a board."""
    board = await db_service.get_board_by_slug(session, slug)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    perspectives_data = board.perspectives or {}
    active = perspectives_data.get("active", ["overview"])
    return {"perspectives": active, "default": active[0] if active else "overview"}


@dynamic_router.post("/boards/{slug}/preview")
async def preview_board(slug: str, session: AsyncSession = Depends(get_session)):
    """
    Run the source adapter and LLM generation for a board without saving to the DB.
    Returns the generated DailySummaryResponse.
    """
    board = await db_service.get_board_by_slug(session, slug)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return await run_board_preview_runtime(board, session)


@dynamic_router.patch("/boards/{slug}")
async def update_board(
    slug: str,
    payload: BoardUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update a board's metadata/config."""
    updates = payload.model_dump(exclude_unset=True)
    if "prompt_key" in updates and updates["prompt_key"] is not None:
        updates["prompt_key"] = validate_board_prompt_key_or_400(updates["prompt_key"])
    if "source_type" in updates or ("source_config" in updates and updates["source_config"] is not None):
        existing_board = await db_service.get_board_by_slug(session, slug)
        if not existing_board:
            raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
        effective_source_type = updates.get("source_type", existing_board.source_type)
        effective_source_config = updates.get("source_config", existing_board.source_config)
        validate_board_source_payload(effective_source_type, effective_source_config)
    board = await db_service.update_board(session, slug, updates)
    if not board:
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    if board_supports_rss_sources(board) and ("source_type" in updates or "source_config" in updates):
        board = await db_service.sync_board_rss_sources(session, board)
    return serialize_board(board)


@dynamic_router.get("/boards/{slug}/sources")
async def list_board_sources_endpoint(
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    board = await resolve_active_board(session, slug)
    if not board_supports_rss_sources(board):
        return []
    sources = await db_service.list_board_sources(session, board.id, "rss", enabled_only=True)
    return [serialize_source(source) for source in sources]


@dynamic_router.post("/boards/{slug}/sources")
async def add_board_source_endpoint(
    slug: str,
    payload: BoardSourceCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    board = await resolve_active_board(session, slug)
    if not board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")
    url = normalize_source_url_or_400(payload.url)
    source = await db_service.add_board_source(
        session,
        board,
        url,
        name=payload.name.strip(),
        credibility_override=payload.credibility_override.strip(),
    )
    return serialize_source(source)


@dynamic_router.patch("/boards/{slug}/sources/{source_id}")
async def update_board_source_endpoint(
    slug: str,
    source_id: int,
    payload: BoardSourceUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    board = await resolve_active_board(session, slug)
    if not board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")
    url = normalize_source_url_or_400(payload.url) if payload.url is not None else None
    source = await db_service.update_board_source(
        session,
        board,
        source_id,
        url=url,
        name=payload.name.strip() if payload.name is not None else None,
        enabled=payload.enabled,
        credibility_override=payload.credibility_override,
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found.")
    return serialize_source(source)


@dynamic_router.delete("/boards/{slug}/sources/{source_id}")
async def delete_board_source_endpoint(
    slug: str,
    source_id: int,
    session: AsyncSession = Depends(get_session),
):
    board = await resolve_active_board(session, slug)
    if not board_supports_rss_sources(board):
        raise HTTPException(status_code=400, detail="P0 source management only supports RSS sources.")
    ok = await db_service.delete_board_source(session, board, source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"status": "ok"}


@dynamic_router.delete("/boards/{slug}")
async def delete_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Soft-delete a board (mark inactive). The default board cannot be deleted."""
    ok = await db_service.delete_board(session, slug)
    if not ok:
        board = await db_service.get_board_by_slug(session, slug)
        if board and board.is_default:
            raise HTTPException(status_code=400, detail="The default board cannot be deleted.")
        raise HTTPException(status_code=404, detail=f"Board '{slug}' not found.")
    return {"status": "ok"}
