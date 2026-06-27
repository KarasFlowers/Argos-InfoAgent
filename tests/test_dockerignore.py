from pathlib import Path


def _dockerignore_lines() -> list[str]:
    return [
        line.strip()
        for line in Path(".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_dockerignore_excludes_sensitive_runtime_files():
    lines = _dockerignore_lines()

    for pattern in [
        ".env*",
        "data/",
        "logs/",
        "backups/",
        "dump.rdb",
        "*.rdb",
        "*.log",
        ".codex-ui-server.*.log",
    ]:
        assert pattern in lines


def test_dockerignore_excludes_local_cache_and_reference_dirs():
    lines = _dockerignore_lines()

    for pattern in [
        "venv/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".tmp/",
        "reference/",
        "tools/redis/",
        "tests/",
    ]:
        assert pattern in lines


def test_dockerignore_keeps_env_template_available():
    lines = _dockerignore_lines()

    assert ".env*" in lines
    assert "!.env.template" in lines
