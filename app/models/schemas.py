from pydantic import BaseModel, Field, model_validator


class ContentItem(BaseModel):
    """Unified content item from any source (RSS, HN, Reddit, GitHub, etc.)."""

    id: str  # {source}:{subtype}:{native_id}
    source_type: str  # "rss" | "hackernews" | "reddit" | "github"
    title: str
    url: str
    content: str | None = None  # body text + appended comments
    author: str | None = None
    published_at: str = ""  # ISO-8601 (empty when unavailable)
    source_name: str = ""  # display label (e.g. "r/LocalLLaMA")
    metadata: dict = Field(default_factory=dict)  # score, subreddit, repo, etc.

    @model_validator(mode="before")
    @classmethod
    def _normalize_published_at(cls, values: dict) -> dict:
        if not values.get("published_at"):
            values["published_at"] = ""
        return values


class Article(BaseModel):
    title: str
    url: str
    source: str
    content_preview: str | None = None


class RSSItem(BaseModel):
    title: str
    link: str
    published: str
    summary: str
    source: str


class RSSResponse(BaseModel):
    source_url: str
    items: list[RSSItem]


class SummaryItem(BaseModel):
    headline: str
    category: str
    key_points: list[str]
    tags: list[str] = Field(default_factory=list)
    topic_path: str = ""
    original_link: str
    source: str
    feedback_sentiment: int | None = None
    persona_score: float | None = None
    is_read: bool = False
    cluster_id: int | None = None
    is_catchup: bool = False
    original_date: str | None = None  # YYYY-MM-DD of the original summary when is_catchup=True

    @model_validator(mode="before")
    @classmethod
    def _normalize_llm_field_names(cls, values: dict) -> dict:
        """Normalise common LLM output deviations.

        Handles:
        - 'title' returned instead of 'headline'
        - 'key_points' as a single string instead of list
        - missing 'category' (defaults to 'general')
        - missing 'tags' (defaults to [])
        - 'event_type' / 'eventType' alias normalisation (future-proofing)
        """
        if not isinstance(values, dict):
            return values
        # headline ← title
        if "headline" not in values and "title" in values:
            values["headline"] = values.pop("title")
        # key_points: string → split into list
        kp = values.get("key_points")
        if isinstance(kp, str):
            values["key_points"] = [s.strip() for s in kp.split("\n") if s.strip()] or [kp]
        elif kp is None:
            values["key_points"] = []
        # category fallback
        if not values.get("category"):
            values["category"] = "general"
        # tags fallback
        if "tags" not in values or values["tags"] is None:
            values["tags"] = []
        return values


class SummaryArchiveItem(BaseModel):
    date: str
    overview_preview: str
    news_count: int
    source_stats: dict[str, int] = Field(default_factory=dict)
    top_categories: list[str] = Field(default_factory=list)


class HistoryStatItem(BaseModel):
    name: str
    count: int


class WeeklyRecapResponse(BaseModel):
    window_start: str
    window_end: str
    days_covered: int
    total_news: int
    top_categories: list[HistoryStatItem] = Field(default_factory=list)
    top_sources: list[HistoryStatItem] = Field(default_factory=list)
    recap_text: str
    weekly_insight: str | None = None
    latest_date: str


class SummaryHistoryResponse(BaseModel):
    archive_items: list[SummaryArchiveItem] = Field(default_factory=list)
    weekly_recap: WeeklyRecapResponse | None = None


class DailySummaryResponse(BaseModel):
    date: str
    overview: str
    perspective: str = "overview"
    top_news: list[SummaryItem]
    events: list[dict] = Field(default_factory=list)
    source_stats: dict[str, int] = Field(default_factory=dict)
    # Recommendation statistics for transparency
    recommendation_report: dict = Field(default_factory=dict)
    # Auto-catchup items from recent unviewed days
    catchup_news: list[SummaryItem] = Field(default_factory=list)
    source_analysis: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalize_top_news_items(cls, values: dict) -> dict:
        """Normalise top_news items and required fields from LLM output.

        Handles:
        - 'title' → 'headline' in each top_news item
        - key_points as string → list
        - missing category → 'general'
        - missing tags → []
        - missing date → today
        - missing/empty overview → placeholder
        """
        if not isinstance(values, dict):
            return values

        # Date fallback
        if not values.get("date"):
            from datetime import datetime

            values["date"] = datetime.now().strftime("%Y-%m-%d")

        # Overview fallback
        if not values.get("overview"):
            values["overview"] = ""

        top_news = values.get("top_news", [])
        if isinstance(top_news, list):
            for item in top_news:
                if not isinstance(item, dict):
                    continue
                # headline ← title
                if "headline" not in item and "title" in item:
                    item["headline"] = item.pop("title")
                # key_points: string → list
                kp = item.get("key_points")
                if isinstance(kp, str):
                    item["key_points"] = [s.strip() for s in kp.split("\n") if s.strip()] or [kp]
                elif kp is None:
                    item["key_points"] = []
                # category fallback
                if not item.get("category"):
                    item["category"] = "general"
                # tags fallback
                if "tags" not in item or item["tags"] is None:
                    item["tags"] = []
        return values
