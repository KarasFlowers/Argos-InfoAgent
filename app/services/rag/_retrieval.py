"""
RAG Retrieval Pipeline: HyDE rewriting, hybrid recall, cross-encoder reranking,
personalization, and streaming LLM query.

Extracted from ``_core.py`` to separate the retrieval / query logic from
the ingestion / content-processing pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import numpy as np

from app.core.config import settings
from app.services.rag._state import (
    _get_chroma_client,
    _ingested_urls,
    get_bi_encoder,
    get_cross_encoder,
)

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# HyDE (Hypothetical Document Embedding) query rewriting
# -------------------------------------------------------------------


async def _hyde_rewrite(question: str) -> str:
    """
    HyDE: ask the LLM to generate a short hypothetical answer.
    This answer will be embedded alongside the original query to
    improve semantic recall for vague or short questions.
    """
    prompt = "请直接给出一段简短的假设性回答（50-100 字），不要加前缀或解释：\n\n" f"问题：{question}"
    try:
        from app.services.llm_service import llm_service

        resp = await llm_service.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )

        hyde_text = (resp.choices[0].message.content or "").strip()
        if hyde_text:
            logger.debug("HyDE hypothesis: %s", hyde_text[:80])
            return hyde_text
    except Exception:
        logger.warning("HyDE rewrite failed, falling back to raw query", exc_info=True)
    return ""


# -------------------------------------------------------------------
# Single-article retrieval (Recall + Rerank)
# -------------------------------------------------------------------


async def _recall_and_rerank(question: str, url: str, top_k_recall: int = 20, top_k_final: int = 3) -> list[dict]:
    """
    Hybrid Retrieval Pipeline:
    Path A: Bi-Encoder vector recall (semantic)
    Path B: BM25 keyword recall
    Fusion: Reciprocal Rank Fusion (RRF)
    Rerank: Cross-Encoder on fused candidates
    Personalization: positive feedback bonus + negative feedback penalty
    """
    from app.services.rag._core import _ensure_bm25_index

    collection_name = _ingested_urls.get(url)
    if not collection_name:
        return []

    collection = _get_chroma_client().get_collection(collection_name)

    # --- PATH A: Bi-Encoder (Vector) Recall ---
    bi_encoder = get_bi_encoder()

    # HyDE: fuse original query embedding with hypothetical-answer embedding
    if settings.RAG_HYDE_ENABLED:
        hyde_text = await _hyde_rewrite(question)
        if hyde_text:
            raw_embs = await asyncio.to_thread(bi_encoder.encode, [question, hyde_text], show_progress_bar=False)
            q_embedding = ((raw_embs[0] + raw_embs[1]) / 2).tolist()
        else:
            q_embedding = (await asyncio.to_thread(bi_encoder.encode, [question], show_progress_bar=False))[0].tolist()
    else:
        q_embedding = bi_encoder.encode(question).tolist()

    vector_results = collection.query(
        query_embeddings=[q_embedding],
        n_results=min(top_k_recall, collection.count()),
        include=["documents", "embeddings"],
    )
    vector_chunks = vector_results["documents"][0]  # ordered by vector similarity
    vector_embeddings = vector_results["embeddings"][0]

    # --- PATH B: BM25 (Keyword) Recall ---
    bm25_chunks = []
    bm25_state = _ensure_bm25_index(url)
    if bm25_state:
        bm25_index, all_chunks = bm25_state
        tokenized_query = question.lower().split()
        bm25_scores = bm25_index.get_scores(tokenized_query)
        ranked_indices = np.argsort(bm25_scores)[::-1][:top_k_recall]
        bm25_chunks = [all_chunks[i] for i in ranked_indices]

    # --- FUSION: Reciprocal Rank Fusion (RRF) ---
    # k=60 is a standard constant that dampens the impact of very high ranks
    k = 60
    rrf_scores: dict[str, float] = {}
    chunk_to_source: dict[str, str] = {}

    for rank, chunk in enumerate(vector_chunks):
        key = chunk[:100]  # use prefix as stable key
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (k + rank + 1)
        # Prefer semantic if already from BM25, otherwise set as semantic
        chunk_to_source[key] = chunk_to_source.get(key, "semantic")

    for rank, chunk in enumerate(bm25_chunks):
        key = chunk[:100]
        rrf_scores[key] = rrf_scores.get(key, 0) + 1 / (k + rank + 1)
        # If it came from both paths, label as hybrid
        if key in chunk_to_source:
            chunk_to_source[key] = "hybrid"
        else:
            chunk_to_source[key] = "keyword"

    # Build a merged list of unique chunks, sorted by RRF score desc
    # Map key back to full chunk text
    all_source_chunks = vector_chunks + [c for c in bm25_chunks if c[:100] not in {v[:100] for v in vector_chunks}]

    scored_chunks = sorted(all_source_chunks, key=lambda c: rrf_scores.get(c[:100], 0), reverse=True)

    # Take top candidates for Cross-Encoder reranking
    candidate_chunks = scored_chunks[:top_k_recall]

    # Build embedding lookup for personalization bonus
    # For vector-recalled chunks we already have embeddings;
    # for BM25-only chunks we encode on the fly
    vector_chunk_set = set(c[:100] for c in vector_chunks)
    chunk_embeddings: dict[str, list] = {c[:100]: emb for c, emb in zip(vector_chunks, vector_embeddings, strict=False)}
    bm25_only = [c for c in candidate_chunks if c[:100] not in vector_chunk_set]
    if bm25_only:
        bm25_embs = await asyncio.to_thread(bi_encoder.encode, bm25_only, show_progress_bar=False)
        for c, emb in zip(bm25_only, bm25_embs, strict=False):
            chunk_embeddings[c[:100]] = emb.tolist()

    # --- Cross-Encoder Reranking ---
    cross_encoder = get_cross_encoder()
    pairs = [[question, chunk] for chunk in candidate_chunks]
    scores = await asyncio.to_thread(cross_encoder.predict, pairs)

    # --- Personalization: positive bonus + negative penalty ---
    from app.services.learning_service import get_user_feedback_profiles

    positive_centroid, negative_centroid = await get_user_feedback_profiles()

    final_scores = []
    for _i, (score, chunk) in enumerate(zip(scores, candidate_chunks, strict=False)):
        bonus = 0.0
        penalty = 0.0
        if positive_centroid is not None or negative_centroid is not None:
            chunk_emb = chunk_embeddings.get(chunk[:100])
            if chunk_emb is not None:
                chunk_emb_np = np.array(chunk_emb)
                norm = np.linalg.norm(chunk_emb_np)
                if norm > 0:
                    chunk_emb_np = chunk_emb_np / norm
                if positive_centroid is not None:
                    similarity_pos = np.dot(positive_centroid, chunk_emb_np)
                    bonus = max(0, similarity_pos) * 3.0
                if negative_centroid is not None:
                    similarity_neg = np.dot(negative_centroid, chunk_emb_np)
                    penalty = max(0, similarity_neg) * 2.0

        total_score = float(score) + bonus - penalty
        source = chunk_to_source.get(chunk[:100], "semantic")

        final_scores.append(
            {
                "chunk": chunk,
                "cross_score": round(float(score), 2),
                "bonus": round(bonus, 2),
                "penalty": round(penalty, 2),
                "total": round(total_score, 2),
                "source": source,  # "semantic" | "keyword" | "hybrid"
            }
        )

    # Sort by total blended score descending
    ranked = sorted(final_scores, key=lambda x: x["total"], reverse=True)
    return ranked[:top_k_final]


# -------------------------------------------------------------------
# Cross-Article Retrieval
# -------------------------------------------------------------------


async def _recall_and_rerank_cross_article(
    question: str,
    top_k_per_collection: int = 5,
    max_collections: int = 20,
    top_k_final: int = 5,
) -> list[dict]:
    """
    Cross-article hybrid retrieval: query all ingested ChromaDB collections,
    fuse results with RRF, then Cross-Encoder rerank + personalization.

    Returns list of dicts with chunk, cross_score, bonus, penalty, total,
    source, and source_url (the originating article URL).
    """
    from app.services.rag._core import _ensure_bm25_index

    if not _ingested_urls:
        return []

    bi_encoder = get_bi_encoder()

    # Embed question (with optional HyDE)
    if settings.RAG_HYDE_ENABLED:
        hyde_text = await _hyde_rewrite(question)
        if hyde_text:
            raw_embs = await asyncio.to_thread(bi_encoder.encode, [question, hyde_text], show_progress_bar=False)
            q_embedding = ((raw_embs[0] + raw_embs[1]) / 2).tolist()
        else:
            q_embedding = (await asyncio.to_thread(bi_encoder.encode, [question], show_progress_bar=False))[0].tolist()
    else:
        q_embedding = bi_encoder.encode(question).tolist()

    # --- Phase 1: Vector recall from each collection ---
    k = 60  # RRF constant
    rrf_scores: dict[str, float] = {}
    chunk_to_source_url: dict[str, str] = {}
    chunk_to_retrieval: dict[str, str] = {}  # "semantic" | "keyword"
    all_chunks_by_key: dict[str, str] = {}  # key -> full chunk text
    chunk_embeddings: dict[str, list] = {}

    # Cap collections to avoid O(n) blowup
    items = list(_ingested_urls.items())[:max_collections]

    # Precompute time-boost per collection (based on ingested_at metadata)
    collection_time_boost: dict[str, float] = {}
    now = datetime.now(UTC)
    for url, collection_name in items:
        try:
            coll_obj = _get_chroma_client().get_collection(collection_name)
            meta = getattr(coll_obj, "metadata", None) or {}
            ingested_at_str = meta.get("ingested_at", "")
            if ingested_at_str:
                try:
                    ingested_at = datetime.fromisoformat(ingested_at_str)
                    days_old = max(0, (now - ingested_at).days)
                    # Exponential decay: half-life ~10 days, mild boost
                    collection_time_boost[url] = 1.0 + float(np.exp(-days_old / 14.0))
                except (ValueError, TypeError):
                    collection_time_boost[url] = 1.5  # neutral fallback
            else:
                collection_time_boost[url] = 1.5  # legacy collections without timestamp
        except Exception:
            collection_time_boost[url] = 1.0

    for url, collection_name in items:
        try:
            collection = _get_chroma_client().get_collection(collection_name)
            count = collection.count()
            if count == 0:
                continue

            n_results = min(top_k_per_collection, count)
            results = collection.query(
                query_embeddings=[q_embedding],
                n_results=n_results,
                include=["documents", "embeddings"],
            )
            docs = results["documents"][0]
            embs = results["embeddings"][0]

            for rank, (doc, emb) in enumerate(zip(docs, embs, strict=False)):
                key = doc[:100]
                time_boost = collection_time_boost.get(url, 1.0)
                rrf_scores[key] = rrf_scores.get(key, 0) + (1 / (k + rank + 1)) * time_boost
                chunk_to_source_url[key] = url
                chunk_to_retrieval[key] = chunk_to_retrieval.get(key, "semantic")
                all_chunks_by_key[key] = doc
                chunk_embeddings[key] = emb if isinstance(emb, list) else emb.tolist()

            # BM25 recall for this collection
            bm25_state = _ensure_bm25_index(url)
            if bm25_state:
                bm25_index, all_coll_chunks = bm25_state
                tokenized_query = question.lower().split()
                bm25_scores = bm25_index.get_scores(tokenized_query)
                ranked_indices = np.argsort(bm25_scores)[::-1][:top_k_per_collection]
                for rank, idx in enumerate(ranked_indices):
                    doc = all_coll_chunks[idx]
                    key = doc[:100]
                    time_boost = collection_time_boost.get(url, 1.0)
                    rrf_scores[key] = rrf_scores.get(key, 0) + (1 / (k + rank + 1)) * time_boost
                    chunk_to_source_url.setdefault(key, url)
                    if key in chunk_to_retrieval:
                        chunk_to_retrieval[key] = "hybrid"
                    else:
                        chunk_to_retrieval[key] = "keyword"
                    all_chunks_by_key[key] = doc
        except Exception:
            logger.debug("Cross-article recall failed for %s", url, exc_info=True)
            continue

    if not all_chunks_by_key:
        return []

    # Sort by RRF score, take top candidates for Cross-Encoder
    sorted_keys = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
    candidate_keys = sorted_keys[: top_k_final * 4]  # 4x over-recall before reranking

    candidate_chunks = [all_chunks_by_key[k] for k in candidate_keys]

    # Encode any chunks missing embeddings (BM25-only)
    missing = [k for k in candidate_keys if k not in chunk_embeddings]
    if missing:
        missing_texts = [all_chunks_by_key[k] for k in missing]
        missing_embs = await asyncio.to_thread(bi_encoder.encode, missing_texts, show_progress_bar=False)
        for k, emb in zip(missing, missing_embs, strict=False):
            chunk_embeddings[k] = emb.tolist()

    # --- Cross-Encoder Reranking ---
    cross_encoder = get_cross_encoder()
    pairs = [[question, chunk] for chunk in candidate_chunks]
    scores = await asyncio.to_thread(cross_encoder.predict, pairs)

    # --- Personalization ---
    from app.services.learning_service import get_user_feedback_profiles

    positive_centroid, negative_centroid = await get_user_feedback_profiles()

    final_scores = []
    for _i, (score, chunk) in enumerate(zip(scores, candidate_chunks, strict=False)):
        key = chunk[:100]
        bonus = 0.0
        penalty = 0.0
        if positive_centroid is not None or negative_centroid is not None:
            chunk_emb = chunk_embeddings.get(key)
            if chunk_emb is not None:
                chunk_emb_np = np.array(chunk_emb)
                norm = np.linalg.norm(chunk_emb_np)
                if norm > 0:
                    chunk_emb_np = chunk_emb_np / norm
                if positive_centroid is not None:
                    bonus = max(0, float(np.dot(positive_centroid, chunk_emb_np))) * 3.0
                if negative_centroid is not None:
                    penalty = max(0, float(np.dot(negative_centroid, chunk_emb_np))) * 2.0

        total_score = float(score) + bonus - penalty
        final_scores.append(
            {
                "chunk": chunk,
                "cross_score": round(float(score), 2),
                "bonus": round(bonus, 2),
                "penalty": round(penalty, 2),
                "total": round(total_score, 2),
                "source": chunk_to_retrieval.get(key, "semantic"),
                "source_url": chunk_to_source_url.get(key, ""),
            }
        )

    ranked = sorted(final_scores, key=lambda x: x["total"], reverse=True)
    return ranked[:top_k_final]


# -------------------------------------------------------------------
# Prompt builders
# -------------------------------------------------------------------


def _build_cross_article_prompt(question: str, context_chunks: list[dict]) -> str:
    """Build RAG prompt for cross-article queries with source URLs."""
    numbered = "\n\n".join(
        f"[{i + 1}] (来源: {c['source_url'][:60]}) {c['chunk']}" for i, c in enumerate(context_chunks)
    )
    return f"""你是一个专业的新闻深度分析助手。以下是从多篇文章中检索到的最相关段落（已编号），请基于这些内容回答用户的问题。
