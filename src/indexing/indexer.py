"""
Repository Indexer Module — Full & Incremental Indexing Interfaces.
Tasks: TASK-R1, TASK-R3, TASK-R5
"""
from __future__ import annotations

import json
import os
from typing import Any
from src.indexing.chunker import chunk_file
from src.indexing.git_indexer import GitIncrementalIndexer, SUPPORTED_EXTENSIONS
from src.indexing.vector_store import get_collection


def get_repository_files(folder_path: str) -> list[str]:
    """Finds all supported source code files in a folder path."""
    repo_files = []
    for root, _, files in os.walk(folder_path):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                repo_files.append(os.path.join(root, f))
    return repo_files


def index_repository(folder_path: str, reset: True = True, collection_name: str = "repo_index") -> Any:
    """
    Performs full repository indexing from scratch.
    """
    collection = get_collection(name=collection_name, reset=reset)
    repo_files = get_repository_files(folder_path)

    all_chunks = []
    for path in repo_files:
        try:
            chunks = chunk_file(path)
            # Store relative file path in metadata
            rel_path = os.path.relpath(path, folder_path).replace("\\", "/")
            for c in chunks:
                c.file_path = rel_path
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"Skipped {path}: {e}")

    if not all_chunks:
        print("No chunks found.")
        return collection

    collection.add(
        documents=[c.code for c in all_chunks],
        ids=[c.id for c in all_chunks],
        metadatas=[
            {
                "file_path": c.file_path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "type": c.type,
                "name": c.name,
                "parent_name": c.parent_name or "",
                "imports": json.dumps(c.imports),
            }
            for c in all_chunks
        ],
    )
    print(f"Indexed {len(all_chunks)} chunks from {len(repo_files)} files.")
    return collection


def index_repository_incremental(
    folder_path: str,
    since_commit: str | None = None,
    collection_name: str = "repo_index",
    collection: Any | None = None,
    retriever: Any | None = None,
) -> dict[str, Any]:
    """
    Performs incremental repository re-indexing using Git diffs.
    Only updates modified, added, deleted, or renamed files.
    """
    indexer = GitIncrementalIndexer(
        repo_path=folder_path,
        collection=collection,
        collection_name=collection_name,
    )
    return indexer.index_incremental(since_commit=since_commit, retriever=retriever)


def search(collection: Any, query: str, n_results: int = 5) -> None:
    """Helper CLI search function for testing collection results."""
    results = collection.query(query_texts=[query], n_results=n_results)
    if not results or not results.get("documents") or not results["documents"][0]:
        print("No results found.")
        return

    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        parent_info = f" (in {meta['parent_name']})" if meta.get("parent_name") else ""
        print(
            f"\n[{meta['type']}] {meta['name']}{parent_info} — {meta['file_path']} "
            f"(lines {meta['start_line']}-{meta['end_line']}, distance={dist:.3f})"
        )
        print(doc[:200], "...")


__all__ = [
    "get_repository_files",
    "index_repository",
    "index_repository_incremental",
    "search",
    "SUPPORTED_EXTENSIONS",
]