"""
BM25 Keyword Search Indexer module for sparse code retrieval.
Task: TASK-R3 (Hybrid Search Engine)
"""
from __future__ import annotations

import re
from typing import Sequence
from rank_bm25 import BM25Plus, BM25Okapi
from src.schema import Chunk


def tokenize_code(text: str) -> list[str]:
    """
    Tokenizes raw code or text into normalized search terms.
    Splits identifiers into snake_case and camelCase components.
    """
    if not text:
        return []

    # Find word tokens (letters, numbers, underscores)
    tokens = re.findall(r'[a-zA-Z0-9_]+', text)
    result_tokens: list[str] = []

    for token in tokens:
        lower_token = token.lower()
        result_tokens.append(lower_token)

        # Split snake_case
        if "_" in lower_token:
            parts = [p for p in lower_token.split("_") if p]
            result_tokens.extend(parts)

        # Split camelCase / PascalCase
        camel_parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)|[0-9]+', token)
        if len(camel_parts) > 1:
            result_tokens.extend([p.lower() for p in camel_parts if p])

    return result_tokens


class BM25Indexer:
    """
    BM25 Keyword Search Indexer wrapping rank_bm25.BM25Plus for code chunks.
    BM25Plus prevents negative/zero IDF on small corpora or code identifiers.
    """

    def __init__(self, chunks: Sequence[Chunk] | None = None) -> None:
        self.chunks: list[Chunk] = []
        self.corpus_tokens: list[list[str]] = []
        self.bm25: BM25Plus | BM25Okapi | None = None

        if chunks:
            self.fit(chunks)

    def fit(self, chunks: Sequence[Chunk]) -> None:
        """
        Builds the BM25 index from a collection of Chunk objects.
        """
        self.chunks = list(chunks)
        self.corpus_tokens = []

        for chunk in self.chunks:
            # Index code content + identifier name + parent_name + file_path
            doc_text = f"{chunk.file_path} {chunk.name} {chunk.parent_name or ''} {chunk.code}"
            tokens = tokenize_code(doc_text)
            self.corpus_tokens.append(tokens)

        if self.corpus_tokens:
            try:
                self.bm25 = BM25Plus(self.corpus_tokens)
            except Exception:
                self.bm25 = BM25Okapi(self.corpus_tokens, epsilon=0.25)
        else:
            self.bm25 = None

    def search(self, query: str, top_k: int = 20) -> list[tuple[Chunk, float, int]]:
        """
        Searches the BM25 index for the given query string.
        Returns a list of tuples: (Chunk, bm25_score, 1_based_rank).
        """
        if not self.bm25 or not self.chunks:
            return []

        query_tokens = tokenize_code(query)
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)

        # Pair chunks with scores
        scored_chunks = list(zip(self.chunks, scores))

        # Sort by descending score
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        results: list[tuple[Chunk, float, int]] = []
        for rank, (chunk, score) in enumerate(scored_chunks[:top_k], start=1):
            results.append((chunk, float(score), rank))

        return results
