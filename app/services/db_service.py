"""
Facade — re-exports ``DBService`` and the singleton ``db_service``
from the ``app.services.repositories`` subpackage so that all existing
imports::

    from app.services.db_service import db_service

continue to work without changes.
"""

from app.services.repositories import DBService, db_service  # noqa: F401

__all__ = ["DBService", "db_service"]
