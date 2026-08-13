"""
Incremental Git Indexing Engine Module — Production Enterprise Edition.
Task: TASK-R5 (Incremental Git Indexing)

Uses gitpython to inspect repository diffs and incrementally update ChromaDB
and BM25 indices for modified, added, deleted, and renamed files.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Sequence, cast

import git
from src.indexing.chunker import chunk_file
from src.indexing.vector_store import get_collection
from src.schema import Chunk

logger = logging.getLogger("ai_engineer.indexing.git_indexer")

SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go"}


def is_supported_file(file_path: str) -> bool:
    """Checks if file extension is supported for chunking."""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


class GitIncrementalIndexer:
    """
    Incremental Git Indexing Engine.
    Tracks file diffs via Git and incrementally updates ChromaDB collections and BM25 indices.
    """

    def __init__(
        self,
        repo_path: str | Path,
        collection: Any | None = None,
        collection_name: str = "repo_index",
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        if not (self.repo_path / ".git").exists():
            raise ValueError(f"Path '{self.repo_path}' is not a valid Git repository.")

        self.repo = git.Repo(self.repo_path)
        self.collection_name = collection_name
        self.collection = collection or get_collection(name=collection_name)

    def _normalize_path(self, raw_path: str) -> str:
        """Standardizes file paths to relative path string using forward slashes."""
        rel = os.path.relpath(os.path.join(self.repo_path, raw_path), self.repo_path)
        return rel.replace("\\", "/")

    def get_changed_files(
        self,
        since_commit: str | None = None,
        compare_against: str = "HEAD",
    ) -> dict[str, list[str]]:
        """
        Detects added, modified, deleted, and renamed files using Git diffs.

        Args:
            since_commit: Optional commit hash or ref to compare against.
                          If None, checks uncommitted local working tree changes.
            compare_against: Ref to compare since_commit against (default 'HEAD').

        Returns:
            Dict containing lists of normalized relative file paths for each change type:
            {"added": [...], "modified": [...], "deleted": [...], "renamed": [...]}
        """
        changed: dict[str, set[str]] = {
            "added": set(),
            "modified": set(),
            "deleted": set(),
            "renamed": set(),
        }

        try:
            if since_commit:
                # Compare specified commit against compare_against (e.g., HEAD)
                diffs = self.repo.commit(since_commit).diff(compare_against)
                for diff_item in diffs:
                    change_type = diff_item.change_type  # 'A', 'M', 'D', 'R'
                    path = diff_item.b_path or diff_item.a_path
                    if path and is_supported_file(path):
                        norm_path = self._normalize_path(path)
                        if change_type == "A":
                            changed["added"].add(norm_path)
                        elif change_type == "M":
                            changed["modified"].add(norm_path)
                        elif change_type == "D":
                            changed["deleted"].add(norm_path)
                        elif change_type == "R":
                            changed["renamed"].add(norm_path)
                            if diff_item.a_path:
                                changed["deleted"].add(self._normalize_path(diff_item.a_path))
                            if diff_item.b_path:
                                changed["added"].add(self._normalize_path(diff_item.b_path))
            else:
                # Check uncommitted changes (working tree + index + untracked)
                # 1. Unstaged changes in working tree
                for diff_item in self.repo.index.diff(None):
                    path = diff_item.b_path or diff_item.a_path
                    if path and is_supported_file(path):
                        norm_path = self._normalize_path(path)
                        if diff_item.change_type == "D":
                            changed["deleted"].add(norm_path)
                        else:
                            changed["modified"].add(norm_path)

                # 2. Staged changes
                if self.repo.head.is_valid():
                    for diff_item in self.repo.head.commit.diff():
                        path = diff_item.b_path or diff_item.a_path
                        if path and is_supported_file(path):
                            norm_path = self._normalize_path(path)
                            if diff_item.change_type == "A":
                                changed["added"].add(norm_path)
                            elif diff_item.change_type == "D":
                                changed["deleted"].add(norm_path)
                            else:
                                changed["modified"].add(norm_path)

                # 3. Untracked files
                for untracked in self.repo.untracked_files:
                    if is_supported_file(untracked):
                        changed["added"].add(self._normalize_path(untracked))

        except Exception as err:
            logger.error("Git diff detection failed: %s", err)
            raise err

        return {k: sorted(list(v)) for k, v in changed.items()}

    def _delete_chunks_by_file_paths(self, file_paths: list[str]) -> int:
        """
        Deletes all chunks in ChromaDB associated with specified file paths.
        Returns count of deleted chunks.
        """
        if not file_paths:
            return 0

        deleted_count = 0
        for path in file_paths:
            try:
                # Retrieve matching IDs first to verify deletion count
                existing = self.collection.get(where={"file_path": path})
                ids_to_del = existing.get("ids") or []
                if ids_to_del:
                    self.collection.delete(ids=ids_to_del)
                    deleted_count += len(ids_to_del)
                    logger.debug("Deleted %d stale chunks for file: %s", len(ids_to_del), path)
            except Exception as err:
                logger.warning("Failed to delete chunks for path '%s': %s", path, err)

        return deleted_count

    def index_incremental(
        self,
        since_commit: str | None = None,
        compare_against: str = "HEAD",
        retriever: Any | None = None,
    ) -> dict[str, Any]:
        """
        Performs incremental re-indexing by processing only Git-modified/added/deleted files.

        Args:
            since_commit: Commit ref to compare against (None for working tree changes).
            compare_against: Ref to compare since_commit against (default 'HEAD').
            retriever: Optional HybridRetriever instance to synchronize BM25 index.

        Returns:
            Dict containing performance latency and indexing statistics.
        """
        start_time = time.perf_counter()
        changed_files = self.get_changed_files(since_commit, compare_against)

        added_files = changed_files["added"]
        modified_files = changed_files["modified"]
        deleted_files = changed_files["deleted"]

        # 1. Purge stale chunks for deleted and modified files
        files_to_purge = list(set(deleted_files + modified_files))
        chunks_deleted = self._delete_chunks_by_file_paths(files_to_purge)

        # 2. Chunk & index added and modified files
        files_to_index = list(set(added_files + modified_files))
        new_chunks: list[Chunk] = []

        for rel_path in files_to_index:
            abs_path = self.repo_path / rel_path
            if abs_path.exists() and abs_path.is_file():
                try:
                    file_chunks = chunk_file(str(abs_path))
                    # Standardize chunk file_path metadata to relative path
                    for c in file_chunks:
                        c.file_path = rel_path
                    new_chunks.extend(file_chunks)
                except Exception as err:
                    logger.warning("Skipped chunking '%s': %s", rel_path, err)

        # 3. Insert new chunks into ChromaDB
        if new_chunks:
            self.collection.add(
                documents=[c.code for c in new_chunks],
                ids=[c.id for c in new_chunks],
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
                    for c in new_chunks
                ],
            )
            logger.info("Added %d new chunks to collection '%s'.", len(new_chunks), self.collection_name)

        # 4. Sync BM25 index if retriever is passed
        if retriever is not None and hasattr(retriever, "sync_bm25"):
            try:
                retriever.sync_bm25()
                logger.info("Synchronized BM25 indexer.")
            except Exception as err:
                logger.warning("Failed to sync BM25 indexer: %s", err)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        summary = {
            "status": "success",
            "latency_ms": round(latency_ms, 2),
            "files": {
                "added": len(added_files),
                "modified": len(modified_files),
                "deleted": len(deleted_files),
                "renamed": len(changed_files["renamed"]),
            },
            "chunks": {
                "deleted": chunks_deleted,
                "added": len(new_chunks),
            },
        }

        logger.info(
            "Incremental Git Indexing complete in %.2f ms. Added %d chunks, Deleted %d chunks.",
            latency_ms,
            len(new_chunks),
            chunks_deleted,
        )
        return summary


__all__ = ["GitIncrementalIndexer", "is_supported_file"]
