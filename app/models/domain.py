from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import JSON, Column, Integer, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def mask_secret(value: str | None, *, visible_prefix: int = 4, visible_suffix: int = 4) -> str:
    """Return a display-safe representation of a secret value."""
    if not value:
        return ""
    if len(value) <= visible_prefix + visible_suffix:
        return "***"
    return f"{value[:visible_prefix]}...{value[-visible_suffix:]}"


class Board(SQLModel, table=True):
    """
    A "board" (custom section) — e.g. 科技快讯, 冷知识, 英语学习.
    Each board has its own system prompt, data sources, and optionally
    its own preferences / feedback.
    """

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True)  # e.g. "tech", "trivia", "english"
    name: str  # display name e.g. "科技快讯"
    icon: str = Field(default="")  # emoji or lucide key
    description: str = Field(default="")
    system_prompt: str = Field(default="")  # editor prompt override
    source_type: str = Field(default="rss")  # "rss" | "pure_llm" | "hackernews" | "reddit" | "github" | "multi"
    source_config: dict | None = Field(default_factory=dict, sa_column=Column(JSON))
    display_order: int = Field(default=0, index=True)
    is_active: bool = Field(default=True)
    is_default: bool = Field(default=False)  # exactly one default per install
    schedule: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # cron expr e.g. "08:00" or "*/6h"; empty = use global
    notify_channels: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # comma-separated; currently only "email" is implemented
    perspectives: dict | None = Field(
        default=None, sa_column=Column(JSON)
    )  # e.g. {"active": ["technical", "business"]}; None = single-view mode
    prompt_key: str = Field(
        default="daily_briefing", sa_column=Column(Text, nullable=False, server_default="daily_briefing")
    )  # prompt template key
    output_language: str = Field(
        default="auto", sa_column=Column(Text, nullable=False, server_default="auto")
    )  # "auto" | "zh" | "en" — forces LLM output language
    catchup_days: int = Field(
        default=7, sa_column=Column(Integer, nullable=False, server_default="7")
    )  # auto-catchup window in days; 0 = off
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NewsItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    headline: str = Field(index=True)
    category: str = Field(default="Uncategorized", index=True)
    # Stored as native JSON column (migrated from JSON-string in refactor)
    key_points: list = Field(default_factory=list, sa_column=Column(JSON))
    tags: list = Field(default_factory=list, sa_column=Column(JSON))
    topic_path: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))  # e.g. "AI/LLM/微调"
    original_link: str
    source: str
    cluster_id: int | None = Field(default=None, foreign_key="contentcluster.id", index=True, ondelete="SET NULL")

    # Foreign key to DailySummary with Cascade Delete
    summary_id: int = Field(foreign_key="dailysummary.id", ondelete="CASCADE")
    summary: "DailySummary" = Relationship(back_populates="top_news")


