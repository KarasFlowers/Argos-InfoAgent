"""
Pure-LLM source adapter.

Produces original daily content WITHOUT any external data source. Useful for
boards like 冷知识 / 英语学习 / 名人名言 where the LLM itself is the content.
"""

import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.source_adapters.base import SourceAdapter

if TYPE_CHECKING:
    from app.models.domain import Board
    from app.models.schemas import DailySummaryResponse

logger = logging.getLogger(__name__)


class PureLLMAdapter(SourceAdapter):
    """Ask the LLM to produce today's items directly based on board config."""

    source_type = "pure_llm"

    async def produce(
        self,
        board: "Board",
        session: AsyncSession,
        one_time_preference: str | None = None,
        since_hours: int = 24,  # noqa: ARG002 — pure LLM has no date filter
    ) -> "tuple[DailySummaryResponse | None, dict[str, str]]":
        # Lazy-import to avoid circulars.
        from app.services.llm_service import llm_service

        summary = await llm_service.generate_pure_llm_summary(
            board=board,
            session=session,
            one_time_preference=one_time_preference,
        )
        return summary, {}
