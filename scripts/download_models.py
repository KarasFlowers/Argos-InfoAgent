#!/usr/bin/env python3
"""
Pre-download RAG embedding models so the first request is fast.

Usage:
    python scripts/download_models.py

Models downloaded:
    - BAAI/bge-m3          (~570 MB)  - Bi-Encoder for semantic search
    - ms-marco-MiniLM-L-6  (~80 MB)  - Cross-Encoder for reranking
"""

import sys
import time


def main() -> int:
    import os

    print("=" * 50)
    print("  Argos - Model Pre-Download")
    print("=" * 50)
    print()

    if os.environ.get("RAG_ENABLED", "false").lower() not in ("true", "1", "yes", "on"):
        print("[SKIP] RAG_ENABLED=false - model download not required.")
        return 0

    try:
        from sentence_transformers import CrossEncoder, SentenceTransformer
    except ImportError:
        print("[ERROR] sentence-transformers is not installed.")
        print("  Run: pip install -r requirements-rag.txt")
        return 1

    models = [
        ("BAAI/bge-m3", "Bi-Encoder (semantic search)", SentenceTransformer),
        ("cross-encoder/ms-marco-MiniLM-L-6-v2", "Cross-Encoder (reranking)", CrossEncoder),
    ]

    for name, desc, loader in models:
        print(f"[1/2] Downloading {name} - {desc} ...")
        t0 = time.time()
        try:
            loader(name)
            elapsed = time.time() - t0
            print(f"  ✓ Done in {elapsed:.1f}s")
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            return 1
        print()

    print("All models are cached locally. First startup will be fast!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