class DailySummary(SQLModel, table=True):
    # One summary per (board, date, perspective).
    __table_args__ = (
        UniqueConstraint("board_id", "date", "perspective", name="ux_dailysummary_board_date_perspective"),
    )

    id: int | None = Field(default=None, primary_key=True)
    # Note: SQLite doesn't natively support Date, so we store it as a string YYYY-MM-DD
    date: str = Field(index=True)
    board_id: int | None = Field(default=None, foreign_key="board.id", index=True, ondelete="CASCADE")
    perspective: str = Field(
        default="overview", sa_column=Column(Text, nullable=False, server_default="overview")
    )  # "overview" | "technical" | "business" | custom
    overview: str
    stats_json: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # cascade="all, delete-orphan" ensures ORM-level deletion removes related NewsItems
    # instead of trying to NULL their summary_id (which violates NOT NULL).
    top_news: list[NewsItem] = Relationship(
        back_populates="summary",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class UserFeedback(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    article_url: str = Field(index=True, unique=True)
    # sentiment: 1 for Like, -1 for Dislike
    sentiment: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatMessage(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    article_url: str = Field(index=True)
    role: str  # "user" or "ai"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArticleOverview(SQLModel, table=True):
    """Persisted article overview text — avoids re-generating on every panel open."""

    id: int | None = Field(default=None, primary_key=True)
    article_url: str = Field(index=True, unique=True)
    overview_text: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserPersona(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    # The actual instruction or extracted keyword
    content: str
    # "instruction" (manual) vs "extracted" (from vector) vs explicit categories
    category: str = Field(default="instruction", index=True)
    # null = global (applies to all boards). Non-null = scoped to a single board.
    board_id: int | None = Field(default=None, foreign_key="board.id", index=True, ondelete="CASCADE")
    is_active: bool = Field(default=True)
    weight: float = Field(default=1.0)  # decay weight for auto-extracted interests
    source: str = Field(
        default="manual", sa_column=Column(Text, nullable=False, server_default="manual")
    )  # "manual" | "auto"
    last_refreshed: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserMemory(SQLModel, table=True):
    """Persistent factual memory about the user for prompt enrichment.

    Distinct from UserPersona: Persona = interest/keyword for filtering;
    Memory = factual recall (preferences, context, history) for prompt injection.
    """

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)  # e.g. "preferred_language", "last_research_topic"
    value: str = Field(sa_column=Column(Text, nullable=False))
    category: str = Field(default="fact", index=True)  # "fact" | "preference" | "topic"
    source: str = Field(
        default="auto", sa_column=Column(Text, nullable=False, server_default="auto")
    )  # "manual" | "auto" | "chat_extract"
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Runtime Configuration Models (P0 1.2 — database-backed configuration)
# ---------------------------------------------------------------------------


class Source(SQLModel, table=True):
    """An RSS or API data source, replacing hardcoded RSS_FEEDS in config.py."""

    id: int | None = Field(default=None, primary_key=True)
    url: str = Field(index=True)  # RSS feed URL or API endpoint
    name: str = Field(default="")  # display name (auto-detected or manual)
    site_url: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))  # homepage
    source_type: str = Field(default="rss", index=True)  # "rss" | "hackernews" | "reddit" | "github"
    credibility_override: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # "" | official | established | specialist | community | aggregator | mirror | ai_generated | risky
    enabled: bool = Field(default=True)
    board_id: int | None = Field(
        default=None, foreign_key="board.id", ondelete="CASCADE", index=True
    )  # null = global (available to all boards)
    health_status: str = Field(
        default="healthy", sa_column=Column(Text, nullable=False, server_default="healthy")
    )  # "healthy" | "degraded" | "unhealthy"
    last_fetched_at: datetime | None = Field(default=None)
    last_error: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ModelApiConfig(SQLModel, table=True):
    """LLM provider configuration, replacing environment variable multi-tier setup."""

    model_config = ConfigDict(protected_namespaces=())

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)  # e.g. "default", "fast-groq", "smart-openai"
    base_url: str  # e.g. "https://api.openai.com/v1"
    api_key: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # encrypted at rest in future
    model_name: str  # e.g. "gpt-4o-mini"
    concurrency: int = Field(default=5)  # max parallel requests
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)

    def safe_dict(self) -> dict:
        """Serialize for admin/UI responses without exposing provider secrets."""
        data = self.model_dump()
        data["api_key"] = mask_secret(self.api_key)
        return data


