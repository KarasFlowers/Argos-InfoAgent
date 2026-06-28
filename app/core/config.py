import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

    db_path = value[len(prefix) :]
    if not db_path:
        return value

    resolved = Path(db_path)
    if not resolved.is_absolute():
        resolved = (PROJECT_ROOT / resolved).resolve()

    return f"{prefix}{resolved.as_posix()}"


def _validate_http_base_url(value: str, *, field_name: str) -> str:
    raw = (value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be an absolute http(s) URL")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"{field_name} must not include params, query, or fragment")
    return raw


def _validate_cors_origin(value: str) -> str:
    raw = value.strip().rstrip("/")
    if raw == "*":
        return raw
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"CORS origin must be an absolute http(s) origin: {value!r}")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError(f"CORS origin must not include path, params, query, or fragment: {value!r}")
    return raw


def effective_cors_allow_credentials(origins: list[str], requested: bool) -> bool:
    """Return the safe effective CORS credentials flag for Starlette."""
    return requested and "*" not in origins


def _validate_hhmm_time(value: str, *, field_name: str) -> str:
    raw = (value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2 or not all(part.isdigit() and len(part) == 2 for part in parts):
        raise ValueError(f"{field_name} must use HH:MM format")
    hour, minute = (int(part) for part in parts)
    if hour > 23 or minute > 59:
        raise ValueError(f"{field_name} must be a valid 24-hour time")
    return raw


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    PROJECT_NAME: str = "Argos"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

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
    def effective_llm_base_url(self) -> str | None:
        """Return the configured base URL.

        When the user has set LLM_API_KEY (the generic config), only
        LLM_BASE_URL is honoured — we do NOT fall back to DeepSeek's URL,
        because that would silently send a third-party API key to DeepSeek.

        When LLM_API_KEY is unset, the legacy DEEPSEEK_* variables are used
        as a consistent fallback for both key and URL.
        """
        if self.LLM_API_KEY:
            return self.LLM_BASE_URL or None
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

    # Notification channels. Empty by default to avoid external side effects;
    # set to "email" (or comma-separated channels) to enable scheduled pushes.
    NOTIFY_CHANNELS: str = ""

    # RAG Feature Toggle (set to true for article-level RAG and local model downloads)
    RAG_ENABLED: bool = False

    # RAG Vector Store
    CHROMA_DB_DIR: str = "./data/chroma"

    # Background Ingestion Pipeline
    RAG_BACKGROUND_INGEST_ENABLED: bool = True
    RAG_BACKGROUND_INGEST_WORKERS: int = 2

    # Silent mode: run background collection when the PC is idle, then export
    # generated summaries as Markdown files.
    SILENT_MODE_ENABLED: bool = False
    SILENT_MODE_OUTPUT_DIR: str = "./data/silent_reports"
    SILENT_MODE_IDLE_SECONDS: int = 900
    SILENT_MODE_INTERVAL_MINUTES: int = 30
    SILENT_MODE_LOOKBACK_HOURS: int = 24
    SILENT_MODE_BOARD_SLUGS: list[str] = []
    SILENT_MODE_OVERWRITE_TODAY: bool = False

    # HyDE (Hypothetical Document Embedding) query rewriting
    RAG_HYDE_ENABLED: bool = True

    # --- Web Search (Tavily) ---
    TAVILY_API_KEY: str | None = None  # Optional: enables web search in Deep Research

    # --- Weekly report theme enrichment ---
    # When enabled (and TAVILY_API_KEY is set), the weekly report runs an extra
    # stage that web-searches the top themes and injects structured background
    # into the editorial. Off by default — daily summary flow is unaffected.
    WEEKLY_ENRICH_ENABLED: bool = False
    WEEKLY_ENRICH_MAX_THEMES: int = 3  # How many top themes to enrich per weekly run

    # --- Multi-source scraper defaults ---
    GITHUB_TOKEN: str | None = None  # Optional: raises GitHub API rate limit
    HN_FETCH_TOP_STORIES: int = 30  # Hacker News: how many top stories to fetch
    HN_MIN_SCORE: int = 100  # Hacker News: minimum score filter
    REDDIT_FETCH_COMMENTS: int = 5  # Reddit: top comments per post

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

    @field_validator("SILENT_MODE_OUTPUT_DIR", mode="before")
    @classmethod
    def resolve_silent_mode_output_dir(cls, value: str) -> str:
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

    @field_validator("PUBLIC_BASE_URL", "RSSHUB_BASE_URL")
    @classmethod
    def validate_public_http_base_url(cls, value: str, info) -> str:
        return _validate_http_base_url(value, field_name=info.field_name)

    @field_validator("CORS_ORIGINS")
    @classmethod
    def validate_cors_origins(cls, value: list[str]) -> list[str]:
        return [_validate_cors_origin(origin) for origin in value]

    @field_validator("DAILY_PUSH_TIME")
    @classmethod
    def validate_daily_push_time(cls, value: str) -> str:
        return _validate_hhmm_time(value, field_name="DAILY_PUSH_TIME")


settings = Settings()