在回答中，当你引用了某段内容时，请在相应语句末尾用方括号标注来源编号，例如 [1]、[2]。
如果内容中没有相关信息，请直接告知用户。

【多篇文章相关段落】
{numbered}

【用户问题】
{question}

请用简洁流畅的中文回答（记得标注引用编号）："""


def _build_rag_prompt(
    question: str, context_chunks: list[str], history: list[dict] | None = None, memory_context: str = ""
) -> str:
    numbered = "\n\n".join(f"[{i + 1}] {chunk}" for i, chunk in enumerate(context_chunks))

    history_section = ""
    if history:
        lines = []
        for msg in history[-6:]:  # cap at last 6 messages
            role_label = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "").strip()
            if content:
                lines.append(f"{role_label}: {content}")
        if lines:
            history_section = "\n【对话历史】\n" + "\n".join(lines) + "\n"

    memory_section = ""
    if memory_context:
        memory_section = f"\n【关于用户的已知信息】\n{memory_context}\n"

    return f"""你是一个专业的新闻深度分析助手。以下是从原文中检索到的最相关段落（已编号），请仅基于这些内容回答用户的问题。
在回答中，当你引用了某段内容时，请在相应语句末尾用方括号标注来源编号，例如 [1]、[2]。
如果内容中没有相关信息，请直接告知用户。
{memory_section}
【原文相关段落】
{numbered}{history_section}
【用户问题】
{question}

