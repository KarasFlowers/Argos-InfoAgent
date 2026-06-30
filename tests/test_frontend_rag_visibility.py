from pathlib import Path

APP_JS = Path("app/web/static/app.js")
INDEX_CSS = Path("app/web/static/index.css")


def test_rag_entrypoints_are_gated_by_runtime_availability():
    js = APP_JS.read_text(encoding="utf-8")
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "let ragFeatureAvailable = false;" in js
    assert "async function loadRagAvailability()" in js
    assert "await ragAvailabilityPromise;" in js
    assert "if (ragFeatureAvailable) {" in js
    assert "askButton.appendChild(document.createTextNode('深度追问'));" in js
    assert "ragFeatureAvailable && Array.isArray(newsItem.assistant_questions)" in js
    assert "if (!ragFeatureAvailable)" in js
    assert "body.rag-disabled .rag-panel" in css
