"""
Embedder Module — Responsible for dense embeddings generation and ChromaDB vector store access.
Task: TASK-R3 (Vector + BM25 Hybrid Search Engine)
"""
from __future__ import annotations

from src.indexing.vector_store import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_PERSIST_PATH,
    get_collection,
)

__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_PERSIST_PATH",
    "get_collection",
]
