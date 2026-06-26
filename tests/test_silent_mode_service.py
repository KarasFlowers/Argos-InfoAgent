from __future__ import annotations

from pathlib import Path

import pytest

from app.models.domain import Board
from app.models.schemas import DailySummaryResponse, SummaryItem
from app.services import silent_mode_service as sms


def _board() -> Board:
    return Board(slug="tech", name="科技快讯", source_type="rss", source_config={"feeds": []})


def _summary() -> DailySummaryResponse:
    return DailySummaryResponse(
        date="2026-06-25",
        overview="今天的科技新闻摘要。",
        perspective="overview",
        top_news=[
            SummaryItem(
                headline="AI 新进展",
                category="AI",
                key_points=["模型更新", "性能提升"],
                tags=["ai", "llm"],
                topic_path="AI/LLM",
                original_link="https://example.com/a",
                source="Example",
            )
        ],
        events=[
            {
                "cluster_id": 1,
                "title": "模型升级",
                "summary": "围绕新模型发布形成的事件。",
                "item_count": 2,
                "latest_date": "2026-06-25",
                "sources": ["Example"],
                "items": [{"headline": "AI 新进展"}],
            }
        ],
        source_stats={"Example": 1},
        recommendation_report={"quality": "high"},
        catchup_news=[],
        source_analysis={},
    )


def test_idle_helpers():
    assert sms.is_idle_enough(None, 300) is False
    assert sms.is_idle_enough(10, 300) is False
    assert sms.is_idle_enough(300, 300) is True


def test_render_summary_markdown_contains_sections():
    md = sms.render_summary_markdown(_summary(), _board())
    assert md.startswith("---\n")
    assert 'board: "tech"' in md
    assert "article_count: 1" in md
    assert "silent-mode" in md
    assert "# 科技快讯 · 2026-06-25" in md
    assert "## 概览" in md
    assert "## 事件聚合" in md
    assert "## 今日重点" in md
    assert "AI 新进展" in md


def test_export_summary_markdown_writes_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sms.settings, "SILENT_MODE_OUTPUT_DIR", str(tmp_path))
    target = sms.export_summary_markdown(_summary(), _board(), output_dir=tmp_path)
    assert target.exists()
    assert target.suffix == ".md"
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "# 科技快讯" in text


def test_build_silent_mode_path_is_sanitized(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sms.settings, "SILENT_MODE_OUTPUT_DIR", str(tmp_path))
    path = sms.build_silent_mode_path("te/ch?*:", "2026-06-25", "ov/er")
    assert "te_ch" in path.name
    assert path.suffix == ".md"


def test_manifest_entries_are_jsonl(tmp_path: Path):
    first = {"ok": True, "generated_at": "2026-06-25T00:00:00+00:00", "results": []}
    second = {"ok": False, "reason": "pc_not_idle_enough", "results": []}

    manifest = sms.append_manifest_entry(first, output_dir=tmp_path)
    sms.append_manifest_entry(second, output_dir=tmp_path)

    assert manifest.name == "manifest.jsonl"
    entries = sms.read_manifest_entries(limit=10, output_dir=tmp_path)
    assert entries == [first, second]
    assert sms.get_latest_manifest_entry(output_dir=tmp_path) == second
