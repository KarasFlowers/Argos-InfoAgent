from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_board_wizard_uses_response_detail_for_user_visible_errors():
    js = APP_JS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(res, '板块向导请求失败'))" in js
    assert "throw new Error(await readResponseError(res, '读取 Prompt 模板失败'))" in js
    assert "setBoardFormFeedback('error', `Prompt 模板读取失败：" in js
    assert "throw new Error(await readResponseError(res, '预览抓取失败'))" in js
    assert "throw new Error(await readResponseError(res, '替代源获取失败'))" in js
    assert "throw new Error(await readResponseError(res, 'Prompt 预览失败'))" in js
    assert "appendWizardMsg('ai', `❌ 预览失败：${e.message}`)" in js
    assert "appendWizardMsg('ai', `⚠️ 替代源获取失败：${e.message}" in js


def test_response_error_reader_falls_back_to_plain_text_body():
    js = APP_JS.read_text(encoding="utf-8")

    assert "const text = await response.text();" in js
    assert "const data = JSON.parse(text);" in js
    assert "const text = await response.text();" in js
    assert "return data?.detail || data?.message || text.trim();" in js
    assert "return text.trim();" in js


def test_board_wizard_shows_progress_while_ai_is_working():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "const WIZARD_PROGRESS_STEPS = [" in js
    assert "理解你的需求" in js
    assert "拆解筛选规则" in js
    assert "查找可用信息源" in js
    assert "整理模板配置" in js
    assert "做最后校验" in js
    assert "function startWizardProgressMessage(messageEl)" in js
    assert "function clearWizardProgressMessage()" in js
    assert "startWizardProgressMessage(loadingMsg)" in js
    assert "messageEl.setAttribute('role', 'status')" in js
    assert ".wizard-msg--progress" in css
    assert ".wizard-progress__spinner" in css
    assert "@keyframes wizard-progress-spin" in css


def test_board_wizard_renders_clickable_clarification_options():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="wizard-form"' in html
    assert "function renderWizardClarification(clarification)" in js
    assert "function submitWizardClarification(value)" in js
    assert "renderWizardClarification(data.clarification)" in js
    assert "wizard-clarification-option" in js
    assert "也可以直接在输入框里写你的自定义标准。" in js
    assert ".wizard-clarification-options" in css
    assert ".wizard-clarification-option__desc" in css
