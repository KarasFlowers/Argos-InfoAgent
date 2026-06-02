"""Catch-up digest generation — condenses multiple days of summaries into one briefing."""
import json
import logging

from app.core.config import settings
from app.models.schemas import DailySummaryResponse
from app.prompts import get_prompt
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

    async def _score_catchup_items(
        self, summaries: list[dict]
    ) -> list[dict]:
        """Pre-filter: score each top_news item across all summaries and drop low-importance ones.

        Returns a new list of summary dicts with only high-importance items retained.
        """
        # Flatten all items with their origin date for scoring
        flat_items: list[dict] = []
        for s in summaries:
            date = s.get("date", "")
            for n in s.get("top_news", []):
                flat_items.append({
                    "index": len(flat_items),
                    "date": date,
                    "headline": n.get("headline", ""),
                    "summary": "; ".join(n.get("key_points", []))[:200],
                })

        if not flat_items:
            return summaries

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

            # Build a set of (date, headline) pairs that passed
            passed_keys: set[tuple[str, str]] = set()
            for fi in flat_items:
                if fi["index"] in high_indices:
                    passed_keys.add((fi["date"], fi["headline"]))

            # Rebuild summaries keeping only high-importance items
            filtered_summaries = []
            for s in summaries:
                date = s.get("date", "")
                kept = [
                    n for n in s.get("top_news", [])
                    if (date, n.get("headline", "")) in passed_keys
                ]
                if kept:
                    filtered_summaries.append({**s, "top_news": kept})

            logger.info(
                "Catchup quality filter: %s/%s items passed (threshold=%s)",
                len(passed_keys),
                len(flat_items),
                CATCHUP_QUALITY_THRESHOLD,
            )
            return filtered_summaries if filtered_summaries else summaries

        except CircuitOpenError as error:
            logger.warning("Circuit breaker open during catchup scoring, skipping filter: %s", error)
            return summaries
        except Exception as error:
            logger.warning("Catchup scoring failed, using all items: %s", error)
            return summaries

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
