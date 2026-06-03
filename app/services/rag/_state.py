"""
RAG module-level state: caches, model loaders, ChromaDB client, and queue infrastructure.

Extracted from ``_core.py`` to keep mutable global state in one place and make
it easier to reason about concurrency and testing.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from functools import lru_cache
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Bounded LRU Cache
# -------------------------------------------------------------------

class _BoundedLRU(OrderedDict):
    """Minimal dict-like bounded LRU cache. Evicts oldest entry once full.

    All mutating accessors are guarded by a ``threading.Lock`` to prevent
    ``RuntimeError`` / ``KeyError`` when multiple asyncio tasks (or threads
    via ``run_in_executor``) access the cache concurrently.
    """

    def __init__(self, maxsize: int):
        super().__init__()
        self._maxsize = maxsize
        self._lock = threading.Lock()

    def __setitem__(self, key, value):
        with self._lock:
            if key in self:
                self.move_to_end(key)
            super().__setitem__(key, value)
            while len(self) > self._maxsize:
                self.popitem(last=False)

    def __getitem__(self, key):
        with self._lock:
            value = super().__getitem__(key)
            self.move_to_end(key)
            return value

    def get(self, key, default=None):
        with self._lock:
            if key in self:
                self.move_to_end(key)
                return super().__getitem__(key)
            return default


# -------------------------------------------------------------------
# RAG availability check
# -------------------------------------------------------------------

def is_rag_available() -> bool:
    """Return True if RAG is enabled AND the required packages are installed."""
    if not settings.RAG_ENABLED:
        return False
    try:
        import sentence_transformers  # noqa: F401
        import chromadb  # noqa: F401
        import rank_bm25  # noqa: F401
        return True
    except ImportError:
        return False


def _require_rag() -> None:
    """Raise RuntimeError if RAG is not available."""
    if not settings.RAG_ENABLED:
        raise RuntimeError("RAG feature is disabled. Set RAG_ENABLED=true to enable.")
    if not is_rag_available():
        raise RuntimeError(
            "RAG dependencies not installed. Run: pip install -r requirements-rag.txt"
        )


def _reset_hf_http_client() -> None:
    """Invalidate huggingface_hub's internal httpx.Client.

    Works around a known bug where the module-level httpx.Client used by
    ``huggingface_hub`` is garbage-collected or closed prematurely (often
    in multi-threaded contexts), causing ``RuntimeError: Cannot send a
    request, as the client has been closed`` on subsequent requests.

    After calling this function, the next request will lazily create a
    fresh client.
    """
    try:
        import huggingface_hub
        # huggingface_hub >= 0.24 exposes an official API
        if hasattr(huggingface_hub, "configure_http_backend"):
            huggingface_hub.configure_http_backend(backend=None)
            logger.debug("Reset huggingface_hub HTTP backend via configure_http_backend")
            return
    except Exception:
        pass
    try:
        # Fallback for older versions: reset the internal module attribute
        from huggingface_hub.utils import _http as hf_http
        for attr in ("_global_client", "_http_client"):
            if hasattr(hf_http, attr):
                setattr(hf_http, attr, None)
        logger.debug("Reset huggingface_hub HTTP client via internal attribute")
    except Exception:
        logger.debug("Could not reset huggingface_hub HTTP client", exc_info=True)


# -------------------------------------------------------------------
# Model Loading (cached, loaded once at startup)
# -------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_bi_encoder():
    """Load the Bi-Encoder for generating embeddings. Cached after first call."""
    _require_rag()
    from sentence_transformers import SentenceTransformer
    logger.info("Loading Bi-Encoder model (BAAI/bge-m3)")
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            return SentenceTransformer("BAAI/bge-m3")
        except RuntimeError as exc:
            if "client has been closed" in str(exc) and attempt < max_retries:
                logger.warning(
                    "huggingface_hub httpx client closed (attempt %d/%d), resetting and retrying",
                    attempt, max_retries,
                )
                _reset_hf_http_client()
                continue
            raise


@lru_cache(maxsize=1)
def get_cross_encoder():
    """Load the Cross-Encoder for reranking. Cached after first call."""
    _require_rag()
    from sentence_transformers import CrossEncoder
    logger.info("Loading Cross-Encoder rerank model")
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        except RuntimeError as exc:
            if "client has been closed" in str(exc) and attempt < max_retries:
                logger.warning(
                    "huggingface_hub httpx client closed (attempt %d/%d), resetting and retrying",
                    attempt, max_retries,
                )
                _reset_hf_http_client()
                continue
            raise


# -------------------------------------------------------------------
# ChromaDB Client
# -------------------------------------------------------------------

# Lazy-initialised ChromaDB client — created on first use, not at import time.
# This avoids triggering disk I/O (and potential crashes) when the module is
# imported for type-checking or testing without a data directory present.
_chroma_client = None


def _get_chroma_client():
    """Return the shared ChromaDB PersistentClient, creating it on first call."""
    _require_rag()
    import chromadb
    global _chroma_client
    if _chroma_client is None:
        try:
            _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_DB_DIR)
        except KeyError:
            # Workaround for ChromaDB 0.5.x bug: SharedSystemClient can
            # leave its _identifier_to_system cache in an inconsistent state,
            # causing a KeyError on the return path.  Clearing the cache and
            # retrying resolves the issue.
            logger.warning("ChromaDB SharedSystemClient cache inconsistency detected, retrying")
            from chromadb.api.shared_system_client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
            _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_DB_DIR)
        logger.info("ChromaDB PersistentClient initialised at %s", settings.CHROMA_DB_DIR)
    return _chroma_client


# -------------------------------------------------------------------
# Module-level mutable state
# -------------------------------------------------------------------

# A dict to track which URLs have already been ingested (mirrors Chroma state;
# not capped because it is small and retention cleanup removes stale entries).
_ingested_urls: dict[str, str] = {}

# BM25 in-memory index: url -> (BM25Okapi, list[str])
# Tied to live Chroma collections; rebuilt on demand.
_bm25_indices: dict[str, tuple] = {}

# Cached extracted article text and in-flight extraction tasks.
_article_text_cache: _BoundedLRU = _BoundedLRU(maxsize=256)
_article_text_tasks: dict[str, asyncio.Task[str]] = {}

# Cached article overviews so reopening the panel feels instant.
_article_overview_cache: _BoundedLRU = _BoundedLRU(maxsize=256)

# Cached content quality assessments.
_article_quality_cache: _BoundedLRU = _BoundedLRU(maxsize=256)

# -------------------------------------------------------------------
# Background Ingestion Pipeline state
# -------------------------------------------------------------------

# URL queue for the background workers (capped to avoid unbounded memory).
_ingest_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=200)

# Tracks per-URL ingestion state visible to the API layer.
# url -> {"status": "pending"|"running"|"done"|"failed",
#          "chunks": int, "error": str|None}
# Capped to prevent unbounded memory growth from accumulated statuses.
_ingest_status: _BoundedLRU = _BoundedLRU(maxsize=500)

# Content fallback text (e.g. scraped body + comments from HN/Reddit).
# Used by ``ingest`` when trafilatura extraction is too short.
# Capped to avoid unbounded growth if URLs are enqueued but never ingested.
_content_fallback: _BoundedLRU = _BoundedLRU(maxsize=256)


# -------------------------------------------------------------------
# ChromaDB initialisation
# -------------------------------------------------------------------

def prewarm_models() -> None:
    """Pre-load Bi-Encoder and Cross-Encoder models into memory.

    Call this during application startup so the first user request
    doesn't pay the model-loading cost.  Safe to call when RAG is
    disabled (no-op).  Idempotent — subsequent calls are no-ops
    because ``lru_cache`` keeps the models alive.
    """
    if not is_rag_available():
        logger.info("RAG is disabled or dependencies missing; skipping model pre-warm")
        return
    # Ensure huggingface_hub starts with a clean HTTP client state.
    # This prevents the "client has been closed" RuntimeError that can
    # occur when the internal httpx.Client is GC'd or closed by another
    # thread before model loading begins.
    _reset_hf_http_client()
    logger.info("Pre-warming Bi-Encoder model (BAAI/bge-m3)")
    get_bi_encoder()
    logger.info("Pre-warming Cross-Encoder model")
    get_cross_encoder()
    logger.info("RAG models pre-warmed")


def init_chroma() -> None:
    """Pre-warm ChromaDB and load existing collections.

    Call this once during application startup (from FastAPI lifespan) so that
    the first user request doesn't pay the initialisation cost.  It is safe to
    call multiple times — subsequent calls are no-ops.

    If RAG is disabled, this is a no-op.
    """
    if not is_rag_available():
        logger.info("RAG is disabled or dependencies missing; skipping ChromaDB init")
        return
    client = _get_chroma_client()
    # Load existing BGE-M3 collections so we don't lose track of them.
    # We ignore old collections (e.g. 384-dimensional ones) as they are incompatible.
    try:
        for coll_obj in client.list_collections():
            if not coll_obj.name.startswith("rag-m3-"):
                continue
            metadata = getattr(coll_obj, "metadata", None)
            if metadata and "url" in metadata:
                _ingested_urls[metadata["url"]] = coll_obj.name
            else:
                logger.warning("Collection %s missing url metadata", coll_obj.name)
    except Exception:
        logger.exception("Error listing existing ChromaDB collections")
