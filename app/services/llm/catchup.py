"""Catch-up digest generation — condenses multiple days of summaries into one briefing."""
import json
import logging

from app.core.config import settings
from app.models.schemas import DailySummaryResponse
from app.prompts import get_prompt
from app.services.dedup_service import normalize_url
from app.services.llm.client import CircuitOpenError

logger = logging.getLogger(__name__)

# Higher threshold than daily scoring (5) — catch-up should only keep important items.
CATCHUP_QUALITY_THRESHOLD = 7

_CATCHUP_SCORING_PROMPT = """You are a news importance evaluator for a catch-up briefing. The reader has missed several days and needs ONLY truly important updates.

For each news item below, score its IMPORTANCE from 1-10 based on:
- Industry impact: funding rounds, acquisitions, major launches, regulatory actions (high)
- Technical significance: breakthroughs, major releases, critical CVEs (high)
- Wide reach: affects many developers/users or signals a clear trend shift (high)
- Low value: minor updates, routine releases, opinion pieces, listicles, how-to guides (low)

Be STRICT — a score of 7+ means "the reader would miss something important if they skipped this".
Output ONLY a valid JSON object with a top-level "scores" array.
Example:
{
  "scores": [{"index": 0, "score": 8}, {"index": 1, "score": 3}]
}
Do NOT include any other text."""


def _build_catchup_data(summaries: list[dict]) -> str:
    """Build a dense text representation of multiple days' summaries for the LLM."""
    daily_inputs = []
    for s in summaries:
        date = s.get("date", "Unknown Date")
        overview = s.get("overview", "")
        items_detail = []
        for n in s.get("top_news", []):
            headline = n.get("headline", "")
            key_points = n.get("key_points", [])
            source = n.get("source", "")
            link = n.get("original_link", "")
            items_detail.append(
                f"  - {headline} ({source}) {link}\n    Key: {'; '.join(key_points[:3])}"
            )
        daily_inputs.append(
            f"### {date}\nOverview: {overview}\nItems:\n" + "\n".join(items_detail)
        )
    return "\n\n".join(daily_inputs)


