from pathlib import Path

APP_JS = Path("app/web/static/app.js")


def test_history_and_weekly_errors_show_backend_detail():
    js = APP_JS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(response, '周刊生成失败'))" in js
    assert "const weeklyInsight = (data.weekly_insight || '').trim();" in js
    assert "throw new Error('周刊生成完成，但没有返回可展示内容。')" in js
    assert "content.innerHTML = renderMarkdownSafe(weeklyInsight);" in js
    assert "err.textContent = `周刊生成失败：${error.message}`" in js
    assert "} finally {" in js
    assert "genBtn.disabled = false;" in js
    assert "重新生成本周深度汇总" in js
    assert "throw new Error(await readResponseError(response, '读取历史记录失败'))" in js
    assert "function renderMagazineRecapError(message)" in js
    assert "周刊概览加载失败：${escapeHtml(message)}" in js
    assert "if (target === 'magazine')" in js
    assert "err.textContent = `历史记录加载失败：${error.message}`" in js


def test_rag_errors_use_readable_backend_detail():
    js = APP_JS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(response, '详细概要生成失败，但你仍可继续提问。'))" in js
    assert "throw new Error(await readResponseError(historyRes, '读取追问历史失败'))" in js
    assert "appendMessage('system', `追问历史读取失败：" in js
    assert "throw new Error(await readResponseError(statusRes, '索引状态读取失败'))" in js
    assert "appendMessage('system', `索引状态读取失败：" in js
    assert "throw new Error(await readResponseError(response, '文章索引失败，请检查该链接是否可访问。'))" in js
    assert "const message = await readResponseError(response, '请求失败');" in js
    assert "setAiMessageText(aiMessage, `提问失败：${message}`)" in js
    assert "setAiMessageText(aiMessage, `连接中断：${error.message}`)" in js
