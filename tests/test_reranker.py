"""
Unit & Integration Tests for TASK-R4 (Cross-Encoder Re-Ranker) — Production Suite
"""
from __future__ import annotations

import pytest
from src.schema import Chunk, RetrievalResult
from src.retrieval.reranker import (
    CrossEncoderReRanker,
    format_chunk_for_reranking,
    _MODEL_CACHE,
)
from src.retrieval.retriever import HybridRetriever


class MockCrossEncoderModel:
    """
    Mock CrossEncoder model for fast unit testing without loading HF weights.
    """

    def __init__(self, score_map: dict[str, float] | None = None, raise_error: bool = False) -> None:
        self.score_map = score_map or {}
        self.raise_error = raise_error

    def predict(self, pairs: list[tuple[str, str]], batch_size: int = 32) -> list[float]:
        if self.raise_error:
            raise RuntimeError("CUDA Out of Memory mock error")

        scores = []
        for query, text in pairs:
            matched_score = 0.1
            for key, score in self.score_map.items():
                if key in text:
                    matched_score = score
                    break
            scores.append(matched_score)
        return scores


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    c1 = Chunk(
        id="c1",
        file_path="auth/jwt.py",
        start_line=1,
        end_line=15,
        type="function",
        name="verify_jwt",
        code="def verify_jwt(token):\n    # Decode JWT token and check expiration\n    return jwt.decode(token)",
    )
    c2 = Chunk(
        id="c2",
        file_path="db/models.py",
        start_line=1,
        end_line=20,
        type="function",
        name="get_user",
        code="def get_user(db, user_id):\n    # Query database for user profile\n    return db.query(User).filter_by(id=user_id).first()",
    )
    c3 = Chunk(
        id="c3",
        file_path="utils/crypto.py",
        start_line=1,
        end_line=10,
        type="function",
        name="hash_password",
        code="def hash_password(password):\n    # Hash password using bcrypt\n    return bcrypt.hash(password)",
    )
    return [c1, c2, c3]


def test_format_chunk_for_reranking(sample_chunks):
    formatted = format_chunk_for_reranking(sample_chunks[0])
    assert "File: auth/jwt.py" in formatted
    assert "Name: verify_jwt (function)" in formatted
    assert "def verify_jwt(token):" in formatted


def test_reranker_with_mock_model(sample_chunks):
    mock_scores = {
        "hash_password": 0.9,
        "verify_jwt": 0.5,
        "get_user": 0.1,
    }
    mock_model = MockCrossEncoderModel(score_map=mock_scores)
    reranker = CrossEncoderReRanker(model=mock_model)

    query = "how to securely hash user password"
    results = reranker.rerank(query, sample_chunks, top_k=3)

    assert len(results) == 3
    assert isinstance(results[0], RetrievalResult)
    assert results[0].chunk.id == "c3"
    assert results[0].score == 0.9
    assert results[1].chunk.id == "c1"
    assert results[1].score == 0.5
    assert results[2].chunk.id == "c2"
    assert results[2].score == 0.1


def test_reranker_min_score_filtering(sample_chunks):
    mock_scores = {"hash_password": 0.9, "verify_jwt": 0.5, "get_user": 0.1}
    reranker = CrossEncoderReRanker(model=MockCrossEncoderModel(score_map=mock_scores))

    # Filter candidates with score < 0.4
    results = reranker.rerank("hashing password", sample_chunks, top_k=5, min_score=0.4)
    assert len(results) == 2
    assert results[0].chunk.id == "c3"
    assert results[1].chunk.id == "c1"


def test_reranker_fallback_on_exception(sample_chunks):
    # Model throws exception on predict
    error_model = MockCrossEncoderModel(raise_error=True)
    reranker = CrossEncoderReRanker(model=error_model)

    # Should not crash, but return graceful fallback
    results = reranker.rerank("test query", sample_chunks, top_k=2)
    assert len(results) == 2
    assert results[0].chunk.id == "c1"
    assert results[1].chunk.id == "c2"


def test_reranker_top_k_truncation(sample_chunks):
    mock_scores = {"hash_password": 0.9, "verify_jwt": 0.5, "get_user": 0.1}
    reranker = CrossEncoderReRanker(model=MockCrossEncoderModel(score_map=mock_scores))

    results = reranker.rerank("password hashing", sample_chunks, top_k=1)
    assert len(results) == 1
    assert results[0].chunk.id == "c3"


def test_reranker_empty_chunks():
    reranker = CrossEncoderReRanker(model=MockCrossEncoderModel())
    results = reranker.rerank("query", [], top_k=5)
    assert results == []


def test_hybrid_retriever_integration_with_reranker(sample_chunks):
    mock_scores = {
        "get_user": 0.95,
        "verify_jwt": 0.1,
        "hash_password": 0.05,
    }
    mock_reranker = CrossEncoderReRanker(model=MockCrossEncoderModel(score_map=mock_scores))

    retriever = HybridRetriever(chunks=sample_chunks, reranker=mock_reranker)

    normal_results = retriever.retrieve("jwt token verification", top_k=3, rerank=False)
    assert normal_results[0].chunk.id == "c1"

    reranked_results = retriever.retrieve("jwt token verification", top_k=3, rerank=True)
    assert reranked_results[0].chunk.id == "c2"
    assert reranked_results[0].score == 0.95


@pytest.mark.integration
def test_real_cross_encoder_reranker(sample_chunks):
    """
    Integration test verifying real sentence-transformers CrossEncoder.
    """
    reranker = CrossEncoderReRanker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    results = reranker.rerank("hash password bcrypt", sample_chunks, top_k=2)

    assert len(results) == 2
    assert results[0].chunk.id == "c3"
