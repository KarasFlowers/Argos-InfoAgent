# Security Policy

Argos is designed for private single-user or small self-hosted deployments. It is not a multi-tenant SaaS product and does not provide user accounts, organization isolation, or role-based authorization.

## Supported Deployment Model

- Run Argos on a trusted host or private network by default.
- Set `API_KEY` before exposing Argos outside localhost or a private VPN.
- Put Argos behind a reverse proxy that terminates TLS for internet-facing deployments.
- Set `PUBLIC_BASE_URL` to the externally reachable origin when serving feeds behind a proxy.
- Do not publish Redis to the internet. The default Docker Compose stack keeps Redis on the internal Docker network; use `REDIS_URL` for a separately managed, protected Redis instance.

## Authentication

When `API_KEY` is configured, private routes require:

```text
X-API-Key: <your-api-key>
```

The only public paths are:

- `/`
- `/favicon.ico`
- `/static/*`
- `/feed`
- `/feed/*`
- `/api/v1/ping`
- `OPTIONS *` for CORS preflight only

Leaving `API_KEY` empty disables authentication and is intended only for local development or fully private networks.

The web dashboard includes a "Key" control for self-hosted use. It stores the value in browser local storage and adds it as `X-API-Key` only for same-origin `/api/*` requests. Use this convenience only on trusted personal devices; clear it before sharing a browser profile or machine.

## Secrets

- Store provider keys such as `LLM_API_KEY`, `DEEPSEEK_API_KEY`, `TAVILY_API_KEY`, SMTP credentials, and notification tokens in `.env` or your deployment secret manager.
- Docker Compose reads `.env` through an optional `env_file` instead of mounting it into the container filesystem.
- `.dockerignore` excludes `.env*`, `data/`, `logs/`, `backups/`, Redis dumps, and local caches from Docker build context.
- Do not commit `.env`, `data/`, `logs/`, or `backups/`.
- New installs read model provider credentials from environment variables and do not seed them into the SQLite `ModelApiConfig` table.
- Use `ModelApiConfig.safe_dict()` for admin/UI output so stored provider keys are masked before display.
- Scheduled external notifications are disabled by default; enable them explicitly with `NOTIFY_CHANNELS` and channel credentials.
- Existing database rows containing API keys should be rotated if the database has been shared or exposed.

## Network Fetching and SSRF

Argos fetches external URLs for RSS, source discovery, and optional RAG ingestion. These paths use URL safety checks to reject private, loopback, link-local, and otherwise unsafe targets. Keep this validation in place for any new feature that fetches user-provided URLs.

Redirect targets are re-validated before following redirects. RSS feed responses and RAG article HTML that exceed parser size limits are rejected instead of being parsed or cached.

## Data Protection

- The default data store is SQLite under `data/sqlite/argos.db`.
- RAG vector data is stored under `data/chroma/`.
- Back up both together with `python scripts/backup_data.py`; timestamp collisions create a suffixed archive instead of overwriting an existing backup.
- Before restoring, stop Argos and inspect the target paths with `python scripts/restore_data.py backups/<archive>.zip --dry-run`.
- Restore with `--force` only when intentionally replacing existing local data.
- Treat backup archives as sensitive because they may contain article history, preferences, memory, and operational metadata.

## Reporting Issues

For private deployments, rotate exposed credentials first, then file an issue with:

- affected version or commit
- deployment mode
- reproduction steps
- relevant logs with secrets redacted

Please do not include real API keys, tokens, `.env` files, databases, or backup archives in reports.
