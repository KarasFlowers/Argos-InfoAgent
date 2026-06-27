# Argos — AI Daily Tech Briefing

## Overview

Argos is a FastAPI-based daily technology briefing assistant powered by LLM and RAG. It aggregates content from multiple sources (RSS, HackerNews, Reddit, GitHub), applies AI scoring and summarization, and can deliver personalized daily briefings by email.

## Architecture

```
main.py                    # FastAPI app entry, lifespan, middleware
app/
  api/
    router.py              # Aggregates domain REST routers (summary, briefing, persona, admin, etc.)
    routes/                # Domain routers mounted under /api/v1
    rag_router.py           # RAG-specific endpoints (chat, ingest, query/global)
  core/
    config.py              # Pydantic Settings (env vars, defaults)
    db.py                  # Async SQLAlchemy engine, session factory, migrations, seeding
    scheduler.py           # APScheduler background jobs with TaskRun tracking
    auth.py                # API key middleware
    logging_config.py      # Structured logging setup (structlog)
    http_client.py         # Shared httpx client with timeout/retry
    url_safety.py          # SSRF prevention — blocks private/internal URLs
    first_run.py           # First-run .env wizard (interactive CLI)
  models/
    domain.py              # SQLModel tables (Board, NewsItem, DailySummary, UserPersona, UserMemory, Source, TaskRun, etc.)
    schemas.py             # Pydantic request/response schemas with LLM output tolerance
    source_configs.py      # Per-source-type Pydantic validation for board source_config
  prompts/                  # LLM prompt templates (daily_briefing, quality_scoring, weekly_*, research_*, etc.)
  services/
    llm/
      client.py            # Unified LLM client with CircuitBreaker + multi-tier routing
      summary.py           # Daily summary generation pipeline
      scoring.py           # LLM-based article quality scoring with fallback
      weekly.py            # Weekly report generation
      wizard.py            # Conversational board wizard
    rag/                   # RAG pipeline (bi-encoder, cross-encoder, ChromaDB, BM25, HyDE)
    repositories/          # Database facades (SummaryRepo, PersonaRepo, BoardRepo)
    notification/          # Notification dispatcher (email)
    source_adapters/       # Multi-source adapters (RSS, HN, Reddit, GitHub, Multi, pure-LLM)
    llm_service.py         # LLM facade (re-exports from llm/)
    rag_service.py         # RAG facade (re-exports from rag/)
    db_service.py          # DB facade (re-exports from repositories/)
    filtering_service.py   # Rule-based content quality filtering (blacklist + heuristics)
    clustering_service.py  # Event grouping engine (Bi-Encoder + Jaccard fallback)
    insights_service.py    # Topic tree, trending, heatmap, entity timeline
    research_service.py    # Deep research cycle (decompose → search → synthesize)
    memory_service.py      # User factual memory CRUD for prompt enrichment
    interest_filter.py     # Persona-based interest pre-filtering
    learning_service.py    # Feedback-driven interest extraction and reranking
    source_health_service.py  # RSS/API source health monitoring and logging
    dedup_service.py       # URL normalization + semantic deduplication
    redis_service.py       # Redis cache wrapper
    metrics_service.py     # LLM token usage and latency tracking
    chat_history_service.py  # Per-article chat history persistence
    email_service.py       # Email push via SMTP
    rss_service.py         # RSS feed fetching and parsing
  skills/                   # Extensible skill plugins
  web/
    templates/             # Jinja2 HTML templates (index.html, feed.html)
    static/                # CSS, JS assets
alembic/                   # Database migrations (Alembic)
tests/                     # Pytest test suite
mcp_server.py              # MCP Server entry point (14 tools for AI assistant integration)
```

## Key Business Constraints

- **Board System**: Each board has independent sources, prompts, schedules, notification channels, and perspectives. Default board = tech.
- **Multi-tier LLM**: "fast" tier for scoring/filtering, "smart" tier for summarization. CircuitBreaker prevents cascade failures.
- **Graceful degradation**: If LLM fails, fallback summaries are generated from raw article titles/links.
- **Personalization**: UserPersona + UserMemory + feedback-driven interest extraction. Preferences influence scoring but don't dominate (30-40% cap).
- **Daily report refinement**: Users can iteratively refine an existing briefing with natural-language instructions; sessions tracked in `DailyReportRefinementSession`.
- **URL safety**: All user-supplied URLs pass through `url_safety.py` to block private/internal addresses (SSRF prevention).
- **Source health monitoring**: RSS/API source failures logged to `SourceHealthLog`; admin endpoints expose health status.

## Development Principles

1. **Never break existing API contracts** — `DailySummaryResponse` is consumed by multiple clients.
2. **SQLite-first** — all DB operations use async aiosqlite. Alembic migrations must be SQLite-compatible (no ALTER COLUMN type changes).
3. **Defensive LLM parsing** — `model_validator` in schemas normalizes common LLM output variations (title→headline, string→list, missing fields).
4. **Background jobs via APScheduler** — all jobs wrapped with `track_task_run()` for observability.
5. **Best-effort health logging** — RSS fetch failures are recorded but never block the pipeline.
6. **URL safety validation** — all user-supplied URLs must be validated through `url_safety.py` before any outbound HTTP request.

