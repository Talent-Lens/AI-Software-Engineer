"""
Cross-Encoder Re-Ranker Module — Production Enterprise Edition.
Task: TASK-R4 (Cross-Encoder Re-Ranking Pipeline)

Uses sentence-transformers CrossEncoder to compute query-code cross-attention scores
and re-scores retrieved candidate chunks for maximum precision.

Features:
- Lazy model loading & global model instance caching across instances.
- Robust exception handling & graceful fallback when inference fails.
- Batch processing & device (CPU/CUDA) selection.
- Configurable minimum score threshold filtering.
- Comprehensive logging and type annotations.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Sequence
from src.schema import Chunk, RetrievalResult

logger = logging.getLogger("ai_engineer.retrieval.reranker")

# Global in-memory cache for CrossEncoder models to avoid redundant weight loads
_MODEL_CACHE: dict[str, Any] = {}


def format_chunk_for_reranking(chunk: Chunk) -> str:
    """
    Formats a Chunk into a clean text representation optimized for cross-encoder scoring.
    Includes file path, metadata context, and source code.
    """
    parts = []
    if chunk.file_path:
        parts.append(f"File: {chunk.file_path}")
    if chunk.name:
        parts.append(f"Name: {chunk.name} ({chunk.type})")
    parts.append(f"Code:\n{chunk.code}")
    return "\n".join(parts)


class CrossEncoderReRanker:
    """
    Production Cross-Encoder Re-Ranker utilizing sentence-transformers CrossEncoder models.
    Default Model: cross-encoder/ms-marco-MiniLM-L-6-v2
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        model: Any | None = None,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model_name = model_name
        self._model = model
        self.device = device
        self.batch_size = batch_size

    def load_model(self) -> Any:
        """
        Lazily loads and caches the sentence-transformers CrossEncoder model instance.
        """
        if self._model is not None:
            return self._model

        cache_key = f"{self.model_name}::{self.device}"
        if cache_key in _MODEL_CACHE:
            self._model = _MODEL_CACHE[cache_key]
            return self._model

        logger.info("Loading CrossEncoder model '%s' (device=%s)...", self.model_name, self.device)
        try:
            from sentence_transformers import CrossEncoder

            kwargs: dict[str, Any] = {}
            if self.device:
                kwargs["device"] = self.device

            model_instance = CrossEncoder(self.model_name, **kwargs)
            _MODEL_CACHE[cache_key] = model_instance
            self._model = model_instance
            logger.info("Successfully loaded and cached model '%s'.", self.model_name)
            return self._model
        except Exception as err:
            logger.error("Failed to load CrossEncoder model '%s': %s", self.model_name, err)
            raise err

    def rerank(
        self,
        query: str,
        chunks: Sequence[Chunk],
        top_k: int = 5,
        min_score: float | None = None,
        apply_sigmoid: bool = False,
    ) -> list[RetrievalResult]:
        """
        Re-scores candidate Chunks against a query using cross-attention.

        Args:
            query: The user or agent code search query string.
            chunks: Sequence of candidate Chunk objects to re-score.
            top_k: Maximum number of high-precision results to return.
            min_score: Optional threshold to filter out results below this score.
            apply_sigmoid: Whether to map raw logit scores to [0, 1] via sigmoid.

        Returns:
            List of RetrievalResult instances sorted by descending cross-encoder score.
        """
        if not chunks:
            return []

        # Graceful fallback input validation
        valid_chunks = [c for c in chunks if c is not None and isinstance(c, Chunk)]
        if not valid_chunks:
            logger.warning("No valid Chunk objects passed for re-ranking.")
            return []

        try:
            model = self.load_model()
            pairs = [(query, format_chunk_for_reranking(chunk)) for chunk in valid_chunks]

            logger.debug(
                "Re-ranking %d candidates for query '%s' (batch_size=%d)...",
                len(pairs),
                query,
                self.batch_size,
            )

            raw_scores = model.predict(pairs, batch_size=self.batch_size)

            chunk_score_pairs: list[tuple[Chunk, float]] = []
            for chunk, score in zip(valid_chunks, raw_scores):
                val = float(score)
                if apply_sigmoid:
                    val = 1.0 / (1.0 + math.exp(-val))
                chunk_score_pairs.append((chunk, val))

            # Filter by minimum score if threshold is provided
            if min_score is not None:
                chunk_score_pairs = [pair for pair in chunk_score_pairs if pair[1] >= min_score]

            # Sort descending by cross-encoder score
            sorted_pairs = sorted(chunk_score_pairs, key=lambda x: x[1], reverse=True)

            results = [
                RetrievalResult(chunk=chunk, score=score, query=query)
                for chunk, score in sorted_pairs[:top_k]
            ]
            return results

        except Exception as err:
            logger.error("Error during cross-encoder re-ranking: %s. Falling back to input order.", err)
            # Safe production fallback: return input candidates up to top_k with default rank score
            return [
                RetrievalResult(chunk=chunk, score=1.0 / (idx + 1), query=query)
                for idx, chunk in enumerate(valid_chunks[:top_k])
            ]


__all__ = ["CrossEncoderReRanker", "format_chunk_for_reranking"]
