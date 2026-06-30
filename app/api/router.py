import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.boards import resolve_active_board
from app.api.routes import board_wizard as board_wizard_routes
from app.api.routes.boards import add_board_source_endpoint as _boards_add_board_source_endpoint
from app.api.routes.boards import create_board as _boards_create_board
from app.api.routes.boards import delete_board as _boards_delete_board
from app.api.routes.boards import delete_board_source_endpoint as _boards_delete_board_source_endpoint
from app.api.routes.boards import dynamic_router as board_dynamic_router
from app.api.routes.boards import get_board as _boards_get_board
from app.api.routes.boards import get_board_perspectives as _boards_get_board_perspectives
from app.api.routes.boards import list_board_sources_endpoint as _boards_list_board_sources_endpoint
from app.api.routes.boards import list_boards as _boards_list_boards
from app.api.routes.boards import list_prompt_templates as _boards_list_prompt_templates
from app.api.routes.boards import preview_board as _boards_preview_board
from app.api.routes.boards import preview_board_from_payload as _boards_preview_board_from_payload
from app.api.routes.boards import render_prompt_preview as _boards_render_prompt_preview
from app.api.routes.boards import router as boards_router
from app.api.routes.boards import update_board as _boards_update_board
from app.api.routes.boards import update_board_source_endpoint as _boards_update_board_source_endpoint
from app.api.routes.briefing import RefineRequest
from app.api.routes.briefing import get_daily_briefing as _briefing_get_daily_briefing
from app.api.routes.briefing import get_refinement_session as _briefing_get_refinement_session
from app.api.routes.briefing import refine_daily_briefing as _briefing_refine_daily_briefing
from app.api.routes.briefing import router as briefing_router
from app.api.routes.catchup import generate_catchup_digest as _catchup_generate_catchup_digest
from app.api.routes.catchup import get_catchup_status as _catchup_get_catchup_status
from app.api.routes.catchup import router as catchup_router
from app.api.routes.feed import get_rss_feed as _feed_get_rss_feed
from app.api.routes.feed import manually_trigger_rss_fetch as _feed_manually_trigger_rss_fetch
from app.api.routes.feed import router as feed_router
from app.api.routes.history import router as history_router
from app.api.routes.insights import router as insights_router
from app.api.routes.persona import router as persona_router
from app.api.routes.saved import router as saved_router
from app.api.routes.settings import router as settings_router
from app.api.routes.silent_mode import router as silent_mode_router
from app.api.routes.sources import check_single_feed_url, discover_feed_links, parse_feed_links
from app.api.routes.sources import get_source_coverage_endpoint as _sources_get_source_coverage_endpoint
from app.api.routes.sources import router as sources_router
from app.api.routes.summary import generate_summary as _summary_generate_summary
from app.api.routes.summary import router as summary_router
from app.api.routes.system import router as system_router
from app.api.schemas import (
    BoardCreateRequest,
    BoardPreviewRequest,
    BoardSourceCreateRequest,
    BoardSourceUpdateRequest,
    BoardUpdateRequest,
)
from app.api.url_params import normalize_article_url_or_400, normalize_source_url_or_400
from app.core.db import get_session
from app.services.board_api_service import (
    board_supports_rss_sources,
    build_source_topic,
    serialize_board,
    serialize_source,
    validate_board_prompt_key_or_400,
    validate_board_source_payload,
    validate_rss_feed_urls_in_config,
)

logger = logging.getLogger(__name__)


def _normalize_article_url_or_400(url: str) -> str:
    """Compatibility export for tests and older internal imports."""
    return normalize_article_url_or_400(url)


def _normalize_source_url_or_400(url: str | None) -> str:
    """Compatibility export for tests and older internal imports."""
    return normalize_source_url_or_400(url)


api_router = APIRouter()
api_router.include_router(briefing_router)
api_router.include_router(board_wizard_routes.router)
api_router.include_router(boards_router)
api_router.include_router(catchup_router)
api_router.include_router(feed_router)
api_router.include_router(history_router)
api_router.include_router(insights_router)
api_router.include_router(persona_router)
api_router.include_router(saved_router)
api_router.include_router(settings_router)
api_router.include_router(silent_mode_router)
api_router.include_router(sources_router)
api_router.include_router(summary_router)
api_router.include_router(system_router)


