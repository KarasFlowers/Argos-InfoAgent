import json
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(value: str) -> str:
    """Resolve a relative path against PROJECT_ROOT. Does NOT create directories."""
    path = Path(value)
    if path.is_absolute():
        resolved = path
    else:
        resolved = (PROJECT_ROOT / path).resolve()
    return str(resolved)


def _resolve_sqlite_uri(value: str) -> str:
    """Resolve relative paths inside a sqlite+aiosqlite URI. Does NOT create directories."""
    prefix = "sqlite+aiosqlite:///"
    if not value.startswith(prefix):
        return value

    db_path = value[len(prefix):]
    if not db_path:
        return value

    resolved = Path(db_path)
    if not resolved.is_absolute():
        resolved = (PROJECT_ROOT / resolved).resolve()

    return f"{prefix}{resolved.as_posix()}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    PROJECT_NAME: str = "Argos"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    
    # RSS feeds — must be freely accessible (no paywall) for RAG to scrape full text
    RSS_FEEDS: list[str] = [
        "https://news.ycombinator.com/rss",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://huggingface.co/blog/feed.xml",
        "https://openai.com/news/rss.xml",
        "https://www.theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
        "https://linux.do/top.rss",
        "https://sspai.com/feed",
        "https://www.solidot.org/index.rss",
        "https://36kr.com/feed",
    ]
    
    # LLM Configuration — generic provider settings
    LLM_MODEL: str = "deepseek-chat"
    LLM_API_KEY: str | None = None
    LLM_BASE_URL: str | None = None
    LLM_TIMEOUT: int = 180
    LLM_MAX_RETRIES: int = 1

    # Multi-model routing: "provider:model" format, e.g. "openai:gpt-4o-mini"
    # Leave empty to fall back to LLM_MODEL for all tiers.
    FAST_LLM: str = ""
    SMART_LLM: str = ""

    # Board wizard: when True, use the multi-stage grounded pipeline
    # (plan → discover+verify real sources → finalize → preview). When False,
    # fall back to the legacy single-call wizard_suggest_board path.
    WIZARD_PIPELINE_ENABLED: bool = True

    # RSSHub — generates standard RSS for sources without native feeds (公众号/
    # 知乎/B站/即刻 ...). Used by the wizard's discovery stage. The base URL is
    # the public instance by default; point it at a self-hosted instance for
    # reliability. Set RSSHUB_ENABLED=false to skip RSSHub discovery entirely.
    RSSHUB_ENABLED: bool = True
    RSSHUB_BASE_URL: str = "https://rsshub.app"

    # Legacy DeepSeek-specific keys (used as fallback when LLM_* is unset)
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"

    @property
    def effective_llm_api_key(self) -> str | None:
        return self.LLM_API_KEY or self.DEEPSEEK_API_KEY

    @property
    def effective_llm_base_url(self) -> str:
        return self.LLM_BASE_URL or self.DEEPSEEK_BASE_URL
    
    # Database
    SQLALCHEMY_DATABASE_URI: str = "sqlite+aiosqlite:///./data/sqlite/argos.db"
    
    # Retention Policy
    HISTORY_DAYS_TO_KEEP: int = 7
    
    # Email Push Settings
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 465
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None
    EMAIL_SUBSCRIBERS: list[str] = []
    DAILY_PUSH_TIME: str = "08:00"  # Format HH:MM

    # Webhook Notification
    WEBHOOK_URL: str | None = None            # Generic webhook (POST JSON)
    WEBHOOK_SECRET: str | None = None         # Optional HMAC signing key

    # Bark Push (iOS)
    BARK_URL: str | None = None               # e.g. https://api.day.app/YOUR_KEY
    BARK_GROUP: str = "Argos"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    # Notification channels to enable (comma-separated: email,webhook,bark,telegram)
    NOTIFY_CHANNELS: str = "email"
    
    # RAG Feature Toggle (set to false to skip heavy model downloads)
    RAG_ENABLED: bool = True

    # RAG Vector Store
    CHROMA_DB_DIR: str = "./data/chroma"

    # Background Ingestion Pipeline
    RAG_BACKGROUND_INGEST_ENABLED: bool = True
    RAG_BACKGROUND_INGEST_WORKERS: int = 2

    # HyDE (Hypothetical Document Embedding) query rewriting
    RAG_HYDE_ENABLED: bool = True

    # --- Web Search (Tavily) ---
    TAVILY_API_KEY: str | None = None             # Optional: enables web search in Deep Research

    # --- Weekly report theme enrichment ---
    # When enabled (and TAVILY_API_KEY is set), the weekly report runs an extra
    # stage that web-searches the top themes and injects structured background
    # into the editorial. Off by default — daily summary flow is unaffected.
    WEEKLY_ENRICH_ENABLED: bool = False
    WEEKLY_ENRICH_MAX_THEMES: int = 3             # How many top themes to enrich per weekly run

    # --- Multi-source scraper defaults ---
    GITHUB_TOKEN: str | None = None               # Optional: raises GitHub API rate limit
    HN_FETCH_TOP_STORIES: int = 30                # Hacker News: how many top stories to fetch
    HN_MIN_SCORE: int = 100                       # Hacker News: minimum score filter
    REDDIT_FETCH_COMMENTS: int = 5                # Reddit: top comments per post

    # Redis Cache
    REDIS_URL: str = "redis://localhost:6379"

    # API Key Authentication
    # When set, all /api/v1/* endpoints require X-API-Key header.
    # Leave empty (default) to disable auth — convenient for local dev.
    API_KEY: str | None = None

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    CORS_ALLOW_CREDENTIALS: bool = True

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def resolve_database_uri(cls, value: str) -> str:
        return _resolve_sqlite_uri(value)

    @field_validator("CHROMA_DB_DIR", mode="before")
    @classmethod
    def resolve_chroma_dir(cls, value: str) -> str:
        return _resolve_path(value)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                return json.loads(raw)
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value

settings = Settings()
