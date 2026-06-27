from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_source_management_uses_inline_feedback_instead_of_alerts():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "alert(" not in js
    assert "function setSourceManagementFeedback" in js
    assert "setSourceManagementFeedback('请先输入 RSS 源 URL。', 'error')" in js
    assert "setSourceManagementFeedback('RSS 源 URL 必须以 http:// 或 https:// 开头。', 'error')" in js
    assert "if (!isSafeHttpUrlString(url))" in js
    assert "setSourceManagementFeedback('此信息源已存在。', 'error')" in js
    assert "setSourceManagementFeedback('信息源已添加。', 'ok')" in js
    assert "setSourceManagementFeedback('信息源已删除。', 'ok')" in js
    assert "setSourceManagementFeedback(`添加失败：" in js
    assert "setSourceManagementFeedback(`删除失败：" in js
    assert "setSourceManagementFeedback(`更新可信度失败：" in js
    assert "document.getElementById('source-add-btn')" in js
    assert "addButton.textContent = '添加中...';" in js
    assert "addButton.textContent = '+ 添加';" in js
    assert js.count("throw new Error(await readResponseError(res, '测试信息源失败'))") == 2
    assert "throw new Error(await readResponseError(res, '测试全部信息源失败'))" in js
    assert "setSourceManagementFeedback('全部信息源测试完成。', 'ok')" in js
    assert "setSourceManagementFeedback(`测试全部信息源失败：" in js
    assert "addDiscoveredSource(button.dataset.sourceUrl || '', button)" in js
    assert "button.textContent = '添加中...'" in js
    assert "button.textContent = '添加到当前板块'" in js
    assert "applySourceAlternative(Number(button.dataset.sourceId), button.dataset.sourceUrl || '', button)" in js
    assert "button.textContent = '应用中...'" in js
    assert "button.textContent = '采用这个'" in js
    assert "dashboardError = await readResponseError(dashboardRes, '来源仪表盘读取失败')" in js
    assert "来源仪表盘读取失败：${escapeHtml(dashboardError)}" in js
    assert "badgeEl.className = 'sources-silent-mode-badge is-error'" in js
    assert "runBtn.textContent = '运行中...'" in js
    assert "runBtn.textContent = '立即运行'" in js
    assert "testExistingFeed(statusKey, url, testBtn)" in js
    assert "button.textContent = '测试中...'" in js
    assert "button.textContent = '测试';" in js
    assert "document.getElementById('sources-discover-btn')" in js
    assert "button.textContent = '发现中...';" in js
    assert "button.textContent = '智能发现';" in js
    assert ".sources-silent-mode-badge.is-error" in css
    assert ".sources-silent-mode-actions button:disabled" in css
    assert ".sources-replacement-apply-btn:disabled" in css
    assert ".source-feed-test-btn:disabled" in css
    assert ".sources-test-btn:disabled" in css
    assert ".sources-add-btn:disabled" in css
    assert "resultEl.setAttribute('role', type === 'error' ? 'alert' : 'status')" in js
    assert "resultEl.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite')" in js


def test_source_feedback_region_is_announced_to_assistive_tech():
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="source-test-result" class="source-test-result" role="status" aria-live="polite"' in html
    assert 'id="source-add-btn"' in html
    assert 'id="sources-discover-btn"' in html
