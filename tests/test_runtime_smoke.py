from scripts import runtime_smoke


class _FakeProcess:
    stdout = None

    def poll(self):
        return None


def test_runtime_smoke_uses_lightweight_private_runtime_settings(monkeypatch):
    popen_calls: list[dict] = []
    checked: list[tuple[str, str, str | None]] = []
    terminated: list[_FakeProcess] = []

    def fake_popen(cmd, *, env, text, stdout, stderr):
        popen_calls.append(
            {
                "cmd": cmd,
                "env": env,
                "text": text,
                "stdout": stdout,
                "stderr": stderr,
            }
        )
        return _FakeProcess()

    def fake_wait_for_ping(root_url: str, deadline_seconds: int) -> None:
        assert root_url == "http://127.0.0.1:8765"
        assert deadline_seconds == 7

    def fake_request_status(root_url: str, path: str, *, api_key: str | None = None, timeout: float = 3.0) -> int:
        checked.append((root_url, path, api_key))
        if path == "/api/v1/ping":
            return 200
        if api_key == runtime_smoke.API_KEY:
            return 200
        return 403

    def fake_terminate(process: _FakeProcess) -> None:
        terminated.append(process)

    monkeypatch.setattr(runtime_smoke.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime_smoke, "wait_for_ping", fake_wait_for_ping)
    monkeypatch.setattr(runtime_smoke, "request_status", fake_request_status)
    monkeypatch.setattr(runtime_smoke, "terminate", fake_terminate)
    monkeypatch.setattr("sys.argv", ["runtime_smoke.py", "--port", "8765", "--timeout", "7"])

    assert runtime_smoke.main() == 0

    call = popen_calls[0]
    assert call["env"]["API_KEY"] == runtime_smoke.API_KEY
    assert call["env"]["PUBLIC_BASE_URL"] == "http://127.0.0.1:8765"
    assert call["env"]["RAG_ENABLED"] == "false"
    assert call["env"]["SQLALCHEMY_DATABASE_URI"].startswith("sqlite+aiosqlite:///")
    assert call["env"]["CHROMA_DB_DIR"]
    assert call["stdout"].name.endswith("runtime-smoke.log")
    assert "uvicorn.run('main:app'" in call["cmd"][2]
    assert ("http://127.0.0.1:8765", "/api/v1/ping", None) in checked
    assert ("http://127.0.0.1:8765", "/api/v1/admin/tasks", None) in checked
    assert ("http://127.0.0.1:8765", "/api/v1/admin/tasks", "wrong-key") in checked
    assert ("http://127.0.0.1:8765", "/api/v1/admin/tasks", runtime_smoke.API_KEY) in checked
    assert ("http://127.0.0.1:8765", "/api/v1/status", None) in checked
    assert ("http://127.0.0.1:8765", "/api/v1/status", "wrong-key") in checked
    assert ("http://127.0.0.1:8765", "/api/v1/status", runtime_smoke.API_KEY) in checked
    assert len(terminated) == 1


def test_runtime_smoke_log_tail_is_bounded(tmp_path):
    log_path = tmp_path / "runtime-smoke.log"
    log_path.write_text("x" * 5000, encoding="utf-8")

    assert runtime_smoke.tail_file(log_path, limit=12) == "x" * 12


def test_temporary_runtime_dir_warns_instead_of_failing_on_cleanup_lock(monkeypatch, capsys):
    attempts: list[str] = []

    def fake_mkdtemp(prefix: str) -> str:
        assert prefix == "argos-runtime-smoke-"
        return "C:/tmp/argos-runtime-smoke-locked"

    def fake_rmtree(path):
        attempts.append(str(path))
        raise PermissionError("locked")

    monkeypatch.setattr(runtime_smoke.tempfile, "mkdtemp", fake_mkdtemp)
    monkeypatch.setattr(runtime_smoke.shutil, "rmtree", fake_rmtree)
    monkeypatch.setattr(runtime_smoke.time, "sleep", lambda _seconds: None)

    with runtime_smoke.temporary_runtime_dir() as tmp_path:
        assert tmp_path.name == "argos-runtime-smoke-locked"

    assert len(attempts) == 5
    assert "could not remove temporary runtime directory" in capsys.readouterr().err
