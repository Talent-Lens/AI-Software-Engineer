import pytest
from src.schema import Chunk
from src.retrieval.bm25 import BM25Indexer, tokenize_code
from src.retrieval.retriever import (
    HybridRetriever,
    compute_rrf_scores,
)


def test_tokenize_code():
    text = "def calculate_total_amount(userAccount, price_usd_2026): pass"
    tokens = tokenize_code(text)

    # Must contain full tokens and sub-tokens
    assert "calculate_total_amount" in tokens
    assert "calculate" in tokens
    assert "total" in tokens
    assert "amount" in tokens
    assert "useraccount" in tokens
    assert "user" in tokens
    assert "account" in tokens
    assert "price" in tokens
    assert "usd" in tokens


def test_bm25_indexer():
    chunk1 = Chunk(
        id="chunk_1",
        file_path="src/math.py",
        start_line=1,
        end_line=10,
        type="function",
        name="compute_fibonacci",
        code="def compute_fibonacci(n):\n    if n <= 1: return n\n    return compute_fibonacci(n-1) + compute_fibonacci(n-2)",
    )
    chunk2 = Chunk(
        id="chunk_2",
        file_path="src/db.py",
        start_line=1,
        end_line=5,
        type="function",
        name="connect_to_database",
        code="def connect_to_database(db_url):\n    return f'Connecting to {db_url}'",
    )

    indexer = BM25Indexer([chunk1, chunk2])

    # Query for exact keyword 'fibonacci'
    results = indexer.search("fibonacci", top_k=2)
    assert len(results) >= 1
    top_chunk, score, rank = results[0]
    assert top_chunk.id == "chunk_1"
    assert rank == 1
    assert score > 0.0

    # Query for exact keyword 'database'
    db_results = indexer.search("database", top_k=2)
    assert len(db_results) >= 1
    assert db_results[0][0].id == "chunk_2"


def test_compute_rrf_scores():
    chunk_a = Chunk(id="a", file_path="a.py", start_line=1, end_line=5, type="function", name="func_a", code="pass")
    chunk_b = Chunk(id="b", file_path="b.py", start_line=1, end_line=5, type="function", name="func_b", code="pass")
    chunk_c = Chunk(id="c", file_path="c.py", start_line=1, end_line=5, type="function", name="func_c", code="pass")

    # Vector rank: a=1, b=2
    vector_ranked = [(chunk_a, 0.1, 1), (chunk_b, 0.4, 2)]
    # BM25 rank: b=1, c=2
    bm25_ranked = [(chunk_b, 5.0, 1), (chunk_c, 2.0, 2)]

    k = 60
    fused = compute_rrf_scores(vector_ranked, bm25_ranked, k=k)

    # Expected RRF scores:
    # a: 1/(60+1) = 1/61 ~ 0.016393
    # b: 1/(60+2) + 1/(60+1) = 1/62 + 1/61 ~ 0.032522
    # c: 1/(60+2) = 1/62 ~ 0.016129
    #
    # Top rank should be chunk_b because it appears in both lists!
    assert fused[0][0].id == "b"
    assert abs(fused[0][1] - (1.0 / 61 + 1.0 / 62)) < 1e-6

    assert fused[1][0].id == "a"
    assert fused[2][0].id == "c"


def test_hybrid_retriever_without_collection():
    chunk1 = Chunk(
        id="c1",
        file_path="auth.py",
        start_line=1,
        end_line=20,
        type="function",
        name="verify_jwt_token",
        code="def verify_jwt_token(token, secret_key):\n    return jwt.decode(token, secret_key)",
    )
    chunk2 = Chunk(
        id="c2",
        file_path="user.py",
        start_line=1,
        end_line=15,
        type="function",
        name="get_user_profile",
        code="def get_user_profile(user_id):\n    return db.query(User).filter_by(id=user_id).first()",
    )

    retriever = HybridRetriever(chunks=[chunk1, chunk2])
    results = retriever.retrieve(query="jwt token verification", top_k=2)

    assert len(results) == 2
    assert results[0].chunk.id == "c1"
    assert results[0].query == "jwt token verification"
    assert results[0].score > 0
