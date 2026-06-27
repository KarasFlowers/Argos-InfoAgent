from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_system_metrics_refresh_has_user_visible_failure_feedback():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert 'id="metrics-status" class="metrics-status" role="status" aria-live="polite"' in html
    assert "function setMetricsStatus(message, type = 'info')" in js
    assert "setMetricsStatus('正在刷新系统消耗...')" in js
    assert "throw new Error(await readResponseError(response, '读取系统消耗失败'))" in js
    assert "setMetricsStatus(`系统消耗读取失败：${e.message}`, 'error')" in js
    assert ".metrics-status.is-error" in css
