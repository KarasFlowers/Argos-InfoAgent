import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path("app/web/static/app.js")
INDEX_HTML = Path("app/web/templates/index.html")
INDEX_CSS = Path("app/web/static/index.css")


def test_dashboard_has_settings_entrypoint_and_cache_bump():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="settings-btn"' in html
    assert "toggleSettingsPanel()" in html
    assert 'id="settings-api-key-input"' in html
    assert 'id="settings-api-key-save" class="primary-btn" onclick="saveApiKeyFromSettings()">保存</button>' in html
    assert "/static/app.js?v=62" in html
    assert "/static/index.css?v=54" in html


def test_frontend_fetch_wrapper_adds_api_key_only_to_same_origin_api_requests():
    js = APP_JS.read_text(encoding="utf-8")

    assert "const API_KEY_STORAGE_KEY = 'argos_api_key';" in js
    assert "const API_KEY_HEADER = 'X-API-Key';" in js
    assert "window.fetch = async function argosAuthenticatedFetch" in js
    assert "url.origin === window.location.origin && url.pathname.startsWith('/api/')" in js
    assert "headers.set(API_KEY_HEADER, apiKey)" in js
    assert "response.status === 403 && _isArgosApiRequest(input)" in js
    assert "showApiKeyRequired()" in js
    assert "event.key === 'Enter'" in js
    assert "saveApiKeyFromDialog()" in js
    assert 'id="api-key-message" class="api-key-message" role="status" aria-live="polite"' in js
    assert "messageEl.setAttribute('role', 'alert')" in js
    assert "messageEl.setAttribute('role', 'status')" in js
    assert "async function saveApiKeyFromDialog()" in js
    assert "async function saveApiKeyFromSettings()" in js
    assert "API Key 已保存，后续请求会自动使用。" in js
    assert "_nativeFetch('/api/v1/status'" in js
    assert "[API_KEY_HEADER]: value" in js
    assert "API Key 未通过验证" in js
    assert "无法验证 API Key" in js
    assert "input.select()" in js
    assert "input.type = 'password'" in js
    assert "toggleApiKeyVisibility()" in js
    assert "api-key-toggle" in js
    assert "toggle.textContent = '显示'" in js
    assert "当前保存的 API Key 未通过验证" in js
    assert "服务器需要 API Key" in js


def test_frontend_api_key_modal_has_required_styles():
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert ".api-key-modal-content" in css
    assert ".api-key-input-row:focus-within" in css
    assert ".api-key-toggle" in css
    assert "#settings-btn.has-api-key" in css


def test_frontend_auth_smoke_script_passes():
    if shutil.which("node") is None:
        pytest.skip("Node.js is not available")

    subprocess.run(["node", "scripts/frontend_auth_smoke.js"], check=True)
