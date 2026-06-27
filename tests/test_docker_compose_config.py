import shutil
import subprocess
from pathlib import Path

import yaml

from scripts import docker_smoke


def test_docker_compose_exposes_runtime_security_settings():
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
    app_env = compose["services"]["app"]["environment"]
    app_service = compose["services"]["app"]
    redis_service = compose["services"]["redis"]

    assert app_service["env_file"] == [{"path": ".env", "required": False}]
    assert "./.env:/app/.env:ro" not in app_service.get("volumes", [])
    assert "API_KEY=${API_KEY:-}" in app_env
    assert "PUBLIC_BASE_URL=${PUBLIC_BASE_URL:-http://localhost:8000}" in app_env
    assert "RAG_ENABLED=${RAG_ENABLED:-true}" in app_env
    assert "ports" not in redis_service


def test_docker_smoke_uses_private_runtime_settings(monkeypatch):
    commands: list[list[str]] = []
    env_seen: list[dict[str, str]] = []
    checked: list[tuple[str, str | None]] = []

    def fake_run(cmd: list[str], *, env: dict[str, str]) -> None:
        commands.append(cmd)
        env_seen.append(env)

    def fake_wait_for_ping(deadline_seconds: int) -> None:
        assert deadline_seconds == 120

    def fake_request_status(path: str, *, api_key: str | None = None, timeout: float = 3.0) -> int:
        checked.append((path, api_key))
        if path == "/api/v1/ping":
            return 200
        if api_key == docker_smoke.API_KEY:
            return 200
        return 403

    monkeypatch.setattr(docker_smoke, "run", fake_run)
    monkeypatch.setattr(docker_smoke, "wait_for_ping", fake_wait_for_ping)
    monkeypatch.setattr(docker_smoke, "request_status", fake_request_status)
    monkeypatch.setattr("sys.argv", ["docker_smoke.py", "--no-build"])

    assert docker_smoke.main() == 0
    assert commands == [["docker", "info"], ["docker", "compose", "up", "-d"]]
    assert env_seen[0]["RAG_ENABLED"] == "false"
    assert env_seen[0]["API_KEY"] == docker_smoke.API_KEY
    assert env_seen[0]["PUBLIC_BASE_URL"] == docker_smoke.ROOT_URL
    assert ("/api/v1/ping", None) in checked
    assert ("/api/v1/admin/tasks", None) in checked
    assert ("/api/v1/admin/tasks", "wrong-key") in checked
    assert ("/api/v1/admin/tasks", docker_smoke.API_KEY) in checked
    assert ("/api/v1/status", None) in checked
    assert ("/api/v1/status", "wrong-key") in checked
    assert ("/api/v1/status", docker_smoke.API_KEY) in checked


def test_docker_smoke_prints_logs_and_tears_down_on_failure(monkeypatch):
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], *, env: dict[str, str]) -> None:
        commands.append(cmd)

    def fake_wait_for_ping(deadline_seconds: int) -> None:
        return None

    def fake_request_status(path: str, *, api_key: str | None = None, timeout: float = 3.0) -> int:
        if path == "/api/v1/ping":
            return 200
        return 403

    monkeypatch.setattr(docker_smoke, "run", fake_run)
    monkeypatch.setattr(docker_smoke, "wait_for_ping", fake_wait_for_ping)
    monkeypatch.setattr(docker_smoke, "request_status", fake_request_status)
    monkeypatch.setattr("sys.argv", ["docker_smoke.py", "--no-build", "--teardown"])

    try:
        docker_smoke.main()
    except RuntimeError as error:
        assert "Unexpected Docker smoke status matrix" in str(error)
    else:
        raise AssertionError("docker smoke should fail when correct API key is rejected")

    assert ["docker", "compose", "logs", "--tail", "80", "app"] in commands
    assert ["docker", "compose", "down"] in commands


def test_docker_compose_config_allows_missing_env_file(tmp_path):
    if shutil.which("docker") is None:
        return

    (tmp_path / "docker-compose.yml").write_text(
        Path("docker-compose.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    result = subprocess.run(
        ["docker", "compose", "config", "--quiet"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
