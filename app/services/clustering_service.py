"""Event clustering engine — groups related news items by topic similarity.

Inspired by Infinitum's content clustering but using Argos's existing
Bi-Encoder infrastructure for fast similarity computation.

Pipeline:
1. Compute title embeddings for incoming news items
2. Match each item against existing clusters (cosine similarity)
3. Assign to best cluster if above threshold, else create new cluster
4. Periodically merge near-duplicate clusters
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ContentCluster, NewsItem

logger = logging.getLogger(__name__)

# Similarity threshold for assigning an item to an existing cluster
_CLUSTER_THRESHOLD = 0.75
# Minimum items to form a meaningful cluster in the summary
_MIN_CLUSTER_SIZE = 2


def _fingerprint(title: str) -> str:
    """Generate a stable fingerprint for cluster dedup."""
    normalized = title.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _cluster_fingerprint(title: str, board_id: int | None) -> str:
    """Generate the persisted fingerprint, scoped to a board when available."""
    scope = f"board:{board_id}" if board_id is not None else "global"
    return f"{scope}:{_fingerprint(title)}"


async def assign_clusters(
    items: list[NewsItem],
    board_id: int | None,
    session: AsyncSession,
    *,
    commit: bool = True,
) -> dict[int, int]:
    """Assign news items to clusters. Returns {item_id: cluster_id}.

    Uses title-based similarity with the project's Bi-Encoder if available,
    otherwise falls back to simple string overlap matching.
    """
    if not items:
        return {}

    # Load existing clusters for this board
    stmt = select(ContentCluster)
    if board_id is not None:
        stmt = stmt.where(ContentCluster.board_id == board_id)
    result = await session.execute(stmt)
    existing_clusters: list[ContentCluster] = list(result.scalars().all())

    existing_by_id = {c.id: c for c in existing_clusters if c.id is not None}
    # Build cluster title index
    cluster_titles = {c.id: c.title for c in existing_clusters if c.id is not None}

    assignments: dict[int, int] = {}
    new_clusters: list[ContentCluster] = []
    pending_by_fingerprint: dict[str, ContentCluster] = {}

    # Try to use Bi-Encoder for embeddings
    embedder = _get_embedder()

    for item in items:
        if not item.id:
            continue

        best_cluster_id: int | None = None
        best_score = 0.0

        if embedder and cluster_titles:
            best_cluster_id, best_score = _find_best_cluster_embedding(item.headline, cluster_titles, embedder)
        elif cluster_titles:
            best_cluster_id, best_score = _find_best_cluster_overlap(item.headline, cluster_titles)

        if best_cluster_id and best_score >= _CLUSTER_THRESHOLD:
            assignments[item.id] = best_cluster_id
            item.cluster_id = best_cluster_id
            # Update existing cluster
            c = existing_by_id.get(best_cluster_id)
            if c:
                c.item_count += 1
                ids = c.item_ids or []
                if item.id not in ids:
                    ids.append(item.id)
                c.item_ids = ids
                c.last_updated_at = datetime.now(UTC)
        else:
            # Create new cluster
            fp = _cluster_fingerprint(item.headline, board_id)
            pending = pending_by_fingerprint.get(fp)
            if pending:
                ids = pending.item_ids or []
                if item.id not in ids:
                    ids.append(item.id)
                pending.item_ids = ids
                pending.item_count = len(ids)
                pending.last_updated_at = datetime.now(UTC)
                continue

            existing_stmt = select(ContentCluster).where(ContentCluster.fingerprint == fp)
            if board_id is not None:
                existing_stmt = existing_stmt.where(ContentCluster.board_id == board_id)
            existing_result = await session.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()
            if existing and existing.id:
                assignments[item.id] = existing.id
                item.cluster_id = existing.id
                existing.item_count += 1
                ids = existing.item_ids or []
                if item.id not in ids:
                    ids.append(item.id)
                existing.item_ids = ids
                existing.last_updated_at = datetime.now(UTC)
                existing_by_id[existing.id] = existing
                cluster_titles[existing.id] = existing.title
                continue

            cluster = ContentCluster(
                fingerprint=fp,
                title=item.headline,
                item_count=1,
                item_ids=[item.id],
                first_seen_at=datetime.now(UTC),
                last_updated_at=datetime.now(UTC),
                board_id=board_id,
            )
            session.add(cluster)
            new_clusters.append(cluster)
            pending_by_fingerprint[fp] = cluster
            # Add to title index for subsequent items in same batch
            # (id will be set after flush)

    if new_clusters:
        try:
            await session.flush()  # get IDs for new clusters
        except IntegrityError:
            # Duplicate fingerprint — find existing cluster and merge
            await session.rollback()
            logger.info("Duplicate cluster fingerprint detected, merging")
            for cluster in new_clusters:
                existing_stmt = select(ContentCluster).where(ContentCluster.fingerprint == cluster.fingerprint)
                if board_id is not None:
                    existing_stmt = existing_stmt.where(ContentCluster.board_id == board_id)
                ex_result = await session.execute(existing_stmt)
                existing = ex_result.scalar_one_or_none()
                if existing and cluster.item_ids:
                    for item_id in cluster.item_ids:
                        assignments[item_id] = existing.id
                    existing.item_count += len(cluster.item_ids)
                    ids = existing.item_ids or []
                    ids.extend(cluster.item_ids)
                    existing.item_ids = ids
                    existing.last_updated_at = datetime.now(UTC)
                    cluster_titles[existing.id] = existing.title
            await session.flush()

        for cluster in new_clusters:
            if cluster.id and cluster.item_ids:
                for item_id in cluster.item_ids:
                    assignments[item_id] = cluster.id
                    matched_item = next((candidate for candidate in items if candidate.id == item_id), None)
                    if matched_item:
                        matched_item.cluster_id = cluster.id
                cluster_titles[cluster.id] = cluster.title

    if commit:
        await session.commit()
    else:
        await session.flush()

    logger.info(
        "Clustering: %d items -> %d assignments (%d new clusters)",
        len(items),
        len(assignments),
        len(new_clusters),
    )
    return assignments


async def get_clusters_for_board(
    session: AsyncSession,
    board_id: int | None = None,
    min_items: int = _MIN_CLUSTER_SIZE,
    limit: int = 20,
) -> list[ContentCluster]:
    """Retrieve clusters for a board, sorted by item_count descending."""
    stmt = (
        select(ContentCluster)
        .where(ContentCluster.item_count >= min_items)
        .order_by(ContentCluster.item_count.desc())
        .limit(limit)
    )

    if board_id is not None:
        stmt = stmt.where(ContentCluster.board_id == board_id)

    result = await session.execute(stmt)
    return list(result.scalars().all())


def _get_embedder():
    """Try to get the Bi-Encoder for similarity computation."""
    try:
        from app.services.rag._core import get_bi_encoder

        return get_bi_encoder()
    except Exception:
        return None


def _find_best_cluster_embedding(
    title: str,
    cluster_titles: dict[int, str],
    embedder,
) -> tuple[int | None, float]:
    """Find best matching cluster using Bi-Encoder embeddings."""
    try:
        titles_list = list(cluster_titles.values())
        ids_list = list(cluster_titles.keys())
        if not titles_list:
            return None, 0.0

        # Encode query and all cluster titles
        all_texts = [title] + titles_list
        embeddings = embedder.encode(all_texts, normalize_embeddings=True)

        query_emb = embeddings[0]
        cluster_embs = embeddings[1:]

        # Cosine similarity (embeddings are normalized)
        import numpy as np

        scores = np.dot(cluster_embs, query_emb)

        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        return ids_list[best_idx], best_score
    except Exception as err:
        logger.warning("Embedding-based clustering failed: %s", err)
        return None, 0.0


def _find_best_cluster_overlap(
    title: str,
    cluster_titles: dict[int, str],
) -> tuple[int | None, float]:
    """Fallback: find best matching cluster using word overlap (Jaccard)."""
    title_words = set(title.lower().split())
    if not title_words:
        return None, 0.0

    best_id: int | None = None
    best_score = 0.0

    for cid, ctitle in cluster_titles.items():
        cluster_words = set(ctitle.lower().split())
        if not cluster_words:
            continue
        intersection = title_words & cluster_words
        union = title_words | cluster_words
        jaccard = len(intersection) / len(union) if union else 0.0
        if jaccard > best_score:
            best_score = jaccard
            best_id = cid

    return best_id, best_score
