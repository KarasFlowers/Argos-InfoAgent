from scripts import check_release


def test_check_release_runs_default_gates_without_docker_smoke(monkeypatch):
    seen: list[tuple[str, list[str], str | None]] = []

    def fake_run_command(name: str, command: list[str], *, env: dict[str, str]) -> None:
        seen.append((name, command, env.get("RAG_ENABLED")))

    monkeypatch.setattr(check_release, "run_command", fake_run_command)
    monkeypatch.setattr("sys.argv", ["check_release.py"])
    monkeypatch.setenv("RAG_ENABLED", "true")

    assert check_release.main() == 0

    names = [name for name, _, _ in seen]
    assert names == [
        "Ruff lint",
        "Ruff format",
        "Git diff check",
        "Frontend syntax",
        "Frontend API key smoke",
        "Docker Compose config",
        "Docker Compose RAG config",
        "Docker Compose Redis config",
        "Tests",
        "Runtime smoke",
    ]
    assert all(rag_enabled == "true" for _, _, rag_enabled in seen)


def test_check_release_can_include_docker_smoke(monkeypatch):
    seen: list[str] = []

    def fake_run_command(name: str, command: list[str], *, env: dict[str, str]) -> None:
        seen.append(name)

    monkeypatch.setattr(check_release, "run_command", fake_run_command)
    monkeypatch.setattr("sys.argv", ["check_release.py", "--with-docker-smoke"])

    assert check_release.main() == 0
    assert seen[-1] == "Docker smoke"
