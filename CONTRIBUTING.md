# Contributing to Argos

Thanks for contributing. This guide covers the workflow, branch strategy, and commit conventions.

## Branch strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production-ready. Protected — merge via PR only. |
| `develop` | Integration branch for the next release. |
| `feat/<name>` | New feature. |
| `fix/<name>` | Bug fix. |
| `chore/<name>` | Tooling, deps, refactors with no behavior change. |

Never commit directly to `main`. Branch off `develop`, then open a PR back into it.

```bash
git switch develop
git pull
git switch -c feat/my-feature
# ...work...
git push -u origin feat/my-feature
```

## Commit messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>
```

Common types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`.
Scope is optional but encouraged (`feat(rag): ...`, `fix(api): ...`).

## Before you push

```bash
python scripts/check_release.py
```

This runs Ruff lint/format, `git diff --check`, frontend syntax and API-key smoke checks, Docker Compose config validation, the full pytest suite, and the local runtime smoke. When a Docker daemon is available and deployment behavior changed, also run:

```bash
python scripts/check_release.py --with-docker-smoke
```

You can also install the git hooks for faster local feedback while developing:

```bash
pip install pre-commit
pre-commit install
```

## Pull requests

1. Keep PRs focused — one logical change per PR.
2. Fill out the PR template.
3. Ensure CI is green before requesting review.
4. Squash-merge into `develop` unless there's a reason to preserve history.

See [DEVELOPMENT.md](DEVELOPMENT.md) for local setup.
