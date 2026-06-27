from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_header_promotes_main_path_and_moves_tools_to_menu():
    html = (ROOT / "app/web/templates/index.html").read_text(encoding="utf-8")

    assert 'id="saved-btn"' in html
    assert 'id="more-btn"' in html
    assert "工具" in html
    assert 'id="api-key-btn" class="more-menu-item"' in html
    assert 'id="stats-btn"' not in html


def test_news_cards_render_recommendation_reason_and_question_chips():
    js = (ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/web/static/index.css").read_text(encoding="utf-8")

    assert "recommendation_reason" in js
    assert "preference_matches" in js
    assert "assistant_questions" in js
    assert "recommendation-reason" in css
    assert "assistant-question-chip" in css


def test_rag_panel_has_suggested_questions_and_citation_basis_label():
    js = (ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/web/static/index.css").read_text(encoding="utf-8")

    assert "renderRagQuestionSuggestions" in js
    assert "maybeRunInitialRagQuestion" in js
    assert "回答依据" in js
    assert "rag-suggestion-chip" in css
