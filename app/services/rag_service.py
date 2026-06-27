"""
Facade — re-exports all public names from the ``app.services.rag``
subpackage so that existing imports::

    from app.services.rag_service import ingest, query_stream, ...

continue to work.
"""

from app.services.rag import (  # noqa: F401
    _bm25_indices,
    _content_fallback,
    _ingest_queue,
    _ingest_status,
    _ingested_urls,
    _prepare_overview_context,
    assess_content_quality,
    close_chroma_client,
    delete_collections_by_urls,
    enqueue_for_ingest,
    fetch_article_text,
    generate_article_overview,
    get_bi_encoder,
    get_cross_encoder,
    get_db_cached_overview,
    get_ingest_status,
    ingest,
    ingest_worker_loop,
    init_chroma,
    is_rag_available,
    prewarm_models,
    query_cross_article,
    query_stream,
    semantic_split,
    split_into_chunks,
    stream_article_overview,
)
