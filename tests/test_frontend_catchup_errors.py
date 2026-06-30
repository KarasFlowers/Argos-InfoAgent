from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_catchup_status_and_digest_errors_are_user_visible():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(resp, '读取未读状态失败'))" in js
    assert "检查未读状态失败：${escapeHtml(error.message)}" in js
    assert "function showCatchupBadgeError(badge, message)" in js
    assert "badge.textContent = '!';" in js
    assert "badge.title = `补读状态读取失败：" in js
    assert "function clearCatchupBadgeError(badge)" in js
    assert ".catchup-badge.is-error" in css
    assert "throw new Error(await readResponseError(resp, '生成补读失败'))" in js
    assert "await _loadCatchupStatus();" in js
    assert "await _refreshCatchupBadge();" in js
    assert "生成失败：${escapeHtml(error.message)}" in js


def test_catchup_config_save_failure_is_visible_and_reverts():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert 'id="catchup-config-status" class="catchup-config-status" role="status" aria-live="polite"' in html
    assert 'id="settings-modal"' in html
    assert 'id="catchup-auto-chk"' in html
    assert "function setCatchupConfigStatus(message, type = 'info')" in js
    assert "throw new Error(await readResponseError(resp, '读取补读设置失败'))" in js
    assert "setCatchupConfigStatus('正在保存补读设置...')" in js
    assert "throw new Error(await readResponseError(response, '保存补读设置失败'))" in js
    assert "setCatchupConfigStatus('补读设置已保存。', 'success')" in js
    assert "setCatchupConfigStatus(`补读设置保存失败，已恢复服务器设置：" in js
    assert "await _loadCatchupConfig();" in js
    assert ".catchup-config-status.is-error" in css