async def get_rss_feed(
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _feed_get_rss_feed(board=board, session=session)


async def get_source_coverage_endpoint(
    board: str | None = None,
    date: str | None = None,
    days: int = Query(default=3, ge=2, le=7),
    limit: int = Query(default=6, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _sources_get_source_coverage_endpoint(
        board=board,
        date=date,
        days=days,
        limit=limit,
        session=session,
    )


async def manually_trigger_rss_fetch():
    """Compatibility wrapper for older direct imports."""
    return await _feed_manually_trigger_rss_fetch()


async def _test_single_feed(url: str, timeout: float = 15.0) -> dict:
    """Compatibility wrapper for wizard tests and older internal imports."""
    return await check_single_feed_url(url, timeout=timeout)


async def _discover_feeds(homepage: str, timeout: float = 8.0, limit: int = 4) -> list[str]:
    """Compatibility wrapper for wizard tests and older internal imports."""
    return await discover_feed_links(homepage, timeout=timeout, limit=limit)


def _parse_feed_links(html_text: str, base_url: str, limit: int = 4) -> list[str]:
    """Compatibility wrapper for wizard tests and older internal imports."""
    return parse_feed_links(html_text, base_url, limit=limit)


async def _resolve_board(session: AsyncSession, slug: str | None):
    return await resolve_active_board(session, slug)


def _serialize_source(source) -> dict:
    return serialize_source(source)


def _build_source_topic(board, source_name: str = "") -> str:
    return build_source_topic(board, source_name)


def _board_supports_rss_sources(board) -> bool:
    return board_supports_rss_sources(board)


async def generate_summary(
    force: bool = False,
    date: str | None = None,
    preference: str | None = None,
    save_preference: bool = False,
    board: str | None = None,
    perspective: str = "overview",
    lite: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _summary_generate_summary(
        force=force,
        date=date,
        preference=preference,
        save_preference=save_preference,
        board=board,
        perspective=perspective,
        lite=lite,
        session=session,
    )


async def get_daily_briefing(
    date: str | None = None,
    board: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _briefing_get_daily_briefing(date=date, board=board, session=session)


async def refine_daily_briefing(
    payload: RefineRequest,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _briefing_refine_daily_briefing(payload=payload, session=session)


async def get_refinement_session(
    session_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _briefing_get_refinement_session(session_id=session_id, session=session)


# ------------------------------------------------------------------
# Board (custom section) CRUD
# ------------------------------------------------------------------


def _serialize_board(board) -> dict:
    return serialize_board(board)


def _validate_board_source_payload(source_type: str, source_config: dict | None) -> None:
    validate_board_source_payload(source_type, source_config)


def _validate_rss_feed_urls_in_config(source_type: str, source_config: dict) -> None:
    validate_rss_feed_urls_in_config(source_type, source_config)


def _validate_board_prompt_key_or_400(prompt_key: str | None) -> str:
    return validate_board_prompt_key_or_400(prompt_key)


async def list_boards(
    include_inactive: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_list_boards(include_inactive=include_inactive, session=session)


async def create_board(
    payload: BoardCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_create_board(payload=payload, session=session)


_probe_url = board_wizard_routes._probe_url
_github_headers = board_wizard_routes._github_headers
_count_via_scraper = board_wizard_routes._count_via_scraper
_enrich_deep = board_wizard_routes._enrich_deep
_validate_source_group = board_wizard_routes._validate_source_group
_validate_config_sources = board_wizard_routes._validate_config_sources
_derive_feed_validation = board_wizard_routes._derive_feed_validation
_serialize_source_quality_report = board_wizard_routes._serialize_source_quality_report
_discover_rss_candidates = board_wizard_routes._discover_rss_candidates
_probe_common_feed_paths = board_wizard_routes._probe_common_feed_paths
_rsshub_candidate_urls = board_wizard_routes._rsshub_candidate_urls
_plan_to_nonrss_config = board_wizard_routes._plan_to_nonrss_config
_discover_reddit_config = board_wizard_routes._discover_reddit_config
_discover_github_config = board_wizard_routes._discover_github_config
discover_and_verify = board_wizard_routes.discover_and_verify
_verify_and_fix_feeds = board_wizard_routes._verify_and_fix_feeds
board_wizard = board_wizard_routes.board_wizard
_run_wizard_pipeline = board_wizard_routes._run_wizard_pipeline
WizardPreviewRequest = board_wizard_routes.WizardPreviewRequest
wizard_preview = board_wizard_routes.wizard_preview
FixFeedsRequest = board_wizard_routes.FixFeedsRequest
wizard_fix_feeds = board_wizard_routes.wizard_fix_feeds


async def list_prompt_templates():
    """Compatibility wrapper for older direct imports."""
    return await _boards_list_prompt_templates()


async def render_prompt_preview(
    payload: BoardPreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_render_prompt_preview(payload=payload, session=session)


async def get_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Compatibility wrapper for older direct imports."""
    return await _boards_get_board(slug=slug, session=session)


async def get_board_perspectives(slug: str, session: AsyncSession = Depends(get_session)):
    """Compatibility wrapper for older direct imports."""
    return await _boards_get_board_perspectives(slug=slug, session=session)


async def preview_board_from_payload(
    payload: BoardPreviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_preview_board_from_payload(payload=payload, session=session)


async def preview_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Compatibility wrapper for older direct imports."""
    return await _boards_preview_board(slug=slug, session=session)


async def update_board(
    slug: str,
    payload: BoardUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_update_board(slug=slug, payload=payload, session=session)


async def list_board_sources_endpoint(
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_list_board_sources_endpoint(slug=slug, session=session)


async def add_board_source_endpoint(
    slug: str,
    payload: BoardSourceCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_add_board_source_endpoint(slug=slug, payload=payload, session=session)


discover_board_sources_endpoint = board_wizard_routes.discover_board_sources_endpoint


async def update_board_source_endpoint(
    slug: str,
    source_id: int,
    payload: BoardSourceUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_update_board_source_endpoint(
        slug=slug,
        source_id=source_id,
        payload=payload,
        session=session,
    )


get_board_source_alternatives_endpoint = board_wizard_routes.get_board_source_alternatives_endpoint


api_router.include_router(board_dynamic_router)


async def delete_board_source_endpoint(
    slug: str,
    source_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _boards_delete_board_source_endpoint(slug=slug, source_id=source_id, session=session)


async def delete_board(slug: str, session: AsyncSession = Depends(get_session)):
    """Compatibility wrapper for older direct imports."""
    return await _boards_delete_board(slug=slug, session=session)


# ---------------------------------------------------------------------------
# Catch-up Digest & Cache Viewer
# ---------------------------------------------------------------------------


async def get_catchup_status(
    board: str | None = None,
    max_days: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _catchup_get_catchup_status(board=board, max_days=max_days, session=session)


async def generate_catchup_digest(
    board: str | None = None,
    max_days: int = 7,
    session: AsyncSession = Depends(get_session),
):
    """Compatibility wrapper for older direct imports."""
    return await _catchup_generate_catchup_digest(board=board, max_days=max_days, session=session)