class CatchupMixin:
    """Mixin providing catch-up digest generation for LLMService."""

    @staticmethod
    def _catchup_story_key(item: dict) -> tuple[str, str] | None:
        """Build a stable dedupe key for a catch-up news item."""
        url = str(item.get("original_link", "") or "").strip()
        if url:
            normalized = normalize_url(url).strip().lower()
            if normalized:
                return ("url", normalized)

        headline = str(item.get("headline", "") or "").strip().lower()
        if headline:
            return ("headline", headline[:160])
        return None

    @staticmethod
    def _catchup_item_richness(item: dict) -> int:
        """Prefer the version with more detail when duplicates collide."""
        key_points = item.get("key_points") or []
        tags = item.get("tags") or []
        joined = " ".join(
            [
                str(item.get("headline", "") or ""),
                str(item.get("original_link", "") or ""),
                " ".join(str(k) for k in key_points),
                " ".join(str(t) for t in tags),
            ]
        )
        return len(joined)

    @classmethod
    def _prefer_catchup_item(cls, candidate: dict, incumbent: dict) -> bool:
        """Choose the newer or richer duplicate when the same story repeats."""
        candidate_date = str(candidate.get("_origin_date", "") or "")
        incumbent_date = str(incumbent.get("_origin_date", "") or "")
        if candidate_date != incumbent_date:
            return candidate_date > incumbent_date

        candidate_richness = cls._catchup_item_richness(candidate)
        incumbent_richness = cls._catchup_item_richness(incumbent)
        if candidate_richness != incumbent_richness:
            return candidate_richness > incumbent_richness

        return int(candidate.get("_origin_order", 0) or 0) > int(
            incumbent.get("_origin_order", 0) or 0
        )

    @classmethod
    def _dedupe_catchup_summaries(cls, summaries: list[dict]) -> list[dict]:
        """Remove repeated stories across days before scoring or digesting.

        Keeps the newest variant of the same article URL, then groups the
        survivors back into their original daily summary shape.
        """
        if not summaries:
            return []

        winners: dict[tuple[str, str], dict] = {}
        unkeyed: list[dict] = []
        origin_order = 0

        for summary in summaries:
            date = str(summary.get("date", "") or "")
            for item in summary.get("top_news", []) or []:
                candidate = dict(item)
                candidate["_origin_date"] = date
                candidate["_origin_order"] = origin_order
                origin_order += 1

                key = cls._catchup_story_key(candidate)
                if key is None:
                    unkeyed.append(candidate)
                    continue

                incumbent = winners.get(key)
                if incumbent is None or cls._prefer_catchup_item(candidate, incumbent):
                    winners[key] = candidate

        grouped_items: dict[str, list[dict]] = {}
        kept_items = sorted(
            [*winners.values(), *unkeyed],
            key=lambda item: (
                str(item.get("_origin_date", "") or ""),
                int(item.get("_origin_order", 0) or 0),
            ),
        )
        for item in kept_items:
            date = str(item.get("_origin_date", "") or "")
            cleaned = {k: v for k, v in item.items() if not k.startswith("_origin_")}
            grouped_items.setdefault(date, []).append(cleaned)

        deduped: list[dict] = []
        for summary in summaries:
            date = str(summary.get("date", "") or "")
            top_news = grouped_items.get(date) or []
            if top_news:
                deduped.append({**summary, "top_news": top_news})

        return deduped

    async def _score_flat_items(self, flat_items: list[dict]) -> set[int]:
        """Score a flat list of ``{index, headline, summary}`` dicts via the fast tier.

        Returns the set of ``index`` values scoring >= ``CATCHUP_QUALITY_THRESHOLD``.
        Fails open: on any error (or circuit open) every index is returned so callers
        keep all items rather than silently dropping content.
        """
        if not flat_items:
            return set()

        all_indices = {fi["index"] for fi in flat_items}
        input_for_scoring = json.dumps(flat_items, ensure_ascii=False)

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": _CATCHUP_SCORING_PROMPT},
                    {"role": "user", "content": input_for_scoring},
                ],
                tier="fast",
                label="catchup_scoring",
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2000,
            )

            result = response.choices[0].message.content
            parsed = json.loads(result)
            scores = parsed.get("scores", parsed.get("articles", [])) if isinstance(parsed, dict) else parsed
            if not isinstance(scores, list):
                scores = []

            high_indices = {
                item["index"]
                for item in scores
                if isinstance(item, dict) and item.get("score", 0) >= CATCHUP_QUALITY_THRESHOLD
            }
            logger.info(
                "Catchup quality filter: %s/%s items passed (threshold=%s)",
                len(high_indices),
                len(flat_items),
                CATCHUP_QUALITY_THRESHOLD,
            )
            return high_indices

        except CircuitOpenError as error:
            logger.warning("Circuit breaker open during catchup scoring, keeping all items: %s", error)
            return all_indices
        except Exception as error:
            logger.warning("Catchup scoring failed, keeping all items: %s", error)
            return all_indices

    async def select_important_catchup_indices(self, items: list[dict]) -> set[int]:
        """Strict importance filter for a flat list of catch-up items.

        ``items`` is an ordered list of ``{"headline": str, "summary": str}`` dicts;
        the returned set holds the positional indices (0-based) that pass the
        importance threshold. Fails open (returns all indices) on error.
        """
        flat_items = [
            {"index": i, "headline": it.get("headline", ""), "summary": (it.get("summary", "") or "")[:200]}
            for i, it in enumerate(items)
        ]
        return await self._score_flat_items(flat_items)

    async def _score_catchup_items(
        self, summaries: list[dict]
    ) -> list[dict]:
        """Pre-filter: score each top_news item across all summaries and drop low-importance ones.

        Returns a new list of summary dicts with only high-importance items retained.
        """
        summaries = self._dedupe_catchup_summaries(summaries)

        # Flatten all items with their origin date for scoring
        flat_items: list[dict] = []
        origins: list[tuple[str, int]] = []
        for s in summaries:
            date = s.get("date", "")
            for item_index, n in enumerate(s.get("top_news", [])):
                flat_items.append({
                    "index": len(flat_items),
                    "date": date,
                    "headline": n.get("headline", ""),
                    "summary": "; ".join(n.get("key_points", []))[:200],
                })
                origins.append((date, item_index))

        if not flat_items:
            return summaries

        high_indices = await self._score_flat_items(flat_items)

        # Build a set of (date, item_index) pairs that passed.
        passed_keys = {origins[i] for i in high_indices if i < len(origins)}

        # Rebuild summaries keeping only high-importance items
        filtered_summaries = []
        for s in summaries:
            date = s.get("date", "")
            kept = [
                n
                for item_index, n in enumerate(s.get("top_news", []))
                if (date, item_index) in passed_keys
            ]
            if kept:
                filtered_summaries.append({**s, "top_news": kept})

        return filtered_summaries if filtered_summaries else summaries

    async def generate_catchup_digest(
        self,
        summaries: list[dict],
        output_language: str | None = None,
    ) -> DailySummaryResponse | None:
        """
        Generate a condensed catch-up digest from multiple days of summaries.

        Args:
            summaries: List of DailySummaryResponse.model_dump() dicts.
            output_language: Optional board output language ("zh"|"en"|"auto").

        Returns:
            A DailySummaryResponse representing the condensed digest, or None.
        """
        if not settings.effective_llm_api_key:
            return None

        if not summaries:
            logger.info("No summaries provided for catch-up digest.")
            return None

        from app.core.llm_config import language_directive

        # Step 1: Pre-filter — keep only high-importance items
        filtered = await self._score_catchup_items(summaries)

        catchup_data = _build_catchup_data(filtered)
        prompt = get_prompt("catchup_digest") + language_directive(output_language)

        # Derive a representative date (latest date in the set)
        dates = sorted(s.get("date", "") for s in summaries)
        date_hint = dates[-1] if dates else ""

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Here are the summaries from the past {len(summaries)} days:\n\n{catchup_data}",
                    },
                ],
                tier="smart",
                label="catchup_digest",
                temperature=0.5,
                max_tokens=3000,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()

            parsed = json.loads(raw)
            # Ensure the date field reflects the digest, not a single day
            if date_hint:
                parsed["date"] = date_hint
            return DailySummaryResponse(**parsed)

        except Exception as error:
            logger.error("Error during catch-up digest generation: %s", error)
            return None
