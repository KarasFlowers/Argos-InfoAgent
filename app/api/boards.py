from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.db_service import db_service


async def resolve_active_board(session: AsyncSession, slug: str | None):
    """
    Resolve an optional board slug to an active Board row.

    When slug is None, returns the default board. Raises 404 if a provided slug
    does not exist or points to an inactive board.
    """
    if slug:
        board = await db_service.get_board_by_slug(session, slug)
        if not board or not board.is_active:
            raise HTTPException(status_code=404, detail=f"Board '{slug}' not found or inactive.")
        return board
    return await db_service.get_default_board(session)
