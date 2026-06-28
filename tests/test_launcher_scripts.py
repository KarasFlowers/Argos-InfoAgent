from pathlib import Path

from app.core import first_run


def test_unix_launcher_prompts_for_generic_llm_api_key():
    script = Path("scripts/start.sh").read_text(encoding="utf-8")

    assert "LLM_API_KEY:" in script
    assert "ARGOS_FIRST_RUN_LLM_API_KEY" in script
    assert '# LLM_API_KEY="sk-your-api-key-here"' in script
    assert "sk-your-deepseek-api-key-here" not in script
    assert "Please edit it to add your LLM_API_KEY." in script
    assert "RAG_ENABLED_EFFECTIVE=false" in script
    assert "true|1|yes|on)" in script
    assert "skipping RAG dependencies and embedding model download" in script
    assert '"$PIP" install -r requirements-rag.txt -q' in script
    assert '"$PYTHON" scripts/download_models.py' in script


def test_windows_launcher_bootstraps_first_run_environment():
    script = Path("scripts/Open_Web_Dashboard.bat").read_text(encoding="utf-8")

    assert 'set "PYTHON_EXE=' in script
    assert '-m venv "%PROJECT_ROOT%\\venv"' in script
    assert '-m pip install -r "%PROJECT_ROOT%\\requirements.txt"' in script
    assert "RAG_ENABLED_EFFECTIVE=false" in script
    assert "resolve_rag_enabled.py" in script
    assert "requirements-rag.txt" in script
    assert "download_models.py" in script
    assert "setup_redis.ps1" not in script
    assert "Redis not found. Caching will be disabled." in script
    assert 'copy "%PROJECT_ROOT%\\.env.template" "%PROJECT_ROOT%\\.env"' in script
    assert "ARGOS_FIRST_RUN_LLM_API_KEY=LLM_API_KEY" in script
    assert '# LLM_API_KEY=\\"sk-your-api-key-here\\"' in script
    assert "DEEPSEEK_API_KEY:" not in script


class _InteractiveStdin:
    def isatty(self) -> bool:
        return True


def test_first_run_interactive_writes_generic_llm_api_key(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_template = tmp_path / ".env.template"
    env_template.write_text(
        '# LLM_API_KEY="sk-your-api-key-here"\nDEEPSEEK_API_KEY=""\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(first_run, "ENV_FILE", env_file)
    monkeypatch.setattr(first_run, "ENV_TEMPLATE", env_template)
    monkeypatch.setattr(first_run.sys, "stdin", _InteractiveStdin())
    monkeypatch.setattr("builtins.input", lambda _: "sk-test-key")

    first_run.ensure_env()

    text = env_file.read_text(encoding="utf-8")
    assert 'LLM_API_KEY="sk-test-key"' in text
    assert 'DEEPSEEK_API_KEY=""' in text
    assert "DeepSeek API key" not in capsys.readouterr().out


def test_first_run_interactive_skip_mentions_llm_api_key(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_template = tmp_path / ".env.template"
    env_template.write_text(
        '# LLM_API_KEY="sk-your-api-key-here"\nDEEPSEEK_API_KEY=""\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(first_run, "ENV_FILE", env_file)
    monkeypatch.setattr(first_run, "ENV_TEMPLATE", env_template)
    monkeypatch.setattr(first_run.sys, "stdin", _InteractiveStdin())
    monkeypatch.setattr("builtins.input", lambda _: "")

    first_run.ensure_env()

    out = capsys.readouterr().out
    assert "set LLM_API_KEY before using LLM features" in out
    assert "DEEPSEEK_API_KEY or LLM_API_KEY" not in out
