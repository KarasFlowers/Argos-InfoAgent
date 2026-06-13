"""
Repository sub-package.

``DBService`` delegates to the three repo classes while preserving
the original public API.
"""
from app.services.repositories.summary_repo import SummaryRepo
from app.services.repositories.persona_repo import PersonaRepo
from app.services.repositories.board_repo import BoardRepo
from app.services.repositories.read_state_repo import ReadStateRepo
from app.services.repositories.source_repo import SourceRepo


class DBService(SummaryRepo, PersonaRepo, BoardRepo, ReadStateRepo, SourceRepo):
    """Facade that composes all repository mixins."""
    pass


db_service = DBService()

__all__ = ["DBService", "db_service"]
