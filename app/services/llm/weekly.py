"""Weekly consolidation / recap generation — multi-stage pipeline."""
import asyncio
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


async def _enrich_themes(themes: list[dict], llm) -> None:
    """Enrich the top recurring themes with web-grounded background, in-place.

    For each of the top ``WEEKLY_ENRICH_MAX_THEMES`` themes: web-search the
    theme (Tavily), then ask the fast LLM for structured background. The result
    is attached as ``theme["enrichment"]`` = {whats_new, why_it_matters,
    background, sources}. Gated behind ``WEEKLY_ENRICH_ENABLED`` + a configured
    ``TAVILY_API_KEY``; any failure degrades silently (theme left unenriched).

    Aggregation-level adaptation of Horizon's per-item ContentEnricher.
    """
    if not settings.WEEKLY_ENRICH_ENABLED or not settings.TAVILY_API_KEY:
        return
    if not themes:
        return

    from app.services.research_service import tavily_search

    # Themes come from raw LLM output — operate only on well-formed dict entries.
    targets = [t for t in themes[: max(1, settings.WEEKLY_ENRICH_MAX_THEMES)] if isinstance(t, dict)]
    if not targets:
        return
    enrich_prompt = get_prompt("weekly_theme_enrich", required=False)
    if not enrich_prompt:
        logger.warning("weekly_theme_enrich prompt missing — skipping enrichment")
        return

    async def _one(theme: dict) -> None:
        label = (theme.get("label") or "").strip()
        arc = (theme.get("arc_summary") or "").strip()
        query = f"{label} {arc}".strip()
        if not query:
            return
        try:
            results = await tavily_search(query, max_results=3)
        except Exception as exc:
            logger.debug("Theme enrichment search failed for '%s': %s", label, exc)
            return
        if not results:
            return

        available = {r["url"]: r["title"] for r in results if r.get("url")}
        web_context = "\n".join(
            f"- [{r['title']}]({r['url']}): {r['content']}" for r in results
        )
        user = (
            f"Theme: {label}\nArc summary: {arc}\n\n"
            f"Web search results:\n{web_context}"
        )
        try:
            response = await llm.chat(
                messages=[
                    {"role": "system", "content": enrich_prompt},
                    {"role": "user", "content": user},
                ],
                tier="fast",
                label="weekly:enrich",
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=700,
            )
            data = json.loads(response.choices[0].message.content or "{}")
        except Exception as exc:
            logger.debug("Theme enrichment LLM failed for '%s': %s", label, exc)
            return

        # Keep only citations that actually came from our search results.
        sources = [u for u in (data.get("sources") or []) if u in available]
        theme["enrichment"] = {
            "whats_new": (data.get("whats_new") or "").strip(),
            "why_it_matters": (data.get("why_it_matters") or "").strip(),
            "background": (data.get("background") or "").strip(),
            "sources": sources,
        }

    await asyncio.gather(*(_one(t) for t in targets), return_exceptions=True)


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

        # Stage 2.5: Optional theme enrichment (fast LLM + web search).
        # Gated behind WEEKLY_ENRICH_ENABLED + TAVILY_API_KEY; degrades silently.
        try:
            await _enrich_themes(result["themes"], self.llm)
        except Exception as exc:
            logger.debug("Weekly theme enrichment skipped: %s", exc)

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
                    enrich = t.get("enrichment")
                    if enrich:
                        if enrich.get("whats_new"):
                            themes_context += f"  - What's new: {enrich['whats_new']}\n"
                        if enrich.get("why_it_matters"):
                            themes_context += f"  - Why it matters: {enrich['why_it_matters']}\n"
                        if enrich.get("background"):
                            themes_context += f"  - Background: {enrich['background']}\n"

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
