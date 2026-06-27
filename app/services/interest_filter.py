"""
AI Interest Filter Service.

Pre-filters content items based on user personas before they reach the LLM
scoring/summarisation pipeline. Two layers:

1. **Keyword pre-filter** (free, no LLM call):
   - Drops items matching ``block_topic`` personas.
   - Boosts items matching ``focus_topic`` / ``extracted`` personas to the front.

2. **Embedding similarity filter** (optional, requires Bi-Encoder model):
   - When the Bi-Encoder model is available, computes cosine similarity
     between persona content embeddings and item title/content embeddings.
   - Falls back to keyword-only logic when the model is not loaded.

3. **Persona-aware scoring prompt injection** (used by ScoringMixin):
   - Builds a concise interest context string from active personas so the
     LLM quality scorer can factor user interests into scores.

This keeps the filter lightweight while still allowing the LLM to make nuanced
decisions about borderline items.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from app.models.domain import UserPersona
    from app.models.schemas import ContentItem

logger = logging.getLogger(__name__)


class InterestFilter:
    """Stateless interest-based content filter."""

    def __init__(self, personas: list[UserPersona]):
        self._personas = personas
        self._block_patterns: list[re.Pattern] = []
        self._boost_keywords: list[str] = []
        self._focus_texts: list[str] = []  # raw text for embedding
        self._focus_embeddings: np.ndarray | None = None  # lazily computed

        for p in personas:
            if p.category == "block_topic" and p.content:
                # Each block_topic persona is a keyword/phrase to exclude
                pattern = re.compile(re.escape(p.content), re.IGNORECASE)
                self._block_patterns.append(pattern)
            elif p.category in ("focus_topic", "extracted") and p.content:
                # Extract first meaningful keyword chunk for boosting
                keywords = [w.strip() for w in p.content.split(",")]
                self._boost_keywords.extend(keywords)
                # Keep full text for embedding-based similarity
                self._focus_texts.append(p.content)

    @property
    def has_interests(self) -> bool:
        return bool(self._block_patterns or self._boost_keywords)

    def _ensure_embeddings(self) -> bool:
        """Lazily compute focus embeddings. Returns True if embeddings are available."""
        if self._focus_embeddings is not None:
            return True
        if not self._focus_texts:
            return False
        try:
            from app.services.rag_service import get_bi_encoder

            bi_encoder = get_bi_encoder()
            self._focus_embeddings = bi_encoder.encode(self._focus_texts)
            logger.debug("Computed %d focus embeddings for interest filter", len(self._focus_texts))
            return True
        except Exception as exc:
            logger.debug("Bi-Encoder not available for interest filter, using keyword fallback: %s", exc)
            return False

    def filter_items(self, items: list[ContentItem]) -> list[ContentItem]:
        """
        Apply pre-filter:
        - Remove items whose title matches any block_topic pattern.
        - Sort remaining so that items matching boost keywords / embeddings come first.

        Returns a new list (does not mutate the input).
        """
        if not self._personas:
            return items

        # 1. Block filter
        kept = []
        blocked_count = 0
        for item in items:
            title = item.title or ""
            if any(pat.search(title) for pat in self._block_patterns):
                blocked_count += 1
                continue
            kept.append(item)

        if blocked_count:
            logger.info("Interest filter: blocked %d items via block_topic rules", blocked_count)

        # 2. Boost sort — try embedding similarity first, fall back to keywords
        has_embeddings = self._ensure_embeddings() and self._focus_embeddings is not None

        if has_embeddings:
            kept = self._sort_by_embedding_similarity(kept)
        elif self._boost_keywords:
            kept = self._sort_by_keyword_boost(kept)

        return kept

    def _sort_by_embedding_similarity(self, items: list[ContentItem]) -> list[ContentItem]:
        """Sort items by cosine similarity to focus embeddings (descending)."""
        from app.services.rag_service import get_bi_encoder

        bi_encoder = get_bi_encoder()

        texts = []
        for item in items:
            kp_text = " ".join(item.key_points) if hasattr(item, "key_points") and item.key_points else ""
            texts.append(f"{item.title or ''} {kp_text}")

        if not texts:
            return items

        item_embeddings = bi_encoder.encode(texts)
        # Compute max similarity across all focus embeddings for each item
        scores = []
        for _i, emb in enumerate(item_embeddings):
            emb_norm = emb / (np.linalg.norm(emb) + 1e-9)
            max_sim = 0.0
            for focus_emb in self._focus_embeddings:
                focus_norm = focus_emb / (np.linalg.norm(focus_emb) + 1e-9)
                sim = float(np.dot(focus_norm, emb_norm))
                if sim > max_sim:
                    max_sim = sim
            scores.append(-max_sim)  # negative for descending sort

        paired = list(zip(scores, items, strict=False))
        paired.sort(key=lambda x: x[0])
        return [item for _, item in paired]

    def _sort_by_keyword_boost(self, items: list[ContentItem]) -> list[ContentItem]:
        """Sort items by keyword match score (descending)."""

        def _boost_score(item: ContentItem) -> int:
            title_lower = (item.title or "").lower()
            content_lower = (item.content or "")[:200].lower()
            score = 0
            for kw in self._boost_keywords:
                kw_lower = kw.lower()
                if kw_lower in title_lower:
                    score += 2
                elif kw_lower in content_lower:
                    score += 1
            return -score  # negative for descending sort

        items_copy = list(items)
        items_copy.sort(key=_boost_score)
        return items_copy

    def build_scoring_context(self) -> str:
        """
        Build a concise persona context string for injection into the LLM
        scoring prompt. Returns empty string if no relevant personas.
        """
        if not self._personas:
            return ""

        lines = []
        for p in self._personas:
            if p.category == "focus_topic":
                lines.append(f"- MUST prioritize: {p.content}")
            elif p.category == "block_topic":
                lines.append(f"- MUST exclude: {p.content}")
            elif p.category == "extracted":
                lines.append(f"- User interest: {p.content}")
            elif p.category == "prefer_source":
                lines.append(f"- Preferred source: {p.content}")
            elif p.category == "avoid_source":
                lines.append(f"- De-prioritize source: {p.content}")

        if not lines:
            return ""

        return (
            "\n\nUSER INTEREST GUIDELINES (factor these into your scoring):\n"
            + "\n".join(lines)
            + "\nArticles matching user interests should score 1-2 points higher. "
            "Articles matching block topics should score 1 (minimum)."
        )


def build_interest_filter(personas: list[UserPersona]) -> InterestFilter:
    """Factory helper."""
    return InterestFilter(personas)
