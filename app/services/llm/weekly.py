"""Weekly consolidation / recap generation — multi-stage pipeline."""
import json
import logging
from typing import Any

from app.core.config import settings
from app.prompts import get_prompt

logger = logging.getLogger(__name__)


def _build_week_data(summaries: list[dict]) -> str:
    """Build a dense text representation of a week's summaries."""
    daily_inputs = []
    for s in summaries:
        date = s.get("date", "Unknown Date")
        overview = s.get("overview", "")
        headlines = [n.get("headline", "") for n in s.get("top_news", [])]
        daily_inputs.append(
            f"### {date}\nOverview: {overview}\nHeadlines: {', '.join(headlines)}"
        )
    return "\n\n".join(daily_inputs)


class WeeklyMixin:
    """Mixin providing weekly report generation for LLMService."""

    async def generate_weekly_consolidation(
        self,
        summaries: list[dict],
        output_language: str | None = None,
    ) -> str | None:
        """
        Backward-compatible: single-stage magazine-style recap.
        Delegates to the editorial stage of the multi-stage pipeline.
        """
        if not settings.effective_llm_api_key:
            return None

        from app.core.llm_config import language_directive
        week_data = _build_week_data(summaries)
        editor_prompt = get_prompt("weekly_editor") + language_directive(output_language)

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": editor_prompt},
                    {
                        "role": "user",
                        "content": f"Here is the data from the past 7 days:\n\n{week_data}",
                    },
                ],
                tier="smart",
                label="weekly",
                temperature=0.7,
                max_tokens=2500,
            )
            return response.choices[0].message.content
        except Exception as error:
            logger.error("Error during weekly consolidation: %s", error)
            return None

    async def generate_structured_weekly_report(
        self,
        summaries: list[dict],
        output_language: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Multi-stage weekly report pipeline:

        1. **Topic extraction** (fast) — identify recurring themes.
        2. **Statistics** (fast) — structured stats from raw data.
        3. **Editorial** (smart) — long-form narrative with theme context.

        Returns a dict with ``themes``, ``stats``, ``editorial``.
        """
        if not settings.effective_llm_api_key:
            return None

        from app.core.llm_config import language_directive
        lang_directive = language_directive(output_language)
        week_data = _build_week_data(summaries)
        result: dict[str, Any] = {"themes": [], "stats": {}, "editorial": ""}

        # Stage 1: Topic / theme extraction (fast LLM)
        try:
            topic_prompt = get_prompt("weekly_topic_extract")
            topic_response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": topic_prompt},
                    {"role": "user", "content": week_data},
                ],
                tier="fast",
                label="weekly:topics",
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=1500,
            )
            topic_data = json.loads(topic_response.choices[0].message.content)
            result["themes"] = topic_data.get("themes", [])
        except Exception as exc:
            logger.warning("Weekly topic extraction failed: %s", exc)

        # Stage 2: Statistics summary (fast LLM)
        try:
            stats_prompt = get_prompt("weekly_stats")
            stats_input = (
                f"Themes:\n{json.dumps(result['themes'], ensure_ascii=False)}\n\n"
                f"Daily data:\n{week_data}"
            )
            stats_response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": stats_prompt},
                    {"role": "user", "content": stats_input},
                ],
                tier="fast",
                label="weekly:stats",
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=1000,
            )
            result["stats"] = json.loads(stats_response.choices[0].message.content)
        except Exception as exc:
            logger.warning("Weekly stats failed: %s", exc)

        # Stage 3: Editorial (smart LLM) — pass theme context for richer output
        try:
            editor_prompt = get_prompt("weekly_editor") + lang_directive
            themes_context = ""
            if result["themes"]:
                themes_context = "\n\nKey themes identified this week:\n"
                for t in result["themes"]:
                    themes_context += (
                        f"- **{t.get('label', '')}**: {t.get('arc_summary', '')}\n"
                    )

            editorial_response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": editor_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Here is the data from the past 7 days:\n\n{week_data}"
                            f"{themes_context}"
                        ),
                    },
                ],
                tier="smart",
                label="weekly:editorial",
                temperature=0.7,
                max_tokens=3000,
            )
            result["editorial"] = editorial_response.choices[0].message.content or ""
        except Exception as exc:
            logger.error("Weekly editorial failed: %s", exc)

        return result if result["editorial"] else None
