import shutil
import subprocess
from pathlib import Path

import yaml

from scripts import docker_smoke


def _compose(path: str = "docker-compose.yml") -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_docker_compose_defaults_to_lightweight_app_only():
    compose = _compose()
    services = compose["services"]
    app_service = services["app"]
    app_env = app_service["environment"]
    build_args = app_service["build"]["args"]

    assert set(services) == {"app"}
    assert app_service["env_file"] == [{"path": ".env", "required": False}]
    assert "./.env:/app/.env:ro" not in app_service.get("volumes", [])
    assert build_args["RAG_ENABLED"] == "${RAG_ENABLED:-false}"
    assert build_args["PREWARM_RAG_MODELS"] == "${PREWARM_RAG_MODELS:-false}"
    assert build_args["MCP_ENABLED"] == "${MCP_ENABLED:-false}"
    assert app_env["API_KEY"] == "${API_KEY:-}"
    assert app_env["PUBLIC_BASE_URL"] == "${PUBLIC_BASE_URL:-http://localhost:8000}"
    assert app_env["RAG_ENABLED"] == "${RAG_ENABLED:-false}"


def test_docker_compose_rag_override_enables_rag_and_model_cache():
    override = _compose("docker-compose.rag.yml")
    app_service = override["services"]["app"]

    assert app_service["build"]["args"]["RAG_ENABLED"] == "true"
    assert app_service["build"]["args"]["PREWARM_RAG_MODELS"] == "${PREWARM_RAG_MODELS:-false}"
    assert app_service["environment"]["RAG_ENABLED"] == "true"
    assert "./data/hf-cache:/opt/hf-cache" in app_service["volumes"]
    assert "./data/chroma:/app/data/chroma" in app_service["volumes"]


def test_docker_compose_redis_override_keeps_redis_internal():
    override = _compose("docker-compose.redis.yml")
    redis_service = override["services"]["redis"]
    app_service = override["services"]["app"]

    assert "ports" not in redis_service
    assert app_service["depends_on"]["redis"]["condition"] == "service_healthy"
    assert app_service["environment"]["REDIS_URL"] == "redis://redis:6379"


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

    for filename in ["docker-compose.yml", "docker-compose.rag.yml", "docker-compose.redis.yml"]:
        (tmp_path / filename).write_text(Path(filename).read_text(encoding="utf-8"), encoding="utf-8")

    commands = [
        ["docker", "compose", "config", "--quiet"],
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.rag.yml", "config", "--quiet"],
        ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.redis.yml", "config", "--quiet"],
    ]
    for command in commands:
        result = subprocess.run(
            command,
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
