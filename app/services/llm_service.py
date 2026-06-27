"""
Facade — re-exports ``LLMService`` and the singleton ``llm_service``
from the ``app.services.llm`` subpackage so that all existing imports::

    from app.services.llm_service import llm_service

continue to work without changes.
"""

from app.services.llm import LLMService, llm_service  # noqa: F401

__all__ = ["LLMService", "llm_service"]
