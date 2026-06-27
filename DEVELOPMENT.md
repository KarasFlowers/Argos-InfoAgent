# Development Guide

Local setup and common tasks for working on Argos.

## Prerequisites

- Python 3.11+
- Redis (for caching) — optional for most tests
- An OpenAI-compatible LLM API key

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-rag.txt   # only if RAG_ENABLED=true
cp .env.template .env                 # then edit LLM_API_KEY
```

## Running

```bash
uvicorn main:app --reload
```

The dashboard is at http://127.0.0.1:8000 and the public feed at `/feed`.

## Testing

```bash
pytest tests/                   # all tests
pytest tests/test_llm_client.py # one file
pytest -m "not slow"            # skip slow tests
pytest --cov=app                # with coverage
```

Tests talk to the ASGI app directly via `httpx.ASGITransport` (see `tests/conftest.py`), so the app lifespan and Redis are not required for most of them.

## Linting & formatting

```bash
ruff check .          # lint
ruff check . --fix    # autofix
ruff format .         # format
ruff format --check . # CI format gate
```

## Database migrations

Migrations use Alembic (config in `alembic.ini`, versions in `alembic/versions/`).

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Project layout

```
app/
├── api/              # FastAPI routers
│   └── routes/       # domain-specific route modules included by api/router.py
├── core/            # config, db, auth, logging, scheduler
├── models/          # domain models + Pydantic schemas
├── prompts/         # LLM prompt templates (.md)
├── services/        # business logic, integrations, repositories
│   ├── llm/         # LLM client + task-specific prompting
│   ├── rag/         # retrieval pipeline
│   ├── repositories/# data access
│   ├── notification/# email dispatcher
│   └── source_adapters/  # RSS, HN, Reddit, GitHub adapters
└── web/             # static assets + Jinja2 templates
mcp_server.py        # MCP server entry point
main.py              # FastAPI app entry point
```

`app/api/router.py` is the compatibility aggregator for the v1 API. New endpoints should go into a focused module under `app/api/routes/` and be included from the aggregator. Keep request/response DTOs close to their route module unless they are shared by multiple domains.

## Environment toggles

- `RAG_ENABLED` — set `false` to skip ~2GB model downloads and disable RAG Q&A.
- `API_KEY` — when set, private API routes require the `X-API-Key` header. `/`, `/favicon.ico`, `/static/*`, `/feed`, and `/api/v1/ping` stay public; `OPTIONS` stays open for CORS preflight.
- `PUBLIC_BASE_URL` — public origin used in RSS/canonical links; set this when running behind a reverse proxy. It must be an absolute `http(s)` URL without query/fragment.
- `CORS_ORIGINS` — comma-separated browser origins. Use origins only (`https://argos.example.com`), not paths. If set to `*`, credentialed CORS is disabled even when `CORS_ALLOW_CREDENTIALS=true`.
- `DAILY_PUSH_TIME` — local 24-hour `HH:MM` time. Invalid values fail fast during settings load.
- `LOG_FORMAT=json` — emits JSON logs for Docker/log collectors; common secret fields and token-like values are redacted before output.
- `TAVILY_API_KEY` — enables web search for Deep Research and weekly enrichment.

## Production sanity checks

```bash
python scripts/check_release.py
```

This runs the local release gate: Ruff lint/format, `git diff --check`, frontend syntax and API-key smoke, Docker Compose config validation, the full test suite, and the local runtime smoke.

Run the real Docker Compose smoke only when Docker is available:

```bash
python scripts/check_release.py --with-docker-smoke
```

Equivalent individual commands:

```bash
ruff check .
ruff format --check .
pytest
node --check app/web/static/app.js
node scripts/frontend_auth_smoke.js
docker compose config --quiet
python scripts/runtime_smoke.py
python scripts/docker_smoke.py
python scripts/backup_data.py
python scripts/restore_data.py backups/<archive>.zip --dry-run
python scripts/restore_data.py backups/<archive>.zip --force
```

`scripts/runtime_smoke.py` starts a real local Uvicorn process with a temporary SQLite database, `RAG_ENABLED=false`, and an `API_KEY`, then verifies `/api/v1/ping` stays public while private routes require `X-API-Key`.

Use `/api/v1/ping` for public liveness checks. Use the private `/api/v1/status` endpoint for operator diagnostics; it reports database readiness and feature flags without returning provider keys, tokens, or passwords.

`scripts/docker_smoke.py` runs `RAG_ENABLED=false API_KEY=argos-smoke-key docker compose up -d --build`, waits for `/api/v1/ping`, and verifies private endpoints reject missing/wrong `X-API-Key` values while accepting the correct key. It requires a running Docker daemon.

`scripts/backup_data.py` writes a zip archive under `backups/` using SQLite's backup API for `data/sqlite/argos.db` and includes `data/chroma/` by default. It never overwrites an existing archive with the same timestamp; a numeric suffix is added instead.

`scripts/restore_data.py --dry-run` validates the archive and prints target paths without writing files. The real restore should run only after Argos is stopped; it refuses to overwrite existing data unless `--force` is passed.

The requirement-by-requirement hardening evidence is tracked in `docs/INDUSTRIALIZATION_AUDIT.md`.

See `.env.template` for the full list.
