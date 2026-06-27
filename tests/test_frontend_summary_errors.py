from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_summary_fetch_uses_response_detail_for_error_state():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="summary-feedback" class="summary-feedback" role="status" aria-live="polite"' in html
    assert "function setSummaryFeedback(message, type = 'info')" in js
    assert "const loadingMessage = date" in js
    assert "正在加载 ${formatSummaryDate(date)} 的简报..." in js
    assert "await fetchSummaryWithUrl(url, loadingMessage);" in js
    assert "async function fetchSummaryWithUrl(url, retainedContentMessage = '正在刷新简报...')" in js
    assert "setSummaryFeedback(retainedContentMessage, 'info');" in js
    assert "throw new Error(await readResponseError(response, '读取简报失败'))" in js
    assert "showErrorState(error.message, () => fetchSummary())" in js
    assert "setSummaryFeedback(`刷新简报失败：" in js
    assert "当前仍显示上次成功生成的内容。" in js
    assert "setSummaryFeedback('');" in js
    assert ".summary-feedback" in css
    assert ".summary-feedback.is-error" in css
