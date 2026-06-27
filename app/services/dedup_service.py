"""
Deduplication service: URL-based cross-source merge + AI semantic dedup.
Ported from Horizon's orchestrator logic.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.models.schemas import ContentItem
from app.prompts import get_prompt

if TYPE_CHECKING:
    from app.services.llm.client import LLMClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts for AI semantic dedup
# ---------------------------------------------------------------------------

# Lazily resolved: avoid importing get_prompt at module load so a missing/
# malformed template file doesn't break the whole dedup module (and every
# downstream caller). Falls back to a minimal inline prompt if the template
# is unavailable.
_DEDUP_FALLBACK_SYSTEM = (
    "You are a deduplication assistant. Given a numbered list of news items "
    "(title, summary), identify groups covering the SAME event. "
    'Return {"duplicates": [[primary_index, dup_index, ...]]}. '
    "Items not duplicating anything must not appear. Output ONLY the JSON."
)


def _topic_dedup_system() -> str:
    """Return the semantic-dedup system prompt, loaded on first use."""
    try:
        return get_prompt("semantic_dedup")
    except (FileNotFoundError, Exception) as exc:  # noqa: BLE001
        logger.warning("semantic_dedup prompt unavailable, using fallback: %s", exc)
        return _DEDUP_FALLBACK_SYSTEM


TOPIC_DEDUP_USER = "Here are the items:\n\n{items}"


# ---------------------------------------------------------------------------
# URL normalisation & cross-source merge
# ---------------------------------------------------------------------------


def normalize_url(url: str) -> str:
    """Normalise a URL for cross-source dedup grouping.

    Strips scheme (http/https), ``www.`` prefix, trailing slash, and
    fragment so that the same page reached via different entry points
    (e.g. ``https://example.com/article`` vs ``http://www.example.com/article#comments``)
    collapses to the same key.

    **Caveat**: stripping the scheme means ``http://foo.com/a`` and
    ``https://bar.com/a`` (different hosts) would collide.  This is
    acceptable because real-world cross-posting always shares the same
    hostname; the merge logic in ``merge_cross_source_duplicates`` adds
    an extra safety guard by checking that grouped items share the same
    hostname before merging.
    """
    parsed = urlparse(str(url))
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def merge_cross_source_duplicates(items: list[ContentItem]) -> list[ContentItem]:
    """Group by normalised URL, keep richest content, merge metadata/comments.

    Items that normalise to the same key but have **different hostnames**
    are kept separate as a safety guard against scheme-stripping collisions.
    """
    url_groups: dict[str, list[ContentItem]] = {}
    for item in items:
        key = normalize_url(item.url)
        url_groups.setdefault(key, []).append(item)

    merged: list[ContentItem] = []
    for _key, group in url_groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Safety guard: if items in the same normalised group have different
        # hostnames, they are NOT the same page — keep them separate.
        hostnames: dict[str, list[ContentItem]] = {}
        for item in group:
            h = (urlparse(item.url).hostname or "").removeprefix("www.")
            hostnames.setdefault(h, []).append(item)
        if len(hostnames) > 1:
            for sub_items in hostnames.values():
                if len(sub_items) == 1:
                    merged.append(sub_items[0])
                else:
                    merged.append(_merge_group(sub_items))
            continue

        merged.append(_merge_group(group))

    return merged


def _merge_group(group: list[ContentItem]) -> ContentItem:
    """Merge a list of ContentItems that cover the same URL into one."""
    primary = max(group, key=lambda x: len(x.content or ""))

    all_sources: set[str] = set()
    for item in group:
        all_sources.add(item.source_type)
        for mk, mv in item.metadata.items():
            if mk not in primary.metadata or not primary.metadata[mk]:
                primary.metadata[mk] = mv

        if item is not primary and item.content:
            if primary.content and item.content not in primary.content:
                primary.content = (primary.content or "") + f"\n\n--- From {item.source_type} ---\n" + item.content

    primary.metadata["merged_sources"] = list(all_sources)
    return primary


# ---------------------------------------------------------------------------
# AI semantic dedup
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict | None:
    """Best-effort extraction of a JSON object from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


async def merge_topic_duplicates(
    items: list[ContentItem],
    llm_client: LLMClient,
) -> list[ContentItem]:
    """Send titles to LLM, identify duplicate groups, merge.

    Falls back to returning *items* unchanged on any failure.
    """
    if len(items) <= 1:
        return items

    lines: list[str] = []
    for i, item in enumerate(items):
        summary = (item.content or "")[:120]
        lines.append(f"[{i}] {item.title}\n    Summary: {summary}")
    items_text = "\n\n".join(lines)

    try:
        response = await llm_client.chat(
            messages=[
                {"role": "system", "content": _topic_dedup_system()},
                {"role": "user", "content": TOPIC_DEDUP_USER.format(items=items_text)},
            ],
            tier="fast",
            label="dedup",
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=1500,
        )
        result = _parse_json_response(response.choices[0].message.content or "")
        if result is None:
            logger.warning("dedup: could not parse AI response, skipping")
            return items

        duplicate_groups = result.get("duplicates", [])
    except Exception as e:
        logger.warning("dedup: AI call failed (%s), skipping", e)
        return items

    if not duplicate_groups:
        return items

    drop_indices: set[int] = set()
    for group in duplicate_groups:
        if not isinstance(group, list) or len(group) < 2:
            continue
        primary_idx = group[0]
        if not (0 <= primary_idx < len(items)):
            continue
        primary = items[primary_idx]
        for dup_idx in group[1:]:
            if not isinstance(dup_idx, int) or not (0 <= dup_idx < len(items)):
                continue
            if dup_idx == primary_idx:
                continue
            dup = items[dup_idx]
            if dup.content:
                if not primary.content or dup.content not in primary.content:
                    label = dup.source_type
                    primary.content = (primary.content or "") + f"\n\n--- From {label} ---\n{dup.content}"
            logger.info(
                "dedup: keep [%d] %s  |  drop [%d] %s",
                primary_idx,
                primary.title[:50],
                dup_idx,
                dup.title[:50],
            )
            drop_indices.add(dup_idx)

    return [item for i, item in enumerate(items) if i not in drop_indices]
