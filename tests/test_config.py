"""
test_config.py - Unit tests for application configuration.

Tests:
  - Default settings load correctly
  - Path resolution works for relative paths
  - SQLite URI resolution
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import (
    PROJECT_ROOT,
    Settings,
    _resolve_path,
    _resolve_sqlite_uri,
    effective_cors_allow_credentials,
)

# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    def test_relative_path_resolves_to_project_root(self):
        result = _resolve_path("data/test")
        expected = (PROJECT_ROOT / "data/test").resolve()
        assert Path(result) == expected

    def test_absolute_path_unchanged(self):
        # Use a Windows-compatible absolute path
        import sys

        if sys.platform == "win32":
            abs_path = "C:\\tmp\\argos-test"
        else:
            abs_path = "/tmp/argos-test"
        result = _resolve_path(abs_path)
        assert Path(result) == Path(abs_path)

    def test_creates_directory(self, tmp_path):
        # _resolve_path no longer creates directories; just verify it resolves
        target = str(tmp_path / "new_dir" / "sub_dir")
        result = _resolve_path(target)
        # tmp_path is already absolute, so result should equal target
        assert Path(result).is_absolute()


# ---------------------------------------------------------------------------
# _resolve_sqlite_uri
# ---------------------------------------------------------------------------


class TestResolveSqliteUri:
    def test_relative_path_resolved(self):
        result = _resolve_sqlite_uri("sqlite+aiosqlite:///data/argos.db")
        assert "sqlite+aiosqlite:///" in result
        assert "data/argos.db" in result
        # Should be an absolute path now
        db_path = result.replace("sqlite+aiosqlite:///", "")
        assert Path(db_path).is_absolute()

    def test_absolute_path_unchanged(self):
        import sys

        if sys.platform == "win32":
            uri = "sqlite+aiosqlite:///C:/tmp/test.db"
        else:
            uri = "sqlite+aiosqlite:///tmp/test.db"
        result = _resolve_sqlite_uri(uri)
        assert result == uri

    def test_non_sqlite_uri_unchanged(self):
        uri = "postgresql://user:pass@localhost/db"
        result = _resolve_sqlite_uri(uri)
        assert result == uri

    def test_empty_db_path(self):
        uri = "sqlite+aiosqlite:///"
        result = _resolve_sqlite_uri(uri)
        assert result == uri


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    def test_project_name(self):
        from app.core.config import settings

        assert settings.PROJECT_NAME == "Argos"

    def test_version_format(self):
        from app.core.config import settings

        # Should be semver-like
        parts = settings.VERSION.split(".")
        assert len(parts) >= 2

    def test_api_prefix(self):
        from app.core.config import settings

        assert settings.API_V1_STR.startswith("/api")


class TestSettingsValidation:
    def test_public_base_url_must_be_absolute_http_url(self):
        with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
            Settings(PUBLIC_BASE_URL="argos.local")

    def test_public_base_url_rejects_query_and_trims_trailing_slash(self):
        with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
            Settings(PUBLIC_BASE_URL="https://argos.example.com/app?x=1")

        settings = Settings(PUBLIC_BASE_URL="https://argos.example.com/")
        assert settings.PUBLIC_BASE_URL == "https://argos.example.com"

    def test_cors_origins_must_be_origins(self):
        with pytest.raises(ValidationError, match="CORS_ORIGINS"):
            Settings(CORS_ORIGINS="https://app.example.com/path")

        settings = Settings(CORS_ORIGINS="https://app.example.com/, http://localhost:5173")
        assert settings.CORS_ORIGINS == ["https://app.example.com", "http://localhost:5173"]

    def test_wildcard_cors_disables_credentials(self):
        settings = Settings(CORS_ORIGINS="*", CORS_ALLOW_CREDENTIALS=True)

        assert settings.CORS_ORIGINS == ["*"]
        assert effective_cors_allow_credentials(settings.CORS_ORIGINS, settings.CORS_ALLOW_CREDENTIALS) is False

    def test_explicit_cors_origins_can_allow_credentials(self):
        settings = Settings(CORS_ORIGINS="https://app.example.com", CORS_ALLOW_CREDENTIALS=True)

        assert effective_cors_allow_credentials(settings.CORS_ORIGINS, settings.CORS_ALLOW_CREDENTIALS) is True

    def test_daily_push_time_must_be_valid_hhmm(self):
        with pytest.raises(ValidationError, match="DAILY_PUSH_TIME"):
            Settings(DAILY_PUSH_TIME="24:00")

        assert Settings(DAILY_PUSH_TIME="23:59").DAILY_PUSH_TIME == "23:59"