请用简洁流畅的中文回答（记得标注引用编号）："""


# -------------------------------------------------------------------
# Streaming query endpoints
# -------------------------------------------------------------------


async def query_cross_article(
    question: str,
    top_k_per_collection: int = 5,
    max_collections: int = 20,
    top_k_final: int = 5,
) -> AsyncGenerator[str, None]:
    """
    Cross-article RAG query: search all ingested articles and stream an answer.
    Yields [METADATA]...[/METADATA] first, then streaming text tokens.
    """
    if not _ingested_urls:
        yield "抱歉，目前没有任何已入库的文章可供搜索。"
        return

    ranked_results = await _recall_and_rerank_cross_article(
        question,
        top_k_per_collection=top_k_per_collection,
        max_collections=max_collections,
        top_k_final=top_k_final,
    )

    if not ranked_results:
        yield "抱歉，在已入库的文章中未找到与您问题相关的内容。"
        return

    # Build citations with source URLs
    citations = [
        {
            "index": i + 1,
            "preview": r["chunk"][:120].replace("\n", " "),
            "source": r.get("source", "semantic"),
            "source_url": r.get("source_url", ""),
        }
        for i, r in enumerate(ranked_results)
    ]

    metadata = {
        "type": "scoring_explain",
        "mode": "cross_article",
        "scores": [
            {
                "cross_score": r["cross_score"],
                "bonus": r["bonus"],
                "penalty": r.get("penalty", 0),
                "total": r["total"],
                "source": r.get("source", "semantic"),
                "source_url": r.get("source_url", ""),
                "preview": r["chunk"][:40] + "...",
            }
            for r in ranked_results
        ],
        "citations": citations,
    }
    yield f"[METADATA]{json.dumps(metadata)}[/METADATA]"

    prompt = _build_cross_article_prompt(
        question, [{"chunk": r["chunk"], "source_url": r.get("source_url", "")} for r in ranked_results]
    )

    from app.services.llm_service import llm_service
    from app.services.metrics_service import metrics_service

    stream = await llm_service.llm.chat_stream(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000,
    )

    full_response = ""
    async for chunk in stream:
        if chunk.usage:
            await metrics_service.record_tokens(
                chunk.usage.prompt_tokens,
                chunk.usage.completion_tokens,
            )
            continue
        if chunk.choices and chunk.choices[0].delta.content:
            delta = chunk.choices[0].delta.content
            full_response += delta
            yield delta


async def query_stream(question: str, url: str, history: list[dict] | None = None) -> AsyncGenerator[str, None]:
    """
    Run the full RAG pipeline and yield streaming tokens.

    If *history* is None, the last 6 chat messages are loaded from DB
    (before saving the current question, so the current message is not
    duplicated in context).  If *history* is provided by the caller,
    it is used directly — this avoids an extra DB round-trip.
    """
    from app.services.chat_history_service import get_chat_history, save_chat_message

    # Load history BEFORE saving the current question
    if history is None:
        try:
            db_history = await get_chat_history(url)
            history = [{"role": "user" if m.role == "user" else "ai", "content": m.content} for m in db_history[-6:]]
        except Exception:
            history = []

    # Save user question
    await save_chat_message(url, "user", question)

    # Two-stage retrieval + Personalization
    ranked_results = await _recall_and_rerank(question, url)

    if not ranked_results:
        yield "抱歉，暂时无法检索到相关内容，请确认文章已成功加载。"
        return

    # Extract just the chunks for the prompt
    top_chunks = [r["chunk"] for r in ranked_results]

    # Build citations list (1-indexed, matching prompt numbering)
    citations = [
        {
            "index": i + 1,
            "preview": r["chunk"][:120].replace("\n", " "),
            "source": r.get("source", "semantic"),
        }
        for i, r in enumerate(ranked_results)
    ]

    # Send scoring + citation metadata as a special JSON packet
    metadata = {
        "type": "scoring_explain",
        "scores": [
            {
                "cross_score": r["cross_score"],
                "bonus": r["bonus"],
                "penalty": r.get("penalty", 0),
                "total": r["total"],
                "source": r.get("source", "semantic"),
                # Show first 40 chars of chunk as a preview
                "preview": r["chunk"][:40] + "...",
            }
            for r in ranked_results
        ],
        "citations": citations,
    }
    yield f"[METADATA]{json.dumps(metadata)}[/METADATA]"

    # Load user memory context for personalized responses
    memory_context = ""
    try:
        from app.services.memory_service import build_memory_context

        memory_context = await build_memory_context()
    except Exception:
        pass  # non-critical; proceed without memory

    prompt = _build_rag_prompt(question, top_chunks, history=history, memory_context=memory_context)

    # Use the shared LLM client to avoid creating a new connection per query.
    from app.services.llm_service import llm_service
    from app.services.metrics_service import metrics_service

    stream = await llm_service.llm.chat_stream(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
    )

    full_response = ""
    async for chunk in stream:
        if chunk.usage:
            await metrics_service.record_tokens(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
            continue

        if chunk.choices and chunk.choices[0].delta.content:
            delta = chunk.choices[0].delta.content
            full_response += delta
            yield delta

    # Save AI response
    if full_response:
        await save_chat_message(url, "ai", full_response)
