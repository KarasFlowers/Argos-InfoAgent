# Argos Industrialization Audit

This document maps the hardening plan to current repository evidence. Keep it updated when release gates, deployment behavior, or public interfaces change.

Last local evidence:

- `python scripts/check_release.py`
- Result: `426 passed`; Ruff lint/format, git diff check, frontend syntax/auth smoke, Docker Compose config, full pytest, and runtime smoke all passed.
- Real Docker container smoke is not yet proven on this host because Docker Desktop's Linux daemon is not running (`dockerDesktopLinuxEngine` pipe is missing).

## Requirement Status

| Area | Status | Current evidence |
|---|---|---|
| Private single-user/self-hosted scope | Proven | README/SECURITY explicitly document no multi-tenant accounts or roles. |
| API key middleware public/private split | Proven | `app/core/auth.py`; `tests/test_auth.py`; runtime and Docker smoke scripts validate private endpoints reject missing/wrong keys and accept the correct key. Key comparison uses constant-time digest comparison, and CORS preflight `OPTIONS` is allowed without opening private business methods. |
| Browser-facing security headers | Proven | `main.py`; responses set `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy`; `tests/test_api.py`. |
| CORS credential boundary | Proven | `app/core/config.py` exposes the effective CORS credential policy; wildcard origins disable credentialed CORS; `tests/test_config.py` and docs consistency tests cover the behavior. |
| Public health check | Proven | `GET /api/v1/ping` remains public; `tests/test_auth.py`; `scripts/runtime_smoke.py`. |
| Private operator diagnostics | Proven | `GET /api/v1/status` reports DB/feature readiness without secrets; `tests/test_api.py`; route registration test. |
| Release quality gates | Proven | `pyproject.toml`; `.github/workflows/ci.yml` runs Ruff, `git diff --check`, frontend smoke, Compose config, pytest, and runtime smoke; `scripts/check_release.py`; latest release gate passed. |
| Frontend API key behavior | Proven | `app/web/static/app.js`; `scripts/frontend_auth_smoke.js`; `tests/test_frontend_api_key.py`. |
| Router modularization | Proven | `app/api/router.py` aggregates domain routes under `app/api/routes/`; `tests/test_api_route_registration.py`. |
| `PUBLIC_BASE_URL` for feed/canonical links | Proven | `app/core/config.py`; feed templates/routes; `tests/test_public_base_url.py`. |
| Secret handling | Proven | Model API config no longer seeds env keys into SQLite; safe serialization/log redaction tests cover secret masking. |
| Trace/logging observability | Proven | Per-request trace IDs are returned as `X-Trace-ID`, log context is reset after each request, and secret redaction is tested. |
| SQLite migrations and compatibility | Proven | Alembic now bootstraps an empty SQLite database to head, verifies ORM-declared tables/columns exist at head, startup compatibility fallback remains for legacy schemas, and both paths are covered by `tests/test_db_migrations.py`. |
| TaskRun reliability | Proven | Scheduler task run lifecycle/status/error truncation covered by `tests/test_scheduler_task_runs.py`. |
| SSRF/URL safety | Proven | URL safety checks and feed/RAG/source discovery tests under `tests/test_url_safety.py`, `tests/test_source_url_safety.py`, `tests/test_p3_advanced_rag.py`, and related route tests; hosts are normalized before blocklist/IP checks, user-supplied fetches re-validate redirect targets before following them, and oversized RSS/RAG responses are rejected before parsing/caching. |
| Backup/restore | Proven | `scripts/backup_data.py` and `scripts/restore_data.py`; tests cover SQLite snapshot, Chroma, symlink skipping, manifest host-path redaction, overwrite protection, dry-run, and zip-slip rejection. |
| Runtime smoke | Proven | `scripts/runtime_smoke.py` starts real Uvicorn with temp SQLite, `RAG_ENABLED=false`, and API key matrix checks. |
| Docker Compose config | Proven | `docker compose config --quiet` passes; tests cover optional `.env`, Redis not exposed, security env wiring. |
| Real Docker container smoke | Blocked by environment | `scripts/docker_smoke.py` is implemented and tested, but cannot run here until Docker Desktop Linux daemon is available. |
| Documentation | Proven | README, README_zh, DEVELOPMENT, SECURITY, `.env.template`, docs, and PR template document operation/security/release checks; `tests/test_docs_consistency.py` guards high-risk facts, prevents advertising unimplemented notification channels, and ensures `docs/` is not ignored by Git. |

## Release Commands

Run before merging:

```bash
python scripts/check_release.py
```

Run when Docker daemon is available:

```bash
python scripts/check_release.py --with-docker-smoke
```

## External Blocker

The only current unproven acceptance item is a real Docker Compose container run. `docker compose config --quiet` is validated, but `docker info` fails on this host because the Docker Desktop Linux engine pipe does not exist. Do not mark Docker smoke as complete until `python scripts/check_release.py --with-docker-smoke` succeeds.
