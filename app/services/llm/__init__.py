"""
LLM service sub-package.

The ``LLMService`` class is assembled here from mixin classes defined
in sibling modules.  The singleton ``llm_service`` is the public entry
point — all existing imports of ``from app.services.llm_service import
llm_service`` continue to work through the facade in ``../llm_service.py``.
"""

import logging

from app.core.config import settings
from app.services.llm.catchup import CatchupMixin
from app.services.llm.client import LLMClient
from app.services.llm.scoring import ScoringMixin
from app.services.llm.summary import SummaryMixin
from app.services.llm.weekly import WeeklyMixin
from app.services.llm.wizard import WizardMixin

logger = logging.getLogger(__name__)


class LLMService(CatchupMixin, ScoringMixin, SummaryMixin, WeeklyMixin, WizardMixin):
    def __init__(self) -> None:
        self._llm: LLMClient | None = None

    @property
    def llm(self) -> LLMClient:
        """Lazy-initialised LLM client — created on first access, not import time."""
        if self._llm is None:
            if not settings.effective_llm_api_key:
                logger.warning("LLM_API_KEY / DEEPSEEK_API_KEY is not set. LLM features will fail.")
            self._llm = LLMClient(settings)
        return self._llm

    @property
    def client(self):
        """Backward-compat: some call-sites still reference self.client."""
        return self.llm.raw

    @property
    def model(self) -> str:
        return self.llm.model


llm_service = LLMService()

__all__ = ["LLMService", "llm_service"]
