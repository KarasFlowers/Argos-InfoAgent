"""
Prompt template system.

All LLM prompts are stored as ``.md`` files in this package directory.
Each file may carry YAML-like frontmatter delimited by ``---`` lines.
Use ``get_prompt(key, **vars)`` to load and render a template with Jinja2.

Supported variables depend on the template; common ones include:
  - ``board_name``, ``date``, ``interest_context``
  - ``custom_instructions`` (board.system_prompt injected as variable)
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment, TemplateNotFound
from jinja2.sandbox import ImmutableSandboxedEnvironment

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-style frontmatter and return (metadata, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    meta: dict[str, Any] = {}
    for line in raw.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        # Coerce booleans
        if val.lower() in ("true", "false"):
            val = val.lower() == "true"
        # Coerce numbers
        elif val.isdigit():
            val = int(val)
        elif re.match(r"^\d+(\.\d+)?$", val):
            val = float(val)
        meta[key] = val
    body = text[m.end():]
    return meta, body


def _read_prompt_file(key: str) -> tuple[str, dict[str, Any]]:
    """Read raw prompt file, returning (body_without_frontmatter, metadata)."""
    path = _PROMPTS_DIR / f"{key}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt template '{key}' not found at {path}")
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    # Fill implicit metadata
    if "key" not in meta:
        meta["key"] = key
    if "type" not in meta:
        meta["type"] = "unknown"
    if "user_selectable" not in meta:
        meta["user_selectable"] = False
    return body, meta


# Metadata cache (separate from template compilation cache)
_metadata_cache: dict[str, dict[str, Any]] = {}


def _get_metadata(key: str) -> dict[str, Any]:
    """Get template metadata, caching the result."""
    if key not in _metadata_cache:
        _, meta = _read_prompt_file(key)
        _metadata_cache[key] = meta
    return _metadata_cache[key]


# ---------------------------------------------------------------------------
# Jinja2 loader & environment
# ---------------------------------------------------------------------------

class _FileSystemLoader(BaseLoader):
    """Jinja2 loader that reads .md files, stripping frontmatter before rendering."""

    def get_source(self, environment: Environment, template: str):
        path = _PROMPTS_DIR / f"{template}.md"
        if not path.is_file():
            raise TemplateNotFound(template)
        mtime = path.stat().st_mtime
        body, _meta = _read_prompt_file(template)
        # uptodate: check if file has been modified since load
        return body, str(path), lambda: path.stat().st_mtime <= mtime


def _require_filter(value: Any, name: str = "variable") -> Any:
    """Jinja2 filter: raise if value is empty/None."""
    if not value and value != 0:
        raise ValueError(f"Required variable '{name}' is empty or missing.")
    return value


_env = ImmutableSandboxedEnvironment(
    loader=_FileSystemLoader(),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["require"] = _require_filter


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@lru_cache(maxsize=32)
def _load_template_cached(key: str):
    """Cache compiled templates (cleared on restart)."""
    return _env.get_template(key)


def get_prompt(key: str, *, required: bool = True, **variables: Any) -> str:
    """Load and render a prompt template.

    Args:
        key: Template name without extension (e.g. ``"daily_briefing"``).
        required: If ``True`` (default), raise on missing template.
            If ``False``, log a warning and return ``""``.
        **variables: Jinja2 template variables.

    Returns:
        Rendered prompt string, or ``""`` if *required* is False and the
        template is missing.

    Raises:
        FileNotFoundError: If *required* is True and no matching .md file exists.
    """
    try:
        template = _load_template_cached(key)
        return template.render(**variables)
    except TemplateNotFound:
        if required:
            raise FileNotFoundError(
                f"Prompt template '{key}' not found at {_PROMPTS_DIR / f'{key}.md'}"
            )
        logger.warning("Optional prompt template '%s' not found, returning empty string", key)
        return ""


def get_prompt_metadata(key: str) -> dict[str, Any]:
    """Return template metadata (frontmatter fields).

    Returns an empty dict for templates without frontmatter.
    """
    try:
        return dict(_get_metadata(key))
    except FileNotFoundError:
        return {}


def list_prompt_templates(
    *,
    template_type: str | None = None,
    user_selectable: bool | None = None,
) -> list[dict[str, Any]]:
    """List all available prompt templates, optionally filtered.

    Args:
        template_type: Filter by ``type`` field (e.g. ``"board_summary"``).
        user_selectable: Filter by ``user_selectable`` field.

    Returns:
        List of metadata dicts, each containing at least ``key``, ``type``,
        ``user_selectable``, ``name``, ``version``, ``description``.
    """
    results: list[dict[str, Any]] = []
    for path in sorted(_PROMPTS_DIR.glob("*.md")):
        key = path.stem
        try:
            meta = _get_metadata(key)
        except Exception:
            continue
        if template_type is not None and meta.get("type") != template_type:
            continue
        if user_selectable is not None and meta.get("user_selectable") != user_selectable:
            continue
        results.append(meta)
    return results


def is_prompt_selectable(key: str, *, template_type: str = "board_summary") -> bool:
    """Check whether a prompt key can be used as a board summary template.

    A template is selectable when:
    - The file exists.
    - Its ``type`` matches *template_type*.
    - Its ``user_selectable`` is truthy.
    """
    try:
        meta = _get_metadata(key)
    except FileNotFoundError:
        return False
    return bool(
        meta.get("type") == template_type
        and meta.get("user_selectable")
    )


__all__ = [
    "get_prompt",
    "get_prompt_metadata",
    "list_prompt_templates",
    "is_prompt_selectable",
]
