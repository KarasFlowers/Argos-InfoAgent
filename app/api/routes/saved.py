from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.url_params import normalize_article_url_or_400
from app.services.saved_service import add_saved, get_saved_url_map, list_saved, remove_saved

router = APIRouter()


class SavedArticleRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    status: Literal["favorite", "read_later"]
    headline: str = Field(default="", max_length=500)
    source: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=120)
    board: str = Field(default="", max_length=64)


class SavedArticleDeleteRequest(BaseModel):
    url: str = Field(min_length=5, max_length=2048)
    status: Literal["favorite", "read_later"]


@router.get("/saved")
async def list_saved_articles(
    status: Literal["favorite", "read_later"] = Query("favorite"),
    limit: int = Query(default=200, ge=1, le=500),
):
    """List saved articles for a given status (favorite | read_later)."""
    return {"status": status, "items": await list_saved(status, limit=limit)}


@router.get("/saved/urls")
async def get_saved_url_map_endpoint():
    """Return {url: [status, ...]} for highlighting saved articles in the UI."""
    return await get_saved_url_map()


@router.post("/saved")
async def add_saved_article(payload: SavedArticleRequest):
    """Save an article under the given status."""
    try:
        url = normalize_article_url_or_400(payload.url)
        await add_saved(
            url,
            payload.status,
            headline=payload.headline,
            source=payload.source,
            category=payload.category,
            board_slug=payload.board,
        )
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/saved")
async def remove_saved_article(payload: SavedArticleDeleteRequest):
    """Remove a saved article for the given status."""
    try:
        url = normalize_article_url_or_400(payload.url)
        await remove_saved(url, payload.status)
        return {"status": "ok"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
