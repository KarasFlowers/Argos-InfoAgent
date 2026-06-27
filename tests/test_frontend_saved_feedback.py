from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")


def test_saved_action_failures_are_visible_and_revert_state():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(res, '保存状态失败'))" in js
    assert "throw new Error(await readResponseError(res, '读取收藏状态失败'))" in js
    assert "let savedStateLoadError = '';" in js
    assert "savedStateLoadError = e.message || '读取收藏状态失败';" in js
    assert "syncVisibleSavedButtons();" in js
    assert "showFeedbackInlineMessage(buttonElement, `收藏状态可能未同步：" in js
    assert "function renderSavedStateWarning(container)" in js
    assert "retryButton.textContent = '重新同步'" in js
    assert "function syncVisibleSavedButtons()" in js
    assert "throw new Error(await readResponseError(response, '反馈提交失败'))" in js
    assert "showFeedbackInlineMessage(buttonElement, `反馈提交失败：" in js
    assert "throw new Error(await readResponseError(r, '偏好保存失败'))" in js
    assert "showInterestPopupError(popup, `保存失败：" in js
    assert "function showInterestPopupError" in js
    assert "throw new Error(await readResponseError(res, '读取收藏列表失败'))" in js
    assert "error.className = 'saved-placeholder saved-placeholder--error'" in js
    assert "retryButton.textContent = '重试'" in js
    assert "retryButton.addEventListener('click', () => renderSavedList(status))" in js
    assert "error.setAttribute('role', 'alert')" in js
    assert "buttonElement.classList.toggle('active', isActive)" in js
    assert "showFeedbackInlineMessage(buttonElement, `保存状态失败：" in js
    assert "function showFeedbackInlineMessage" in js
    assert "throw new Error(await readResponseError(res, '移除失败'))" in js
    assert "showSavedItemFeedback(row, `移除失败：" in js
    assert "function showSavedItemFeedback" in js
    assert "messageEl.setAttribute('role', type === 'error' ? 'alert' : 'status')" in js
    assert ".feedback-inline-message" in css
    assert ".feedback-inline-message.is-info" in css
    assert ".interest-popup__error" in css
    assert ".saved-state-warning" in css
    assert ".saved-state-warning__retry" in css
    assert ".saved-item__error" in css
    assert ".saved-placeholder--error" in css
    assert ".saved-retry-btn" in css
