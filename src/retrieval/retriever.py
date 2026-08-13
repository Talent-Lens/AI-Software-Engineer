"""
Retriever Module — Hybrid search candidate retriever and re-ranker interface.
Task: TASK-R3 & TASK-R4 (Hybrid Search & Cross-Encoder Re-Ranker)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Sequence
from src.schema import Chunk, RetrievalResult
from src.retrieval.bm25 import BM25Indexer
from src.retrieval.reranker import CrossEncoderReRanker

logger = logging.getLogger("ai_engineer.retrieval.hybrid")


def collection_to_chunks(collection: Any) -> list[Chunk]:
    """
    Helper function to extract all Chunk objects from a ChromaDB collection.
    """
    try:
        data = collection.get()
    except Exception as err:
        logger.warning("Failed to read ChromaDB collection: %s", err)
        return []

    if not data or not data.get("documents"):
        return []

    chunks: list[Chunk] = []
    ids = data.get("ids") or []
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []

    for doc, meta, doc_id in zip(documents, metadatas, ids):
        raw_imports = meta.get("imports", "[]") if meta else "[]"
        try:
            parsed_imports = json.loads(raw_imports) if raw_imports else []
        except Exception:
            parsed_imports = []

        file_path = meta.get("file_path", "") if meta else ""
        start_line = meta.get("start_line", 0) if meta else 0
        end_line = meta.get("end_line", 0) if meta else 0
        chunk_type = meta.get("type", "code_block") if meta else "code_block"
        name = meta.get("name", "") if meta else ""
        parent_name = meta.get("parent_name") or None if meta else None

        chunk = Chunk(
            id=doc_id,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            type=chunk_type,
            name=name,
            code=doc,
            parent_name=parent_name,
            imports=parsed_imports,
        )
        chunks.append(chunk)

    return chunks


def vector_search(collection: Any, query: str, top_k: int = 20) -> list[tuple[Chunk, float, int]]:
    """
    Performs dense vector search on ChromaDB collection.
    Returns list of (Chunk, distance, 1_based_rank).
    """
    try:
        results = collection.query(query_texts=[query], n_results=top_k)
    except Exception as err:
        logger.warning("Vector search query failed: %s", err)
        return []

    if not results or not results.get("documents") or not results["documents"][0]:
        return []

    vector_results: list[tuple[Chunk, float, int]] = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    ids = results["ids"][0]
    dists = results["distances"][0]

    for rank, (doc, meta, doc_id, dist) in enumerate(zip(docs, metas, ids, dists), start=1):
        raw_imports = meta.get("imports", "[]") if meta else "[]"
        try:
            parsed_imports = json.loads(raw_imports) if raw_imports else []
        except Exception:
            parsed_imports = []

        chunk = Chunk(
            id=doc_id,
            file_path=meta.get("file_path", ""),
            start_line=meta.get("start_line", 0),
            end_line=meta.get("end_line", 0),
            type=meta.get("type", "code_block"),
            name=meta.get("name", ""),
            code=doc,
            parent_name=meta.get("parent_name") or None,
            imports=parsed_imports,
        )
        vector_results.append((chunk, float(dist), rank))

    return vector_results


def compute_rrf_scores(
    vector_ranked: list[tuple[Chunk, float, int]],
    bm25_ranked: list[tuple[Chunk, float, int]],
    k: int = 60,
) -> list[tuple[Chunk, float]]:
    """
    Combines dense vector ranks and sparse BM25 ranks using Reciprocal Rank Fusion (RRF).
    Formula: RRF(d) = sum_{m in M} 1 / (k + rank_m(d))
    Returns list of (Chunk, rrf_score) ordered by highest score descending.
    """
    rrf_map: dict[str, float] = {}
    chunk_map: dict[str, Chunk] = {}

    for chunk, _dist, rank in vector_ranked:
        chunk_id = chunk.id
        chunk_map[chunk_id] = chunk
        rrf_map[chunk_id] = rrf_map.get(chunk_id, 0.0) + (1.0 / (k + rank))

    for chunk, _bm25_score, rank in bm25_ranked:
        chunk_id = chunk.id
        chunk_map[chunk_id] = chunk
        rrf_map[chunk_id] = rrf_map.get(chunk_id, 0.0) + (1.0 / (k + rank))

    sorted_items = sorted(rrf_map.items(), key=lambda x: x[1], reverse=True)
    return [(chunk_map[chunk_id], rrf_score) for chunk_id, rrf_score in sorted_items]


class HybridRetriever:
    """
    Hybrid Retriever integrating Dense Vector Search (ChromaDB) and
    Sparse Keyword Search (BM25) fused via Reciprocal Rank Fusion (RRF),
    with an optional Cross-Encoder re-ranking stage.
    """

    def __init__(
        self,
        collection: Any = None,
        chunks: Sequence[Chunk] | None = None,
        bm25_indexer: BM25Indexer | None = None,
        reranker: CrossEncoderReRanker | None = None,
    ) -> None:
        self.collection = collection
        self.bm25_indexer: BM25Indexer
        self.reranker = reranker

        if bm25_indexer is not None:
            self.bm25_indexer = bm25_indexer
        elif chunks is not None:
            self.bm25_indexer = BM25Indexer(chunks)
        elif collection is not None:
            extracted_chunks = collection_to_chunks(collection)
            self.bm25_indexer = BM25Indexer(extracted_chunks)
        else:
            self.bm25_indexer = BM25Indexer()

    def sync_bm25(self, chunks: Sequence[Chunk] | None = None) -> None:
        """
        Re-indexes BM25 corpus from collection or provided chunks.
        """
        if chunks is not None:
            self.bm25_indexer.fit(chunks)
        elif self.collection is not None:
            extracted_chunks = collection_to_chunks(self.collection)
            self.bm25_indexer.fit(extracted_chunks)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        vector_k: int = 20,
        bm25_k: int = 20,
        rrf_k: int = 60,
        rerank: bool = False,
        candidate_k: int = 20,
        reranker: CrossEncoderReRanker | None = None,
        min_score: float | None = None,
    ) -> list[RetrievalResult]:
        """
        Performs hybrid retrieval for a query using Vector + BM25 + RRF,
        optionally re-ranking top candidate_k fused candidates with a Cross-Encoder.
        Returns top_k RetrievalResult items sorted by relevance score.
        """
        vector_ranked: list[tuple[Chunk, float, int]] = []
        if self.collection is not None:
            vector_ranked = vector_search(self.collection, query, top_k=vector_k)

        bm25_ranked = self.bm25_indexer.search(query, top_k=bm25_k)

        fused = compute_rrf_scores(vector_ranked, bm25_ranked, k=rrf_k)

        active_reranker = reranker or self.reranker
        should_rerank = rerank or (reranker is not None)

        if should_rerank:
            if active_reranker is None:
                active_reranker = CrossEncoderReRanker()

            candidate_chunks = [chunk for chunk, _score in fused[:candidate_k]]
            return active_reranker.rerank(
                query, candidate_chunks, top_k=top_k, min_score=min_score
            )

        retrieval_results = [
            RetrievalResult(chunk=chunk, score=score, query=query)
            for chunk, score in fused[:top_k]
            if min_score is None or score >= min_score
        ]
        return retrieval_results


__all__ = [
    "BM25Indexer",
    "CrossEncoderReRanker",
    "HybridRetriever",
    "compute_rrf_scores",
    "collection_to_chunks",
    "vector_search",
]
