from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")
INDEX_HTML = Path("app/web/templates/index.html")


def test_board_order_drag_save_has_visible_feedback_and_recovery():
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert 'id="board-tabs-feedback" class="board-tabs-feedback" role="status" aria-live="polite"' in html
    assert "function setBoardTabsFeedback(message, type = 'info')" in js
    assert "setBoardTabsFeedback('正在保存板块顺序...')" in js
    assert "throw new Error(await readResponseError(response, '保存板块顺序失败'))" in js
    assert "setBoardTabsFeedback('板块顺序已保存。', 'success')" in js
    assert "setBoardTabsFeedback(`板块顺序保存失败，已恢复服务器顺序：" in js
    assert "await initBoards();" in js
    assert ".board-tabs-feedback.is-success" in css
    assert ".board-tabs-feedback.is-error" in css


def test_board_initial_load_failure_is_visible():
    js = APP_JS.read_text(encoding="utf-8")

    assert "throw new Error(await readResponseError(res, '读取板块失败'))" in js
    assert "availableBoards = [];" in js
    assert "setBoardTabsFeedback(`板块加载失败：" in js
