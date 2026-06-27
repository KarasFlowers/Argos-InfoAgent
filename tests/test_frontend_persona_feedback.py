from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_persona_panel_surfaces_load_and_delete_failures():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert 'id="persona-feedback"' in html
    assert 'class="persona-feedback" role="status" aria-live="polite"' in html
    assert "function setPersonaFeedback(message, type = 'info')" in js
    assert "setPersonaFeedback(`读取偏好失败：" in js
    assert "throw new Error(await readResponseError(response, '请求失败'))" in js
    assert "return false;" in js
    assert "removePersona(persona.id, removeButton)" in js
    assert "if (removeButton) removeButton.disabled = true;" in js
    assert "const reloaded = await loadPersonaData();" in js
    assert "if (reloaded) setPersonaFeedback('已删除偏好。', 'success');" in js
    assert "setPersonaFeedback(`删除偏好失败：" in js
    assert ".persona-feedback--success" in css
    assert ".persona-feedback--error" in css


def test_persona_training_load_failure_is_visible():
    js = APP_JS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(response, '读取训练面板失败'))" in js
    assert "训练面板读取失败：${escapeHtml(error.message)}" in js
    assert "setPersonaFeedback(`训练面板读取失败：" in js


def test_explicit_preference_tags_surface_failures_and_successes():
    js = APP_JS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(res, '读取显式偏好失败'))" in js
    assert "setPersonaFeedback(`读取显式偏好失败：" in js
    assert "deletePrefTag(item.id, button)" in js
    assert "if (button) button.disabled = true;" in js
    assert "throw new Error(await readResponseError(res, '添加偏好失败'))" in js
    assert "setPersonaFeedback('偏好已添加。', 'success')" in js
    assert "setPersonaFeedback(`添加偏好失败：" in js
    assert "async function deletePrefTag(id, button = null)" in js
    assert "throw new Error(await readResponseError(res, '删除偏好失败'))" in js
    assert "setPersonaFeedback('偏好已删除。', 'success')" in js
    assert "setPersonaFeedback(`删除偏好失败：" in js


def test_preference_suggestions_surface_load_failures():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(res, '读取来源建议失败'))" in js
    assert "throw new Error(await readResponseError(res, '读取话题建议失败'))" in js
    assert "suggestionErrors.push(`来源建议读取失败：" in js
    assert "suggestionErrors.push(`话题建议读取失败：" in js
    assert "function renderSuggestionWarnings(messages)" in js
    assert "setPersonaFeedback(`${suggestionErrors.join('；')}。你仍可手动添加偏好。`, 'info')" in js
    assert "pref-suggestion-warning" in js
    assert ".persona-feedback--info" in css
    assert ".pref-suggestion-warning" in css


def test_interest_reason_popup_surfaces_backend_option_errors():
    js = APP_JS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(res, '偏好选项生成失败'))" in js
    assert "error.message !== '偏好选项生成失败'" in js
    assert "服务器未返回具体原因" in js
    assert "showInterestPopupError(popup, `偏好选项生成失败：" in js
    assert "可稍后在偏好面板手动添加。" in js
