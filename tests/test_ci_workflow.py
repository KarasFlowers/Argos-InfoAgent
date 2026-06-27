import re
from pathlib import Path

import yaml


def _ci_workflow() -> dict:
    return yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))


def _step_runs(job: dict) -> list[str]:
    return [step.get("run", "") for step in job.get("steps", [])]


def test_ci_lint_job_keeps_release_gate_checks():
    workflow = _ci_workflow()
    lint_runs = _step_runs(workflow["jobs"]["lint"])

    assert "ruff check ." in lint_runs
    assert "ruff format --check ." in lint_runs
    assert "git diff --check" in lint_runs
    assert "docker compose config --quiet" in lint_runs
    assert "node --check app/web/static/app.js" in lint_runs
    assert "node scripts/frontend_auth_smoke.js" in lint_runs


def test_ci_test_job_uses_project_pytest_defaults():
    workflow = _ci_workflow()
    test_runs = _step_runs(workflow["jobs"]["test"])

    assert "python -m pytest" in test_runs
    assert "python scripts/runtime_smoke.py --timeout 90" in test_runs
    assert "pytest tests/ -v" not in test_runs


def test_docker_python_version_is_covered_by_ci_matrix():
    workflow = _ci_workflow()
    matrix_versions = set(workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"])
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    image_versions = set(re.findall(r"FROM python:(\d+\.\d+)-slim", dockerfile))

    assert image_versions
    assert image_versions <= matrix_versions
