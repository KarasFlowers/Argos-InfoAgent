from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_operator_status_endpoint_is_documented():
    for path in [
        "README.md",
        "README_zh.md",
        "DEVELOPMENT.md",
        "docs/structure.md",
        "docs/introduction.md",
    ]:
        text = _read(path)
        assert "/api/v1/status" in text or "`/status`" in text


def test_docs_directory_is_not_gitignored():
    gitignore = _read(".gitignore")

    assert "\ndocs/\n" not in f"\n{gitignore}\n"


def test_security_restore_docs_promote_dry_run_before_force():
    security = _read("SECURITY.md")

    assert "--dry-run" in security
    assert "--force" in security
    assert security.index("--dry-run") < security.index("--force")


def test_industrialization_audit_records_docker_smoke_boundary():
    audit = _read("docs/INDUSTRIALIZATION_AUDIT.md")

    assert "git diff check" in audit
    assert "accept the correct key" in audit
    assert "Blocked by environment" in audit
    assert "python scripts/check_release.py --with-docker-smoke" in audit


def test_docs_keep_private_single_user_scope():
    readme = _read("README.md")
    readme_zh = _read("README_zh.md")
    security = _read("SECURITY.md")
    introduction = _read("docs/introduction.md")
    roadmap = _read("docs/后续方向.txt")
    interview_qa = _read("docs/interview-qa.md")

    assert "private single-user/self-hosted app" in readme
    assert "私有单用户/自托管应用" in readme_zh
    assert "private single-user or small self-hosted deployments" in security
    assert "保持私有单用户/小型自托管定位" in introduction
    assert "不把登录、多用户或租户隔离作为当前路线" in roadmap
    assert "多用户系统与权限管理" not in introduction
    assert "简单多用户" not in roadmap
    assert "多租户架构" not in interview_qa


def test_docs_use_versioned_admin_paths():
    structure = _read("docs/structure.md")

    assert "/api/v1/admin/*" in structure
    assert "(/admin/*)" not in structure


def test_docs_match_url_safety_fake_ip_policy():
    introduction = _read("docs/introduction.md")

    assert "198.18.0.0/15 Fake IP 的放行" in introduction
    assert "阻止 198.18.0.0/15" not in introduction


def test_security_docs_mention_external_response_size_limits():
    security = _read("SECURITY.md")

    assert "RSS feed responses" in security
    assert "RAG article HTML" in security
    assert "size limits" in security


def test_docs_match_llm_base_url_fallback_policy():
    readme = _read("README.md")
    readme_zh = _read("README_zh.md")
    structure = _read("docs/structure.md")
    introduction = _read("docs/introduction.md")

    assert "Required when using generic `LLM_API_KEY`" in readme
    assert "使用通用 `LLM_API_KEY` 时需要显式设置" in readme_zh
    assert "set explicitly with generic `LLM_API_KEY`" in structure
    assert "使用通用 `LLM_API_KEY` 时需显式设置" in introduction


def test_docs_describe_wildcard_cors_credentials_boundary():
    for path in ["README.md", "README_zh.md", "DEVELOPMENT.md", "docs/structure.md", "docs/introduction.md"]:
        text = _read(path)
        assert "CORS_ORIGINS" in text
        assert "credentialed CORS" in text
        assert "*" in text


def test_docs_describe_options_preflight_auth_boundary():
    for path in ["README.md", "README_zh.md", "DEVELOPMENT.md", "SECURITY.md", ".env.template"]:
        text = _read(path)
        assert "OPTIONS" in text
        assert "CORS" in text


def test_core_docs_do_not_advertise_unimplemented_notification_channels():
    unsupported_markers = ["WEBHOOK_URL", "WEBHOOK_SECRET", "BARK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    for path in ["README.md", "README_zh.md", "docs/introduction.md"]:
        text = _read(path)
        assert "NOTIFY_CHANNELS" in text
        assert "email" in text
        for marker in unsupported_markers:
            assert marker not in text


def test_contributing_uses_release_gate():
    contributing = _read("CONTRIBUTING.md")

    assert "python scripts/check_release.py" in contributing
    assert "python scripts/check_release.py --with-docker-smoke" in contributing
    assert "pytest tests/" not in contributing
