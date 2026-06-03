"""
RAG Service: Two-Stage Retrieval Pipeline for Conversational Deep Dive

Pipeline:
  1. Ingest: scrape URL → clean text → split into chunks → embed with Bi-Encoder → store in ChromaDB
  2. Query:  embed question → top-20 recall → Cross-Encoder Rerank → keep top-3 → DeepSeek query
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime, UTC
from typing import AsyncGenerator, Optional
from urllib.parse import urljoin

import httpx
import trafilatura
from bs4 import BeautifulSoup
import numpy as np
from app.core.config import settings
from app.core.url_safety import ensure_public_url_target
from app.core.db import AsyncSessionLocal
from app.models.domain import ArticleOverview
from sqlalchemy.future import select

# All mutable state and model loaders live in _state.py
from app.services.rag._state import (  # noqa: F401
    is_rag_available,
    _require_rag,
    get_bi_encoder,
    get_cross_encoder,
    init_chroma,
    prewarm_models,
    _get_chroma_client,
    _BoundedLRU,
    _ingested_urls,
    _bm25_indices,
    _article_text_cache,
    _article_text_tasks,
    _article_overview_cache,
    _article_quality_cache,
    _ingest_queue,
    _ingest_status,
    _content_fallback,
)

logger = logging.getLogger(__name__)


def enqueue_for_ingest(
    urls: list[str],
    fallback_contents: dict[str, str] | None = None,
) -> int:
    """
    Enqueue URLs for background ingestion.  Skips URLs that are already
    ingested or already queued.  Returns the number of newly enqueued URLs.

    ``fallback_contents`` is an optional mapping of URL -> pre-fetched text
    (e.g. body + comments from HN/Reddit scrapers).  When the online
    trafilatura extraction yields too little content, this text is used
    instead so that rich comment context is still searchable via RAG.
    """
    if fallback_contents:
        _content_fallback.update(fallback_contents)

    enqueued = 0
    for url in urls:
        if url in _ingested_urls:
            continue
        if url in _ingest_status and _ingest_status[url]["status"] in ("pending", "running"):
            continue
        _ingest_status[url] = {"status": "pending", "chunks": 0, "error": None}
        try:
            _ingest_queue.put_nowait(url)
            enqueued += 1
        except asyncio.QueueFull:
            logger.warning("Background ingest queue full, dropping %s", url)
            _ingest_status.pop(url, None)
    if enqueued:
        logger.info("Enqueued %d URLs for background ingestion", enqueued)
    return enqueued


def get_ingest_status(url: str) -> dict | None:
    """Return the ingestion status dict for *url*, or None if unknown."""
    if url in _ingested_urls:
        try:
            coll = _get_chroma_client().get_collection(_ingested_urls[url])
            chunks = coll.count()
        except Exception:
            chunks = 0
        return {"status": "done", "chunks": chunks, "error": None}
    return _ingest_status.get(url)


async def ingest_worker_loop(worker_id: int = 0) -> None:
    """
    Long-running coroutine that pulls URLs from the queue and ingests them.
    Send ``None`` into the queue to gracefully shut down.
    """
    logger.info("Background ingest worker-%d started", worker_id)
    while True:
        url = await _ingest_queue.get()
        if url is None:
            # Shutdown sentinel
            _ingest_queue.task_done()
            logger.info("Background ingest worker-%d shutting down", worker_id)
            return
        try:
            _ingest_status[url] = {"status": "running", "chunks": 0, "error": None}
            result = await ingest(url)
            _ingest_status[url] = {
                "status": "done",
                "chunks": result["chunks"],
                "error": None,
            }
            logger.info("Background ingested %s (%d chunks)", url, result["chunks"])
        except Exception as exc:
            logger.warning("Background ingest failed for %s: %s", url, exc)
            _ingest_status[url] = {
                "status": "failed",
                "chunks": 0,
                "error": str(exc),
            }
        finally:
            _ingest_queue.task_done()


def _build_bm25_index(chunks: list[str]) -> tuple:
    from rank_bm25 import BM25Okapi
    tokenized = [chunk.lower().split() for chunk in chunks]
    return BM25Okapi(tokenized), chunks


def _load_collection_chunks(url: str) -> list[str]:
    collection_name = _ingested_urls.get(url)
    if not collection_name:
        return []

    collection = _get_chroma_client().get_collection(collection_name)
    payload = collection.get(include=["documents"])
    documents = payload.get("documents") or []
    return [doc for doc in documents if isinstance(doc, str) and doc.strip()]


def _ensure_bm25_index(url: str) -> tuple | None:
    existing = _bm25_indices.get(url)
    if existing:
        return existing

    chunks = _load_collection_chunks(url)
    if not chunks:
        return None

    index = _build_bm25_index(chunks)
    _bm25_indices[url] = index
    return index


# -------------------------------------------------------------------
# Step 1: Web Scraping
# -------------------------------------------------------------------

async def fetch_article_text(url: str) -> str:
    """
    Fetch the raw article content and extract the main body text.
    Uses trafilatura for high-precision extraction, falls back to BeautifulSoup.
    """
    cached_text = _article_text_cache.get(url)
    if cached_text:
        return cached_text

    existing_task = _article_text_tasks.get(url)
    if existing_task:
        return await existing_task

    async def _fetch_and_extract() -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.google.com/",
        }

        current_url = await ensure_public_url_target(url)
        redirect_limit = 5

        try:
            async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=False) as client:
                for _ in range(redirect_limit + 1):
                    response = await client.get(current_url)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("Redirect target is missing.")
                        current_url = await ensure_public_url_target(urljoin(str(response.url), location))
                        continue

                    response.raise_for_status()
                    html_content = response.text
                    logger.info("Successfully fetched article HTML (len=%d) from %s", len(html_content), current_url)
                    break
                else:
                    raise ValueError("Too many redirects while fetching article.")
        except ValueError:
            raise
        except Exception:
            logger.exception("Error fetching article URL %s", url)
            raise

        text = await asyncio.to_thread(
            trafilatura.extract,
            html_content,
            include_comments=False,
            include_tables=True,
            no_fallback=False
        )

        if text and len(text) > 300:
            return text

        soup = BeautifulSoup(html_content, "html.parser")

        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()

        paragraphs = soup.find_all("p")
        text = "\n".join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)

        if len(text) < 200:
            text = soup.get_text(separator="\n", strip=True)

        if not text or len(text) < 100:
            logger.warning("Scraping failed for %s. Trafilatura and BeautifulSoup both returned insufficient content.", url)
            return ""

        logger.info("Successfully extracted text (len=%d) for %s", len(text), url)
        return text

    task = asyncio.create_task(_fetch_and_extract())
    _article_text_tasks[url] = task

    try:
        text = await task
        _article_text_cache[url] = text
        return text
    finally:
        if _article_text_tasks.get(url) is task:
            _article_text_tasks.pop(url, None)


# -------------------------------------------------------------------
# Step 1.5: Content Quality Assessment
# -------------------------------------------------------------------

_NOISE_PATTERNS = re.compile(
    r"(subscribe|newsletter|cookie|广告|关注我们|点击关注|免费试用|"
    r"sign\s*up|log\s*in|privacy\s*policy|terms\s*of\s*service|"
    r"accept\s*cookies|unsubscribe|share\s*this)",
    re.IGNORECASE,
)


def assess_content_quality(text: str) -> dict:
    """
    Evaluate the quality of extracted article text.

    Returns:
        {
            "score": 0.0~1.0,
            "verdict": "good" | "partial" | "poor",
            "details": human-readable explanation
        }
    """
    if not text or not text.strip():
        return {"score": 0.0, "verdict": "poor", "details": "未能提取到任何文本内容"}

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    total_lines = len(lines)
    if total_lines == 0:
        return {"score": 0.0, "verdict": "poor", "details": "未能提取到任何文本内容"}

    # Factor 1: Paragraph density — meaningful lines (>30 chars) vs total
    meaningful_lines = [line for line in lines if len(line) > 30]
    density = len(meaningful_lines) / total_lines if total_lines > 0 else 0

    # Factor 2: Noise word ratio
    noise_hits = len(_NOISE_PATTERNS.findall(text))
    noise_ratio = min(noise_hits / max(total_lines, 1), 1.0)

    # Factor 3: Overall text length adequacy
    text_length = len(text)
    length_score = min(text_length / 1500, 1.0)  # 1500 chars = fully adequate

    # Weighted composite score
    score = (density * 0.45) + ((1 - noise_ratio) * 0.25) + (length_score * 0.30)
    score = round(max(0.0, min(1.0, score)), 2)

    # Determine verdict
    if score >= 0.65:
        verdict = "good"
        details = ""
    elif score >= 0.40:
        verdict = "partial"
        issues = []
        if density < 0.5:
            issues.append("有效段落占比偏低")
        if noise_ratio > 0.15:
            issues.append("检测到较多广告/导航噪声")
        if text_length < 800:
            issues.append("提取文本偏短")
        details = "；".join(issues) if issues else "内容质量中等"
    else:
        verdict = "poor"
        issues = []
        if density < 0.3:
            issues.append("大量碎片化短文本")
        if noise_ratio > 0.25:
            issues.append("噪声内容过多")
        if text_length < 400:
            issues.append("提取内容极少")
        details = "；".join(issues) if issues else "内容提取质量很差"

    return {"score": score, "verdict": verdict, "details": details}


# -------------------------------------------------------------------
# Step 2: Text Chunking
# -------------------------------------------------------------------

def split_into_chunks(text: str, max_chars: int = 600, overlap_chars: int = 100) -> list[str]:
    """
    Split text into overlapping chunks.
    Each chunk is at most `max_chars` long, with `overlap_chars` of carried-over context.
    """
    # Split on sentence boundaries first
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(current_chunk) + len(sentence) <= max_chars:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # Start new chunk with overlap from the end of the last chunk
            current_chunk = current_chunk[-overlap_chars:] + sentence + " "

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


# Regex to detect semantic boundaries (markdown headings, horizontal rules)
_HEADING_RE = re.compile(r"^(#{1,4}\s.+|---+|\*\*\*+)", re.MULTILINE)


def semantic_split(text: str, max_chars: int = 800, overlap_chars: int = 120) -> list[str]:
    """
    Split text into chunks that respect semantic boundaries (headings, paragraphs).

    Algorithm:
    1. Split into paragraphs by double-newline or heading markers.
    2. Group adjacent paragraphs until exceeding max_chars or hitting a heading.
    3. For very long single paragraphs, fall back to sentence-based splitting.
    """
    if not text or not text.strip():
        return []

    # Step 1: Split into paragraphs
    # Split on double-newline sequences, keeping heading lines as separate paragraphs
    raw_paragraphs = re.split(r"\n{2,}", text.strip())

    paragraphs = []
    for para in raw_paragraphs:
        para = para.strip()
        if not para:
            continue
        # If a paragraph contains multiple heading lines, split them out
        lines = para.split("\n")
        current_sub = []
        for line in lines:
            if _HEADING_RE.match(line.strip()):
                if current_sub:
                    paragraphs.append("\n".join(current_sub))
                    current_sub = []
                paragraphs.append(line)
            else:
                current_sub.append(line)
        if current_sub:
            paragraphs.append("\n".join(current_sub))

    if not paragraphs:
        return [text.strip()[:max_chars]]

    # Step 2: Group paragraphs into chunks
    chunks = []
    current_chunk = ""

    for para in paragraphs:
        is_heading = _HEADING_RE.match(para.strip())

        # If current chunk + this paragraph exceeds max_chars, flush
        if current_chunk and len(current_chunk) + len(para) + 2 > max_chars:
            chunks.append(current_chunk.strip())
            # Start new chunk with overlap
            if overlap_chars > 0 and len(current_chunk) > overlap_chars:
                current_chunk = current_chunk[-overlap_chars:] + "\n\n" + para
            else:
                current_chunk = para
        # If this is a heading and we already have content, start a new chunk
        # (headings should begin a new topic section)
        elif is_heading and current_chunk:
            chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk.strip())

    # Step 3: For any chunk still exceeding max_chars, fall back to sentence splitting
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
        else:
            # Use the existing sentence-based splitter for oversized chunks
            final_chunks.extend(split_into_chunks(chunk, max_chars, overlap_chars))

    return final_chunks


def _select_overview_chunks(chunks: list[str]) -> list[str]:
    """Pick a small but representative set of chunks for a fast article overview."""
    if len(chunks) <= 7:
        return chunks

    middle = len(chunks) // 2
    indices = [0, 1, 2, max(0, middle - 1), middle, len(chunks) - 2, len(chunks) - 1]
    selected = []
    seen = set()

    for index in indices:
        if 0 <= index < len(chunks) and index not in seen:
            selected.append(chunks[index])
            seen.add(index)

    return selected


def _build_article_overview_prompt(context: str) -> str:
    return f"""你是一个帮助用户快速理解技术文章的助手。请仅根据给定原文内容，用中文生成一份“比首页卡片更详细、但远短于原文”的阅读概要。

