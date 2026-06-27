"""LLM article quality scoring."""

import json
import logging

from app.prompts import get_prompt
from app.services.llm.client import CircuitOpenError

logger = logging.getLogger(__name__)


class ScoringMixin:
    """Mixin providing ``_score_articles`` for LLMService."""

    async def _score_articles(self, articles: list[dict], interest_context: str = "") -> tuple[list[dict], dict]:
        """
        Pre-filter: ask the LLM to score each article's value (1-10).
        Returns (high_quality_articles, stats_metadata).

        If ``interest_context`` is provided, it's appended to the scoring prompt
        so user interests influence the scores.
        """
        quality_threshold = 5

        scoring_prompt = get_prompt("quality_scoring", interest_context=interest_context)

        input_for_scoring = json.dumps(
            [{"index": i, "title": a["title"], "summary": a["summary"][:150]} for i, a in enumerate(articles)],
            ensure_ascii=False,
        )

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": scoring_prompt},
                    {"role": "user", "content": input_for_scoring},
                ],
                tier="fast",
                label="scoring",
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=2000,
            )

            result = response.choices[0].message.content
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                scores = parsed.get("scores", parsed.get("articles", []))
            elif isinstance(parsed, list):
                scores = parsed
            else:
                scores = []

            high_quality_indices = {
                item["index"] for item in scores if isinstance(item, dict) and item.get("score", 0) >= quality_threshold
            }

            filtered = [article for i, article in enumerate(articles) if i in high_quality_indices]
            excluded = [article for i, article in enumerate(articles) if i not in high_quality_indices]

            logger.info(
                "Quality filter: %s/%s articles passed (threshold=%s)",
                len(filtered),
                len(articles),
                quality_threshold,
            )

            # Build report metadata
            report = {
                "total_fetched": len(articles),
                "passed_count": len(filtered),
                "excluded_count": len(excluded),
                "excluded_samples": [a["title"] for a in excluded[:5]],
            }

            if len(filtered) < 8 and len(articles) >= 8:
                sorted_scores = sorted(scores, key=lambda item: item.get("score", 0), reverse=True)
                top_indices = {item["index"] for item in sorted_scores[: max(10, len(filtered))]}
                filtered = [article for i, article in enumerate(articles) if i in top_indices]
                logger.info("Fallback: kept top %s articles by score (needed >=8)", len(filtered))

            return filtered if filtered else articles[:10], report
        except CircuitOpenError as error:
            logger.warning("Circuit breaker open during scoring, skipping LLM filter: %s", error)
            return articles, {"total_fetched": len(articles), "scoring_skipped": True, "reason": "circuit_open"}
        except Exception as error:
            logger.warning("Article scoring failed, using all articles: %s", error)
            return articles, {"total_fetched": len(articles), "error": str(error)}
