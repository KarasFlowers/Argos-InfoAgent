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
    assert "currentBtn.textContent = '运行当前板块'" in js
    assert "allBtn.textContent = '运行全部板块'" in js
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


def test_board_template_and_silent_mode_controls_are_easy_to_reach():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert 'class="board-template-panel"' in html
    assert 'id="board-template-description"' in html
    assert html.index('id="board-template-description"') < html.index('id="board-prompt-preview"')
    assert html.index('id="board-prompt-preview"') < html.index('id="board-advanced-settings"')
    assert "function updatePromptTemplateDescription" in js
    assert "需求模板示例:" in html
    assert 'id="board-template-goal"' in html
    assert 'id="board-template-focus"' in html
    assert 'id="board-template-rules"' in html
    assert "function buildTemplateProfileFromForm" in js
    assert "template_profile: buildTemplateProfileFromForm()" in js
    assert "applyTemplateProfileToForm(board.template_profile || {})" in js
    assert "需求处理方案" in js
    assert "模板配置会作为长期需求处理方案影响筛选和输出。" in js
    assert "board-template-preview-btn" in js
    assert "container.scrollIntoView({ behavior: 'smooth', block: 'nearest' })" in js
    assert "board-prompt-preview__body" in js
    assert ".board-template-description" in css
    assert ".board-template-preview-btn" in css
    assert ".board-prompt-preview__body" in css

    assert 'id="silent-mode-run-current"' in html
    assert 'id="silent-mode-run-all"' in html
    assert "runSilentModeNow('current')" in html
    assert "runSilentModeNow('all')" in html
    assert "payload.board_slugs = [currentBoard.slug]" in js
    assert "本次只运行当前板块" in js
    assert "运行全部板块" in js
    assert "overflow-wrap: anywhere" in css


def test_source_discovery_result_summarizes_quality_stats():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "data?.localized_summary || data?.summary" in js
    assert "const statItems = [" in js
    assert "stats.candidate_count" in js
    assert "stats.verified_count" in js
    assert "stats.selected_count ?? suggestions.length" in js
    assert "sources-discovery-stats" in js
    assert ".sources-discovery-stats" in css
    assert ".sources-discovery-stats strong" in css
