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
├── core/            # config, db, auth, logging, scheduler
├── models/          # domain models + Pydantic schemas
├── prompts/         # LLM prompt templates (.md)
├── services/        # business logic, integrations, repositories
│   ├── llm/         # LLM client + task-specific prompting
│   ├── rag/         # retrieval pipeline
│   ├── repositories/# data access
│   ├── notification/# email, webhook, bark, telegram
│   └── source_adapters/  # RSS, HN, Reddit, GitHub adapters
└── web/             # static assets + Jinja2 templates
mcp_server.py        # MCP server entry point
main.py              # FastAPI app entry point
```

## Environment toggles

- `RAG_ENABLED` — set `false` to skip ~2GB model downloads and disable RAG Q&A.
- `API_KEY` — when set, all `/api/v1/*` routes require the `X-API-Key` header.
- `TAVILY_API_KEY` — enables web search for Deep Research and weekly enrichment.

See `.env.template` for the full list.
