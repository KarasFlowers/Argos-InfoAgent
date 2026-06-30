from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_HTML = Path("app/web/templates/index.html")


def test_tools_menu_is_simplified_to_settings_entrypoint():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert "toggleHistoryPanel(); closeMoreMenu();" in html
    assert "toggleMagazinePanel(); closeMoreMenu();" in html
    assert "toggleCatchupPanel(); closeMoreMenu();" in html
    assert "toggleStatsPanel(); closeMoreMenu();" in html
    assert "toggleSourcesPanel(); closeMoreMenu();" in html
    assert "toggleSettingsPanel(); closeMoreMenu();" in html
    assert "toggleSilentModePanel(); closeMoreMenu();" not in html
    assert "toggleRuntimeSettingsPanel(); closeMoreMenu();" not in html
    assert "openApiKeyDialog(); closeMoreMenu();" not in html


def test_sources_modal_no_longer_contains_silent_mode_card():
    html = INDEX_HTML.read_text(encoding="utf-8")
    sources_modal = html.split('<div id="sources-modal"', 1)[1].split('<div id="coverage-modal"', 1)[0]

    assert 'id="silent-mode-card"' not in sources_modal
    assert "静默模式" not in sources_modal


def test_settings_panel_contains_runtime_automation_and_access_key_sections():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")

    assert 'id="settings-modal"' in html
    assert 'id="settings-runtime-grid"' in html
    assert 'id="catchup-auto-chk"' in html
    assert 'id="weekly-auto-report-enabled"' in html
    assert 'id="weekly-auto-report-day"' in html
    assert 'id="weekly-auto-report-time"' in html
    assert 'id="settings-api-key-input"' in html
    assert 'id="silent-mode-card"' in html
    assert "fetch('/api/v1/settings/automation')" in js
    assert "saveWeeklyAutoReportSettings" in js
