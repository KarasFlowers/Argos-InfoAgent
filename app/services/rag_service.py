"""
Facade — re-exports all public names from the ``app.services.rag``
subpackage so that existing imports::

    from app.services.rag_service import ingest, query_stream, ...

continue to work.
"""
from app.services.rag import (  # noqa: F401
    is_rag_available,
    get_bi_encoder,
    get_cross_encoder,
    init_chroma,
    prewarm_models,
    enqueue_for_ingest,
    get_ingest_status,
    ingest_worker_loop,
    ingest,
    delete_collections_by_urls,
    fetch_article_text,
    assess_content_quality,
    split_into_chunks,
    semantic_split,
    stream_article_overview,
    generate_article_overview,
    get_db_cached_overview,
    query_stream,
    query_cross_article,
    _ingested_urls,
    _ingest_queue,
    _ingest_status,
    _bm25_indices,
    _content_fallback,
    _prepare_overview_context,
)