要求：
1. 先写 `**核心概要**`：用 2-3 句话概括这篇文章真正讲了什么。
2. 再写 `**关键细节**`：提供 4-6 条项目符号，尽量覆盖机制、数据、背景、争议、限制或影响。
3. 最后写 `**值得继续追问**`：给出 2-3 条很短的问题方向，帮助用户继续提问。
4. 不要编造原文没有的信息；如果信息不足，直接说明。
5. 使用简洁 markdown，总体保持紧凑、易扫读。

原文内容：
{context}
"""


def _get_overview_context_from_chunks(chunks: list[str]) -> str:
    return "\n\n---\n\n".join(_select_overview_chunks(chunks))


async def _prepare_overview_context(url: str) -> str:
    if url in _bm25_indices:
        _, chunks = _bm25_indices[url]
    else:
        article_text = await fetch_article_text(url)
        cleaned_text = (article_text or "").strip()
        if len(cleaned_text) < 300:
            raise ValueError(f"Extracted content for '{url}' is too short ({len(cleaned_text)} characters). The article might be behind a paywall or cookie wall.")
        chunks = await asyncio.to_thread(semantic_split, cleaned_text, 900, 120)

    context = _get_overview_context_from_chunks(chunks)
    if not context:
        raise ValueError("Could not extract enough article content.")
    return context


async def stream_article_overview(url: str) -> AsyncGenerator[str, None]:
    """Stream a fast, richer article overview for the RAG side panel."""
    cached = _article_overview_cache.get(url)
    if cached:
        yield cached
        return

    context = await _prepare_overview_context(url)

    from app.services.llm_service import llm_service
    from app.services.metrics_service import metrics_service

    stream = await llm_service.llm.chat_stream(
        messages=[{"role": "user", "content": _build_article_overview_prompt(context)}],
        max_tokens=700,
        temperature=0.3,
    )

    full_response = ""
    async for chunk in stream:
        if chunk.usage:
            await metrics_service.record_tokens(
                chunk.usage.prompt_tokens, 
                chunk.usage.completion_tokens
            )
            continue
            
        if chunk.choices and chunk.choices[0].delta.content:
            delta = chunk.choices[0].delta.content
            full_response += delta
            yield delta

    if not full_response:
        raise RuntimeError("Failed to generate article overview.")

    _article_overview_cache[url] = full_response
    await _save_overview_to_db(url, full_response)


async def _save_overview_to_db(url: str, text: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(ArticleOverview).where(ArticleOverview.article_url == url)
            result = await session.execute(stmt)
            existing = result.scalars().first()
            if existing:
                existing.overview_text = text
            else:
                session.add(ArticleOverview(article_url=url, overview_text=text))
            await session.commit()
    except Exception:
        logger.debug("Failed to persist overview to DB", exc_info=True)


async def get_db_cached_overview(url: str) -> str | None:
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(ArticleOverview).where(ArticleOverview.article_url == url)
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row:
                _article_overview_cache[url] = row.overview_text
                return row.overview_text
    except Exception:
        logger.debug("DB overview lookup failed", exc_info=True)
    return None


async def generate_article_overview(url: str) -> str:
    """Generate a fast, richer article overview for the RAG side panel."""
    parts = []
    async for token in stream_article_overview(url):
        parts.append(token)
    return "".join(parts)


# -------------------------------------------------------------------
# Step 3: Embed & Store in ChromaDB
# -------------------------------------------------------------------

def _collection_name_for(url: str) -> str:
    """Generate a safe collection name from a URL."""
    # ChromaDB collection names must be alphanumeric + hyphens, 3-63 chars
    safe = re.sub(r"[^a-zA-Z0-9]", "-", url)[-52:]
    safe = safe.strip("-")
    return f"rag-m3-{safe}"


async def ingest(url: str) -> dict:
    """
    Ingest a URL into the RAG pipeline.
    Returns {"chunks": int, "quality": dict}.
    If already ingested this session, returns cached data.
    """
    cached_quality = _article_quality_cache.get(url, {"score": 1.0, "verdict": "good", "details": ""})

    if url in _ingested_urls:
        coll = _get_chroma_client().get_collection(_ingested_urls[url])
        return {"chunks": coll.count(), "quality": cached_quality}
    
    # Fetch and chunk in thread (CPU-bound)
    text = await fetch_article_text(url)

    # If online extraction yielded too little content, try the fallback
    # (pre-fetched body + comments from HN/Reddit scraper).
    fallback = _content_fallback.pop(url, None)
    if (not text or len(text) < 300) and fallback:
        logger.info("Using content fallback for %s (online text too short: %d chars)", url, len(text or ""))
        text = fallback

    # Assess content quality before chunking
    quality = await asyncio.to_thread(assess_content_quality, text)
    _article_quality_cache[url] = quality

    chunks = await asyncio.to_thread(semantic_split, text)
    
    if not chunks:
        return {"chunks": 0, "quality": quality}
    
    # Generate embeddings
    bi_encoder = get_bi_encoder()
    embeddings = await asyncio.to_thread(bi_encoder.encode, chunks, show_progress_bar=False)
    
    # Store in ChromaDB
    collection_name = _collection_name_for(url)
    # Delete old collection if it exists
    try:
        _get_chroma_client().delete_collection(collection_name)
    except Exception:
        pass
    
    collection = _get_chroma_client().create_collection(
        name=collection_name, 
        metadata={"url": url, "ingested_at": datetime.now(UTC).isoformat()}
    )
    collection.add(
        ids=[str(uuid.uuid4()) for _ in chunks],
        documents=chunks,
        embeddings=embeddings.tolist(),
    )

    _ingested_urls[url] = collection_name
    _bm25_indices[url] = _build_bm25_index(chunks)
    
    return {"chunks": len(chunks), "quality": quality}


async def delete_collections_by_urls(urls: list[str]) -> int:
    """
    Remove ChromaDB collections and BM25 indices for the provided URLs.
    Returns the count of successfully deleted collections.
    """
    deleted_count = 0
    for url in urls:
        collection_name = _collection_name_for(url)
        try:
            # Remove from ChromaDB
            _get_chroma_client().delete_collection(collection_name)
            # Clear local tracking caches
            _ingested_urls.pop(url, None)
            _bm25_indices.pop(url, None)
            _article_text_cache.pop(url, None)
            _article_overview_cache.pop(url, None)
            deleted_count += 1
        except Exception:
            # Collection might not exist or already deleted; treat as no-op but log at debug.
            logger.debug("Collection for %s not deleted (missing or already removed)", url)

    logger.info("Cleanup deleted %s RAG collections from ChromaDB", deleted_count)
    return deleted_count


# -------------------------------------------------------------------
# Retrieval pipeline (delegated to _retrieval.py)
# -------------------------------------------------------------------
# Re-export for backward compatibility — existing imports via _core still work.
from app.services.rag._retrieval import (  # noqa: F401
    query_stream,
    query_cross_article,
    _build_rag_prompt,
    _build_cross_article_prompt,
)
