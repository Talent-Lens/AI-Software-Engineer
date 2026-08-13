"""
Unit & Integration Tests for TASK-R7 (Codebase GraphRAG via NetworkX)
"""
from __future__ import annotations

import pytest
from src.schema import Chunk, RetrievalResult
from src.retrieval.graph_rag import (
    CodebaseGraph,
    GraphRetriever,
    build_codebase_graph,
    parse_class_inheritance,
    parse_symbol_calls,
)
from src.retrieval.retriever import HybridRetriever


def test_parse_class_inheritance():
    py_chunk = Chunk(
        id="c1",
        file_path="models.py",
        start_line=1,
        end_line=10,
        type="class",
        name="User",
        code="class User(BaseModel, AuthMixin):\n    pass",
    )
    parents = parse_class_inheritance(py_chunk)
    assert "BaseModel" in parents
    assert "AuthMixin" in parents

    ts_chunk = Chunk(
        id="c2",
        file_path="service.ts",
        start_line=1,
        end_line=5,
        type="class",
        name="UserService",
        code="class UserService extends BaseService {\n}",
    )
    ts_parents = parse_class_inheritance(ts_chunk)
    assert ts_parents == ["BaseService"]


def test_parse_symbol_calls():
    chunk = Chunk(
        id="c1",
        file_path="auth.py",
        start_line=1,
        end_line=5,
        type="function",
        name="login",
        code="def login(user):\n    validate_credentials(user)\n    return generate_token(user)",
    )
    symbols = {"validate_credentials", "generate_token", "unrelated_func"}
    calls = parse_symbol_calls(chunk, symbols)

    assert "validate_credentials" in calls
    assert "generate_token" in calls
    assert "unrelated_func" not in calls


def test_build_codebase_graph():
    base_class = Chunk(
        id="base_1",
        file_path="base.py",
        start_line=1,
        end_line=10,
        type="class",
        name="BaseModel",
        code="class BaseModel:\n    pass",
    )
    child_class = Chunk(
        id="child_1",
        file_path="user.py",
        start_line=1,
        end_line=15,
        type="class",
        name="User",
        code="class User(BaseModel):\n    def get_name(self):\n        return self.name",
        imports=["from base import BaseModel"],
    )

    graph = build_codebase_graph([base_class, child_class])

    assert graph.graph.has_node("base_1")
    assert graph.graph.has_node("child_1")
    # Inheritance edge child_1 -> base_1
    assert graph.graph.has_edge("child_1", "base_1")
    assert graph.graph.edges["child_1", "base_1"]["relation"] == "INHERITS_FROM"
    assert "INHERITS_FROM" in graph.graph.edges["child_1", "base_1"]["relations"]
    assert "CALLS" in graph.graph.edges["child_1", "base_1"]["relations"]


def test_import_resolution():
    helper_chunk = Chunk(
        id="h1",
        file_path="utils.py",
        start_line=1,
        end_line=5,
        type="function",
        name="format_date",
        code="def format_date(d):\n    return str(d)",
    )
    main_chunk = Chunk(
        id="m1",
        file_path="main.py",
        start_line=1,
        end_line=10,
        type="function",
        name="run",
        code="def run():\n    return format_date('2026')",
        imports=["from utils import format_date"],
    )

    graph = build_codebase_graph([helper_chunk, main_chunk])
    assert graph.graph.has_edge("m1", "h1")
    rel_set = graph.graph.edges["m1", "h1"]["relations"]
    assert "IMPORTS" in rel_set or "CALLS" in rel_set


def test_graph_context_expansion():
    c_base = Chunk(
        id="base_id",
        file_path="db.py",
        start_line=1,
        end_line=10,
        type="class",
        name="DatabaseConnection",
        code="class DatabaseConnection:\n    def connect(self): pass",
    )
    c_child = Chunk(
        id="child_id",
        file_path="user_db.py",
        start_line=1,
        end_line=15,
        type="class",
        name="UserDatabase",
        code="class UserDatabase(DatabaseConnection):\n    pass",
    )

    graph = build_codebase_graph([c_base, c_child])

    # Seed is child class
    expanded = graph.expand_context(seed_chunks=[c_child], max_depth=1)

    assert len(expanded) == 2
    expanded_ids = [c.id for c in expanded]
    assert "child_id" in expanded_ids
    assert "base_id" in expanded_ids


def test_graph_retriever_end_to_end():
    c1 = Chunk(
        id="auth_id",
        file_path="auth.py",
        start_line=1,
        end_line=10,
        type="function",
        name="authenticate_user",
        code="def authenticate_user(username, password):\n    return check_db_user(username)",
    )
    c2 = Chunk(
        id="db_id",
        file_path="db.py",
        start_line=1,
        end_line=10,
        type="function",
        name="check_db_user",
        code="def check_db_user(username):\n    return True",
    )

    hybrid_retriever = HybridRetriever(chunks=[c1, c2])
    graph_retriever = GraphRetriever(hybrid_retriever=hybrid_retriever)

    # Search query targeting authenticate_user
    results = graph_retriever.retrieve("authenticate user credentials", top_k=1, enable_graph_expansion=True)

    # Should return seed chunk (c1) + expanded call dependency chunk (c2)
    assert len(results) >= 2
    res_ids = [r.chunk.id for r in results]
    assert "auth_id" in res_ids
    assert "db_id" in res_ids

    # Expanded chunk should have distance score 0.60 (0.85 - 0.25 * 1)
    expanded_res = [r for r in results if r.chunk.id == "db_id"][0]
    assert expanded_res.score == 0.60

