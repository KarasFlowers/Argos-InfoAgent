## Description
<!-- What does this PR change and why? -->

## Related issues
<!-- e.g. Closes #123 -->

## Type of change
- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no functional change)
- [ ] Documentation
- [ ] Chore / tooling

## Checklist
- [ ] Local release gate passes (`python scripts/check_release.py`)
- [ ] Frontend request/auth changes validated (`node --check app/web/static/app.js && node scripts/frontend_auth_smoke.js`)
- [ ] Added/updated tests for the change
- [ ] Updated relevant documentation
- [ ] Runtime smoke passes when API/auth/startup behavior changes (`python scripts/runtime_smoke.py`)
- [ ] Docker/deployment changes validated (`docker compose config --quiet`; run `python scripts/docker_smoke.py` when Docker daemon is available)
- [ ] No secrets or credentials committed
