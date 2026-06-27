"""
Source adapters: pluggable content producers for boards.

Each adapter implements ``SourceAdapter.produce(board, session, ...)`` which
returns a ``DailySummaryResponse`` (or None on failure). The router dispatches
to the correct adapter based on ``board.source_type``.

Built-in adapters:
  - ``rss``         : pull from RSS feeds in ``board.source_config["feeds"]``
  - ``pure_llm``    : ask the LLM to generate N items, no external sources
  - ``hackernews``  : fetch Hacker News top stories + comments
  - ``reddit``      : fetch Reddit subreddit/user posts + comments
  - ``github``      : fetch GitHub user events & repo releases
  - ``multi``       : fetch from multiple source types in parallel

Skill-based adapters:
  Any module placed at ``app/skills/<name>/skill.py`` that defines a class
  inheriting from ``SourceAdapter`` will be auto-registered at startup.
"""

import importlib
import logging
from pathlib import Path

from app.services.source_adapters.base import SourceAdapter, UnknownSourceTypeError
from app.services.source_adapters.github_adapter import GitHubAdapter
from app.services.source_adapters.hackernews_adapter import HackerNewsAdapter
from app.services.source_adapters.multi_adapter import MultiSourceAdapter
from app.services.source_adapters.pure_llm_adapter import PureLLMAdapter
from app.services.source_adapters.reddit_adapter import RedditAdapter
from app.services.source_adapters.rss_adapter import RSSAdapter

_logger = logging.getLogger(__name__)

_REGISTRY: dict[str, SourceAdapter] = {
    "rss": RSSAdapter(),
    "pure_llm": PureLLMAdapter(),
    "hackernews": HackerNewsAdapter(),
    "reddit": RedditAdapter(),
    "github": GitHubAdapter(),
    "multi": MultiSourceAdapter(),
}


def _discover_skill_adapters() -> None:
    """Scan ``app/skills/*/skill.py`` for SourceAdapter subclasses and register them."""
    skills_dir = Path(__file__).resolve().parents[2] / "skills"
    if not skills_dir.is_dir():
        return

    for skill_path in skills_dir.iterdir():
        if not skill_path.is_dir():
            continue
        skill_module_path = skill_path / "skill.py"
        if not skill_module_path.is_file():
            continue

        module_name = f"app.skills.{skill_path.name}.skill"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            _logger.warning("Failed to import skill '%s': %s", module_name, exc)
            continue

        # Find SourceAdapter subclasses defined in the module
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, SourceAdapter)
                and obj is not SourceAdapter
                and getattr(obj, "source_type", "")
            ):
                source_type = obj.source_type
                if source_type in _REGISTRY:
                    _logger.warning(
                        "Skill '%s' defines source_type='%s' which conflicts with " "an existing adapter; skipping.",
                        module_name,
                        source_type,
                    )
                    continue
                _REGISTRY[source_type] = obj()
                _logger.info(
                    "Registered skill adapter '%s' (source_type='%s')",
                    module_name,
                    source_type,
                )


_discover_skill_adapters()

VALID_SOURCE_TYPES: tuple[str, ...] = tuple(_REGISTRY.keys())


def get_adapter(source_type: str) -> SourceAdapter:
    """Return the adapter for a board's source_type. Raises if unknown."""
    adapter = _REGISTRY.get(source_type)
    if adapter is None:
        raise UnknownSourceTypeError(
            f"No adapter registered for source_type='{source_type}'. " f"Valid types: {list(_REGISTRY.keys())}"
        )
    return adapter


def register_adapter(adapter: SourceAdapter) -> None:
    """Programmatically register an adapter at runtime."""
    global VALID_SOURCE_TYPES
    source_type = adapter.source_type
    if not source_type:
        raise ValueError("Adapter must define a non-empty source_type class attribute.")
    _REGISTRY[source_type] = adapter
    VALID_SOURCE_TYPES = tuple(_REGISTRY.keys())


__all__ = [
    "SourceAdapter",
    "UnknownSourceTypeError",
    "get_adapter",
    "register_adapter",
    "VALID_SOURCE_TYPES",
    "RSSAdapter",
    "PureLLMAdapter",
    "HackerNewsAdapter",
    "RedditAdapter",
    "GitHubAdapter",
    "MultiSourceAdapter",
]
