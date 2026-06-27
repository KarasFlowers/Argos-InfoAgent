# Argos Refactor Notes

## Summary
Full-scope refactoring of the Argos codebase covering 17 improvement items across architecture, robustness, documentation, and data model concerns.

## API Compatibility
All public import names are preserved:
- `from app.services.llm_service import llm_service` — facade delegates to `app/services/llm/` subpackage
- `from app.services.rag_service import ingest, query_stream, _ingested_urls, ...` — facade re-exports from `app/services/rag/`
- `from app.services.db_service import db_service` — facade delegates to `app/services/repositories/`

## Changes Log

### Stage 1 — P0 Critical Fixes

| # | Item | Description |
|---|---|---|
| 3 | Eliminate `_last_content_fallback` global state | Source adapters now return `(summary, fallback_dict)` tuples explicitly. Fallback content flows back to the router for background RAG enqueue. |
| 11 | Unify `VALID_SOURCE_TYPES` | Single source of truth derived from adapter registry in `app/services/source_adapters/registry.py`. |
| 9 | Reddit 429 retry | Exponential backoff with `httpx.HTTPTransport(retries=2)` on HTTP 429/503 in `reddit_adapter.py`. |

### Stage 2 — P1 Architecture & Robustness

| # | Item | Description |
|---|---|---|
| 8 | Reuse shared `httpx.AsyncClient` | `app/core/http_client.py` singleton, closed via `@app.on_event("shutdown")`. All scrapers and RAG share one client. |
| 10 | RAG reuse OpenAI client | `rag_service` reuses `llm_service.client` instead of creating a second `AsyncOpenAI` instance. |
| 5 | `source_config` schema validation | Pydantic models per `source_type` in `app/models/source_configs.py`. Enforced at board creation time in `router.py`. |
| 15-17 | Docs & config updates | `README.md`, `.env.template` (added GitHub token / HN defaults / Reddit defaults), `.gitignore` (Redis persistence files). |

### Stage 3 — P3 Minor Improvements

| # | Item | Description |
|---|---|---|
| 7 | `published_at` default | `ContentItem.published_at` defaults to `""` with a `model_validator` that normalizes `None` to `""`. |
| 12 | `normalize_url` scheme docs | Expanded docstring + hostname safety guard in `merge_cross_source_duplicates` to prevent scheme-stripping collisions. |

### Stage 4 — P2 Large-Scale Refactoring

| # | Item | Description | Files |
|---|---|---|---|
| 1 | Split `llm_service` | Extracted 4 mixin classes into `app/services/llm/` subpackage: `ScoringMixin`, `SummaryMixin`, `WeeklyMixin`, `WizardMixin`. Original `llm_service.py` is now a thin facade re-exporting `LLMService` and `llm_service`. | `app/services/llm/*.py` |
| 2 | Encapsulate `rag_service` | Moved 914-line implementation to `app/services/rag/_core.py`. Original `rag_service.py` is a facade re-exporting all public names. | `app/services/rag/_core.py`, `rag_service.py` |
| 4 | Split `db_service` | Extracted 3 repository classes into `app/services/repositories/` subpackage: `SummaryRepo`, `PersonaRepo`, `BoardRepo`. `DBService` composes all three via mixin inheritance. Original `db_service.py` is a facade. | `app/services/repositories/*.py`, `db_service.py` |
| 6 | NewsItem JSON columns | `key_points`, `tags`, and `stats_json` changed from `str` (JSON-encoded) to native `JSON` columns. `_migrate_json_columns()` in `db.py` handles in-place SQLite migration on startup. | `app/models/domain.py`, `app/core/db.py` |

---

## Architecture Notes

### Facade Pattern

All three large service modules now follow a **facade** pattern so existing imports keep working without any changes:

```
from app.services.llm_service import llm_service      # -> app/services/llm/__init__.py
from app.services.rag_service import ingest             # -> app/services/rag/__init__.py
from app.services.db_service import db_service          # -> app/services/repositories/__init__.py
```

Internal structure:
- `app/services/llm/` — 4 mixins + composed `LLMService`
- `app/services/rag/` — `_core.py` with all functions + `__init__.py` re-exports
- `app/services/repositories/` — 3 repo classes + `DBService` mixin composition

### Module-Level Global State in RAG

`rag_service` still holds module-level state (`_ingested_urls`, `_ingest_queue`, `_bm25_indices`, `_content_fallback`, `_article_overview_cache`) because these are tightly coupled with the background `ingest_worker_loop()`. A future Stage 5 refactor could wrap these into a `RAGService` class once the worker lifecycle is redesigned.

### Native JSON Column Migration

SQLite stores `JSON` columns as `TEXT` internally, so the migration in `_migrate_json_columns()` re-parses any legacy string-encoded JSON and rewrites it as a single JSON object. This is idempotent — already-migrated rows are left untouched.

