from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_insights_views_use_response_detail_for_error_states():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")

    assert 'id="entity-search-btn"' in html
    assert "throw new Error(await readResponseError(res, '读取话题热度失败'))" in js
    assert "if (daysSelect) daysSelect.disabled = true;" in js
    assert "if (daysSelect) daysSelect.disabled = wasDaysSelectDisabled;" in js
    assert "#heatmap-days:disabled" in css
    assert "throw new Error(await readResponseError(res, '搜索实体时间线失败'))" in js
    assert "请输入要搜索的实体名称。" in js
    assert "input.focus();" in js
    assert "button.textContent = '搜索中...';" in js
    assert "button.textContent = '搜索';" in js
    assert ".entity-search-bar button:disabled" in css
    assert "加载失败: ${escapeHtml(e.message)}" in js
    assert "搜索失败: ${escapeHtml(e.message)}" in js
