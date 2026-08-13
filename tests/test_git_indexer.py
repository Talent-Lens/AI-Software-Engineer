"""
Unit & Integration Tests for TASK-R5 (Incremental Git Indexing Engine)
"""
from __future__ import annotations

import os
import shutil
import pytest
import git
from pathlib import Path

from src.indexing.git_indexer import GitIncrementalIndexer, is_supported_file
from src.indexing.indexer import index_repository, index_repository_incremental
from src.indexing.vector_store import get_collection
from src.retrieval.retriever import HybridRetriever


@pytest.fixture
def git_repo_dir(tmp_path: Path) -> Path:
    """
    Creates a temporary Git repository with initial commits for testing.
    """
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()

    repo = git.Repo.init(repo_dir)
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test Engineer")
        config.set_value("user", "email", "test@ai-engineer.com")

    # Initial files
    f1 = repo_dir / "math_utils.py"
    f1.write_text("def compute_square(x):\n    return x * x\n", encoding="utf-8")

    f2 = repo_dir / "auth_service.py"
    f2.write_text("def verify_user(user_id):\n    return True\n", encoding="utf-8")

    repo.index.add(["math_utils.py", "auth_service.py"])
    repo.index.commit("Initial commit")

    return repo_dir


def test_is_supported_file():
    assert is_supported_file("src/main.py") is True
    assert is_supported_file("components/App.tsx") is True
    assert is_supported_file("service/User.java") is True
    assert is_supported_file("README.md") is False
    assert is_supported_file("build.log") is False


def test_git_indexer_diff_detection(git_repo_dir: Path):
    indexer = GitIncrementalIndexer(repo_path=git_repo_dir)

    # 1. Add a new file
    f3 = git_repo_dir / "payment.py"
    f3.write_text("def process_payment(amount):\n    return True\n", encoding="utf-8")

    # 2. Modify math_utils.py
    f1 = git_repo_dir / "math_utils.py"
    f1.write_text("def compute_square(x):\n    return x * x\n\ndef add_numbers(a, b):\n    return a + b\n", encoding="utf-8")

    # 3. Delete auth_service.py
    f2 = git_repo_dir / "auth_service.py"
    if f2.exists():
        os.remove(f2)

    # Detect uncommitted working tree changes
    changed = indexer.get_changed_files()
    assert "payment.py" in changed["added"]
    assert "math_utils.py" in changed["modified"]
    assert "auth_service.py" in changed["deleted"]


def test_incremental_indexing_chromadb(git_repo_dir: Path):
    collection_name = "test_git_chroma_idx"

    # Initial full index
    collection = index_repository(str(git_repo_dir), reset=True, collection_name=collection_name)
    initial_chunks = collection.get()
    assert len(initial_chunks["ids"]) >= 2

    # Make working tree changes
    f_new = git_repo_dir / "crypto.py"
    f_new.write_text("def encrypt_data(data):\n    return f'encrypted_{data}'\n", encoding="utf-8")

    f_auth = git_repo_dir / "auth_service.py"
    if f_auth.exists():
        os.remove(f_auth)

    # Run incremental indexing
    indexer = GitIncrementalIndexer(repo_path=git_repo_dir, collection_name=collection_name)
    summary = indexer.index_incremental()

    assert summary["status"] == "success"
    assert summary["files"]["added"] == 1
    assert summary["files"]["deleted"] == 1
    assert summary["latency_ms"] < 2000.0  # Sub-second / sub-2-second target

    # Verify ChromaDB contents after incremental sync
    updated_data = collection.get()
    metas = updated_data.get("metadatas") or []
    file_paths = [m["file_path"] for m in metas]

    assert "crypto.py" in file_paths
    assert "auth_service.py" not in file_paths


def test_incremental_indexing_with_commit_ref(git_repo_dir: Path):
    collection_name = "test_git_commit_idx"
    collection = index_repository(str(git_repo_dir), reset=True, collection_name=collection_name)

    repo = git.Repo(git_repo_dir)
    initial_commit = str(repo.head.commit.hexsha)

    # Commit a new change
    f_new = git_repo_dir / "analytics.py"
    f_new.write_text("def track_event(event_name):\n    pass\n", encoding="utf-8")
    repo.index.add(["analytics.py"])
    new_commit = repo.index.commit("Add analytics.py")

    # Incrementally index changes between initial_commit and HEAD
    summary = index_repository_incremental(
        folder_path=str(git_repo_dir),
        since_commit=initial_commit,
        collection_name=collection_name,
    )

    assert summary["status"] == "success"
    assert summary["files"]["added"] == 1

    updated_data = collection.get()
    metas = updated_data.get("metadatas") or []
    file_paths = [m["file_path"] for m in metas]
    assert "analytics.py" in file_paths
