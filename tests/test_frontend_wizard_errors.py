from pathlib import Path

APP_JS = Path("app/web/static/app.js")


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
