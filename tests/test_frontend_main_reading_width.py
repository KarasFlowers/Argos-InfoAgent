from pathlib import Path

INDEX_CSS = Path("app/web/static/index.css")


def test_main_news_reading_area_stays_narrower_than_app_shell():
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert "main,\n.overview-section,\n.source-analysis-section" in css
    assert "max-width: 760px;" in css
