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
    assert "if (await shouldBlockSummaryGenerationForMissingLlm(url))" in js
    assert "function showLlmMissingState" in js
    assert "未配置 LLM API Key" in js
    assert "LLM_API_KEY 或 DEEPSEEK_API_KEY" in js
    assert "label: '打开设置'" in js
    assert "retryButton.textContent = options.retryLabel || '重试';" in js
    assert "throw new Error(await readResponseError(response, '读取简报失败'))" in js
    assert "showLlmMissingState(() => fetchSummary())" in js
    assert "setSummaryFeedback(`刷新简报失败：" in js
    assert "当前仍显示上次成功生成的内容。" in js
    assert "setSummaryFeedback('');" in js
    assert ".summary-feedback" in css
    assert ".summary-feedback.is-error" in css
    assert ".error-message__actions" in css
    assert ".retry-btn--secondary" in css


def test_summary_bootstrap_validates_board_before_board_scoped_requests():
    js = APP_JS.read_text(encoding="utf-8")

    init_pos = js.index("await initBoards();")
    catchup_pos = js.index("_refreshCatchupBadge();")
    saved_pos = js.index("loadSavedState();")
    summary_pos = js.index("fetchSummary();")

    assert init_pos < catchup_pos < summary_pos
    assert init_pos < saved_pos < summary_pos
    assert "_primeBoardSlugFromStorage();" not in js
    assert "localStorage.removeItem('argos_board')" in js


def test_summary_run_status_ui_fetches_board_scoped_task_runs():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="summary-run-status" class="summary-run-status" role="status" aria-live="polite"' in html
    assert "async function fetchSummaryRunStatus()" in js
    assert "/api/v1/admin/tasks?kind=summary_generation&board_id=" in js
    assert "renderSummaryRunStatus(latest);" in js
    assert "window.setInterval(fetchSummaryRunStatus, 2500)" in js
    assert "if (currentBoardSlug) {" in js
    assert "url += `&board=${encodeURIComponent(currentBoardSlug)}`;" in js
    assert "fetchSummaryWithUrl(url, '正在重新生成简报...');" in js
    assert ".summary-run-status.is-running" in css
    assert ".summary-run-status.is-done" in css
    assert ".summary-run-status.is-failed" in css


def test_summary_default_fetch_uses_lite_mode():
    js = APP_JS.read_text(encoding="utf-8")

    assert "if (!force && !date) params.push('lite=true');" in js