class TaskRun(SQLModel, table=True):
    """Background task execution record for observability."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # "daily_push" | "cleanup" | "auto_extract" | "summary_generation"
    trigger_type: str = Field(
        default="scheduled", sa_column=Column(Text, nullable=False, server_default="scheduled")
    )  # "scheduled" | "manual" | "api"
    status: str = Field(default="queued", index=True)  # "queued" | "running" | "done" | "failed"
    progress_label: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # e.g. "scoring articles"
    progress_current: int = Field(default=0)
    progress_total: int = Field(default=0)
    stage_timings: dict | None = Field(default=None, sa_column=Column(JSON))  # {"scoring": 2.3, "summary": 5.1}
    ai_call_breakdown: dict | None = Field(
        default=None, sa_column=Column(JSON)
    )  # {"scoring": {"tokens": 500}, "summary": {"tokens": 2000}}
    error_summary: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    board_id: int | None = Field(default=None, foreign_key="board.id", ondelete="SET NULL", index=True)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Filtering Models (P1 2.1 — rule-based content quality filtering)
# ---------------------------------------------------------------------------


class ContentCluster(SQLModel, table=True):
    """A group of related news items covering the same event/topic."""

    id: int | None = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True, unique=True)  # hash-based dedup key
    title: str  # representative cluster title
    summary: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # AI-generated cluster summary
    item_count: int = Field(default=1)
    item_ids: list | None = Field(default_factory=list, sa_column=Column(JSON))  # list of NewsItem IDs in this cluster
    first_seen_at: datetime | None = Field(default=None)
    last_updated_at: datetime | None = Field(default=None)
    board_id: int | None = Field(default=None, foreign_key="board.id", ondelete="CASCADE", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BlacklistKeyword(SQLModel, table=True):
    """A keyword or pattern that causes content to be automatically filtered."""

    id: int | None = Field(default=None, primary_key=True)
    pattern: str = Field(index=True)  # keyword or regex pattern
    match_field: str = Field(
        default="title", sa_column=Column(Text, nullable=False, server_default="title")
    )  # "title" | "url" | "content"
    is_regex: bool = Field(default=False)  # if True, pattern is treated as regex
    reason: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # e.g. "marketing", "low_quality"
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FilteredItem(SQLModel, table=True):
    """An item caught by the rule filter, kept for admin review and potential restore."""

    id: int | None = Field(default=None, primary_key=True)
    title: str
    url: str = Field(index=True)
    source: str = Field(default="")
    filter_reason: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )  # which rule matched
    filter_rule_id: int | None = Field(default=None, foreign_key="blacklistkeyword.id", ondelete="SET NULL")
    status: str = Field(default="filtered", index=True)  # "filtered" | "restored" | "confirmed"
    board_id: int | None = Field(default=None, foreign_key="board.id", ondelete="CASCADE", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reviewed_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Daily Report Refinement (P2 3.1)
# ---------------------------------------------------------------------------


class DailyReportRefinementSession(SQLModel, table=True):
    """A user-driven refinement session on an existing daily report."""

    id: int | None = Field(default=None, primary_key=True)
    board_id: int | None = Field(default=None, foreign_key="board.id", ondelete="CASCADE", index=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    instruction: str = Field(sa_column=Column(Text, nullable=False))  # user refinement instruction
    original_summary_json: dict | None = Field(default=None, sa_column=Column(JSON))
    refined_summary_json: dict | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True)  # "pending" | "processing" | "done" | "failed"
    error_message: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Catch-up / Digest Viewed Tracking
# ---------------------------------------------------------------------------


class SummaryViewLog(SQLModel, table=True):
    """Tracks which summary dates the user has viewed (global, not per-board)."""

    id: int | None = Field(default=None, primary_key=True)
    date: str = Field(index=True, unique=True)  # YYYY-MM-DD
    viewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArticleReadState(SQLModel, table=True):
    """Article-level read state, scoped per board for single-user Argos."""

    __table_args__ = (UniqueConstraint("article_url", "board_id", name="ux_articlereadstate_url_board"),)

    id: int | None = Field(default=None, primary_key=True)
    article_url: str = Field(index=True)
    board_id: int | None = Field(default=None, foreign_key="board.id", index=True, ondelete="CASCADE")
    is_read: bool = Field(default=False, index=True)
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    read_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = Field(default=None)


# ---------------------------------------------------------------------------
# Saved Articles (Favorites / Read Later)
# ---------------------------------------------------------------------------


class SavedArticle(SQLModel, table=True):
    """A user-saved article. Two independent statuses are supported so the same
    article can be both favorited and queued for later reading."""

    __table_args__ = (UniqueConstraint("article_url", "status", name="ux_savedarticle_url_status"),)

    id: int | None = Field(default=None, primary_key=True)
    article_url: str = Field(index=True)
    status: str = Field(default="favorite", index=True)  # "favorite" | "read_later"
    # Display snapshot (so the saved list renders without joining DailySummary)
    headline: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    source: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    category: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    board_slug: str = Field(default="", sa_column=Column(Text, nullable=False, server_default=""))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
