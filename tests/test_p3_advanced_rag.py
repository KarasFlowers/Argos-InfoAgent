"""Tests for the memory_service module."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Unit tests for _build_rag_prompt with history + memory
# ---------------------------------------------------------------------------


class TestBuildRagPromptWithHistory:
    def test_no_history_no_memory(self):
        from app.services.rag._core import _build_rag_prompt

        result = _build_rag_prompt("What is AI?", ["AI is artificial intelligence."])
        assert "【原文相关段落】" in result
        assert "【对话历史】" not in result
        assert "【关于用户的已知信息】" not in result

    def test_with_history(self):
        from app.services.rag._core import _build_rag_prompt

        history = [
            {"role": "user", "content": "What is machine learning?"},
            {"role": "ai", "content": "Machine learning is a subset of AI."},
        ]
        result = _build_rag_prompt("Tell me more", ["ML uses data to learn."], history=history)
        assert "【对话历史】" in result
        assert "用户: What is machine learning?" in result
        assert "助手: Machine learning is a subset of AI." in result

    def test_history_capped_at_six(self):
        from app.services.rag._core import _build_rag_prompt

        history = [{"role": "user", "content": f"Q{i}"} for i in range(10)]
        result = _build_rag_prompt("Next", ["Chunk."], history=history)
        # Should only include last 6 messages
        assert "Q0" not in result
        assert "Q4" in result
        assert "Q9" in result

    def test_with_memory_context(self):
        from app.services.rag._core import _build_rag_prompt

        result = _build_rag_prompt(
            "What is RAG?",
            ["RAG is retrieval-augmented generation."],
            memory_context="preferred_language: 中文；last_research_topic: RAG 技术",
        )
        assert "【关于用户的已知信息】" in result
        assert "preferred_language: 中文" in result

    def test_with_history_and_memory(self):
        from app.services.rag._core import _build_rag_prompt

        history = [{"role": "user", "content": "Hello"}]
        result = _build_rag_prompt(
            "Hi again",
            ["Chunk."],
            history=history,
            memory_context="role: CS student",
        )
        assert "【对话历史】" in result
        assert "【关于用户的已知信息】" in result


# ---------------------------------------------------------------------------
# Unit tests for semantic_split
# ---------------------------------------------------------------------------


class TestSemanticSplit:
    def test_empty_text(self):
        from app.services.rag._core import semantic_split

        assert semantic_split("") == []
        assert semantic_split("   ") == []

    def test_short_text_single_chunk(self):
        from app.services.rag._core import semantic_split

        text = "This is a short paragraph."
        chunks = semantic_split(text, max_chars=800)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_heading_creates_new_chunk(self):
        from app.services.rag._core import semantic_split

        text = "Introduction text here.\n\n## Methods\n\nWe used the following methods."
        chunks = semantic_split(text, max_chars=800)
        # Heading should cause a split
        assert len(chunks) == 2
        assert "Introduction" in chunks[0]
        assert "Methods" in chunks[1]

    def test_multiple_paragraphs_grouped(self):
        from app.services.rag._core import semantic_split

        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = semantic_split(text, max_chars=800)
        # All should be grouped into one chunk since they fit
        assert len(chunks) == 1

    def test_max_chars_respected(self):
        from app.services.rag._core import semantic_split

        # Create text that exceeds max_chars
        text = "A" * 500 + "\n\n" + "B" * 500
        chunks = semantic_split(text, max_chars=600)
        # Overlap may cause slight exceedance; allow 20% margin
        assert all(len(c) <= 720 for c in chunks)
        assert len(chunks) >= 2

    def test_oversized_paragraph_fallback(self):
        from app.services.rag._core import semantic_split

        # Single paragraph with no sentence boundaries that exceeds max_chars
        text = "A" * 1000
        chunks = semantic_split(text, max_chars=600)
        # Should fall back to sentence splitting (which splits on 。！？.!?)
        # Since there are no sentence boundaries, it'll be one oversized chunk
        # but the fallback will try split_into_chunks
        assert len(chunks) >= 1

    def test_horizontal_rule_boundary(self):
        from app.services.rag._core import semantic_split

        text = "First section.\n\n---\n\nSecond section."
        chunks = semantic_split(text, max_chars=800)
        assert len(chunks) == 2

    def test_preserves_content(self):
        from app.services.rag._core import semantic_split

        text = "First paragraph with important info.\n\nSecond paragraph with more details."
        chunks = semantic_split(text, max_chars=800)
        full = " ".join(chunks)
        assert "First paragraph" in full
        assert "Second paragraph" in full


class TestArticleFetchBounds:
    def test_bounded_response_text_accepts_normal_html(self):
        from app.services.rag._core import _bounded_response_text

        response = httpx.Response(200, content=b"<html><p>Hello</p></html>")

        assert _bounded_response_text(response, url="https://example.com/a") == "<html><p>Hello</p></html>"

    def test_bounded_response_text_rejects_large_html(self):
        from app.services.rag._core import MAX_ARTICLE_HTML_BYTES, _bounded_response_text

        response = httpx.Response(200, content=b"x" * (MAX_ARTICLE_HTML_BYTES + 1))

        with pytest.raises(ValueError, match="too large"):
            _bounded_response_text(response, url="https://example.com/a")

    @pytest.mark.asyncio
    async def test_fetch_article_text_blocks_trailing_dot_localhost_before_fetch(self, monkeypatch):
        from app.services.rag import _core

        class FailingClient:
            def __init__(self, *args, **kwargs):
                raise AssertionError("HTTP client should not be created for unsafe URLs")

        _core._article_text_cache.pop("http://localhost./article", None)
        _core._article_text_tasks.pop("http://localhost./article", None)
        monkeypatch.setattr(_core.httpx, "AsyncClient", FailingClient)

        with pytest.raises(ValueError, match="blocklist"):
            await _core.fetch_article_text("http://localhost./article")


# ---------------------------------------------------------------------------
# Unit tests for memory_service
# ---------------------------------------------------------------------------


class TestMemoryService:
    @pytest.mark.asyncio
    async def test_save_and_get_memory(self):
        with patch("app.services.memory_service.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            from app.services.memory_service import save_memory

            # Mock: no existing entry
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = None
            mock_session.execute.return_value = mock_result

            await save_memory("test_key", "test_value", category="fact", source="auto")

            # Verify session.add was called
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_memory_context_empty(self):
        with patch("app.services.memory_service.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute.return_value = mock_result

            from app.services.memory_service import build_memory_context

            result = await build_memory_context()
            assert result == ""

    @pytest.mark.asyncio
    async def test_build_memory_context_with_entries(self):
        from app.models.domain import UserMemory

        with patch("app.services.memory_service.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            mem1 = UserMemory(key="lang", value="中文", category="preference", source="auto")
            mem2 = UserMemory(key="topic", value="RAG", category="fact", source="auto")
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mem1, mem2]
            mock_session.execute.return_value = mock_result

            from app.services.memory_service import build_memory_context

            result = await build_memory_context()
            assert "lang: 中文" in result
            assert "topic: RAG" in result
            assert "；" in result

    @pytest.mark.asyncio
    async def test_delete_memory(self):
        from app.models.domain import UserMemory

        with patch("app.services.memory_service.AsyncSessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            existing = UserMemory(key="test", value="val", category="fact", source="auto")
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = existing
            mock_session.execute.return_value = mock_result

            from app.services.memory_service import delete_memory

            result = await delete_memory("test")
            assert result is True
            assert existing.is_active is False


# ---------------------------------------------------------------------------
# Unit tests for cross-article prompt builder
# ---------------------------------------------------------------------------


class TestCrossArticlePrompt:
    def test_includes_source_url(self):
        from app.services.rag._core import _build_cross_article_prompt

        chunks = [
            {"chunk": "AI is transforming industries.", "source_url": "https://example.com/article1"},
            {"chunk": "ML models require data.", "source_url": "https://example.com/article2"},
        ]
        result = _build_cross_article_prompt("What is AI?", chunks)
        assert "多篇文章" in result
        assert "example.com" in result
        assert "[1]" in result
        assert "[2]" in result