## Testing

```bash
# Run all tests
$env:PYTHONPATH="."; venv\Scripts\python.exe -m pytest tests/ -v

# Run specific test suites
pytest tests/test_circuit_breaker.py     # CircuitBreaker state machine
pytest tests/test_filtering_service.py   # Blacklist, low-signal, domain filters
pytest tests/test_clustering_service.py  # Fingerprint, Jaccard overlap
pytest tests/test_schemas_tolerance.py   # LLM output tolerance validation
```

## Database Migrations

```bash
# Generate a new migration after model changes
$env:PYTHONPATH="."; venv\Scripts\python.exe -m alembic revision --autogenerate -m "description"

# IMPORTANT: Review generated migration and remove SQLite-incompatible ALTER COLUMN ops
# Then add `import sqlmodel.sql.sqltypes` if AutoString columns are used

# Apply migrations
$env:PYTHONPATH="."; venv\Scripts\python.exe -m alembic upgrade head

# Stamp current state (when tables already exist from create_all)
$env:PYTHONPATH="."; venv\Scripts\python.exe -m alembic stamp head
```

## Environment Variables

Key settings (see `app/core/config.py` for full list):

| Variable | Description |
|----------|-------------|
| `LLM_API_KEY` | Primary LLM API key (any OpenAI-compatible provider) |
| `LLM_BASE_URL` | LLM API base URL; set explicitly with generic `LLM_API_KEY` |
| `LLM_MODEL` | Default model name (default: `deepseek-chat`) |
| `FAST_LLM` | "fast" tier model in `provider:model` format |
| `SMART_LLM` | "smart" tier model in `provider:model` format |
| `DEEPSEEK_API_KEY` | Legacy alias — fallback when `LLM_API_KEY` is unset |
| `API_KEY` | Optional API key for private routes; `/api/v1/ping` and documented public pages remain open |
| `PUBLIC_BASE_URL` | Public origin for generated RSS/canonical links |
| `SQLALCHEMY_DATABASE_URI` | SQLite path (default: `sqlite+aiosqlite:///./data/sqlite/argos.db`) |
| `REDIS_URL` | Redis URL for caching (default: `redis://localhost:6379`) |
| `CHROMA_DB_DIR` | ChromaDB persistent storage path |
| `RAG_BACKGROUND_INGEST_ENABLED` | Enable background RAG ingestion |
| `RAG_BACKGROUND_INGEST_WORKERS` | Number of background ingest workers |
| `RAG_HYDE_ENABLED` | Enable HyDE query rewriting |
| `HISTORY_DAYS_TO_KEEP` | Days to retain historical data |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins; `*` disables credentialed CORS |
| `CORS_ALLOW_CREDENTIALS` | Allow credentialed CORS for explicit origins |

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/summary` | Daily summary (with caching + generation) |
| `GET /api/v1/briefing` | Structured briefing with sections + clusters |
| `POST /api/v1/briefing/refine` | Refine existing briefing with instruction |
| `GET /api/v1/briefing/refine/{session_id}` | Check refinement session status |
| `GET /api/v1/history` | Summary history archive |
| `GET /api/v1/history/weekly_insight` | AI-generated weekly insight |
| `GET /api/v1/history/weekly_report` | Structured weekly report |
| `GET /api/v1/boards` | List all boards |
| `POST /api/v1/boards` | Create a board |
| `GET /api/v1/boards/{slug}` | Get board details |
| `POST /api/v1/boards/wizard` | AI-guided board wizard |
| `GET /api/v1/persona` | List persona instructions |
| `GET /api/v1/persona/inferred` | AI-inferred interests |
| `GET /api/v1/preferences` | Explicit preferences (persona + memory) |
| `POST /api/v1/rag/ingest` | Ingest URL into vector store |
| `POST /api/v1/rag/query` | RAG Q&A (SSE streaming) |
| `POST /api/v1/rag/query/global` | Cross-article RAG Q&A |
| `GET /api/v1/insights/topic_tree` | Hierarchical topic tree |
| `GET /api/v1/insights/trending` | Trending topics analysis |
| `GET /api/v1/insights/heatmap` | Category frequency heatmap |
| `GET /api/v1/insights/timeline` | Entity occurrence timeline |
| `POST /api/v1/research` | Deep research cycle |
| `GET /api/v1/metrics` | System metrics (token usage, latency) |
| `GET /api/v1/metrics/cost` | Per-label LLM cost breakdown |
| `GET /api/v1/feed` | RSS 2.0 XML feed |
| `GET /feed` | Public SEO HTML feed page |
| `GET /api/v1/admin/tasks` | Background task runs |
| `GET /api/v1/admin/sources/health` | Source health dashboard |
| `GET /api/v1/ping` | Health check |
| `GET /api/v1/status` | Private operator diagnostics (DB/features/auth flags, no secrets) |

## Admin Access

Admin endpoints (`/api/v1/admin/*`) are protected by the same `API_KEY` middleware as other private endpoints. No separate admin auth, user accounts, tenants, or roles are implemented; set `API_KEY` to enable single-key protection.
