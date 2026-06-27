"""
Base class for board source adapters.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse


class UnknownSourceTypeError(ValueError):
    """Raised when a board specifies a source_type with no registered adapter."""


class SourceAdapter(ABC):
    """
    Strategy interface for content producers.

    Each concrete adapter reads the board's configuration and produces a
    ``DailySummaryResponse`` for the current day (or None when nothing can
    be produced).
    """

    source_type: str = ""  # subclasses should set this

    @abstractmethod
    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
        since_hours: int = 24,
    ) -> "tuple[DailySummaryResponse | None, dict[str, str]]":
        """Produce today's summary for this board.

        Args:
            since_hours: How many hours back to look for content.
                Default 24 (today); set higher for catch-up backfill.

        Returns:
            (summary_or_none, content_fallback) where content_fallback maps
            article URL -> pre-fetched body text for RAG ingest.
        """
        raise NotImplementedError
